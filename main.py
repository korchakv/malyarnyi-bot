import traceback

try:
    import os
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
        )
    
        result = response.json()
    
        try:
            return result["choices"][0]["message"]["content"]
        except:
            return "Помилка AI. Спробуйте пізніше."
    
    
    @dp.message(CommandStart())
    async def start(message: Message):
    
        text = '''
    🎨 Вітаємо у магазині Малярний!
    
    Професійні фарби та декоративні матеріали.
    
    ✔ Teknos
    ✔ Aura
    ✔ Eskaro
    
    👇 Оберіть що вас цікавить
    '''
    
        await message.answer(text, reply_markup=main_keyboard)
    
    
    @dp.message(F.text == "📍 Контакти")
    async def contacts(message: Message):
    
        text = '''
    📍 Івано-Франківськ
    вул. Вовчинецька 191
    
    📞 063 770 24 57
    📞 068 770 24 57
    '''
    
        await message.answer(text)
    
    
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
    
    
    @dp.message()
    async def chat(message: Message):
    
        user_text = message.text
    
        if any(char.isdigit() for char in user_text):
    
            await bot.send_message(
                ADMIN_CHAT_ID,
                f"📞 Новий номер телефону:
    {user_text}"
            )
    
        answer = ai_answer(user_text)
    
        await message.answer(answer)
    
    
    if __name__ == "__main__":
        dp.run_polling(bot)
        except Exception as e:
        print("ERROR:")
        traceback.print_exc()
