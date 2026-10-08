import asyncio
import logging
import os
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiohttp import web

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add it in Environment Variables.")

ADMIN_ID = 1528769580
DATABASE_PATH = os.getenv("MESSAGE_DB", "message_history.sqlite3")
WELCOME_TEXT = "Хаии!! отправь сюда что угодно и камни ответит как только сможет!💗"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# --- Веб-сервер для поддержки активности Render ---
async def handle_ping(request):
    return web.Response(text="Bot is running!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()


# --- База данных ---
def init_db() -> None:
    with sqlite3.connect(DATABASE_PATH) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS message_history (
                admin_message_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS welcomed_users (
                user_id INTEGER PRIMARY KEY,
                welcomed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def register_first_start(user_id: int) -> bool:
    with sqlite3.connect(DATABASE_PATH) as db:
        cursor = db.execute(
            "INSERT OR IGNORE INTO welcomed_users (user_id) VALUES (?)",
            (user_id,),
        )
    return cursor.rowcount == 1


def save_message_mapping(admin_message_id: int, user_id: int) -> None:
    with sqlite3.connect(DATABASE_PATH) as db:
        db.execute(
            """
            INSERT OR REPLACE INTO message_history (admin_message_id, user_id)
            VALUES (?, ?)
            """,
            (admin_message_id, user_id),
        )


def get_user_id(admin_message_id: int) -> int | None:
    with sqlite3.connect(DATABASE_PATH) as db:
        row = db.execute(
            "SELECT user_id FROM message_history WHERE admin_message_id = ?",
            (admin_message_id,),
        ).fetchone()
    return row[0] if row else None


# --- Обработка команд и сообщений ---
@dp.message(CommandStart(), F.chat.type == "private")
async def start_cmd(message: Message) -> None:
    if message.from_user is None:
        return

    is_admin = message.from_user.id == ADMIN_ID
    is_first_start = register_first_start(message.from_user.id)

    if is_first_start:
        await message.answer(WELCOME_TEXT)

    if is_admin:
        await message.answer("Бот запущен. Чтобы ответить анониму, ответьте через Reply на его сообщение.")
    elif not is_first_start:
        await message.answer(WELCOME_TEXT)


@dp.message(F.chat.type == "private")
async def handle_message(message: Message) -> None:
    if message.from_user is None:
        return

    if message.from_user.id == ADMIN_ID:
        if message.reply_to_message is None:
            await message.answer("Чтобы ответить анониму, сделайте Reply на его сообщение.")
            return

        user_id = get_user_id(message.reply_to_message.message_id)
        if user_id is None:
            await message.answer("Не удалось найти отправителя этого сообщения. Возможно, оно было получено до запуска этой версии бота.")
            return

        try:
            await message.copy_to(chat_id=user_id)
        except TelegramAPIError:
            logging.exception("Не удалось отправить ответ пользователю")
            await message.answer("❌ Не удалось отправить ответ. Возможно, пользователь заблокировал бота.")
        return

    try:
        copied = await message.copy_to(chat_id=ADMIN_ID)
        save_message_mapping(copied.message_id, message.from_user.id)
        await message.answer("Сообщение доставлено! 🤍")
    except TelegramAPIError:
        logging.exception("Не удалось доставить сообщение администратору")
        await message.answer("❌ Не удалось доставить сообщение. Попробуй позже.")
    except sqlite3.Error:
        logging.exception("Не удалось сохранить связь сообщения с отправителем")
        await message.answer("❌ Сообщение не удалось зарегистрировать для анонимного ответа.")


async def main() -> None:
    init_db()
    await start_web_server()
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
