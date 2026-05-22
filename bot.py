import os
import sys
import json
import logging
import asyncio
import re
from datetime import datetime

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

print(f"Python version: {sys.version}", flush=True)
print("Starting bot...", flush=True)

required_vars = ["TELEGRAM_TOKEN", "OPENROUTER_KEY", "ADMIN_CHAT_ID"]
missing = [v for v in required_vars if not os.environ.get(v)]
if missing:
    print(f"ERROR: Missing env vars: {missing}", flush=True)
    sys.exit(1)
print("All required env vars present ✓", flush=True)

from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import httpx

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENROUTER_KEY = os.environ["OPENROUTER_KEY"]
ADMIN_CHAT_ID  = int(os.environ["ADMIN_CHAT_ID"])
MODEL          = os.environ.get("OPENROUTER_MODEL", "openai/gpt-oss-120b:free")
SHOP_NAME      = "Малярний"
SHOP_PHONE     = os.environ.get("SHOP_PHONE", "")  # optional

# ── Session storage ───────────────────────────────────────────────────────────
# States: start → name → task → surface → area → phone → done
sessions: dict[int, dict] = {}

def get_session(chat_id: int) -> dict:
    if chat_id not in sessions:
        sessions[chat_id] = {
            "state": "start",
            "name": None,
            "task": None,
            "surface": None,
            "area": None,
            "phone": None,
            "tg_username": None,
        }
    return sessions[chat_id]

# ── Send to admin ─────────────────────────────────────────────────────────────
async def notify_admin(context, session: dict, chat_id: int):
    name     = session.get("name") or "не вказано"
    task     = session.get("task") or "не вказано"
    surface  = session.get("surface") or "не вказано"
    area     = session.get("area") or "не вказано"
    phone    = session.get("phone") or "не вказано"
    username = session.get("tg_username") or "—"
    time_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    msg = (
        f"🔔 НОВА ЗАЯВКА — {SHOP_NAME}\n"
        f"{'─'*30}\n"
        f"👤 Ім'я: {name}\n"
        f"📱 Телефон: {phone}\n"
        f"✈️ Telegram: {username}\n"
        f"🕐 Час: {time_str}\n"
        f"{'─'*30}\n"
        f"🎨 Завдання: {task}\n"
        f"🏠 Поверхня: {surface}\n"
        f"📐 Площа: {area}\n"
        f"{'─'*30}\n"
        f"👉 tg://user?id={chat_id}"
    )

    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg)
        logger.info(f"Admin notified about chat_id={chat_id}")
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

# ── Keyboards ─────────────────────────────────────────────────────────────────
def task_keyboard():
    buttons = [
        [InlineKeyboardButton("🏠 Стіни / стеля (інтер'єр)", callback_data="task_interior")],
        [InlineKeyboardButton("🏡 Фасад / зовнішні роботи", callback_data="task_facade")],
        [InlineKeyboardButton("🌲 Дерево (підлога, двері, меблі)", callback_data="task_wood")],
        [InlineKeyboardButton("🔩 Метал / антикорозія", callback_data="task_metal")],
        [InlineKeyboardButton("🧱 Бетон / ґрунтування", callback_data="task_primer")],
        [InlineKeyboardButton("✏️ Інше — напишу сам", callback_data="task_other")],
    ]
    return InlineKeyboardMarkup(buttons)

def surface_keyboard():
    buttons = [
        [InlineKeyboardButton("Нова (ще не фарбована)", callback_data="surf_new")],
        [InlineKeyboardButton("Стара фарба є", callback_data="surf_old")],
        [InlineKeyboardButton("Після ремонту / шпаклівка", callback_data="surf_repair")],
        [InlineKeyboardButton("Не знаю", callback_data="surf_unknown")],
    ]
    return InlineKeyboardMarkup(buttons)

def phone_keyboard():
    btn = KeyboardButton("📱 Поділитися номером", request_contact=True)
    return ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True)

def confirm_keyboard():
    buttons = [
        [InlineKeyboardButton("✅ Підтвердити заявку", callback_data="confirm_yes")],
        [InlineKeyboardButton("✏️ Змінити дані", callback_data="confirm_no")],
    ]
    return InlineKeyboardMarkup(buttons)

