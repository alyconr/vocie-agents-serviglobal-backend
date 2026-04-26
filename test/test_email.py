import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIGURACIÓN
# ============================================================
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

DESTINATARIO = "dicalop7@gmail.com"  # <--- Email destino para la prueba

# ============================================================
# CONTENIDO DEL EMAIL DE PRUEBA
# ============================================================
ASUNTO = "🧪 Test - Notificación Inmobiliaria"
CUERPO_HTML = """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <h2 style="color: #2c3e50;">✅ Email de Prueba</h2>
    <p>Este es un correo de verificación del servicio de notificaciones.</p>
    <hr style="border: 1px solid #eee;">
    <h3>Datos de Prueba:</h3>
    <ul>
        <li><strong>Cliente:</strong> Juan Pérez</li>
        <li><strong>Teléfono:</strong> +57 319 306 5230</li>
        <li><strong>Propiedad:</strong> Apartamento Poblado 301</li>
        <li><strong>Fecha:</strong> 28/04/2026 a las 10:00 AM</li>
        <li><strong>Asesor:</strong> María López</li>
    </ul>
    <hr style="border: 1px solid #eee;">
    <p style="color: #7f8c8d; font-size: 12px;">
        Enviado desde el sistema de notificaciones - Inmobiliaria Demo
    </p>
</div>
"""


def test_email():
    # 1. Validar credenciales
    print("=" * 50)
    print("🧪 TEST DE ENVÍO DE EMAIL (SMTP/Gmail)")
    print("=" * 50)

    print(f"\n📋 Configuración:")
    print(f"   Host:  {SMTP_HOST}")
    print(f"   Port:  {SMTP_PORT}")
    print(f"   From:  {SMTP_EMAIL}")
    print(f"   Pass:  {'***' + SMTP_PASSWORD[-4:] if SMTP_PASSWORD else '❌ NO CONFIGURADA'}")
    print(f"   To:    {DESTINATARIO}")

    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print("\n❌ Error: Faltan SMTP_EMAIL o SMTP_PASSWORD en el archivo .env")
        print("   Asegúrate de tener estas variables:")
        print("   SMTP_HOST=smtp.gmail.com")
        print("   SMTP_PORT=587")
        print("   SMTP_EMAIL=tu_email@gmail.com")
        print("   SMTP_PASSWORD=tu_contraseña_de_aplicacion")
        return

    # 2. Construir mensaje
    msg = MIMEMultipart()
    msg["From"] = f"Inmobiliaria Bot <{SMTP_EMAIL}>"
    msg["To"] = DESTINATARIO
    msg["Subject"] = ASUNTO
    msg.attach(MIMEText(CUERPO_HTML, "html", "utf-8"))

    # 3. Enviar
    print(f"\n📨 Conectando a {SMTP_HOST}:{SMTP_PORT}...")

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
        server.set_debuglevel(0)  # Cambia a 1 para ver logs SMTP detallados

        print("🔒 Iniciando TLS...")
        server.starttls()

        print("🔑 Autenticando...")
        server.login(SMTP_EMAIL, SMTP_PASSWORD)

        print(f"📤 Enviando a {DESTINATARIO}...")
        server.send_message(msg)

        server.quit()
        print(f"\n✅ ¡ÉXITO! Email enviado a {DESTINATARIO}")
        print("   Revisa tu bandeja de entrada (y spam).")

    except smtplib.SMTPAuthenticationError as e:
        print(f"\n❌ ERROR DE AUTENTICACIÓN: {e}")
        print("\n💡 Solución para Gmail:")
        print("   1. Ve a https://myaccount.google.com/apppasswords")
        print("   2. Genera una 'Contraseña de aplicación' para 'Correo'")
        print("   3. Usa esa contraseña (16 caracteres) como SMTP_PASSWORD")
        print("   ⚠️  NO uses tu contraseña normal de Gmail")

    except smtplib.SMTPConnectError as e:
        print(f"\n❌ ERROR DE CONEXIÓN: {e}")
        print("   Verifica que SMTP_HOST y SMTP_PORT sean correctos.")

    except TimeoutError:
        print(f"\n❌ TIMEOUT: No se pudo conectar a {SMTP_HOST}:{SMTP_PORT}")
        print("   Verifica tu conexión a internet y que el puerto no esté bloqueado.")

    except Exception as e:
        print(f"\n❌ ERROR: {type(e).__name__}: {e}")


if __name__ == "__main__":
    test_email()
