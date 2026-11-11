ВСТАВЬТЕ СЮДА ВАШ ТОКЕН ИЗ BOTFATHER (вместе с кавычками)
BOT_TOKEN = "9242516981:AAGLMbUIijikVPxOq9qFLWPeGZ-jscgGWcI"
ВАШ ID
ADMIN_ID = 8567564191
bot = Bot(token=BOT_TOKEN) dp = Dispatcher() user_map = {}
@dp.message(Command("start")) async def start(message: types.Message): await message.answer("Здравствуйте! Напишите ваш вопрос, и мы ответим вам.")
@dp.message(lambda message: message.from_user.id != ADMIN_ID) async def handle_user_message(message: types.Message): forwarded = await bot.forward_message( chat_id=ADMIN_ID, from_chat_id=message.chat.id, message_id=message.message_id ) user_map[forwarded.message_id] = message.from_user.id await message.answer("Ваше сообщение отправлено в поддержку. Ожидайте ответа.")
@dp.message(lambda message: message.from_user.id == ADMIN_ID) async def handle_admin_reply(message: types.Message): if message.reply_to_message: original_msg_id = message.reply_to_message.message_id user_id = user_map.get(original_msg_id) if user_id: await bot.send_message(chat_id=user_id, text=message.text) await message.answer("Ответ отправлен пользователю.") else: await message.answer("Не удалось найти пользователя для этого сообщения.") else: await message.answer("Пожалуйста, используйте функцию «Ответить» на сообщение пользователя.")
async def main(): await dp.start_polling(bot)
if name == "main": asyncio.run(main())
