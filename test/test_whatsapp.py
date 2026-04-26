import asyncio
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIGURACIÓN
# ============================================================
TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
DESTINATARIO = "573193065230"  # <--- Número destino (con código de país, sin +)

# ============================================================
# MODO DE ENVÍO: "text" o "template"
# ============================================================
MODO = "template"  # <--- Cambia a "text" para mensaje simple (ventana 24h)

# ============================================================
# CONFIGURACIÓN DE PLANTILLA (solo si MODO = "template")
# ============================================================
TEMPLATE_NAME = "cita_confirmada_cliente"  # <--- Nombre exacto de tu plantilla aprobada en Meta
TEMPLATE_LANG = "es_CO"                    # <--- Idioma (es_CO, es, es_MX, etc.)
TEMPLATE_PARAMS = [                        # <--- Variables {{1}}, {{2}}, etc.
    "Juan Pérez",                          # {{1}} - Nombre cliente
    "28/04/2026 a las 10:00 AM",           # {{2}} - Fecha
    "María López",                         # {{3}} - Asesor
    "Apartamento Poblado 301",             # {{4}} - Propiedad
]

# ============================================================
# TEXTO SIMPLE (solo si MODO = "text", requiere ventana 24h)
# ============================================================
TEXTO_SIMPLE = "En qué puedo ayudarte el día de hoy?."


async def test_send():
    if not TOKEN or not PHONE_ID:
        print("❌ Error: Faltan WHATSAPP_TOKEN o WHATSAPP_PHONE_ID en .env")
        return

    url = f"https://graph.facebook.com/v24.0/{PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }

    # --- Construir payload según modo ---
    if MODO == "template":
        payload = {
            "messaging_product": "whatsapp",
            "to": DESTINATARIO,
            "type": "template",
            "template": {
                "name": TEMPLATE_NAME,
                "language": {"code": TEMPLATE_LANG},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": str(p)} for p in TEMPLATE_PARAMS
                        ]
                    }
                ]
            }
        }
        print(f"📨 Enviando PLANTILLA '{TEMPLATE_NAME}' a {DESTINATARIO}...")
        print(f"   Params: {TEMPLATE_PARAMS}")
    else:
        payload = {
            "messaging_product": "whatsapp",
            "to": DESTINATARIO,
            "recipient_type": "individual",
            "type": "text",
            "text": {"body": TEXTO_SIMPLE}
        }
        print(f"📨 Enviando TEXTO a {DESTINATARIO}: {TEXTO_SIMPLE}")

    # --- Enviar ---
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            print(f"\nStatus Code: {response.status_code}")
            print(f"Respuesta: {response.json()}")

            if response.status_code == 200:
                print("\n✅ ¡ÉXITO! Revisa tu WhatsApp.")
            else:
                print("\n❌ Falló el envío. Detalles arriba.")
        except Exception as e:
            print(f"❌ Error de conexión: {e}")


if __name__ == "__main__":
    asyncio.run(test_send())