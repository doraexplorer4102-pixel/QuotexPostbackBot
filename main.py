import os
from flask import Flask, request
from telegram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))

bot = Bot(BOT_TOKEN)

app = Flask(__name__)

@app.route("/")
def home():
    return "Quotex Postback Bot Running"

@app.route("/postback")
def postback():
    data = request.args

    message = (
        f"🔥 QUOTEX POSTBACK\n\n"
        f"Trader ID: {data.get('uid')}\n"
        f"Country: {data.get('country')}\n"
        f"Status: {data.get('status')}\n"
        f"FTD: {data.get('ftd')}\n"
        f"Deposit: {data.get('sumdep')}\n"
        f"Withdrawal: {data.get('sumwithdraw')}"
    )

    bot.send_message(
        chat_id=OWNER_ID,
        text=message
    )

    return "OK"

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )
