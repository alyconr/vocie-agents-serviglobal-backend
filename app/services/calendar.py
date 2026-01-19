from datetime import datetime, timedelta
import pytz
from app.config import TENANTS
from app.core.google_auth import get_service

BOGOTA_TZ = pytz.timezone("America/Bogota")


def get_target_calendar(tenant, calendar_id_arg):
    """
    Si viene un ID de calendario específico (ej: c_123...@group.calendar...), úsalo.
    Si no, usa el default de la inmobiliaria.
    """
    if calendar_id_arg and (
        "@group.calendar.google.com" in calendar_id_arg
        or "@gmail.com" in calendar_id_arg
    ):
        print(f"🎯 Usando calendario específico: {calendar_id_arg}")
        return calendar_id_arg.strip()
    return tenant["calendar_id"]


async def check_availability(
    agent_id: str, date_str: str, asesor_calendar_id: str = None
):
    tenant = TENANTS.get(agent_id)
    if not tenant:
        return "Error config."

    # Usamos el ID específico si viene
    calendar_id = get_target_calendar(tenant, asesor_calendar_id)

    try:
        service = get_service("calendar", "v3", tenant["creds_file"])

        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        start_of_day = BOGOTA_TZ.localize(
            datetime.combine(target_date, datetime.min.time().replace(hour=8))
        )
        end_of_day = BOGOTA_TZ.localize(
            datetime.combine(target_date, datetime.min.time().replace(hour=18))
        )

        body = {
            "timeMin": start_of_day.isoformat(),
            "timeMax": end_of_day.isoformat(),
            "timeZone": "America/Bogota",
            "items": [{"id": calendar_id}],
        }

        try:
            events_result = service.freebusy().query(body=body).execute()
            busy_slots = events_result["calendars"][calendar_id]["busy"]
        except Exception as e:
            print(f"⚠️ Error permisos calendario {calendar_id}: {e}")
            return "No pude sincronizar la agenda específica, intentemos una general."

        available_slots = []
        current_slot = start_of_day

        while current_slot < end_of_day:
            slot_end = current_slot + timedelta(hours=1)
            is_busy = False
            for busy in busy_slots:
                busy_start = datetime.fromisoformat(busy["start"])
                busy_end = datetime.fromisoformat(busy["end"])
                # Lógica de colisión simple
                if (current_slot < busy_end) and (slot_end > busy_start):
                    is_busy = True
                    break

            if not is_busy:
                available_slots.append(current_slot.strftime("%I:%M %p"))
            current_slot += timedelta(hours=1)

        if not available_slots:
            return "Agenda llena para ese día."

        return f"Horarios disponibles: {', '.join(available_slots[:4])}."

    except Exception as e:
        print(f"❌ Error Availability: {e}")
        return "Error consultando agenda."


async def create_event_and_lock(agent_id: str, data: dict):
    tenant = TENANTS.get(agent_id)
    service = get_service("calendar", "v3", tenant["creds_file"])

    # Usamos el ID específico del asesor si viene
    calendar_id = get_target_calendar(tenant, data.get("asesor_calendar_id"))

    try:
        dt_naive = datetime.fromisoformat(data["fecha_hora_inicio"])
        start_dt = (
            BOGOTA_TZ.localize(dt_naive) if dt_naive.tzinfo is None else dt_naive
        )
    except ValueError:
        return False

    buffer_hours = tenant.get("appointment_buffer_hours", 1)
    end_dt = start_dt + timedelta(hours=buffer_hours)

    # 1. VERIFICAR CONFLICTO EN CALENDARIO ESPECÍFICO
    try:
        events_check = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=start_dt.isoformat(),
                timeMax=end_dt.isoformat(),
                singleEvents=True,
            )
            .execute()
        )

        if events_check.get("items"):
            print(f"⛔ Conflicto encontrado en {calendar_id}")
            return False
    except Exception as e:
        print(f"⚠️ Error verificando conflicto en {calendar_id}: {e}")
        # Si falla el específico, podríamos intentar el general, o abortar.
        # Por seguridad, abortamos para no sobreagendar.
        return False

    # 2. CREAR EVENTO
    event = {
        "summary": f"CITA: {data['cliente_nombre']} - {data.get('propiedad_interes', 'General')}",
        "description": f"Cliente: {data['cliente_nombre']}\nTel: {data['cliente_telefono']}\nAsesor: {data.get('asesor_nombre')}",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "America/Bogota"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "America/Bogota"},
    }

    try:
        service.events().insert(calendarId=calendar_id, body=event).execute()
        print(f"✅ Evento creado en {calendar_id}")
        return True
    except Exception as e:
        print(f"❌ Error Calendar Insert: {e}")
        return False


