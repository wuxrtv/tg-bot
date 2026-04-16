import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from openai import OpenAI

# 🔑 TOKENS
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OWNER_CHAT_ID = 7567850330

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN not found")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found")

client = OpenAI(api_key=OPENAI_API_KEY)

# 📊 MEMORY
user_histories = {}
sent_leads = set()

SYSTEM_PROMPT = """Ты топовый менеджер по продажам маркетингового агентства Virus Media. Твоя главная цель — ПРОДАТЬ услуги и записать клиента на консультацию.

НАШИ УСЛУГИ:

1. AI-АВАТАР ДЛЯ БЛОГА
— Создаём цифрового аватара человека на основе его внешности и голоса
— Аватар ведёт блог от лица клиента без его участия
— Клиент зарабатывает и растёт в соцсетях пока спит!

2. ВЕДЕНИЕ АККАУНТОВ (КЛИПИНГ)
— Берём контент клиента и распространяем на 10-20 аккаунтах одновременно
— Клиент растёт в 10-20 раз быстрее конкурентов
— Работаем с Instagram, TikTok, YouTube Shorts, Telegram

3. КОМПЛЕКСНОЕ ПРОДВИЖЕНИЕ
— AI-аватар + клипинг на множестве аккаунтов
— Полное ведение без участия клиента

ПРАВИЛА ПРОДАЖ:
— Всегда подчёркивай выгоду для клиента
— Создавай срочность — говори что места ограничены
— Если клиент сомневается — предложи БЕСПЛАТНУЮ консультацию
— Если спрашивают цену — скажи от $200 но сначала нужна консультация
— Всегда заканчивай вопросом чтобы продолжить диалог
— Никогда не сдавайся — если клиент говорит нет найди другой аргумент

СБОР ДАННЫХ — делай по порядку:
1. Сначала спроси ИМЯ
2. Потом спроси НОМЕР ТЕЛЕФОНА
3. Потом спроси что именно интересует
4. Потом спроси УДОБНОЕ ВРЕМЯ для консультации
5. Когда получишь все четыре данных напиши в конце: ДАННЫЕ_КЛИЕНТА: [имя] | [телефон] | [интересы] | [время]
6. После этого продолжай разговор — поблагодари и скажи что менеджер свяжется в указанное время

важно на коком языке был задан вопрос Отвечай на узбекском или  русском  """
# 🧠 GPT
async def ask_gpt(user_id, text):
    if user_id not in user_histories:
        user_histories[user_id] = []

    user_histories[user_id].append({"role": "user", "content": text})
    user_histories[user_id] = user_histories[user_id][-10:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + user_histories[user_id]

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages
        )
        reply = response.choices[0].message.content
    except Exception as e:
        print("OpenAI error:", e)
        reply = "Попробуйте ещё раз позже"

    user_histories[user_id].append({"role": "assistant", "content": reply})
    return reply


# 🔥 TEXT + LOGIC
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_message = update.message.text
        user_name = update.message.from_user.first_name
        user_id = update.message.from_user.id

        if not user_message:
            return

        reply = await ask_gpt(user_id, user_message)

        if "ДАННЫЕ_КЛИЕНТА:" in reply:
            clean_reply = reply.split("ДАННЫЕ_КЛИЕНТА:")[0].strip()
            await update.message.reply_text(clean_reply)

            if user_id not in sent_leads:
                sent_leads.add(user_id)

                try:
                    data = reply.split("ДАННЫЕ_КЛИЕНТА:")[1].strip()
                    parts = [x.strip() for x in data.split("|")]

                    name = parts[0] if len(parts) > 0 else "—"
                    phone = parts[1] if len(parts) > 1 else "—"
                    interest = parts[2] if len(parts) > 2 else "—"
                    time = parts[3] if len(parts) > 3 else "—"

                    await context.bot.send_message(
                        chat_id=OWNER_CHAT_ID,
                        text=f"""🔥 НОВЫЙ ЛИД!

👤 Имя: {name}
📞 Телефон: {phone}
💡 Интерес: {interest}
🕐 Время: {time}

🆔 ID: {user_id}
👤 Имя: {user_name}"""
                    )
                except Exception as e:
                    print("Lead parsing error:", e)

        else:
            await update.message.reply_text(reply)

    except Exception as e:
        print("Handler error:", e)


# 🎤 VOICE HANDLER
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        voice_file = await update.message.voice.get_file()
        file_path = "voice.ogg"

        await voice_file.download_to_drive(file_path)

        with open(file_path, "rb") as audio:
            transcript = client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=audio
            )

        text = transcript.text

        # 👉 отправляем в текстовую логику
        update.message.text = text
        await handle_message(update, context)

    except Exception as e:
        print("Voice error:", e)
        await update.message.reply_text("Не смог разобрать голосовое")


# 🚀 START
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(MessageHandler(filters.VOICE, handle_voice))

print("Бот запущен 🚀")
app.run_polling()