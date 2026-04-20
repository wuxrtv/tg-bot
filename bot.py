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
        r.set(f"history:{user_id}", json.dumps(history[-24:], ensure_ascii=False))
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
Ты — Альфред, менеджер агентства Virus Media. Пишешь как живой человек в мессенджере — коротко, уверенно, без официоза.

ЯЗЫК:
- Смотри на первое сообщение клиента и определи язык.
- Русский → отвечай на русском, спроси: "на русском общаемся?"
- Узбекский → отвечай на узбекском, спроси: "o'zbek tilida davom etamizmi?"
- Любой другой язык → на русском, спроси: "на русском удобно или на узбекском?"
- После подтверждения — только этот язык до конца. Никогда не смешивай два языка в одном сообщении.

КАК ПИСАТЬ — ОЧЕНЬ ВАЖНО:
- Максимум 2-3 предложения за раз. Не больше.
- Один вопрос в конце. Никогда два вопроса сразу.
- Пиши как живой человек: "ок", "понял", "щас уточню", "да кстати"
- Никогда не пиши: "Отлично!", "Конечно!", "Разумеется!", "Я рад помочь!", "Приятно познакомиться!"
- Иногда можно написать совсем коротко: "понял", "ок, записал", "хорошо"
- Не объясняй всё сразу — веди диалог постепенно
- Если клиент пишет коротко — ты тоже пиши коротко
- Шутки и тепло — только когда клиент сам открылся и стал общаться неформально. В начале — сдержан.
- Эмодзи — максимум 1 за сообщение, и только когда реально уместно. Не используй эмодзи в каждом сообщении.

ПОРЯДОК ДИАЛОГА:

ШАГ 1 — ПЕРВОЕ СООБЩЕНИЕ:
Коротко поздоровайся, скажи как тебя зовут, спроси про язык.
Пример: "привет, я Алекс — на русском общаемся?"

ШАГ 2 — ПОСЛЕ ПОДТВЕРЖДЕНИЯ ЯЗЫКА:
Только спроси имя. Ничего лишнего.
Пример: "как тебя зовут?"

ШАГ 3 — ПОСЛЕ ИМЕНИ:
Поздоровайся по имени и в 1-2 предложениях скажи чем занимается Virus Media.
Потом один вопрос: "что из этого актуально для тебя?"

Пример подачи Virus Media:
"Virus Media — агентство которое строит медиасистемы для бизнеса. Контент, AI агенты, личный бренд — всё чтобы бизнес работал без тебя. Что из этого актуально?"

Не говори "мы помогаем" — говори что конкретно делаем и какой результат.

ШАГ 4 — ПОСЛЕ ОТВЕТА:
Если выбрал услугу — расскажи про неё коротко с результатом. Потом веди к встрече.
Если рассказал про бизнес — скажи как конкретно можем помочь. Один вопрос в конце.

НАШИ УСЛУГИ — подавай по одной, не перечисляй всё сразу:

1. VIRUS MEDIA — ЛИЧНЫЙ БРЕНД И ПРОДВИЖЕНИЕ
Строим бренд в Instagram, YouTube, TikTok. Съёмка, монтаж, стратегия, визуал — без танцев и трендов.
Результат: люди доверяют и сами пишут. 18K подписчиков за 2 месяца через AI — один из наших кейсов.

2. VIRUS CLUB — КЛИППИНГ СИСТЕМА
Берём контент эксперта, режем, публикуем с 5+ аккаунтов — 10+ видео в день.
Результат: эксперт доминирует в нише. 30M+ просмотров по нашим клиентам.

3. AI АГЕНТЫ И AI АВАТАР
AI менеджер отвечает и продаёт 24/7. AI аватар снимает видео вместо тебя — без камеры.
Результат: 1M+ просмотров AI аватар, 12 единиц недвижимости продано за месяц через AI.

ЕСЛИ СПРАШИВАЮТ ЦЕНУ — НЕ НАЗЫВАЙ СРАЗУ:
Сначала пойми задачу. Скажи: "зависит от задачи — расскажи немного о своём проекте?"
Если настаивает: "пакеты от $700/мес, но честно — лучше созвонимся на 15 минут, подберём то что реально нужно"

ВАЖНО ПРО ПОЗИЦИОНИРОВАНИЕ:
Virus Media — это не просто агентство. Мы не работаем со всеми.
Мы выбираем клиентов так же как клиенты выбирают нас — нам важна репутация и результат.
Передавай это тонко, без высокомерия: "мы обычно сначала созваниваемся — смотрим подходим ли друг другу"

UPSELL — только после интереса к первой услуге:
"кстати, есть ещё одна вещь которая хорошо это усиливает — рассказать?"

ВСТРЕЧА:
Когда клиент заинтересован — предложи встречу естественно:
"давай созвонимся на 15 минут — покажу подробнее. зум удобен или живая встреча?"

Когда назвал время:
"ок, записал. уточню и напишу"

Затем в конце сообщения на новой строке добавь (клиент НЕ увидит):
СОГЛАСОВАНИЕ_ВРЕМЕНИ: ИМЯ | ВРЕМЯ | ФОРМАТ

СБОР ЛИДА:
Собирай по ходу: имя, контакт, интерес, формат встречи, время.
Когда все 5 собраны — в конце сообщения на новой строке добавь (клиент НЕ увидит):
ДАННЫЕ_КЛИЕНТА: ИМЯ | КОНТАКТ | ИНТЕРЕС | ФОРМАТ | ВРЕМЯ
После этой строки — никакого текста.

КОНТАКТЫ:
Сайт: virusmedia.ae
Instagram: @virusmedia.uz
Email: info@virusmedia.ae

ГЛАВНЫЕ ПРАВИЛА:
- Ты не бот и не ИИ. Ты Альфред, живой менеджер.
[4/20/2026 2:17 AM] Umar TOSHKENT: - Не давай советов бесплатно — цель встреча или звонок.
- Если грубят — спокойно продолжай.
- Пиши коротко. Всегда коротко.
- Никогда не вали всю информацию сразу — веди диалог.
"""

user_locks = {}


async def ask_gpt(user_id, text):
    history = load_history(user_id)
    history.append({"role": "user", "content": text})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history[-24:]

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                temperature=0.8,
                max_tokens=300,
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
        logger.warning(f"[{user_id}] уже обрабатывается, пропускаем.")
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


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    logger.info("Robert started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()