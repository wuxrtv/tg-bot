import os
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
DEFAULT_OWNER_CHAT_ID = 7567850330

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не найден.")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY не найден.")

try:
    OWNER_CHAT_ID = int(OWNER_CHAT_ID_ENV) if OWNER_CHAT_ID_ENV else DEFAULT_OWNER_CHAT_ID
except ValueError:
    OWNER_CHAT_ID = DEFAULT_OWNER_CHAT_ID

client = OpenAI(api_key=OPENAI_API_KEY)

# ──────────────────────────────────────────────
#  СИСТЕМНЫЙ ПРОМПТ
# ──────────────────────────────────────────────
SYSTEM_PROMPT = """
Ты — Роберт, старший менеджер по работе с клиентами маркетингового агентства Virus Media.
Ты живой, тёплый, уверенный человек. Говоришь просто и по делу.
Никогда не говори что ты бот или ИИ. Ты — Роберт, живой сотрудник.

━━━━━━━━━━━━━━━━━━
ЯЗЫК — ГЛАВНОЕ ПРАВИЛО:
━━━━━━━━━━━━━━━━━━
• Определи язык по ПЕРВОМУ сообщению клиента.
• Если клиент написал на РУССКОМ — отвечай на русском и спроси:
  "Продолжим на русском языке?"
• Если клиент написал на УЗБЕКСКОМ — отвечай на узбекском и спроси:
  "O'zbek tilida davom etamizmi?"
• Если клиент написал на ЛЮБОМ ДРУГОМ языке (английский, китайский, турецкий и т.д.) —
  отвечай на русском и спроси: "Продолжим на русском или предпочитаете узбекский?"
• После подтверждения языка — общайся ТОЛЬКО на нём до конца диалога.
• НИКОГДА не пиши одно сообщение сразу на двух языках.

━━━━━━━━━━━━━━━━━━
ПОРЯДОК ДИАЛОГА:
━━━━━━━━━━━━━━━━━━

ШАГ 1 — ПЕРВОЕ СООБЩЕНИЕ:
Определи язык → поздоровайся → представься как Роберт → спроси подтверждение языка.
Пример (клиент написал на русском):
"Привет! Меня зовут Роберт 👋 Продолжим на русском языке?"

ШАГ 2 — ПОСЛЕ ПОДТВЕРЖДЕНИЯ ЯЗЫКА:
Спроси имя. Коротко и тепло.
Пример: "Отлично! Как вас зовут?"

ШАГ 3 — ПОСЛЕ ИМЕНИ:
Поздоровайся по имени. Задай ОДИН вопрос — узнай чем занимается человек или что его интересует.
Не перечисляй услуги. Просто слушай.

ШАГ 4 — ВЫЯВЛЕНИЕ ПОТРЕБНОСТИ:
Задай уточняющий вопрос чтобы понять главную боль или цель клиента.
Только потом предложи ОДНУ подходящую услугу — коротко, 2–3 предложения.

━━━━━━━━━━━━━━━━━━
НАШИ УСЛУГИ (подавай по одной, постепенно):
━━━━━━━━━━━━━━━━━━

1️⃣ ЛИЧНЫЙ БРЕНД И СОЦСЕТИ
Строим личный бренд в Instagram, YouTube, TikTok.
Результат: аудитория доверяет → заявки приходят сами, без холодных звонков.

2️⃣ ИИ-АГЕНТЫ И ИИ-АВАТАР
ИИ-агенты автоматизируют продажи и поддержку 24/7.
Цифровой аватар снимается в видео и создаёт контент вместо владельца.
Результат: бизнес работает пока вы занимаетесь другим.

3️⃣ КОПИРАЙТИНГ И МАССОВЫЕ АККАУНТЫ
Продающие тексты, сценарии, посты.
Ведём сотни и тысячи аккаунтов через ИИ — каждый отвечает, вовлекает, продаёт.
Результат: огромный охват на автопилоте.

━━━━━━━━━━━━━━━━━━
UPSELL — ПЛАВНО:
━━━━━━━━━━━━━━━━━━
После того как человек заинтересовался одной услугой — мягко упомяни смежную через пользу:
"Кстати, раз для вас важен [результат] — есть ещё одно направление которое хорошо это усиливает. Интересно?"
Жди ответа. Не перечисляй всё сразу.

━━━━━━━━━━━━━━━━━━
ВСТРЕЧА:
━━━━━━━━━━━━━━━━━━
Когда человек достаточно заинтересован — предложи встречу:
"Давайте созвонимся, расскажу подробнее и посмотрим что подойдёт именно вам.
Вам удобнее живая встреча или Zoom?"

Когда человек назвал формат и время — скажи:
"Отлично, [время] записал. Уточню у руководства и напишу вам подтверждение."

Затем добавь в конец сообщения (НЕВИДИМО для клиента):
СОГЛАСОВАНИЕ_ВРЕМЕНИ: ИМЯ | ВРЕМЯ | ФОРМАТ

━━━━━━━━━━━━━━━━━━
СБОР ДАННЫХ ЛИДА:
━━━━━━━━━━━━━━━━━━
Когда собраны все 5 пунктов (имя, контакт, интерес, формат, время) —
добавь в конец сообщения (НЕВИДИМО для клиента):
ДАННЫЕ_КЛИЕНТА: ИМЯ | КОНТАКТ | ИНТЕРЕС | ФОРМАТ | ВРЕМЯ

━━━━━━━━━━━━━━━━━━
СТИЛЬ:
━━━━━━━━━━━━━━━━━━
• Сообщения короткие — максимум 3–4 предложения.
• Один вопрос в конце сообщения.
• Эмодзи — 1–2 максимум.
• Без фраз: "конечно!", "разумеется!", "я рад помочь!", "отличный вопрос!".
• Бесплатных советов не давай — цель встреча, не консультация.
• Если клиент грубит — остаёшься спокойным и профессиональным.
"""

