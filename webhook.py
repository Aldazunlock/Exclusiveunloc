from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CallbackQueryHandler, CommandHandler
import os
from Exclusiveunloc import TelegramBot  # Importa tu clase TelegramBot

# Configuración del webhook
TOKEN = os.getenv('TOKEN', '7988514338:AAF5_fH0Ud9rjciNPee2kqpmUUDx7--IUj0')
WEBHOOK_URL = "https://exclusiveunloc.onrender.com/webhook"
PORT = int(os.environ.get('PORT', 10000))

async def webhook_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = TelegramBot()  # Instancia de tu bot
    if update.message:
        if update.message.text:
            if update.message.text.startswith('/'):
                command = update.message.text.split()[0][1:]
                if hasattr(bot, command):
                    await getattr(bot, command)(update, context)
                else:
                    await bot.handle_unknown_text(update, context)
            else:
                await bot.handle_unknown_text(update, context)
        elif update.message.document:
            await bot.recibir_archivo(update, context)
    elif update.callback_query:
        await bot.button_handler(update, context)

def main():
    # Crea la aplicación
    application = ApplicationBuilder().token(TOKEN).build()

    # Registra los handlers
    application.add_handler(CommandHandler("start", TelegramBot().start))
    application.add_handler(CommandHandler("search", TelegramBot().search))
    application.add_handler(CommandHandler("request", TelegramBot().request_file))
    application.add_handler(CommandHandler("add", TelegramBot().add))
    application.add_handler(CommandHandler("delete", TelegramBot().delete))
    application.add_handler(CommandHandler("list", TelegramBot().list_files))
    application.add_handler(CommandHandler("approve_request", TelegramBot().approve_request))
    application.add_handler(MessageHandler(filters.Document.ALL, TelegramBot().recibir_archivo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, TelegramBot().handle_unknown_text))
    application.add_handler(CallbackQueryHandler(TelegramBot().button_handler))

    # Configura el webhook
    if WEBHOOK_URL:
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
        )
        print(f"Webhook configurado en {WEBHOOK_URL}")
    else:
        application.run_polling()
        print("Modo polling activado")

if __name__ == "__main__":
    main()
