from datetime import datetime, timedelta
import pytz
from app.config import TENANTS
from app.core.google_auth import get_service

BOGOTA_TZ = pytz.timezone('America/Bogota')

def get_target_calendar(tenant, calendar_id_arg):
    """
    Selecciona el calendario correcto.
    CORRECCIÓN: Se eliminó la restricción estricta de dominios (@gmail/@group).
    Ahora acepta cualquier email válido que venga del inventario.
    """
    # Si viene un argumento y parece un email o ID válido (tiene @), úsalo.
    if calendar_id_arg and '@' in str(calendar_id_arg):
        print(f"🎯 Usando calendario específico del asesor: {calendar_id_arg}")
        return calendar_id_arg.strip()
    
    # Si no, usa el default de la inmobiliaria (Fallback)
    print(f"⚠️ No se detectó ID específico, usando calendario general: {tenant['calendar_id']}")
    return tenant['calendar_id']

async def check_availability(agent_id: str, date_str: str, asesor_calendar_id: str = None):
    tenant = TENANTS.get(agent_id)
    if not tenant: return "Error config."

    # Usamos el ID específico si viene
    calendar_id = get_target_calendar(tenant, asesor_calendar_id)

    try:
        service = get_service('calendar', 'v3', tenant['creds_file'])
        
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        # Horario laboral: 8 AM a 6 PM (Ajustado para dar margen)
        start_of_day = BOGOTA_TZ.localize(datetime.combine(target_date, datetime.min.time().replace(hour=8)))
        end_of_day = BOGOTA_TZ.localize(datetime.combine(target_date, datetime.min.time().replace(hour=18)))

        body = {
            "timeMin": start_of_day.isoformat(),
            "timeMax": end_of_day.isoformat(),
            "timeZone": "America/Bogota",
            "items": [{"id": calendar_id}]
        }
        
        try:
            # Consultamos FreeBusy a Google
            events_result = service.freebusy().query(body=body).execute()
            calendars_data = events_result.get('calendars', {})
            
            # Validación de seguridad: ¿Google encontró el calendario?
            if calendar_id not in calendars_data or 'errors' in calendars_data[calendar_id]:
                print(f"⚠️ Error o No encontrado en Google: {calendar_id}. Reintentando con Default.")
                # Si falla el específico, consultamos el general para no dejar al cliente colgado
                calendar_id = tenant['calendar_id']
                body['items'][0]['id'] = calendar_id
                events_result = service.freebusy().query(body=body).execute()
            
            busy_slots = events_result['calendars'][calendar_id]['busy']
            
        except Exception as e:
            print(f"⚠️ Excepción técnica consultando {calendar_id}: {e}")
            return "No pude sincronizar la agenda, intentemos otro horario."

        available_slots = []
        current_slot = start_of_day
        
        # Generamos slots de 1 hora
        while current_slot < end_of_day:
            slot_end = current_slot + timedelta(hours=1)
            is_busy = False
            
            for busy in busy_slots:
                busy_start = datetime.fromisoformat(busy['start'])
                busy_end = datetime.fromisoformat(busy['end'])
                
                # Lógica de colisión estricta (Cualquier solapamiento marca ocupado)
                if (current_slot < busy_end) and (slot_end > busy_start):
                    is_busy = True
                    break
            
            if not is_busy:
                # Formato amigable: "09:00 AM"
                available_slots.append(current_slot.strftime("%I:%M %p"))
            
            current_slot += timedelta(hours=1)

        if not available_slots:
            return "La agenda está llena para ese día."
            
        return f"Horarios disponibles: {', '.join(available_slots[:4])}."

    except Exception as e:
        print(f"❌ Error Availability Crítico: {e}")
        return "Error consultando agenda."

async def create_event_and_lock(agent_id: str, data: dict):
    tenant = TENANTS.get(agent_id)
    service = get_service('calendar', 'v3', tenant['creds_file'])
    
    # IMPORTANTE: Aquí también usamos la función corregida
    # Prioridad: 1. ID de calendario explícito, 2. Email del asesor, 3. Default
    target_id = data.get('asesor_calendar_id') or data.get('asesor_email')
    calendar_id = get_target_calendar(tenant, target_id)

    try:
        dt_naive = datetime.fromisoformat(data['fecha_hora_inicio'])
        start_dt = BOGOTA_TZ.localize(dt_naive) if dt_naive.tzinfo is None else dt_naive
    except ValueError:
        return False

    buffer_hours = tenant.get('appointment_buffer_hours', 1)
    end_dt = start_dt + timedelta(hours=buffer_hours)

    # 1. VERIFICAR CONFLICTO (Doble chequeo antes de escribir)
    events_check = service.events().list(
        calendarId=calendar_id,
        timeMin=start_dt.isoformat(),
        timeMax=end_dt.isoformat(),
        singleEvents=True
    ).execute()

    if events_check.get('items'):
        print(f"⛔ Conflicto detectado en el último segundo para {calendar_id}")
        return False 

    # 2. CREAR EVENTO
    event = {
        'summary': f"CITA: {data.get('cliente_nombre', 'Cliente')} - {data.get('propiedad_interes', 'Propiedad')}",
        'description': f"Cliente: {data.get('cliente_nombre')}\nTel: {data.get('cliente_telefono')}\nAsesor Asignado: {data.get('asesor_nombre')}",
        'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'America/Bogota'},
        'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'America/Bogota'},
        # Opcional: Agregar al asesor como asistente si el calendario es diferente al suyo
        'attendees': [{'email': data.get('asesor_email')}] if data.get('asesor_email') and '@' in data.get('asesor_email') else []
    }
    
    try:
        service.events().insert(calendarId=calendar_id, body=event).execute()
        print(f"✅ Cita creada exitosamente en calendario: {calendar_id}")
        return True
    except Exception as e:
        print(f"❌ Error Calendar Insert: {e}")
        return False