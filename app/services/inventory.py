import json
import pandas as pd
from app.core.redis_client import redis_client
from app.core.google_auth import get_service
from app.config import TENANTS

async def search_inventory(agent_id: str, args: dict):
    tenant = TENANTS.get(agent_id)
    if not tenant: return "Error: Agente no configurado."

    cache_key = f"inventory:{agent_id}"
    cached_json = await redis_client.get(cache_key)

    df = None
    if cached_json:
        df = pd.read_json(cached_json, orient='records')
    else:
        # Descarga de Google Sheets
        try:
            service = get_service('sheets', 'v4', tenant['creds_file'])
            result = service.spreadsheets().values().get(
                spreadsheetId=tenant['sheet_inventory_id'], range=tenant['inventory_range']
            ).execute()
            rows = result.get('values', [])
            if not rows: return "El inventario está vacío."
            
            df = pd.DataFrame(rows[1:], columns=rows[0])
            # Limpieza
            if 'precio_total_cop' in df.columns:
                df['precio_total_cop'] = pd.to_numeric(
                    df['precio_total_cop'].astype(str).str.replace(r'[$,.]', '', regex=True), errors='coerce'
                )
            await redis_client.setex(cache_key, 300, df.to_json(orient='records'))
        except Exception as e:
            print(f"Error Sheets: {e}")
            return "Error técnico consultando inventario."

    # Filtros
    results = df.copy()
    if args.get('ciudad'):
        results = results[results['ciudad'].astype(str).str.contains(args['ciudad'], case=False, na=False)]
    if args.get('presupuesto_max'):
        results = results[results['precio_total_cop'] <= args['presupuesto_max']]

    if results.empty: return "No encontré propiedades con esos criterios exactos."
    
    top_3 = results.head(3).to_dict(orient='records')
    return f"Encontré estas opciones: {json.dumps(top_3)}"