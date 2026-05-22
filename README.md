# 🎨 Малярний Bot — Telegram консультант TEKNOS

Telegram-бот консультант для магазину лакофарбових матеріалів.  
Підбирає товари з каталогу TEKNOS, відповідає на питання, пересилає складні запити менеджеру.

---

## 📁 Структура проекту

```
malyarny_bot/
├── bot.py           # Основний код бота
├── products.json    # Каталог товарів (409 позицій)
├── requirements.txt
├── render.yaml      # Конфіг для Render.com
└── README.md
```

---

## 🚀 Деплой на Render.com (покрокова інструкція)

### 1. Підготовка GitHub репозиторію

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO

# Скопіюй файли бота в репозиторій
cp -r malyarny_bot/* .

git add .
git commit -m "Add Malyarny bot"
git push
```

### 2. Отримай свій Telegram ID (ADMIN_CHAT_ID)

Напиши боту [@userinfobot](https://t.me/userinfobot) — він відправить твій ID (число).

### 3. Налаштуй Environment Variables на Render

В Dashboard → твій сервіс → **Environment**:

| Змінна | Значення |
|--------|----------|
| `TELEGRAM_TOKEN` | Токен від [@BotFather](https://t.me/BotFather) |
| `OPENROUTER_KEY` | API ключ з [openrouter.ai](https://openrouter.ai/keys) |
| `ADMIN_CHAT_ID` | Твій Telegram ID (число) |
| `WEBHOOK_URL` | URL твого сервісу на Render, напр. `https://malyarny-bot.onrender.com` |
| `OPENROUTER_MODEL` | `anthropic/claude-3.5-sonnet` (або інша) |

### 4. Перевір що бот живий

Відкрий Render Logs — маєш побачити:
```
Starting webhook on port 10000
```

Напиши боту `/start` — він відповість меню.

---

## 🔄 Оновлення каталогу товарів

Якщо прайс-лист змінився — перегенеруй `products.json`:

```bash
python generate_products.py  # або вручну відредагуй JSON
git add products.json
git commit -m "Update catalog"
git push
```
Render автоматично перезапустить бота.

---

## 💬 Команди бота

| Команда | Дія |
|---------|-----|
| `/start` | Привітання + меню категорій |
| `/reset` | Скинути діалог (почати з початку) |

---

## ⚙️ Як працює бот

1. Клієнт описує завдання або обирає категорію
2. AI аналізує запит і шукає відповідні товари в каталозі (409 позицій)
3. Пропонує 1-3 товари з артикулом і ціною
4. Якщо питання поза каталогом — пересилає повідомлення менеджеру в Telegram

---

## 🛠 Локальний запуск (для тесту)

```bash
pip install -r requirements.txt

export TELEGRAM_TOKEN="your_token"
export OPENROUTER_KEY="your_key"
export ADMIN_CHAT_ID="your_id"
# WEBHOOK_URL не треба — буде polling

python bot.py
```
