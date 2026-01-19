import sys
import os

# Añadir el directorio actual al path para imports
sys.path.append(os.getcwd())

from datetime import datetime, timedelta
import pytz
from app.config import TENANTS
from app.core.google_auth import get_service

# Configuración
AGENT_ID = "agent_89e9f56cb7d25e9f1da5e38d45"
PHONE = "573106666709"
BOGOTA_TZ = pytz.timezone("America/Bogota")


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

        now_dt = datetime.now(BOGOTA_TZ)
        future_limit = now_dt + timedelta(days=60)

        print(f"⏳ Buscando eventos desde {now_dt} hasta {future_limit}")
        print(f"📞 Buscando teléfono: {PHONE}")

        # Intentar listar sin filtro 'q'
        events_check = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=now_dt.isoformat(),
                timeMax=future_limit.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        items = events_check.get("items", [])
        print(f"📊 Total eventos futuros encontrados: {len(items)}")

        matches = []
        for ev in items:
            summary = ev.get("summary", "")
            description = ev.get("description", "")

            print(f"  - Revisando: '{summary}'")
            if PHONE in summary or PHONE in description:
                print(f"    ✅ MATCH ENCONTRADO!")
                matches.append(ev)

        print(f"\n💡 Total Coincidencias: {len(matches)}")

    except Exception as e:
        print(f"❌ Error API Calendario: {e}")


if __name__ == "__main__":
    debug_calendar()
