from datetime import datetime
from app.core.google_auth import get_service
from app.config import TENANTS

async def log_lead_bg(agent_id: str, data: dict):
    tenant = TENANTS.get(agent_id)
    try:
        service = get_service('sheets', 'v4', tenant['creds_file'])
        row = [datetime.now().isoformat(), data['cliente_nombre'], data['cliente_telefono'], "Caliente", "Agendado"]
        service.spreadsheets().values().append(
            spreadsheetId=tenant['sheet_crm_id'], range="Leads!A:E",
            valueInputOption="USER_ENTERED", body={'values': [row]}
        ).execute()
    except Exception as e:
        print(f"Error CRM: {e}")