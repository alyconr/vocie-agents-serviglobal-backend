from datetime import datetime, timedelta
import pytz
from app.config import TENANTS
from app.core.google_auth import get_service

BOGOTA_TZ = pytz.timezone('America/Bogota')

async def check_availability(agent_id: str, date_str: str):
    """
    Consulta huecos libres en Google Calendar.
    """
    tenant = TENANTS.get(agent_id)
    if not tenant: return "Error: Agente no configurado."

    try:
        service = get_service('calendar', 'v3', tenant['creds_file'])
        
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        start_of_day = BOGOTA_TZ.localize(datetime.combine(target_date, datetime.min.time().replace(hour=9)))
        end_of_day = BOGOTA_TZ.localize(datetime.combine(target_date, datetime.min.time().replace(hour=17)))

        body = {
            "timeMin": start_of_day.isoformat(),
            "timeMax": end_of_day.isoformat(),
            "timeZone": "America/Bogota",
            "items": [{"id": tenant['calendar_id']}]
        }
        
        events_result = service.freebusy().query(body=body).execute()
        busy_slots = events_result['calendars'][tenant['calendar_id']]['busy']

        available_slots = []
        current_slot = start_of_day
        
        while current_slot < end_of_day:
            slot_end = current_slot + timedelta(hours=1)
            is_busy = False
            for busy in busy_slots:
                busy_start = datetime.fromisoformat(busy['start'])
                busy_end = datetime.fromisoformat(busy['end'])
                if (current_slot < busy_end) and (slot_end > busy_start):
                    is_busy = True
                    break
            
            if not is_busy:
                available_slots.append(current_slot.strftime("%I:%M %p"))
            current_slot += timedelta(hours=1)

        if not available_slots:
            return "Lo siento, ese día está totalmente lleno."
            
        return f"Tengo disponibilidad a las: {', '.join(available_slots[:3])}."

    except Exception as e:
        print(f"❌ Error Availability: {e}")
        return "Tuve un problema consultando la agenda."

async def create_event_and_lock(agent_id: str, data: dict):
    """
    Intenta agendar. Si hay conflicto, retorna False.
    """
    tenant = TENANTS.get(agent_id)
    service = get_service('calendar', 'v3', tenant['creds_file'])
    
    try:
        dt_naive = datetime.fromisoformat(data['fecha_hora_inicio'])
        # Asumimos que la hora que llega es la deseada en local
        start_dt = BOGOTA_TZ.localize(dt_naive) if dt_naive.tzinfo is None else dt_naive
    except ValueError:
        return False

    buffer_hours = tenant.get('appointment_buffer_hours', 2)
    end_dt = start_dt + timedelta(hours=buffer_hours)

    # 1. VERIFICAR CONFLICTO
    events_check = service.events().list(
        calendarId=tenant['calendar_id'],
        timeMin=start_dt.isoformat(),
        timeMax=end_dt.isoformat(),
        singleEvents=True
    ).execute()

    if events_check.get('items'):
        return False # Ya está ocupado

    # 2. CREAR EVENTO CON ASESOR
    descripcion = f"""
    Cliente: {data['cliente_nombre']}
    Tel: {data['cliente_telefono']}
    Propiedad: {data.get('propiedad_interes')}
    ------------------
    ASESOR ASIGNADO: {data.get('asesor_nombre', 'No asignado')}
    """

    event = {
        'summary': f"CITA: {data['cliente_nombre']} - {data.get('propiedad_interes', 'General')}",
        'description': descripcion,
        'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'America/Bogota'},
        'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'America/Bogota'},
    }
    
    try:
        service.events().insert(calendarId=tenant['calendar_id'], body=event).execute()
        return True
    except Exception as e:
        print(f"Error Calendar Insert: {e}")
        return False