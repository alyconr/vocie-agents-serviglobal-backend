from datetime import datetime, timedelta
import pytz
from app.config import TENANTS
from app.core.google_auth import get_service

# Zona horaria fija para Colombia
BOGOTA_TZ = pytz.timezone('America/Bogota')

async def check_availability(agent_id: str, date_str: str):
    """
    Consulta los huecos libres en Google Calendar para una fecha específica (9 AM - 5 PM).
    """
    tenant = TENANTS.get(agent_id)
    if not tenant: return "Error: Agente no configurado."

    try:
        service = get_service('calendar', 'v3', tenant['creds_file'])
        
        # 1. Definir rango del día (9 AM a 5 PM hora Bogotá)
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        
        # Inicio del día de trabajo (09:00)
        start_of_day = BOGOTA_TZ.localize(datetime.combine(target_date, datetime.min.time().replace(hour=9)))
        # Fin del día de trabajo (17:00)
        end_of_day = BOGOTA_TZ.localize(datetime.combine(target_date, datetime.min.time().replace(hour=17)))

        # 2. Consultar 'freebusy' a Google (¿Qué está ocupado?)
        body = {
            "timeMin": start_of_day.isoformat(),
            "timeMax": end_of_day.isoformat(),
            "timeZone": "America/Bogota",
            "items": [{"id": tenant['calendar_id']}]
        }
        
        events_result = service.freebusy().query(body=body).execute()
        busy_slots = events_result['calendars'][tenant['calendar_id']]['busy']

        # 3. Calcular Huecos Libres (Algoritmo de Slots)
        # Asumimos citas de 1 hora por defecto para sugerir huecos
        available_slots = []
        current_slot = start_of_day
        
        while current_slot < end_of_day:
            slot_end = current_slot + timedelta(hours=1) # Duración tentativa 1h
            
            # Verificar si este slot choca con algún evento ocupado
            is_busy = False
            for busy in busy_slots:
                busy_start = datetime.fromisoformat(busy['start'])
                busy_end = datetime.fromisoformat(busy['end'])
                
                # Lógica de solapamiento
                if (current_slot < busy_end) and (slot_end > busy_start):
                    is_busy = True
                    break
            
            if not is_busy:
                # Formato amigable: "10:00 AM"
                available_slots.append(current_slot.strftime("%I:%M %p"))
            
            # Avanzar 1 hora
            current_slot += timedelta(hours=1)

        if not available_slots:
            return "Lo siento, ese día está totalmente lleno. ¿Revisamos otra fecha?"
            
        # Retornar máximo 3 opciones para no saturar la voz
        return f"Tengo disponibilidad a las: {', '.join(available_slots[:3])}."

    except Exception as e:
        print(f"❌ Error Checking Availability: {e}")
        return "Tuve un problema consultando la agenda, ¿me dices otra fecha?"

async def create_event_and_lock(agent_id: str, data: dict):
    """
    Intenta agendar. Si hay conflicto, falla y avisa.
    """
    tenant = TENANTS.get(agent_id)
    service = get_service('calendar', 'v3', tenant['creds_file'])
    
    # 1. Parsear fechas con zona horaria correcta
    try:
        # La fecha viene en ISO (ej: 2024-12-05T10:00:00)
        # Asumimos que Retell manda la hora "local" deseada, así que la localizamos a Bogotá
        dt_naive = datetime.fromisoformat(data['fecha_hora_inicio'])
        start_dt = BOGOTA_TZ.localize(dt_naive)
    except ValueError:
        # Fallback si ya viene con offset
        start_dt = datetime.fromisoformat(data['fecha_hora_inicio'])

    buffer_hours = tenant.get('appointment_buffer_hours', 2)
    end_dt = start_dt + timedelta(hours=buffer_hours)

    # 2. VERIFICACIÓN FINAL DE CONFLICTO (Double Check)
    # Antes de escribir, preguntamos de nuevo si ese hueco específico está libre
    events_check = service.events().list(
        calendarId=tenant['calendar_id'],
        timeMin=start_dt.isoformat(),
        timeMax=end_dt.isoformat(),
        singleEvents=True
    ).execute()

    if events_check.get('items'):
        print(f"⚠️ Conflicto detectado: Ya hay un evento a esa hora.")
        return False # Retorna Falso para que el Main.py le diga al usuario que no se pudo

    # 3. Crear Evento
    event = {
        'summary': f"CITA: {data['cliente_nombre']}",
        'description': f"Tel: {data['cliente_telefono']}\nInterés: {data.get('propiedad_interes')}",
        'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'America/Bogota'},
        'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'America/Bogota'},
    }
    
    try:
        service.events().insert(calendarId=tenant['calendar_id'], body=event).execute()
        return True
    except Exception as e:
        print(f"Error Calendar Insert: {e}")
        return False