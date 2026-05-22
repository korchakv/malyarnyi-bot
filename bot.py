import os
import sys
import json
import logging
import asyncio
from datetime import datetime
from collections import defaultdict

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

print(f"Python version: {sys.version}", flush=True)
print("Starting bot...", flush=True)

required_vars = ["TELEGRAM_TOKEN", "OPENROUTER_KEY", "ADMIN_CHAT_ID"]
missing = [v for v in required_vars if not os.environ.get(v)]
if missing:
    print(f"ERROR: Missing env vars: {missing}", flush=True)
    sys.exit(1)
print("All required env vars present ✓", flush=True)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import httpx

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENROUTER_KEY = os.environ["OPENROUTER_KEY"]
ADMIN_CHAT_ID  = int(os.environ["ADMIN_CHAT_ID"])
MODEL          = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
SHOP_NAME      = "Малярний"

# ── Load catalog ─────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)
with open(os.path.join(BASE_DIR, "products.json"), encoding="utf-8") as f:
    PRODUCTS: list[dict] = json.load(f)

def build_catalog_text() -> str:
    by_brand_cat = defaultdict(list)
    for p in PRODUCTS:
        key = f"{p['brand']} / {p['category']}"
        by_brand_cat[key].append(p)

    lines = []
    for key in sorted(by_brand_cat.keys()):
        items = by_brand_cat[key]
        lines.append(f"\n## {key}")
        for p in items:
            vol   = f"{p['volume']}{p.get('volume_unit','л')}" if p.get('volume') else ""
            price = f"{p['price']:.0f}грн" if p.get('price') else "—"
            avail = p.get('availability', 'В наявності')
            desc  = f" | {p['short_desc'][:80]}" if p.get('short_desc') else ""
            lines.append(f"- [{p['brand']}] {p['name']} | {p.get('base_color','')} | {vol} | арт.{p.get('article','')} | {price} | {avail}{desc}")
    return "\n".join(lines)

CATALOG_TEXT = build_catalog_text()
print(f"Catalog loaded: {len(PRODUCTS)} products, {len(CATALOG_TEXT)} chars", flush=True)

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""Ти — Маля, експерт-консультант магазину лакофарбових матеріалів «{SHOP_NAME}».
Магазин продає два бренди: TEKNOS (преміум, Фінляндія) і АУРА (бюджет/середній, Україна).

ТВОЯ ЗАДАЧА — провести клієнта від питання до покупки за чіткою схемою:

