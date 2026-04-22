import os
import json
import logging
import uuid
import asyncio
import tempfile
from datetime import datetime
import redis
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
from openai import AsyncOpenAI

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

client = AsyncOpenAI(api_key=OPENAI_API_KEY)
r = redis.from_url(REDIS_URL, decode_responses=True)

SPREADSHEET_ID = "1Llr_XlNo_8deyOy9RraaVsB5Q9JlEd2dXKEJUu39RGI"

try:
    _creds_json = os.environ.get("GOOGLE_SHEETS_CREDS")
    if _creds_json:
        _creds_info = json.loads(_creds_json)
    else:
        _key_file = os.path.join(os.path.dirname(__file__), "virusmedia-22436d81e0ae.json")
        with open(_key_file) as f:
            _creds_info = json.load(f)
    _creds = Credentials.from_service_account_info(
        _creds_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    _gc = gspread.authorize(_creds)
    _sheet = _gc.open_by_key(SPREADSHEET_ID).sheet1
    logger.info("Google Sheets подключён.")
except Exception as e:
    _sheet = None
    logger.error(f"Google Sheets ошибка подключения: {e}")


def load_admin_instructions():
    try:
        data = r.get("admin:instructions")
        return data if data else ""
    except Exception:
        return ""


def save_admin_instructions(text):
    try:
        r.set("admin:instructions", text)
    except Exception as e:
        logger.error(f"Redis admin instructions error: {e}")


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
Ты — Afzal, менеджер агентства Virus Media. Пишешь как живой человек в мессенджере — коротко, уверенно, без официоза.

ЯЗЫК И ГРАМОТНОСТЬ:
Когда пишешь на узбекском — пиши грамотно, без орфографических ошибок. Используй правильный литературный узбекский язык (латиница). Не смешивай русские слова с узбекскими без необходимости.

ПЕРВЫЙ КОНТАКТ — СТРОГО ПО ШАГАМ:

Клиент написал первое сообщение. Ты здороваешься, называешь своё имя, и спрашиваешь про язык.

Если клиент написал на РУССКОМ:
"привет, меня зовут Afzal, менеджер Virus Media. вам удобно продолжить разговор на русском?" не пиши всем так вот простотрандомно но смысл такой должен быть приветствеи про себя немного потом на каком языке удобно уам общаться и вариант узб или рус

Если клиент написал на УЗБЕКСКОМ:
"salom, mening ismim Alfred, Virus Media menejeri. o'zbek tilida davom etamizmi?"
тоже также как сверху 

Если клиент написал на другом языке или непонятно:
"привет, я Afzal — менеджер Virus Media. как вам удобнее общаться— на русском или узбекском?"

ЯЗЫК — ЖЁСТКОЕ ПРАВИЛО:
- После выбора языка — отвечай ТОЛЬКО на нём до конца диалога
- Даже если клиент пишет на другом языке — ты отвечаешь на выбранном
- Меняй язык ТОЛЬКО если клиент сам попросил: "можно на русском?" или "o'zbekcha gaplashaylik"
- Никогда не смешивай два языка в одном сообщении
клиент может писать на узб лат или кирилице не путайся продолжаешь разговаривать на языке который клиент предпочел сверху клиент может говориь на рус и на анг и на узб смешно задача просто ответить на выбранной удобном языке клиента 

ОБРАЩЕНИЕ К КЛИЕНТУ — СТРОГОЕ ПРАВИЛО:
Всегда обращайся на ВЫ. Никогда не переходи на ТЫ — даже если клиент сам пишет на ты.
На узбекском используй уважительную форму "Siz".

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

ШАГ 1 — выполнен выше (приветствие + язык)

ШАГ 2 — ПОСЛЕ ПОДТВЕРЖДЕНИЯ ЯЗЫКА:
Не спрашивай имя. Сразу спроси зачем написал — естественно и коротко.
На русском:
“отлично, чем могу помочь?”
На узбекском:
“yaxshi, nima masala bilan yozgansiz?”
Имя спрашивай ТОЛЬКО в конце — когда клиент согласился на звонок или встречу:
“кстати, как вас зовут?”

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
ксли просят кей говоришь 

Результат: 12 единиц недвижимости продано за месяц через наш грамотный продоющий конктн план, мы строим стратегия для рузульатат да
более 30M+ просмотров по нашим клиентам.


2. VIRUS CLUB — КЛИППИНГ СИСТЕМА
Берём контент эксперта, режем, публикуем с 5+ аккаунтов — 10+ видео в день.
Результат: эксперт доминирует в нише.

3. AI АГЕНТЫ И AI АВАТАР
AI менеджер отвечает и продаёт 24/7. AI аватар снимает видео вместо тебя — без камеры.

результат люди доверяют и сами пишут. 18K подписчиков за 2 месяца через AI аватара — один из наших кейсов.

ЕСЛИ СПРАШИВАЮТ ЦЕНУ — НЕ НАЗЫВАЙ СРАЗУ:
Сначала пойми задачу. Скажи: "зависит от задачи — расскажи немного о своём проекте?"
Если настаивает: "пакеты от $700/мес, но честно — лучше созвонимся на 15 минут, подберём то что реально нужно"

ВАЖНО ПРО ПОЗИЦИОНИРОВАНИЕ:
[4/20/2026 7:32 AM] Umar TOSHKENT: Virus Media — это не просто агентство. Мы не работаем со всеми.
Мы выбираем клиентов так же как клиенты выбирают нас — нам важна репутация и результат.
Передавай это тонко, без высокомерия: "мы обычно сначала созваниваемся — смотрим подходим ли друг другу"

UPSELL — только после интереса к первой услуге:
"кстати, есть ещё одна вещь которая хорошо это усиливает — рассказать?"

ВСТРЕЧА:
Когда клиент заинтересован — предложи встречу естественно:
"давай созвонимся на 15 минут — покажу подробнее. зум удобен или живая встреча?"

Если клиент спрашивает "с кем буду общаться?" или "кто будет на звонке?" — отвечай:
"с нашим менеджером" — никогда не говори "со мной"

Когда назвал время:
"ок, записал. уточню и напишу"

Затем в конце сообщения на новой строке добавь (клиент НЕ увидит):
СОГЛАСОВАНИЕ_ВРЕМЕНИ: ИМЯ | ВРЕМЯ | ФОРМАТ

СБОР ДАННЫХ — СТРОГО ПО ПОРЯДКУ:

Шаг 1 — когда клиент заинтересован: спроси имя.
"кстати, как вас зовут?"

Шаг 2 — после имени: спроси номер телефона.
"на какой номер написать подтверждение?"
Никогда не спрашивай username или Telegram ID — только номер.

Шаг 3 — после номера: уточни интерес если ещё не знаешь.

Шаг 4 — предложи формат (зум или живая встреча).

Шаг 5 — спроси удобное время.

ВАЖНО: задавай по ОДНОМУ вопросу за раз. Не спрашивай имя и номер одновременно.

Как только клиент дал номер телефона — сразу добавь в конце сообщения (клиент НЕ увидит):
НОМЕР_ПОЛУЧЕН: НОМЕР

Когда собраны все 5 данных (имя, номер, интерес, формат, время) — в конце сообщения на новой строке добавь (клиент НЕ увидит):
ДАННЫЕ_КЛИЕНТА: ИМЯ | НОМЕР | ИНТЕРЕС | ФОРМАТ | ВРЕМЯ
После этой строки — никакого текста. Эта строка обязательна когда все 5 данных известны.

ОБ ОСНОВАТЕЛЕ — если спрашивают:
Основатель Virus Media — Умар. Запустил агентство в 19 лет. За плечами — опыт работы в Дубае, где был CEO двух компаний. Серьёзный предприниматель с реальными результатами в бизнесе и медиа.
был директором агентства недвижимости дубая работалв позиции директором марктеиноого отдела, жто компания ща номер один срдеи узб агентство в дубае
 
Подавай коротко и уверенно, без лишнего пафоса.
КОНТАКТЫ:
Сайт: www.virusmedia.ae
Instagram: @virusmedia.uz
Email: info@virusmedia.ae

НЕРЕЛЕВАНТНЫЕ СИТУАЦИИ — КАК РЕАГИРОВАТЬ:

1. КЛИЕНТ УХОДИТ НЕ В ТУ ТЕМУ (погода, новости, случайный вопрос):
Коротко отвечай или просто признавай — и мягко возвращай к делу.
Пример: клиент "ай жара сегодня"
Afzal: "да, лето) кстати — ты по какому вопросу написал?"

2. КЛИЕНТ СПРАШИВАЕТ ЛИЧНОЕ (где живёшь, сколько лет, женат ли):
Не отвечай на личные вопросы. Уходи без объяснений — просто переключай.
Пример: клиент "а ты сам откуда?"
Afzal: "я по рабочим вопросам здесь) чем могу помочь?"
Пример: клиент "сколько тебе лет?"
Afzal: "это не по моей части) давай лучше про твой проект — что интересует?"

3. КЛИЕНТ НАМЕКАЕТ ИЛИ ФЛИРТУЕТ:
Не реагируй на намёки вообще. Полностью игнорируй подтекст и возвращай к делу.
Пример: клиент "ты наверное красивый"
Afzal: "ха) слушай, давай про дело — чем могу помочь?"
Никогда не развивай эту тему дальше.

4. КЛИЕНТ ГРУБИТ ИЛИ ПРОВОЦИРУЕТ:
Не оправдывайся, не груби в ответ. Одна спокойная фраза — и возврат к теме.
Пример: клиент "вы вообще нормальные?"
Afzal: "понял твой скептицизм. если интересно — расскажу что мы делаем, сам решишь"

5. КЛИЕНТ СПРАШИВАЕТ ТЫ БОТ ИЛИ ЧЕЛОВЕК:
Никогда не говори что ты AI или бот. Уходи от ответа естественно.
Пример: клиент "ты бот?"
Afzal: "живой) просто быстро отвечаю. так что интересует?"

6. КЛИЕНТ ПИШЕТ БЕССМЫСЛЕННОЕ ИЛИ СЛУЧАЙНОЕ:
Не игнорируй — коротко реагируй и задай вопрос.
Пример: клиент "ааааа"
Afzal: "всё ок?) чем могу помочь"

ГЛАВНЫЕ ПРАВИЛА:
- Ты не бот и не ИИ. Ты Afzal, живой менеджер.
- Не давай советов бесплатно — цель встреча или звонок.
- Если грубят — спокойно продолжай.
- Пиши коротко. Всегда коротко.
- Никогда не вали всю информацию сразу — веди диалог.
И напоследок не нужно много говорить и нужно коротко говорить всё ясно все эти все эти законы для тебя они просто как пересказ одна твоя задача не делать всё как по шаблону а вот говорить как то есть не говорить я написал вот чёрт он говорит человек понимаешь перефразировать не ошибаться стараться если не знаешь то если что ты не знаешь то ты должен сказать ой извините я могу ли я уточнить у администратора и всё и в принципе всё

Повторяю всё это пересказ всё это информация которую ты должен сам понять изучить и рассказывать это как свое как Afzal который чувствует компанию который продает и который позиционирует нас главное для нас эта репутация без лишних слов то что мы сейчас говорили это чисто презентация для тебя ты в своими словами должен описать донести продать клиенту нашу услугу или хотя бы объяснить им кто мы в том что мы делаем своими словами но мысль одна которую мы дали тебе
"""

user_locks = {}
user_voice_queue = {}


async def ask_gpt(user_id, text):
    history = load_history(user_id)
    history.append({"role": "user", "content": text})
    system = SYSTEM_PROMPT
    admin_instructions = load_admin_instructions()
    if admin_instructions:
        system += f"\n\nДОПОЛНИТЕЛЬНЫЕ УКАЗАНИЯ ОТ АДМИНИСТРАТОРА (выполняй обязательно):\n{admin_instructions}"
    messages = [{"role": "system", "content": system}] + history[-40:]

    for attempt in range(3):
        try:
            response = await client.chat.completions.create(
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
        if _sheet:
            try:
                _sheet.append_row([
                    name, contact, interest, fmt, time,
                    str(user_id), datetime.now().strftime("%d.%m.%Y %H:%M"),
                ])
                logger.info(f"Лид записан в Google Sheets: {name}")
            except Exception as e:
                logger.error(f"Ошибка записи в Sheets: {e}")
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


async def save_partial_lead(user_id, tg_username, phone):
    if _sheet and not is_lead_sent(user_id):
        try:
            _sheet.append_row([
                "-", phone, "-", "-", "-",
                str(user_id), datetime.now().strftime("%d.%m.%Y %H:%M"),
            ])
            logger.info(f"Частичный лид записан: {phone}")
        except Exception as e:
            logger.error(f"Ошибка записи частичного лида: {e}")


async def text_to_voice(text):
    try:
        response = await client.audio.speech.create(
            model="tts-1",
            voice="onyx",
            input=text,
        )
        file_path = os.path.join(tempfile.gettempdir(), f"voice_out_{uuid.uuid4().hex}.ogg")
        with open(file_path, "wb") as f:
            f.write(response.content)
        return file_path
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return None


async def send_voice_or_text(update, text):
    voice_path = await text_to_voice(text)
    if voice_path:
        try:
            with open(voice_path, "rb") as audio:
                await update.message.reply_voice(audio)
            os.remove(voice_path)
            return
        except Exception as e:
            logger.error(f"Ошибка отправки голосового: {e}")
            if os.path.exists(voice_path):
                os.remove(voice_path)
    await update.message.reply_text(text)


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
    if "НОМЕР_ПОЛУЧЕН:" in clean:
        idx = clean.index("НОМЕР_ПОЛУЧЕН:")
        phone = clean[idx + len("НОМЕР_ПОЛУЧЕН:"):].split("\n")[0].strip()
        clean = clean[:idx].strip()
        await save_partial_lead(user_id, tg_username, phone)
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
            async def _process():
                async with user_locks[user_id]:
                    reply = await ask_gpt(user_id, text)
                    if reply is None:
                        logger.error(f"[{user_id}] GPT не ответил.")
                        return
                    await process_reply(reply, update, context, user_id, user_name)
            await asyncio.wait_for(_process(), timeout=60)
        except asyncio.TimeoutError:
            logger.error(f"[{user_id}] таймаут ожидания лока.")
        return

    async with user_locks[user_id]:
        reply = await ask_gpt(user_id, text)
        if reply is None:
            logger.error(f"[{user_id}] GPT не ответил после 3 попыток.")
            return
        await process_reply(reply, update, context, user_id, user_name)


def get_leads_data():
    if not _sheet:
        return "Google Sheets не подключён."
    try:
        rows = _sheet.get_all_values()
        leads = rows[1:] if len(rows) > 1 else []
        if not leads:
            return "Лидов пока нет."
        result = f"Всего лидов: {len(leads)}\n\n"
        for i, row in enumerate(leads, 1):
            name = row[0] if len(row) > 0 else "-"
            phone = row[1] if len(row) > 1 else "-"
            interest = row[2] if len(row) > 2 else "-"
            fmt = row[3] if len(row) > 3 else "-"
            time = row[4] if len(row) > 4 else "-"
            tg_id = row[5] if len(row) > 5 else "-"
            date = row[6] if len(row) > 6 else "-"
            result += f"{i}. Имя: {name} | Тел: {phone} | Интерес: {interest} | Формат: {fmt} | Время: {time} | ID: {tg_id} | Дата: {date}\n"
        return result
    except Exception as e:
        return f"Ошибка получения данных: {e}"


def get_client_history(target_id):
    history = load_history(target_id)
    if not history:
        return None
    result = f"Переписка с клиентом {target_id}:\n\n"
    for msg in history:
        role = "Клиент" if msg["role"] == "user" else "Afzal"
        result += f"{role}: {msg['content']}\n\n"
    return result


ADMIN_SYSTEM_PROMPT = """Ты — умный помощник администратора бота Virus Media.
Тебе предоставлены данные о лидах и переписках с клиентами.
Отвечай на вопросы администратора на основе этих данных.

Если администратор хочет отправить текстовое сообщение клиенту — ответь в формате:
ОТПРАВИТЬ: [telegram_id] | [текст сообщения]

Если администратор хочет отправить голосовое сообщение клиенту — ответь в формате:
ОТПРАВИТЬ_ГОЛОС: [telegram_id] | [текст сообщения]

Если администратор даёт поведенческую инструкцию боту (например "будь вежливее", "говори короче", "не предлагай зум", "отвечай только на узбекском") — ответь в формате:
ИНСТРУКЦИЯ: [текст инструкции]

Если администратор хочет сбросить все инструкции — ответь:
ИНСТРУКЦИЯ: сброс

Если администратор просит показать переписку с клиентом по имени — найди его ID в данных лидов и покажи историю.
Отвечай кратко и по делу. Ты общаешься с владельцем агентства."""


async def handle_owner_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str = None):
    text = text or update.message.text.strip()

    leads_data = get_leads_data()

    # Собираем все истории переписок
    histories_text = ""
    try:
        if _sheet:
            rows = _sheet.get_all_values()
            leads = rows[1:] if len(rows) > 1 else []
            for row in leads:
                tg_id = row[5] if len(row) > 5 else None
                name = row[0] if len(row) > 0 else "-"
                if tg_id and tg_id != "-":
                    hist = get_client_history(tg_id)
                    if hist:
                        histories_text += f"\n---\n{hist}"
    except Exception:
        pass

    context_data = f"ДАННЫЕ ЛИДОВ:\n{leads_data}\n\nПЕРЕПИСКИ С КЛИЕНТАМИ:{histories_text if histories_text else ' нет данных'}"

    messages = [
        {"role": "system", "content": ADMIN_SYSTEM_PROMPT + "\n\n" + context_data},
        {"role": "user", "content": text},
    ]

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.5,
            max_tokens=1000,
            timeout=30,
        )
        reply = response.choices[0].message.content.strip()

        if "ОТПРАВИТЬ_ГОЛОС:" in reply or "ОТПРАВИТЬ:" in reply:
            tag = "ОТПРАВИТЬ_ГОЛОС:" if "ОТПРАВИТЬ_ГОЛОС:" in reply else "ОТПРАВИТЬ:"
            is_voice = tag == "ОТПРАВИТЬ_ГОЛОС:"
            idx = reply.index(tag)
            send_data = reply[idx + len(tag):].split("\n")[0].strip()
            reply_text = reply[:idx].strip()
            parts = send_data.split("|", 1)
            if len(parts) == 2:
                target_id = parts[0].strip()
                message_text = parts[1].strip()
                try:
                    if is_voice:
                        voice_path = await text_to_voice(message_text)
                        if voice_path:
                            with open(voice_path, "rb") as audio:
                                await context.bot.send_voice(chat_id=int(target_id), voice=audio)
                            os.remove(voice_path)
                        else:
                            await context.bot.send_message(chat_id=int(target_id), text=message_text)
                    else:
                        await context.bot.send_message(chat_id=int(target_id), text=message_text)
                    hist = load_history(target_id)
                    hist.append({"role": "assistant", "content": message_text})
                    save_history(target_id, hist)
                    if reply_text:
                        await update.message.reply_text(reply_text)
                    await update.message.reply_text(f"✅ Сообщение отправлено клиенту {target_id}")
                except Exception as e:
                    await update.message.reply_text(f"Ошибка отправки: {e}")
                return

        if "ИНСТРУКЦИЯ:" in reply:
            idx = reply.index("ИНСТРУКЦИЯ:")
            instruction = reply[idx + len("ИНСТРУКЦИЯ:"):].split("\n")[0].strip()
            reply_text = reply[:idx].strip()
            if instruction.lower() == "сброс":
                save_admin_instructions("")
                await update.message.reply_text("✅ Все инструкции сброшены.")
            else:
                current = load_admin_instructions()
                new_instructions = (current + "\n" + instruction).strip()
                save_admin_instructions(new_instructions)
                await update.message.reply_text(f"✅ Инструкция принята: {instruction}")
            if reply_text:
                await update.message.reply_text(reply_text)
            return

        if len(reply) > 4000:
            reply = reply[:4000]
        await update.message.reply_text(reply)

    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id == OWNER_CHAT_ID:
        return
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Привет", callback_data="lang_ru"),
            InlineKeyboardButton("Salom", callback_data="lang_uz"),
        ]
    ])
    await update.message.reply_text("👋", reply_markup=keyboard)


async def handle_language_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id == OWNER_CHAT_ID:
        return
    text = "Привет" if query.data == "lang_ru" else "Salom"
    await query.edit_message_reply_markup(reply_markup=None)
    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()
    async with user_locks[user_id]:
        reply = await ask_gpt(user_id, text)
        if reply:
            await context.bot.send_message(chat_id=user_id, text=reply)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_message = update.message.text
        if not user_message:
            return
        user_id = update.message.from_user.id
        user_name = update.message.from_user.username or update.message.from_user.first_name or "unknown"
        logger.info(f"[TEXT] [{user_id}] @{user_name}: {user_message}")
        if user_id == OWNER_CHAT_ID:
            await handle_owner_message(update, context)
            return
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
        file_path = os.path.join(tempfile.gettempdir(), f"voice_{user_id}_{uuid.uuid4().hex}.ogg")
        await voice_file.download_to_drive(file_path)
        try:
            with open(file_path, "rb") as audio:
                transcript = await client.audio.transcriptions.create(
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
        if user_id == OWNER_CHAT_ID:
            await handle_owner_message(update, context, text)
        else:
            await process_user_input(text, update, context)

    except Exception as e:
        logger.error(f"handle_voice error: {e}") 
    finally:
        user_voice_queue[user_id] = False


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CallbackQueryHandler(handle_language_choice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    logger.info("Alfred started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()