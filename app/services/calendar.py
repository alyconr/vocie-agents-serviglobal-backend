from datetime import datetime, timedelta
from app.config import TENANTS
from app.core.google_auth import get_service

async def check_availability(agent_id: str, date_str: str):
    # Mock para MVP. En fase 2 implementar events().list
    return "Tengo disponibilidad a las 9:00 AM, 11:00 AM y 3:00 PM."

async def create_event_and_lock(agent_id: str, data: dict):
    tenant = TENANTS.get(agent_id)
    service = get_service('calendar', 'v3', tenant['creds_file'])
    
    start_dt = datetime.fromisoformat(data['fecha_hora_inicio'])
    end_dt = start_dt + timedelta(hours=tenant['appointment_buffer_hours'])
    
    event = {
        'summary': f"CITA: {data['cliente_nombre']}",
        'description': f"Tel: {data['cliente_telefono']}\nInterés: {data.get('propiedad_interes')}",
        'start': {'dateTime': start_dt.isoformat(), 'timeZone': tenant['timezone']},
        'end': {'dateTime': end_dt.isoformat(), 'timeZone': tenant['timezone']},
        'attendees': [{'email': tenant['owner_email']}]
    }
    
    try:
        service.events().insert(calendarId=tenant['calendar_id'], body=event).execute()
        return True
    except Exception as e:
        print(f"Error Calendar: {e}")
        return False