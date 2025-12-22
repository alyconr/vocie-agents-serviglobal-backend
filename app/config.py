import os
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Para el MVP usamos un solo número (el tuyo) para salida
GLOBAL_WA_TOKEN = os.getenv("WHATSAPP_TOKEN")
GLOBAL_WA_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")

TENANTS = {
    # REEMPLAZA ESTE ID CON EL QUE TE DE RETELL EN SU DASHBOARD
    "agent_89e9f56cb7d25e9f1da5e38d45": { 
        "name": "Inmobiliaria Demo",
        "creds_file": "credentials/client_demo.json", # Nombre de tu archivo JSON
        
        # IDs de los Google Sheets (Saca esto de la URL del navegador)
        "sheet_inventory_id": "1f-pIMvtz7N7SVsnM4MveXAjAxzrb-b6XIEQfnfOVpnw",
        "sheet_crm_id": "1EbTnCXR2qzJSyykpjGtIwrz196voa8lcBZ-vc5ITh3U",
        
        "calendar_id": "alyconr473@gmail.com",
        "inventory_range": "inventario!A:ZZ",
        "timezone": "America/Bogota",
        
        # DATOS DEL DUEÑO (TÚ)
        "owner_phone": "573106666709",  # Tu celular para recibir alertas
        "owner_email": "alyconr@hotmail.com",
        "appointment_buffer_hours": 1,
        
        # Whatsapp (opcional, si no usará el global)
        "whatsapp_token": os.getenv("WHATSAPP_TOKEN"),
        "whatsapp_phone_id": os.getenv("WHATSAPP_PHONE_ID")
    }
}