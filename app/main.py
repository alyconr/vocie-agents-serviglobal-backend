import os
import uvicorn
import json
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, PlainTextResponse
from dotenv import load_dotenv

# Importación de servicios internos
from app.services import inventory, calendar, notifications, crm
from app.config import WHATSAPP_VERIFY_TOKEN, TENANTS

# Cargar variables de entorno
load_dotenv()

app = FastAPI()

# --- RUTAS DE SALUD ---
@app.get("/")
def home():
    return {"status": "online", "message": "Voice Agent Backend is running"}

# --- WEBHOOK PARA RETELL AI (VOZ) ---
@app.post("/webhook/retell")
async def handle_retell_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Maneja las llamadas de función (Function Calling) desde Retell AI.
    """
    try:
        payload = await request.json()
        print(f"📥 PAYLOAD RETELL: {payload}")

        # 1. Identificar Agente y Herramienta
        agent_id = payload.get("agent_id")
        # Algunos LLMs envían 'name' y otros 'tool_name'
        tool_name = payload.get("name") or payload.get("tool_name") 

        # 2. Extracción Inteligente de Argumentos
        # Retell suele enviar los parámetros dentro de un objeto 'args'.
        # Si no existe 'args', asumimos que el payload plano contiene los datos (para pruebas manuales).
        if isinstance(payload.get('args'), dict):
            args = payload['args']
        else:
            args = payload
        
        print(f"🔧 Tool: {tool_name} | Args: {args}")

        # 3. Enrutamiento de Funciones
        if tool_name == "search_inventory":
            # Busca propiedades en Google Sheets / Redis
            result = await inventory.search_inventory(agent_id, args)
            return JSONResponse(content={"result": result})

        elif tool_name == "check_calendar_availability":
            # Consulta disponibilidad en Google Calendar
            # args.get('asesor_calendar_id') es opcional, si no viene usa el default
            availability = await calendar.check_availability(
                agent_id, 
                args.get("fecha"), 
                args.get("asesor_calendar_id")
            )
            return JSONResponse(content={"result": availability})

        elif tool_name == "book_appointment_and_notify":
            # Intenta agendar la cita
            success = await calendar.create_event_and_lock(agent_id, args)
            
            if success:
                # Tareas en segundo plano (No bloquean la respuesta de voz)
                background_tasks.add_task(notifications.notify_all_parties, agent_id, args)
                background_tasks.add_task(crm.add_lead_to_sheets, agent_id, args)
                return JSONResponse(content={"result": "Cita agendada exitosamente. Enviando confirmaciones."})
            else:
                return JSONResponse(content={"result": "Error: El horario ya no está disponible o hubo un conflicto."})

        # 4. Fallback (Si no hay tool_name explícito, intentamos inferir por campos)
        # Esto es útil para pruebas manuales o LLMs antiguos
        else:
            print("🕵️ Inferencia de intención (Fallback)...")
            if "cliente_telefono" in args and "fecha_hora_inicio" in args:
                # Inferencia: Agendar
                success = await calendar.create_event_and_lock(agent_id, args)
                if success:
                    background_tasks.add_task(notifications.notify_all_parties, agent_id, args)
                    return JSONResponse(content={"result": "Cita agendada (Inferencia)."})
                return JSONResponse(content={"result": "Fallo al agendar (Inferencia)."})
            
            elif "presupuesto_max" in args or "zona_ciudad" in args:
                # Inferencia: Buscar
                result = await inventory.search_inventory(agent_id, args)
                return JSONResponse(content={"result": result})

        return JSONResponse(content={"result": "Función no reconocida o sin argumentos válidos."})

    except Exception as e:
        print(f"❌ Error Crítico en Retell Webhook: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


# --- WEBHOOK PARA WHATSAPP (META) ---

@app.get("/webhook/whatsapp")
async def verify_whatsapp(request: Request):
    """
    Verificación del token requerida por Meta al configurar el webhook.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
            print("✅ Webhook de WhatsApp verificado.")
            return PlainTextResponse(content=challenge, status_code=200)
        else:
            raise HTTPException(status_code=403, detail="Token de verificación incorrecto")
    return {"status": "error", "message": "Faltan parámetros"}

@app.post("/webhook/whatsapp")
async def receive_whatsapp_message(request: Request, background_tasks: BackgroundTasks):
    """
    Recibe mensajes, estados y respuestas de botones de WhatsApp.
    """
    try:
        data = await request.json()
        
        # Validación básica de estructura
        entry = data.get("entry", [])
        if not entry:
            return {"status": "ignored"}

        changes = entry[0].get("changes", [])
        if not changes:
            return {"status": "ignored"}

        value = changes[0].get("value", {})
        
        # A. MANEJO DE MENSAJES ENTRANTES
        if "messages" in value:
            message = value["messages"][0]
            sender = message.get("from")
            msg_type = message.get("type")

            # 1. MENSAJES DE TEXTO (Incluye Quick Replies)
            if msg_type == "text":
                text_body = message["text"]["body"].strip()
                print(f"📩 Mensaje de {sender}: {text_body}")

                # --- LÓGICA DE CANCELACIÓN (BOTÓN O TEXTO) ---
                if text_body.lower() in ["cancelar cita", "cancelar"]:
                    print(f"🛑 Solicitud de cancelación recibida de {sender}")
                    
                    # Seleccionamos un tenant por defecto (O mejora esta lógica si tienes múltiples números)
                    agent_id_default = list(TENANTS.keys())[0] if TENANTS else None
                    
                    if agent_id_default:
                        # a. Buscar y borrar en Google Calendar
                        canceled_data = await calendar.find_and_cancel_appointment(agent_id_default, sender)
                        
                        if canceled_data:
                            # b. Notificar cancelación
                            background_tasks.add_task(notifications.notify_cancellation, agent_id_default, canceled_data)
                            print("✅ Cancelación procesada y notificada.")
                        else:
                            print("⚠️ No se encontró cita futura para cancelar.")
                    else:
                        print("❌ Error: No hay agentes configurados para procesar la cancelación.")

            # 2. RESPUESTAS DE BOTONES INTERACTIVOS (Payloads)
            elif msg_type == "interactive":
                interactive = message.get("interactive")
                if interactive["type"] == "button_reply":
                    payload_id = interactive["button_reply"]["id"]
                    print(f"🔘 Botón ID presionado: {payload_id}")
                    # Aquí podrías manejar lógica si usas botones con ID en lugar de Quick Reply

        # B. MANEJO DE ESTADOS (Sent, Delivered, Read)
        elif "statuses" in value:
            status = value["statuses"][0]
            recipient_id = status.get("recipient_id")
            status_val = status.get("status")
            print(f"🚦 ESTADO WA: {status_val} | Para: {recipient_id}")

        return {"status": "processed"}

    except Exception as e:
        print(f"❌ Error procesando WhatsApp: {e}")
        return {"status": "error"}

