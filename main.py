import os
import asyncio
import threading
import time
from datetime import datetime
from flask import Flask, request, Response
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import psycopg2
from psycopg2.extras import RealDictCursor

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN    = os.getenv("BOT_TOKEN")
OWNER_ID     = int(os.getenv("OWNER_ID", "0"))
VIP_LINK     = os.getenv("VIP_LINK", "https://t.me/+H3isrme8c3BiNDg1")
AFFILIATE    = "https://broker-qx.pro/sign-up/?lid=1504736"
WEBHOOK_URL  = os.getenv("WEBHOOK_URL", "")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:DEfYBWltENxssYQNpworlKPeKVSKUuyQ@acela.proxy.rlwy.net:19828/railway")
MIN_DEPOSIT  = 20

user_state: dict = {}
app = Flask(__name__)
tg_app: Application = None
loop = asyncio.new_event_loop()

# ─── DATABASE ─────────────────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """Create tables if they don't exist."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS verified_traders (
                    uid TEXT PRIMARY KEY,
                    deposit FLOAT DEFAULT 0.0,
                    status TEXT DEFAULT '',
                    country TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            conn.commit()
    print("✅ Database initialized")

def db_save_trader(uid: str, deposit: float = 0.0, status: str = "", country: str = ""):
    """Save or update a trader ID in the database."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO verified_traders (uid, deposit, status, country, updated_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (uid) DO UPDATE SET
                        deposit = GREATEST(verified_traders.deposit, EXCLUDED.deposit),
                        status = EXCLUDED.status,
                        updated_at = NOW()
                """, (uid, deposit, status, country))
                conn.commit()
    except Exception as e:
        print(f"DB save error: {e}")

def db_get_trader(uid: str):
    """Get trader by UID. Returns dict or None."""
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM verified_traders WHERE uid = %s", (uid,))
                return cur.fetchone()
    except Exception as e:
        print(f"DB get error: {e}")
        return None

def db_trader_exists(uid: str) -> bool:
    return db_get_trader(uid) is not None

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def run_async(coro):
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=30)

def get_state(chat_id):
    if chat_id not in user_state:
        user_state[chat_id] = {
            "step": "start", "trader_id": None,
            "deposit": 0.0, "last_reminder": None,
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

def reject_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Register with Our Link", url=AFFILIATE)],
        [InlineKeyboardButton("🔄 Try Again", callback_data="registered")],
    ])

async def notify_owner(text):
    try:
        await Bot(BOT_TOKEN).send_message(chat_id=OWNER_ID, text=text)
    except Exception as e:
        print("Owner notify error:", e)

async def grant_vip(message, state, chat_id):
    state["step"] = "done"
    await message.reply_text(
        "🎉 *Deposit Confirmed! Welcome to VIP!*\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 Join our *Exclusive VIP Signals Group*:\n\n"
        f"👉 {VIP_LINK}\n\nWelcome to the winning team! 🏆",
        parse_mode="Markdown"
    )
    await notify_owner(f"✅ VIP Granted\n👤 ID: {state['trader_id']}\n💰 ${state['deposit']}\n💬 Chat: {chat_id}")

# ─── ID VERIFICATION ──────────────────────────────────────────────────────────

