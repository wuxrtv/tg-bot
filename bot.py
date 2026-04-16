import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from openai import OpenAI

# 🔑 КЛЮЧИ
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OWNER_CHAT_ID = 7567850330

if not TELEGRAM_TOKEN:
    raise ValueError("Нет TELEGRAM_TOKEN")

if not OPENAI_API_KEY:
    raise ValueError("Нет OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# 📊 СОСТОЯНИЕ
user_states = {}
user_histories = {}

# 🧠 GPT ПРОДАЖА
SYSTEM_PROMPT = """
Ты менеджер агентства Virus Media.

Отвечай ТОЛЬКО:
— на русском или узбекском (latin)
— коротко (1-2 предложения)
— всегда с вопросом

Услуги:
1. AI аватар (блог без съёмки)
2. Продвижение (рост через много аккаунтов)
3. AI агенты (автоматизация бизнеса)

Задача:
— усиливать интерес
— говорить через выгоду
— подводить к консультации
"""

# 🔥 GPT функция
async def ask_gpt(user_id, text):
    if user_id not in user_histories:
        user_histories[user_id] = []

    user_histories[user_id].append({
        "role": "user",
        "content": text
    })

    user_histories[user_id] = user_histories[user_id][-10:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + user_histories[user_id]

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages
        )
        reply = response.choices[0].message.content
    except Exception as e:
        print("Ошибка GPT:", e)
        return "Попробуйте ещё раз"

    user_histories[user_id].append({
        "role": "assistant",
        "content": reply
    })

    return reply


# 🔥 ОСНОВНАЯ ЛОГИКА
async def process(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    if user_id not in user_states:
        user_states[user_id] = {
            "step": "name",
            "data": {}
        }

    state = user_states[user_id]

    # 1️⃣ ИМЯ
    if state["step"] == "name":
        state["data"]["name"] = text
        state["step"] = "phone"

        reply = await ask_gpt(user_id, "Клиент оставил имя, задай вопрос про телефон")
        await update.message.reply_text(reply)
        return

    # 2️⃣ ТЕЛЕФОН
    elif state["step"] == "phone":
        state["data"]["phone"] = text
        state["step"] = "interest"

        reply = await ask_gpt(user_id, "Спроси что интересует: AI аватар, продвижение или AI агент")
        await update.message.reply_text(reply)
        return

    # 3️⃣ ИНТЕРЕС
    elif state["step"] == "interest":
        state["data"]["interest"] = text
        state["step"] = "format"

        reply = await ask_gpt(user_id, "Объясни пользу и спроси Zoom или офлайн")
        await update.message.reply_text(reply)
        return

    # 4️⃣ ФОРМАТ
    elif state["step"] == "format":
        state["data"]["format"] = text
        state["step"] = "time"

        reply = await ask_gpt(user_id, "Спроси удобное время встречи")
        await update.message.reply_text(reply)
        return

    # 5️⃣ ВРЕМЯ
    elif state["step"] == "time":
        state["data"]["time"] = text
        data = state["data"]

        await context.bot.send_message(
            chat_id=OWNER_CHAT_ID,
            text=f"""🔥 НОВЫЙ ЛИД!

👤 Имя: {data.get('name')}
📞 Телефон: {data.get('phone')}
💡 Интерес: {data.get('interest')}
📍 Формат: {data.get('format')}
🕐 Время: {data.get('time')}

🆔 ID: {user_id}
👤 Username: {user_name}"""
        )

        reply = await ask_gpt(user_id, "Поблагодари и скажи что менеджер свяжется")
        await update.message.reply_text(reply)

        user_states.pop(user_id)
        return


# 🔤 ТЕКСТ
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    await process(update, context, text)


# 🎤 ГОЛОС
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = await update.message.voice.get_file()
    file_path = "voice.ogg"
    await voice.download_to_drive(file_path)

    try:
        with open(file_path, "rb") as audio:
            transcript = client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=audio
            )
        text = transcript.text
    except Exception as e:
        print("Voice error:", e)
        await update.message.reply_text("Не понял голос")
        return

    await process(update, context, text)


# 🚀 ЗАПУСК
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(MessageHandler(filters.VOICE, handle_voice))

print("Бот работает 🚀")
app.run_polling()