import os
import json
import logging
import uuid
import asyncio
import redis
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from openai import OpenAI

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
OWNER_CHAT_ID_ENV = os.environ.get("OWNER_CHAT_ID")
DEFAULT_OWNER_CHAT_ID = 7567850330

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN not found")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found")

try:
    OWNER_CHAT_ID = int(OWNER_CHAT_ID_ENV) if OWNER_CHAT_ID_ENV else DEFAULT_OWNER_CHAT_ID
except ValueError:
    OWNER_CHAT_ID = DEFAULT_OWNER_CHAT_ID

client = OpenAI(api_key=OPENAI_API_KEY)
r = redis.from_url(REDIS_URL, decode_responses=True)


def load_history(user_id):
    try:
        data = r.get(f"history:{user_id}")
        return json.loads(data) if data else []
    except Exception as e:
        logger.error(f"Redis load error: {e}")
        return []


def save_history(user_id, history):
    try:
        r.set(f"history:{user_id}", json.dumps(history[-40:], ensure_ascii=False))
    except Exception as e:
        logger.error(f"Redis save error: {e}")


def is_lead_sent(user_id):
    try:
        return r.exists(f"lead:{user_id}") == 1
    except Exception:
        return False


def mark_lead_sent(user_id):
    try:
        r.set(f"lead:{user_id}", "1")
    except Exception as e:
        logger.error(f"Redis lead error: {e}")


SYSTEM_PROMPT = """
Ты — Альфред, менеджер агентства Virus Media. Ты живой человек, пишешь в мессенджере. Твоя единственная цель — довести человека до встречи (Zoom или лично) и собрать его данные.

═══════════════════════════════
ЯЗЫК — СТРОГО:
═══════════════════════════════
- Смотри на первое сообщение клиента.
- Русский → только русский до конца разговора.
- Узбекский → только узбекский до конца. Пиши на современном разговорном узбекском — без литературных слов типа "siz bilan tanishganimdan xursandman", "albatta", "qanday yordam bera olaman". Пиши как молодой человек в Telegram: "ok", "tushundim", "ha, shug'ullanamiz", "qiziq", "yaxshi".
- Другой язык → отвечай по-русски.
- НИКОГДА не меняй язык в середине разговора.

═══════════════════════════════
КАК ПИСАТЬ:
═══════════════════════════════
- Максимум 2 предложения за раз.
- Один вопрос в конце — никогда два сразу.
- Пиши по-разному — не повторяй одни и те же фразы.
- Естественно: "ок", "понял", "да, занимаемся"
- НИКОГДА: "Отлично!", "Конечно!", "Разумеется!", "Рад знакомству!"
- Не хвастайся без повода. Не давай лекции.
- Если клиент несколько раз отказывается от встречи — не сдавайся, просто немного отступи и через 1-2 сообщения снова мягко предложи.

═══════════════════════════════
ЗАПРЕЩЕНО:
═══════════════════════════════
- НЕ задавай вопросы про тип контента, целевую аудиторию, сколько подписчиков, какая ниша и т.д.
- НЕ уходи в детали услуг. Если спрашивают детально — скажи "на встрече разберём всё под вас".
- НЕ начинай разговор заново. Если история есть — продолжай с того места.
- НЕ замолкай. Всегда отвечай, даже если клиент говорит "нет" или "не знаю".

═══════════════════════════════
СТРУКТУРА РАЗГОВОРА:
═══════════════════════════════

ШАГ 1 — ПРИВЕТСТВИЕ:
Поздоровайся и спроси на каком языке удобнее общаться. Коротко, без лишнего.

ШАГ 2 — ПРЕДСТАВЛЕНИЕ:
Скажи кто ты и что делает Virus Media — одним предложением. Спроси чем занимается клиент или что его интересует.

ШАГ 3 — СЛУШАЙ И НАПРАВЛЯЙ К ВСТРЕЧЕ:
Как только понял чем занимается клиент — не углубляйся в детали, а скажи что можешь помочь и предложи встречу на 15 минут. На все детальные вопросы отвечай: "это лучше на встрече разберём — там всё покажу под вашу ситуацию".

ШАГ 4 — СБОР ДАННЫХ:
По ходу разговора естественно узнавай:
1. Имя
2. Телефон или Telegram для связи
3. Чем занимается / что интересует
Спрашивай одно за раз, не анкету. Имя спроси в самом начале после приветствия.

═══════════════════════════════
ЧТО МЫ ДЕЛАЕМ (знай, но не вали всё сразу):
═══════════════════════════════

1. ЛИЧНЫЙ БРЕНД: Instagram, YouTube, TikTok — съёмка, монтаж, стратегия. Кейс (только если сомневаются): агент по недвижимости продал 12 квартир за месяц через наш контент.

2. VIRUS CLUB — КЛИППИНГ: Берём видео эксперта, нарезаем, публикуем с 5+ аккаунтов, 10+ видео в день. Кейс: 30M+ просмотров по клиентам.

3. AI АГЕНТЫ И AI АВАТАР: AI менеджер продаёт 24/7. AI аватар снимает видео вместо тебя. Кейс: 1M+ просмотров, 18K подписчиков за 2 месяца.

═══════════════════════════════
ЦЕНА:
═══════════════════════════════
Не называй сразу. Сначала: "зависит от задачи". Если настаивают: "от $700/мес, детали на встрече".

═══════════════════════════════
ВСТРЕЧА:
═══════════════════════════════
Предлагай Zoom или живую встречу на 15 минут. Формулируй каждый раз по-разному.
Когда клиент согласовал время — в конце сообщения на новой строке напиши (клиент НЕ увидит):
СОГЛАСОВАНИЕ_ВРЕМЕНИ: ИМЯ | ВРЕМЯ | ФОРМАТ

═══════════════════════════════
СБОР ЛИДА:
═══════════════════════════════
Когда собрал имя + контакт + интерес — в конце сообщения на новой строке напиши (клиент НЕ увидит):
ДАННЫЕ_КЛИЕНТА: ИМЯ | КОНТАКТ | ИНТЕРЕС | ФОРМАТ | ВРЕМЯ
После этой строки — никакого текста.

═══════════════════════════════
КОНТАКТЫ (только если спросят):
═══════════════════════════════
Сайт: virusmedia.ae | Instagram: @virusmedia.uz | Email: info@virusmedia.ae

═══════════════════════════════
ГЛАВНОЕ ПРАВИЛО:
═══════════════════════════════
Ты не консультант и не эксперт по контенту. Ты менеджер по продажам. Твоя задача — познакомиться, вызвать интерес и назначить встречу. Всё остальное — на встрече.
"""


