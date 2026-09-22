import threading
import bot

# ...

if __name__ == "__main__":
    threading.Thread(target=bot.main, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
