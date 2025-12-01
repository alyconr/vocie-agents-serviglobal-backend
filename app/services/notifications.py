import httpx
from app.config import GLOBAL_WA_TOKEN, GLOBAL_WA_PHONE_ID, TENANTS

async def notify_all_parties(agent_id: str, data: dict):
    tenant = TENANTS.get(agent_id)
    
    # 1. Al Cliente
    await send_whatsapp(data['cliente_telefono'], "cita_confirmada_cliente", 
                        [data['cliente_nombre'], data['fecha_hora_inicio']])
    
    # 2. Al Dueño
    await send_whatsapp(tenant['owner_phone'], "alerta_nuevo_lead_owner", 
                        [tenant['name'], data['cliente_nombre'], data['cliente_telefono'], data['fecha_hora_inicio']])

async def send_whatsapp(to: str, template: str, params: list):
    url = f"https://graph.facebook.com/v17.0/{GLOBAL_WA_PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {GLOBAL_WA_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp", "to": to, "type": "template",
        "template": {"name": template, "language": {"code": "es"}, "components": [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in params]}]}
    }
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload, headers=headers)