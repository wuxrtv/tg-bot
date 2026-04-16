import os
import logging
import uuid
import asyncio

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
ЯЗЫК:
━━━━━━━━━━━━━━━━━━
• Определи язык по ПЕРВОМУ сообщению клиента.
• Клиент написал на РУССКОМ → отвечай на русском, спроси: "Продолжим на русском языке?"
• Клиент написал на УЗБЕКСКОМ → отвечай на узбекском, спроси: "O'zbek tilida davom etamizmi?"
• Клиент написал на ЛЮБОМ ДРУГОМ языке → отвечай на русском, спроси: "Продолжим на русском или предпочитаете узбекский?"
• После подтверждения — общайся ТОЛЬКО на выбранном языке до конца.
• НИКОГДА не пиши одно сообщение сразу на двух языках.

━━━━━━━━━━━━━━━━━━
ПОРЯДОК ДИАЛОГА:
━━━━━━━━━━━━━━━━━━

ШАГ 1 — ПЕРВОЕ СООБЩЕНИЕ:
Поздоровайся, представься как Роберт, спроси подтверждение языка.
Пример: "Привет! Меня зовут Роберт 👋 Продолжим на русском языке?"

ШАГ 2 — ПОСЛЕ ПОДТВЕРЖДЕНИЯ ЯЗЫКА:
Спроси имя коротко: "Отлично! Как вас зовут?"

ШАГ 3 — ПОСЛЕ ИМЕНИ:
Поздоровайся по имени. Спроси чем занимается человек или что его интересует. Не перечисляй услуги.

ШАГ 4 — ВЫЯВЛЕНИЕ ПОТРЕБНОСТИ:
Задай уточняющий вопрос чтобы понять боль клиента.
Потом предложи ОДНУ подходящую услугу — коротко, 2–3 предложения. Жди реакции.

━━━━━━━━━━━━━━━━━━
НАШИ УСЛУГИ (подавай по одной, постепенно):
━━━━━━━━━━━━━━━━━━

1️⃣ ЛИЧНЫЙ БРЕНД И СОЦСЕТИ
Строим личный бренд в Instagram, YouTube, TikTok.
Результат: аудитория доверяет → заявки приходят сами, без холодных звонков.

2️⃣ ИИ-АГЕНТЫ И ИИ-АВАТАР
ИИ-агенты автоматизируют продажи и поддержку 24/7.
Цифровой аватар снимается в видео и создаёт контент вместо владельца.
Результат: бизнес работает и масштабируется пока вы занимаетесь другим.

3️⃣ КОПИРАЙТИНГ И МАССОВЫЕ АККАУНТЫ
Продающие тексты, сценарии, посты.
Ведём сотни и тысячи аккаунтов через ИИ — каждый отвечает, вовлекает, продаёт.
Результат: огромный охват на автопилоте.

━━━━━━━━━━━━━━━━━━
UPSELL — ПЛАВНО:
━━━━━━━━━━━━━━━━━━
После интереса к одной услуге — мягко предложи смежную:
"Кстати, раз для вас важен [результат] — есть ещё одно направление которое хорошо это усиливает. Интересно?"
Жди ответа. Не вали всё сразу.

━━━━━━━━━━━━━━━━━━
ВСТРЕЧА:
━━━━━━━━━━━━━━━━━━
Когда клиент заинтересован — предложи встречу:
"Давайте созвонимся, расскажу подробнее и посмотрим что подойдёт именно вам. Вам удобнее живая встреча или Zoom?"

Когда клиент назвал формат и время — скажи:
"Отлично, [время] записал. Уточню у руководства и напишу вам подтверждение."

Затем В САМОМ КОНЦЕ своего сообщения добавь (клиент это НЕ увидит):
СОГЛАСОВАНИЕ_ВРЕМЕНИ: ИМЯ | ВРЕМЯ | ФОРМАТ

━━━━━━━━━━━━━━━━━━
СБОР ЛИДА — ОЧЕНЬ ВАЖНО:
━━━━━━━━━━━━━━━━━━
По ходу диалога собирай: имя, контакт (телефон или Telegram), интерес, формат встречи, время.

Как только собраны ВСЕ 5 пунктов — В САМОМ КОНЦЕ своего сообщения добавь (клиент это НЕ увидит):
ДАННЫЕ_КЛИЕНТА: ИМЯ | КОНТАКТ | ИНТЕРЕС | ФОРМАТ | ВРЕМЯ

Пример:
ДАННЫЕ_КЛИЕНТА: Алишер | +998901234567 | Личный бренд | Zoom | Вторник 10:00

ВАЖНО: эта строка должна быть на отдельной строке в самом конце. Никакого текста после неё.

━━━━━━━━━━━━━━━━━━
СТИЛЬ:
━━━━━━━━━━━━━━━━━━
• Максимум 3–4 предложения за раз.
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
LEADS_FILE = "sent_leads.txt"

def load_sent_leads() -> set:
    if os.path.exists(LEADS_FILE):
        with open(LEADS_FILE, "r") as f:
            return set(int(line.strip()) for line in f if line.strip())
    return set()

def save_lead(user_id: int):
    with open(LEADS_FILE, "a") as f:
        f.write(f"{user_id}\n")

