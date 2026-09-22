import os
import threading
from flask import Flask
import bot

app = Flask(__name__)

@app.route('/')
def health():
    return "Bot is running", 200

def start_bot():
    try:
        print("🚀 ЗАПУСК БОТА В ПОТОКЕ")
        bot.main()
    except Exception as e:
        import traceback
        print("❌ БОТ УПАЛ: " + str(e))
        traceback.print_exc()

if __name__ == "__main__":
    threading.Thread(target=start_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
