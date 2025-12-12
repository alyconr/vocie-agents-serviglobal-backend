import json
import pandas as pd
import io
import unicodedata
from app.core.redis_client import redis_client
from app.core.google_auth import get_service
from app.config import TENANTS

# --- FUNCIÓN HELPER PARA NORMALIZAR TEXTO (Tildes y Mayúsculas) ---
def normalize_text(text):
    
    if not isinstance(text, str):
        return str(text)
    
    # 1. Normalizar unicode (separar caracteres de sus tildes)
    normalized = unicodedata.normalize('NFD', text)
    # 2. Filtrar solo caracteres no-diacríticos y pasar a minúsculas
    return "".join(c for c in normalized if unicodedata.category(c) != 'Mn').lower()

async def search_inventory(agent_id: str, args: dict):
    tenant = TENANTS.get(agent_id)
    if not tenant: return "Error: Agente no configurado."

    cache_key = f"inventory:{agent_id}"
    
    # --- FASE 1: LEER DATOS (Redis o Sheets) ---
    cached_json = await redis_client.get(cache_key)
    df = None

    if cached_json:
        try:
            df = pd.read_json(io.StringIO(cached_json), orient='records')
            if 'precio_total_cop' not in df.columns and 'canon_mensual_cop' not in df.columns:
                df = None 
        except Exception:
            df = None

    if df is None:
        try:
            # Descarga de Google Sheets
            service = get_service('sheets', 'v4', tenant['creds_file'])
            result = service.spreadsheets().values().get(
                spreadsheetId=tenant['sheet_inventory_id'], 
                range=tenant['inventory_range']
            ).execute()
            
            rows = result.get('values', [])
            if not rows: return "El inventario está vacío."
            
            # Buscar header
            header_idx = 0
            for i, row in enumerate(rows[:5]):
                row_str = str(row).lower()
                if 'precio' in row_str or 'barrio' in row_str or 'operacion' in row_str:
                    header_idx = i
                    break
            
            df = pd.DataFrame(rows[header_idx + 1:], columns=rows[header_idx])

            # --- NORMALIZACIÓN DE COLUMNAS ---
            df.columns = df.columns.astype(str).str.strip().str.lower()
            df.columns = df.columns.str.replace(' ', '_').str.replace('.', '')
            
            # RENOMBRADO INTELIGENTE
            for col in df.columns:
                if 'parqueadero' in col: continue
                
                if 'operacion' in col or 'modalidad' in col: df.rename(columns={col: 'tipo_operacion'}, inplace=True)
                elif ('precio' in col and 'cop' in col) or ('venta' in col and 'valor' in col): df.rename(columns={col: 'precio_total_cop'}, inplace=True)
                elif 'canon' in col: df.rename(columns={col: 'canon_mensual_cop'}, inplace=True)
                elif 'administracion' in col or 'admin' in col: df.rename(columns={col: 'valor_admin_cop'}, inplace=True)
                elif 'email' in col and 'asesor' in col: df.rename(columns={col: 'asesor_email'}, inplace=True)

            # Limpieza Duplicados
            df = df.loc[:, ~df.columns.duplicated()]

            # Limpieza Numérica
            def clean_money(val):
                return pd.to_numeric(str(val).replace('$', '').replace('.', '').replace(',', '').replace(' ', ''), errors='coerce')

            if 'precio_total_cop' in df.columns: df['precio_total_cop'] = df['precio_total_cop'].apply(clean_money)
            if 'canon_mensual_cop' in df.columns: df['canon_mensual_cop'] = df['canon_mensual_cop'].apply(clean_money)
            if 'valor_admin_cop' in df.columns: df['valor_admin_cop'] = df['valor_admin_cop'].apply(clean_money).fillna(0)

            await redis_client.setex(cache_key, 300, df.to_json(orient='records'))

        except Exception as e:
            print(f"❌ Error Sheets: {e}")
            return "Error técnico en base de datos."

    # --- FASE 2: FILTRADO ---
    try:
        results = df.copy()
        
        # 1. FILTRO CIUDAD (NORMALIZADO)
        # Aplicamos normalize_text a la columna del DataFrame Y al input del usuario
        if args.get('ciudad') and 'ciudad' in results.columns:
            ciudad_usuario = normalize_text(args['ciudad'])
            
            # Crear una serie temporal normalizada para filtrar
            # Esto evita modificar los datos originales (que queremos mostrar bonitos: "Bogotá")
            columna_normalizada = results['ciudad'].astype(str).apply(normalize_text)
            
            results = results[columna_normalizada.str.contains(ciudad_usuario, na=False)]

        # 2. FILTRO TIPO DE OPERACIÓN
        operacion_usuario = args.get('tipo_operacion', 'Venta')
        if 'tipo_operacion' in results.columns:
            # También normalizamos aquí por si acaso (Venta vs venta)
            op_normalizada = normalize_text(operacion_usuario)
            col_op_normalizada = results['tipo_operacion'].astype(str).apply(normalize_text)
            results = results[col_op_normalizada.str.contains(op_normalizada, na=False)]

        # 3. FILTRO PRESUPUESTO
        presupuesto = args.get('presupuesto_max')
        if presupuesto:
            presupuesto = float(presupuesto)
            if operacion_usuario.lower() == 'arriendo':
                if 'canon_mensual_cop' in results.columns:
                    val_admin = results['valor_admin_cop'] if 'valor_admin_cop' in results.columns else 0
                    results['costo_mensual_total'] = results['canon_mensual_cop'] + val_admin
                    results = results[results['costo_mensual_total'] <= presupuesto]
            else:
                if 'precio_total_cop' in results.columns:
                    results = results[results['precio_total_cop'].notna()]
                    results = results[results['precio_total_cop'] <= presupuesto]

        if results.empty: return f"No encontré propiedades en {operacion_usuario} con esos criterios."
        
        # --- FASE 3: RESPUESTA ---
        campos_comunes = ['barrio', 'habitaciones', 'area_construida_m2', 'ciudad', 'asesor_nombre', 'asesor_email', 'direccion']
        campos_precio = ['canon_mensual_cop', 'valor_admin_cop'] if operacion_usuario.lower() == 'arriendo' else ['precio_total_cop']
            
        cols_to_show = [c for c in (campos_comunes + campos_precio) if c in results.columns]
        
        # Obtenemos los registros crudos
        top_records = results.head(3)[cols_to_show].to_dict(orient='records')

        # FORMATEO FORZADO A PESOS
        for item in top_records:
            for key, val in item.items():
                if 'precio' in key or 'canon' in key or 'valor' in key:
                    try:
                        item[key] = f"$ {int(val):,.0f} COP".replace(",", ".")
                    except:
                        pass 

        return f"Encontré {len(results)} opciones. {json.dumps(top_records)}"

    except Exception as e:
        print(f"❌ Error filtrando: {e}")
        return "Hubo un error procesando tu búsqueda."