import json
import pandas as pd
import io
import unicodedata
from datetime import datetime
import pytz
from app.core.redis_client import redis_client
from app.core.google_auth import get_service
from app.config import TENANTS

# --- HELPER: NORMALIZAR TEXTO ---
def normalize_text(text):
    if not isinstance(text, str):
        return str(text)
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn").lower()

# --- HELPER CENTRALIZADO DE CARGA DE DATOS ---
async def _get_inventory_df(agent_id: str):
    """
    Carga, limpia y cachea el inventario. Retorna un DataFrame o None.
    """
    tenant = TENANTS.get(agent_id)
    if not tenant: return None

    cache_key = f"inventory:{agent_id}"
    df = None

    # 1. Intentar leer de Redis
    cached_json = await redis_client.get(cache_key)
    if cached_json:
        try:
            df = pd.read_json(io.StringIO(cached_json), orient="records")
            # Validación rápida de estructura
            if "precio_total_cop" not in df.columns and "canon_mensual_cop" not in df.columns:
                df = None
        except:
            df = None

    # 2. Si no hay cache o falló, leer de Google Sheets
    if df is None:
        try:
            service = get_service("sheets", "v4", tenant["creds_file"])
            result = service.spreadsheets().values().get(
                spreadsheetId=tenant["sheet_inventory_id"],
                range=tenant["inventory_range"],
            ).execute()

            rows = result.get("values", [])
            if not rows: return None

            # Detectar header dinámicamente
            header_idx = 0
            for i, row in enumerate(rows[:5]):
                row_str = str(row).lower()
                if "precio" in row_str or "barrio" in row_str or "operacion" in row_str:
                    header_idx = i
                    break

            df = pd.DataFrame(rows[header_idx + 1 :], columns=rows[header_idx])

            # Normalización de Columnas
            df.columns = df.columns.astype(str).str.strip().str.lower()
            df.columns = df.columns.str.replace(" ", "_").str.replace(".", "")

            for col in df.columns:
                if "parqueadero" in col: continue
                if "operacion" in col or "modalidad" in col: df.rename(columns={col: "tipo_operacion"}, inplace=True)
                elif "tipo" in col and "inmueble" in col: df.rename(columns={col: "tipo_inmueble"}, inplace=True)
                elif ("precio" in col and "cop" in col) or ("venta" in col and "valor" in col): df.rename(columns={col: "precio_total_cop"}, inplace=True)
                elif "canon" in col: df.rename(columns={col: "canon_mensual_cop"}, inplace=True)
                elif "administracion" in col or "admin" in col: df.rename(columns={col: "valor_admin_cop"}, inplace=True)
                elif "email" in col and "asesor" in col: df.rename(columns={col: "asesor_email"}, inplace=True)
                elif "calendario" in col and "id" in col: df.rename(columns={col: "asesor_calendar_id"}, inplace=True)

            # Agregar Metadata (Fecha ejecución)
            bogota_tz = pytz.timezone("America/Bogota")
            now_bogota = datetime.now(bogota_tz)
            df["fecha_ejecucion"] = now_bogota.strftime("%Y-%m-%d %I:%M %p")
            days = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            df["weekday"] = days[now_bogota.weekday()]

            # Limpieza de datos
            df = df.loc[:, ~df.columns.duplicated()]
            def clean_money(val):
                return pd.to_numeric(str(val).replace("$", "").replace(".", "").replace(",", "").replace(" ", ""), errors="coerce")

            if "precio_total_cop" in df.columns: df["precio_total_cop"] = df["precio_total_cop"].apply(clean_money)
            if "canon_mensual_cop" in df.columns: df["canon_mensual_cop"] = df["canon_mensual_cop"].apply(clean_money)
            if "valor_admin_cop" in df.columns: df["valor_admin_cop"] = df["valor_admin_cop"].apply(clean_money).fillna(0)

            # Guardar en Redis
            await redis_client.setex(cache_key, 300, df.to_json(orient="records"))

        except Exception as e:
            print(f"❌ Error cargando inventario: {e}")
            return None

    return df