# ──────────────────────────────────────────────
#  ПАМЯТЬ
# ──────────────────────────────────────────────
user_histories: dict[int, list] = {}
sent_leads: set[int] = set()
processed_messages: set[int] = set()   # защита от дублей по message_id


# ──────────────────────────────────────────────
#  GPT
# ──────────────────────────────────────────────
async def ask_gpt(user_id: int, text: str) -> str:
    if user_id not in user_histories:
        user_histories[user_id] = []

    user_histories[user_id].append({"role": "user", "content": text})
    user_histories[user_id] = user_histories[user_id][-24:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + user_histories[user_id]

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.75,
            max_tokens=500,
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"OpenAI error (user {user_id}): {e}")
        reply = "Прошу прощения, что-то пошло не так. Напишите чуть позже 🙏"

    user_histories[user_id].append({"role": "assistant", "content": reply})
    return reply


# ──────────────────────────────────────────────
#  ОТПРАВКА ЛИДА
# ──────────────────────────────────────────────
async def send_lead_to_owner(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    tg_username: str,
    raw_data: str,
):
    if user_id in sent_leads:
        return
    sent_leads.add(user_id)

    try:
        parts    = [p.strip() for p in raw_data.split("|")]
        name     = parts[0] if len(parts) > 0 else "—"
        contact  = parts[1] if len(parts) > 1 else "—"
        interest = parts[2] if len(parts) > 2 else "—"
        fmt      = parts[3] if len(parts) > 3 else "—"
        time     = parts[4] if len(parts) > 4 else "—"

        await context.bot.send_message(
            chat_id=OWNER_CHAT_ID,
            text=(
                f"🔥 *НОВЫЙ ЛИД — Virus Media*\n\n"
                f"👤 Имя: {name}\n"
                f"📞 Контакт: {contact}\n"
                f"💡 Интерес: {interest}\n"
                f"📅 Формат: {fmt}\n"
                f"🕐 Время: {time}\n\n"
                f"─────────────────\n"
                f"🆔 Telegram ID: `{user_id}`\n"
                f"👤 Username: @{tg_username}"
            ),
            parse_mode="Markdown",
        )
        logger.info(f"Лид: {name} | {contact} | {interest} | {fmt} | {time}")
    except Exception as e:
        logger.error(f"Ошибка отправки лида: {e}")


