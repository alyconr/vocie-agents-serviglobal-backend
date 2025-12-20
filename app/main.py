from fastapi import FastAPI, BackgroundTasks, Request, Query, HTTPException
from fastapi.responses import PlainTextResponse
from app.services import inventory, calendar, notifications, crm
from app.config import TENANTS
import os

app = FastAPI()

# Token de verificación que configurarás en el panel de Meta
# Debe coincidir con lo que pongas en "Verify Token" en la configuración de la App
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "inmobiliaria_token_secreto")

@app.get("/webhook/whatsapp")
async def verify_whatsapp_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge")
):
    """
    Endpoint para la verificación del Webhook de WhatsApp por parte de Meta.
    Meta enviará una petición GET con estos parámetros.
    """
    # 1. Verificar si el modo y el token son correctos
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        print("✅ Webhook de WhatsApp verificado correctamente.")
        # 2. Responder con el desafío (challenge) en texto plano
        return PlainTextResponse(content=hub_challenge, status_code=200)
    
    # 3. Si no coincide, rechazar la conexión
    print(f"❌ Fallo de verificación de Webhook. Token recibido: {hub_verify_token}")
    raise HTTPException(status_code=403, detail="Verificación fallida")

#
@app.post("/webhook/whatsapp")
async def receive_whatsapp_message(request: Request):
    """
    Endpoint Unificado: Recibe Mensajes (Texto) y Actualizaciones de Estado (Delivered/Read).
    """
    try:
        payload = await request.json()
        
        # 1. Extracción Segura de Datos (Navegación del JSON de Meta)
        # El JSON de Meta siempre viene anidado en entry -> changes -> value
        entry = payload.get('entry', [])
        if not entry:
            return {"status": "ignored", "reason": "no_entry"}
            
        changes = entry[0].get('changes', [])
        if not changes:
            return {"status": "ignored", "reason": "no_changes"}
            
        value = changes[0].get('value', {})
        
        # --- CASO A: ACTUALIZACIÓN DE ESTADO (CONFIRMACIÓN DE ENVÍO) ---
        # Aquí es donde verificas si el mensaje del ID 'wamid...' llegó.
        if 'statuses' in value:
            status_update = value['statuses'][0]
            msg_id = status_update.get('id')        # El ID 'wamid...' que viste en tu script
            status = status_update.get('status')    # sent, delivered, read, failed
            recipient = status_update.get('recipient_id')
            
            print(f"🚦 ESTADO ACTUALIZADO: ID={msg_id} | Status={status} | Para={recipient}")
            
            # (Opcional) Aquí podrías actualizar tu Base de Datos:
            # await db.update_message_status(msg_id, status)
            
            return {"status": "ack_status_update"}

        # --- CASO B: MENSAJE ENTRANTE (CLIENTE ESCRIBE) ---
        elif 'messages' in value:
            message = value['messages'][0]
            sender = message.get('from')
            msg_type = message.get('type')
            
            print(f"📩 MENSAJE RECIBIDO de {sender} ({msg_type})")
            
            # Aquí procesarías el texto o audio
            if msg_type == 'text':
                print(f"   Texto: {message['text']['body']}")
                
            return {"status": "message_received"}

        else:
            return {"status": "ignored", "reason": "unknown_event"}

    except Exception as e:
        print(f"❌ Error procesando Webhook: {e}")
        # Siempre responder 200 a Meta o te bloquearán el webhook
        return {"status": "error", "detail": str(e)}

