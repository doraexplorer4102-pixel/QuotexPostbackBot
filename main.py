import os
import asyncio
from flask import Flask, request
from telegram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")

owner = os.getenv("OWNER_ID")

if not owner:
    raise Exception("OWNER_ID variable not found in Railway")

OWNER_ID = int(owner)

bot = Bot(BOT_TOKEN)

app = Flask(__name__)


@app.route("/")
def home():
    return "Quotex Postback Bot Running"


@app.route("/postback")
def postback():
    data = request.args

    message = (
        "🔥 QUOTEX POSTBACK\n\n"
        f"👤 Trader ID: {data.get('uid', 'N/A')}\n"
        f"🌍 Country: {data.get('country', 'N/A')}\n"
        f"📌 Status: {data.get('status', 'N/A')}\n"
        f"💰 Deposit: ${data.get('sumdep', '0')}\n"
        f"💸 Withdrawal: ${data.get('sumwithdraw', '0')}"
    )

    try:
        asyncio.run(
            bot.send_message(
                chat_id=OWNER_ID,
                text=message
            )
        )

    except Exception as e:
        print("Telegram Error:", e)

    return "OK"


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )
