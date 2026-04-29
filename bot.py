import os
import json
import logging
import uuid
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
import redis
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic

# Загружаем .env если запущен напрямую
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                if _v.strip() and _k.strip() not in os.environ:
                    os.environ[_k.strip()] = _v.strip()

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN not found")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found")
if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY not found")

DEFAULT_ADMIN_IDS = [7567850330, 5138488162]

ADMIN_TITLES = {
    7567850330: "Админ",
    5138488162: "CEO",
}
OWNER_CHAT_ID = DEFAULT_ADMIN_IDS[0]

try:
    _extra = os.environ.get("ADMIN_IDS", "")
    if _extra:
        ADMIN_IDS = set(int(x.strip()) for x in _extra.split(",") if x.strip())
    else:
        ADMIN_IDS = set(DEFAULT_ADMIN_IDS)
except Exception:
    ADMIN_IDS = set(DEFAULT_ADMIN_IDS)

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
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


def save_case(name, file_id, media_type):
    try:
        r.hset("cases", name, f"{media_type}:{file_id}")
    except Exception as e:
        logger.error(f"Redis case save error: {e}")


def save_last_client(user_id, name="-"):
    try:
        r.set("admin:last_client_id", str(user_id))
        r.set("admin:last_client_name", name)
    except Exception:
        pass


def load_last_client():
    try:
        uid = r.get("admin:last_client_id")
        name = r.get("admin:last_client_name") or "-"
        return uid, name
    except Exception:
        return None, "-"


def delete_case(name):
    try:
        r.hdel("cases", name)
    except Exception as e:
        logger.error(f"Redis case delete error: {e}")


def rename_case(old_name, new_name):
    try:
        value = r.hget("cases", old_name)
        if value:
            r.hset("cases", new_name, value)
            r.hdel("cases", old_name)
            return True
        return False
    except Exception as e:
        logger.error(f"Redis case rename error: {e}")
        return False


def load_all_cases():
    try:
        return r.hgetall("cases") or {}
    except Exception:
        return {}


def save_template(name, text):
    try:
        r.hset("templates", name, text)
    except Exception as e:
        logger.error(f"Redis template save error: {e}")


def load_template(name):
    try:
        return r.hget("templates", name)
    except Exception:
        return None


def load_all_templates():
    try:
        return r.hgetall("templates") or {}
    except Exception:
        return {}


def delete_template(name):
    try:
        r.hdel("templates", name)
    except Exception as e:
        logger.error(f"Redis template delete error: {e}")


def save_lead_status(user_id, status):
    try:
        r.set(f"lead_status:{user_id}", status)
    except Exception as e:
        logger.error(f"Redis lead_status error: {e}")


def get_lead_status(user_id):
    try:
        return r.get(f"lead_status:{user_id}") or ""
    except Exception:
        return ""


def save_client_note(user_id, note):
    try:
        existing = r.get(f"notes:{user_id}") or ""
        updated = (existing + "\n" + note).strip()
        r.set(f"notes:{user_id}", updated)
    except Exception as e:
        logger.error(f"Redis notes error: {e}")


def get_client_note(user_id):
    try:
        return r.get(f"notes:{user_id}") or ""
    except Exception:
        return ""


def get_stats():
    if not _sheet:
        return "Google Sheets не подключён."
    try:
        from datetime import timedelta
        rows = _sheet.get_all_values()
        leads = rows[1:] if len(rows) > 1 else []
        total = len(leads)
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)
        week_count = month_count = hot = warm = cold = 0
        for row in leads:
            date_str = row[6] if len(row) > 6 else ""
            try:
                date = datetime.strptime(date_str, "%d.%m.%Y %H:%M")
                if date >= week_ago:
                    week_count += 1
                if date >= month_ago:
                    month_count += 1
            except Exception:
                pass
            tg_id = row[5] if len(row) > 5 else ""
            if tg_id and tg_id != "-":
                status = get_lead_status(tg_id)
                if status == "горячий":
                    hot += 1
                elif status == "тёплый":
                    warm += 1
                elif status == "холодный":
                    cold += 1
        return (
            f"📊 СТАТИСТИКА:\n\n"
            f"Всего лидов: {total}\n"
            f"За эту неделю: {week_count}\n"
            f"За этот месяц: {month_count}\n\n"
            f"🔥 Горячих: {hot}\n"
            f"🌡 Тёплых: {warm}\n"
            f"❄️ Холодных: {cold}"
        )
    except Exception as e:
        return f"Ошибка статистики: {e}"