# ── Handlers ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sessions.pop(chat_id, None)
    session = get_session(chat_id)
    session["tg_username"] = f"@{update.effective_user.username}" if update.effective_user.username else f"ID:{chat_id}"

    await update.message.reply_text(
        f"👋 Вітаю! Це магазин *{SHOP_NAME}*.\n\n"
        "Допоможу швидко оформити заявку на консультацію — менеджер підбере потрібний матеріал і передзвонить.\n\n"
        "Як вас звати?",
        parse_mode="Markdown"
    )
    session["state"] = "name"

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle phone number shared via button"""
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    contact = update.message.contact
    phone = contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    session["phone"] = phone

    await update.message.reply_text(
        "Дякую! Видалив клавіатуру.",
        reply_markup=ReplyKeyboardRemove()
    )
    await show_confirmation(update, context, chat_id)

async def show_confirmation(update, context, chat_id: int):
    session = get_session(chat_id)
    name    = session.get("name", "—")
    task    = session.get("task", "—")
    surface = session.get("surface", "—")
    area    = session.get("area", "—")
    phone   = session.get("phone", "—")

    text = (
        "📋 *Перевірте дані заявки:*\n\n"
        f"👤 Ім'я: {name}\n"
        f"🎨 Завдання: {task}\n"
        f"🏠 Поверхня: {surface}\n"
        f"📐 Площа: {area}\n"
        f"📱 Телефон: {phone}\n\n"
        "Все вірно?"
    )
    await context.bot.send_message(chat_id=chat_id, text=text,
                                   parse_mode="Markdown",
                                   reply_markup=confirm_keyboard())
    session["state"] = "confirm"

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    session = get_session(chat_id)
    data = query.data

    # Task selection
    if data.startswith("task_"):
        task_map = {
            "task_interior": "Фарбування стін / стелі (інтер'єр)",
            "task_facade":   "Фасад / зовнішні роботи",
            "task_wood":     "Покриття для дерева",
            "task_metal":    "Фарба / захист для металу",
            "task_primer":   "Ґрунтування бетону",
            "task_other":    None,
        }
        task = task_map.get(data)
        if task is None:
            await query.message.reply_text("Напишіть коротко що саме потрібно зробити:")
            session["state"] = "task_text"
            return
        session["task"] = task
        session["state"] = "surface"
        await query.message.reply_text(
            "Який стан поверхні?",
            reply_markup=surface_keyboard()
        )

    # Surface selection
    elif data.startswith("surf_"):
        surf_map = {
            "surf_new":     "Нова поверхня",
            "surf_old":     "Є стара фарба",
            "surf_repair":  "Після ремонту / шпаклівка",
            "surf_unknown": "Не знаю",
        }
        session["surface"] = surf_map.get(data, "—")
        session["state"] = "area"
        await query.message.reply_text(
            "Яка приблизна площа? (наприклад: *20 м²*, або *кімната 4×5 м*)\n\n"
            "Якщо не знаєте — напишіть *не знаю*",
            parse_mode="Markdown"
        )

    # Confirm
    elif data == "confirm_yes":
        await notify_admin(context, session, chat_id)
        session["state"] = "done"
        shop_ph = f"\n📞 Або зателефонуйте нам: {SHOP_PHONE}" if SHOP_PHONE else ""
        await query.message.reply_text(
            "✅ *Заявку прийнято!*\n\n"
            "Менеджер зв'яжеться з вами найближчим часом.\n"
            f"Зазвичай передзвонюємо протягом 1 години в робочий час (9:00–18:00).{shop_ph}\n\n"
            "Дякуємо що обрали нас! 🎨",
            parse_mode="Markdown"
        )

    elif data == "confirm_no":
        sessions.pop(chat_id, None)
        await query.message.reply_text(
            "Добре, почнемо заново. Як вас звати?"
        )
        session = get_session(chat_id)
        session["tg_username"] = f"@{query.from_user.username}" if query.from_user.username else f"ID:{chat_id}"
        session["state"] = "name"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    text = update.message.text.strip()
    state = session.get("state", "start")

    if state == "start" or state == "done":
        await start(update, context)
        return

    elif state == "name":
        session["name"] = text[:50]
        session["state"] = "task"
        await update.message.reply_text(
            f"Приємно познайомитись, *{session['name']}*! 👋\n\n"
            "Що потрібно зробити?",
            parse_mode="Markdown",
            reply_markup=task_keyboard()
        )

    elif state == "task_text":
        session["task"] = text[:200]
        session["state"] = "surface"
        await update.message.reply_text(
            "Який стан поверхні?",
            reply_markup=surface_keyboard()
        )

    elif state == "area":
        session["area"] = text[:100]
        session["state"] = "phone"
        await update.message.reply_text(
            "Останній крок — *номер телефону* для зворотного зв'язку.\n\n"
            "Натисніть кнопку нижче або введіть номер вручну:",
            parse_mode="Markdown",
            reply_markup=phone_keyboard()
        )

    elif state == "phone":
        # Manual phone entry
        phone_match = re.search(r'[\d\+][\d\s\-\(\)]{8,}', text)
        if phone_match:
            session["phone"] = phone_match.group().strip()
            await update.message.reply_text("Дякую!", reply_markup=ReplyKeyboardRemove())
            await show_confirmation(update, context, chat_id)
        else:
            await update.message.reply_text(
                "Будь ласка, введіть коректний номер телефону (або скористайтесь кнопкою):"
            )

    elif state == "confirm":
        await update.message.reply_text(
            "Оберіть один з варіантів вище ⬆️",
            reply_markup=confirm_keyboard()
        )

    else:
        await start(update, context)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sessions.pop(update.effective_chat.id, None)
    await update.message.reply_text("Розмову скинуто.", reply_markup=ReplyKeyboardRemove())
    await start(update, context)

# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting polling mode")
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot is running!")
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
