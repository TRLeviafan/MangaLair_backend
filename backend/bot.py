import asyncio
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes
from .settings import settings

def create_application() -> Application:
    if not settings.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")
    app = Application.builder().token(settings.BOT_TOKEN).build()

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(text="Открыть Mangalair — MiniApp", web_app=WebAppInfo(url=settings.FRONTEND_URL))
        ]])
        if update.message:
            await update.message.reply_text(
                "Добро пожаловать в Mangalair! Откройте мини-приложение кнопкой ниже.",
                reply_markup=kb
            )

    app.add_handler(CommandHandler("start", start))
    return app

async def run_bot(app: Application):
    # Proper polling for PTB v21.x
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=[])
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