async def cancel_appointment(agent_id: str, client_phone: str):
    """
    Busca la próxima cita activa asociada al teléfono en TODOS los calendarios accesibles.
    Retorna los datos del evento eliminado o None.
    """
    tenant = TENANTS.get(agent_id)
    if not tenant:
        print("❌ Tenant no encontrado.")
        return None

    service = get_service("calendar", "v3", tenant["creds_file"])
    
    # Limpiamos el teléfono
    phone_clean = client_phone.replace(" ", "").replace("+", "").strip()

    now_dt = datetime.now(BOGOTA_TZ)
    future_limit = now_dt + timedelta(days=60) # Buscar hasta 2 meses adelante

    print(f"🕵️ Iniciando Búsqueda Multi-Calendario para cancelar: {phone_clean}")

    try:
        # PASO 1: Obtener lista de TODOS los calendarios accesibles por el Service Account
        calendar_list_result = service.calendarList().list().execute()
        calendar_items = calendar_list_result.get("items", [])
        
        # Filtramos solo aquellos donde tenemos permiso de escritura ('writer' o 'owner')
        # para no perder tiempo buscando en calendarios de solo lectura (como festivos).
        writable_calendars = [
            cal['id'] for cal in calendar_items 
            if cal.get('accessRole') in ['writer', 'owner']
        ]

        # Aseguramos que el calendario default esté en la lista por si acaso
        if tenant["calendar_id"] not in writable_calendars:
            writable_calendars.append(tenant["calendar_id"])

        print(f"📅 Calendarios a escanear ({len(writable_calendars)}): {writable_calendars}")

        # PASO 2: Iterar y buscar el evento
        for cal_id in writable_calendars:
            try:
                # Buscamos eventos donde aparezca el teléfono (Query libre 'q')
                events_result = (
                    service.events()
                    .list(
                        calendarId=cal_id,
                        timeMin=now_dt.isoformat(),
                        timeMax=future_limit.isoformat(),
                        singleEvents=True,
                        orderBy="startTime",
                        q=phone_clean, # Google busca este string en todo el evento
                    )
                    .execute()
                )
                
                items = events_result.get("items", [])

                if items:
                    # ¡ENCONTRADO!
                    event_to_cancel = items[0]
                    event_id = event_to_cancel["id"]
                    summary = event_to_cancel.get("summary", "")
                    
                    print(f"✅ Cita encontrada en calendario: {cal_id} | Evento: {summary}")
                    
                    # PASO 3: Borrar Evento
                    service.events().delete(calendarId=cal_id, eventId=event_id).execute()
                    print(f"🗑️ Cita eliminada exitosamente.")

                    # Preparar respuesta
                    start_str = event_to_cancel.get("start", {}).get("dateTime", "")
                    fecha_humana = start_str
                    try:
                        dt_obj = datetime.fromisoformat(start_str)
                        fecha_humana = dt_obj.strftime("%d/%m/%Y a las %I:%M %p")
                    except:
                        pass
                    
                    return {
                        "evento_summary": summary,
                        "fecha_humana": fecha_humana,
                        "cliente_telefono": client_phone,
                        "asesor_calendario_origen": cal_id # Dato útil para debug
                    }

            except Exception as e_inner:
                # Si falla leer un calendario específico, continuamos con el siguiente
                print(f"⚠️ Error leyendo calendario {cal_id}: {e_inner}")
                continue
        
        print(f"⚠️ No se encontró ninguna cita futura para {phone_clean} en ningún calendario.")
        return None

    except Exception as e:
        print(f"❌ Error Global en cancel_appointment: {e}")
        return None