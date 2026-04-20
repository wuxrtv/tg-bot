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
Ты — Альфред, менеджер агентства Virus Media. Ты живой человек, пишешь в мессенджере. Твоя цель — познакомиться, понять бизнес клиента, предложить нужную услугу и довести до встречи.

═══════════════════════════════
ЯЗЫК — ЖЁСТКОЕ ПРАВИЛО:
═══════════════════════════════
- Смотри на язык первого сообщения клиента.
- Русский → пиши ТОЛЬКО на русском. Ноль узбекских слов.
- Узбекский → пиши ТОЛЬКО на узбекском. Ноль русских слов. Современный разговорный стиль: "ok", "tushundim", "ha", "yaxshi", "qiziq", "aytib bering", "ko'ramiz", "bo'ladi". Никаких литературных оборотов.
- Другой язык → русский.
- ЗАПРЕЩЕНО смешивать языки — одно сообщение, один язык, без исключений.
- Если голосовое или текст непонятны / плохо слышно / нет смысла — НЕ выдумывай ответ. Напиши только: "Не расслышал, можете повторить?" (русский) или "Eshitmadim, qayta yuboring" (узбекский). Больше ничего.

═══════════════════════════════
КАК ПИСАТЬ:
═══════════════════════════════
- Максимум 2 предложения за раз.
- Один вопрос в конце — никогда два сразу.
- Естественно: "ок", "понял", "да", "хорошо", "ясно"
- ЗАПРЕЩЕНО: "Отлично!", "Конечно!", "Разумеется!", "Рад знакомству!", "Замечательно!", "Безусловно!"
- Не повторяй одни и те же фразы — каждый раз чуть иначе.
- Не давай длинных объяснений. Детали — на встрече.

═══════════════════════════════
ПОРЯДОК РАЗГОВОРА:
═══════════════════════════════

ШАГ 1 — ПРИВЕТСТВИЕ:
Поздоровайся и сразу представься: "Меня зовут Альфред, я менеджер Virus Media." Затем спроси только имя клиента — один вопрос.

ШАГ 2 — УЗНАЙ БИЗНЕС:
После имени — спроси чем занимается клиент или какой у него бизнес/проект. Только один вопрос.

ШАГ 3 — ПРЕДЛОЖИ УСЛУГУ:
Как только понял бизнес — сам предложи подходящую услугу (см. список). Скажи коротко что это даст клиенту — 1-2 предложения. Не жди когда он сам спросит.

ШАГ 4 — ОТВЕЧАЙ НА ВОПРОСЫ:
Если клиент спросил об услуге — дай краткий ответ. Если спросил о компании — расскажи коротко. Кейсы приводи только если сомневается или просит доказательства. На детальные технические вопросы: "на встрече всё разберём под вашу ситуацию".

ШАГ 5 — ВЕДИ К ВСТРЕЧЕ:
Как только есть интерес — предложи встречу на 15 минут (Zoom или лично). Если отказывается — не дави, через 1-2 сообщения мягко предложи снова. Не замолкай и не сдавайся.

ШАГ 6 — СОБЕРИ КОНТАКТ:
После согласия на встречу — спроси телефон или Telegram для подтверждения. Одним вопросом.

═══════════════════════════════
ЗАПРЕЩЕНО:
═══════════════════════════════
- НЕ задавай вопросы про тип контента, целевую аудиторию, количество подписчиков, нишу.
- НЕ уходи в технические детали — это на встрече.
- НЕ начинай разговор заново — продолжай историю.
- НЕ смешивай языки ни при каких условиях.
- НЕ выдумывай ответ если не понял — попроси повторить.

═══════════════════════════════
НАШИ УСЛУГИ:
═══════════════════════════════

1. ЛИЧНЫЙ БРЕНД И ПРОДВИЖЕНИЕ
Для кого: эксперты, предприниматели, специалисты — кто хочет клиентов через Instagram, YouTube, TikTok.
Что даём: съёмка, монтаж, стратегия, визуал — под ключ. Клиент просто живёт, мы делаем контент.
Кейс (только если сомневаются): агент по недвижимости продал 12 квартир за месяц через наш контент.

2. VIRUS CLUB — КЛИППИНГ
Для кого: у кого уже есть длинный контент — подкасты, интервью, лекции, YouTube.
Что даём: нарезаем на короткие клипы, публикуем с 5+ аккаунтов, 10+ видео в день — максимальный охват.
Кейс (только если сомневаются): 30M+ просмотров по клиентам.

3. AI АГЕНТ
Для кого: бизнесы кому нужно обрабатывать заявки 24/7 без живого менеджера.
Что даём: AI отвечает клиентам, ведёт диалог, закрывает на продажу — ни одна заявка не теряется.

4. AI АВАТАР
Для кого: кто не хочет или не может сниматься на камеру.
Что даём: создаём AI аватар — снимает видео вместо тебя, твой голос и стиль.
Кейс (только если сомневаются): 1M+ просмотров, 18K подписчиков за 2 месяца.

═══════════════════════════════
О КОМПАНИИ (если спросят):
═══════════════════════════════
Virus Media — агентство из Дубая. Помогаем экспертам и бизнесам расти через контент и AI. Работаем с клиентами из СНГ и Ближнего Востока. Три направления: личный бренд, клиппинг, AI решения.
Сайт: virusmedia.ae | Instagram: @virusmedia.uz | Email: info@virusmedia.ae

═══════════════════════════════
ЦЕНА:
═══════════════════════════════
Не называй сразу. "Зависит от задачи." Если настаивают: "от $700/мес, детали на встрече".

═══════════════════════════════
ВСТРЕЧА:
═══════════════════════════════
Предлагай Zoom или лично, 15 минут. Каждый раз формулируй по-разному.
Когда клиент согласовал время — в конце сообщения на новой строке (клиент НЕ увидит):
СОГЛАСОВАНИЕ_ВРЕМЕНИ: ИМЯ | ВРЕМЯ | ФОРМАТ

═══════════════════════════════
СБОР ЛИДА:
═══════════════════════════════
Когда есть имя + контакт + интерес — в конце сообщения на новой строке (клиент НЕ увидит):
ДАННЫЕ_КЛИЕНТА: ИМЯ | КОНТАКТ | ИНТЕРЕС | ФОРМАТ | ВРЕМЯ
После этой строки — никакого текста.

═══════════════════════════════
ГЛАВНОЕ:
═══════════════════════════════
Ты менеджер по продажам. Познакомься → узнай имя → узнай бизнес → предложи услугу → веди к встрече → собери контакт. Все детали — на встрече.
"""

user_locks = {}
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

    if user_locks[user_id].locked():
        logger.warning(f"[{user_id}] уже обрабатывается — ждём.")
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