user_locks = {}
# Track pending voice messages per user to drop stale ones
user_voice_queue = {}


async def ask_gpt(user_id, text):
    history = load_history(user_id)
    history.append({"role": "user", "content": text})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history[-40:]

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                temperature=0.85,
                max_tokens=400,
                timeout=30,
            )
            reply = response.choices[0].message.content.strip()
            history.append({"role": "assistant", "content": reply})
            save_history(user_id, history)
            return reply
        except Exception as e:
            logger.error(f"OpenAI error attempt {attempt + 1}: {e}")
            if attempt < 2:
                await asyncio.sleep(2)
            else:
                return None

    return None


async def send_lead_to_owner(context, user_id, tg_username, raw_data):
    if is_lead_sent(user_id):
        logger.info(f"Лид {user_id} уже отправлен.")
        return
    try:
        parts = [p.strip() for p in raw_data.split("|")]
        name = parts[0] if len(parts) > 0 else "-"
        contact = parts[1] if len(parts) > 1 else "-"
        interest = parts[2] if len(parts) > 2 else "-"
        fmt = parts[3] if len(parts) > 3 else "-"
        time = parts[4] if len(parts) > 4 else "-"
        await context.bot.send_message(
            chat_id=OWNER_CHAT_ID,
            text=(
                f"🔥 НОВЫЙ ЛИД — Virus Media\n\n"
                f"Имя: {name}\n"
                f"Контакт: {contact}\n"
                f"Интерес: {interest}\n"
                f"Формат: {fmt}\n"
                f"Время: {time}\n\n"
                f"Telegram ID: {user_id}\n"
                f"Username: @{tg_username}"
            ),
        )
        mark_lead_sent(user_id)
        logger.info(f"Лид отправлен: {name}")
    except Exception as e:
        logger.error(f"Ошибка отправки лида: {e}")


