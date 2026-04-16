import os
import sys
import subprocess
import logging
import uuid

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from openai import OpenAI

# ──────────────────────────────────────────────
#  ЛОГИРОВАНИЕ
# ──────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  ТОКЕНЫ
# ──────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OWNER_CHAT_ID_ENV = os.environ.get("OWNER_CHAT_ID")
DEFAULT_OWNER_CHAT_ID = 7567850330  # ← твой chat_id

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не найден в переменных окружения.")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY не найден в переменных окружения.")

try:
    OWNER_CHAT_ID = int(OWNER_CHAT_ID_ENV) if OWNER_CHAT_ID_ENV else DEFAULT_OWNER_CHAT_ID
except ValueError:
    OWNER_CHAT_ID = DEFAULT_OWNER_CHAT_ID

client = OpenAI(api_key=OPENAI_API_KEY)


# ──────────────────────────────────────────────
#  СИСТЕМНЫЙ ПРОМПТ — РОБЕРТ
# ──────────────────────────────────────────────
SYSTEM_PROMPT = """
Ты — Роберт, старший менеджер по работе с клиентами маркетингового агентства Virus Media.
Ты живой, тёплый, уверенный человек. Говоришь просто, без канцелярита, как умный друг который разбирается в бизнесе.
Твоя цель — помочь клиенту вырасти, выстроить доверие и мягко привести к встрече.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ЯЗЫК ОБЩЕНИЯ:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Всегда отвечай ТОЛЬКО на русском или узбекском языке.
• Если клиент пишет на английском, казахском, турецком или любом другом языке — всё равно отвечай на русском.
• Определяй язык по контексту: если клиент явно пишет на узбекском — отвечай на узбекском, иначе — на русском.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
КТО ТЫ И ЧТО МЫ ПРЕДЛАГАЕМ:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Virus Media — агентство которое помогает бизнесам и личным брендам расти через три ключевых направления:

1️⃣ ЛИЧНЫЙ БРЕНД И ПРОДВИЖЕНИЕ В СОЦСЕТЯХ
   — Строим личный бренд предпринимателя или компании в Instagram, YouTube, TikTok и других платформах.
   — Создаём контент-стратегию, снимаем, монтируем, ведём аккаунты.
   — Результат: доверие аудитории → входящие заявки → рост продаж без холодных звонков.

2️⃣ ИИ-АГЕНТЫ И ИИ-АВАТАР ДЛЯ БИЗНЕСА
   — Создаём ИИ-агентов которые автоматизируют продажи, поддержку и маркетинг 24/7.
   — Создаём цифровой ИИ-аватар человека: он снимается в видео, создаёт контент, отвечает на вопросы — вместо живого владельца.
   — Результат: бизнес работает и масштабируется даже когда вы спите.

3️⃣ КОПИРАЙТИНГ И МАССОВОЕ ВЕДЕНИЕ АККАУНТОВ
   — Пишем продающие тексты, скрипты, посты, сценарии.
   — Ведём десятки, сотни и даже тысячи аккаунтов через ИИ — каждый аккаунт отвечает на сообщения, отправляет голосовые, вовлекает аудиторию.
   — Результат: масштабный охват и продажи на автопилоте.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
КАК ТЫ ВЕДЁШЬ ДИАЛОГ:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Сначала познакомься — узнай имя клиента (если он ещё не назвался).
• Спроси чем занимается его бизнес или какая у него цель.
• Выслушай — затем предложи подходящую услугу и объясни КОНКРЕТНУЮ ПОЛЬЗУ для его ситуации.
• Не перечисляй всё сразу. Сначала закрой одну потребность, потом мягко предложи смежную услугу.
• Upsell делай через пользу: "Кстати, раз вам важно X — у нас есть ещё одно направление которое усилит результат..."
• Всегда веди к встрече: живой или Zoom.
• Говори тепло, уверенно, по-человечески. Без роботских фраз типа "конечно!", "разумеется!", "я рад помочь!".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
СБОР ДАННЫХ КЛИЕНТА:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
По ходу разговора собирай:
• Имя клиента
• Чем интересуется (какая услуга)
• Номер телефона или способ связи
• Предпочтительный формат встречи (живая / Zoom)

Когда все 4 пункта собраны — в КОНЦЕ своего сообщения (после ответа клиенту) добавь строго в таком формате:
ДАННЫЕ_КЛИЕНТА: ИМЯ | ТЕЛЕФОН | ИНТЕРЕС | ФОРМАТ_ВСТРЕЧИ

Пример:
ДАННЫЕ_КЛИЕНТА: Алишер | +998901234567 | Личный бренд + ИИ-аватар | Zoom, вторник вечером

Эту строку НЕ показывай клиенту — она только для системы.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ВАЖНЫЕ ПРАВИЛА:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Никогда не говори что ты ИИ или бот. Ты — Роберт, живой сотрудник.
• Не давай общих советов по маркетингу бесплатно. Твоя цель — привести к встрече.
• Если клиент агрессивен или грубит — оставайся спокойным и профессиональным.
• Сообщения пиши коротко и по делу. Не более 4–5 предложений за раз.
• Используй эмодзи умеренно — 1–2 на сообщение максимум.
"""


