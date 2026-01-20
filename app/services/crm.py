from datetime import datetime
import pytz
from app.core.google_auth import get_service
from app.config import TENANTS

BOGOTA_TZ = pytz.timezone("America/Bogota")

async def log_lead_bg(agent_id: str, data: dict):
    print(f"📝 CRM Log Start: {agent_id}")
    tenant = TENANTS.get(agent_id)
    if not tenant:
        return

    try:
        service = get_service("sheets", "v4", tenant["creds_file"])

        now_bogota = datetime.now(BOGOTA_TZ)
        fecha = now_bogota.strftime("%Y-%m-%d")
        hora = now_bogota.strftime("%I:%M %p")

        # --- LÓGICA DE CLASIFICACIÓN MEJORADA ---
        # 1. Si viene explícito desde la herramienta update_lead_status, úsalo.
        clasificacion = data.get("clasificacion")
        estado = data.get("estado")
        
        # 2. Si no viene explícito, inferir (Fallback para book_appointment)
        if not clasificacion:
            if data.get("fecha_hora_inicio"):
                clasificacion = "Caliente"
            else:
                clasificacion = "Tibio" # Default si algo falla
        
        if not estado:
            if data.get("fecha_hora_inicio"):
                estado = "Agendado"
            else:
                estado = "Interesado" # Default

        # Datos del cliente
        cliente = data.get("cliente_nombre", "Desconocido")
        telefono = data.get("cliente_telefono", "No provisto")
        email = data.get("cliente_email", "No provisto")
        propiedad = data.get("propiedad_interes", "General")
        asesor = data.get("asesor_nombre", "General")
        resumen = data.get("motivo", "") # Nuevo campo opcional para notas

        print(f"📊 Clasificando Lead: {cliente} -> {clasificacion} ({estado})")

        # Col H: Clasificación, Col I: Estado, Col J: Notas (Opcional si tu sheet lo permite)
        row_values = [
            fecha,
            hora,
            cliente,
            telefono,
            email,
            propiedad,
            asesor,
            clasificacion,
            estado,
            resumen # Agregamos el motivo/resumen al final por si tienes columna extra
        ]

        body = {"values": [row_values]}

        service.spreadsheets().values().append(
            spreadsheetId=tenant["sheet_crm_id"],
            range="Leads!A:J",  # Ampliamos el rango para incluir notas
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body,
        ).execute()
        print(f"✅ Lead guardado exitosamente.")

    except Exception as e:
        print(f"❌ Error CRM: {e}")