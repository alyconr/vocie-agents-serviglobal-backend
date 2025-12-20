import asyncio
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

# Configuración (Asegúrate de que estas variables estén en tu .env o reemplázalas aquí)
TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
DESTINATARIO = "573106666709" # <--- PON TU NÚMERO AQUÍ (con código de país, sin +)

async def test_send():
    if not TOKEN or not PHONE_ID:
        print("❌ Error: Faltan credenciales en el archivo .env")
        return

    url = f"https://graph.facebook.com/v24.0/{PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Payload para enviar un mensaje de plantilla (o texto simple si tienes sesión abierta)
    # Nota: Para iniciar conversación, DEBES usar una plantilla aprobada.
    # Si no tienes plantilla, intenta un mensaje de texto normal (solo funciona si el usuario te escribió antes en las últimas 24h).
    
    payload = {
        "messaging_product": "whatsapp",
        "to": DESTINATARIO,
        "type": "text",
        "text": {
            
            "body": "¡Hola! Este es un mensaje de prueba desde Python."
        }
    }
    
    print(f"📨 Enviando mensaje a {DESTINATARIO}...")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            print(f"Status Code: {response.status_code}")
            print(f"Respuesta: {response.json()}")
            
            if response.status_code == 200:
                print("✅ ¡ÉXITO! Revisa tu WhatsApp.")
            else:
                print("❌ Falló el envío. Revisa el token y el ID.")
        except Exception as e:
            print(f"❌ Error de conexión: {e}")

if __name__ == "__main__":
    asyncio.run(test_send())