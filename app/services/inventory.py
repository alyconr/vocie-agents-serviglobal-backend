import json
import pandas as pd
import io
from app.core.redis_client import redis_client
from app.core.google_auth import get_service
from app.config import TENANTS

async def search_inventory(agent_id: str, args: dict):
    tenant = TENANTS.get(agent_id)
    if not tenant: return "Error: Agente no configurado."

    cache_key = f"inventory:{agent_id}"
    
    # --- FASE 1: LEER DE REDIS CON VALIDACIÓN ---
    cached_json = await redis_client.get(cache_key)
    df = None

    if cached_json:
        try:
            df = pd.read_json(io.StringIO(cached_json), orient='records')
            if 'precio_total_cop' not in df.columns:
                print(f"⚠️ Cache corrupta o antigua detectada para {agent_id}. Forzando recarga...")
                df = None 
            else:
                print("⚡ Cache HIT: Datos válidos en memoria.")
        except Exception:
            df = None

    # --- FASE 2: DESCARGAR SI NO HAY CACHÉ VÁLIDA ---
    if df is None:
        print("🌐 Cache MISS: Descargando de Google Sheets...")
        try:
            service = get_service('sheets', 'v4', tenant['creds_file'])
            result = service.spreadsheets().values().get(
                spreadsheetId=tenant['sheet_inventory_id'], 
                range=tenant['inventory_range']
            ).execute()
            
            rows = result.get('values', [])
            if not rows: return "El inventario está vacío."
            
            # Búsqueda de encabezados
            header_idx = 0
            for i, row in enumerate(rows[:5]):
                row_str = str(row).lower()
                if 'precio' in row_str or 'barrio' in row_str or 'ciudad' in row_str:
                    header_idx = i
                    break
            
            df = pd.DataFrame(rows[header_idx + 1:], columns=rows[header_idx])

            # --- NORMALIZACIÓN DE COLUMNAS ---
            df.columns = df.columns.astype(str).str.strip().str.lower()
            df.columns = df.columns.str.replace(' ', '_').str.replace('.', '')
            
            # --- RENOMBRADO INTELIGENTE (CORREGIDO) ---
            for col in df.columns:
                # CORRECCIÓN: Si es algo de parqueadero, IGNORARLO
                if 'parqueadero' in col: 
                    continue

                if 'precio' in col and 'cop' not in col: df.rename(columns={col: 'precio_total_cop'}, inplace=True)
                elif 'valor' in col and 'total' in col: df.rename(columns={col: 'precio_total_cop'}, inplace=True)
                elif 'venta' in col: df.rename(columns={col: 'precio_total_cop'}, inplace=True)

            # --- CORRECCIÓN FINAL: ELIMINAR DUPLICADOS ---
            # Si por error quedaron dos columnas con el mismo nombre, nos quedamos con la primera
            df = df.loc[:, ~df.columns.duplicated()]

            print(f"📊 Columnas normalizadas: {df.columns.tolist()}")

            # --- LIMPIEZA DE DATOS ---
            if 'precio_total_cop' in df.columns:
                df['precio_total_cop'] = pd.to_numeric(
                    df['precio_total_cop'].astype(str).str.replace(r'[^\d]', '', regex=True), 
                    errors='coerce'
                )
            
            if 'habitaciones' in df.columns:
                df['habitaciones'] = pd.to_numeric(df['habitaciones'], errors='coerce')

            await redis_client.setex(cache_key, 300, df.to_json(orient='records'))

        except Exception as e:
            print(f"❌ Error Sheets: {e}")
            import traceback
            traceback.print_exc()
            return "Error técnico consultando la base de datos."

    # --- FASE 3: FILTRADO SEGURO ---
    try:
        results = df.copy()

        # 1. Filtro Presupuesto
        if args.get('presupuesto_max'):
            if 'precio_total_cop' in results.columns:
                results = results[results['precio_total_cop'].notna()]
                results = results[results['precio_total_cop'] <= float(args['presupuesto_max'])]
        
        # 2. Filtro Ciudad
        if args.get('ciudad') and 'ciudad' in results.columns:
            results = results[results['ciudad'].astype(str).str.contains(args['ciudad'], case=False, na=False)]

        if results.empty: return "No encontré propiedades con esos filtros."
        
        # --- FASE 4: SELECCIÓN DE CAMPOS ---
        campos_seguros = ['barrio', 'precio_total_cop', 'habitaciones', 'area_construida_m2', 'ciudad', 'tipo_inmueble', 'direccion']
        cols_to_show = [c for c in campos_seguros if c in results.columns]
        
        top_3 = results.head(3)[cols_to_show].to_dict(orient='records')
        return f"Encontré {len(results)} opciones. Aquí las mejores: {json.dumps(top_3)}"

    except Exception as e:
        print(f"❌ Error filtrando: {e}")
        return "Hubo un error procesando tu búsqueda."