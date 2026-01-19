import sys
import os
import datetime

# Añadir el directorio actual al path para imports
sys.path.append(os.getcwd())

from app.config import TENANTS
from app.core.google_auth import get_service

# Configuración
AGENT_ID = "agent_89e9f56cb7d25e9f1da5e38d45"
PHONE = "573106666709"


def debug_calendar():
    print("🚀 Iniciando Debug de Calendario...")
    tenant = TENANTS.get(AGENT_ID)
    if not tenant:
        print("❌ Tenant no encontrado")
        return

    calendar_id = tenant["calendar_id"]
    print(f"📅 ID de Calendario Configurado: {calendar_id}")

    # Verificar archivo credenciales
    creds_file = tenant["creds_file"]
    if not os.path.exists(creds_file):
        print(f"❌ Archivo de credenciales no encontrado: {creds_file}")
        return

    try:
        service = get_service("calendar", "v3", creds_file)

        # 1. Listar Calendarios Visibles
        print("\n🔎 Listando calendarios visibles para la cuenta de servicio:")
        cal_list = service.calendarList().list().execute()
        found_target = False
        for cal in cal_list.get("items", []):
            print(
                f"   - {cal.get('summary')} (ID: {cal.get('id')}) - Access: {cal.get('accessRole')}"
            )
            if cal.get("id") == calendar_id:
                found_target = True

        if not found_target:
            print(
                f"⚠️ ¡ADVERTENCIA! El calendario objetivo '{calendar_id}' NO está en la lista de calendarios visibles."
            )
            print(
                "   Esto significa que la cuenta de servicio no lo ha 'agregado' o no tiene permisos."
            )
        else:
            print(f"✅ Calendario objetivo encontrado en la lista.")

        # 2. Buscar Eventos
        # Usamos UTC para evitar dependency hell de pytz si no está instalado
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        start_search = now_dt - datetime.timedelta(days=2)  # 2 días atrás
        future_limit = now_dt + datetime.timedelta(days=60)

        print(
            f"\n⏳ Buscando eventos desde {start_search.isoformat()} hasta {future_limit.isoformat()}"
        )
        print(f"📞 Buscando teléfono: {PHONE}")

        # Intentar listar sin filtro 'q'
        events_check = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=start_search.isoformat(),
                timeMax=future_limit.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        items = events_check.get("items", [])
        print(f"📊 Total eventos encontrados: {len(items)}")

        matches = []
        for ev in items:
            summary = ev.get("summary", "")
            description = ev.get("description", "")
            # print(f"  - Revisando: '{summary}' | Start: {ev.get('start')}")
            if PHONE in summary or PHONE in description:
                print(f"    ✅ MATCH ENCONTRADO: {summary}")
                matches.append(ev)

        print(f"\n💡 Total Coincidencias: {len(matches)}")

    except Exception as e:
        print(f"❌ Error API Calendario: {e}")


if __name__ == "__main__":
    debug_calendar()
