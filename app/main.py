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
        fecha = payload.args.get('fecha')
        cal_id = payload.args.get('asesor_calendar_id') # <--- ID Específico
        
        if not fecha:
            return {"result": "¿Para qué fecha?"}
            
        return {"result": await calendar.check_availability(payload.agent_id, fecha, cal_id)}

    if payload.name == "book_appointment_and_notify":
        if not payload.args.get('cliente_telefono'):
            return {"result": "Necesito confirmar tu número de WhatsApp."}
            
        success = await calendar.create_event_and_lock(payload.agent_id, payload.args)
        
        if success:
            bg_tasks.add_task(notifications.notify_all_parties, payload.agent_id, payload.args)
            bg_tasks.add_task(crm.log_lead_bg, payload.agent_id, payload.args)
            return {"result": "Listo, cita agendada."}
        else:
            try:
                full_date = payload.args.get('fecha_hora_inicio', '')
                date_only = full_date.split('T')[0]
                cal_id = payload.args.get('asesor_calendar_id')
                alternativas = await calendar.check_availability(payload.agent_id, date_only, cal_id)
                return {"result": f"Horario ocupado. {alternativas}"}
            except:
                return {"result": "Horario ocupado. ¿Miramos otro?"}

    return {"result": "Función no reconocida."}