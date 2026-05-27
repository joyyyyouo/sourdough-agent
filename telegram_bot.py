import asyncio
import datetime
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import infra.db as db_module
from assistant_names import generate_assistant_name
from config import DB_PATH, TELEGRAM_BOT_TOKEN
from service import BakingAgentService

_executor = ThreadPoolExecutor(max_workers=4)
_service = BakingAgentService()
_session_locks: dict[int, asyncio.Lock] = {}


def _split_message(text: str, max_len: int = 4000) -> list[str]:
    """Split text into chunks that each fit within Telegram's 4096-char message limit."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at <= 0:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _session_locks:
        _session_locks[chat_id] = asyncio.Lock()
    return _session_locks[chat_id]


async def _run_sync(fn, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, fn, *args)


def _get_or_create_session(chat_id: int) -> tuple[str, str, str]:
    """Return (session_key, thread_id, bot_name), creating a new session if needed."""
    session_key = str(chat_id)
    conn = db_module.init_db(DB_PATH)
    try:
        row = db_module.get_user_session(conn, session_key)
    finally:
        conn.close()

    if row and _service.checkpoint_exists(row["thread_id"]):
        return session_key, row["thread_id"], row["bot_name"]

    thread_id = str(uuid.uuid4())
    bot_name = generate_assistant_name()
    now = _now_iso()

    conn = db_module.init_db(DB_PATH)
    try:
        # ON CONFLICT must update thread_id too — db_module.upsert_user_session only
        # updates last_seen_at, which is wrong for the orphan-session reset case.
        conn.execute(
            """INSERT INTO user_sessions
               (session_key, thread_id, bot_name, created_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(session_key) DO UPDATE SET
                   thread_id    = excluded.thread_id,
                   bot_name     = excluded.bot_name,
                   created_at   = excluded.created_at,
                   last_seen_at = excluded.last_seen_at""",
            (session_key, thread_id, bot_name, now, now),
        )
        conn.commit()
    finally:
        conn.close()

    _service.seed(thread_id, {"session_key": session_key, "bot_name": bot_name})
    return session_key, thread_id, bot_name


def _reset_session(chat_id: int) -> tuple[str, str, str]:
    """Force a brand-new session regardless of existing state."""
    session_key = str(chat_id)
    thread_id = str(uuid.uuid4())
    bot_name = generate_assistant_name()
    now = _now_iso()

    conn = db_module.init_db(DB_PATH)
    try:
        conn.execute(
            """INSERT INTO user_sessions
               (session_key, thread_id, bot_name, created_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(session_key) DO UPDATE SET
                   thread_id       = excluded.thread_id,
                   bot_name        = excluded.bot_name,
                   bake_session_id = NULL,
                   bake_phase      = 'planning',
                   created_at      = excluded.created_at,
                   last_seen_at    = excluded.last_seen_at""",
            (session_key, thread_id, bot_name, now, now),
        )
        conn.commit()
    finally:
        conn.close()

    _service.seed(thread_id, {"session_key": session_key, "bot_name": bot_name})
    return session_key, thread_id, bot_name


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    async with _get_lock(chat_id):
        session_key, thread_id, bot_name = await _run_sync(_get_or_create_session, chat_id)

    state = await _run_sync(_service.get_state, thread_id)
    messages = state.get("messages", [])
    assistant_msgs = [m["content"] for m in messages if m.get("role") == "assistant"]

    if len(assistant_msgs) > 1:
        full = (
            f"Welcome back! Here's where we left off:\n\n{assistant_msgs[-1]}\n\n"
            "(Use /reset to start a fresh bake session.)"
        )
        for chunk in _split_message(full):
            await update.message.reply_text(chunk)
    elif assistant_msgs:
        for chunk in _split_message(assistant_msgs[0]):
            await update.message.reply_text(chunk)
    else:
        await update.message.reply_text("Hello! Ready to bake some sourdough?")


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    async with _get_lock(chat_id):
        session_key, thread_id, bot_name = await _run_sync(_reset_session, chat_id)

    state = await _run_sync(_service.get_state, thread_id)
    messages = state.get("messages", [])
    opening = next(
        (m["content"] for m in messages if m.get("role") == "assistant"),
        "Fresh start! Ready to bake?",
    )
    await update.message.reply_text(f"Starting a new bake session!\n\n{opening}")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Couch to Crust — Sourdough Baking Assistant\n\n"
        "Commands:\n"
        "/start — Resume your session (or start a new one)\n"
        "/reset — Start a completely fresh bake session\n"
        "/help  — Show this message\n\n"
        "Just send me a message to continue your bake planning!"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_text = (update.message.text or "").strip()
    if not user_text:
        return

    async with _get_lock(chat_id):
        session_key, thread_id, bot_name = await _run_sync(_get_or_create_session, chat_id)

    state = await _run_sync(_service.get_state, thread_id)
    if state.get("stage") == "complete":
        await update.message.reply_text(
            "Your bake session is complete! Use /reset to start a new bake session."
        )
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    def _process():
        result = _service.send_message(thread_id, user_text)
        now = _now_iso()
        conn = db_module.init_db(DB_PATH)
        try:
            db_module.upsert_user_session(conn, session_key, thread_id, bot_name, now, now)
        finally:
            conn.close()
        return result

    try:
        result = await _run_sync(_process)
    except Exception:
        logging.exception("Error processing message for chat_id=%s", chat_id)
        await update.message.reply_text(
            "Something went wrong while thinking. Please try again in a moment."
        )
        return

    for response in result.get("_responses") or []:
        for chunk in _split_message(response):
            await update.message.reply_text(chunk)


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add it to your .env file.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