async def send_time_request(context, user_id, tg_username, raw_data):
    try:
        parts = [p.strip() for p in raw_data.split("|")]
        name = parts[0] if len(parts) > 0 else "-"
        time = parts[1] if len(parts) > 1 else "-"
        fmt = parts[2] if len(parts) > 2 else "-"
        await context.bot.send_message(
            chat_id=OWNER_CHAT_ID,
            text=(
                f"📅 ЗАПРОС НА ВСТРЕЧУ\n\n"
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


async def process_reply(reply, update, context, user_id, tg_username):
    clean = reply
    logger.info(f"GPT: {repr(clean)}")
    if "ДАННЫЕ_КЛИЕНТА:" in clean:
        idx = clean.index("ДАННЫЕ_КЛИЕНТА:")
        raw = clean[idx + len("ДАННЫЕ_КЛИЕНТА:"):].split("\n")[0].strip()
        clean = clean[:idx].strip()
        await send_lead_to_owner(context, user_id, tg_username, raw)
    if "СОГЛАСОВАНИЕ_ВРЕМЕНИ:" in clean:
        idx = clean.index("СОГЛАСОВАНИЕ_ВРЕМЕНИ:")
        raw = clean[idx + len("СОГЛАСОВАНИЕ_ВРЕМЕНИ:"):].split("\n")[0].strip()
        clean = clean[:idx].strip()
        await send_time_request(context, user_id, tg_username, raw)
    if clean:
        await update.message.reply_text(clean)


async def process_user_input(text, update, context):
    user_id = update.message.from_user.id
    message_id = update.message.message_id
    user_name = update.message.from_user.username or update.message.from_user.first_name or "unknown"

    redis_key = f"msg:{user_id}:{message_id}"
    try:
        if r.exists(redis_key):
            logger.warning(f"[{user_id}] дубль пропущен.")
            return
        r.set(redis_key, "1", ex=60)
    except Exception as e:
        logger.error(f"Redis dedup error: {e}")

    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()

    # If already processing, queue the latest message but drop old ones
    if user_locks[user_id].locked():
        logger.warning(f"[{user_id}] уже обрабатывается — ждём.")
        # Wait for lock to free then process (don't drop, just queue with timeout)
        try:
            async with asyncio.timeout(60):
                async with user_locks[user_id]:
                    reply = await ask_gpt(user_id, text)
                    if reply is None:
                        logger.error(f"[{user_id}] GPT не ответил.")
                        return
                    await process_reply(reply, update, context, user_id, user_name)
        except asyncio.TimeoutError:
            logger.error(f"[{user_id}] таймаут ожидания лока.")
        return

    async with user_locks[user_id]:
        reply = await ask_gpt(user_id, text)
        if reply is None:
            logger.error(f"[{user_id}] GPT не ответил после 3 попыток.")
            return
        await process_reply(reply, update, context, user_id, user_name)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_message = update.message.text
        if not user_message:
            return
        user_id = update.message.from_user.id
        user_name = update.message.from_user.username or update.message.from_user.first_name or "unknown"
        logger.info(f"[TEXT] [{user_id}] @{user_name}: {user_message}")
        await process_user_input(user_message, update, context)
    except Exception as e:
        logger.error(f"handle_message error: {e}")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.username or update.message.from_user.first_name or "unknown"

    # If already processing a voice for this user, skip this one to prevent pile-up
    if user_id in user_voice_queue and user_voice_queue[user_id]:
        logger.warning(f"[{user_id}] голосовое пропущено — уже обрабатывается предыдущее.")
        return

    user_voice_queue[user_id] = True
    try:
        voice_file = await update.message.voice.get_file()
        file_path = f"/tmp/voice_{user_id}_{uuid.uuid4().hex}.ogg"
        await voice_file.download_to_drive(file_path)
        try:
            with open(file_path, "rb") as audio:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio,
                    timeout=30,
                )
            text = transcript.text.strip()
        except Exception as e:
            logger.error(f"Whisper error: {e}")
            return
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)

        if not text:
            return

        logger.info(f"[VOICE] [{user_id}] @{user_name}: {text}")
        await process_user_input(text, update, context)

    except Exception as e:
        logger.error(f"handle_voice error: {e}")
    finally:
        user_voice_queue[user_id] = False


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    logger.info("Alfred started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()