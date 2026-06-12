import os
import asyncio
import threading
import time
from datetime import datetime
from flask import Flask, request
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.getenv("BOT_TOKEN")
OWNER_ID    = int(os.getenv("OWNER_ID", "0"))
VIP_LINK    = os.getenv("VIP_LINK", "https://t.me/+H3isrme8c3BiNDg1")
AFFILIATE   = "https://broker-qx.pro/sign-up/?lid=1504736"
MIN_DEPOSIT = 20

user_state: dict = {}

app = Flask(__name__)

# Global event loop for the telegram bot
bot_loop = asyncio.new_event_loop()

def get_state(chat_id: int) -> dict:
    if chat_id not in user_state:
        user_state[chat_id] = {
            "step": "start",
            "trader_id": None,
            "deposit": 0.0,
            "last_reminder": None,
            "first_reminder_sent": False,
        }
    return user_state[chat_id]

def register_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Register on Quotex", url=AFFILIATE)],
        [InlineKeyboardButton("✅ I Have Registered", callback_data="registered")],
    ])

def deposit_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Fund My Account ($20 min)", url=AFFILIATE)],
        [InlineKeyboardButton("✅ I Have Deposited", callback_data="deposited")],
    ])

def run_coro(coro):
    """Run a coroutine on the bot's event loop from any thread."""
    return asyncio.run_coroutine_threadsafe(coro, bot_loop).result(timeout=30)

