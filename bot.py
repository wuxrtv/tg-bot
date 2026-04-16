import os
import sys
import subprocess
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from openai import OpenAI
import logging
import uuid

# Configure logging
logging.basicConfig(
    format=\'%(asctime)s - %(name)s - %(levelname)s - %(message)s\
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Function to install dependencies
def install_dependencies():
    required_packages = ["python-telegram-bot", "openai"]
    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
        except ImportError:
            logger.info(f"Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            logger.info(f"{package} installed successfully.")

# 🔑 TOKENS
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Default OWNER_CHAT_ID if not set in environment variables
DEFAULT_OWNER_CHAT_ID = 7567850330  # Your provided chat ID
OWNER_CHAT_ID_ENV = os.environ.get("OWNER_CHAT_ID")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN not found in environment variables.")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in environment variables.")

if OWNER_CHAT_ID_ENV:
    try:
        OWNER_CHAT_ID = int(OWNER_CHAT_ID_ENV)
    except ValueError:
        logger.warning(f"OWNER_CHAT_ID from environment is not an integer: {OWNER_CHAT_ID_ENV}. Using default: {DEFAULT_OWNER_CHAT_ID}")
        OWNER_CHAT_ID = DEFAULT_OWNER_CHAT_ID
else:
    logger.info(f"OWNER_CHAT_ID not found in environment variables. Using default: {DEFAULT_OWNER_CHAT_ID}")
    OWNER_CHAT_ID = DEFAULT_OWNER_CHAT_ID

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

ОЧЕНЬ ВАЖНО: Отвечай на том языке, на котором задан вопрос (русский или узбекский). Если язык не определен, используй русский. Будь как человек, сначала познакомься, а потом предлагай услуги как очень мощный специалист.
"""
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
        logger.error(f"OpenAI error for user {user_id}: {e}")
        reply = "Извините, произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте ещё раз позже."

    user_histories[user_id].append({"role": "assistant", "content": reply})
    return reply


# 🔥 TEXT + LOGIC
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_message = update.message.text
        user_name = update.message.from_user.first_name
        user_id = update.message.from_user.id

        logger.info(f"User {user_id} ({user_name}) sent text: {user_message}")

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
                    logger.info(f"Lead from user {user_id} sent to OWNER_CHAT_ID.")
                except Exception as e:
                    logger.error(f"Lead parsing or sending error for user {user_id}: {e}")
                    await context.bot.send_message(
                        chat_id=OWNER_CHAT_ID,
                        text=f"""⚠️ Ошибка при парсинге/отправке лида от пользователя {user_id} ({user_name}): {e}
Исходный ответ GPT: {reply}"""
                    )

        else:
            await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"Error in handle_message for user {user_id}: {e}")
        await update.message.reply_text("Извините, произошла непредвиденная ошибка. Пожалуйста, попробуйте ещё раз.")


# 🎤 VOICE HANDLER
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name
    logger.info(f"User {user_id} ({user_name}) sent a voice message.")

    try:
        voice_file = await update.message.voice.get_file()
        file_path = f"voice_{user_id}_{uuid.uuid4()}.ogg"

        await voice_file.download_to_drive(file_path)
        logger.info(f"Voice file downloaded to {file_path}")

        with open(file_path, "rb") as audio:
            transcript = client.audio.transcriptions.create(
                model="whisper-1", # Corrected model name
                file=audio
            )

        text = transcript.text
        logger.info(f"Voice message transcribed for user {user_id}: {text}")

        # Clean up the voice file
        os.remove(file_path)
        logger.info(f"Voice file {file_path} removed.")

        # 👉 отправляем в текстовую логику
        # Create a dummy message object to pass to handle_message
        dummy_update = Update(update.update_id, message=update.message)
        dummy_update.message.text = text
        await handle_message(dummy_update, context)

    except Exception as e:
        logger.error(f"Error in handle_voice for user {user_id}: {e}")
        await update.message.reply_text("Не смог разобрать голосовое сообщение. Пожалуйста, попробуйте ещё раз или напишите текстом.")


# 🚀 START
def main():
    install_dependencies()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    logger.info("Бот запущен 🚀")
    app.run_polling()

if __name__ == \'__main__\':
    main()
