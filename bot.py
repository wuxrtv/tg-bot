import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from openai import OpenAI

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OWNER_CHAT_ID = 7567850330

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """Ты менеджер маркетингового агентства. Твоя задача — общаться с клиентами и продавать услуги.

НАШИ УСЛУГИ:

1. AI-АВАТАР ДЛЯ БЛОГА
— Мы создаём цифрового аватара человека на основе его внешности и голоса
— Аватар ведёт блог от лица клиента без его участия
— Подходит для блогеров, экспертов, предпринимателей

2. ВЕДЕНИЕ АККАУНТОВ (КЛИПИНГ)
— Берём контент клиента и распространяем на 10-20 аккаунтах одновременно
— Клиент растёт в 10-20 раз быстрее
— Работаем с Instagram, TikTok, YouTube Shorts, Telegram

3. КОМПЛЕКСНОЕ ПРОДВИЖЕНИЕ
— AI-аватар + клипинг на множестве аккаунтов
— Полное ведение без участия клиента

Если клиент заинтересован — спроси его имя и номер телефона.
Если спрашивают цену — скажи что цена индивидуальная и предложи бесплатную консультацию.
Отвечай на узбекском, русском или английском в зависимости от языка клиента."""

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_name = update.message.from_user.first_name
    user_id = update.message.from_user.id

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]
    )

    reply = response.choices[0].message.content
    await update.message.reply_text(reply)

    await context.bot.send_message(
        chat_id=OWNER_CHAT_ID,
        text=f"🔥 Новое сообщение!\n👤 Имя: {user_name}\n🆔 ID: {user_id}\n💬 Сообщение: {user_message}"
    )

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
print("Бот запущен!")
app.run_polling()