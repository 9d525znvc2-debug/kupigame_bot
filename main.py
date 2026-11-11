import asyncio
import aiosqlite
import os
from flask import Flask
from threading import Thread
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 8567564191))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
DB_NAME = "support.db"

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER (чтобы не брал деньги) ---
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is alive!"

def run_web_server():
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 8080)))

# --- КОНЕЦ ВЕБ-СЕРВЕРА ---

class SupportStates(StatesGroup):
    waiting_for_message = State()
    waiting_for_reply = State()

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER,
                sender TEXT,
                text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ticket_id) REFERENCES tickets (id)
            )
        """)
        await db.commit()

def get_main_keyboard(is_admin=False):
    builder = ReplyKeyboardBuilder()
    if is_admin:
        builder.button(text="📋 Все заявки")
    else:
        builder.button(text="✍️ Написать в поддержку")
        builder.button(text="📁 Мои заявки")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_admin_ticket_keyboard(ticket_id, status):
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Ответить", callback_data=f"reply_{ticket_id}")
    if status == 'open':
        builder.button(text="🔒 Закрыть заявку", callback_data=f"close_{ticket_id}")
    builder.button(text="🗑 Удалить из списка", callback_data=f"delete_{ticket_id}")
    builder.adjust(1)
    return builder.as_markup()

def get_user_ticket_keyboard(ticket_id, status):
    builder = InlineKeyboardBuilder()
    if status == 'open':
        builder.button(text="✍️ Дописать сообщение", callback_data=f"append_{ticket_id}")
    builder.adjust(1)
    return builder.as_markup()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("Привет, Админ! Твоя панель управления готова.", reply_markup=get_main_keyboard(True))
    else:
        await message.answer("Здравствуйте! Вы можете написать в поддержку или посмотреть свои заявки.", reply_markup=get_main_keyboard(False))

@dp.message(F.text == "📋 Все заявки", F.from_user.id == ADMIN_ID)
async def show_all_tickets(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, username, status, created_at FROM tickets ORDER BY id DESC") as cursor:
            tickets = await cursor.fetchall()
    
    if not tickets:
        await message.answer("Заявок пока нет.")
        return
    
    for t in tickets:
        t_id, username, status, created_at = t
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT text FROM messages WHERE ticket_id = ? AND sender = 'user' ORDER BY id DESC LIMIT 1", (t_id,)) as cursor:
                last_msg_row = await cursor.fetchone()
                last_msg = last_msg_row[0] if last_msg_row else "Нет текста"
        
        status_text = "🟢 Открыта" if status == 'open' else "🔴 Закрыта"
        text = f"Заявка #{t_id}\nОт: @{username}\nСтатус: {status_text}\nДата: {created_at}\n\n💬 Суть: {last_msg[:100]}..."
        await message.answer(text, reply_markup=get_admin_ticket_keyboard(t_id, status))

@dp.callback_query(F.data.startswith("close_"), F.from_user.id == ADMIN_ID)
async def close_ticket(callback: types.CallbackQuery):
    ticket_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tickets SET status = 'closed' WHERE id = ?", (ticket_id,))
        await db.commit()
    
    await callback.message.edit_text(callback.message.text + "\n\n✅ Заявка закрыта.")
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM tickets WHERE id = ?", (ticket_id,)) as cursor:
            user_id = (await cursor.fetchone())[0]
    
    await bot.send_message(user_id, f"Ваша заявка #{ticket_id} была закрыта. Спасибо за обращение!")

@dp.callback_query(F.data.startswith("delete_"), F.from_user.id == ADMIN_ID)
async def delete_ticket(callback: types.CallbackQuery):
    ticket_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM messages WHERE ticket_id = ?", (ticket_id,))
        await db.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
        await db.commit()
    
    await callback.message.delete()
    await callback.answer("Заявка удалена из вашего списка.")

@dp.callback_query(F.data.startswith("reply_"), F.from_user.id == ADMIN_ID)
async def admin_reply_start(callback: types.CallbackQuery, state: FSMContext):
    ticket_id = int(callback.data.split("_")[1])
    await state.update_data(ticket_id=ticket_id)
    await state.set_state(SupportStates.waiting_for_reply)
    await callback.message.answer(f"Введите ваш ответ для заявки #{ticket_id}:")
    await callback.answer()

@dp.message(SupportStates.waiting_for_reply, F.from_user.id == ADMIN_ID)
async def admin_send_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data['ticket_id']
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO messages (ticket_id, sender, text) VALUES (?, ?, ?)", (ticket_id, 'admin', message.text))
        await db.commit()
        
        async with db.execute("SELECT user_id FROM tickets WHERE id = ?", (ticket_id,)) as cursor:
            user_id = (await cursor.fetchone())[0]
    
    await bot.send_message(user_id, f"📩 Ответ от поддержки по заявке #{ticket_id}:\n\n{message.text}")
    await message.answer("✅ Ответ отправлен.")
    await state.clear()

@dp.message(F.text == "✍️ Написать в поддержку", ~F.from_user.id == ADMIN_ID)
async def user_new_ticket(message: types.Message, state: FSMContext):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id FROM tickets WHERE user_id = ? AND status = 'open'", (message.from_user.id,)) as cursor:
            open_ticket = await cursor.fetchone()
    
    if open_ticket:
        await message.answer(f"У вас уже есть открытая заявка #{open_ticket[0]}. Вы можете дописать в нее через «Мои заявки».")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("INSERT INTO tickets (user_id, username) VALUES (?, ?)", 
                                  (message.from_user.id, message.from_user.username or message.from_user.first_name))
        ticket_id = cursor.lastrowid
        await db.execute("INSERT INTO messages (ticket_id, sender, text) VALUES (?, ?, ?)", (ticket_id, 'user', "Заявка создана"))
        await db.commit()
    
    await state.update_data(ticket_id=ticket_id)
    await state.set_state(SupportStates.waiting_for_message)
    await message.answer(f"Заявка #{ticket_id} создана! Напишите ваш вопрос одним сообщением:")

@dp.message(F.text == "📁 Мои заявки", ~F.from_user.id == ADMIN_ID)
async def user_show_tickets(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, status FROM tickets WHERE user_id = ? ORDER BY id DESC", (message.from_user.id,)) as cursor:
            tickets = await cursor.fetchall()
    
    if not tickets:
        await message.answer("У вас нет заявок.")
        return
    
    for t_id, status in tickets:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT text FROM messages WHERE ticket_id = ? AND sender = 'admin' ORDER BY id DESC LIMIT 1", (t_id,)) as cursor:
                last_reply_row = await cursor.fetchone()
                last_reply = last_reply_row[0] if last_reply_row else "Ожидайте ответа"
        
        status_text = "🟢 Открыта" if status == 'open' else "🔴 Закрыта"
        text = f"Заявка #{t_id}\nСтатус: {status_text}\n\n💬 Последний ответ: {last_reply[:100]}..."
        await message.answer(text, reply_markup=get_user_ticket_keyboard(t_id, status))

@dp.callback_query(F.data.startswith("append_"), ~F.from_user.id == ADMIN_ID)
async def user_append(callback: types.CallbackQuery, state: FSMContext):
    ticket_id = int(callback.data.split("_")[1])
    await state.update_data(ticket_id=ticket_id)
    await state.set_state(SupportStates.waiting_for_message)
    await callback.message.answer(f"Напишите сообщение для заявки #{ticket_id}:")
    await callback.answer()

@dp.message(SupportStates.waiting_for_message, ~F.from_user.id == ADMIN_ID)
async def user_send_message(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data['ticket_id']
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO messages (ticket_id, sender, text) VALUES (?, ?, ?)", (ticket_id, 'user', message.text))
        await db.commit()
        
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT username FROM tickets WHERE id = ?", (ticket_id,)) as cursor:
                username = (await cursor.fetchone())[0]
    
    await bot.send_message(ADMIN_ID, f"📩 Новое сообщение по заявке #{ticket_id} от @{username}:\n\n{message.text}")
    await message.answer("✅ Ваше сообщение отправлено в поддержку.")
    await state.clear()

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Запускаем веб-сервер в отдельном потоке
    t = Thread(target=run_web_server)
    t.start()
    
    # Запускаем бота
    asyncio.run(main())