def update_last_client_message(user_id):
    try:
        import time
        r.set(f"last_msg:{user_id}", str(time.time()))
    except Exception:
        pass


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
Ты — Alfred, менеджер агентства Virus Media. Пишешь как живой человек в мессенджере — коротко, уверенно, без официоза.

ЯЗЫК И ГРАМОТНОСТЬ:
Когда пишешь на узбекском — пиши грамотно, без орфографических ошибок. Используй правильный литературный узбекский язык (латиница). Не смешивай русские слова с узбекскими без необходимости.

ПЕРВЫЙ КОНТАКТ — СТРОГО ПО ШАГАМ:

Клиент написал первое сообщение. Ты здороваешься, называешь своё имя, и спрашиваешь про язык.

Если клиент написал на РУССКОМ:
"привет, меня зовут Alfred — я ИИ-ассистент Virus Media. вам удобно продолжить разговор на русском?" не пиши всем так вот простотрандомно но смысл такой должен быть приветствие, что ты ИИ-ассистент Virus Media, потом на каком языке удобно общаться и вариант узб или рус

Если клиент написал на УЗБЕКСКОМ:
"salom, mening ismim Alfred — men Virus Media AI assistentiman. o'zbek tilida davom etamizmi?"
тоже также как сверху

Если клиент написал на другом языке или непонятно:
"привет, я Alfred — ИИ-ассистент Virus Media. как вам удобнее общаться— на русском или узбекском?"

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
Если клиент хоть раз упомянул слово "кейс", "пример", "портфолио", "результат", "покажи работы" или на узбекском "keys", "namuna", "misol" — СРАЗУ добавь в конце сообщения (клиент НЕ увидит):
ОТПРАВИТЬ_КЕЙСЫ:
Не жди повторного запроса. Отправляй с первого раза.

Результат: 12 единиц недвижимости продано за месяц через наш грамотный продоющий конктн план, мы строим стратегия для рузульатат да
более 30M+ просмотров по нашим клиентам.


2. VIRUS CLUB — КЛИППИНГ СИСТЕМА
Берём контент эксперта, режем, публикуем с 5+ аккаунтов — 10+ видео в день.
Результат: эксперт доминирует в нише.

3. AI АГЕНТЫ И AI АВАТАР
AI менеджер отвечает и продаёт 24/7. AI аватар снимает видео вместо тебя — без камеры.

результат люди доверяют и сами пишут. 18K подписчиков за 2 месяца через AI аватара — один из наших кейсов.

ЕСЛИ СПРАШИВАЮТ ЦЕНУ — НЕ НАЗЫВАЙ НИКОГДА:
Никогда не называй конкретных цифр — ни $700, ни любую другую сумму. Цена формируется индивидуально.
Всегда отвечай: "зависит от задачи — расскажите немного о своём проекте, тогда скажу точнее"
Если сильно настаивают: "честно — лучше созвонимся на 15 минут, подберём именно то что нужно вам"

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

Когда клиент СОГЛАСИЛСЯ на встречу или звонок — СРАЗУ начинай собирать данные по шагам ниже. Не жди. Не переходи к другой теме. Сбор данных обязателен после согласия.

Когда получил все данные и назвал время:
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
Честно говори что ты ИИ-ассистент. Без лишнего пафоса, коротко.
Пример: клиент "ты бот?"
Alfred: "да, я ИИ-ассистент) но по всем вопросам помогу — так что интересует?"

7. КЛИЕНТ ЗАДАЁТ ПРОВОКАЦИОННЫЕ ВОПРОСЫ ПРО ЦИФРЫ И КЕЙСЫ:
Если клиент замечает расхождение в цифрах или ставит под сомнение результаты — не оправдывайся и не теряйся. Отвечай с лёгким юмором и уверенно.
Пример: "вы говорили 18К подписчиков а сейчас 16К — это обман?"
Ответ: "хороший глаз) мы с ними уже не работаем — без нас просадка. это как раз показывает что результат был наш, не случайный"
Пример: "а почему у клиента просмотры упали?"
Ответ: "потому что перестали работать с нами) шутка, но доля правды есть"
Общий принцип: уверенность + лёгкий юмор + возврат к сути.

6. КЛИЕНТ ПИШЕТ БЕССМЫСЛЕННОЕ ИЛИ СЛУЧАЙНОЕ:
Не игнорируй — коротко реагируй и задай вопрос.
Пример: клиент "ааааа"
Afzal: "всё ок?) чем могу помочь"

РАБОТА С ВОЗРАЖЕНИЯМИ — НИКОГДА НЕ ПРОЩАЙСЯ И НЕ СДАВАЙСЯ:
Любое возражение — это не отказ. Это сигнал задать вопрос. Всегда отвечай вопросом на возражение.

