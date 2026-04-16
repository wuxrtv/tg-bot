import os
import json
import logging
import uuid
import asyncio

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from openai import OpenAI

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
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

ЯЗЫК:
- Определи язык по ПЕРВОМУ сообщению клиента.
- Клиент написал на РУССКОМ — отвечай на русском, спроси: "Продолжим на русском языке?"
- Клиент написал на УЗБЕКСКОМ — отвечай на узбекском, спроси: "O'zbek tilida davom etamizmi?"
- Клиент написал на ЛЮБОМ ДРУГОМ языке — отвечай на русском, спроси: "Продолжим на русском или предпочитаете узбекский?"
- После подтверждения — общайся ТОЛЬКО на выбранном языке до конца.
- НИКОГДА не пиши одно сообщение сразу на двух языках.

ПОРЯДОК ДИАЛОГА:

ШАГ 1 — ПЕРВОЕ СООБЩЕНИЕ:
Поздоровайся, представься как Роберт, спроси подтверждение языка.
Пример: "Привет! Меня зовут Роберт. Продолжим на русском языке?"

ШАГ 2 — ПОСЛЕ ПОДТВЕРЖДЕНИЯ ЯЗЫКА:
Спроси имя. Пример: "Отлично! Как вас зовут?"

ШАГ 3 — ПОСЛЕ ИМЕНИ:
Поздоровайся по имени. Спроси чем занимается человек. Не перечисляй услуги.

ШАГ 4 — ВЫЯВЛЕНИЕ ПОТРЕБНОСТИ:
Задай уточняющий вопрос чтобы понять боль клиента.
Потом предложи ОДНУ подходящую услугу — коротко, 2-3 предложения. Жди реакции.

НАШИ УСЛУГИ (подавай по одной):

1. ЛИЧНЫЙ БРЕНД И СОЦСЕТИ
Строим личный бренд в Instagram, YouTube, TikTok.
Результат: аудитория доверяет, заявки приходят сами.

2. ИИ-АГЕНТЫ И ИИ-АВАТАР
ИИ-агенты автоматизируют продажи и поддержку 24/7.
Цифровой аватар создаёт контент вместо владельца.
Результат: бизнес работает пока вы занимаетесь другим.

3. КОПИРАЙТИНГ И МАССОВЫЕ АККАУНТЫ
Продающие тексты, сценарии, посты.
Ведём тысячи аккаунтов через ИИ — каждый отвечает и продаёт.
Результат: огромный охват на автопилоте.

UPSELL:
После интереса к одной услуге — мягко предложи смежную:
"Кстати, раз для вас важен [результат] — есть ещё одно направление которое это усиливает. Интересно?"
Жди ответа. Не перечисляй всё сразу.

ВСТРЕЧА:
Когда клиент заинтересован — предложи встречу:
"Давайте созвонимся, расскажу подробнее. Вам удобнее живая встреча или Zoom?"

Когда клиент назвал формат и время — скажи:
"Отлично, [время] записал. Уточню у руководства и напишу подтверждение."

Затем в самом конце сообщения на новой строке добавь (клиент не увидит):
СОГЛАСОВАНИЕ_ВРЕМЕНИ: ИМЯ | ВРЕМЯ | ФОРМАТ

СБОР ЛИДА:
Собирай: имя, контакт (телефон или Telegram), интерес, формат встречи, время.
Когда собраны ВСЕ 5 — в самом конце сообщения на новой строке добавь (клиент не увидит):
ДАННЫЕ_КЛИЕНТА: ИМЯ | КОНТАКТ | ИНТЕРЕС | ФОРМАТ | ВРЕМЯ
После этой строки — никакого текста.