# ──────────────────────────────────────────────
#  ПАМЯТЬ ПОЛЬЗОВАТЕЛЕЙ
# ──────────────────────────────────────────────
user_histories: dict[int, list] = {}
sent_leads: set[int] = set()


# ──────────────────────────────────────────────
#  GPT-ЗАПРОС
# ──────────────────────────────────────────────
async def ask_gpt(user_id: int, text: str) -> str:
    if user_id not in user_histories:
        user_histories[user_id] = []

    user_histories[user_id].append({"role": "user", "content": text})
    # Храним последние 20 сообщений (10 пар)
    user_histories[user_id] = user_histories[user_id][-20:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + user_histories[user_id]

    try:
        response = client.chat.completions.create(
            model="gpt-4o",          # Используем gpt-4o для качественных ответов
            messages=messages,
            temperature=0.75,        # Живость речи
            max_tokens=600,
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"OpenAI error (user {user_id}): {e}")
        reply = "Прошу прощения, что-то пошло не так. Напишите чуть позже, я скоро вернусь 🙏"

    user_histories[user_id].append({"role": "assistant", "content": reply})
    return reply


# ──────────────────────────────────────────────
#  ОТПРАВКА ЛИДА ВЛАДЕЛЬЦУ
# ──────────────────────────────────────────────
async def send_lead_to_owner(context: ContextTypes.DEFAULT_TYPE, user_id: int, user_name: str, raw_data: str):
    if user_id in sent_leads:
        return

    sent_leads.add(user_id)

    try:
        parts = [p.strip() for p in raw_data.split("|")]
        name     = parts[0] if len(parts) > 0 else "—"
        phone    = parts[1] if len(parts) > 1 else "—"
        interest = parts[2] if len(parts) > 2 else "—"
        meeting  = parts[3] if len(parts) > 3 else "—"

        await context.bot.send_message(
            chat_id=OWNER_CHAT_ID,
            text=(
                f"🔥 *НОВЫЙ ЛИД — Virus Media*\n\n"
                f"👤 Имя: {name}\n"
                f"📞 Телефон: {phone}\n"
                f"💡 Интерес: {interest}\n"
                f"📅 Встреча: {meeting}\n\n"
                f"─────────────────\n"
                f"🆔 Telegram ID: `{user_id}`\n"
                f"👤 Username: {user_name}"
            ),
            parse_mode="Markdown",
        )
        logger.info(f"Лид отправлен: {name} | {phone} | {interest}")
    except Exception as e:
        logger.error(f"Ошибка отправки лида: {e}")


# ──────────────────────────────────────────────
#  ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ
# ──────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_message = update.message.text
        user_name    = update.message.from_user.username or update.message.from_user.first_name
        user_id      = update.message.from_user.id

        if not user_message:
            return

        logger.info(f"[{user_id}] {user_name}: {user_message}")

        reply = await ask_gpt(user_id, user_message)

        # Проверяем наличие данных лида
        if "ДАННЫЕ_КЛИЕНТА:" in reply:
            clean_reply = reply.split("ДАННЫЕ_КЛИЕНТА:")[0].strip()
            raw_data    = reply.split("ДАННЫЕ_КЛИЕНТА:")[1].strip()

            await update.message.reply_text(clean_reply)
            await send_lead_to_owner(context, user_id, user_name, raw_data)
        else:
            await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"handle_message error: {e}")
        await update.message.reply_text("Что-то пошло не так. Напишите ещё раз, пожалуйста.")


# ──────────────────────────────────────────────
#  ОБРАБОТКА ГОЛОСОВЫХ СООБЩЕНИЙ
# ──────────────────────────────────────────────
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.message.from_user.id
    user_name = update.message.from_user.username or update.message.from_user.first_name

    try:
        # Скачиваем голосовое
        voice_file = await update.message.voice.get_file()
        file_path  = f"/tmp/voice_{user_id}_{uuid.uuid4().hex}.ogg"
        await voice_file.download_to_drive(file_path)

        # Транскрибируем через Whisper
        with open(file_path, "rb") as audio:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio,
                language=None,   # Автоопределение — Whisper поймёт русский/узбекский
            )

        os.remove(file_path)
        text = transcript.text.strip()

        if not text:
            await update.message.reply_text("Не смог разобрать голосовое, попробуйте написать текстом.")
            return

        logger.info(f"[VOICE] [{user_id}] {user_name}: {text}")

        # Передаём расшифровку в GPT как обычное сообщение
        reply = await ask_gpt(user_id, text)

        if "ДАННЫЕ_КЛИЕНТА:" in reply:
            clean_reply = reply.split("ДАННЫЕ_КЛИЕНТА:")[0].strip()
            raw_data    = reply.split("ДАННЫЕ_КЛИЕНТА:")[1].strip()
            await update.message.reply_text(clean_reply)
            await send_lead_to_owner(context, user_id, user_name, raw_data)
        else:
            await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"handle_voice error: {e}")
        await update.message.reply_text("Не смог обработать голосовое. Попробуйте написать текстом 🙏")


# ──────────────────────────────────────────────
#  ЗАПУСК
# ──────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    logger.info("✅ Бот Роберт запущен и ждёт клиентов...")
    app.run_polling()


if __name__ == "__main__":
    main()