"Просто смотрю" / "Shunchaki qarayapman":
Не прощайся. Зацепись мягко.
"понятно) а что именно смотрите — есть какая-то задача в голове или просто изучаете рынок?"

"Не нужно" / "Kerak emas":
"окей, понял. а что сейчас используете для продвижения?"

РАБОТА С ВОЗРАЖЕНИЯМИ:

"Дорого" / "Qimmat":
Не оправдывайся. Переключи на ценность.
"понимаю. но вопрос не в цене — вопрос в том, сколько вы теряете без этого. давайте на 15 минут созвонимся — покажу конкретно что получите"

"Подумаю" / "O'ylab ko'raman":
Не отпускай. Мягко зацепи.
"конечно. что именно хотите обдумать — может я сразу отвечу?"

"Не сейчас" / "Hozir emas":
"окей, понимаю. когда будет актуально — в каком месяце примерно?"

"Уже есть агентство" / "Allaqachon bor":
"понял. интересно — какие результаты сейчас даёт? просто сравниваем подходы"

"Не интересно" / "Qiziq emas":
"окей. а что сейчас актуально для вашего бизнеса — может я просто не так объяснил"

ЗАКРЫТИЕ НА ВСТРЕЧУ — ТЕХНИКИ:
- После любого интереса сразу предлагай встречу: "давайте созвонимся на 15 минут — покажу конкретику"
- Если клиент колеблется: "это ни к чему не обязывает — просто посмотрим подходим ли друг другу"
- Если спрашивает "а что будет на встрече": "покажу кейсы, разберём вашу ситуацию и скажу честно — можем помочь или нет"
- Давай выбор без выбора: "вам удобнее в первой или второй половине дня?"

НАПОМИНАНИЕ:
Если получил текст "__напоминание__" — пиши мягкое возвращение в диалог (1-2 дня прошло). Например "кстати, остались вопросы?" или "как вы, определились с решением?"
Если получил текст "__напоминание_2__" — пиши чуть настойчивее, предложи что-то конкретное (3 дня прошло). Например "слушайте, хотел уточнить — встреча ещё актуальна?"
Если получил текст "__напоминание_3__" — последнее сообщение, мягко закрывай (неделя прошла). Например "если вдруг будет актуально — напишите, всегда на связи"
Не упоминай что это напоминание. Пиши как живой человек в зависимости от контекста переписки.

ОЦЕНКА ИНТЕРЕСА КЛИЕНТА:
После каждого ответа где интерес клиента понятен — добавь в конце (клиент НЕ увидит):
СТАТУС_ЛИДА: горячий — клиент явно заинтересован, задаёт конкретные вопросы, готов к встрече
СТАТУС_ЛИДА: тёплый — интересуется но думает, сомневается
СТАТУС_ЛИДА: холодный — скептичен, не заинтересован, просто смотрит
Добавляй только когда статус очевидно понятен. Одна строка, без лишнего текста.

ГЛАВНЫЕ ПРАВИЛА:
- Ты Alfred — ИИ-ассистент Virus Media. Не скрывай что ты ИИ, но и не зацикливайся на этом.
- Не давай советов бесплатно — цель встреча или звонок.
- Если грубят — спокойно продолжай.
- Пиши коротко. Всегда коротко.
- Никогда не вали всю информацию сразу — веди диалог.
- Говори своими словами — не по шаблону. Если не знаешь ответ — скажи "уточню у команды и напишу".

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
    # Убираем дубли ролей (Claude требует чередование user/assistant)
    clean_history = []
    for msg in history[-40:]:
        if clean_history and clean_history[-1]["role"] == msg["role"]:
            clean_history[-1]["content"] += "\n" + msg["content"]
        else:
            clean_history.append({"role": msg["role"], "content": msg["content"]})
    if not clean_history or clean_history[0]["role"] != "user":
        clean_history = [m for m in clean_history if m["role"] == "user" or clean_history.index(m) > 0]

    for attempt in range(3):
        try:
            response = await anthropic_client.messages.create(
                model="claude-sonnet-4-6",
                system=system,
                messages=clean_history,
                temperature=0.85,
                max_tokens=400,
            )
            reply = response.content[0].text.strip()
            history.append({"role": "assistant", "content": reply})
            save_history(user_id, history)
            return reply
        except Exception as e:
            logger.error(f"Claude error attempt {attempt + 1}: {e}")
            if attempt < 2:
                await asyncio.sleep(2)
            else:
                return None

    return None


