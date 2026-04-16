import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from openai import OpenAI

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OWNER_CHAT_ID = 7567850330

client = OpenAI(api_key=OPENAI_API_KEY)

user_histories = {}
sent_leads = set()

SYSTEM_PROMPT = """Ты топовый менеджер по продажам маркетингового агентства Virus Media. Твоя главная цель — ПРОДАТЬ услуги и записать клиента на консультацию.

НАШИ УСЛУГИ:

1. AI-АВАТАР ДЛЯ БЛОГА
— Создаём цифрового аватара человека на основе его внешности и голоса
— Аватар ведёт блог от лица клиента без его участия
— Клиент зарабатывает и растёт в соцсетях пока спит!

2. ВЕДЕНИЕ АККАУНТОВ (КЛИПИНГ)
— Берём контент клиента и распространяем на 10-20 аккаунтах одновременно
— Клиент растёт в 10-20 раз быстрее конкурентов
— Работаем с Instagram, TikTok, YouTube Shorts, Telegram

3. КОМПЛЕКСНОЕ ПРОДВИЖЕНИЕ
— AI-аватар + клипинг на множестве аккаунтов
— Полное ведение без участия клиента

ПРАВИЛА ПРОДАЖ:
— Всегда подчёркивай выгоду для клиента
— Создавай срочность — говори что места ограничены
— Если клиент сомневается — предложи БЕСПЛАТНУЮ консультацию
— Если спрашивают цену — скажи от $200 но сначала нужна консультация
— Всегда заканчивай вопросом чтобы продолжить диалог
— Никогда не сдавайся — если клиент говорит нет найди другой аргумент

СБОР ДАННЫХ — делай по порядку:
1. Сначала спроси ИМЯ
2. Потом спроси НОМЕР ТЕЛЕФОНА
3. Потом спроси что именно интересует
4. Потом спроси УДОБНОЕ ВРЕМЯ для консультации
5. Когда получишь все четыре данных напиши в конце: ДАННЫЕ_КЛИЕНТА: [имя] | [телефон] | [интересы] | [время]
6. После этого продолжай разговор — поблагодари и скажи что менеджер свяжется в указанное время

важно на коком языке был задан вопрос Отвечай на узбекском или  русском  """

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_name = update.message.from_user.first_name
    user_id = update.message.from_user.id

    if user_id not in user_histories:
        user_histories[user_id] = []

    user_histories[user_id].append({
        "role": "user",
        "content": user_message
    })

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += user_histories[user_id]

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages
    )

    reply = response.choices[0].message.content

    user_histories[user_id].append({
        "role": "assistant",
        "content": reply
    })

    if "ДАННЫЕ_КЛИЕНТА:" in reply:
        clean_reply = reply.split("ДАННЫЕ_КЛИЕНТА:")[0].strip()
        await update.message.reply_text(clean_reply)

        if user_id not in sent_leads:
            sent_leads.add(user_id)
            data = reply.split("ДАННЫЕ_КЛИЕНТА:")[1].strip()
            parts = data.split("|")
            name = parts[0].strip() if len(parts) > 0 else "—"
            phone = parts[1].strip() if len(parts) > 1 else "—"
            interests = parts[2].strip() if len(parts) > 2 else "—"
            time = parts[3].strip() if len(parts) > 3 else "—"

            await context.bot.send_message(
                chat_id=OWNER_CHAT_ID,
                text=f"🔥 НОВЫЙ ЛИД!\n\n👤 Имя: {name}\n📞 Телефон: {phone}\n💡 Интересы: {interests}\n🕐 Время: {time}\n\n🆔 Telegram ID: {user_id}\n👤 Telegram имя: {user_name}"
            )
    else:
        await update.message.reply_text(reply)

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
print("Бот запущен!")
app.run_polling()