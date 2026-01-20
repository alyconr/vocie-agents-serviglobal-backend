from datetime import datetime, timedelta
import pytz
from app.config import TENANTS
from app.core.google_auth import get_service

# Importamos el módulo de inventario para obtener los calendarios de asesores
from app.services import inventory

BOGOTA_TZ = pytz.timezone("America/Bogota")


def get_target_calendar(tenant, calendar_id_arg):
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
    calendar_id = get_target_calendar(tenant, data.get("asesor_calendar_id"))

    try:
        dt_naive = datetime.fromisoformat(data["fecha_hora_inicio"])
        start_dt = BOGOTA_TZ.localize(dt_naive) if dt_naive.tzinfo is None else dt_naive
    except ValueError:
        return False

    buffer_hours = tenant.get("appointment_buffer_hours", 1)
    end_dt = start_dt + timedelta(hours=buffer_hours)

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
        return False

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
    Busca la próxima cita activa escaneando TODOS los calendarios definidos en el Inventario.
    """
    tenant = TENANTS.get(agent_id)
    if not tenant:
        return None

    service = get_service("calendar", "v3", tenant["creds_file"])
    phone_clean = client_phone.replace(" ", "").replace("+", "").strip()

    now_dt = datetime.now(BOGOTA_TZ)
    future_limit = now_dt + timedelta(days=60)

    # 1. OBTENER LISTA MAESTRA DE CALENDARIOS (INVENTARIO + DEFAULT)
    # Consultamos al inventario qué asesores existen
    advisor_calendars = await inventory.get_unique_calendar_ids(agent_id)

    # Creamos un conjunto único para no escanear doble
    calendars_to_scan = set(advisor_calendars)
    calendars_to_scan.add(tenant["calendar_id"])

    print(f"🕵️ Iniciando Búsqueda para cancelar: {phone_clean}")
    print(
        f"📅 Escaneando {len(calendars_to_scan)} calendarios: {list(calendars_to_scan)}"
    )

    # 2. ESCANEAR CADA CALENDARIO
    for cal_id in calendars_to_scan:
        try:
            events_result = (
                service.events()
                .list(
                    calendarId=cal_id,
                    timeMin=now_dt.isoformat(),
                    timeMax=future_limit.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    q=phone_clean,  # Google busca el teléfono en todo el evento
                )
                .execute()
            )

            items = events_result.get("items", [])

            if items:
                event_to_cancel = items[0]
                event_id = event_to_cancel["id"]
                summary = event_to_cancel.get("summary", "")

                print(f"✅ Cita encontrada en {cal_id} | Evento: {summary}")

                # 3. BORRAR
                service.events().delete(calendarId=cal_id, eventId=event_id).execute()
                print(f"🗑️ Cita eliminada.")

                start_str = event_to_cancel.get("start", {}).get("dateTime", "")
                fecha_humana = start_str
                try:
                    dt_obj = datetime.fromisoformat(start_str)
                    fecha_humana = dt_obj.strftime("%d/%m/%Y a las %I:%M %p")
                except:
                    pass

                # 4. RESOLVER EMAIL REAL DEL ASESOR
                asesor_email_real = None
                
                # A. Si el ID del calendario parece un email personal (no group.calendar), úsalo.
                if "@" in cal_id and "group.calendar.google.com" not in cal_id:
                    asesor_email_real = cal_id
                
                # B. Si no (es un ID técnico), búscalo en el inventario
                if not asesor_email_real:
                    asesor_email_real = await inventory.get_advisor_email_by_calendar(agent_id, cal_id)

                return {
                    "evento_summary": summary,
                    "fecha_humana": fecha_humana,
                    "cliente_telefono": client_phone,
                    "asesor_calendario_origen": cal_id,
                }

        except Exception as e:
            # Si no tenemos permiso en un calendario específico, lo saltamos y seguimos con el siguiente
            print(f"⚠️ Saltando calendario {cal_id}: {e}")
            continue

    print(f"⚠️ No se encontró cita para {phone_clean} en ningún calendario.")
    return None