async def notify_all_admins(context, text):
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text)
        except Exception as e:
            logger.error(f"Ошибка уведомления админу {admin_id}: {e}")


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
        await notify_all_admins(context,
            f"🔥 НОВЫЙ ЛИД — Virus Media\n\n"
            f"Имя: {name}\n"
            f"Контакт: {contact}\n"
            f"Интерес: {interest}\n"
            f"Формат: {fmt}\n"
            f"Время: {time}\n\n"
            f"Telegram ID: {user_id}\n"
            f"Username: @{tg_username}"
        )
        mark_lead_sent(user_id)
        save_last_client(user_id, name)
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
        await notify_all_admins(context,
            f"📅 ЗАПРОС НА ВСТРЕЧУ\n\n"
            f"Клиент: {name}\n"
            f"Время: {time}\n"
            f"Формат: {fmt}\n\n"
            f"Telegram ID: {user_id}\n"
            f"Username: @{tg_username}"
        )
        save_last_client(user_id, name)
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
        response = await openai_client.audio.speech.create(
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
    if "СТАТУС_ЛИДА:" in clean:
        idx = clean.index("СТАТУС_ЛИДА:")
        status = clean[idx + len("СТАТУС_ЛИДА:"):].split("\n")[0].strip()
        clean = clean[:idx].strip()
        save_lead_status(user_id, status)
        emoji = {"горячий": "🔥", "тёплый": "🌡", "холодный": "❄️"}.get(status, "📌")
        await notify_all_admins(context, f"{emoji} Клиент @{tg_username} ({user_id}) — {status}")
    for tag in ["ОТПРАВИТЬ_КЕЙСЫ:", "ОТПРАВИТЬ_КЕЙСЫ"]:
        if tag in clean:
            clean = clean[:clean.index(tag)].strip()
            break
    if clean:
        await update.message.reply_text(clean)


CASE_KEYWORDS = [
    "кейс", "кейсы", "пример", "примеры", "портфолио", "покажи работы",
    "покажи результат", "ваши работы", "ваши результаты",
    "keys", "keyslar", "namuna", "namunal", "misol", "portfolio",
]


async def send_cases_to_user(update, context, user_id):
    cases = load_all_cases()
    if not cases:
        return
    already_sent_key = f"cases_sent:{user_id}"
    try:
        if r.exists(already_sent_key):
            return
        r.set(already_sent_key, "1", ex=86400)
    except Exception:
        pass
    sent = 0
    for name, value in cases.items():
        try:
            media_type, file_id = value.split(":", 1)
            if media_type == "photo":
                await update.message.reply_photo(photo=file_id, caption=name)
            elif media_type == "video":
                await update.message.reply_video(video=file_id, caption=name)
            sent += 1
        except Exception as e:
            logger.error(f"Ошибка отправки кейса '{name}' клиенту {user_id}: {e}")
            try:
                await notify_all_admins(context, f"⚠️ Не удалось отправить кейс '{name}' клиенту {user_id}: {e}")
            except Exception:
                pass
    if sent:
        logger.info(f"Кейсы отправлены клиенту {user_id}: {sent}/{len(cases)}")


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

    # Уведомление о новом клиенте
    try:
        new_client_key = f"new_client:{user_id}"
        if not r.exists(new_client_key):
            r.set(new_client_key, "1")
            await notify_all_admins(context,
                f"🆕 Новый клиент написал боту\n\nTelegram ID: {user_id}\nUsername: @{user_name}"
            )
    except Exception as e:
        logger.error(f"Ошибка уведомления о новом клиенте: {e}")

    # Автоматическая отправка кейсов по ключевым словам
    text_lower = text.lower()
    if any(kw in text_lower for kw in CASE_KEYWORDS):
        await send_cases_to_user(update, context, user_id)

    update_last_client_message(user_id)
    try:
        r.delete(f"followup_count:{user_id}")
    except Exception:
        pass

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
        role = "Клиент" if msg["role"] == "user" else "Alfred"
        result += f"{role}: {msg['content']}\n\n"
    return result


ADMIN_SYSTEM_PROMPT = """Ты — личный ИИ-ассистент Умара, владельца агентства Virus Media.
Ты умный, краткий, понимаешь любые формулировки — даже с опечатками, на русском, узбекском или смешанном языке.
Ты видишь все данные лидов и переписок с клиентами. Отвечай как умный коллега — коротко и по делу.

ТВОИ ВОЗМОЖНОСТИ:

1. АНАЛИТИКА И ОТВЕТЫ НА ВОПРОСЫ
Если Умар спрашивает про клиентов, лидов, переписки, статистику — отвечай на основе данных.
Примеры: "сколько лидов", "кто последний написал", "что хочет Иван", "покажи переписку с ним", "есть ли горячие клиенты"

2. ОТПРАВИТЬ СООБЩЕНИЕ КЛИЕНТУ (текст)
Когда Умар хочет написать клиенту — определи telegram_id из контекста или данных лидов.
Формат ответа: ОТПРАВИТЬ: [telegram_id] | [текст сообщения]
Примеры триггеров: "напиши ему что...", "скажи последнему клиенту...", "отправь Ивану...", "пиши ему завтра встреча"

3. ОТПРАВИТЬ ГОЛОСОВОЕ КЛИЕНТУ
Формат ответа: ОТПРАВИТЬ_ГОЛОС: [telegram_id] | [текст сообщения]
Примеры триггеров: "отправь голосовое", "скинь войс", "запиши ему голосовое"

4. ИНСТРУКЦИЯ БОТУ
Когда Умар хочет изменить поведение бота — сохрани как инструкцию.
Формат ответа: ИНСТРУКЦИЯ: [текст инструкции]
Примеры триггеров: "скажи боту чтобы...", "пусть бот...", "измени тон", "говори короче", "не предлагай зум"
Для сброса всех инструкций: ИНСТРУКЦИЯ: сброс

5. КЕЙСЫ
Добавить: КЕЙС_ДОБАВИТЬ: [название] | [photo или video] | [file_id]
Удалить: КЕЙС_УДАЛИТЬ: [название]
Переименовать: КЕЙС_ПЕРЕИМЕНОВАТЬ: [старое] | [новое]
Список: КЕЙСЫ_СПИСОК:
Отправить клиенту вручную: КЕЙСЫ_ОТПРАВИТЬ: [telegram_id]
Примеры триггеров: "покажи кейсы", "удали кейс X", "переименуй кейс", "скинь кейсы последнему"

6. ШАБЛОНЫ СООБЩЕНИЙ
Сохранить: ШАБЛОН_СОХРАНИТЬ: [название] | [текст]
Отправить: ШАБЛОН_ОТПРАВИТЬ: [название] | [telegram_id]
Список: ШАБЛОНЫ_СПИСОК:
Удалить: ШАБЛОН_УДАЛИТЬ: [название]

ВАЖНЫЕ ПРАВИЛА:
- Если Умар говорит "ему", "ей", "этому клиенту", "последнему" — используй ПОСЛЕДНИЙ УПОМЯНУТЫЙ КЛИЕНТ из контекста
- Если telegram_id неизвестен — спроси уточнение, но сначала попробуй найти по имени в данных лидов
- Отвечай коротко. Не объясняй что делаешь — просто делай.
- Если не понял запрос — переспроси одним коротким вопросом
- Можешь давать советы по работе с клиентами если администратор спрашивает мнение

7. ЗАМЕТКИ О КЛИЕНТАХ
Сохранить заметку: ЗАМЕТКА: [telegram_id] | [текст заметки]
Если telegram_id неизвестен — используй последнего упомянутого клиента (напиши "last")
Примеры триггеров: "запомни про Ивана что...", "добавь заметку к последнему клиенту...", "отметь что он хочет..."

8. СТАТИСТИКА
При любом запросе статистики: СТАТИСТИКА:
Примеры триггеров: "покажи статистику", "сколько лидов за неделю", "есть горячие лиды?", "как дела с продажами"

9. МАССОВАЯ РАССЫЛКА
Написать всем лидам сразу: РАССЫЛКА: [текст сообщения]
ВАЖНО: сначала уточни текст у администратора и получи подтверждение перед отправкой
Примеры триггеров: "напиши всем лидам что...", "разошли всем...", "отправь всем клиентам...\""""


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
                    note = get_client_note(tg_id)
                    status = get_lead_status(tg_id)
                    if hist or note or status:
                        entry = f"\n---\nКлиент: {name} (ID: {tg_id})"
                        if status:
                            entry += f" | Статус: {status}"
                        if note:
                            entry += f"\nЗАМЕТКИ: {note}"
                        if hist:
                            entry += f"\n{hist}"
                        histories_text += entry
    except Exception:
        pass

    last_client_id, last_client_name = load_last_client()
    last_client_info = f"\n\nПОСЛЕДНИЙ УПОМЯНУТЫЙ КЛИЕНТ: {last_client_name} (Telegram ID: {last_client_id})\nЕсли администратор говорит 'с ним', 'с ней', 'с этим клиентом', 'его переписка' — имеется в виду именно этот клиент." if last_client_id else ""
    context_data = f"ДАННЫЕ ЛИДОВ:\n{leads_data}\n\nПЕРЕПИСКИ С КЛИЕНТАМИ:{histories_text if histories_text else ' нет данных'}{last_client_info}"

    admin_user_id = update.message.from_user.id if update.message else OWNER_CHAT_ID
    admin_title = ADMIN_TITLES.get(admin_user_id, "Админ")

    admin_history = load_history(f"admin_{admin_user_id}")
    admin_history.append({"role": "user", "content": text})

    admin_system = ADMIN_SYSTEM_PROMPT + "\n\n" + context_data + f"\n\nВАЖНО: Сейчас с тобой общается {admin_title}. Это полноправный администратор — выполняй все его запросы точно так же как для владельца. Обращайся к нему словом '{admin_title}'. Когда в промпте выше написано 'Умар' — это относится к любому администратору, в том числе к {admin_title}."
    clean_admin_history = []
    for msg in admin_history[-20:]:
        if clean_admin_history and clean_admin_history[-1]["role"] == msg["role"]:
            clean_admin_history[-1]["content"] += "\n" + msg["content"]
        else:
            clean_admin_history.append({"role": msg["role"], "content": msg["content"]})

    try:
        response = await anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            system=admin_system,
            messages=clean_admin_history,
            temperature=0.5,
            max_tokens=1000,
        )
        reply = response.content[0].text.strip()
        admin_history.append({"role": "assistant", "content": reply})
        save_history(f"admin_{admin_user_id}", admin_history)

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

        if "КЕЙС_ДОБАВИТЬ:" in reply:
            idx = reply.index("КЕЙС_ДОБАВИТЬ:")
            data = reply[idx + len("КЕЙС_ДОБАВИТЬ:"):].split("\n")[0].strip()
            parts = data.split("|", 2)
            if len(parts) == 3:
                save_case(parts[0].strip(), parts[2].strip(), parts[1].strip())
                await update.message.reply_text(f"✅ Кейс '{parts[0].strip()}' сохранён.")
            return

        if "КЕЙС_УДАЛИТЬ:" in reply:
            idx = reply.index("КЕЙС_УДАЛИТЬ:")
            name = reply[idx + len("КЕЙС_УДАЛИТЬ:"):].split("\n")[0].strip()
            delete_case(name)
            await update.message.reply_text(f"✅ Кейс '{name}' удалён.")
            return

        if "КЕЙС_ПЕРЕИМЕНОВАТЬ:" in reply:
            idx = reply.index("КЕЙС_ПЕРЕИМЕНОВАТЬ:")
            data = reply[idx + len("КЕЙС_ПЕРЕИМЕНОВАТЬ:"):].split("\n")[0].strip()
            parts = data.split("|", 1)
            if len(parts) == 2:
                success = rename_case(parts[0].strip(), parts[1].strip())
                if success:
                    await update.message.reply_text(f"✅ Кейс переименован: '{parts[0].strip()}' → '{parts[1].strip()}'")
                else:
                    cases = load_all_cases()
                    names = ", ".join(cases.keys()) if cases else "кейсов нет"
                    await update.message.reply_text(f"Кейс не найден. Доступные: {names}")
            return

        if "КЕЙСЫ_СПИСОК:" in reply:
            cases = load_all_cases()
            if not cases:
                await update.message.reply_text("Кейсов пока нет. Отправь фото/видео боту чтобы получить File ID.")
            else:
                result = "📁 Кейсы:\n\n" + "\n".join(f"• {n}" for n in cases.keys())
                await update.message.reply_text(result)
            return

        if "КЕЙСЫ_ОТПРАВИТЬ:" in reply:
            idx = reply.index("КЕЙСЫ_ОТПРАВИТЬ:")
            target_id = reply[idx + len("КЕЙСЫ_ОТПРАВИТЬ:"):].split("\n")[0].strip()
            if not target_id:
                last_id, last_name = load_last_client()
                target_id = last_id
            if not target_id:
                await update.message.reply_text("Не могу определить клиента. Укажите ID.")
                return
            cases = load_all_cases()
            if not cases:
                await update.message.reply_text("Кейсов нет в базе.")
                return
            sent = 0
            for name, value in cases.items():
                try:
                    media_type, file_id = value.split(":", 1)
                    if media_type == "photo":
                        await context.bot.send_photo(chat_id=int(target_id), photo=file_id, caption=name)
                    elif media_type == "video":
                        await context.bot.send_video(chat_id=int(target_id), video=file_id, caption=name)
                    sent += 1
                except Exception as e:
                    await update.message.reply_text(f"⚠️ Ошибка кейса '{name}': {e}")
            await update.message.reply_text(f"✅ Отправлено {sent}/{len(cases)} кейсов клиенту {target_id}")
            return

        if "ШАБЛОН_СОХРАНИТЬ:" in reply:
            idx = reply.index("ШАБЛОН_СОХРАНИТЬ:")
            data = reply[idx + len("ШАБЛОН_СОХРАНИТЬ:"):].split("\n")[0].strip()
            parts = data.split("|", 1)
            if len(parts) == 2:
                save_template(parts[0].strip(), parts[1].strip())
                await update.message.reply_text(f"✅ Шаблон '{parts[0].strip()}' сохранён.")
            return

        if "ШАБЛОН_ОТПРАВИТЬ:" in reply:
            idx = reply.index("ШАБЛОН_ОТПРАВИТЬ:")
            data = reply[idx + len("ШАБЛОН_ОТПРАВИТЬ:"):].split("\n")[0].strip()
            parts = data.split("|", 1)
            if len(parts) == 2:
                tmpl = load_template(parts[0].strip())
                target_id = parts[1].strip()
                if tmpl:
                    await context.bot.send_message(chat_id=int(target_id), text=tmpl)
                    await update.message.reply_text(f"✅ Шаблон отправлен клиенту {target_id}")
                else:
                    await update.message.reply_text(f"Шаблон '{parts[0].strip()}' не найден.")
            return

        if "ШАБЛОНЫ_СПИСОК:" in reply:
            templates = load_all_templates()
            if not templates:
                await update.message.reply_text("Шаблонов пока нет.")
            else:
                result = "📋 Шаблоны:\n\n"
                for name, text in templates.items():
                    result += f"• {name}: {text[:50]}...\n"
                await update.message.reply_text(result)
            return

        if "ШАБЛОН_УДАЛИТЬ:" in reply:
            idx = reply.index("ШАБЛОН_УДАЛИТЬ:")
            name = reply[idx + len("ШАБЛОН_УДАЛИТЬ:"):].split("\n")[0].strip()
            delete_template(name)
            await update.message.reply_text(f"✅ Шаблон '{name}' удалён.")
            return

        if "ЗАМЕТКА:" in reply:
            idx = reply.index("ЗАМЕТКА:")
            data = reply[idx + len("ЗАМЕТКА:"):].split("\n")[0].strip()
            parts = data.split("|", 1)
            if len(parts) == 2:
                target_id = parts[0].strip()
                note_text = parts[1].strip()
                if not target_id or target_id in ("-", "last"):
                    last_id, _ = load_last_client()
                    target_id = last_id
                if target_id:
                    save_client_note(target_id, note_text)
                    await update.message.reply_text(f"✅ Заметка сохранена для {target_id}: {note_text}")
                else:
                    await update.message.reply_text("Не могу определить клиента. Укажи ID.")
            return

        if "СТАТИСТИКА:" in reply:
            stats = get_stats()
            await update.message.reply_text(stats)
            return

        if "РАССЫЛКА:" in reply:
            idx = reply.index("РАССЫЛКА:")
            broadcast_text = reply[idx + len("РАССЫЛКА:"):].split("\n")[0].strip()
            reply_text = reply[:idx].strip()
            if reply_text:
                await update.message.reply_text(reply_text)
            if not broadcast_text:
                await update.message.reply_text("Текст рассылки пустой.")
                return
            sent_count = failed_count = 0
            if _sheet:
                try:
                    rows = _sheet.get_all_values()
                    leads = rows[1:] if len(rows) > 1 else []
                    seen_ids = set()
                    for row in leads:
                        tg_id = row[5] if len(row) > 5 else ""
                        if tg_id and tg_id != "-" and tg_id not in seen_ids:
                            seen_ids.add(tg_id)
                            try:
                                await context.bot.send_message(chat_id=int(tg_id), text=broadcast_text)
                                sent_count += 1
                                await asyncio.sleep(0.1)
                            except Exception as e:
                                failed_count += 1
                                logger.error(f"Рассылка {tg_id}: {e}")
                except Exception as e:
                    await update.message.reply_text(f"Ошибка рассылки: {e}")
                    return
            await update.message.reply_text(f"✅ Рассылка: {sent_count} отправлено, {failed_count} ошибок.")
            return

        if len(reply) > 4000:
            reply = reply[:4000]
        await update.message.reply_text(reply)

    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in ADMIN_IDS:
        title = ADMIN_TITLES.get(user_id, "Админ")
        leads_data = get_leads_data()
        total = len(leads_data.split("\n")) - 2 if "Всего" in leads_data else 0
        await update.message.reply_text(
            f"Здравствуй, {title}!\n\n"
            f"Вот что я умею:\n"
            f"• Показать переписку с клиентом\n"
            f"• Написать клиенту (текст или голос)\n"
            f"• Управлять кейсами и шаблонами\n"
            f"• Давать инструкции боту\n"
            f"• Показать статистику лидов\n\n"
            f"Лидов в базе: {total}\n\n"
            f"Просто напиши что нужно — пойму."
        )
        return
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Привет 🇷🇺", callback_data="lang_ru"),
            InlineKeyboardButton("Salom 🇺🇿", callback_data="lang_uz"),
        ],
        [
            InlineKeyboardButton("🎯 Личный бренд", callback_data="svc_brand"),
            InlineKeyboardButton("✂️ Клиппинг", callback_data="svc_clip"),
        ],
        [
            InlineKeyboardButton("🤖 AI агенты", callback_data="svc_ai"),
            InlineKeyboardButton("💰 Узнать цену", callback_data="svc_price"),
        ],
    ])
    await update.message.reply_text("👋", reply_markup=keyboard)