# --- NUEVA FUNCIÓN PARA OBTENER CALENDARIOS ---
async def get_unique_calendar_ids(agent_id: str):
    """
    Retorna una lista de todos los IDs de calendario de asesores presentes en el inventario.
    """
    df = await _get_inventory_df(agent_id)
    if df is not None and "asesor_calendar_id" in df.columns:
        # Extraer únicos, eliminar vacíos y asegurar que parecen emails
        ids = df["asesor_calendar_id"].dropna().unique().tolist()
        return [str(x).strip() for x in ids if "@" in str(x)]
    return []

# --- FUNCIÓN PRINCIPAL DE BÚSQUEDA ---
async def search_inventory(agent_id: str, args: dict):
    df = await _get_inventory_df(agent_id)
    if df is None: return "Error técnico o inventario vacío."

    try:
        results = df.copy()
        
        # 1. Filtro Ciudad
        if args.get("ciudad") and "ciudad" in results.columns:
            ciudad = normalize_text(args["ciudad"])
            results = results[results["ciudad"].astype(str).apply(normalize_text).str.contains(ciudad, na=False)]

        # 2. Filtro Operación
        op = args.get("tipo_operacion", "Venta")
        if "tipo_operacion" in results.columns:
            op_norm = normalize_text(op)
            results = results[results["tipo_operacion"].astype(str).apply(normalize_text).str.contains(op_norm, na=False)]

        # 3. Filtro Zona
        if args.get("zona_ciudad") and "zona_ciudad" in results.columns:
            zona = normalize_text(args["zona_ciudad"])
            results = results[results["zona_ciudad"].astype(str).apply(normalize_text).str.contains(zona, na=False)]

        # 4. Filtro Tipo Inmueble
        if args.get("tipo_inmueble") and "tipo_inmueble" in results.columns:
            tipo = normalize_text(args["tipo_inmueble"])
            match_key = tipo
            if "apto" in tipo or "apartamento" in tipo: match_key = "apartamento"
            elif "casa" in tipo: match_key = "casa"
            elif "lote" in tipo or "terreno" in tipo: match_key = "lote"
            elif "bodega" in tipo: match_key = "bodega"
            elif "oficina" in tipo or "consultorio" in tipo: match_key = "oficina"
            
            results = results[results["tipo_inmueble"].astype(str).apply(normalize_text).str.contains(match_key, na=False)]

        # 5. Filtro Presupuesto
        presupuesto = args.get("presupuesto_max")
        if presupuesto:
            try:
                presupuesto = float(presupuesto)
                if op.lower() == "arriendo":
                    if "canon_mensual_cop" in results.columns:
                        canon = pd.to_numeric(results["canon_mensual_cop"], errors="coerce").fillna(0)
                        admin = pd.to_numeric(results.get("valor_admin_cop", 0), errors="coerce").fillna(0)
                        results = results[(canon + admin) <= presupuesto]
                else:
                    if "precio_total_cop" in results.columns:
                        precio = pd.to_numeric(results["precio_total_cop"], errors="coerce").fillna(0)
                        results = results[precio <= presupuesto]
            except: pass

        if results.empty: return f"No encontré propiedades en {op} con esos criterios."

        # Respuesta
        campos_comunes = ["barrio", "habitaciones", "banos", "parqueadero", "piso", "ascensor", "conjunto_cerrado", "mascotas", "area_construida_m2", "tipo_inmueble", "ciudad", "zona_ciudad", "asesor_nombre", "asesor_email", "asesor_calendar_id", "direccion", "fecha_ejecucion", "weekday"]
        campos_precio = ["canon_mensual_cop", "valor_admin_cop"] if op.lower() == "arriendo" else ["precio_total_cop"]
        
        cols = [c for c in (campos_comunes + campos_precio) if c in results.columns]
        top_records = results.head(3)[cols].to_dict(orient="records")

        # Formateo Pesos
        for item in top_records:
            for k, v in item.items():
                if any(x in k for x in ["precio", "canon", "valor"]) and isinstance(v, (int, float)):
                    item[k] = f"$ {int(v):,.0f} COP".replace(",", ".")

        return f"Encontré {len(results)} opciones. {json.dumps(top_records)}"

    except Exception as e:
        print(f"❌ Error filtrando: {e}")
        return "Hubo un error procesando tu búsqueda."