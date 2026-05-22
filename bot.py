import os
import sys
import json
import logging
import asyncio
from datetime import datetime

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

print(f"Python version: {sys.version}", flush=True)
print("Starting bot...", flush=True)

required_vars = ["TELEGRAM_TOKEN", "ADMIN_CHAT_ID"]
missing = [v for v in required_vars if not os.environ.get(v)]
if missing:
    print(f"ERROR: Missing env vars: {missing}", flush=True)
    sys.exit(1)
print("All required env vars present ✓", flush=True)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ADMIN_CHAT_ID  = int(os.environ["ADMIN_CHAT_ID"])
SHOP_NAME      = "Малярний"

# ── Forwarding storage ────────────────────────────────────────────────────────
# chat_id → True if already forwarded to admin
forwarded: dict[int, bool] = {}
seen_users: set[int] = {}

# ── Keyboards ─────────────────────────────────────────────────────────────────
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Написати запит", callback_data="write")],
        [InlineKeyboardButton("📱 Поділитися номером", callback_data="phone")],
    ])

def phone_keyboard():
    btn = KeyboardButton("📱 Поділитися номером", request_contact=True)
    return ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True)

# ── Notify admin ──────────────────────────────────────────────────────────────
async def notify_admin(context, update_or_chat_id, text: str, user, phone: str = None):
    chat_id  = user.id
    username = f"@{user.username}" if user.username else f"ID:{chat_id}"
    name     = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Без імені"
    time_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    phone_str = phone if phone else "не вказано"

    msg = (
        f"🔔 {SHOP_NAME} — новий клієнт\n"
        f"{'─'*28}\n"
        f"👤 {name}  {username}\n"
        f"📱 {phone_str}\n"
        f"🕐 {time_str}\n"
        f"{'─'*28}\n"
        f"💬 {text}\n"
        f"{'─'*28}\n"
        f"👉 Написати: tg://user?id={chat_id}"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg)
        forwarded[chat_id] = True
    except Exception as e:
        logger.error(f"Admin notify error: {e}")

# ── Handlers ──────────────────────────────────────────────────────────────────
async def greet(chat_id: int, context, reply_func):
    forwarded.pop(chat_id, None)
    seen_users.add(chat_id)
    await reply_func(
        f"Привіт! 👋 Магазин *{SHOP_NAME}* — лакофарбові матеріали.\n\n"
        "Що вас цікавить? Напишіть — менеджер одразу побачить ваш запит 🎨",
        parse_mode="Markdown"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await greet(chat_id, context, update.message.reply_text)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "write":
        await query.message.reply_text("Пишіть — слухаємо 👇")

    elif query.data == "phone":
        await query.message.reply_text(
            "Натисніть кнопку — і менеджер сам зателефонує вам:",
            reply_markup=phone_keyboard()
        )

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    phone = update.message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone

    await update.message.reply_text(
        "✅ Дякуємо! Менеджер зателефонує вам найближчим часом.",
        reply_markup=ReplyKeyboardRemove()
    )
    await notify_admin(context, update, f"[Залишив номер телефону: {phone}]", update.effective_user, phone)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text    = update.message.text.strip()
    user    = update.effective_user

    # Auto-greet if first time
    if chat_id not in seen_users:
        seen_users.add(chat_id)
        await update.message.reply_text(
            f"Привіт! 👋 Магазин *{SHOP_NAME}* — лакофарбові матеріали.\n\n"
            "Що вас цікавить? Напишіть — менеджер одразу побачить ваш запит 🎨",
            parse_mode="Markdown"
        )
        return

    # Forward to admin
    await notify_admin(context, update, text, user)

    # Reply to client
    await update.message.reply_text(
        "✅ Дякуємо! Менеджер вже бачить ваш запит і зв'яжеться з вами найближчим часом.\n\n"
        "Зазвичай відповідаємо протягом кількох хвилин 🕐"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    seen_users.discard(chat_id)
    forwarded.pop(chat_id, None)
    await greet(chat_id, context, update.message.reply_text)

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
