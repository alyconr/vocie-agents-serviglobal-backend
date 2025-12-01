from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from app.services import inventory, calendar, notifications, crm

app = FastAPI()

class RetellPayload(BaseModel):
    agent_id: str
    name: str
    args: dict

@app.post("/webhook")
async def retell_webhook(payload: RetellPayload, bg_tasks: BackgroundTasks):
    print(f"🔔 Call: {payload.name} | Agent: {payload.agent_id}")
    
    if payload.name == "search_inventory":
        return {"result": await inventory.search_inventory(payload.agent_id, payload.args)}

    if payload.name == "check_calendar_availability":
        return {"result": await calendar.check_availability(payload.agent_id, payload.args.get('fecha'))}

    if payload.name == "book_appointment_and_notify":
        if not payload.args.get('cliente_telefono'):
            return {"result": "Necesito confirmar tu número de WhatsApp."}
            
        if await calendar.create_event_and_lock(payload.agent_id, payload.args):
            bg_tasks.add_task(notifications.notify_all_parties, payload.agent_id, payload.args)
            bg_tasks.add_task(crm.log_lead_bg, payload.agent_id, payload.args)
            return {"result": "Listo, cita agendada y confirmación enviada."}
        else:
            return {"result": "Error al agendar, intenta otro horario."}

    return {"result": "Función no reconocida"}