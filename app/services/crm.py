from datetime import datetime
import pytz
from app.core.google_auth import get_service
from app.config import TENANTS

BOGOTA_TZ = pytz.timezone('America/Bogota')

async def log_lead_bg(agent_id: str, data: dict):
    print(f"📝 CRM Log Start: {agent_id}")
    tenant = TENANTS.get(agent_id)
    if not tenant: return

    try:
        service = get_service('sheets', 'v4', tenant['creds_file'])
        
        now_bogota = datetime.now(BOGOTA_TZ)
        fecha = now_bogota.strftime("%Y-%m-%d")
        hora = now_bogota.strftime("%I:%M %p")
        
        clasificacion = "Caliente" if data.get('fecha_hora_inicio') else "Tibio"
        estado = "Agendado" if data.get('fecha_hora_inicio') else "Interesado"

        # Col F es para el Asesor
        row_values = [
            fecha,
            hora,
            data.get('cliente_nombre', 'Desconocido'),
            data.get('cliente_telefono', 'No provisto'),
            data.get('cliente_email', 'No provisto'),
            data.get('propiedad_interes', 'General'),
            data.get('asesor_nombre', 'General'), # <--- CAMPO NUEVO
            clasificacion,
            estado
        ]

        body = {'values': [row_values]}
        
        service.spreadsheets().values().append(
            spreadsheetId=tenant['sheet_crm_id'],
            range="Leads!A:H", # Rango ampliado
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body
        ).execute()
        print(f"✅ Lead guardado con Asesor: {data.get('asesor_nombre')}")
        
    except Exception as e:
        print(f"❌ Error CRM: {e}")