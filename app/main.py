from fastapi import FastAPI, BackgroundTasks, Request, Query, HTTPException
from fastapi.responses import PlainTextResponse
from app.services import inventory, calendar, notifications, crm
from app.config import TENANTS
import os

app = FastAPI()

# Token de verificación que configurarás en el panel de Meta
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "inmobiliaria_token_secreto")


@app.get("/webhook/whatsapp")
async def verify_whatsapp_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    """
    Endpoint para la verificación del Webhook de WhatsApp por parte de Meta.
    """
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        print("✅ Webhook de WhatsApp verificado correctamente.")
        return PlainTextResponse(content=hub_challenge, status_code=200)

    print(f"❌ Fallo de verificación de Webhook. Token recibido: {hub_verify_token}")
    raise HTTPException(status_code=403, detail="Verificación fallida")


@app.post("/webhook/whatsapp")
async def receive_whatsapp_message(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint Unificado: Recibe Mensajes (Texto/Botones) y Actualizaciones de Estado.
    """
    try:
        payload = await request.json()

        # 1. Extracción Segura de Datos
        entry = payload.get("entry", [])
        if not entry:
            return {"status": "ignored", "reason": "no_entry"}

        changes = entry[0].get("changes", [])
        if not changes:
            return {"status": "ignored", "reason": "no_changes"}

        value = changes[0].get("value", {})

        # --- CASO A: ACTUALIZACIÓN DE ESTADO ---
        if "statuses" in value:
            status_update = value["statuses"][0]
            msg_id = status_update.get("id")
            status = status_update.get("status")
            recipient = status_update.get("recipient_id")

            print(f"🚦 ESTADO ACTUALIZADO: ID={msg_id} | Status={status} | Para={recipient}")
            return {"status": "ack_status_update"}

        # --- CASO B: MENSAJE ENTRANTE (CLIENTE ESCRIBE O PRESIONA BOTÓN) ---
        elif "messages" in value:
            message = value["messages"][0]
            sender = message.get("from")
            msg_type = message.get("type")

            print(f"📩 MENSAJE RECIBIDO de {sender} ({msg_type})")

            # FLAG PARA DETECTAR INTENCIÓN DE CANCELAR
            should_cancel = False

            # 1. SI ES TEXTO (O Quick Reply simple)
            if msg_type == "text":
                text_body = message["text"]["body"].strip()
                print(f"   Texto: {text_body}")
                if text_body.lower() in ["cancelar cita", "cancelar"]:
                    should_cancel = True

            # 2. SI ES BOTÓN INTERACTIVO (Payload)
            elif msg_type == "interactive":
                interactive = message.get("interactive", {})
                if interactive.get("type") == "button_reply":
                    btn_id = interactive["button_reply"]["id"]
                    btn_title = interactive["button_reply"]["title"]
                    print(f"🔘 Botón presionado: ID={btn_id} | Title={btn_title}")
                    
                    # Verificamos ID o Texto del botón
                    if btn_id == "CANCELAR_CITA" or btn_title.lower() in ["cancelar cita", "cancelar"]:
                        should_cancel = True

            # --- EJECUCIÓN CENTRALIZADA DE CANCELACIÓN ---
            if should_cancel:
                print(f"🛑 Solicitud de cancelación detectada para {sender}")
                
                # Seleccionar Agente
                try:
                    agent_id = list(TENANTS.keys())[0]
                except IndexError:
                    print("❌ Error crítico: No hay agentes configurados.")
                    return {"status": "error"}

                # Ejecutar cancelación
                canceled_data = await calendar.cancel_appointment(agent_id, sender)

                if canceled_data:
                    background_tasks.add_task(notifications.notify_cancellation, agent_id, canceled_data)
                    print("✅ Cancelación procesada y tarea de notificación encolada.")
                else:
                    print("⚠️ No se encontró cita futura para cancelar.")

            return {"status": "message_received"}

        else:
            return {"status": "ignored", "reason": "unknown_event"}

    except Exception as e:
        print(f"❌ Error procesando Webhook WhatsApp: {e}")
        return {"status": "error", "detail": str(e)}


@app.post("/webhook")
async def retell_webhook(request: Request, bg_tasks: BackgroundTasks):
    """
    Webhook Inteligente para Retell AI (Voz).
    """
    try:
        payload = await request.json()
        print(f"📥 PAYLOAD RECIBIDO: {payload}")

        agent_id = payload.get("agent_id")
        func_name = payload.get("name") or payload.get("tool_name")
        args = payload

        # Fallback de Agente
        try:
            agent_id = list(TENANTS.keys())[0]
            print(f"🔧 Usando agente por defecto: {agent_id}")
        except:
            return {"result": "Error crítico: No hay agentes configurados."}

        # LÓGICA DE INFERENCIA
        keys = args.keys()
        user_text = str(args.get("user_message", "")).lower()

        if "cancelar" in user_text or args.get("action") == "cancel_appointment" or "cancelar" in str(payload):
            func_name = "cancel_appointment"
        elif "cliente_telefono" in keys or ("cliente_nombre" in keys and "fecha_hora_inicio" in keys):
            func_name = "book_appointment_and_notify"
        elif "ciudad" in keys or "tipo_operacion" in keys or "presupuesto_max" in keys:
            func_name = "search_inventory"
        elif "fecha" in keys or "asesor_calendar_id" in keys:
            func_name = "check_calendar_availability"
        
        # Fallback final
        elif "presupuesto_max" in args: func_name = "search_inventory"
        elif "cliente_telefono" in args: func_name = "book_appointment_and_notify"
        elif "fecha" in args: func_name = "check_calendar_availability"

        print(f"🕵️ Función inferida: {func_name}")

        if not func_name:
            return {"result": "No pude entender qué función ejecutar."}

        print(f"🔔 Ejecutando: {func_name}")

        # --- EJECUCIÓN ---
        if func_name == "search_inventory":
            return {"result": await inventory.search_inventory(agent_id, args)}

        if func_name == "check_calendar_availability":
            fecha = args.get("fecha")
            cal_id = args.get("asesor_calendar_id") or args.get("asesor_email")
            if not fecha: return {"result": "¿Para qué fecha?"}
            return {"result": await calendar.check_availability(agent_id, fecha, cal_id)}

        if func_name == "book_appointment_and_notify":
            if not args.get("cliente_telefono"):
                return {"result": "Necesito confirmar tu número de WhatsApp."}
            
            success = await calendar.create_event_and_lock(agent_id, args)
            if success:
                bg_tasks.add_task(notifications.notify_all_parties, agent_id, args)
                bg_tasks.add_task(crm.log_lead_bg, agent_id, args)
                return {"result": "Listo, cita agendada."}
            else:
                return {"result": "Ese horario ya está ocupado."}

        if func_name == "cancel_appointment":
            phone = args.get("cliente_telefono") or args.get("from_number")
            if not phone: return {"result": "No identifiqué tu número."}
            
            cancel_result = await calendar.cancel_appointment(agent_id, phone)
            if cancel_result:
                bg_tasks.add_task(notifications.notify_cancellation, agent_id, cancel_result, args)
                return {"result": f"Cita cancelada: {cancel_result.get('evento_summary', '')}."}
            else:
                return {"result": "No encontré ninguna cita futura."}

        return {"result": f"Función {func_name} no encontrada."}

    except Exception as e:
        print(f"❌ ERROR FATAL: {str(e)}")
        return {"result": "Error técnico interno."}