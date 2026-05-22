import os
import sys
import json
import logging
import asyncio
from datetime import datetime

# ── Startup diagnostics ──────────────────────────────────────────────────────
print(f"Python version: {sys.version}", flush=True)
print(f"Starting bot...", flush=True)

required_vars = ["TELEGRAM_TOKEN", "OPENROUTER_KEY", "ADMIN_CHAT_ID"]
missing = [v for v in required_vars if not os.environ.get(v)]
if missing:
    print(f"ERROR: Missing environment variables: {missing}", flush=True)
    sys.exit(1)

print("All required env vars present ✓", flush=True)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import httpx

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
OPENROUTER_KEY   = os.environ["OPENROUTER_KEY"]
ADMIN_CHAT_ID    = int(os.environ["ADMIN_CHAT_ID"])   # your Telegram user ID
MODEL            = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
SHOP_NAME        = "Малярний"

# ── Load product catalog ─────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)
with open(os.path.join(BASE_DIR, "products.json"), encoding="utf-8") as f:
    PRODUCTS: list[dict] = json.load(f)

# Build compact catalog text for system prompt (group by category)
def build_catalog_text() -> str:
    from collections import defaultdict
    by_cat = defaultdict(list)
    for p in PRODUCTS:
        by_cat[p["category"]].append(p)

    lines = []
    for cat, items in by_cat.items():
        lines.append(f"\n### {cat}")
        for p in items:
            avail = p["availability"]
            vol   = f"{p['volume_l']}л" if p["volume_l"] else ""
            price = f"{p['price_uah']:.0f} грн" if p["price_uah"] else "—"
            desc  = f" | {p['description']}" if p["description"] else ""
            lines.append(
                f"- {p['name']} {p['base_color']} {vol} | арт.{p['article']} | {price} | {avail}{desc}"
            )
    return "\n".join(lines)

CATALOG_TEXT = build_catalog_text()

SYSTEM_PROMPT = f"""Ти — консультант інтернет-магазину лакофарбових матеріалів «{SHOP_NAME}».
Твоє завдання: зрозуміти потребу клієнта, задати уточнюючі питання (поверхня, приміщення, умови, бажаний колір, площа) і підібрати оптимальний товар з асортименту магазину.

ПРАВИЛА:
1. Спілкуйся виключно українською мовою, дружньо і професійно.
2. Відповідай лаконічно — не більше 3-4 речень + список товарів якщо потрібно.
3. Якщо клієнт описав задачу — одразу пропонуй 1-3 конкретні товари з артикулом і ціною.
4. Якщо не маєш точної відповіді — чесно скажи "Я передам ваше питання менеджеру" і завверши відповідь тегом [FORWARD_TO_MANAGER].
5. Ніколи не вигадуй товари, яких немає в каталозі нижче.
6. Якщо клієнт хоче зробити замовлення або залишити контакт — скажи що менеджер зв'яжеться і постав тег [FORWARD_TO_MANAGER].
7. Для кожного рекомендованого товару вказуй: Назва, Артикул, Ціна, Наявність.

АСОРТИМЕНТ МАГАЗИНУ:
{CATALOG_TEXT}
"""

# ── In-memory conversation storage ──────────────────────────────────────────
conversations: dict[int, list[dict]] = {}

def get_history(chat_id: int) -> list[dict]:
    if chat_id not in conversations:
        conversations[chat_id] = []
    return conversations[chat_id]

def add_message(chat_id: int, role: str, content: str):
    history = get_history(chat_id)
    history.append({"role": role, "content": content})
    # Keep last 20 messages to stay within context
    if len(history) > 20:
        conversations[chat_id] = history[-20:]

# ── OpenRouter API ───────────────────────────────────────────────────────────
async def ask_ai(chat_id: int, user_text: str) -> str:
    add_message(chat_id, "user", user_text)
    messages = get_history(chat_id)

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "HTTP-Referer": f"https://t.me/{SHOP_NAME}Bot",
                "X-Title": f"{SHOP_NAME} Bot",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    *messages
                ],
                "max_tokens": 1024,
                "temperature": 0.4,
            }
        )
        response.raise_for_status()
        data = response.json()

    reply = data["choices"][0]["message"]["content"].strip()
    add_message(chat_id, "assistant", reply)
    return reply

# ── Forward to admin ─────────────────────────────────────────────────────────
async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user = update.effective_user
    username = f"@{user.username}" if user.username else f"ID:{user.id}"
    name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Без імені"
    time_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    # Build last 5 messages context
    history = get_history(update.effective_chat.id)
    dialog = "\n".join(
        f"{'👤' if m['role']=='user' else '🤖'} {m['content'][:200]}"
        for m in history[-6:]
    )

    admin_msg = (
        f"🔔 *Нове звернення до менеджера*\n"
        f"👤 {name} ({username})\n"
        f"🕐 {time_str}\n"
        f"💬 Останнє питання: _{user_text[:300]}_\n\n"
        f"📋 *Діалог:*\n{dialog}"
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_msg,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to forward to admin: {e}")

# ── Handlers ─────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversations.pop(update.effective_chat.id, None)  # clear history
    keyboard = [
        [InlineKeyboardButton("🎨 Фарби інтер'єрні", callback_data="cat_interior")],
        [InlineKeyboardButton("🏠 Фасадні фарби", callback_data="cat_facade")],
        [InlineKeyboardButton("🔩 Антикорозійні покриття", callback_data="cat_anticorr")],
        [InlineKeyboardButton("🌲 Покриття для дерева", callback_data="cat_wood")],
        [InlineKeyboardButton("✉️ Зв'язатися з менеджером", callback_data="manager")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"👋 Вітаю в магазині *{SHOP_NAME}*!\n\n"
        "Я — ваш консультант з лакофарбових матеріалів TEKNOS.\n"
        "Опишіть завдання, і я підберу потрібний товар — або оберіть категорію:\n",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    cat_map = {
        "cat_interior":  "Мене цікавлять інтер'єрні фарби для внутрішніх робіт",
        "cat_facade":    "Мене цікавлять фасадні фарби для зовнішніх робіт",
        "cat_anticorr":  "Мене цікавлять антикорозійні покриття для металу",
        "cat_wood":      "Мене цікавлять покриття та фарби для деревини",
        "manager":       "Хочу поговорити з менеджером магазину",
    }

    text = cat_map.get(query.data, query.data)
    await query.message.reply_text(f"🔍 {text}")
    await process_message(update, context, text, query.message.chat_id)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    await process_message(update, context, text, update.effective_chat.id)

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, chat_id: int):
    # Show typing indicator
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        reply = await ask_ai(chat_id, text)
    except Exception as e:
        logger.error(f"AI error: {e}")
        reply = (
            "Вибачте, виникла технічна помилка. "
            "Ваше питання передане менеджеру. [FORWARD_TO_MANAGER]"
        )

    # Check if we need to forward
    needs_forward = "[FORWARD_TO_MANAGER]" in reply
    clean_reply = reply.replace("[FORWARD_TO_MANAGER]", "").strip()

    await context.bot.send_message(
        chat_id=chat_id,
        text=clean_reply,
        parse_mode="Markdown"
    )

    if needs_forward:
        await forward_to_admin(update, context, text)
        await context.bot.send_message(
            chat_id=chat_id,
            text="📨 Ваше питання передано менеджеру. Зазвичай відповідаємо протягом кількох годин.",
        )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversations.pop(update.effective_chat.id, None)
    await update.message.reply_text("🔄 Розмову скинуто. /start — розпочати знову.")

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting polling mode")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
