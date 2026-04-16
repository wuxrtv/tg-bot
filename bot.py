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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
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

DEFAULT_OWNER_CHAT_ID = 7567850330
OWNER_CHAT_ID_ENV = os.environ.get("OWNER_CHAT_ID")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN not found in environment variables.")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in environment variables.")

if OWNER_CHAT_ID_ENV:
    try:
        OWNER_CHAT_ID = int(OWNER_CHAT_ID_ENV)
    except ValueError:
        logger.warning("OWNER_CHAT_ID invalid. Using default.")
        OWNER_CHAT_ID = DEFAULT_OWNER_CHAT_ID
else:
    OWNER_CHAT_ID = DEFAULT_OWNER_CHAT_ID

client = OpenAI(api_key=OPENAI_API_KEY)

# 📊 MEMORY
user_histories = {}
sent_leads = set()

SYSTEM_PROMPT = """Ты топовый менеджер по продажам маркетингового агентства Virus Media..."""

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
        reply = "Извините, произошла ошибка. Попробуйте позже."

    user_histories[user_id].append({"role": "assistant", "content": reply})
    return reply


# 🔥 TEXT + LOGIC
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_message = update.message.text
        user_name = update.message.from_user.first_name
        user_id = update.message.from_user.id

        logger.info(f"User {user_id} ({user_name}): {user_message}")

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
                    logger.error(f"Lead error: {e}")

        else:
            await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"handle_message error: {e}")
        await update.message.reply_text("Ошибка, попробуйте ещё раз.")


# 🎤 VOICE HANDLER
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        voice_file = await update.message.voice.get_file()
        file_path = f"voice_{user_id}_{uuid.uuid4()}.ogg"

        await voice_file.download_to_drive(file_path)

        with open(file_path, "rb") as audio:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio
            )

        text = transcript.text

        os.remove(file_path)

        update.message.text = text
        await handle_message(update, context)

    except Exception as e:
        logger.error(f"Voice error: {e}")
        await update.message.reply_text("Не смог разобрать голосовое.")


# 🚀 START
def main():
    install_dependencies()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    logger.info("Бот запущен 🚀")
    app.run_polling()


if __name__ == "__main__":
    main()