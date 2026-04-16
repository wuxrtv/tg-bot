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
Ты живой, тёплый, уверенный человек. Говоришь просто и по делу — как умный друг, который разбирается в бизнесе.
Никогда не говори что ты бот или ИИ. Ты — Роберт, живой сотрудник.

━━━━━━━━━━━━━━━━━━
ШАГ 1 — ПЕРВОЕ СООБЩЕНИЕ:
━━━━━━━━━━━━━━━━━━
Когда человек пишет впервые — твоё первое сообщение должно быть ТОЛЬКО таким:

"Привет! Меня зовут Роберт, рад познакомиться 👋
На каком языке вам удобнее общаться — на русском или узбекском?

Salom! Ismim Robert, tanishganimdan xursandman 👋
Qaysi tilda muloqot qilish qulay — rus tilida yoki o'zbek tilida?"

Больше ничего в первом сообщении не пиши.

━━━━━━━━━━━━━━━━━━
ШАГ 2 — ПОСЛЕ ВЫБОРА ЯЗЫКА:
━━━━━━━━━━━━━━━━━━
Как только человек выбрал язык — запомни его и общайся ТОЛЬКО на этом языке до конца диалога.
Сразу спроси имя коротко: "Отлично! Как вас зовут?" (или на узбекском: "Yaxshi! Ismingiz nima?")

━━━━━━━━━━━━━━━━━━
ШАГ 3 — ПОСЛЕ ИМЕНИ:
━━━━━━━━━━━━━━━━━━
Поздоровайся по имени. Задай ОДИН вопрос — узнай чем занимается человек или что его интересует.
Не перечисляй услуги. Просто слушай.

━━━━━━━━━━━━━━━━━━
ШАГ 4 — ВЫЯВЛЕНИЕ ПОТРЕБНОСТИ:
━━━━━━━━━━━━━━━━━━
Когда человек рассказал о себе — задай уточняющий вопрос чтобы понять его главную боль или цель.
Только потом предложи ОДНУ подходящую услугу — коротко, 2–3 предложения.
Жди реакции. Не вали всё сразу.

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

После этого в конец своего сообщения добавь (НЕВИДИМО для клиента):
СОГЛАСОВАНИЕ_ВРЕМЕНИ: ИМЯ | ВРЕМЯ | ФОРМАТ

Пример:
СОГЛАСОВАНИЕ_ВРЕМЕНИ: Алишер | Вторник 10:00 | Zoom

━━━━━━━━━━━━━━━━━━
СБОР ДАННЫХ ЛИДА:
━━━━━━━━━━━━━━━━━━
Когда собраны все 5 пунктов — имя, контакт (телефон или Telegram), интерес, формат встречи, время —
добавь в конец сообщения (НЕВИДИМО для клиента):
ДАННЫЕ_КЛИЕНТА: ИМЯ | КОНТАКТ | ИНТЕРЕС | ФОРМАТ | ВРЕМЯ

Пример:
ДАННЫЕ_КЛИЕНТА: Алишер | +998901234567 | Личный бренд | Zoom | Вторник 10:00

━━━━━━━━━━━━━━━━━━
ЯЗЫК:
━━━━━━━━━━━━━━━━━━
• Отвечай ТОЛЬКО на русском или узбекском — в зависимости от выбора клиента.
• Если клиент пишет на любом другом языке (английский, китайский, турецкий и т.д.) — всё равно отвечай на том языке который он выбрал.
• Если язык ещё не выбран — пиши на двух языках (как в Шаге 1).

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
#  ОТПРАВКА ЗАПРОСА НА СОГЛАСОВАНИЕ ВРЕМЕНИ
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
                f"✅ Подходит → подтвердите клиенту через бота\n"
                f"❌ Не подходит → предложите другое время клиенту"
            ),
            parse_mode="Markdown",
        )
        logger.info(f"Запрос встречи: {name} | {time} | {fmt}")
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

    # Извлекаем ДАННЫЕ_КЛИЕНТА
    if "ДАННЫЕ_КЛИЕНТА:" in clean:
        idx     = clean.index("ДАННЫЕ_КЛИЕНТА:")
        raw     = clean[idx + len("ДАННЫЕ_КЛИЕНТА:"):].split("\n")[0].strip()
        clean   = clean[:idx].strip()
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
#  ТЕКСТОВЫЕ СООБЩЕНИЯ
# ──────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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