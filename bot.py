import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from openai import OpenAI

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OWNER_CHAT_ID = 7567850330

# 🔥 Проверка ключей
if not TELEGRAM_TOKEN:
    raise ValueError("Нет TELEGRAM_TOKEN")

if not OPENAI_API_KEY:
    raise ValueError("Нет OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

user_histories = {}
sent_leads = set()

SYSTEM_PROMPT = """Ты менеджер по продажам агентства Virus Media.

ГЛАВНОЕ:
— Отвечай ТОЛЬКО на русском или узбекском (uzbek latin)
— Если клиент пишет на русском — отвечай на русском
— Если клиент пишет на узбекском — отвечай на узбекском
— Если язык непонятен — отвечай на русском

СТИЛЬ:
— Пиши очень кратко (1-3 предложения)
— Без длинных объяснений
— Просто и по делу
— Всегда заканчивай вопросом

ПРОДАЖА:
— Делай акцент на выгоде
— Если сомневается — предложи бесплатную консультацию
— Если спрашивает цену — скажи: от $200, детали на консультации
— Создавай лёгкую срочность

СБОР ДАННЫХ (по шагам):
1. Имя
2. Телефон
3. Интерес
4. Удобное время

После получения всех данных напиши:
ДАННЫЕ_КЛИЕНТА: имя | телефон | интерес | время

И продолжи диалог коротко."""

# 🔥 Функция общения с GPT
async def ask_gpt(user_id, text):
    if user_id not in user_histories:
        user_histories[user_id] = []

    user_histories[user_id].append({"role": "user", "content": text})

    # ограничение памяти
    user_histories[user_id] = user_histories[user_id][-10:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + user_histories[user_id]

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages
        )
        reply = response.choices[0].message.content
    except Exception as e:
        print("Ошибка OpenAI:", e)
        return "⚠️ Временно ошибка сервера, попробуй позже"

    user_histories[user_id].append({"role": "assistant", "content": reply})
    return reply


# 🔥 ОБРАБОТКА ТЕКСТА
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name
    text = update.message.text

    reply = await ask_gpt(user_id, text)

    await process_reply(update, context, reply, user_id, user_name)


# 🔥 ОБРАБОТКА ГОЛОСА
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    voice = await update.message.voice.get_file()
    file_path = f"voice_{user_id}.ogg"
    await voice.download_to_drive(file_path)

    try:
        with open(file_path, "rb") as audio:
            transcript = client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=audio
            )

        text = transcript.text
    except Exception as e:
        print("Ошибка распознавания:", e)
        await update.message.reply_text("Не смог распознать голос 😢")
        return

    reply = await ask_gpt(user_id, text)

    await process_reply(update, context, reply, user_id, user_name)


# 🔥 ОБЩАЯ ЛОГИКА
async def process_reply(update, context, reply, user_id, user_name):
    if "ДАННЫЕ_КЛИЕНТА:" in reply:
        clean_reply = reply.split("ДАННЫЕ_КЛИЕНТА:")[0].strip()
        await update.message.reply_text(clean_reply)

        if user_id not in sent_leads:
            sent_leads.add(user_id)

            try:
                data = reply.split("ДАННЫЕ_КЛИЕНТА:")[1].strip()
                parts = data.split("|")

                name = parts[0].strip() if len(parts) > 0 else "—"
                phone = parts[1].strip() if len(parts) > 1 else "—"
                interests = parts[2].strip() if len(parts) > 2 else "—"
                time = parts[3].strip() if len(parts) > 3 else "—"

                await context.bot.send_message(
                    chat_id=OWNER_CHAT_ID,
                    text=f"""🔥 НОВЫЙ ЛИД!

👤 Имя: {name}
📞 Телефон: {phone}
💡 Интересы: {interests}
🕐 Время: {time}

🆔 Telegram ID: {user_id}
👤 Telegram имя: {user_name}"""
                )
            except Exception as e:
                print("Ошибка обработки лида:", e)
    else:
        await update.message.reply_text(reply)


# 🚀 ЗАПУСК
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(MessageHandler(filters.VOICE, handle_voice))

print("Бот запущен 🚀")
app.run_polling()