async def verify_id_then_respond(uid: str, chat_id: int):
    state = get_state(chat_id)
    bot = Bot(BOT_TOKEN)

    # Show checking message
    msg = await bot.send_message(
        chat_id=chat_id,
        text=f"🔍 *Verifying ID* `{uid}`*...*\n\nChecking with Quotex...",
        parse_mode="Markdown"
    )

    # Check DB immediately first
    trader = db_get_trader(uid)

    # If not found, wait up to 30 seconds for postback
    if not trader:
        for _ in range(10):
            await asyncio.sleep(3)
            trader = db_get_trader(uid)
            if trader:
                break

    if not trader:
        # Not found in DB = not from your affiliate link
        state["step"] = "start"
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg.message_id,
            text=(
                "❌ *ID Not Verified!*\n\n"
                f"Trader ID `{uid}` was *not registered through our link*.\n\n"
                "To get VIP access, you must sign up using our link.\n\n"
                "👇 Register below and come back with your new ID:"
            ),
            parse_mode="Markdown",
            reply_markup=reject_keyboard()
        )
        await notify_owner(f"❌ Unverified ID attempt\n👤 ID: {uid}\n💬 Chat: {chat_id}")
        return

    # ✅ ID verified!
    dep = trader["deposit"] or 0.0
    state["trader_id"] = uid
    state["deposit"] = dep
    state["last_reminder"] = datetime.now()
    state["first_reminder_sent"] = False

    if dep >= MIN_DEPOSIT:
        state["step"] = "done"
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg.message_id,
            text=f"✅ *ID `{uid}` verified!*\n\nDeposit already confirmed! Granting VIP... 🚀",
            parse_mode="Markdown"
        )
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "🎉 *Welcome to VIP!*\n\n"
                f"🚀 Join our *Exclusive VIP Signals Group*:\n\n"
                f"👉 {VIP_LINK}\n\nWelcome to the winning team! 🏆"
            ),
            parse_mode="Markdown"
        )
        await notify_owner(f"✅ VIP Granted\n👤 ID: {uid}\n💰 ${dep}\n💬 Chat: {chat_id}")
    else:
        state["step"] = "awaiting_deposit"
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg.message_id,
            text=(
                f"✅ *ID `{uid}` verified!*\n\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                "📋 *STEP 3 — Fund Your Account*\n\n"
                f"💰 Deposit minimum *${MIN_DEPOSIT}* to unlock VIP.\n\n"
                "Click below once deposited ✅"
            ),
            parse_mode="Markdown",
            reply_markup=deposit_keyboard()
        )
        await notify_owner(f"🆕 Verified User\n👤 ID: {uid}\n💬 Chat: {chat_id}")