КРОК 1 — ЗНАЙОМСТВО (якщо ім'я не відоме):
Запитай ім'я: «Як вас звати?»

КРОК 2 — ВИЯВЛЕННЯ ПОТРЕБИ (задай 2-3 питання підряд):
- Що фарбуємо? (стіни, стеля, підлога, дерево, метал, фасад)
- Де? (всередині/зовні, волога кімната, сауна, вулиця)
- Яка площа орієнтовно?
- Поверхня нова чи раніше фарбована?

КРОК 3 — ПІДБІР (завжди давай 2 варіанти: економ і преміум):
- Порекомендуй конкретні товари з каталогу
- Порахуй скільки банок потрібно (витрати зазвичай 8-12 м²/л за 1 шар, 2 шари)
- Обов'язково додай: ґрунт + основна фарба + (якщо потрібно) розчинник
- Вкажи: Назва, Артикул, Об'єм, Ціна, Наявність

КРОК 4 — ЗАКРИТТЯ:
Після рекомендації ЗАВЖДИ питай:
«[Ім'я], хочете оформити замовлення або дізнатись більше про доставку?»
Якщо вагається — додай: «Ці товари є в наявності, можемо зарезервувати для вас»

КРОК 5 — ЗБІР КОНТАКТУ:
Якщо клієнт хоче замовити або зв'язатися — запитай:
«Залиште, будь ласка, ваш номер телефону — менеджер зв'яжеться протягом години»
Після отримання номера — постав тег [FORWARD_TO_MANAGER] і підтвердження клієнту.

ПРАВИЛА:
1. Спілкуйся на ТИ, тепло і по-людськи, але професійно
2. Відповідай коротко — максимум 4-5 речень + список товарів
3. НІКОЛИ не вигадуй товари яких немає в каталозі
4. Якщо питання поза каталогом — скажи «Передам менеджеру» і постав [FORWARD_TO_MANAGER]
5. Якщо клієнт питає «що краще» — порівняй АУРА (дешевше) vs ТЕКНОС (якісніше/довговічніше)
6. При розрахунку кількості: площа / 10 м²/л * 2 шари = літрів. Округли вгору до найближчої тари.
7. Якщо клієнт незадоволений або скаржиться — одразу [FORWARD_TO_MANAGER]

ФОРМАТ рекомендації:
🎨 [Назва] ([Бренд])
   Артикул: XXXXXX | [об'єм] | [ціна] грн | [наявність]
   [1 речення що це і навіщо]

АСОРТИМЕНТ МАГАЗИНУ:
{CATALOG_TEXT}
"""

# ── Conversation storage ──────────────────────────────────────────────────────
conversations: dict[int, list[dict]] = {}
client_profiles: dict[int, dict] = {}  # store name, phone, etc.

def get_history(chat_id: int) -> list[dict]:
    if chat_id not in conversations:
        conversations[chat_id] = []
    return conversations[chat_id]

def get_profile(chat_id: int) -> dict:
    if chat_id not in client_profiles:
        client_profiles[chat_id] = {"name": None, "phone": None, "interest": None}
    return client_profiles[chat_id]

def add_message(chat_id: int, role: str, content: str):
    history = get_history(chat_id)
    history.append({"role": role, "content": content})
    if len(history) > 30:
        conversations[chat_id] = history[-30:]

# ── OpenRouter ────────────────────────────────────────────────────────────────
async def ask_ai(chat_id: int, user_text: str) -> str:
    add_message(chat_id, "user", user_text)
    messages = get_history(chat_id)

    async with httpx.AsyncClient(timeout=60) as client:
        payload = json.dumps({
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                *messages
            ],
            "max_tokens": 1024,
            "temperature": 0.5,
        }, ensure_ascii=False).encode("utf-8")

        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "HTTP-Referer": "https://github.com/korchakv/malyarnyi-bot",
                "X-Title": "Malyarny Bot",
                "Content-Type": "application/json; charset=utf-8",
            },
            content=payload,
        )
        response.raise_for_status()
        data = response.json()

    reply = data["choices"][0]["message"]["content"].strip()
    add_message(chat_id, "assistant", reply)
    return reply

# ── Forward to admin ──────────────────────────────────────────────────────────
async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str, reason: str = "питання"):
    user    = update.effective_user
    profile = get_profile(update.effective_chat.id)
    username = f"@{user.username}" if user.username else f"ID:{user.id}"
    name     = profile.get("name") or f"{user.first_name or ''} {user.last_name or ''}".strip() or "Без імені"
    phone    = profile.get("phone") or "не вказано"
    time_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    history  = get_history(update.effective_chat.id)
    dialog   = "\n".join(
        f"{'Клієнт' if m['role']=='user' else 'Бот'}: {m['content'][:200]}"
        for m in history[-8:]
    )

    admin_msg = (
        f"НОВЕ ЗВЕРНЕННЯ - {reason.upper()}\n"
        f"Ім'я: {name}\n"
        f"Телефон: {phone}\n"
        f"Telegram: {username}\n"
        f"Час: {time_str}\n"
        f"Останнє повідомлення: {user_text[:300]}\n\n"
        f"Діалог:\n{dialog}"
    )

    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg)
    except Exception as e:
        logger.error(f"Failed to forward to admin: {e}")

# ── Handlers ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversations.pop(chat_id, None)
    client_profiles.pop(chat_id, None)

    keyboard = [
        [InlineKeyboardButton("🏠 Фарби для стін та стелі", callback_data="q_interior")],
        [InlineKeyboardButton("🏡 Фасадні фарби", callback_data="q_facade")],
        [InlineKeyboardButton("🌲 Покриття для дерева", callback_data="q_wood")],
        [InlineKeyboardButton("🔩 Антикорозійні покриття", callback_data="q_metal")],
        [InlineKeyboardButton("🧹 Ґрунтовки", callback_data="q_primer")],
        [InlineKeyboardButton("💬 Інше питання", callback_data="q_other")],
    ]
    await update.message.reply_text(
        f"Привіт! Я Маля — консультант магазину {SHOP_NAME} 🎨\n\n"
        "Допоможу підібрати фарбу чи покриття саме для вашого завдання.\n"
        "З чим сьогодні працюємо?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    texts = {
        "q_interior": "Хочу підібрати фарбу для стін або стелі всередині приміщення",
        "q_facade":   "Потрібна фарба для фасаду або зовнішніх робіт",
        "q_wood":     "Шукаю покриття, лак або антисептик для дерева",
        "q_metal":    "Потрібна фарба або ґрунт для металу, антикорозійний захист",
        "q_primer":   "Цікавлять ґрунтовки — адгезійні або звичайні",
        "q_other":    "Маю інше питання щодо лакофарбових матеріалів",
    }
    text = texts.get(query.data, query.data)
    await query.message.reply_text(f"Зрозуміло! {text}")
    await process_message(update, context, text, query.message.chat_id)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.effective_chat.id

    # Try to detect phone number
    import re
    phone_pattern = r'(\+?38)?[\s\-]?\(?0\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}'
    if re.search(phone_pattern, text):
        profile = get_profile(chat_id)
        profile["phone"] = text
        await forward_to_admin(update, context, text, reason="залишив контакт")
        await update.message.reply_text(
            "Дякую! Ваш номер передано менеджеру.\n"
            "Зателефонуємо протягом години в робочий час. "
            "Якщо є ще питання — я тут!"
        )
        return

    await process_message(update, context, text, chat_id)

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, chat_id: int):
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        reply = await ask_ai(chat_id, text)
    except Exception as e:
        logger.error(f"AI error: {e}")
        await forward_to_admin(update, context, text, reason="помилка AI")
        await context.bot.send_message(
            chat_id=chat_id,
            text="Вибачте, виникла технічна помилка. Ваше питання вже передано менеджеру — він зв'яжеться з вами найближчим часом!"
        )
        return

    needs_forward = "[FORWARD_TO_MANAGER]" in reply
    clean_reply   = reply.replace("[FORWARD_TO_MANAGER]", "").strip()

    # Split long messages (Telegram limit 4096)
    if len(clean_reply) > 4000:
        parts = [clean_reply[i:i+4000] for i in range(0, len(clean_reply), 4000)]
        for part in parts:
            await context.bot.send_message(chat_id=chat_id, text=part)
    else:
        await context.bot.send_message(chat_id=chat_id, text=clean_reply)

    if needs_forward:
        await forward_to_admin(update, context, text, reason="запит менеджеру")
        await context.bot.send_message(
            chat_id=chat_id,
            text="Ваше питання передано менеджеру. Зв'яжемося з вами протягом кількох годин!"
        )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversations.pop(chat_id, None)
    client_profiles.pop(chat_id, None)
    await update.message.reply_text("Розмову скинуто. Напишіть /start щоб почати заново.")

# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CallbackQueryHandler(handle_callback))
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