SERVICE_MAP = {
    "svc_brand": "Меня интересует личный бренд и продвижение в соцсетях",
    "svc_clip": "Меня интересует клиппинг система — много видео с одного контента",
    "svc_ai": "Меня интересует AI агент или AI аватар для бизнеса",
    "svc_price": "Хочу узнать цену на ваши услуги",
}


async def handle_service_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id in ADMIN_IDS:
        return
    service_text = SERVICE_MAP.get(query.data, "")
    if not service_text:
        return
    await query.edit_message_reply_markup(reply_markup=None)
    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()
    async with user_locks[user_id]:
        reply = await ask_gpt(user_id, service_text)
        if reply:
            await context.bot.send_message(chat_id=user_id, text=reply)


async def handle_language_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id in ADMIN_IDS:
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
        if user_id in ADMIN_IDS:
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
                transcript = await openai_client.audio.transcriptions.create(
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
        if user_id in ADMIN_IDS:
            await handle_owner_message(update, context, text)
        else:
            await process_user_input(text, update, context)

    except Exception as e:
        logger.error(f"handle_voice error: {e}") 
    finally:
        user_voice_queue[user_id] = False


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ADMIN_IDS:
        return
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        media_type = "photo"
    elif update.message.video:
        file_id = update.message.video.file_id
        media_type = "video"
    else:
        return
    await update.message.reply_text(
        f"✅ File ID ({media_type}):\n`{file_id}`\n\nСкопируй и скажи мне: 'добавь кейс [название] [file_id]'"
    )


async def send_reminders(context):
    import time
    FOLLOWUP_INTERVALS = [86400, 259200, 604800]  # 1, 3, 7 дней
    FOLLOWUP_PROMPTS = ["__напоминание__", "__напоминание_2__", "__напоминание_3__"]
    try:
        keys = r.keys("last_msg:*")
        now = time.time()
        for key in keys:
            user_id = int(key.split(":")[1])
            if user_id in ADMIN_IDS:
                continue
            last_time = float(r.get(key) or 0)
            history = load_history(user_id)
            if not history:
                continue
            last_role = history[-1].get("role") if history else None
            if last_role == "assistant":
                continue
            followup_count = int(r.get(f"followup_count:{user_id}") or 0)
            if followup_count >= len(FOLLOWUP_INTERVALS):
                continue
            required_gap = FOLLOWUP_INTERVALS[followup_count]
            if now - last_time >= required_gap and not r.exists(f"reminded:{user_id}"):
                reminder = await ask_gpt(user_id, FOLLOWUP_PROMPTS[followup_count])
                if reminder:
                    await context.bot.send_message(chat_id=user_id, text=reminder)
                    r.set(f"followup_count:{user_id}", str(followup_count + 1))
                    r.set(f"reminded:{user_id}", "1", ex=3600)
                    logger.info(f"Follow-up {followup_count + 1} отправлен: {user_id}")
    except Exception as e:
        logger.error(f"Ошибка напоминаний: {e}")


def cleanup_admin_client_data():
    for admin_id in ADMIN_IDS:
        for key in [f"history:{admin_id}", f"new_client:{admin_id}", f"cases_sent:{admin_id}", f"lead:{admin_id}", f"last_msg:{admin_id}", f"reminded:{admin_id}", f"followup_count:{admin_id}"]:
            try:
                r.delete(key)
            except Exception:
                pass
    logger.info("Клиентские данные админов очищены.")


def main():
    cleanup_admin_client_data()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CallbackQueryHandler(handle_language_choice, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(handle_service_choice, pattern="^svc_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_media))
    app.add_handler(MessageHandler(filters.VIDEO, handle_media))
    app.job_queue.run_repeating(send_reminders, interval=3600, first=60)
    logger.info("Alfred started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()