# ─── BOT HANDLERS ─────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = get_state(chat_id)
    state.update({"step": "start", "first_reminder_sent": False, "last_reminder": datetime.now()})
    await update.message.reply_text(
        "👋 Welcome to *Quotex VIP Signals Bot!*\n\n"
        "I'll guide you step by step to join our *VIP Signals Group* 🚀\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "📋 *STEP 1 — Register*\n\n"
        "Click below to create your *FREE Quotex account* using our link.\n\n"
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
        uid = state.get("trader_id")
        trader = db_get_trader(uid)
        dep = trader["deposit"] if trader else 0.0
        state["deposit"] = dep
        if dep >= MIN_DEPOSIT:
            await grant_vip(query.message, state, chat_id)
        else:
            await query.message.reply_text(
                "⏳ *Deposit Not Confirmed Yet*\n\n"
                f"Account (*ID: {uid}*) shows: *${dep:.2f}*\n\n"
                f"Minimum: *${MIN_DEPOSIT}*\n\n"
                "Deposit at least $20 and try again in a minute.",
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
        state["step"] = "checking"
        asyncio.run_coroutine_threadsafe(
            verify_id_then_respond(text, chat_id), loop
        )
    else:
        await update.message.reply_text("👋 Use /start to begin or tap a button above.")

# ─── FLASK ROUTES ─────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return "✅ Quotex VIP Bot Running"

@app.route("/webhook/<token>", methods=["POST"])
def webhook(token):
    if token != BOT_TOKEN:
        return Response("Forbidden", status=403)
    json_data = request.get_json(force=True)
    update = Update.de_json(json_data, tg_app.bot)
    run_async(tg_app.process_update(update))
    return Response("OK", status=200)

@app.route("/postback")
def postback():
    data    = request.args
    uid     = data.get("uid", "").strip()
    status  = data.get("status", "")
    sumdep  = float(data.get("sumdep", 0))
    country = data.get("country", "N/A")

    if not uid or uid in ("{trader_id}", "{uid}"):
        return "OK"

    # Save to DB permanently
    db_save_trader(uid, sumdep, status, country)

    msg = f"🔥 QUOTEX POSTBACK\n\n👤 ID: {uid}\n🌍 {country}\n📌 {status}\n💰 ${sumdep}"
    try:
        run_async(notify_owner(msg))
    except Exception as e:
        print("Postback notify error:", e)

    # Auto-send VIP if deposit confirmed
    if sumdep >= MIN_DEPOSIT:
        for chat_id, state in user_state.items():
            if state.get("trader_id") == uid and state["step"] != "done":
                state["deposit"] = sumdep
                state["step"] = "done"
                async def send_vip(cid=chat_id):
                    await Bot(BOT_TOKEN).send_message(
                        chat_id=cid,
                        text=(
                            "🎉 *Deposit Confirmed! Welcome to VIP!*\n\n"
                            "✅ Deposit received!\n\n"
                            f"🚀 Join VIP:\n👉 {VIP_LINK}\n\nWelcome! 🏆"
                        ),
                        parse_mode="Markdown"
                    )
                try:
                    run_async(send_vip())
                except Exception as e:
                    print("VIP send error:", e)
                break

    return "OK"

# ─── ADMIN: manually add an old ID ───────────────────────────────────────────

@app.route("/addid")
def add_id():
    """Secret route to manually add old IDs. 
    Usage: /addid?uid=12345678&key=ADMIN_SECRET"""
    key = request.args.get("key", "")
    uid = request.args.get("uid", "").strip()
    if key != os.getenv("ADMIN_KEY", "quotexadmin2024"):
        return Response("Forbidden", status=403)
    if not uid:
        return "No uid provided"
    db_save_trader(uid, 0.0, "manual", "")
    return f"✅ ID {uid} added successfully"

# ─── REMINDERS ────────────────────────────────────────────────────────────────

async def send_reminders():
    bot = Bot(BOT_TOKEN)
    now = datetime.now()
    for chat_id, state in list(user_state.items()):
        if state["step"] != "awaiting_deposit":
            continue
        last = state.get("last_reminder") or now
        elapsed = (now - last).total_seconds()
        try:
            if not state["first_reminder_sent"] and elapsed >= 1800:
                state["first_reminder_sent"] = True
                state["last_reminder"] = now
                await bot.send_message(
                    chat_id=chat_id,
                    text=(f"⚠️ *Don't miss out!*\n\n"
                          f"ID *{state['trader_id']}* — deposit *${MIN_DEPOSIT}* to unlock VIP! 🚀"),
                    parse_mode="Markdown", reply_markup=deposit_keyboard()
                )
            elif state["first_reminder_sent"] and elapsed >= 10800:
                state["last_reminder"] = now
                await bot.send_message(
                    chat_id=chat_id,
                    text=(f"🔔 *Still waiting!*\n\n"
                          f"ID *{state['trader_id']}* — just *${MIN_DEPOSIT}* and you're in VIP! 📈"),
                    parse_mode="Markdown", reply_markup=deposit_keyboard()
                )
        except Exception as e:
            print(f"Reminder error {chat_id}:", e)

def reminder_loop():
    while True:
        time.sleep(300)
        try:
            run_async(send_reminders())
        except Exception as e:
            print("Reminder loop error:", e)

def start_loop():
    asyncio.set_event_loop(loop)
    loop.run_forever()

async def setup_bot():
    global tg_app
    tg_app = Application.builder().token(BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(CallbackQueryHandler(button_handler))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    await tg_app.initialize()
    await tg_app.start()
    webhook_addr = f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}"
    await tg_app.bot.set_webhook(webhook_addr)
    print(f"✅ Webhook set: {webhook_addr}")

if __name__ == "__main__":
    init_db()
    threading.Thread(target=start_loop, daemon=True).start()
    future = asyncio.run_coroutine_threadsafe(setup_bot(), loop)
    future.result(timeout=30)
    threading.Thread(target=reminder_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
