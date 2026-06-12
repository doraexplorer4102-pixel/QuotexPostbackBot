import os
import asyncio
import threading
import time
import ssl
from datetime import datetime
from flask import Flask, request, Response
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN    = os.getenv("BOT_TOKEN")
OWNER_ID     = int(os.getenv("OWNER_ID", "0"))
VIP_LINK     = os.getenv("VIP_LINK", "https://t.me/+H3isrme8c3BiNDg1")
AFFILIATE    = "https://broker-qx.pro/sign-up/?lid=1504736"
WEBHOOK_URL  = os.getenv("WEBHOOK_URL", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
MIN_DEPOSIT  = 20
ADMIN_KEY    = os.getenv("ADMIN_KEY", "quotexadmin2024")

user_state: dict = {}
app = Flask(__name__)
tg_app: Application = None
loop = asyncio.new_event_loop()

# ─── DATABASE ─────────────────────────────────────────────────────────────────
import pg8000.native

def get_db():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = DATABASE_URL.replace("postgresql://", "").replace("postgres://", "")
    userpass, rest = url.split("@", 1)
    user, password = userpass.split(":", 1)
    hostport, database = rest.split("/", 1)
    host, port = (hostport.split(":") + ["5432"])[:2]
    return pg8000.native.Connection(
        host=host, port=int(port), user=user,
        password=password, database=database,
        ssl_context=ctx
    )

def init_db():
    conn = get_db()
    conn.run("""
        CREATE TABLE IF NOT EXISTS verified_traders (
            uid TEXT PRIMARY KEY,
            deposit FLOAT DEFAULT 0.0,
            status TEXT DEFAULT '',
            country TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.close()
    print("✅ Database ready")

def db_save_trader(uid, deposit=0.0, status="", country=""):
    try:
        conn = get_db()
        conn.run("""
            INSERT INTO verified_traders (uid, deposit, status, country, updated_at)
            VALUES (:uid, :dep, :status, :country, NOW())
            ON CONFLICT (uid) DO UPDATE SET
                deposit = GREATEST(verified_traders.deposit, EXCLUDED.deposit),
                status = EXCLUDED.status,
                updated_at = NOW()
        """, uid=uid, dep=float(deposit), status=status, country=country)
        conn.close()
    except Exception as e:
        print(f"DB save error: {e}")

def db_get_trader(uid):
    try:
        conn = get_db()
        rows = conn.run(
            "SELECT uid, deposit FROM verified_traders WHERE uid = :uid",
            uid=uid
        )
        conn.close()
        if rows:
            return {"uid": rows[0][0], "deposit": float(rows[0][1] or 0)}
        return None
    except Exception as e:
        print(f"DB get error: {e}")
        return None

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def run_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=30)

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
        print(f"Owner notify error: {e}")

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

async def verify_id_then_respond(uid, chat_id):
    state = get_state(chat_id)
    bot = Bot(BOT_TOKEN)

    msg = await bot.send_message(
        chat_id=chat_id,
        text=f"🔍 *Verifying ID* `{uid}`*...*",
        parse_mode="Markdown"
    )

    # Check DB — wait up to 30s for postback if not found
    trader = db_get_trader(uid)
    if not trader:
        for _ in range(10):
            await asyncio.sleep(3)
            trader = db_get_trader(uid)
            if trader:
                break

    if not trader:
        state["step"] = "start"
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg.message_id,
            text=(
                "❌ *ID Not Verified!*\n\n"
                f"ID `{uid}` was *not registered through our link*.\n\n"
                "You must sign up using our link to get VIP access.\n\n"
                "👇 Register below and try again:"
            ),
            parse_mode="Markdown", reply_markup=reject_keyboard()
        )
        await notify_owner(f"❌ Fake ID attempt\n👤 ID: {uid}\n💬 Chat: {chat_id}")
        return

    dep = trader["deposit"]
    state["trader_id"] = uid
    state["deposit"] = dep
    state["last_reminder"] = datetime.now()
    state["first_reminder_sent"] = False

    if dep >= MIN_DEPOSIT:
        state["step"] = "done"
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg.message_id,
            text=f"✅ *ID `{uid}` verified! Deposit confirmed!*\n\nGranting VIP now... 🚀",
            parse_mode="Markdown"
        )
        await bot.send_message(
            chat_id=chat_id,
            text=f"🎉 *Welcome to VIP!*\n\n🚀 Join:\n👉 {VIP_LINK}\n\nWelcome! 🏆",
            parse_mode="Markdown"
        )
        await notify_owner(f"✅ VIP Granted\n👤 ID: {uid}\n💰 ${dep}\n💬 Chat: {chat_id}")
    else:
        state["step"] = "awaiting_deposit"
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg.message_id,
            text=(
                f"✅ *ID `{uid}` verified!*\n\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                "📋 *STEP 3 — Fund Your Account*\n\n"
                f"💰 Deposit minimum *${MIN_DEPOSIT}* to unlock VIP.\n\n"
                "Click below once deposited ✅"
            ),
            parse_mode="Markdown", reply_markup=deposit_keyboard()
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
        parse_mode="Markdown", reply_markup=register_keyboard()
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
                f"Minimum: *${MIN_DEPOSIT}*\n\nDeposit at least $20 and try again.",
                parse_mode="Markdown", reply_markup=deposit_keyboard()
            )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = get_state(chat_id)
    text = update.message.text.strip()
    if state["step"] == "awaiting_id":
        if not text.isdigit():
            await update.message.reply_text(
                "⚠️ Please send *only numbers* (e.g. `89057949`)", parse_mode="Markdown"
            )
            return
        state["step"] = "checking"
        asyncio.run_coroutine_threadsafe(verify_id_then_respond(text, chat_id), loop)
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
    update = Update.de_json(request.get_json(force=True), tg_app.bot)
    run_async(tg_app.process_update(update))
    return Response("OK", status=200)

@app.route("/postback")
def postback():
    uid     = request.args.get("uid", "").strip()
    status  = request.args.get("status", "")
    sumdep  = float(request.args.get("sumdep", 0))
    country = request.args.get("country", "N/A")

    if not uid or uid in ("{trader_id}", "{uid}"):
        return "OK"

    db_save_trader(uid, sumdep, status, country)

    try:
        run_async(notify_owner(f"🔥 POSTBACK\n\n👤 ID: {uid}\n🌍 {country}\n📌 {status}\n💰 ${sumdep}"))
    except Exception as e:
        print(f"Notify error: {e}")

    if sumdep >= MIN_DEPOSIT:
        for chat_id, state in user_state.items():
            if state.get("trader_id") == uid and state["step"] != "done":
                state["deposit"] = sumdep
                state["step"] = "done"
                async def send_vip(cid=chat_id):
                    await Bot(BOT_TOKEN).send_message(
                        chat_id=cid,
                        text=f"🎉 *Deposit Confirmed!*\n\n✅ Auto-verified!\n\n🚀 Join VIP:\n👉 {VIP_LINK}\n\nWelcome! 🏆",
                        parse_mode="Markdown"
                    )
                try:
                    run_async(send_vip())
                except Exception as e:
                    print(f"VIP send error: {e}")
                break
    return "OK"

@app.route("/addid")
def add_id():
    if request.args.get("key", "") != ADMIN_KEY:
        return Response("Forbidden", status=403)
    uid = request.args.get("uid", "").strip()
    if not uid:
        return "No uid"
    db_save_trader(uid, 0.0, "manual", "")
    return f"✅ ID {uid} added"

# ─── REMINDERS ────────────────────────────────────────────────────────────────

async def send_reminders():
    bot = Bot(BOT_TOKEN)
    now = datetime.now()
    for chat_id, state in list(user_state.items()):
        if state["step"] != "awaiting_deposit":
            continue
        elapsed = (now - (state.get("last_reminder") or now)).total_seconds()
        try:
            if not state["first_reminder_sent"] and elapsed >= 1800:
                state["first_reminder_sent"] = True
                state["last_reminder"] = now
                await bot.send_message(chat_id=chat_id,
                    text=f"⚠️ *Don't miss out!*\n\nID *{state['trader_id']}* — deposit *${MIN_DEPOSIT}* to unlock VIP! 🚀",
                    parse_mode="Markdown", reply_markup=deposit_keyboard())
            elif state["first_reminder_sent"] and elapsed >= 10800:
                state["last_reminder"] = now
                await bot.send_message(chat_id=chat_id,
                    text=f"🔔 *Still waiting!*\n\nID *{state['trader_id']}* — just *${MIN_DEPOSIT}* and you're in VIP! 📈",
                    parse_mode="Markdown", reply_markup=deposit_keyboard())
        except Exception as e:
            print(f"Reminder error: {e}")

def reminder_loop():
    while True:
        time.sleep(300)
        try:
            run_async(send_reminders())
        except Exception as e:
            print(f"Reminder loop error: {e}")

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
    asyncio.run_coroutine_threadsafe(setup_bot(), loop).result(timeout=30)
    threading.Thread(target=reminder_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