# ──────────────────────────────────────────────
#  ЗАПРОС НА СОГЛАСОВАНИЕ ВРЕМЕНИ
# ──────────────────────────────────────────────
async def send_time_request(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    tg_username: str,
    raw_data: str,
):
    try:
        parts = [p.strip() for p in raw_data.split("|")]
        name  = parts[0] if len(parts) > 0 else "—"
        time  = parts[1] if len(parts) > 1 else "—"
        fmt   = parts[2] if len(parts) > 2 else "—"

        await context.bot.send_message(
            chat_id=OWNER_CHAT_ID,
            text=(
                f"📅 *ЗАПРОС НА ВСТРЕЧУ*\n\n"
                f"👤 Клиент: {name}\n"
                f"🕐 Желаемое время: {time}\n"
                f"📍 Формат: {fmt}\n\n"
                f"🆔 Telegram ID: `{user_id}`\n"
                f"👤 Username: @{tg_username}\n\n"
                f"✅ Подходит → подтвердите клиенту\n"
                f"❌ Не подходит → предложите другое время"
            ),
            parse_mode="Markdown",
        )
        logger.info(f"Встреча: {name} | {time} | {fmt}")
    except Exception as e:
        logger.error(f"Ошибка отправки запроса на встречу: {e}")


# ──────────────────────────────────────────────
#  ОБРАБОТКА ОТВЕТА GPT
# ──────────────────────────────────────────────
async def process_reply(
    reply: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    tg_username: str,
):
    clean = reply

    if "ДАННЫЕ_КЛИЕНТА:" in clean:
        idx   = clean.index("ДАННЫЕ_КЛИЕНТА:")
        raw   = clean[idx + len("ДАННЫЕ_КЛИЕНТА:"):].split("\n")[0].strip()
        clean = clean[:idx].strip()
        await send_lead_to_owner(context, user_id, tg_username, raw)

    if "СОГЛАСОВАНИЕ_ВРЕМЕНИ:" in clean:
        idx   = clean.index("СОГЛАСОВАНИЕ_ВРЕМЕНИ:")
        raw   = clean[idx + len("СОГЛАСОВАНИЕ_ВРЕМЕНИ:"):].split("\n")[0].strip()
        clean = clean[:idx].strip()
        await send_time_request(context, user_id, tg_username, raw)

    if clean:
        await update.message.reply_text(clean)


# ──────────────────────────────────────────────
#  ТЕКСТОВЫЕ СООБЩЕНИЯ
# ──────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message_id = update.message.message_id

        # ✅ Защита от дублей — пропускаем уже обработанные message_id
        if message_id in processed_messages:
            logger.warning(f"Дубль message_id={message_id}, пропускаем.")
            return
        processed_messages.add(message_id)

        # Не даём сету расти бесконечно
        if len(processed_messages) > 10000:
            processed_messages.clear()

        user_message = update.message.text
        user_name    = update.message.from_user.username or update.message.from_user.first_name or "unknown"
        user_id      = update.message.from_user.id

        if not user_message:
            return

        logger.info(f"[TEXT] [{user_id}] @{user_name}: {user_message}")

        reply = await ask_gpt(user_id, user_message)
        await process_reply(reply, update, context, user_id, user_name)

    except Exception as e:
        logger.error(f"handle_message error: {e}")
        await update.message.reply_text("Что-то пошло не так. Напишите ещё раз, пожалуйста.")


# ──────────────────────────────────────────────
#  ГОЛОСОВЫЕ СООБЩЕНИЯ
# ──────────────────────────────────────────────
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message_id = update.message.message_id

        # ✅ Защита от дублей
        if message_id in processed_messages:
            logger.warning(f"Дубль voice message_id={message_id}, пропускаем.")
            return
        processed_messages.add(message_id)

        if len(processed_messages) > 10000:
            processed_messages.clear()

        user_id   = update.message.from_user.id
        user_name = update.message.from_user.username or update.message.from_user.first_name or "unknown"

        voice_file = await update.message.voice.get_file()
        file_path  = f"/tmp/voice_{user_id}_{uuid.uuid4().hex}.ogg"
        await voice_file.download_to_drive(file_path)

        with open(file_path, "rb") as audio:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio,
            )

        os.remove(file_path)
        text = transcript.text.strip()

        if not text:
            await update.message.reply_text(
                "Не смог разобрать голосовое — попробуйте написать текстом."
            )
            return

        logger.info(f"[VOICE] [{user_id}] @{user_name}: {text}")

        reply = await ask_gpt(user_id, text)
        await process_reply(reply, update, context, user_id, user_name)

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
    logger.info("✅ Роберт запущен и готов к работе...")
    app.run_polling()


if __name__ == "__main__":
    main()