@app.post("/webhook")
async def retell_webhook(request: Request, bg_tasks: BackgroundTasks):
    """
    Webhook Inteligente: Maneja payloads planos y estándar.
    Prioriza la detección de Agendamiento para evitar bucles en la conversación.
    """
    try:
        # 1. Leer el JSON crudo
        payload = await request.json()
        print(f"📥 PAYLOAD RECIBIDO: {payload}")

        # 2. Intentar extraer estructura estándar
        agent_id = payload.get('agent_id')
        func_name = payload.get('name') or payload.get('tool_name')
        args = payload.get('args')

        # --- MODO INFERENCIA (Si llega JSON plano) ---
        if not agent_id or not args:
            print("⚠️ Payload sin estructura estándar. Iniciando modo de inferencia...")
            
            # A. Asumimos que todo el payload son los argumentos
            args = payload
            
            # B. Asignamos el primer agente configurado por defecto (Fallback vital)
            try:
                agent_id = list(TENANTS.keys())[0]
                print(f"🔧 Usando agente por defecto (Fallback): {agent_id}")
            except:
                return {"result": "Error crítico: No hay agentes configurados en el sistema."}

            # C. LÓGICA DE INFERENCIA MEJORADA (PRIORIDAD ESTRICTA)
            keys = args.keys()
            
            # CASO 1: AGENDAR (Prioridad Máxima)
            # Si hay teléfono O (nombre Y fecha_hora), es un cierre.
            if 'cliente_telefono' in keys or ('cliente_nombre' in keys and 'fecha_hora_inicio' in keys):
                func_name = "book_appointment_and_notify"
            
            # CASO 2: BUSCAR INVENTARIO
            elif 'ciudad' in keys or 'tipo_operacion' in keys or 'presupuesto_max' in keys:
                func_name = "search_inventory"
            
            # CASO 3: CONSULTAR DISPONIBILIDAD (Solo si no es lo anterior)
            elif 'fecha' in keys or 'asesor_calendar_id' in keys:
                func_name = "check_calendar_availability"
            
            # Fallback final de inferencia
            elif 'presupuesto_max' in args: func_name = "search_inventory"
            elif 'cliente_telefono' in args: func_name = "book_appointment_and_notify"
            elif 'fecha' in args: func_name = "check_calendar_availability"
            
            print(f"🕵️ Función inferida: {func_name}")

        # 3. Validación final antes de ejecutar
        if not func_name:
            return {"result": "No pude entender qué función ejecutar con estos datos."}

        print(f"🔔 Ejecutando: {func_name} | Agent: {agent_id}")

        # --- EJECUCIÓN DE FUNCIONES ---

        if func_name == "search_inventory":
            return {"result": await inventory.search_inventory(agent_id, args)}

        if func_name == "check_calendar_availability":
            fecha = args.get('fecha')
            cal_id = args.get('asesor_calendar_id') or args.get('asesor_email')
            
            if not fecha:
                return {"result": "¿Para qué fecha te gustaría revisar?"}
            return {"result": await calendar.check_availability(agent_id, fecha, cal_id)}

        if func_name == "book_appointment_and_notify":
            if not args.get('cliente_telefono'):
                return {"result": "Necesito confirmar tu número de WhatsApp."}
            
            # Intento de Agendamiento
            success = await calendar.create_event_and_lock(agent_id, args)
            
            if success:
                bg_tasks.add_task(notifications.notify_all_parties, agent_id, args)
                bg_tasks.add_task(crm.log_lead_bg, agent_id, args)
                return {"result": "Listo, cita agendada y confirmación enviada."}
            else:
                try:
                    full_date = args.get('fecha_hora_inicio', '')
                    # Limpieza de fecha
                    date_only = full_date.split('T')[0] if 'T' in full_date else full_date
                    cal_id = args.get('asesor_calendar_id')
                    
                    alternativas = await calendar.check_availability(agent_id, date_only, cal_id)
                    return {"result": f"Ese horario ya está ocupado. {alternativas} ¿Alguna te sirve?"}
                except:
                    return {"result": "Ese horario ya está ocupado. ¿Te sirve otra hora?"}

        return {"result": f"Función {func_name} no encontrada."}

    except Exception as e:
        print(f"❌ ERROR FATAL: {str(e)}")
        # import traceback
        # traceback.print_exc()
        return {"result": "Tuve un error técnico interno."}