sent_leads: set[int] = load_sent_leads()
user_locks: dict[int, asyncio.Lock] = {}  # 🔒 защита от дублей


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
#  ОТПРАВКА ЛИДА — ИСПРАВЛЕННАЯ ВЕРСИЯ
# ──────────────────────────────────────────────
async def send_lead_to_owner(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    tg_username: str,
    raw_data: str,
):
    if user_id in sent_leads:
        logger.info(f"Лид {user_id} уже был отправлен ранее, пропускаем.")
        sent_leads.add(user_id)
        save_lead(user_id)
        return
    try:
    # Разрешаем повторную отправку если данные обновились (убрали блок sent_leads)
    try:
        parts    = [p.strip() for p in raw_data.split("|")]
        name     = parts[0] if len(parts) > 0 else "—"
        contact  = parts[1] if len(parts) > 1 else "—"
        interest = parts[2] if len(parts) > 2 else "—"
        fmt      = parts[3] if len(parts) > 3 else "—"
        time     = parts[4] if len(parts) > 4 else "—"

        logger.info(f"Отправляем лида: {name} | {contact} | {interest} | {fmt} | {time}")

        await context.bot.send_message(
            chat_id=OWNER_CHAT_ID,
            text=(
                f"🔥 НОВЫЙ ЛИД — Virus Media\n\n"
                f"👤 Имя: {name}\n"
                f"📞 Контакт: {contact}\n"
                f"💡 Интерес: {interest}\n"
                f"📅 Формат: {fmt}\n"
                f"🕐 Время: {time}\n\n"
                f"─────────────────\n"
                f"🆔 Telegram ID: {user_id}\n"
                f"👤 Username: @{tg_username}"
            ),
        )
        logger.info(f"✅ Лид отправлен успешно: {name}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки лида: {e}")


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
                f"📅 ЗАПРОС НА ВСТРЕЧУ\n\n"
                f"👤 Клиент: {name}\n"
                f"🕐 Желаемое время: {time}\n"
                f"📍 Формат: {fmt}\n\n"
                f"🆔 Telegram ID: {user_id}\n"
                f"👤 Username: @{tg_username}\n\n"
                f"✅ Подходит → подтвердите клиенту\n"
                f"❌ Не подходит → предложите другое время"
            ),
        )
        logger.info(f"📅 Запрос на встречу отправлен: {name} | {time} | {fmt}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки запроса на встречу: {e}")


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
    logger.info(f"Полный ответ GPT: {repr(clean)}")

    # Извлекаем ДАННЫЕ_КЛИЕНТА
    if "ДАННЫЕ_КЛИЕНТА:" in clean:
        idx   = clean.index("ДАННЫЕ_КЛИЕНТА:")
        raw   = clean[idx + len("ДАННЫЕ_КЛИЕНТА:"):].split("\n")[0].strip()
        clean = clean[:idx].strip()
        logger.info(f"Найден лид: {raw}")
        await send_lead_to_owner(context, user_id, tg_username, raw)

    # Извлекаем СОГЛАСОВАНИЕ_ВРЕМЕНИ
    if "СОГЛАСОВАНИЕ_ВРЕМЕНИ:" in clean:
        idx   = clean.index("СОГЛАСОВАНИЕ_ВРЕМЕНИ:")
        raw   = clean[idx + len("СОГЛАСОВАНИЕ_ВРЕМЕНИ:"):].split("\n")[0].strip()
        clean = clean[:idx].strip()
        await send_time_request(context, user_id, tg_username, raw)

    if clean:
        await update.message.reply_text(clean)


# ──────────────────────────────────────────────
#  ОБЩАЯ ФУНКЦИЯ ОБРАБОТКИ ВХОДЯЩЕГО ТЕКСТА
# ──────────────────────────────────────────────
async def process_user_input(
    text: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id   = update.message.from_user.id
    user_name = update.message.from_user.username or update.message.from_user.first_name or "unknown"

    # 🔒 Получаем или создаём лок для этого пользователя
    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()

    # Если уже обрабатываем запрос от этого пользователя — пропускаем
    if user_locks[user_id].locked():
        logger.warning(f"[{user_id}] Запрос уже обрабатывается, дубль пропущен.")
        return

    async with user_locks[user_id]:
        reply = await ask_gpt(user_id, text)
        await process_reply(reply, update, context, user_id, user_name)


# ──────────────────────────────────────────────
#  ТЕКСТОВЫЕ СООБЩЕНИЯ
# ──────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_message = update.message.text
        if not user_message:
            return

        user_id   = update.message.from_user.id
        user_name = update.message.from_user.username or update.message.from_user.first_name or "unknown"
        logger.info(f"[TEXT] [{user_id}] @{user_name}: {user_message}")

        await process_user_input(user_message, update, context)

    except Exception as e:
        logger.error(f"handle_message error: {e}")
        await update.message.reply_text("Что-то пошло не так. Напишите ещё раз, пожалуйста.")


# ──────────────────────────────────────────────
#  ГОЛОСОВЫЕ СООБЩЕНИЯ
# ──────────────────────────────────────────────
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.message.from_user.id
    user_name = update.message.from_user.username or update.message.from_user.first_name or "unknown"

    try:
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
            await update.message.reply_text("Не смог разобрать голосовое — попробуйте написать текстом.")
            return

        logger.info(f"[VOICE] [{user_id}] @{user_name}: {text}")
        await process_user_input(text, update, context)

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