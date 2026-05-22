import os
import traceback
import requests

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

# =========================
# LOAD ENV
# =========================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))

# =========================
# BOT INIT
# =========================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# =========================
# KEYBOARD
# =========================

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📍 Контакти"),
            KeyboardButton(text="🎨 Каталог"),
        ],
    ],
    resize_keyboard=True,
)

# =========================
# AI FUNCTION
# =========================

def ai_answer(user_text):

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    data = {
        "model": "openai/gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": """
Ти менеджер магазину Малярний.

Магазин продає:
- фарби
- декоративні штукатурки
- матеріали Teknos
- Aura
- Eskaro

Відповідай коротко і українською.
""",
            },
            {
                "role": "user",
                "content": user_text,
            },
        ],
    }

    try:

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=60,
        )

        result = response.json()

        return result["choices"][0]["message"]["content"]

    except Exception as e:
        print("AI ERROR:")
        traceback.print_exc()
        return "Помилка AI. Спробуйте пізніше."

# =========================
# START
# =========================

@dp.message(CommandStart())
async def start(message: Message):

    text = """
🎨 Вітаємо у магазині Малярний!

Професійні фарби та декоративні матеріали.

✔ Teknos
✔ Aura
✔ Eskaro

👇 Оберіть що вас цікавить
"""

    await message.answer(
        text,
        reply_markup=main_keyboard,
    )

# =========================
# CONTACTS
# =========================

@dp.message(F.text == "📍 Контакти")
async def contacts(message: Message):

    text = """
📍 Івано-Франківськ
вул. Вовчинецька 191

📞 063 770 24 57
📞 068 770 24 57
"""

    await message.answer(text)

# =========================
# PHOTO
# =========================

@dp.message(F.photo)
async def photo(message: Message):

    await bot.forward_message(
        ADMIN_CHAT_ID,
        message.chat.id,
        message.message_id,
    )

    await message.answer(
        "✅ Фото отримано. Менеджер скоро відповість."
    )

# =========================
# CHAT
# =========================

@dp.message()
async def chat(message: Message):

    user_text = message.text

    if any(char.isdigit() for char in user_text):

        await bot.send_message(
            ADMIN_CHAT_ID,
            f"📞 Новий номер телефону:\n{user_text}"
        )

    answer = ai_answer(user_text)

    await message.answer(answer)

# =========================
# RUN
# =========================

if __name__ == "__main__":

    try:
        print("BOT STARTED")

        dp.run_polling(bot)

    except Exception as e:
        print("ERROR:")
        traceback.print_exc()
