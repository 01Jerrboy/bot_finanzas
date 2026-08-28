import os
import json
import asyncio
from datetime import datetime
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from supabase import create_client, Client
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import Optional

# Mini servidor HTTP para satisfacer el escaneo de puertos de Render
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running 24/7!")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# Iniciar servidor web en un hilo secundario
Thread(target=run_health_server, daemon=True).start()

# Cargar variables de entorno
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0").strip())
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Inicializar clientes
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# Esquema para la IA
class FinancialEntry(BaseModel):
    tipo: str = Field(description="Uno de: 'GASTO_PROPIO', 'PRESTAMO_TERCERO', 'PAGO_RECIBIDO'")
    persona: Optional[str] = Field(default=None, description="Nombre de la persona involucrada si aplica (ej. Elsa, Alejandro, Jesús), o null si es gasto propio")
    tarjeta_o_medio: str = Field(default="Efectivo", description="Medio de pago: 'BCP', 'CMR Black', 'CMR', 'Yape', 'Efectivo'")
    descripcion: str = Field(description="Detalle o comercio")
    monto: float = Field(description="Monto numérico en soles")
    cuotas: int = Field(default=1, description="Número de cuotas")
    es_diferido: bool = Field(default=False, description="True si es una deuda sin fecha de cobro fija")
    mes_facturacion: Optional[str] = Field(default=None, description="Mes en formato YYYY-MM solo si el usuario lo menciona explícitamente")

SYSTEM_PROMPT = """
Eres un asistente financiero personal para control de gastos propios y préstamos de tarjetas.
Tu tarea es estructurar el mensaje del usuario en JSON según el esquema indicado.
Reglas:
1. Si el usuario dice "Pagué S/ X para [Persona]" o "Le compré a [Persona]", tipo = PRESTAMO_TERCERO.
2. Si el usuario dice "[Persona] me pagó S/ X" o "[Persona] me yapéo S/ X", tipo = PAGO_RECIBIDO.
3. Si el usuario solo menciona un consumo propio, tipo = GASTO_PROPIO.
4. Normaliza los nombres de personas conocidas: Elsa, Alejandro, Rubén, Esteban, Leonardo, Jesús, Tía Cielo.
5. Normaliza los medios de pago: BCP, CMR Black, CMR, Yape, Efectivo.
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    await update.message.reply_text(
        "👋 ¡Hola! Estoy listo para registrar tus gastos y cobranzas.\n\n"
        "Solo escríbeme con total naturalidad:\n"
        "• *'Pagué en Deltron S/ 1,450 con BCP para Elsa'*\n"
        "• *'Alejandro me pagó S/ 100 por Yape'*\n"
        "• *'Cené chifa S/ 25 con CMR'*",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    user_text = update.message.text
    await update.message.reply_chat_action("typing")

    try:
        now = datetime.now()
        current_date_str = now.strftime("%Y-%m-%d")
        current_month_str = now.strftime("%Y-%m")

        response = ai_client.models.generate_content(
            model='gemini-3.6-flash',
            contents=user_text,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=FinancialEntry,
                temperature=0.1
            )
        )
        
        data = json.loads(response.text)
        billing_month = data.get("mes_facturacion") or current_month_str
        
        db_payload = {
            "type": data.get("tipo"),
            "description": data.get("descripcion"),
            "amount": data.get("monto"),
            "installments": data.get("cuotas", 1),
            "transaction_date": current_date_str,
            "billing_month": billing_month,
            "is_deferred": data.get("es_diferido", False),
            "status": "COBRADO" if data.get("tipo") == "PAGO_RECIBIDO" else "PENDIENTE"
        }
        
        if data.get("persona"):
            contact_res = supabase.table("contacts").select("id").ilike("name", f"%{data['persona']}%").execute()
            if contact_res.data:
                db_payload["contact_id"] = contact_res.data[0]["id"]

        supabase.table("transactions").insert(db_payload).execute()

        tipo_str = {
            "PRESTAMO_TERCERO": "💳 <b>Préstamo de Tarjeta (Por Cobrar)</b>",
            "GASTO_PROPIO": "🛒 <b>Gasto Propio</b>",
            "PAGO_RECIBIDO": "💰 <b>Cobro Recibido</b>"
        }.get(data.get("tipo"), "Transacción")

        msg = (
            f"✅ <b>Registro Guardado con Éxito</b>\n\n"
            f"{tipo_str}\n"
            f"• <b>Concepto:</b> {data.get('descripcion')}\n"
            f"• <b>Monto:</b> S/ {data.get('monto'):,.2f}\n"
            f"• <b>Medio:</b> {data.get('tarjeta_o_medio', 'Efectivo')}\n"
            f"• <b>Involucrado:</b> {data.get('persona') or 'Personal'}\n"
            f"• <b>Fecha:</b> {current_date_str}\n"
            f"• <b>Mes:</b> {billing_month}\n"
        )
        if data.get("es_diferido"):
            msg += "\n⚠️ <i>Marcado como saldo diferido (sin fecha fija).</i>"

        await update.message.reply_text(msg, parse_mode="HTML")

    except Exception as e:
        await update.message.reply_text(f"❌ Error al procesar: {str(e)}")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot encendido y escuchando mensajes...")
    app.run_polling()