async def notify_owner(text: str):
    try:
        bot = Bot(BOT_TOKEN)
        await bot.send_message(chat_id=OWNER_ID, text=text)
    except Exception as e:
        print("Owner notify error:", e)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = get_state(chat_id)
    state["step"] = "start"
    state["first_reminder_sent"] = False
    state["last_reminder"] = datetime.now()
    await update.message.reply_text(
        "👋 Welcome to *Quotex VIP Signals Bot!*\n\n"
        "I'll guide you step by step to join our exclusive *VIP Signals Group* 🚀\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "📋 *STEP 1 — Register*\n\n"
        "Click the button below to create your *FREE Quotex account* using our link.\n\n"
        "⚠️ You *MUST* use our link to get VIP access!",
        parse_mode="Markdown",
        reply_markup=register_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    state = get_state(chat_id)

    if query.data == "registered":
        state["step"] = "awaiting_id"
        await query.message.reply_text(
            "✅ *Great! You're registered!*\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "📋 *STEP 2 — Share your Trader ID*\n\n"
            "Please send me your *Quotex Trader ID*.\n\n"
            "👉 Find it in your Quotex dashboard (top-right corner).\n\n"
            "Just type and send your ID number 👇",
            parse_mode="Markdown"
        )

    elif query.data == "deposited":
        dep = state.get("deposit", 0.0)
        if dep >= MIN_DEPOSIT:
            await _grant_vip(query.message, state, chat_id)
        else:
            await query.message.reply_text(
                "⏳ *Checking your deposit...*\n\n"
                "Not confirmed yet on our system.\n\n"
                f"🔍 Account (*ID: {state['trader_id']}*) shows: *${dep:.2f}*\n\n"
                f"💡 Minimum required: *${MIN_DEPOSIT}*\n\n"
                "Please deposit and try again in a few minutes.",
                parse_mode="Markdown",
                reply_markup=deposit_keyboard()
            )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = get_state(chat_id)
    text = update.message.text.strip()

    if state["step"] == "awaiting_id":
        if not text.isdigit():
            await update.message.reply_text(
                "⚠️ Please send *only numbers* (e.g. `89057949`)",
                parse_mode="Markdown"
            )
            return
        state["trader_id"] = text
        state["step"] = "awaiting_deposit"
        state["last_reminder"] = datetime.now()
        state["first_reminder_sent"] = False
        await update.message.reply_text(
            f"🎯 *Trader ID `{text}` linked!*\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "📋 *STEP 3 — Fund Your Account*\n\n"
            f"💰 Deposit minimum *${MIN_DEPOSIT}* to unlock VIP access.\n\n"
            "Click below once deposited ✅",
            parse_mode="Markdown",
            reply_markup=deposit_keyboard()
        )
        await notify_owner(f"🆕 New Registration\n👤 ID: {text}\n💬 Chat: {chat_id}")
    else:
        await update.message.reply_text("👋 Use /start to begin or tap the buttons above.")

async def _grant_vip(message, state: dict, chat_id: int):
    state["step"] = "done"
    await message.reply_text(
        "🎉 *Deposit Confirmed! Welcome to VIP!*\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "✅ Your account has been verified.\n\n"
        f"🚀 Join the *Exclusive VIP Signals Group*:\n\n"
        f"👉 {VIP_LINK}\n\n"
        "Welcome to the winning team! 🏆",
        parse_mode="Markdown"
    )
    await notify_owner(f"✅ VIP Granted\n👤 ID: {state['trader_id']}\n💰 ${state['deposit']}\n💬 Chat: {chat_id}")

# ─── FLASK ROUTES ─────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return "✅ Quotex VIP Bot Running"

@app.route("/postback")
def postback():
    data    = request.args
    uid     = data.get("uid", "")
    status  = data.get("status", "")
    sumdep  = float(data.get("sumdep", 0))
    country = data.get("country", "N/A")

    msg = f"🔥 QUOTEX POSTBACK\n\n👤 ID: {uid}\n🌍 {country}\n📌 {status}\n💰 ${sumdep}"
    try:
        run_coro(notify_owner(msg))
    except Exception as e:
        print("Postback notify error:", e)

    for chat_id, state in user_state.items():
        if state.get("trader_id") == uid:
            state["deposit"] = sumdep
            if sumdep >= MIN_DEPOSIT and state["step"] != "done":
                async def send_vip(cid=chat_id, s=state):
                    bot = Bot(BOT_TOKEN)
                    await bot.send_message(
                        chat_id=cid,
                        text=(
                            f"🎉 *Deposit Confirmed! Welcome to VIP!*\n\n"
                            f"✅ Auto-verified!\n\n"
                            f"🚀 Join VIP now:\n👉 {VIP_LINK}\n\nWelcome! 🏆"
                        ),
                        parse_mode="Markdown"
                    )
                    s["step"] = "done"
                try:
                    run_coro(send_vip())
                except Exception as e:
                    print("VIP send error:", e)
            break

    return "OK"

# ─── REMINDER LOOP ────────────────────────────────────────────────────────────

async def send_reminders():
    bot = Bot(BOT_TOKEN)
    now = datetime.now()
    for chat_id, state in list(user_state.items()):
        if state["step"] not in ("awaiting_deposit", "awaiting_deposit_verify"):
            continue
        last    = state.get("last_reminder") or now
        elapsed = (now - last).total_seconds()

        if not state["first_reminder_sent"] and elapsed >= 1800:
            state["first_reminder_sent"] = True
            state["last_reminder"] = now
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"⚠️ *Don't miss out!*\n\n"
                        f"Account *ID: {state['trader_id']}* still shows $0.\n\n"
                        f"💰 Deposit *${MIN_DEPOSIT}* to unlock VIP! 🚀"
                    ),
                    parse_mode="Markdown",
                    reply_markup=deposit_keyboard()
                )
            except Exception as e:
                print(f"Reminder error {chat_id}:", e)

        elif state["first_reminder_sent"] and elapsed >= 10800:
            state["last_reminder"] = now
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🔔 *VIP Access Still Waiting!*\n\n"
                        f"Account *ID: {state['trader_id']}* not funded yet.\n\n"
                        f"💸 Just *${MIN_DEPOSIT}* and you're in! 📈"
                    ),
                    parse_mode="Markdown",
                    reply_markup=deposit_keyboard()
                )
            except Exception as e:
                print(f"Reminder error {chat_id}:", e)

def reminder_loop():
    while True:
        time.sleep(300)
        asyncio.run_coroutine_threadsafe(send_reminders(), bot_loop)

# ─── TELEGRAM BOT (runs on dedicated event loop) ──────────────────────────────

def run_telegram():
    asyncio.set_event_loop(bot_loop)

    tg_app = Application.builder().token(BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(CallbackQueryHandler(button_handler))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    bot_loop.run_until_complete(tg_app.initialize())
    bot_loop.run_until_complete(tg_app.start())
    bot_loop.run_until_complete(tg_app.updater.start_polling(drop_pending_updates=True))
    bot_loop.run_forever()

# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    threading.Thread(target=run_telegram, daemon=True).start()
    threading.Thread(target=reminder_loop, daemon=True).start()

    # Give telegram thread a moment to start
    time.sleep(2)

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