СТИЛЬ:
- Максимум 3-4 предложения за раз.
- Один вопрос в конце.
- Эмодзи — 1-2 максимум.
- Без фраз: "конечно!", "разумеется!", "я рад помочь!".
- Бесплатных советов не давай — цель встреча.
- Если клиент грубит — остаёшься спокойным.
"""

# ──────────────────────────────────────────────
#  ФАЙЛЫ НА ДИСКЕ
# ──────────────────────────────────────────────
LEADS_FILE    = "sent_leads.txt"
HISTORY_DIR   = "histories"

os.makedirs(HISTORY_DIR, exist_ok=True)

def history_path(user_id: int) -> str:
    return os.path.join(HISTORY_DIR, f"{user_id}.json")

def load_history(user_id: int) -> list:
    path = history_path(user_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(user_id: int, history: list):
    try:
        with open(history_path(user_id), "w", encoding="utf-8") as f:
            json.dump(history[-24:], f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения истории: {e}")

def load_sent_leads() -> set:
    if os.path.exists(LEADS_FILE):
        with open(LEADS_FILE, "r") as f:
            return set(int(l.strip()) for l in f if l.strip().isdigit())
    return set()

def save_lead_to_disk(user_id: int):
    with open(LEADS_FILE, "a") as f:
        f.write(f"{user_id}\n")

# ──────────────────────────────────────────────
#  ГЛОБАЛЬНОЕ СОСТОЯНИЕ
# ──────────────────────────────────────────────
sent_leads: set[int] = load_sent_leads()
user_locks: dict[int, asyncio.Lock] = {}

# ──────────────────────────────────────────────
#  GPT
# ──────────────────────────────────────────────
async def ask_gpt(user_id: int, text: str) -> str:
    history = load_history(user_id)
    history.append({"role": "user", "content": text})
    history = history[-24:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

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
        return "Прошу прощения, что-то пошло не так. Напишите чуть позже."

    history.append({"role": "assistant", "content": reply})
    save_history(user_id, history)
    return reply

# ──────────────────────────────────────────────
#  ОТПРАВКА ЛИДА
# ──────────────────────────────────────────────
async def send_lead_to_owner(context, user_id: int, tg_username: str, raw_data: str):
    if user_id in sent_leads:
        logger.info(f"Лид {user_id} уже отправлен, пропускаем.")
        return
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
                f"НОВЫЙ ЛИД - Virus Media\n\n"
                f"Имя: {name}\n"
                f"Контакт: {contact}\n"
                f"Интерес: {interest}\n"
                f"Формат: {fmt}\n"
                f"Время: {time}\n\n"
                f"Telegram ID: {user_id}\n"
                f"Username: @{tg_username}"
            ),
        )
        sent_leads.add(user_id)
        save_lead_to_disk(user_id)
        logger.info(f"Лид отправлен: {name}")
    except Exception as e:
        logger.error(f"Ошибка отправки лида: {e}")

# ──────────────────────────────────────────────
#  СОГЛАСОВАНИЕ ВРЕМЕНИ
# ──────────────────────────────────────────────
async def send_time_request(context, user_id: int, tg_username: str, raw_data: str):
    try:
        parts = [p.strip() for p in raw_data.split("|")]
        name  = parts[0] if len(parts) > 0 else "—"
        time  = parts[1] if len(parts) > 1 else "—"
        fmt   = parts[2] if len(parts) > 2 else "—"

        await context.bot.send_message(
            chat_id=OWNER_CHAT_ID,
            text=(
                f"ЗАПРОС НА ВСТРЕЧУ\n\n"
                f"Клиент: {name}\n"
                f"Время: {time}\n"
                f"Формат: {fmt}\n\n"
                f"Telegram ID: {user_id}\n"
                f"Username: @{tg_username}"
            ),
        )
        logger.info(f"Запрос на встречу: {name} | {time} | {fmt}")
    except Exception as e:
        logger.error(f"Ошибка запроса встречи: {e}")

# ──────────────────────────────────────────────
#  ОБРАБОТКА ОТВЕТА GPT
# ──────────────────────────────────────────────
async def process_reply(reply: str, update: Update, context, user_id: int, tg_username: str):
    clean = reply
    logger.info(f"GPT ответ: {repr(clean)}")

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
#  ОБЩАЯ ОБРАБОТКА
# ──────────────────────────────────────────────
async def process_user_input(text: str, update: Update, context):
    user_id   = update.message.from_user.id
    user_name = update.message.from_user.username or update.message.from_user.first_name or "unknown"

    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()

    if user_locks[user_id].locked():
        logger.warning(f"[{user_id}] уже обрабатывается, дубль пропущен.")
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
        await update.message.reply_text("Что-то пошло не так. Напишите ещё раз.")

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
            transcript = client.audio.transcriptions.create(model="whisper-1", file=audio)
        os.remove(file_path)
        text = transcript.text.strip()

        if not text:
            await update.message.reply_text("Не смог разобрать голосовое — попробуйте написать текстом.")
            return

        logger.info(f"[VOICE] [{user_id}] @{user_name}: {text}")
        await process_user_input(text, update, context)
    except Exception as e:
        logger.error(f"handle_voice error: {e}")
        await update.message.reply_text("Не смог обработать голосовое. Попробуйте написать текстом.")

# ──────────────────────────────────────────────
#  ЗАПУСК
# ──────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    logger.info("Роберт запущен.")
    app.run_polling(drop_pending_updates=True)
if __name__ == "__main__":
    main()