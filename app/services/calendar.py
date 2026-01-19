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
            datetime.combine(target_date, datetime.min.time().replace(hour=9))
        )
        end_of_day = BOGOTA_TZ.localize(
            datetime.combine(target_date, datetime.min.time().replace(hour=17))
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
            # Fallback al calendario principal si falla el específico
            return "No pude sincronizar la agenda específica, intentemos una general."

        available_slots = []
        current_slot = start_of_day

        while current_slot < end_of_day:
            slot_end = current_slot + timedelta(hours=1)
            is_busy = False
            for busy in busy_slots:
                busy_start = datetime.fromisoformat(busy["start"])
                busy_end = datetime.fromisoformat(busy["end"])
                if (current_slot < busy_end) and (slot_end > busy_start):
                    is_busy = True
                    break

            if not is_busy:
                available_slots.append(current_slot.strftime("%I:%M %p"))
            current_slot += timedelta(hours=1)

        if not available_slots:
            return "Agenda llena para ese día."

        return f"Horarios disponibles: {', '.join(available_slots[:3])}."

    except Exception as e:
        print(f"❌ Error Availability: {e}")
        return "Error consultando agenda."


async def create_event_and_lock(agent_id: str, data: dict):
    tenant = TENANTS.get(agent_id)
    service = get_service("calendar", "v3", tenant["creds_file"])

    # Usamos el ID específico
    calendar_id = get_target_calendar(tenant, data.get("asesor_calendar_id"))

    try:
        dt_naive = datetime.fromisoformat(data["fecha_hora_inicio"])
        start_dt = BOGOTA_TZ.localize(dt_naive) if dt_naive.tzinfo is None else dt_naive
    except ValueError:
        return False

    buffer_hours = tenant.get("appointment_buffer_hours", 2)
    end_dt = start_dt + timedelta(hours=buffer_hours)

    # 1. VERIFICAR CONFLICTO EN CALENDARIO ESPECÍFICO
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
        return True
    except Exception as e:
        print(f"Error Calendar Insert: {e}")
        return False


async def cancel_appointment(agent_id: str, client_phone: str):
    """
    Busca la próxima cita activa asociada al número de teléfono y la cancela via delete().
    Retorna un dict con los datos del evento cancelado para notificaciones, o None si no encontró.
    """
    tenant = TENANTS.get(agent_id)
    if not tenant:
        print("❌ Tenant no encontrado para cancelar cita.")
        return None

    calendar_id = tenant["calendar_id"]
    service = get_service("calendar", "v3", tenant["creds_file"])

    now_dt = datetime.now(BOGOTA_TZ)
    # Buscar hasta 30 días en el futuro (o lo que se considere "próxima cita")
    future_limit = now_dt + timedelta(days=60)

    try:
        # 1. LISTAR EVENTOS FUTUROS
        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=now_dt.isoformat(),
                timeMax=future_limit.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                q=client_phone,  # Buscamos el teléfono en description o summary
            )
            .execute()
        )
        items = events_result.get("items", [])

        print(f"🔍 Eventos encontrados para {client_phone}: {items}")

        if not items:
            print(f"⚠️ No se encontró cita futura para {client_phone}")
            return None

        # Tomamos el primero (más próximo)
        event_to_cancel = items[0]
        event_id = event_to_cancel["id"]

        # Extraer datos para notificación antes de borrar
        summary = event_to_cancel.get("summary", "")
        description = event_to_cancel.get("description", "")
        start_str = event_to_cancel.get("start", {}).get("dateTime", "")

        # Intentar parsear hora
        fecha_humana = start_str
        try:
            dt_obj = datetime.fromisoformat(start_str)
            fecha_humana = dt_obj.strftime("%d/%m/%Y a las %I:%M %p")
        except:
            pass

        # Extraer email cliente del description si es posible, o retornarlo como None
        # En create_event metemos: "Tel: ...\nAsesor: ..."
        # Si no guardamos email en description, tocaría pasarlo en 'data' al origen si está disponible.
        # Por ahora extraemos lo que hay.

        # 2. BORRAR EVENTO
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        print(f"✅ Cita cancelada: {summary} ({event_id})")

        return {
            "evento_summary": summary,
            "evento_description": description,
            "fecha_humana": fecha_humana,
            "cliente_telefono": client_phone,
            # Se intentará parsear más datos en notifications si es necesario
        }

    except Exception as e:
        print(f"❌ Error cancelando cita: {e}")
        return None
