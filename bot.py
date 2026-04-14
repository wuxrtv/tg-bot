import os
import tempfile
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from openai import OpenAI

# Настройки (убедитесь, что токены в кавычках, если вставляете их сюда напрямую)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OWNER_CHAT_ID = 7567850330 

client = OpenAI(api_key=OPENAI_API_KEY)
user_histories = {}

SYSTEM_PROMPT = "Ты менеджер Virus Media. Твоя цель — продать услуги агентства. Отвечай кратко и вежливо."

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.message.from_user.id
    user_text = update.message.text

    if user_id not in user_histories: user_histories[user_id] = []
    user_histories[user_id].append({"role": "user", "content": user_text})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + user_histories[user_id]
    )
    reply = response.choices[0].message.content
    user_histories[user_id].append({"role": "assistant", "content": reply})
    await update.message.reply_text(reply)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = update.message.voice
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        file_path = tmp.name
    try:
        # Скачиваем голосовое сообщение
        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(file_path)
        # Переводим в текст через Whisper
        with open(file_path, "rb") as audio:
            transcript = client.audio.transcriptions.create(model="whisper-1", file=audio)
        
        user_text = transcript.text
        await update.message.reply_text(f"🎤 Распознано: {user_text}")
        
        # Передаем текст в основной обработчик
        update.message.text = user_text
        await handle_message(update, context)
    finally:
        if os.path.exists(file_path): os.remove(file_path)

if name == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("Бот запущен и готов к работе!")
    app.run_polling()