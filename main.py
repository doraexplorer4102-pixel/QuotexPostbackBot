import os
import asyncio
import threading
import time
from datetime import datetime, timedelta
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
MIN_DEPOSIT = 20   # USD

# ─── STATE ────────────────────────────────────────────────────────────────────
# user_state[chat_id] = {
#   "step": "start" | "awaiting_id" | "awaiting_deposit" | "done",
#   "trader_id": str,
#   "deposit": float,
#   "last_reminder": datetime,
#   "first_reminder_sent": bool
# }
user_state: dict[int, dict] = {}

app = Flask(__name__)

# ─── TELEGRAM APPLICATION ─────────────────────────────────────────────────────
tg_app = Application.builder().token(BOT_TOKEN).build()

# ─── HELPERS ──────────────────────────────────────────────────────────────────

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


# ─── HANDLERS ─────────────────────────────────────────────────────────────────

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
            "👉 You can find it in your Quotex account dashboard (top-right corner).\n\n"
            "Just type and send your ID number 👇",
            parse_mode="Markdown"
        )

    elif query.data == "deposited":
        state["step"] = "awaiting_deposit_verify"
        dep = state.get("deposit", 0.0)

        if dep >= MIN_DEPOSIT:
            await _grant_vip(query.message, state, chat_id)
        else:
            await query.message.reply_text(
                "⏳ *Checking your deposit...*\n\n"
                "Your deposit has not been confirmed yet on our system.\n\n"
                f"🔍 Your account (*ID: {state['trader_id']}*) currently shows: *${dep:.2f}*\n\n"
                f"💡 Minimum required: *${MIN_DEPOSIT}*\n\n"
                "Please make sure you deposited using our link and try again in a few minutes.",
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
                "⚠️ That doesn't look like a valid Trader ID.\n"
                "Please send *only the numbers* (e.g. `89057949`)",
                parse_mode="Markdown"
            )
            return

        state["trader_id"] = text
        state["step"] = "awaiting_deposit"
        state["last_reminder"] = datetime.now()
        state["first_reminder_sent"] = False

        await update.message.reply_text(
            f"🎯 *Trader ID `{text}` linked successfully!*\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "📋 *STEP 3 — Fund Your Account*\n\n"
            f"💰 Make a minimum deposit of *${MIN_DEPOSIT}* to unlock the VIP Signals Group.\n\n"
            "Once deposited, click the button below and I'll verify it instantly! ✅",
            parse_mode="Markdown",
            reply_markup=deposit_keyboard()
        )

        # Notify owner
        await _notify_owner(context, f"🆕 New Registration\n👤 ID: {text}\n💬 Chat: {chat_id}")

    else:
        # Catch-all for unexpected messages
        await update.message.reply_text(
            "👋 Use /start to begin or tap the buttons above.",
        )


async def _grant_vip(message, state: dict, chat_id: int):
    state["step"] = "done"
    await message.reply_text(
        "🎉 *Deposit Confirmed! Welcome to VIP!*\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "✅ Your account has been verified.\n\n"
        "🚀 Click below to join the *Exclusive VIP Signals Group*:\n\n"
        f"👉 {VIP_LINK}\n\n"
        "💡 *Tips for success:*\n"
        "• Follow every signal carefully\n"
        "• Never invest more than you can afford\n"
        "• Stay active in the group for live updates\n\n"
        "Welcome to the winning team! 🏆",
        parse_mode="Markdown"
    )
    await _notify_owner_raw(f"✅ VIP Granted\n👤 ID: {state['trader_id']}\n💰 Deposit: ${state['deposit']}\n💬 Chat: {chat_id}")


async def _notify_owner(context: ContextTypes.DEFAULT_TYPE, text: str):
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=text)
    except Exception as e:
        print("Owner notify error:", e)


async def _notify_owner_raw(text: str):
    try:
        bot = Bot(BOT_TOKEN)
        await bot.send_message(chat_id=OWNER_ID, text=text)
    except Exception as e:
        print("Owner notify error:", e)


# ─── FLASK ROUTES ─────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return "✅ Quotex VIP Bot Running"


@app.route("/postback")
def postback():
    """Quotex calls this URL when a user registers or deposits."""
    data = request.args

    uid       = data.get("uid", "")
    status    = data.get("status", "")
    sumdep    = float(data.get("sumdep", 0))
    country   = data.get("country", "N/A")

    # Notify owner about the postback
    msg = (
        "🔥 *QUOTEX POSTBACK*\n\n"
        f"👤 Trader ID: `{uid}`\n"
        f"🌍 Country: {country}\n"
        f"📌 Status: {status}\n"
        f"💰 Deposit: ${sumdep}\n"
    )
    asyncio.run(_notify_owner_raw(msg))

    # Update deposit in state for matching trader IDs
    for chat_id, state in user_state.items():
        if state.get("trader_id") == uid:
            state["deposit"] = sumdep

            # Auto-grant VIP if deposit threshold met
            if sumdep >= MIN_DEPOSIT and state["step"] != "done":
                async def send_vip():
                    bot = Bot(BOT_TOKEN)
                    await bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "🎉 *Deposit Confirmed! Welcome to VIP!*\n\n"
                            "━━━━━━━━━━━━━━━━━━━\n"
                            "✅ We received your deposit automatically!\n\n"
                            f"🚀 Join the *Exclusive VIP Signals Group* now:\n\n"
                            f"👉 {VIP_LINK}\n\n"
                            "Welcome to the winning team! 🏆"
                        ),
                        parse_mode="Markdown"
                    )
                    state["step"] = "done"
                asyncio.run(send_vip())
            break

    return "OK"


# ─── REMINDER LOOP ────────────────────────────────────────────────────────────

def reminder_loop():
    """Background thread — checks every 5 min who needs a nudge."""
    async def send_reminders():
        bot = Bot(BOT_TOKEN)
        now = datetime.now()
        for chat_id, state in list(user_state.items()):
            if state["step"] not in ("awaiting_deposit", "awaiting_deposit_verify"):
                continue

            last = state.get("last_reminder") or now
            elapsed = (now - last).total_seconds()

            # First reminder: after 30 minutes
            if not state["first_reminder_sent"] and elapsed >= 1800:
                state["first_reminder_sent"] = True
                state["last_reminder"] = now
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "⚠️ *Hey! Don't miss out!*\n\n"
                            f"Your Quotex account (*ID: {state['trader_id']}*) still shows *$0* deposit.\n\n"
                            f"💰 Deposit just *${MIN_DEPOSIT}* to unlock our VIP Signals Group!\n\n"
                            "Our members are making profits right now. Don't get left behind 🚀"
                        ),
                        parse_mode="Markdown",
                        reply_markup=deposit_keyboard()
                    )
                except Exception as e:
                    print(f"Reminder error {chat_id}:", e)

            # Repeat reminders: every 3 hours after first one sent
            elif state["first_reminder_sent"] and elapsed >= 10800:
                state["last_reminder"] = now
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "🔔 *Reminder — VIP Access Waiting!*\n\n"
                            f"Your account (*ID: {state['trader_id']}*) still hasn't been funded.\n\n"
                            f"💸 Just *${MIN_DEPOSIT} minimum* and you're in the VIP group!\n\n"
                            "Our signals are live. Join now before you miss today's trades! 📈"
                        ),
                        parse_mode="Markdown",
                        reply_markup=deposit_keyboard()
                    )
                except Exception as e:
                    print(f"Reminder error {chat_id}:", e)

    while True:
        time.sleep(300)  # check every 5 minutes
        try:
            asyncio.run(send_reminders())
        except Exception as e:
            print("Reminder loop error:", e)


# ─── TELEGRAM POLLING (background thread) ─────────────────────────────────────

def run_telegram():
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(CallbackQueryHandler(button_handler))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    tg_app.run_polling(drop_pending_updates=True)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Start reminder thread
    threading.Thread(target=reminder_loop, daemon=True).start()

    # Start Telegram bot in background thread
    threading.Thread(target=run_telegram, daemon=True).start()

    # Start Flask
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )
