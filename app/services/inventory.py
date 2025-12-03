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
    
    # --- FASE 1: LEER DATOS (Redis o Sheets) ---
    cached_json = await redis_client.get(cache_key)
    df = None

    if cached_json:
        try:
            df = pd.read_json(io.StringIO(cached_json), orient='records')
            if 'precio_total_cop' not in df.columns: # Validación básica
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
            
            # RENOMBRADO INTELIGENTE (Separando Venta de Arriendo)
            for col in df.columns:
                if 'parqueadero' in col: continue # Ignorar columnas de parqueadero
                
                # 1. Identificar Tipo de Operación
                if 'operacion' in col or 'modalidad' in col:
                    df.rename(columns={col: 'tipo_operacion'}, inplace=True)

                # 2. Identificar Precio Venta
                elif ('precio' in col and 'cop' in col) or ('venta' in col and 'valor' in col): 
                    df.rename(columns={col: 'precio_total_cop'}, inplace=True)
                
                # 3. Identificar Canon (Arriendo)
                elif 'canon' in col: 
                    df.rename(columns={col: 'canon_mensual_cop'}, inplace=True)
                
                # 4. Identificar Administración
                elif 'administracion' in col or 'admin' in col: 
                    df.rename(columns={col: 'valor_admin_cop'}, inplace=True)

            # --- LIMPIEZA NUMÉRICA ---
            # Función helper para limpiar dinero
            def clean_money(val):
                return pd.to_numeric(str(val).replace('$', '').replace('.', '').replace(',', '').replace(' ', ''), errors='coerce')

            if 'precio_total_cop' in df.columns:
                df['precio_total_cop'] = df['precio_total_cop'].apply(clean_money)
            
            if 'canon_mensual_cop' in df.columns:
                df['canon_mensual_cop'] = df['canon_mensual_cop'].apply(clean_money)
                
            if 'valor_admin_cop' in df.columns:
                df['valor_admin_cop'] = df['valor_admin_cop'].apply(clean_money).fillna(0) # Si es NaN, es 0

            # Guardar en Redis
            await redis_client.setex(cache_key, 300, df.to_json(orient='records'))

        except Exception as e:
            print(f"❌ Error Sheets: {e}")
            return "Error técnico en base de datos."

    # --- FASE 2: FILTRADO INTELIGENTE ---
    try:
        results = df.copy()

        # 1. FILTRO TIPO DE OPERACIÓN (Vital)
        operacion_usuario = args.get('tipo_operacion', 'Venta') # Default a Venta si no especifican
        
        if 'tipo_operacion' in results.columns:
            # Filtro flexible (contiene "Venta" o "Arriendo")
            results = results[results['tipo_operacion'].astype(str).str.contains(operacion_usuario, case=False, na=False)]

        # 2. FILTRO PRESUPUESTO (Depende de la operación)
        presupuesto = args.get('presupuesto_max')
        
        if presupuesto:
            presupuesto = float(presupuesto)
            
            if operacion_usuario.lower() == 'arriendo':
                # Lógica Arriendo: Canon + Admin <= Presupuesto
                if 'canon_mensual_cop' in results.columns:
                    # Crear columna temporal de costo total mensual
                    val_admin = results['valor_admin_cop'] if 'valor_admin_cop' in results.columns else 0
                    results['costo_mensual_total'] = results['canon_mensual_cop'] + val_admin
                    
                    results = results[results['costo_mensual_total'] <= presupuesto]
            else:
                # Lógica Venta: Precio Total <= Presupuesto
                if 'precio_total_cop' in results.columns:
                    results = results[results['precio_total_cop'].notna()]
                    results = results[results['precio_total_cop'] <= presupuesto]

        # 3. FILTRO CIUDAD
        if args.get('ciudad') and 'ciudad' in results.columns:
            results = results[results['ciudad'].astype(str).str.contains(args['ciudad'], case=False, na=False)]

        if results.empty: return f"No encontré propiedades en {operacion_usuario} con esos criterios."
        
        # --- FASE 3: SELECCIÓN DE RESPUESTA ---
        # Definir qué columnas mostrar según lo que pidió el usuario
        campos_comunes = ['barrio', 'habitaciones', 'area_construida_m2', 'ciudad']
        
        if operacion_usuario.lower() == 'arriendo':
            campos_precio = ['canon_mensual_cop', 'valor_admin_cop']
        else:
            campos_precio = ['precio_total_cop']
            
        cols_to_show = [c for c in (campos_comunes + campos_precio) if c in results.columns]
        
        top_3 = results.head(3)[cols_to_show].to_dict(orient='records')
        return f"Encontré {len(results)} opciones en {operacion_usuario}. Aquí las mejores: {json.dumps(top_3)}"

    except Exception as e:
        print(f"❌ Error filtrando: {e}")
        return "Hubo un error procesando tu búsqueda."