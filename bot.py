# ========== ИМПОРТЫ ==========
import urllib.request
import json
import random
import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager
import time
import threading
import re
import ssl
import html as html_mod
import os

# ========== ДЛЯ TURSO ==========
try:
    import libsql
except ImportError:
    libsql = None

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = "8867087634:AAGehtjfnpQE4SRNh0SyXn51Hi8SuVSBUmY"
ADMIN_ID = 6548175188
CHAT_ID = -1001234567890

JACKPOT_CHANCE = 0.01
JACKPOT_AMOUNT = 100000000000
MAX_ROULETTE_BETS = 100
DB_DATE_FMT = "%Y-%m-%d %H:%M:%S"

try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    SCRIPT_DIR = os.getcwd()
DB_PATH = os.path.join(SCRIPT_DIR, 'game_bot.db')

TITLES = {
    "roulette_king":   {"name": "🎰 Король рулетки",   "condition": "Выиграть 150 раз в рулетке", "type": "roulette_wins", "threshold": 150},
    "roulette_legend": {"name": "👑 Легенда рулетки",  "condition": "Выиграть 250 раз в рулетке", "type": "roulette_wins", "threshold": 250},
    "roulette_grand":  {"name": "💎 Гранд рулетки",    "condition": "Выиграть 500 раз в рулетке", "type": "roulette_wins", "threshold": 500},
    "fiasco":          {"name": "💀 Фиаско",           "condition": "Проиграть 150,000,000,000 в рулетке", "type": "roulette_lost", "threshold": 150_000_000_000},
    "autumn":          {"name": "🍂 Словно Осень",     "condition": "Быть в боте 10 дней", "type": "days_in_bot", "threshold": 10},
    "god_of_game":     {"name": "🔱 Бог игры",         "condition": "Выдаётся только владельцем", "type": "manual", "threshold": 0},
    "luck":            {"name": "🍀 Фарт",             "condition": "Выиграть 300,000,000,000 в рулетке", "type": "roulette_won", "threshold": 300_000_000_000},
}

DB_LOCK = threading.RLock()
CRASH_LOCK = threading.RLock()
DUEL_LOCK = threading.RLock()
PROMO_LOCK = threading.RLock()
TITLE_LOCK = threading.RLock()
ROULETTE_BETS_LOCK = threading.RLock()
JACKPOT_LOCK = threading.RLock()

RL_RIG_NUMBER = None
RL_RIG_LOCK = threading.RLock()

user_states = {}
user_crash = {}


def db_now():
    return datetime.now().strftime(DB_DATE_FMT)


def db_parse(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:19], DB_DATE_FMT)
    except Exception:
        try:
            return datetime.fromisoformat(str(s))
        except Exception:
            return None


def esc(s):
    return html_mod.escape(str(s)) if s is not None else ""


try:
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    pass


print("🚀 ЗАПУСК БОТА")
print("=" * 60)
print(f"👑 Админ: {ADMIN_ID}")
print(f"🏆 Титулов: {len(TITLES)}")
print(f"📁 БД: {DB_PATH}")
if libsql and os.environ.get("TURSO_DATABASE_URL"):
    print("☁️ Используется Turso (облачная база)")
else:
    print("💾 Используется локальная SQLite база")
print("=" * 60)


# ========== БАЗА ДАННЫХ ==========
@contextmanager
def _conn():
    url = os.environ.get("TURSO_DATABASE_URL")
    token = os.environ.get("TURSO_AUTH_TOKEN")

    if libsql and url and token:
        # Подключение к Turso
        conn = libsql.connect(database=url, auth_token=token)
    else:
        # Локальная база
        conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)

    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute('''CREATE TABLE IF NOT EXISTS users
                             (user_id INTEGER PRIMARY KEY, username TEXT,
                              balance INTEGER DEFAULT 15000000, last_bonus TIMESTAMP,
                              registered TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                              invited_by INTEGER DEFAULT 0, invite_count INTEGER DEFAULT 0,
                              last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                              jackpot_won INTEGER DEFAULT 0)''')
                try:
                    c.execute("ALTER TABLE users ADD COLUMN jackpot_won INTEGER DEFAULT 0")
                except Exception:
                    pass
                c.execute('''CREATE TABLE IF NOT EXISTS transactions
                             (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                              amount INTEGER, type TEXT, game TEXT, details TEXT,
                              timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                c.execute('''CREATE TABLE IF NOT EXISTS roulette_history
                             (id INTEGER PRIMARY KEY AUTOINCREMENT, number INTEGER,
                              color TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                c.execute('''CREATE TABLE IF NOT EXISTS treasury
                             (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER,
                              balance INTEGER DEFAULT 0, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                c.execute('''CREATE TABLE IF NOT EXISTS duels
                             (id INTEGER PRIMARY KEY AUTOINCREMENT, challenger INTEGER,
                              opponent INTEGER, amount INTEGER, winner INTEGER,
                              status TEXT DEFAULT 'pending',
                              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, ended_at TIMESTAMP)''')
                c.execute('''CREATE TABLE IF NOT EXISTS invites
                             (id INTEGER PRIMARY KEY AUTOINCREMENT, inviter INTEGER,
                              invited INTEGER, reward INTEGER DEFAULT 50000,
                              timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                c.execute('''CREATE TABLE IF NOT EXISTS settings
                             (key TEXT PRIMARY KEY, value TEXT)''')
                c.execute('''CREATE TABLE IF NOT EXISTS promocodes
                             (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE,
                              reward INTEGER, max_uses INTEGER DEFAULT 1,
                              used_count INTEGER DEFAULT 0, created_by INTEGER,
                              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                              expires_at TIMESTAMP, is_active INTEGER DEFAULT 1,
                              used_by TEXT DEFAULT '')''')
                c.execute('''CREATE TABLE IF NOT EXISTS promo_uses
                             (id INTEGER PRIMARY KEY AUTOINCREMENT, promo_id INTEGER,
                              user_id INTEGER, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                              UNIQUE(promo_id, user_id))''')
                c.execute('''CREATE TABLE IF NOT EXISTS az_coins
                             (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER UNIQUE,
                              amount INTEGER DEFAULT 0, total_bought INTEGER DEFAULT 0,
                              total_spent INTEGER DEFAULT 0,
                              last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                c.execute('''CREATE TABLE IF NOT EXISTS az_exchanges
                             (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                              points_spent INTEGER, az_received INTEGER, rate INTEGER,
                              timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                c.execute('''CREATE TABLE IF NOT EXISTS case_stats
                             (user_id INTEGER, case_type TEXT,
                              opens INTEGER DEFAULT 0,
                              total_spent INTEGER DEFAULT 0,
                              total_won INTEGER DEFAULT 0,
                              best_prize INTEGER DEFAULT 0,
                              PRIMARY KEY (user_id, case_type))''')
                c.execute('''CREATE TABLE IF NOT EXISTS special_cases
                             (user_id INTEGER PRIMARY KEY,
                              progress INTEGER DEFAULT 0,
                              opens_used INTEGER DEFAULT 0,
                              last_open TIMESTAMP)''')
                c.execute('''CREATE TABLE IF NOT EXISTS rl_blocks
                             (user_id INTEGER PRIMARY KEY, blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                c.execute('''CREATE TABLE IF NOT EXISTS titles
                             (id INTEGER PRIMARY KEY AUTOINCREMENT,
                              user_id INTEGER, title_key TEXT, custom_text TEXT,
                              awarded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                              awarded_by INTEGER DEFAULT 0,
                              UNIQUE(user_id, title_key))''')
                c.execute('''CREATE TABLE IF NOT EXISTS title_stats
                             (user_id INTEGER PRIMARY KEY,
                              roulette_wins INTEGER DEFAULT 0,
                              roulette_losses INTEGER DEFAULT 0,
                              roulette_won_amount INTEGER DEFAULT 0,
                              roulette_lost_amount INTEGER DEFAULT 0,
                              last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                c.execute('''CREATE TABLE IF NOT EXISTS roulette_bets
                             (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                              amount INTEGER, bet_type TEXT, bet_from INTEGER,
                              bet_to INTEGER, bet_number INTEGER, label TEXT,
                              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                c.execute("INSERT OR IGNORE INTO treasury (chat_id, balance) VALUES (?, ?)", (CHAT_ID, 0))
                for k, v in [('az_rate', '1000000'), ('az_amount', '100'), ('az_enabled', 'True'),
                             ('tax_percent', '5'), ('roulette_enabled', 'True')]:
                    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
                c.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(LOWER(username))")
                c.execute("CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_roulette_ts ON roulette_history(timestamp)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_titles_user ON titles(user_id)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_rl_bets_user ON roulette_bets(user_id)")
                conn.commit()
        print("✅ БД готова")
        return True
    except Exception as e:
        print(f"❌ БД: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_tax_percent():
    v = get_setting('tax_percent')
    try:
        return int(v) if v else 5
    except Exception:
        return 5


def get_setting(key):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT value FROM settings WHERE key = ?", (key,))
                r = c.fetchone()
                return r["value"] if r else None
    except Exception:
        return None


def set_setting(key, value):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
                conn.commit()
        return True
    except Exception:
        return False


# ========== ТИТУЛЫ ==========
def get_user_titles(user_id):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT title_key, custom_text FROM titles WHERE user_id = ? ORDER BY awarded_at ASC, id ASC", (user_id,))
                rows = c.fetchall()
        result = []
        for r in rows:
            key = r["title_key"]
            if key.startswith("custom_"):
                result.append({"key": key, "name": "✨ " + esc(r["custom_text"]), "condition": "Выдан админом", "custom": True})
            elif key in TITLES:
                t = TITLES[key]
                result.append({"key": key, "name": t["name"], "condition": t["condition"], "custom": False})
        return result
    except Exception:
        return []


def user_has_title(user_id, title_key):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT id FROM titles WHERE user_id = ? AND title_key = ?", (user_id, title_key))
                return c.fetchone() is not None
    except Exception:
        return False


def award_title(user_id, title_key, custom_text=None, awarded_by=0):
    if title_key == "custom":
        if not custom_text:
            return False, "❌ Пустой текст!"
        title_key = "custom_" + custom_text.strip()[:30]
    if not title_key.startswith("custom_") and title_key not in TITLES:
        return False, "❌ Титул не существует!"
    try:
        with TITLE_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT id FROM titles WHERE user_id = ? AND title_key = ?", (user_id, title_key))
                if c.fetchone():
                    return False, "❌ У игрока уже есть этот титул!"
                c.execute("INSERT INTO titles (user_id, title_key, custom_text, awarded_by) VALUES (?, ?, ?, ?)",
                          (user_id, title_key, custom_text, awarded_by))
                conn.commit()
        title_name = "✨ " + custom_text if title_key.startswith("custom_") else TITLES[title_key]["name"]
        try:
            send_message(user_id, "<b>🏆 НОВЫЙ ТИТУЛ!</b>\n\n" + title_name)
        except Exception:
            pass
        return True, "✅ Титул " + title_name + " выдан " + str(user_id)
    except Exception as e:
        return False, "❌ " + str(e)


def remove_title(user_id, title_key):
    try:
        with TITLE_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM titles WHERE user_id = ? AND title_key = ?", (user_id, title_key))
                a = c.rowcount
                conn.commit()
        return a > 0
    except Exception:
        return False


def get_title_stats(user_id):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT roulette_wins, roulette_losses, roulette_won_amount, roulette_lost_amount FROM title_stats WHERE user_id = ?", (user_id,))
                r = c.fetchone()
                if r:
                    return (r["roulette_wins"] or 0, r["roulette_losses"] or 0, r["roulette_won_amount"] or 0, r["roulette_lost_amount"] or 0)
                return (0, 0, 0, 0)
    except Exception:
        return (0, 0, 0, 0)


def update_title_stats(user_id, wins=0, losses=0, won_amount=0, lost_amount=0):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT user_id FROM title_stats WHERE user_id = ?", (user_id,))
                if c.fetchone():
                    c.execute("UPDATE title_stats SET roulette_wins = roulette_wins + ?, roulette_losses = roulette_losses + ?, roulette_won_amount = roulette_won_amount + ?, roulette_lost_amount = roulette_lost_amount + ?, last_updated = ? WHERE user_id = ?",
                              (wins, losses, won_amount, lost_amount, db_now(), user_id))
                else:
                    c.execute("INSERT INTO title_stats (user_id, roulette_wins, roulette_losses, roulette_won_amount, roulette_lost_amount, last_updated) VALUES (?, ?, ?, ?, ?, ?)",
                              (user_id, wins, losses, won_amount, lost_amount, db_now()))
                conn.commit()
        return True
    except Exception:
        return False


def check_and_award_titles(user_id):
    awarded = []
    try:
        wins, losses, won_amount, lost_amount = get_title_stats(user_id)
        checks = [
            ("roulette_king", wins >= 150),
            ("roulette_legend", wins >= 250),
            ("roulette_grand", wins >= 500),
            ("fiasco", lost_amount >= 150_000_000_000),
            ("luck", won_amount >= 300_000_000_000),
        ]
        for key, cond in checks:
            if cond and not user_has_title(user_id, key):
                ok, _ = award_title(user_id, key)
                if ok:
                    awarded.append(TITLES[key]["name"])
        user = get_user(user_id)
        if user and user["registered"]:
            reg = db_parse(user["registered"])
            if reg and (datetime.now() - reg).days >= 10 and not user_has_title(user_id, "autumn"):
                ok, _ = award_title(user_id, "autumn")
                if ok:
                    awarded.append(TITLES["autumn"]["name"])
    except Exception as e:
        print("⚠️ check_and_award_titles: " + str(e))
    return awarded


def format_titles_for_profile(user_id):
    titles = get_user_titles(user_id)
    if not titles:
        return "🏆 Титулы: нет"
    text = "🏆 Титулы:\n"
    for t in titles:
        text += "  " + t["name"] + "\n"
    return text


def format_all_titles_list():
    text = "<b>🏆 ВСЕ ТИТУЛЫ</b>\n\n"
    for key, t in TITLES.items():
        text += t["name"] + "\n  " + t["condition"] + "\n  " + key + "\n\n"
    text += "✨ Кастомный\n  Выдаётся админом\n"
    return text


# ========== СТАВКИ РУЛЕТКИ ==========
def get_user_bets(user_id):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT id, amount, bet_type, bet_from, bet_to, bet_number, label FROM roulette_bets WHERE user_id = ? ORDER BY id ASC", (user_id,))
                rows = c.fetchall()
        result = []
        for r in rows:
            bet = {"id": r["id"], "amount": r["amount"], "type": r["bet_type"], "label": r["label"]}
            if r["bet_type"] == "range":
                bet["from"] = r["bet_from"]
                bet["to"] = r["bet_to"]
            elif r["bet_type"] == "number":
                bet["number"] = r["bet_number"]
            result.append(bet)
        return result
    except Exception:
        return []


def clear_bets_db(user_id):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM roulette_bets WHERE user_id = ?", (user_id,))
                conn.commit()
        return True
    except Exception:
        return False


def get_bets_count(user_id):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT COUNT(*) as cnt FROM roulette_bets WHERE user_id = ?", (user_id,))
                r = c.fetchone()
                return r["cnt"] if r else 0
    except Exception:
        return 0


def get_bets_total(user_id):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT COALESCE(SUM(amount),0) as total FROM roulette_bets WHERE user_id = ?", (user_id,))
                r = c.fetchone()
                return r["total"] if r else 0
    except Exception:
        return 0


def is_roulette_enabled():
    return get_setting('roulette_enabled') == 'True'


def set_roulette_enabled(e):
    return set_setting('roulette_enabled', str(e))


def rl_block_user(uid):
    try:
        with DB_LOCK:
            with _conn() as conn:
                conn.execute("INSERT OR IGNORE INTO rl_blocks (user_id) VALUES (?)", (uid,))
                conn.commit()
        return True
    except Exception:
        return False


def rl_unblock_user(uid):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM rl_blocks WHERE user_id = ?", (uid,))
                a = c.rowcount
                conn.commit()
        return a > 0
    except Exception:
        return False


def rl_is_blocked(uid):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT user_id FROM rl_blocks WHERE user_id = ?", (uid,))
                return c.fetchone() is not None
    except Exception:
        return False


def rl_blocklist():
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT user_id, blocked_at FROM rl_blocks ORDER BY blocked_at DESC")
                return [tuple(x) for x in c.fetchall()]
    except Exception:
        return []


def rl_set_rig(n):
    global RL_RIG_NUMBER
    with RL_RIG_LOCK:
        RL_RIG_NUMBER = n


def rl_get_rig():
    with RL_RIG_LOCK:
        return RL_RIG_NUMBER


def rl_consume_rig():
    global RL_RIG_NUMBER
    with RL_RIG_LOCK:
        n = RL_RIG_NUMBER
        RL_RIG_NUMBER = None
        return n


# ========== USERS ==========
def get_user(user_id):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                return c.fetchone()
    except Exception as e:
        print(f"⚠️ get_user({user_id}): {e}")
        return None


def create_user(user_id, username=None):
    try:
        with DB_LOCK:
            with _conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO users (user_id, username, balance, last_bonus, last_active) VALUES (?, ?, ?, ?, ?)",
                    (user_id, username or str(user_id), 15000000, db_now(), db_now()))
                conn.commit()
        return True
    except Exception as e:
        print(f"❌ CREATE_USER FAILED ({user_id}): {type(e).__name__}: {e}")
        return False


def get_or_create_user(user_id, username=None):
    user = get_user(user_id)
    if user:
        if username:
            try:
                with DB_LOCK:
                    with _conn() as conn:
                        conn.execute("UPDATE users SET username = ? WHERE user_id = ? AND username != ?",
                                     (username, user_id, username))
                        conn.commit()
            except Exception:
                pass
        return user
    create_user(user_id, username)
    for _ in range(5):
        user = get_user(user_id)
        if user:
            return user
        time.sleep(0.1)
    return None


def get_balance(user_id):
    u = get_user(user_id)
    return u["balance"] if u else 0


def add_transaction(user_id, amount, type_, game=None, details=None):
    try:
        with DB_LOCK:
            with _conn() as conn:
                conn.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                             (user_id, amount, type_, game, details))
                conn.commit()
        return True
    except Exception:
        return False


def get_last_bonus(user_id):
    u = get_user(user_id)
    if u and u["last_bonus"]:
        dt = db_parse(u["last_bonus"])
        if dt:
            return dt
    return None


def update_last_active(user_id):
    try:
        with DB_LOCK:
            with _conn() as conn:
                conn.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (db_now(), user_id))
                conn.commit()
        return True
    except Exception:
        return False


def add_roulette_result(number, color):
    try:
        with DB_LOCK:
            with _conn() as conn:
                conn.execute("INSERT INTO roulette_history (number, color) VALUES (?, ?)", (number, color))
                conn.commit()
        return True
    except Exception:
        return False


def get_roulette_history(limit=7):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT number, color FROM roulette_history ORDER BY timestamp DESC LIMIT ?", (limit,))
                return [tuple(x) for x in c.fetchall()][::-1]
    except Exception:
        return []


# ========== КАЗНА ==========
def get_treasury(chat_id):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT balance FROM treasury WHERE chat_id = ?", (chat_id,))
                r = c.fetchone()
                return r["balance"] if r else 0
    except Exception:
        return 0


def donate_to_treasury(chat_id, user_id, amount):
    if amount < 100:
        return False, "❌ Минимум 100!"
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                          (amount, user_id, amount))
                if c.rowcount == 0:
                    conn.rollback()
                    bal = get_balance(user_id)
                    return False, "❌ Недостаточно! Баланс: " + str(bal)
                c.execute("INSERT OR IGNORE INTO treasury (chat_id, balance) VALUES (?, 0)", (chat_id,))
                c.execute("UPDATE treasury SET balance = balance + ?, last_updated = ? WHERE chat_id = ?",
                          (amount, db_now(), chat_id))
                c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                          (user_id, -amount, "treasury_donation", "treasury", "Пожертвование"))
                conn.commit()
    except Exception as e:
        return False, "❌ " + str(e)
    return True, "🙏 Спасибо! +" + format(amount, ",") + "\n💎 Баланс: " + format(get_balance(user_id), ",")


def treasury_withdraw(chat_id, user_id, amount, reason):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("UPDATE treasury SET balance = balance - ? WHERE chat_id = ? AND balance >= ?",
                          (amount, chat_id, amount))
                if c.rowcount == 0:
                    conn.rollback()
                    tbal = get_treasury(chat_id)
                    return False, "❌ Мало в казне! Сейчас: " + format(tbal, ",")
                c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
                c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                          (user_id, amount, "treasury_withdraw", "treasury", reason))
                conn.commit()
    except Exception as e:
        return False, "❌ " + str(e)
    return True, "✅ Выдано " + format(amount, ",") + " → " + str(user_id)


def get_treasury_total_in():
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT SUM(amount) FROM transactions WHERE game = 'treasury' AND type IN ('treasury_donation', 'treasury_admin_add', 'duel_tax')")
                r = c.fetchone()
                val = r[0] if r and r[0] else 0
                return abs(val) if val else 0
    except Exception:
        return 0


def get_treasury_total_out():
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT SUM(amount) FROM transactions WHERE game = 'treasury' AND type = 'treasury_withdraw'")
                r = c.fetchone()
                val = r[0] if r and r[0] else 0
                return abs(val) if val else 0
    except Exception:
        return 0


def get_treasury_logs(limit=10):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT amount, type, details, timestamp FROM transactions WHERE game = 'treasury' ORDER BY timestamp DESC LIMIT ?", (limit,))
                return [tuple(x) for x in c.fetchall()]
    except Exception:
        return []


def set_tax_percent(new_percent):
    if 0 <= new_percent <= 100:
        set_setting('tax_percent', str(new_percent))
        return True, "✅ Налог: " + str(new_percent) + "%"
    return False, "❌ 0-100!"


def get_invite_count(user_id):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT invite_count FROM users WHERE user_id = ?", (user_id,))
                r = c.fetchone()
                return r["invite_count"] if r else 0
    except Exception:
        return 0


# ========== ДУЭЛИ ==========
def create_duel(challenger_id, opponent_id, amount, chat_id=None):
    if challenger_id == opponent_id:
        return False, "❌ Себя нельзя!"
    balance = get_balance(challenger_id)
    if amount > balance:
        return False, "❌ Баланс: " + format(balance, ",")
    try:
        with DUEL_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT id FROM duels WHERE (challenger IN (?, ?) OR opponent IN (?, ?)) AND status IN ('pending', 'processing')",
                          (challenger_id, opponent_id, challenger_id, opponent_id))
                if c.fetchone():
                    return False, "❌ У кого-то уже есть активная дуэль!"
                c.execute("INSERT INTO duels (challenger, opponent, amount) VALUES (?, ?, ?)",
                          (challenger_id, opponent_id, amount))
                duel_id = c.lastrowid
                conn.commit()
            return True, duel_id
    except Exception as e:
        return False, "❌ " + str(e)


def accept_duel(duel_id, opponent_id, chat_id=None):
    tax_percent = get_tax_percent()
    if chat_id is None:
        chat_id = CHAT_ID
    try:
        with DUEL_LOCK:
            with _conn() as conn:
                try:
                    c = conn.cursor()
                    c.execute("UPDATE duels SET status = 'processing' WHERE id = ? AND status = 'pending'", (duel_id,))
                    if c.rowcount == 0:
                        conn.rollback()
                        return False, "❌ Не найдена или уже принята!"
                    c.execute("SELECT * FROM duels WHERE id = ?", (duel_id,))
                    duel = c.fetchone()
                    if duel["opponent"] != opponent_id:
                        conn.rollback()
                        return False, "❌ Не ваша!"
                    if duel["challenger"] == opponent_id:
                        conn.rollback()
                        return False, "❌ Нельзя принять свою дуэль!"
                    amount = duel["amount"]
                    c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                              (amount, duel["challenger"], amount))
                    if c.rowcount == 0:
                        c.execute("UPDATE duels SET status = 'cancelled' WHERE id = ?", (duel_id,))
                        conn.commit()
                        return False, "❌ У создателя недостаточно средств!"
                    c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                              (amount, opponent_id, amount))
                    if c.rowcount == 0:
                        conn.rollback()
                        bal = get_balance(opponent_id)
                        return False, "❌ Баланс: " + format(bal, ",")
                    winner = random.choice([duel["challenger"], duel["opponent"]])
                    c.execute("UPDATE duels SET status = 'finished', winner = ?, ended_at = ? WHERE id = ?",
                              (winner, db_now(), duel_id))
                    total_pot = amount * 2
                    tax = int(total_pot * tax_percent / 100)
                    win_amount = total_pot - tax
                    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (win_amount, winner))
                    c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                              (duel["challenger"], -amount, "duel_bet", "duel", "Дуэль #" + str(duel_id)))
                    c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                              (opponent_id, -amount, "duel_bet", "duel", "Дуэль #" + str(duel_id)))
                    c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                              (winner, win_amount, "duel_win", "duel", "Дуэль #" + str(duel_id)))
                    if tax > 0:
                        c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                                  (0, tax, "duel_tax", "treasury", "Налог #" + str(duel_id)))
                        c.execute("INSERT OR IGNORE INTO treasury (chat_id, balance) VALUES (?, 0)", (chat_id,))
                        c.execute("UPDATE treasury SET balance = balance + ?, last_updated = ? WHERE chat_id = ?",
                                  (tax, db_now(), chat_id))
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
        return True, "⚔️ ДУЭЛЬ! Победитель: " + str(winner) + "\n💰 Ставка: " + format(amount, ",") + "\n💎 Выигрыш: " + format(win_amount, ",") + "\n🏛️ Казне: +" + format(tax, ",")
    except Exception as e:
        return False, "❌ " + str(e)


def get_active_duel(user_id):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT id, challenger, opponent, amount FROM duels WHERE (challenger = ? OR opponent = ?) AND status IN ('pending', 'processing')",
                          (user_id, user_id))
                r = c.fetchone()
                return tuple(r) if r else None
    except Exception:
        return None


def get_user_id_by_username(username):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                username = username.lstrip('@').strip()
                c.execute("SELECT user_id FROM users WHERE username = ? OR LOWER(username) = LOWER(?)",
                          (username, username))
                r = c.fetchone()
                return r["user_id"] if r else None
    except Exception:
        return None


# ========== ПРОМОКОДЫ ==========
def create_promocode(code, reward, max_uses=1, expires_days=7):
    code = (code or "").strip().upper().replace(" ", "")
    if not code:
        return False, "❌ Пустой код!"
    try:
        with PROMO_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT id FROM promocodes WHERE code = ?", (code,))
                if c.fetchone():
                    return False, "❌ Такой промокод уже есть!"
                expires_at = (datetime.now() + timedelta(days=expires_days)).strftime(DB_DATE_FMT)
                c.execute("INSERT INTO promocodes (code, reward, max_uses, expires_at, created_by) VALUES (?, ?, ?, ?, ?)",
                          (code, reward, max_uses, expires_at, ADMIN_ID))
                conn.commit()
        return True, "✅ Промокод " + code + " создан! Награда: " + format(reward, ",") + ", лимит: " + str(max_uses)
    except Exception as e:
        return False, "❌ " + str(e)


def use_promocode(user_id, code):
    code = (code or "").strip().upper().replace(" ", "")
    if not code:
        return False, "❌ Пустой промокод!"
    try:
        with PROMO_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT id, reward, max_uses, used_count, expires_at, is_active FROM promocodes WHERE code = ?", (code,))
                r = c.fetchone()
                if not r:
                    return False, "❌ Промокод не найден!"
                promo_id = r["id"]
                reward = r["reward"]
                max_uses = r["max_uses"]
                expires_at = r["expires_at"]
                is_active = r["is_active"]
                if not is_active:
                    return False, "❌ Промокод неактивен!"
                if expires_at:
                    dt = db_parse(expires_at)
                    if dt and dt < datetime.now():
                        return False, "❌ Промокод истёк!"
                try:
                    c.execute("INSERT INTO promo_uses (promo_id, user_id) VALUES (?, ?)", (promo_id, user_id))
                except sqlite3.IntegrityError:
                    conn.rollback()
                    return False, "❌ Ты уже использовал этот промокод!"
                c.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE id = ? AND used_count < max_uses", (promo_id,))
                if c.rowcount == 0:
                    conn.rollback()
                    return False, "❌ Лимит использований исчерпан!"
                c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (reward, user_id))
                if c.rowcount == 0:
                    conn.rollback()
                    return False, "❌ Пользователь не найден! Напиши /start"
                c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                          (user_id, reward, "promocode", "promo", "Промокод: " + code))
                conn.commit()
        return True, "🎉 ПРОМОКОД АКТИВИРОВАН!\nКод: " + code + "\n💰 +" + format(reward, ",") + "\n💎 Баланс: " + format(get_balance(user_id), ",")
    except Exception as e:
        return False, "❌ Ошибка: " + str(e)


def get_all_promocodes():
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT code, reward, max_uses, used_count, expires_at, is_active FROM promocodes ORDER BY created_at DESC")
                return [tuple(x) for x in c.fetchall()]
    except Exception:
        return []


def delete_promocode(code):
    code = (code or "").strip().upper()
    try:
        with PROMO_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM promocodes WHERE code = ?", (code,))
                a = c.rowcount
                conn.commit()
        return a > 0
    except Exception:
        return False


def toggle_promocode(code):
    code = (code or "").strip().upper()
    try:
        with PROMO_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT is_active FROM promocodes WHERE code = ?", (code,))
                r = c.fetchone()
                if not r:
                    return False, "❌ Не найден!"
                new_status = 0 if r["is_active"] else 1
                c.execute("UPDATE promocodes SET is_active = ? WHERE code = ?", (new_status, code))
                conn.commit()
        return True, "✅ " + ("Активирован" if new_status else "Деактивирован")
    except Exception:
        return False, "❌ Ошибка!"


# ========== AZ ==========
def get_az_balance(user_id):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT amount FROM az_coins WHERE user_id = ?", (user_id,))
                r = c.fetchone()
                return r["amount"] if r else 0
    except Exception:
        return 0


def get_az_rate():
    v = get_setting('az_rate')
    try:
        return int(v) if v else 1000000
    except Exception:
        return 1000000


def set_az_rate(r):
    return set_setting('az_rate', str(r))


def get_az_amount():
    v = get_setting('az_amount')
    try:
        return int(v) if v else 100
    except Exception:
        return 100


def set_az_amount(a):
    return set_setting('az_amount', str(a))


def is_az_enabled():
    return get_setting('az_enabled') == 'True'


def set_az_enabled(e):
    return set_setting('az_enabled', str(e))


def exchange_az(user_id, times=1):
    if not is_az_enabled():
        return False, "❌ Отключён!"
    if times < 1 or times > 100:
        return False, "❌ 1-100!"
    rate = get_az_rate()
    az_per = get_az_amount()
    total_points = rate * times
    total_az = az_per * times
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                          (total_points, user_id, total_points))
                if c.rowcount == 0:
                    conn.rollback()
                    return False, "❌ Мало! Нужно: " + format(total_points, ",")
                c.execute("SELECT id FROM az_coins WHERE user_id = ?", (user_id,))
                if c.fetchone():
                    c.execute("UPDATE az_coins SET amount = amount + ?, total_bought = total_bought + ?, last_updated = ? WHERE user_id = ?",
                              (total_az, total_az, db_now(), user_id))
                else:
                    c.execute("INSERT INTO az_coins (user_id, amount, total_bought, last_updated) VALUES (?, ?, ?, ?)",
                              (user_id, total_az, total_az, db_now()))
                c.execute("INSERT INTO az_exchanges (user_id, points_spent, az_received, rate) VALUES (?, ?, ?, ?)",
                          (user_id, total_points, total_az, rate))
                c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                          (user_id, -total_points, "az_exchange", "az", "Обмен " + str(times) + "x"))
                conn.commit()
    except Exception as e:
        return False, "❌ " + str(e)
    return True, "💱 ОБМЕН " + str(times) + "x\n💸 -" + format(total_points, ",") + "\n💎 +" + str(total_az) + " Az\n\n💰 " + format(get_balance(user_id), ",") + "\n💎 " + str(get_az_balance(user_id))


def get_az_history(user_id, limit=10):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT points_spent, az_received, timestamp FROM az_exchanges WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                          (user_id, limit))
                return [tuple(x) for x in c.fetchall()]
    except Exception:
        return []


def get_az_top(limit=10):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT a.user_id, u.username, a.amount, a.total_bought FROM az_coins a LEFT JOIN users u ON a.user_id = u.user_id WHERE a.amount > 0 ORDER BY a.amount DESC LIMIT ?", (limit,))
                return [tuple(x) for x in c.fetchall()]
    except Exception:
        return []


# ========== КЕЙСЫ ==========
CASES = {
    "common": {"name": "🥉 ОБЫЧНЫЙ КЕЙС", "price": 500000, "currency": "points",
        "rewards": [{"amount": 100000, "chance": 50, "emoji": "💵"},
                    {"amount": 300000, "chance": 35, "emoji": "💰"},
                    {"amount": 1000000, "chance": 15, "emoji": "💎"}]},
    "rare": {"name": "🥈 РЕДКИЙ КЕЙС", "price": 10000000, "currency": "points",
        "rewards": [{"amount": 5000000, "chance": 50, "emoji": "💵"},
                    {"amount": 7000000, "chance": 35, "emoji": "💰"},
                    {"amount": 15000000, "chance": 15, "emoji": "💎"}]},
    "legendary": {"name": "🥇 ЛЕГЕНДАРНЫЙ КЕЙС", "price": 100000000, "currency": "points",
        "rewards": [{"amount": 60000000, "chance": 50, "emoji": "💵"},
                    {"amount": 70000000, "chance": 35, "emoji": "💰"},
                    {"amount": 170000000, "chance": 15, "emoji": "💎"}]},
    "az": {"name": "💎 AZ КЕЙС", "price": 900, "currency": "az",
        "rewards": [{"amount": 5000000, "chance": 50, "emoji": "💵"},
                    {"amount": 10000000, "chance": 35, "emoji": "💰"},
                    {"amount": 500000000, "chance": 15, "emoji": "🏆"}]},
    "special": {"name": "🌟 ОСОБЫЙ КЕЙС", "price": 0, "currency": "special", "requires_opens": 100,
        "rewards": [{"amount": 20000000, "chance": 50, "emoji": "💵"},
                    {"amount": 40000000, "chance": 35, "emoji": "💰"},
                    {"amount": 100000000, "chance": 15, "emoji": "💎"}]},
    "lizard": {"name": "🦎 ЛИЗИАРД КЕЙС", "price": 50000000, "currency": "points",
        "rewards": [{"amount": 1000000000000, "chance": 5, "emoji": "🦎"},
                    {"amount": 1, "chance": 95, "emoji": "🍃"}]}
}


def get_special_progress(user_id):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT progress, opens_used FROM special_cases WHERE user_id = ?", (user_id,))
                r = c.fetchone()
                return (r["progress"], r["opens_used"]) if r else (0, 0)
    except Exception:
        return (0, 0)


def get_case_stats(user_id):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT case_type, opens, total_spent, total_won, best_prize FROM case_stats WHERE user_id = ?", (user_id,))
                r = c.fetchall()
        total_opens = sum((x["opens"] or 0) for x in r)
        total_spent = sum((x["total_spent"] or 0) for x in r)
        total_won = sum((x["total_won"] or 0) for x in r)
        return {"total_opens": total_opens, "total_spent": total_spent,
                "total_won": total_won, "total_profit": total_won - total_spent,
                "by_type": [tuple(x) for x in r]}
    except Exception:
        return {"total_opens": 0, "total_spent": 0, "total_won": 0, "total_profit": 0, "by_type": []}


def get_case_top(limit=10):
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT user_id, SUM(COALESCE(total_won,0) - COALESCE(total_spent,0)) as profit, SUM(COALESCE(opens,0)) as opens FROM case_stats GROUP BY user_id ORDER BY profit DESC LIMIT ?", (limit,))
                return [tuple(x) for x in c.fetchall()]
    except Exception:
        return []


def roll_case_reward(case_type):
    case = CASES.get(case_type)
    if not case:
        return None
    roll = random.randint(1, 100)
    cumulative = 0
    for reward in case["rewards"]:
        cumulative += reward["chance"]
        if roll <= cumulative:
            return reward
    return case["rewards"][-1]


def open_cases_batch(chat_id, message_id, user_id, case_type, count):
    case = CASES.get(case_type)
    if not case:
        send_message(chat_id, "❌ Кейс не найден!")
        return
    if count < 1 or count > 100:
        send_message(chat_id, "❌ Количество: 1-100!")
        return
    currency = case.get("currency", "points")
    price = case["price"]
    rewards_list = []
    for _ in range(count):
        reward = roll_case_reward(case_type)
        if reward:
            rewards_list.append(reward["amount"])
    total_won = sum(rewards_list)
    best_prize = max(rewards_list) if rewards_list else 0
    progress_before, _ = get_special_progress(user_id)
    az_balance = get_az_balance(user_id)
    balance = get_balance(user_id)
    total_cost_az = 0
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                if case_type == "special":
                    available = progress_before // 100
                    if available < 1:
                        send_message(chat_id, "❌ Нужно 100 открытий! У тебя: " + str(progress_before) + "/100")
                        return
                    if count > available:
                        send_message(chat_id, "❌ У тебя только " + str(available) + " особых!")
                        return
                    c.execute("UPDATE special_cases SET progress = progress - ?, opens_used = opens_used + ? WHERE user_id = ? AND progress >= ?",
                              (count * 100, count, user_id, count * 100))
                    if c.rowcount == 0:
                        conn.rollback()
                        send_message(chat_id, "❌ Ошибка прогресса!")
                        return
                    stat_price = 0
                    cost_text = "Бесплатно (100 открытий)"
                elif currency == "az":
                    total_cost_az = price * count
                    if az_balance < total_cost_az:
                        send_message(chat_id, "❌ Мало Az! Нужно: " + str(total_cost_az) + ", есть: " + str(az_balance))
                        return
                    c.execute("UPDATE az_coins SET amount = amount - ?, total_spent = total_spent + ?, last_updated = ? WHERE user_id = ? AND amount >= ?",
                              (total_cost_az, total_cost_az, db_now(), user_id, total_cost_az))
                    if c.rowcount == 0:
                        conn.rollback()
                        send_message(chat_id, "❌ Ошибка списания Az!")
                        return
                    c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                              (user_id, -total_cost_az, "case_open_az", "case", case["name"] + " x" + str(count)))
                    stat_price = total_cost_az * get_az_rate()
                    cost_text = str(total_cost_az) + " Az"
                else:
                    total_cost = price * count
                    if balance < total_cost:
                        send_message(chat_id, "❌ Мало поинтов! Нужно: " + format(total_cost, ",") + ", есть: " + format(balance, ","))
                        return
                    c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                              (total_cost, user_id, total_cost))
                    if c.rowcount == 0:
                        conn.rollback()
                        send_message(chat_id, "❌ Ошибка списания!")
                        return
                    c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                              (user_id, -total_cost, "case_open", "case", case["name"] + " x" + str(count)))
                    stat_price = price
                    cost_text = format(total_cost, ",")
                c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (total_won, user_id))
                c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                          (user_id, total_won, "case_win", "case", case["name"] + " x" + str(count)))
                c.execute("SELECT opens FROM case_stats WHERE user_id = ? AND case_type = ?", (user_id, case_type))
                exists = c.fetchone()
                if stat_price > 0:
                    if exists:
                        c.execute("UPDATE case_stats SET opens = opens + ?, total_spent = total_spent + ?, total_won = total_won + ?, best_prize = MAX(COALESCE(best_prize, 0), ?) WHERE user_id = ? AND case_type = ?",
                                  (count, stat_price, total_won, best_prize, user_id, case_type))
                    else:
                        c.execute("INSERT INTO case_stats (user_id, case_type, opens, total_spent, total_won, best_prize) VALUES (?, ?, ?, ?, ?, ?)",
                                  (user_id, case_type, count, stat_price, total_won, best_prize))
                else:
                    if exists:
                        c.execute("UPDATE case_stats SET opens = opens + ?, total_won = total_won + ?, best_prize = MAX(COALESCE(best_prize, 0), ?) WHERE user_id = ? AND case_type = ?",
                                  (count, total_won, best_prize, user_id, case_type))
                    else:
                        c.execute("INSERT INTO case_stats (user_id, case_type, opens, total_spent, total_won, best_prize) VALUES (?, ?, ?, 0, ?, ?)",
                                  (user_id, case_type, count, total_won, best_prize))
                if case_type != "special":
                    c.execute("SELECT progress FROM special_cases WHERE user_id = ?", (user_id,))
                    r = c.fetchone()
                    if r:
                        c.execute("UPDATE special_cases SET progress = progress + ?, last_open = ? WHERE user_id = ?",
                                  (count, db_now(), user_id))
                    else:
                        c.execute("INSERT INTO special_cases (user_id, progress, last_open) VALUES (?, ?, ?)",
                                  (user_id, count, db_now()))
                conn.commit()
    except Exception as e:
        send_message(chat_id, "❌ Ошибка: " + str(e))
        return
    if message_id:
        try:
            edit_message(chat_id, message_id, case["name"] + "\nОткрываем " + str(count) + "...", None)
            time.sleep(0.5)
        except Exception:
            pass
    rewards_count = {}
    for amount in rewards_list:
        rewards_count[amount] = rewards_count.get(amount, 0) + 1
    if currency == "az":
        profit = total_won - (total_cost_az * get_az_rate())
    elif case_type == "special":
        profit = total_won
    else:
        profit = total_won - (price * count)
    sign = "+" if profit > 0 else ""
    breakdown = ""
    for amount in sorted(rewards_count.keys(), reverse=True):
        cnt = rewards_count[amount]
        breakdown += str(amount) + " x" + str(cnt) + "\n"
    progress, used = get_special_progress(user_id)
    msg = case["name"] + " x" + str(count) + "\n\n"
    msg += "Выпало:\n" + breakdown + "\n"
    msg += "Потрачено: " + cost_text + "\n"
    msg += "Получено: " + format(total_won, ",") + "\n"
    msg += "Профит: " + sign + format(profit, ",") + "\n"
    msg += "Лучший: " + format(best_prize, ",") + "\n\n"
    msg += "Поинты: " + format(get_balance(user_id), ",") + "\n"
    msg += "Az: " + str(get_az_balance(user_id))
    if case_type == "special":
        keyboard = {"inline_keyboard": [
            [{"text": "ОТКРЫТЬ ЕЩЁ", "callback_data": "case_menu_special"}],
            [{"text": "ВСЕ КЕЙСЫ", "callback_data": "cases_menu"}],
            [{"text": "НАЗАД", "callback_data": "back"}]]}
    else:
        keyboard = {"inline_keyboard": [
            [{"text": "ЕЩЁ x" + str(count), "callback_data": "case_open_" + case_type + "_" + str(count)}],
            [{"text": "x1", "callback_data": "case_open_" + case_type + "_1"},
             {"text": "x10", "callback_data": "case_open_" + case_type + "_10"},
             {"text": "x50", "callback_data": "case_open_" + case_type + "_50"}],
            [{"text": "СВОЁ", "callback_data": "case_custom_" + case_type}],
            [{"text": "ВСЕ КЕЙСЫ", "callback_data": "cases_menu"}]]}
    if message_id:
        edit_message(chat_id, message_id, msg, keyboard)
    else:
        send_message(chat_id, msg, keyboard)


# ========== РУЛЕТКА ==========
ROULETTE_COLORS = {0: "green",
    1: "red", 2: "black", 3: "red", 4: "black", 5: "red", 6: "black",
    7: "red", 8: "black", 9: "red", 10: "black", 11: "black", 12: "red",
    13: "black", 14: "red", 15: "black", 16: "red", 17: "black", 18: "red",
    19: "red", 20: "black", 21: "red", 22: "black", 23: "red", 24: "black",
    25: "red", 26: "black", 27: "red", 28: "black", 29: "black", 30: "red",
    31: "black", 32: "red", 33: "black", 34: "red", 35: "black", 36: "red"}


def get_roulette_color(n):
    return ROULETTE_COLORS.get(n, "green")


def parse_roulette_bet(text):
    text = text.lower().strip()
    m = re.match(r'^(\d+)\s+(.+)$', text)
    if not m:
        return None
    amount = int(m.group(1))
    if amount < 100:
        return None
    rest = m.group(2).strip()
    range_match = re.search(r'(\d+)\s*-\s*(\d+)', rest)
    if range_match:
        frm = int(range_match.group(1))
        to = int(range_match.group(2))
        if 0 <= frm <= 36 and 0 <= to <= 36 and frm <= to:
            return {"amount": amount, "type": "range", "from": frm, "to": to, "label": str(frm) + "-" + str(to)}
    if 'красн' in rest or 'red' in rest:
        return {"amount": amount, "type": "red", "label": "красное"}
    if 'черн' in rest or 'black' in rest:
        return {"amount": amount, "type": "black", "label": "чёрное"}
    if 'зелен' in rest or 'green' in rest:
        return {"amount": amount, "type": "green", "label": "зелёное"}
    if 'нечет' in rest or 'odd' in rest:
        return {"amount": amount, "type": "odd", "label": "нечётное"}
    if 'четн' in rest or 'even' in rest:
        return {"amount": amount, "type": "even", "label": "чётное"}
    num_match = re.fullmatch(r'\s*(\d+)\s*', rest)
    if num_match:
        num = int(num_match.group(1))
        if 0 <= num <= 36:
            return {"amount": amount, "type": "number", "number": num, "label": "число " + str(num)}
    return None


def parse_roulette_bets(text):
    bets = []
    for part in re.split(r'[\n,;]+', text):
        part = part.strip()
        if not part:
            continue
        bet = parse_roulette_bet(part)
        if bet:
            bets.append(bet)
    return bets


def get_bet_multiplier(bet, number):
    color = get_roulette_color(number)
    btype = bet["type"]
    if btype == "green":
        return 35 if color == "green" else 0
    if btype == "red":
        return 2 if color == "red" else 0
    if btype == "black":
        return 2 if color == "black" else 0
    if btype == "even":
        return 2 if number != 0 and number % 2 == 0 else 0
    if btype == "odd":
        return 2 if number != 0 and number % 2 != 0 else 0
    if btype == "number":
        return 35 if bet["number"] == number else 0
    if btype == "range":
        if bet["from"] <= number <= bet["to"]:
            size = bet["to"] - bet["from"] + 1
            if size >= 18: return 2
            elif size >= 12: return 3
            elif size >= 6: return 5
            elif size >= 3: return 11
            elif size == 2: return 17
            else: return 35
        return 0
    return 0


def roulette_keyboard():
    return {"inline_keyboard": [
        [{"text": "КРУТИТЬ (Го Рулетка)", "callback_data": "roulette_go"}],
        [{"text": "ОЧИСТИТЬ СТАВКИ", "callback_data": "roulette_clear"}],
        [{"text": "МОИ СТАВКИ", "callback_data": "roulette_my_bets"}],
        [{"text": "НАЗАД", "callback_data": "back"}]]}


def handle_roulette(chat_id, message_id, user_id):
    if not is_roulette_enabled():
        send_message(chat_id, "Рулетка отключена.")
        return
    if rl_is_blocked(user_id):
        send_message(chat_id, "Тебе заблокирован доступ!")
        return
    update_last_active(user_id)
    history = get_roulette_history(7)
    colors = {'red': 'R', 'black': 'B', 'green': 'G'}
    if history:
        ht = "История: " + " ".join([colors.get(c, "?") + str(n) for n, c in history])
    else:
        ht = "История: пусто"
    bets = get_user_bets(user_id)
    balance = get_balance(user_id)
    if bets:
        total = sum(b["amount"] for b in bets)
        bets_text = "Твои ставки (" + str(len(bets)) + "/" + str(MAX_ROULETTE_BETS) + "):\n"
        for b in bets[:15]:
            bets_text += "  " + format(b["amount"], ",") + " → " + b["label"] + "\n"
        if len(bets) > 15:
            bets_text += "  ... и ещё " + str(len(bets) - 15) + "\n"
        bets_text += "\nВсего: " + format(total, ",") + "\nБаланс: " + format(balance, ",")
    else:
        bets_text = "Ставок нет (0/" + str(MAX_ROULETTE_BETS) + ")\n\nБаланс: " + format(balance, ",")
    wins, losses, won_amount, lost_amount = get_title_stats(user_id)
    text = "<b>РУЛЕТКА</b>\n\n" + ht + "\n\n" + bets_text + "\n\nПобед: " + str(wins) + " | Выиграно: " + format(won_amount, ",")
    text += "\n\nСтавки:\n1000 30-36 — диапазон\n500 красное — цвет\n300 17 — число\n200 четное — чёт/нечет"
    text += "\n\nМаксимум: " + str(MAX_ROULETTE_BETS) + "\nЗатем: Го Рулетка\nДЖЕКПОТ: 1% на 100,000,000,000!"
    if message_id:
        edit_message(chat_id, message_id, text, roulette_keyboard())
    else:
        send_message(chat_id, text, roulette_keyboard())


def add_roulette_bet(chat_id, user_id, text):
    update_last_active(user_id)
    if not is_roulette_enabled():
        send_message(chat_id, "Рулетка отключена!")
        return
    if rl_is_blocked(user_id):
        send_message(chat_id, "Тебе заблокирован доступ!")
        return
    bets = parse_roulette_bets(text)
    if not bets:
        send_message(chat_id, "Не понял ставку!\n\nПример: 1000 30-36")
        return
    new_total = sum(b["amount"] for b in bets)
    with ROULETTE_BETS_LOCK:
        try:
            with DB_LOCK:
                with _conn() as conn:
                    c = conn.cursor()
                    c.execute("SELECT COUNT(*) as cnt, COALESCE(SUM(amount),0) as total FROM roulette_bets WHERE user_id = ?", (user_id,))
                    r = c.fetchone()
                    current_count = r["cnt"]
                    existing_total = r["total"]
                    if current_count + len(bets) > MAX_ROULETTE_BETS:
                        send_message(chat_id, "Лимит " + str(MAX_ROULETTE_BETS) + " ставок! У тебя: " + str(current_count))
                        return
                    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                    u = c.fetchone()
                    balance = u["balance"] if u else 0
                    if existing_total + new_total > balance:
                        send_message(chat_id, "Превышен баланс! Баланс: " + format(balance, ","))
                        return
                    for b in bets:
                        c.execute("INSERT INTO roulette_bets (user_id, amount, bet_type, bet_from, bet_to, bet_number, label) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                  (user_id, b["amount"], b["type"], b.get("from"), b.get("to"), b.get("number"), b.get("label", "?")))
                    conn.commit()
        except Exception as e:
            send_message(chat_id, "❌ " + str(e))
            return
    added = "\n".join(["  " + format(b["amount"], ",") + " → " + b["label"] for b in bets])
    total = get_bets_total(user_id)
    total_count = get_bets_count(user_id)
    send_message(chat_id, "Ставка принята!\n\n" + added + "\n\nВсего: " + str(total_count) + "/" + str(MAX_ROULETTE_BETS) + "\nСумма: " + format(total, ",") + "\nБаланс: " + format(balance, ",") + "\n\nНапиши: Го Рулетка", roulette_keyboard())


def clear_roulette_bets(chat_id, user_id):
    clear_bets_db(user_id)
    send_message(chat_id, "Ставки очищены!", roulette_keyboard())


def show_my_bets(chat_id, user_id):
    bets = get_user_bets(user_id)
    if not bets:
        send_message(chat_id, "Ставок нет (0/" + str(MAX_ROULETTE_BETS) + ")", roulette_keyboard())
        return
    total = sum(b["amount"] for b in bets)
    text = "ТВОИ СТАВКИ (" + str(len(bets)) + "/" + str(MAX_ROULETTE_BETS) + ")\n\n"
    for i, b in enumerate(bets, 1):
        text += str(i) + ". " + format(b["amount"], ",") + " → " + b["label"] + "\n"
    text += "\nИтого: " + format(total, ",")
    send_message(chat_id, text, roulette_keyboard())


def go_roulette(chat_id, message_id, user_id):
    if not is_roulette_enabled():
        send_message(chat_id, "Рулетка отключена!")
        return
    if rl_is_blocked(user_id):
        send_message(chat_id, "Тебе заблокирован доступ!")
        return
    with ROULETTE_BETS_LOCK:
        bets = get_user_bets(user_id)
        if not bets:
            send_message(chat_id, "Сначала сделай ставки! Пример: 1000 30-36", roulette_keyboard())
            return
        total_bet = sum(b["amount"] for b in bets)
        rig = rl_consume_rig()
        number = rig if (rig is not None and 0 <= rig <= 36) else random.randint(0, 36)
        color = get_roulette_color(number)
        total_win = 0
        results = []
        for bet in bets:
            mult = get_bet_multiplier(bet, number)
            if mult > 0:
                win = bet["amount"] * mult
                total_win += win
                results.append("WIN " + bet["label"] + " x" + str(mult) + " +" + format(win, ","))
            else:
                results.append("LOSE " + bet["label"] + " -" + format(bet["amount"], ","))
        jackpot_won = False
        with JACKPOT_LOCK:
            try:
                u = get_user(user_id)
                if u and not u["jackpot_won"] and random.random() < JACKPOT_CHANCE:
                    jackpot_won = True
            except Exception:
                pass
        try:
            with DB_LOCK:
                with _conn() as conn:
                    c = conn.cursor()
                    c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?", (total_bet, user_id, total_bet))
                    if c.rowcount == 0:
                        conn.rollback()
                        send_message(chat_id, "Недостаточно средств!")
                        return
                    c.execute("DELETE FROM roulette_bets WHERE user_id = ?", (user_id,))
                    c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)", (user_id, -total_bet, "roulette_bets", "roulette", "stavki"))
                    if total_win > 0:
                        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (total_win, user_id))
                        c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)", (user_id, total_win, "roulette_win", "roulette", "win"))
                    if jackpot_won:
                        c.execute("UPDATE users SET jackpot_won = 1, balance = balance + ? WHERE user_id = ? AND jackpot_won = 0", (JACKPOT_AMOUNT, user_id))
                        if c.rowcount > 0:
                            c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)", (user_id, JACKPOT_AMOUNT, "jackpot", "roulette", "JACKPOT"))
                        else:
                            jackpot_won = False
                    conn.commit()
        except Exception as e:
            send_message(chat_id, "❌ " + str(e))
            return
    add_roulette_result(number, color)
    if jackpot_won:
        update_title_stats(user_id, wins=1, won_amount=JACKPOT_AMOUNT)
        send_message(chat_id, "ДЖЕКПОТ! 100,000,000,000!", roulette_keyboard())
        try:
            send_message(ADMIN_ID, "ДЖЕКПОТ! Игрок: " + str(user_id))
        except Exception:
            pass
        return
    if total_win > 0:
        update_title_stats(user_id, wins=1, won_amount=total_win)
    if total_win < total_bet:
        update_title_stats(user_id, losses=1 if total_win == 0 else 0, lost_amount=total_bet - total_win)
    profit = total_win - total_bet
    sign = "+" if profit > 0 else ""
    msg = "РУЛЕТКА — РЕЗУЛЬТАТ!\n\n"
    msg += "Выпало: " + str(number) + "\n\n"
    msg += "Ставки:\n"
    for r in results[:15]:
        msg += r + "\n"
    msg += "\nПоставлено: " + format(total_bet, ",") + "\n"
    msg += "Выиграно: " + format(total_win, ",") + "\n"
    msg += "Итог: " + sign + format(profit, ",") + "\n\n"
    msg += "Баланс: " + format(get_balance(user_id), ",")
    send_message(chat_id, msg, roulette_keyboard())


# ========== TELEGRAM API ==========
def send_request(url, data, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            json_data = json.dumps(data).encode('utf-8')
            req = urllib.request.Request(url, data=json_data,
                                         headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            last_err = e
            print("⚠️ send_request " + str(attempt + 1) + "/" + str(retries) + ": " + str(e))
            time.sleep(2)
    print("❌ send_request финал: " + str(last_err))
    return None


def send_message(chat_id, text, keyboard=None):
    url = "https://api.telegram.org/bot" + TOKEN + "/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        data["reply_markup"] = json.dumps(keyboard)
    return send_request(url, data)


def edit_message(chat_id, message_id, text, keyboard=None):
    if not message_id:
        return send_message(chat_id, text, keyboard)
    url = "https://api.telegram.org/bot" + TOKEN + "/editMessageText"
    data = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        data["reply_markup"] = json.dumps(keyboard)
    return send_request(url, data)


def answer_callback(callback_id, text=None, show_alert=False):
    url = "https://api.telegram.org/bot" + TOKEN + "/answerCallbackQuery"
    data = {"callback_query_id": callback_id}
    if text:
        data["text"] = text
    if show_alert:
        data["show_alert"] = show_alert
    return send_request(url, data)


def get_updates(offset):
    url = "https://api.telegram.org/bot" + TOKEN + "/getUpdates?offset=" + str(offset) + "&timeout=30"
    try:
        with urllib.request.urlopen(url, timeout=35) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print("❌ get_updates: " + str(e))
        return {"ok": False}


# ========== КЛАВИАТУРЫ ==========
def main_keyboard(user_id=None):
    rows = [
        [{"text": "РУЛЕТКА", "callback_data": "roulette"},
         {"text": "КРАШ", "callback_data": "crash"}],
        [{"text": "БОНУС", "callback_data": "bonus"},
         {"text": "ПРОФИЛЬ", "callback_data": "profile"}],
        [{"text": "ДУЭЛЬ", "callback_data": "duel"},
         {"text": "КАЗНА", "callback_data": "treasury"}],
        [{"text": "ИСТОРИЯ", "callback_data": "history"},
         {"text": "ПЕРЕВОД", "callback_data": "transfer"}],
        [{"text": "КОСТИ", "callback_data": "dice"},
         {"text": "ОБМЕННИК AZ", "callback_data": "az_menu"}],
        [{"text": "КЕЙСЫ", "callback_data": "cases_menu"}],
        [{"text": "ТИТУЛЫ", "callback_data": "titles_menu"}],
    ]
    if user_id == ADMIN_ID:
        rows.append([{"text": "АДМИН-ПАНЕЛЬ", "callback_data": "admin_panel"}])
    return {"inline_keyboard": rows}


def back_keyboard():
    return {"inline_keyboard": [[{"text": "НАЗАД", "callback_data": "back"}]]}


def crash_keyboard():
    return {"inline_keyboard": [
        [{"text": "СТАРТ", "callback_data": "crash_start"}],
        [{"text": "НАЗАД", "callback_data": "back"}]]}


def crash_game_keyboard():
    return {"inline_keyboard": [[{"text": "ЗАБРАТЬ", "callback_data": "crash_cashout"}]]}


def duel_keyboard():
    return {"inline_keyboard": [
        [{"text": "ВЫЗВАТЬ", "callback_data": "duel_challenge"}],
        [{"text": "НАЗАД", "callback_data": "back"}]]}


def treasury_keyboard():
    return {"inline_keyboard": [
        [{"text": "СТАТИСТИКА", "callback_data": "treasury_stats"}],
        [{"text": "НАЗАД", "callback_data": "back"}]]}


def dice_keyboard():
    return {"inline_keyboard": [
        [{"text": "100", "callback_data": "dice_amt_100"},
         {"text": "500", "callback_data": "dice_amt_500"},
         {"text": "1000", "callback_data": "dice_amt_1000"}],
        [{"text": "5000", "callback_data": "dice_amt_5000"},
         {"text": "10000", "callback_data": "dice_amt_10000"},
         {"text": "25000", "callback_data": "dice_amt_25000"}],
        [{"text": "ВСЁ", "callback_data": "dice_amt_all"},
         {"text": "СВОЯ", "callback_data": "dice_amt_custom"},
         {"text": "НАЗАД", "callback_data": "back"}]]}


def dice_choose_number_keyboard():
    return {"inline_keyboard": [
        [{"text": "1", "callback_data": "dice_choose_1"},
         {"text": "2", "callback_data": "dice_choose_2"},
         {"text": "3", "callback_data": "dice_choose_3"}],
        [{"text": "4", "callback_data": "dice_choose_4"},
         {"text": "5", "callback_data": "dice_choose_5"},
         {"text": "6", "callback_data": "dice_choose_6"}],
        [{"text": "НАЗАД", "callback_data": "dice_back_to_amount"}]]}


def az_exchange_keyboard():
    rate = get_az_rate()
    az = get_az_amount()
    return {"inline_keyboard": [
        [{"text": "1x (" + format(rate, ",") + " → " + str(az) + " Az)", "callback_data": "az_ex_1"}],
        [{"text": "5x", "callback_data": "az_ex_5"},
         {"text": "10x", "callback_data": "az_ex_10"}],
        [{"text": "МАКСИМУМ", "callback_data": "az_ex_max"}],
        [{"text": "СВОЁ", "callback_data": "az_ex_custom"}],
        [{"text": "ИСТОРИЯ", "callback_data": "az_history"},
         {"text": "ТОП Az", "callback_data": "az_top"}],
        [{"text": "НАЗАД", "callback_data": "back"}]]}


def cases_keyboard(user_id=None):
    rows = [
        [{"text": "ОБЫЧНЫЙ — 500K", "callback_data": "case_menu_common"}],
        [{"text": "РЕДКИЙ — 10M", "callback_data": "case_menu_rare"}],
        [{"text": "ЛЕГЕНДАРНЫЙ — 100M", "callback_data": "case_menu_legendary"}],
        [{"text": "AZ КЕЙС — 900 Az", "callback_data": "case_menu_az"}],
        [{"text": "ЛИЗИАРД — 50M", "callback_data": "case_menu_lizard"}],
    ]
    if user_id:
        progress, _ = get_special_progress(user_id)
        available = progress // 100
        if available > 0:
            rows.append([{"text": "ОСОБЫЙ — ДОСТУПЕН (" + str(available) + ")", "callback_data": "case_menu_special"}])
        else:
            rows.append([{"text": "ОСОБЫЙ — " + str(progress % 100) + "/100", "callback_data": "case_menu_special"}])
    else:
        rows.append([{"text": "ОСОБЫЙ — за 100 открытий", "callback_data": "case_menu_special"}])
    rows.append([{"text": "СТАТИСТИКА", "callback_data": "case_stats"},
                 {"text": "ТОП", "callback_data": "case_top"}])
    rows.append([{"text": "НАЗАД", "callback_data": "back"}])
    return {"inline_keyboard": rows}


def case_menu_keyboard(case_type, user_id=None):
    case = CASES.get(case_type, {})
    price = case.get("price", 0)
    currency = case.get("currency", "points")
    if case_type == "special":
        progress, _ = get_special_progress(user_id) if user_id else (0, 0)
        available = progress // 100
        rows = []
        if available >= 1:
            rows.append([{"text": "ОТКРЫТЬ 1", "callback_data": "case_open_special_1"}])
        if available >= 5:
            rows.append([{"text": "x5", "callback_data": "case_open_special_5"},
                         {"text": "x10", "callback_data": "case_open_special_10"}])
        if available >= 1:
            rows.append([{"text": "СВОЁ", "callback_data": "case_custom_special"}])
        rows.append([{"text": "НАЗАД", "callback_data": "cases_menu"}])
        return {"inline_keyboard": rows}
    if currency == "az":
        return {"inline_keyboard": [
            [{"text": "ОТКРЫТЬ 1 (" + str(price) + " Az)", "callback_data": "case_open_" + case_type + "_1"}],
            [{"text": "x5 (" + str(price * 5) + " Az)", "callback_data": "case_open_" + case_type + "_5"},
             {"text": "x10 (" + str(price * 10) + " Az)", "callback_data": "case_open_" + case_type + "_10"}],
            [{"text": "СВОЁ", "callback_data": "case_custom_" + case_type}],
            [{"text": "НАЗАД", "callback_data": "cases_menu"}]]}
    return {"inline_keyboard": [
        [{"text": "ОТКРЫТЬ 1 (" + format(price, ",") + ")", "callback_data": "case_open_" + case_type + "_1"}],
        [{"text": "x5", "callback_data": "case_open_" + case_type + "_5"},
         {"text": "x10", "callback_data": "case_open_" + case_type + "_10"},
         {"text": "x50", "callback_data": "case_open_" + case_type + "_50"}],
        [{"text": "СВОЁ", "callback_data": "case_custom_" + case_type}],
        [{"text": "НАЗАД", "callback_data": "cases_menu"}]]}


def titles_menu_keyboard(user_id=None):
    rows = [
        [{"text": "Все титулы", "callback_data": "titles_list"}],
        [{"text": "Мои титулы", "callback_data": "titles_my"}],
    ]
    if user_id == ADMIN_ID:
        rows.append([{"text": "Управление", "callback_data": "admin_titles"}])
    rows.append([{"text": "НАЗАД", "callback_data": "back"}])
    return {"inline_keyboard": rows}


def admin_panel_keyboard():
    az_status = "ON" if is_az_enabled() else "OFF"
    rl_status = "ON" if is_roulette_enabled() else "OFF"
    rig = rl_get_rig()
    rig_label = "Подкрутка: " + str(rig) if rig is not None else "Подкрутить"
    return {"inline_keyboard": [
        [{"text": "ЭКОНОМИКА", "callback_data": "admin_economy"},
         {"text": "РУЛЕТКА", "callback_data": "admin_roulette_menu"}],
        [{"text": "ТИТУЛЫ", "callback_data": "admin_titles"},
         {"text": "ПРОМОКОДЫ", "callback_data": "admin_promo_menu"}],
        [{"text": "ИГРОКИ", "callback_data": "admin_players"},
         {"text": "КАЗНА", "callback_data": "admin_treasury_menu"}],
        [{"text": "Обменник: " + az_status, "callback_data": "admin_toggle_az"}],
        [{"text": "Рулетка: " + rl_status, "callback_data": "admin_toggle_roulette"}],
        [{"text": rig_label, "callback_data": "admin_rl_rig"}],
        [{"text": "Назад", "callback_data": "back"}]]}


def admin_economy_keyboard():
    return {"inline_keyboard": [
        [{"text": "Курс: " + format(get_az_rate(), ",") + " → " + str(get_az_amount()) + " Az", "callback_data": "admin_set_az_rate"}],
        [{"text": "Налог дуэли: " + str(get_tax_percent()) + "%", "callback_data": "admin_set_tax"}],
        [{"text": "ВЫДАТЬ ПОИНТЫ", "callback_data": "admin_give_money"}],
        [{"text": "ТОП ИГРОКОВ", "callback_data": "admin_users_top"}],
        [{"text": "Назад", "callback_data": "admin_panel"}]]}


def admin_roulette_keyboard():
    rl_status = "ВКЛ" if is_roulette_enabled() else "ВЫКЛ"
    rig = rl_get_rig()
    rig_label = "Подкрутка: " + str(rig) if rig is not None else "Подкрутить"
    return {"inline_keyboard": [
        [{"text": rl_status, "callback_data": "admin_toggle_roulette"}],
        [{"text": rig_label, "callback_data": "admin_rl_rig"}],
        [{"text": "Сбросить подкрутку", "callback_data": "admin_rl_reset"}],
        [{"text": "Заблокировать", "callback_data": "admin_rl_block"}],
        [{"text": "Разблокировать", "callback_data": "admin_rl_unblock"}],
        [{"text": "Список блоков", "callback_data": "admin_rl_blocklist"}],
        [{"text": "Статус", "callback_data": "admin_rl_status"}],
        [{"text": "Назад", "callback_data": "admin_panel"}]]}


def admin_promo_keyboard():
    return {"inline_keyboard": [
        [{"text": "СОЗДАТЬ", "callback_data": "admin_promo_create"}],
        [{"text": "СПИСОК", "callback_data": "admin_promo_list"}],
        [{"text": "Вкл/Выкл", "callback_data": "admin_promo_toggle"}],
        [{"text": "УДАЛИТЬ", "callback_data": "admin_promo_delete"}],
        [{"text": "Назад", "callback_data": "admin_panel"}]]}


def admin_players_keyboard():
    return {"inline_keyboard": [
        [{"text": "ВЫДАТЬ ПОИНТЫ", "callback_data": "admin_give_money"}],
        [{"text": "ТОП-10", "callback_data": "admin_users_top"}],
        [{"text": "ПОИСК ИГРОКА", "callback_data": "admin_user_info"}],
        [{"text": "ТИТУЛЫ ИГРОКА", "callback_data": "admin_user_titles"}],
        [{"text": "Назад", "callback_data": "admin_panel"}]]}


def admin_treasury_keyboard():
    return {"inline_keyboard": [
        [{"text": "ПОПОЛНИТЬ", "callback_data": "admin_treasury_add"}],
        [{"text": "ВЫДАТЬ", "callback_data": "admin_treasury_give"}],
        [{"text": "ИСТОРИЯ", "callback_data": "admin_treasury_logs"}],
        [{"text": "СТАТИСТИКА", "callback_data": "admin_treasury_stats"}],
        [{"text": "Назад", "callback_data": "admin_panel"}]]}


def admin_titles_keyboard():
    rows = []
    for key, t in TITLES.items():
        rows.append([{"text": t["name"], "callback_data": "admin_title_info_" + key}])
    rows.append([{"text": "ВЫДАТЬ СТАНДАРТНЫЙ", "callback_data": "admin_title_give"}])
    rows.append([{"text": "ВЫДАТЬ КАСТОМНЫЙ", "callback_data": "admin_title_give_custom"}])
    rows.append([{"text": "СНЯТЬ ТИТУЛ", "callback_data": "admin_title_remove"}])
    rows.append([{"text": "ТИТУЛЫ ИГРОКА", "callback_data": "admin_user_titles"}])
    rows.append([{"text": "Справка", "callback_data": "titles_list"}])
    rows.append([{"text": "Назад", "callback_data": "admin_panel"}])
    return {"inline_keyboard": rows}


# ========== ОБРАБОТЧИКИ ТИТУЛОВ ==========
def handle_titles_menu(chat_id, message_id, user_id):
    titles = get_user_titles(user_id)
    wins, losses, won_amount, lost_amount = get_title_stats(user_id)
    user = get_user(user_id)
    days = 0
    if user and user["registered"]:
        reg = db_parse(user["registered"])
        if reg:
            days = (datetime.now() - reg).days
    mt = "\n".join(["  " + t["name"] for t in titles]) if titles else "  нет"
    text = "ТИТУЛЫ\n\nТвоя статистика:\n"
    text += "Побед: " + str(wins) + "\n"
    text += "Проигрышей: " + str(losses) + "\n"
    text += "Выиграно: " + format(won_amount, ",") + "\n"
    text += "Проиграно: " + format(lost_amount, ",") + "\n"
    text += "Дней: " + str(days) + "\n\n"
    text += "Твои титулы:\n" + mt
    text += "\n\nДоступные:\n"
    text += "Король рулетки — 150 побед\n"
    text += "Легенда рулетки — 250 побед\n"
    text += "Гранд рулетки — 500 побед\n"
    text += "Фиаско — проиграть 150ккк\n"
    text += "Словно Осень — 10 дней\n"
    text += "Фарт — выиграть 300ккк\n"
    text += "Бог игры — от владельца"
    if message_id:
        edit_message(chat_id, message_id, text, titles_menu_keyboard(user_id))
    else:
        send_message(chat_id, text, titles_menu_keyboard(user_id))


def handle_titles_my(chat_id, message_id, user_id):
    titles = get_user_titles(user_id)
    if not titles:
        text = "МОИ ТИТУЛЫ\n\nУ тебя пока нет титулов"
    else:
        text = "МОИ ТИТУЛЫ (" + str(len(titles)) + ")\n\n"
        for i, t in enumerate(titles, 1):
            text += str(i) + ". " + t["name"] + "\n   " + t["condition"] + "\n\n"
    if message_id:
        edit_message(chat_id, message_id, text, titles_menu_keyboard(user_id))
    else:
        send_message(chat_id, text, titles_menu_keyboard(user_id))


def handle_titles_list(chat_id, message_id, user_id):
    text = format_all_titles_list()
    if message_id:
        edit_message(chat_id, message_id, text, titles_menu_keyboard(user_id))
    else:
        send_message(chat_id, text, titles_menu_keyboard(user_id))


def handle_admin_titles(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        send_message(chat_id, "Нет прав!")
        return
    text = "УПРАВЛЕНИЕ ТИТУЛАМИ\n\nВыбирай действие"
    if message_id:
        edit_message(chat_id, message_id, text, admin_titles_keyboard())
    else:
        send_message(chat_id, text, admin_titles_keyboard())


def handle_admin_title_info(chat_id, message_id, user_id, title_key):
    if user_id != ADMIN_ID:
        return
    if title_key not in TITLES:
        send_message(chat_id, "Не найден!")
        return
    t = TITLES[title_key]
    text = t["name"] + "\n\nУсловие: " + t["condition"] + "\nКлюч: " + title_key
    text += "\nТип: " + t["type"] + "\nПорог: " + format(t["threshold"], ",")
    text += "\n\nВыдать: /give_title ID " + title_key
    if message_id:
        edit_message(chat_id, message_id, text, admin_titles_keyboard())
    else:
        send_message(chat_id, text, admin_titles_keyboard())


def handle_admin_title_give(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    user_states[user_id] = {"action": "admin_title_give"}
    text = "ВЫДАТЬ СТАНДАРТНЫЙ\n\nФормат: ID КЛЮЧ\nПример: 123456789 roulette_king\n\nКлючи:\n"
    for k, v in TITLES.items():
        text += "  " + k + " — " + v["name"] + "\n"
    text += "\n/cancel — отмена"
    if message_id:
        edit_message(chat_id, message_id, text, admin_titles_keyboard())
    else:
        send_message(chat_id, text, admin_titles_keyboard())


def process_admin_title_give(chat_id, user_id, text):
    if user_id != ADMIN_ID:
        return
    if user_id in user_states:
        del user_states[user_id]
    try:
        parts = text.strip().split()
        if len(parts) != 2:
            send_message(chat_id, "Формат: ID КЛЮЧ")
            return
        target = int(parts[0])
        title_key = parts[1].lower().strip()
        success, result = award_title(target, title_key, awarded_by=user_id)
        send_message(chat_id, result)
        handle_admin_titles(chat_id, None, user_id)
    except ValueError:
        send_message(chat_id, "ID числом!")


def handle_admin_title_give_custom(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    user_states[user_id] = {"action": "admin_title_give_custom"}
    text = "ВЫДАТЬ КАСТОМНЫЙ\n\nФормат: ID ТЕКСТ\nПример: 123456789 Король чата\n\n/cancel — отмена"
    if message_id:
        edit_message(chat_id, message_id, text, admin_titles_keyboard())
    else:
        send_message(chat_id, text, admin_titles_keyboard())


def process_admin_title_give_custom(chat_id, user_id, text):
    if user_id != ADMIN_ID:
        return
    if user_id in user_states:
        del user_states[user_id]
    try:
        parts = text.strip().split(None, 1)
        if len(parts) < 2:
            send_message(chat_id, "Формат: ID ТЕКСТ")
            return
        target = int(parts[0])
        custom_text = parts[1].strip()
        if len(custom_text) > 50:
            send_message(chat_id, "Максимум 50 символов!")
            return
        success, result = award_title(target, "custom", custom_text=custom_text, awarded_by=user_id)
        send_message(chat_id, result)
        handle_admin_titles(chat_id, None, user_id)
    except ValueError:
        send_message(chat_id, "ID числом!")


def handle_admin_title_remove(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    user_states[user_id] = {"action": "admin_title_remove"}
    text = "СНЯТЬ ТИТУЛ\n\nФормат: ID КЛЮЧ\nПример: 123456789 roulette_king\n\n/cancel — отмена"
    if message_id:
        edit_message(chat_id, message_id, text, admin_titles_keyboard())
    else:
        send_message(chat_id, text, admin_titles_keyboard())


def process_admin_title_remove(chat_id, user_id, text):
    if user_id != ADMIN_ID:
        return
    if user_id in user_states:
        del user_states[user_id]
    try:
        parts = text.strip().split()
        if len(parts) != 2:
            send_message(chat_id, "Формат: ID КЛЮЧ")
            return
        target = int(parts[0])
        title_key = parts[1].strip()
        if remove_title(target, title_key):
            send_message(chat_id, "Титул снят с " + str(target))
        else:
            send_message(chat_id, "Не найден у игрока!")
        handle_admin_titles(chat_id, None, user_id)
    except ValueError:
        send_message(chat_id, "ID!")


def handle_admin_user_titles(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    user_states[user_id] = {"action": "admin_user_titles"}
    text = "ТИТУЛЫ ИГРОКА\n\nОтправь ID игрока.\n\n/cancel — отмена"
    if message_id:
        edit_message(chat_id, message_id, text, admin_titles_keyboard())
    else:
        send_message(chat_id, text, admin_titles_keyboard())


def process_admin_user_titles(chat_id, user_id, text):
    if user_id != ADMIN_ID:
        return
    if user_id in user_states:
        del user_states[user_id]
    try:
        target = int(text.strip())
        titles = get_user_titles(target)
        u = get_user(target)
        name = u["username"] if u and u["username"] else str(target)
        if not titles:
            send_message(chat_id, name + " (" + str(target) + ")\nТитулов нет.", admin_titles_keyboard())
        else:
            txt = name + " (" + str(target) + ")\n\nТитулы (" + str(len(titles)) + "):\n\n"
            for i, t in enumerate(titles, 1):
                txt += str(i) + ". " + t["name"] + "\n   Ключ: " + t["key"] + "\n\n"
            send_message(chat_id, txt, admin_titles_keyboard())
    except ValueError:
        send_message(chat_id, "ID числом!")


# ========== АДМИН ОБРАБОТЧИКИ ==========
def handle_admin_panel(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        send_message(chat_id, "Нет прав!")
        return
    rig = rl_get_rig()
    rig_text = str(rig) if rig is not None else "нет"
    text = "АДМИН-ПАНЕЛЬ\n\n"
    text += "Обменник: " + ("ON" if is_az_enabled() else "OFF") + "\n"
    text += "Курс: " + format(get_az_rate(), ",") + " → " + str(get_az_amount()) + " Az\n"
    text += "Налог: " + str(get_tax_percent()) + "%\n"
    text += "Рулетка: " + ("ВКЛ" if is_roulette_enabled() else "ВЫКЛ") + "\n"
    text += "Подкрутка: " + rig_text + "\n"
    text += "Титулов: " + str(len(TITLES))
    if message_id:
        edit_message(chat_id, message_id, text, admin_panel_keyboard())
    else:
        send_message(chat_id, text, admin_panel_keyboard())


def handle_admin_economy(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    text = "ЭКОНОМИКА\n\n"
    text += "Курс AZ: " + format(get_az_rate(), ",") + " → " + str(get_az_amount()) + " Az\n"
    text += "Налог дуэли: " + str(get_tax_percent()) + "%\n"
    text += "Обменник: " + ("ON" if is_az_enabled() else "OFF")
    if message_id:
        edit_message(chat_id, message_id, text, admin_economy_keyboard())
    else:
        send_message(chat_id, text, admin_economy_keyboard())


def handle_admin_roulette_menu(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    rig = rl_get_rig()
    text = "УПРАВЛЕНИЕ РУЛЕТКОЙ\n\n"
    text += "Статус: " + ("ВКЛ" if is_roulette_enabled() else "ВЫКЛ") + "\n"
    text += "Подкрутка: " + (str(rig) if rig is not None else "нет") + "\n"
    text += "Блокировок: " + str(len(rl_blocklist()))
    if message_id:
        edit_message(chat_id, message_id, text, admin_roulette_keyboard())
    else:
        send_message(chat_id, text, admin_roulette_keyboard())


def handle_admin_promo_menu(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    text = "УПРАВЛЕНИЕ ПРОМОКОДАМИ\n\nВыбирай действие:"
    if message_id:
        edit_message(chat_id, message_id, text, admin_promo_keyboard())
    else:
        send_message(chat_id, text, admin_promo_keyboard())


def handle_admin_players(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    text = "УПРАВЛЕНИЕ ИГРОКАМИ\n\nВыбирай действие:"
    if message_id:
        edit_message(chat_id, message_id, text, admin_players_keyboard())
    else:
        send_message(chat_id, text, admin_players_keyboard())


def handle_admin_treasury_menu(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    text = "УПРАВЛЕНИЕ КАЗНОЙ\n\n"
    text += "Баланс: " + format(get_treasury(CHAT_ID), ",") + "\n"
    text += "Собрано: " + format(get_treasury_total_in(), ",") + "\n"
    text += "Выдано: " + format(get_treasury_total_out(), ",")
    if message_id:
        edit_message(chat_id, message_id, text, admin_treasury_keyboard())
    else:
        send_message(chat_id, text, admin_treasury_keyboard())


def handle_admin_toggle_az(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    current = is_az_enabled()
    set_az_enabled(not current)
    send_message(chat_id, "Обменник " + ("ВКЛ" if not current else "ВЫКЛ"))
    handle_admin_panel(chat_id, message_id, user_id)


def handle_admin_set_az_rate(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    user_states[user_id] = {"action": "admin_set_az_rate"}
    text = "КУРС AZ\n\nТекущий: " + format(get_az_rate(), ",") + " → " + str(get_az_amount()) + " Az\n\n"
    text += "Отправь: ПОИНТЫ AZ\nПример: 1000000 100\n\n/cancel — отмена"
    if message_id:
        edit_message(chat_id, message_id, text, admin_economy_keyboard())
    else:
        send_message(chat_id, text, admin_economy_keyboard())


def process_admin_set_az_rate(chat_id, user_id, text):
    if user_id != ADMIN_ID:
        return
    if user_id in user_states:
        del user_states[user_id]
    try:
        parts = text.strip().split()
        if len(parts) != 2:
            send_message(chat_id, "Формат: ПОИНТЫ AZ")
            return
        rate = int(parts[0])
        az_amt = int(parts[1])
        if rate > 0 and az_amt > 0:
            set_az_rate(rate)
            set_az_amount(az_amt)
            send_message(chat_id, "Курс: " + format(rate, ",") + " → " + str(az_amt) + " Az")
            handle_admin_economy(chat_id, None, user_id)
        else:
            send_message(chat_id, "Числа > 0!")
    except ValueError:
        send_message(chat_id, "Формат: ПОИНТЫ AZ")


def handle_admin_toggle_roulette(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    current = is_roulette_enabled()
    set_roulette_enabled(not current)
    send_message(chat_id, "Рулетка " + ("ВКЛ" if not current else "ВЫКЛ"))
    handle_admin_panel(chat_id, message_id, user_id)


def handle_admin_rl_rig(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    user_states[user_id] = {"action": "admin_rl_rig"}
    rig = rl_get_rig()
    text = "ПОДКРУТКА РУЛЕТКИ\n\nТекущая: " + (str(rig) if rig is not None else "нет") + "\n\n"
    text += "Отправь число 0-36 или reset.\n\n/cancel — отмена"
    if message_id:
        edit_message(chat_id, message_id, text, admin_roulette_keyboard())
    else:
        send_message(chat_id, text, admin_roulette_keyboard())


def process_admin_rl_rig(chat_id, user_id, text):
    if user_id != ADMIN_ID:
        return
    if user_id in user_states:
        del user_states[user_id]
    t = text.strip().lower()
    if t == "reset":
        rl_set_rig(None)
        send_message(chat_id, "Подкрутка сброшена")
        handle_admin_roulette_menu(chat_id, None, user_id)
        return
    try:
        n = int(t)
        if n < 0 or n > 36:
            send_message(chat_id, "Число 0-36!")
            return
        rl_set_rig(n)
        send_message(chat_id, "Следующее выпадение: " + str(n))
        handle_admin_roulette_menu(chat_id, None, user_id)
    except ValueError:
        send_message(chat_id, "Число или reset!")


def handle_admin_rl_reset(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    rl_set_rig(None)
    send_message(chat_id, "Подкрутка сброшена")
    handle_admin_roulette_menu(chat_id, message_id, user_id)


def handle_admin_rl_block(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    user_states[user_id] = {"action": "admin_rl_block"}
    text = "БЛОКИРОВКА\n\nОтправь ID игрока.\n\n/cancel — отмена"
    if message_id:
        edit_message(chat_id, message_id, text, admin_roulette_keyboard())
    else:
        send_message(chat_id, text, admin_roulette_keyboard())


def process_admin_rl_block(chat_id, user_id, text):
    if user_id != ADMIN_ID:
        return
    if user_id in user_states:
        del user_states[user_id]
    try:
        target = int(text.strip())
        if rl_block_user(target):
            send_message(chat_id, str(target) + " заблокирован")
        else:
            send_message(chat_id, "Ошибка!")
        handle_admin_roulette_menu(chat_id, None, user_id)
    except ValueError:
        send_message(chat_id, "ID числом!")


def handle_admin_rl_unblock(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    user_states[user_id] = {"action": "admin_rl_unblock"}
    text = "РАЗБЛОКИРОВКА\n\nОтправь ID игрока.\n\n/cancel — отмена"
    if message_id:
        edit_message(chat_id, message_id, text, admin_roulette_keyboard())
    else:
        send_message(chat_id, text, admin_roulette_keyboard())


def process_admin_rl_unblock(chat_id, user_id, text):
    if user_id != ADMIN_ID:
        return
    if user_id in user_states:
        del user_states[user_id]
    try:
        target = int(text.strip())
        if rl_unblock_user(target):
            send_message(chat_id, str(target) + " разблокирован")
        else:
            send_message(chat_id, "Не был заблокирован!")
        handle_admin_roulette_menu(chat_id, None, user_id)
    except ValueError:
        send_message(chat_id, "ID числом!")


def handle_admin_rl_blocklist(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    lst = rl_blocklist()
    if not lst:
        text = "СПИСОК БЛОКОВ\n\nПусто."
    else:
        text = "СПИСОК БЛОКОВ\n\n"
        for uid, ts in lst:
            u = get_user(uid)
            name = u["username"] if u and u["username"] else "?"
            text += str(uid) + " | " + str(name) + " | " + str(ts)[:16] + "\n"
        text += "\nВсего: " + str(len(lst))
    if message_id:
        edit_message(chat_id, message_id, text, admin_roulette_keyboard())
    else:
        send_message(chat_id, text, admin_roulette_keyboard())


def handle_admin_rl_status(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    rig = rl_get_rig()
    text = "СТАТУС РУЛЕТКИ\n\n"
    text += "Статус: " + ("ВКЛ" if is_roulette_enabled() else "ВЫКЛ") + "\n"
    text += "Подкрутка: " + (str(rig) if rig is not None else "нет") + "\n"
    text += "Заблокировано: " + str(len(rl_blocklist()))
    if message_id:
        edit_message(chat_id, message_id, text, admin_roulette_keyboard())
    else:
        send_message(chat_id, text, admin_roulette_keyboard())


# ========== АДМИН ОБРАБОТЧИКИ 2 ==========
def handle_promo_create(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    user_states[user_id] = {"action": "admin_promo_create"}
    text = "СОЗДАНИЕ ПРОМОКОДА\n\nКОД | НАГРАДА | ЛИМИТ\n\nПример: SUMMER | 100000 | 50\n\n/cancel — отмена"
    if message_id:
        edit_message(chat_id, message_id, text, admin_promo_keyboard())
    else:
        send_message(chat_id, text, admin_promo_keyboard())


def process_promo_create(chat_id, user_id, text):
    if user_id != ADMIN_ID:
        return
    if user_id in user_states:
        del user_states[user_id]
    try:
        parts = text.split('|')
        if len(parts) < 2:
            send_message(chat_id, "КОД | НАГРАДА | ЛИМИТ")
            return
        code = parts[0].strip().upper()
        reward = int(parts[1].strip())
        max_uses = int(parts[2].strip()) if len(parts) > 2 else 1
        if not code or reward < 100:
            send_message(chat_id, "Ошибка!")
            return
        success, result = create_promocode(code, reward, max_uses)
        send_message(chat_id, result)
        if success:
            handle_admin_promo_menu(chat_id, None, user_id)
    except ValueError:
        send_message(chat_id, "Числа!")


def handle_promo_list(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    promocodes = get_all_promocodes()
    if not promocodes:
        text = "ПРОМОКОДЫ\n\nПусто."
    else:
        text = "ПРОМОКОДЫ\n\n"
        for code, reward, max_uses, used_count, expires_at, is_active in promocodes[:15]:
            status = "ON" if is_active else "OFF"
            text += status + " " + str(code) + " | " + format(reward, ",") + " | " + str(used_count) + "/" + str(max_uses) + "\n"
    if message_id:
        edit_message(chat_id, message_id, text, admin_promo_keyboard())
    else:
        send_message(chat_id, text, admin_promo_keyboard())


def handle_admin_promo_toggle(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    user_states[user_id] = {"action": "admin_promo_toggle"}
    text = "ВКЛ/ВЫКЛ ПРОМОКОД\n\nОтправь код.\n\n/cancel — отмена"
    if message_id:
        edit_message(chat_id, message_id, text, admin_promo_keyboard())
    else:
        send_message(chat_id, text, admin_promo_keyboard())


def process_admin_promo_toggle(chat_id, user_id, text):
    if user_id != ADMIN_ID:
        return
    if user_id in user_states:
        del user_states[user_id]
    success, result = toggle_promocode(text.strip())
    send_message(chat_id, result)
    handle_admin_promo_menu(chat_id, None, user_id)


def handle_admin_promo_delete(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    user_states[user_id] = {"action": "admin_promo_delete"}
    text = "УДАЛИТЬ ПРОМОКОД\n\nОтправь код.\n\n/cancel — отмена"
    if message_id:
        edit_message(chat_id, message_id, text, admin_promo_keyboard())
    else:
        send_message(chat_id, text, admin_promo_keyboard())


def process_admin_promo_delete(chat_id, user_id, text):
    if user_id != ADMIN_ID:
        return
    if user_id in user_states:
        del user_states[user_id]
    if delete_promocode(text.strip()):
        send_message(chat_id, "Удалён!")
    else:
        send_message(chat_id, "Не найден!")
    handle_admin_promo_menu(chat_id, None, user_id)


def handle_admin_give_money(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    user_states[user_id] = {"action": "admin_give_money"}
    text = "ВЫДАТЬ ПОИНТЫ\n\nФормат: ID СУММА или @username СУММА\nПример: 123456789 5000\n\n/cancel — отмена"
    if message_id:
        edit_message(chat_id, message_id, text, admin_economy_keyboard())
    else:
        send_message(chat_id, text, admin_economy_keyboard())


def process_admin_give_money(chat_id, user_id, text):
    if user_id != ADMIN_ID:
        return
    if user_id in user_states:
        del user_states[user_id]
    parts = text.strip().split()
    if len(parts) != 2:
        send_message(chat_id, "Формат: ID СУММА")
        return
    target_id = None
    if parts[0].startswith('@'):
        target_id = get_user_id_by_username(parts[0][1:])
        if not target_id:
            send_message(chat_id, "@username не найден!")
            return
    else:
        try:
            target_id = int(parts[0])
        except ValueError:
            send_message(chat_id, "ID числом!")
            return
    try:
        amount = int(parts[1])
    except ValueError:
        send_message(chat_id, "Сумма числом!")
        return
    give_money(chat_id, user_id, target_id, amount)
    handle_admin_economy(chat_id, None, user_id)


def handle_admin_users_top(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT 10")
                users = c.fetchall()
        if not users:
            text = "ТОП-10\n\nПусто."
        else:
            text = "ТОП-10 ПО БАЛАНСУ\n\n"
            for i, u in enumerate(users, 1):
                text += str(i) + ". " + str(u["username"]) + " (" + str(u["user_id"]) + ")\n   " + format(u["balance"], ",") + "\n\n"
        kb = admin_economy_keyboard() if message_id else admin_players_keyboard()
        if message_id:
            edit_message(chat_id, message_id, text, kb)
        else:
            send_message(chat_id, text, kb)
    except Exception as e:
        send_message(chat_id, "❌ " + str(e))


def handle_admin_set_tax(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    user_states[user_id] = {"action": "admin_set_tax"}
    text = "НАЛОГ ДУЭЛИ\n\nТекущий: " + str(get_tax_percent()) + "%\n\nОтправь 0-100.\n\n/cancel"
    if message_id:
        edit_message(chat_id, message_id, text, admin_economy_keyboard())
    else:
        send_message(chat_id, text, admin_economy_keyboard())


def process_admin_set_tax(chat_id, user_id, text):
    if user_id != ADMIN_ID:
        return
    if user_id in user_states:
        del user_states[user_id]
    try:
        n = int(text.strip())
        success, result = set_tax_percent(n)
        send_message(chat_id, result)
        handle_admin_economy(chat_id, None, user_id)
    except ValueError:
        send_message(chat_id, "Число 0-100!")


def handle_admin_user_info(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    user_states[user_id] = {"action": "admin_user_info"}
    text = "ПОИСК ИГРОКА\n\nОтправь ID или @username.\n\n/cancel"
    if message_id:
        edit_message(chat_id, message_id, text, admin_players_keyboard())
    else:
        send_message(chat_id, text, admin_players_keyboard())


def process_admin_user_info(chat_id, user_id, text):
    if user_id != ADMIN_ID:
        return
    if user_id in user_states:
        del user_states[user_id]
    t = text.strip()
    target_id = None
    if t.startswith('@'):
        target_id = get_user_id_by_username(t[1:])
        if not target_id:
            send_message(chat_id, "Не найден!")
            return
    else:
        try:
            target_id = int(t)
        except ValueError:
            send_message(chat_id, "ID или @username!")
            return
    u = get_user(target_id)
    if not u:
        send_message(chat_id, "Игрок не найден!")
        return
    wins, losses, won_amount, lost_amount = get_title_stats(target_id)
    titles = get_user_titles(target_id)
    az = get_az_balance(target_id)
    titles_text = ", ".join([t["name"] for t in titles]) if titles else "нет"
    txt = "ПРОФИЛЬ\n\n"
    txt += "ID: " + str(target_id) + "\n"
    txt += "Имя: " + str(u["username"]) + "\n"
    txt += "Баланс: " + format(u["balance"], ",") + "\n"
    txt += "Az: " + str(az) + "\n"
    txt += "Рег: " + str(u["registered"])[:16] + "\n\n"
    txt += "Побед: " + str(wins) + "\n"
    txt += "Выиграно: " + format(won_amount, ",") + "\n"
    txt += "Проиграно: " + format(lost_amount, ",") + "\n\n"
    txt += "Титулы: " + titles_text
    send_message(chat_id, txt, admin_players_keyboard())


def handle_admin_treasury_add(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    user_states[user_id] = {"action": "admin_treasury_add"}
    text = "ПОПОЛНИТЬ КАЗНУ\n\nФормат: СУММА ПРИЧИНА\nПример: 1000000 Ивент\n\n/cancel"
    if message_id:
        edit_message(chat_id, message_id, text, admin_treasury_keyboard())
    else:
        send_message(chat_id, text, admin_treasury_keyboard())


def process_admin_treasury_add(chat_id, user_id, text):
    if user_id != ADMIN_ID:
        return
    if user_id in user_states:
        del user_states[user_id]
    try:
        parts = text.strip().split(None, 1)
        amount = int(parts[0])
        reason = parts[1] if len(parts) > 1 else "Пополнение"
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("INSERT OR IGNORE INTO treasury (chat_id, balance) VALUES (?, 0)", (CHAT_ID,))
                c.execute("UPDATE treasury SET balance = balance + ?, last_updated = ? WHERE chat_id = ?",
                          (amount, db_now(), CHAT_ID))
                c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                          (ADMIN_ID, amount, "treasury_admin_add", "treasury", reason))
                conn.commit()
        send_message(chat_id, "+" + format(amount, ",") + " в казну. Баланс: " + format(get_treasury(CHAT_ID), ","))
        handle_admin_treasury_menu(chat_id, None, user_id)
    except (ValueError, IndexError):
        send_message(chat_id, "Формат: СУММА ПРИЧИНА")


def handle_admin_treasury_give(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    user_states[user_id] = {"action": "admin_treasury_give"}
    text = "ВЫДАТЬ ИЗ КАЗНЫ\n\nФормат: ID СУММА [ПРИЧИНА]\n\n/cancel"
    if message_id:
        edit_message(chat_id, message_id, text, admin_treasury_keyboard())
    else:
        send_message(chat_id, text, admin_treasury_keyboard())


def process_admin_treasury_give(chat_id, user_id, text):
    if user_id != ADMIN_ID:
        return
    if user_id in user_states:
        del user_states[user_id]
    try:
        parts = text.strip().split(None, 2)
        if len(parts) < 2:
            send_message(chat_id, "Формат: ID СУММА [ПРИЧИНА]")
            return
        target_id = int(parts[0])
        amount = int(parts[1])
        reason = parts[2] if len(parts) > 2 else "Без причины"
        success, result = treasury_withdraw(CHAT_ID, target_id, amount, reason)
        send_message(chat_id, result)
        handle_admin_treasury_menu(chat_id, None, user_id)
    except ValueError:
        send_message(chat_id, "ID и сумма числами!")


def handle_admin_treasury_logs(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    logs = get_treasury_logs(10)
    if not logs:
        text = "ИСТОРИЯ КАЗНЫ\n\nПусто."
    else:
        text = "ИСТОРИЯ КАЗНЫ (10)\n\n"
        for amount, type_, details, timestamp in logs:
            text += str(amount) + " | " + str(type_) + "\n"
    if message_id:
        edit_message(chat_id, message_id, text, admin_treasury_keyboard())
    else:
        send_message(chat_id, text, admin_treasury_keyboard())


def handle_admin_treasury_stats(chat_id, message_id, user_id):
    if user_id != ADMIN_ID:
        return
    text = "СТАТИСТИКА КАЗНЫ\n\n"
    text += "Баланс: " + format(get_treasury(CHAT_ID), ",") + "\n"
    text += "Собрано: " + format(get_treasury_total_in(), ",") + "\n"
    text += "Выдано: " + format(get_treasury_total_out(), ",") + "\n"
    text += "Налог: " + str(get_tax_percent()) + "%"
    if message_id:
        edit_message(chat_id, message_id, text, admin_treasury_keyboard())
    else:
        send_message(chat_id, text, admin_treasury_keyboard())


def give_money(chat_id, admin_id, target_id, amount):
    if admin_id != ADMIN_ID:
        send_message(chat_id, "Нет прав!")
        return
    if amount < 1:
        send_message(chat_id, "Сумма > 0!")
        return
    target = get_or_create_user(target_id)
    if not target:
        send_message(chat_id, "Не удалось создать " + str(target_id))
        return
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
                c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                          (target_id, amount, "admin_give", "admin", "От админа " + str(admin_id)))
                c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                          (admin_id, 0, "admin_give_log", "admin", "→ " + str(target_id) + " +" + str(amount)))
                conn.commit()
    except Exception as e:
        send_message(chat_id, "❌ " + str(e))
        return
    name = target["username"] if target["username"] else str(target_id)
    new_balance = get_balance(target_id)
    send_message(chat_id, "Выдано " + format(amount, ",") + " → " + str(name) + " (" + str(target_id) + ")\nБаланс: " + format(new_balance, ","))
    try:
        send_message(target_id, "+" + format(amount, ",") + " от админа\nБаланс: " + format(new_balance, ","))
    except Exception:
        pass


# ========== ОБРАБОТЧИКИ КЕЙСОВ ==========
def handle_cases_menu(chat_id, message_id, user_id):
    get_or_create_user(user_id)
    balance = get_balance(user_id)
    az_balance = get_az_balance(user_id)
    stats = get_case_stats(user_id)
    progress, used = get_special_progress(user_id)
    available_special = progress // 100
    sign = "+" if stats["total_profit"] > 0 else ""
    text = "КЕЙСЫ\n\n"
    text += "Поинты: " + format(balance, ",") + "\n"
    text += "Az: " + str(az_balance) + "\n\n"
    text += "Статистика:\n"
    text += "Открыто: " + str(stats["total_opens"]) + "\n"
    text += "Потрачено: " + format(stats["total_spent"], ",") + "\n"
    text += "Выиграно: " + format(stats["total_won"], ",") + "\n"
    text += "Профит: " + sign + format(stats["total_profit"], ",") + "\n\n"
    text += "Особый прогресс: " + str(progress % 100) + "/100\n"
    if available_special > 0:
        text += "ДОСТУПНО ОСОБЫХ: " + str(available_special) + "\n"
    text += "\nОБЫЧНЫЙ — 500K\nРЕДКИЙ — 10M\nЛЕГЕНДАРНЫЙ — 100M\nAZ КЕЙС — 900 Az\nЛИЗИАРД — 50M\nОСОБЫЙ — 100 открытий"
    if message_id:
        edit_message(chat_id, message_id, text, cases_keyboard(user_id))
    else:
        send_message(chat_id, text, cases_keyboard(user_id))


def handle_case_menu(chat_id, message_id, user_id, case_type):
    case = CASES.get(case_type)
    if not case:
        send_message(chat_id, "Кейс не найден!")
        return
    balance = get_balance(user_id)
    az_balance = get_az_balance(user_id)
    currency = case.get("currency", "points")
    if case_type == "special":
        progress, used = get_special_progress(user_id)
        available = progress // 100
        status = "Доступно: " + str(available)
    elif currency == "az":
        price = case["price"]
        max_count = az_balance // price if price > 0 else 0
        status = "Цена: " + str(price) + " Az\nУ тебя: " + str(az_balance) + " Az\nМожешь: " + str(min(max_count, 50))
    else:
        price = case["price"]
        max_count = balance // price if price > 0 else 0
        status = "Цена: " + format(price, ",") + "\nБаланс: " + format(balance, ",") + "\nМожешь: " + str(min(max_count, 100))
    prizes = ""
    for r in case["rewards"]:
        prizes += str(r["amount"]) + " — " + str(r["chance"]) + "%\n"
    text = case["name"] + "\n\n" + status + "\n\nПризы:\n" + prizes
    if message_id:
        edit_message(chat_id, message_id, text, case_menu_keyboard(case_type, user_id))
    else:
        send_message(chat_id, text, case_menu_keyboard(case_type, user_id))


def handle_case_open(chat_id, message_id, user_id, case_type, count):
    open_cases_batch(chat_id, message_id, user_id, case_type, count)


def handle_case_custom(chat_id, message_id, user_id, case_type):
    case = CASES.get(case_type)
    if not case:
        return
    currency = case.get("currency", "points")
    if case_type == "special":
        progress, _ = get_special_progress(user_id)
        max_count = progress // 100
        if max_count < 1:
            send_message(chat_id, "Нет доступных!")
            return
        user_states[user_id] = {"action": "case_custom", "case_type": case_type}
        text = "КОЛИЧЕСТВО\n\nОсобых: " + str(max_count) + "\n\nНапиши число (1-" + str(max_count) + "):\n/cancel"
    elif currency == "az":
        az_balance = get_az_balance(user_id)
        max_count = min(az_balance // case["price"], 50)
        if max_count < 1:
            send_message(chat_id, "Мало Az Coins!")
            return
        user_states[user_id] = {"action": "case_custom", "case_type": case_type}
        text = "КОЛИЧЕСТВО\n\nAz: " + str(az_balance) + "\nЦена: " + str(case["price"]) + " Az\nМакс: " + str(max_count) + "\n\nНапиши (1-" + str(max_count) + "):\n/cancel"
    else:
        balance = get_balance(user_id)
        max_count = min(balance // case["price"], 100)
        if max_count < 1:
            send_message(chat_id, "Мало поинтов!")
            return
        user_states[user_id] = {"action": "case_custom", "case_type": case_type}
        text = "КОЛИЧЕСТВО\n\nБаланс: " + format(balance, ",") + "\nЦена: " + format(case["price"], ",") + "\nМакс: " + str(max_count) + "\n\nНапиши (1-" + str(max_count) + "):\n/cancel"
    edit_message(chat_id, message_id, text, back_keyboard())


def process_case_custom(chat_id, user_id, text):
    if user_id not in user_states:
        return
    state = user_states[user_id]
    if state.get("action") != "case_custom":
        return
    case_type = state.get("case_type")
    case = CASES.get(case_type)
    try:
        count = int(text.strip())
        max_limit = 50 if (case and case.get("currency") == "az") else 100
        if count < 1 or count > max_limit:
            send_message(chat_id, "Число от 1 до " + str(max_limit) + "!")
            return
        if case:
            currency = case.get("currency", "points")
            if case_type == "special":
                progress, _ = get_special_progress(user_id)
                available = progress // 100
                if count > available:
                    send_message(chat_id, "Доступно только " + str(available) + "!")
                    return
            elif currency == "az":
                if get_az_balance(user_id) < case["price"] * count:
                    send_message(chat_id, "Мало Az!")
                    return
            else:
                if get_balance(user_id) < case["price"] * count:
                    send_message(chat_id, "Мало поинтов!")
                    return
        if user_id in user_states:
            del user_states[user_id]
        handle_case_open(chat_id, None, user_id, case_type, count)
    except ValueError:
        send_message(chat_id, "Введи число!")


def handle_case_stats(chat_id, message_id, user_id):
    stats = get_case_stats(user_id)
    progress, used = get_special_progress(user_id)
    if stats["total_opens"] == 0:
        text = "СТАТИСТИКА\n\nПусто."
    else:
        sign = "+" if stats["total_profit"] > 0 else ""
        text = "СТАТИСТИКА КЕЙСОВ\n\n"
        text += "Открыто: " + str(stats["total_opens"]) + "\n"
        text += "Потрачено: " + format(stats["total_spent"], ",") + "\n"
        text += "Выиграно: " + format(stats["total_won"], ",") + "\n"
        text += "Профит: " + sign + format(stats["total_profit"], ",") + "\n\n"
        for row in stats["by_type"]:
            case_type, opens, spent, won, best = row
            opens = opens or 0
            spent = spent or 0
            won = won or 0
            best = best or 0
            case_name = CASES.get(case_type, {}).get("name", case_type)
            profit = won - spent
            s = "+" if profit > 0 else ""
            text += case_name + "\n"
            text += "  Открыто: " + str(opens) + "\n"
            text += "  Потрачено: " + format(spent, ",") + "\n"
            text += "  Выиграно: " + format(won, ",") + "\n"
            text += "  Профит: " + s + format(profit, ",") + "\n"
            text += "  Лучший: " + format(best, ",") + "\n\n"
        text += "Особый: " + str(progress % 100) + "/100 (исп " + str(used) + ")"
    if message_id:
        edit_message(chat_id, message_id, text, cases_keyboard(user_id))
    else:
        send_message(chat_id, text, cases_keyboard(user_id))


def handle_case_top(chat_id, message_id, user_id):
    top = get_case_top(10)
    if not top:
        text = "ТОП\n\nПусто."
    else:
        text = "ТОП ПО КЕЙСАМ\n\n"
        for i, row in enumerate(top, 1):
            uid, profit, opens = row
            profit = profit or 0
            opens = opens or 0
            user = get_user(uid)
            name = user["username"] if user and user["username"] else str(uid)
            s = "+" if profit > 0 else ""
            text += str(i) + ". " + str(name) + "\n   " + str(opens) + " | " + s + format(profit, ",") + "\n\n"
    stats = get_case_stats(user_id)
    text += "\nТвой профит: " + format(stats["total_profit"], ",")
    if message_id:
        edit_message(chat_id, message_id, text, cases_keyboard(user_id))
    else:
        send_message(chat_id, text, cases_keyboard(user_id))


# ========== ПРОФИЛЬ / БОНУС / ПЕРЕВОД ==========
def handle_profile(chat_id, message_id, user_id):
    user = get_or_create_user(user_id)
    if not user:
        send_message(chat_id, "Напиши /start")
        return
    invite_count = get_invite_count(user_id)
    az_balance = get_az_balance(user_id)
    stats = get_case_stats(user_id)
    progress, _ = get_special_progress(user_id)
    titles_text = format_titles_for_profile(user_id)
    sign = "+" if stats["total_profit"] > 0 else ""
    reg_date = str(user["registered"])[:16] if user["registered"] else "?"
    username = user["username"] or str(user_id)
    balance = user["balance"] or 0
    text = "ПРОФИЛЬ\n\n"
    text += "ID: " + str(user_id) + "\n"
    text += "Имя: " + str(username) + "\n"
    text += "Поинты: " + format(balance, ",") + "\n"
    text += "Az: " + str(az_balance) + "\n"
    text += "Рег: " + reg_date + "\n"
    text += "Приглашений: " + str(invite_count) + "\n\n"
    text += titles_text + "\n\n"
    text += "Кейсы:\n"
    text += "Открыто: " + str(stats["total_opens"]) + "\n"
    text += "Профит: " + sign + format(stats["total_profit"], ",") + "\n"
    text += "Прогресс: " + str(progress % 100) + "/100\n\n"
    text += "Казна: " + format(get_treasury(CHAT_ID), ",")
    if message_id:
        edit_message(chat_id, message_id, text, back_keyboard())
    else:
        send_message(chat_id, text, back_keyboard())


def handle_bonus(chat_id, message_id, user_id):
    get_or_create_user(user_id)
    threshold = (datetime.now() - timedelta(hours=3)).strftime(DB_DATE_FMT)
    now_str = db_now()
    got = False
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("UPDATE users SET balance = balance + 1500000, last_bonus = ? WHERE user_id = ? AND (last_bonus IS NULL OR last_bonus <= ?)",
                          (now_str, user_id, threshold))
                if c.rowcount == 0:
                    conn.rollback()
                else:
                    conn.commit()
                    got = True
    except Exception as e:
        send_message(chat_id, "❌ " + str(e))
        return
    if got:
        add_transaction(user_id, 1500000, "bonus")
        text = "БОНУС!\n\n+1,500,000\nБаланс: " + format(get_balance(user_id), ",")
    else:
        last_bonus = get_last_bonus(user_id)
        if last_bonus is None:
            text = "БОНУС ДОСТУПЕН! Нажми ещё раз."
        else:
            remaining = timedelta(hours=3) - (datetime.now() - last_bonus)
            total_sec = max(0, int(remaining.total_seconds()))
            h = total_sec // 3600
            m = (total_sec % 3600) // 60
            text = "ЖДИ " + str(h) + "ч " + str(m) + "мин"
    if message_id:
        edit_message(chat_id, message_id, text, back_keyboard())
    else:
        send_message(chat_id, text, back_keyboard())


def handle_transfer(chat_id, message_id, user_id):
    text = "ПЕРЕВОД\n\n"
    text += "1) Ответь на сообщение игрока и напиши:\n   /transfer СУММА\n\n"
    text += "2) Или по ID:\n   /transfer ID СУММА"
    if message_id:
        edit_message(chat_id, message_id, text, back_keyboard())
    else:
        send_message(chat_id, text, back_keyboard())


def process_transfer(chat_id, user_id, args):
    try:
        if len(args) != 2:
            send_message(chat_id, "/transfer ID Сумма")
            return
        target_id = int(args[0])
        amount = int(args[1])
        if amount < 100:
            send_message(chat_id, "Минимум 100!")
            return
        if target_id == user_id:
            send_message(chat_id, "Нельзя себе!")
            return
        target = get_or_create_user(target_id)
        if not target:
            send_message(chat_id, "Ошибка создания!")
            return
        try:
            with DB_LOCK:
                with _conn() as conn:
                    c = conn.cursor()
                    c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                              (amount, user_id, amount))
                    if c.rowcount == 0:
                        conn.rollback()
                        send_message(chat_id, "Недостаточно!")
                        return
                    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
                    c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                              (user_id, -amount, "transfer_out", "transfer", "→ " + str(target_id)))
                    c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                              (target_id, amount, "transfer_in", "transfer", "← " + str(user_id)))
                    conn.commit()
        except Exception as e:
            send_message(chat_id, "❌ " + str(e))
            return
        send_message(chat_id, format(amount, ",") + " → " + str(target["username"]))
        try:
            send_message(target_id, "+" + format(amount, ",") + " от " + str(user_id))
        except Exception:
            pass
    except ValueError:
        send_message(chat_id, "/transfer ID Сумма")


def process_transfer_reply(chat_id, user_id, reply_to_user_id, reply_to_name, amount):
    if amount < 100:
        send_message(chat_id, "Минимум 100!")
        return
    if reply_to_user_id == user_id:
        send_message(chat_id, "Нельзя себе!")
        return
    target = get_or_create_user(reply_to_user_id, reply_to_name)
    if not target:
        send_message(chat_id, "Ошибка!")
        return
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                          (amount, user_id, amount))
                if c.rowcount == 0:
                    conn.rollback()
                    send_message(chat_id, "Недостаточно!")
                    return
                c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, reply_to_user_id))
                c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                          (user_id, -amount, "transfer_out", "transfer", "→ " + str(reply_to_user_id)))
                c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                          (reply_to_user_id, amount, "transfer_in", "transfer", "← " + str(user_id)))
                conn.commit()
    except Exception as e:
        send_message(chat_id, "❌ " + str(e))
        return
    name = target["username"] if target["username"] else str(reply_to_user_id)
    send_message(chat_id, "Переведено " + format(amount, ",") + " → " + str(name))
    try:
        send_message(reply_to_user_id, "+" + format(amount, ",") + " от " + str(user_id))
    except Exception:
        pass


def handle_history(chat_id, message_id, user_id):
    text = "ИСТОРИЯ\n\nПока пусто."
    if message_id:
        edit_message(chat_id, message_id, text, back_keyboard())
    else:
        send_message(chat_id, text, back_keyboard())


# ========== ДУЭЛИ / КАЗНА / START ==========
def handle_duel(chat_id, message_id, user_id):
    duel = get_active_duel(user_id)
    duel_text = ("Дуэль #" + str(duel[0]) + "\nСтавка: " + format(duel[3], ",")) if duel else "Нет активных"
    text = "ДУЭЛИ\n\nВызвать: /duel @username 1000\nПринять: /accept ID\n\n"
    text += "Налог: " + str(get_tax_percent()) + "%\n\n" + duel_text
    if message_id:
        edit_message(chat_id, message_id, text, duel_keyboard())
    else:
        send_message(chat_id, text, duel_keyboard())


def process_duel_command(chat_id, user_id, args):
    if len(args) != 2:
        send_message(chat_id, "/duel @username Сумма")
        return
    try:
        opp_input = args[0]
        if opp_input.startswith('@'):
            opponent_id = get_user_id_by_username(opp_input[1:])
            if not opponent_id:
                send_message(chat_id, "Не найден!")
                return
        else:
            opponent_id = int(opp_input)
        amount = int(args[1])
        if amount < 100:
            send_message(chat_id, "Минимум 100!")
            return
        success, result = create_duel(user_id, opponent_id, amount, chat_id)
        if not success:
            send_message(chat_id, result)
            return
        send_message(chat_id, "ВЫЗОВ!\n\n/accept " + str(result))
        try:
            send_message(opponent_id, "ВЫЗОВ!\n\n/accept " + str(result))
        except Exception:
            pass
    except ValueError:
        send_message(chat_id, "Формат!")


def process_accept_command(chat_id, user_id, args):
    if len(args) != 1:
        send_message(chat_id, "/accept ID")
        return
    try:
        duel_id = int(args[0])
        success, result = accept_duel(duel_id, user_id, chat_id)
        send_message(chat_id, result)
    except ValueError:
        send_message(chat_id, "ID!")


def handle_treasury(chat_id, message_id, user_id):
    treasury = get_treasury(CHAT_ID)
    text = "КАЗНА\n\n"
    text += "Баланс: " + format(treasury, ",") + "\n"
    text += "Собрано: " + format(get_treasury_total_in(), ",") + "\n"
    text += "Выдано: " + format(get_treasury_total_out(), ",") + "\n"
    text += "Налог: " + str(get_tax_percent()) + "%"
    if message_id:
        edit_message(chat_id, message_id, text, treasury_keyboard())
    else:
        send_message(chat_id, text, treasury_keyboard())


def handle_treasury_stats(chat_id, message_id, user_id):
    text = "СТАТИСТИКА КАЗНЫ\n\n"
    text += "Баланс: " + format(get_treasury(CHAT_ID), ",") + "\n"
    text += "Собрано: " + format(get_treasury_total_in(), ",") + "\n"
    text += "Выдано: " + format(get_treasury_total_out(), ",")
    if message_id:
        edit_message(chat_id, message_id, text, treasury_keyboard())
    else:
        send_message(chat_id, text, treasury_keyboard())


def handle_start(chat_id, user_id, username):
    get_or_create_user(user_id, username)
    try:
        with DB_LOCK:
            with _conn() as conn:
                conn.execute("UPDATE users SET username = ? WHERE user_id = ?",
                             (username, user_id))
                conn.commit()
    except Exception as e:
        print(f"⚠️ handle_start UPDATE: {e}")
    update_last_active(user_id)
    check_and_award_titles(user_id)
    balance = get_balance(user_id)
    treasury = get_treasury(CHAT_ID)
    az_balance = get_az_balance(user_id)
    progress, _ = get_special_progress(user_id)
    titles = get_user_titles(user_id)
    titles_text = ""
    if titles:
        titles_text = "\nТитулы: " + " | ".join([t["name"] for t in titles[:3]])
        if len(titles) > 3:
            titles_text += " +" + str(len(titles) - 3)
    text = "ДОБРО ПОЖАЛОВАТЬ!\n\n"
    text += "ID: " + str(user_id) + "\n"
    text += "Поинты: " + format(balance, ",") + "\n"
    text += "Az: " + str(az_balance) + titles_text + "\n\n"
    text += "Казна: " + format(treasury, ",") + "\n"
    text += "Обменник: " + format(get_az_rate(), ",") + " → " + str(get_az_amount()) + " Az\n"
    text += "Титулов: " + str(len(TITLES)) + "\n\n"
    text += "Прогресс особого: " + str(progress % 100) + "/100\n\n"
    text += "ДЖЕКПОТ: 1% на 100,000,000,000!\n\n"
    text += "Ставки: 500 30-36, потом Го Рулетка\n"
    text += "Обмен: /az\n"
    text += "Кейсы: /cases\n"
    text += "Титулы: /titles"
    send_message(chat_id, text, main_keyboard(user_id))


# ========== КРАШ ==========
def handle_crash(chat_id, message_id, user_id):
    balance = get_balance(user_id)
    text = "КРАШ\n\nДо x4!\nБаланс: " + format(balance, ",")
    if message_id:
        edit_message(chat_id, message_id, text, crash_keyboard())
    else:
        send_message(chat_id, text, crash_keyboard())


def handle_crash_start(chat_id, message_id, user_id):
    with CRASH_LOCK:
        if user_id in user_crash and user_crash[user_id].get("active"):
            send_message(chat_id, "Уже активная игра!", crash_keyboard())
            return
        user_crash[user_id] = {"amount": 0, "multiplier": 1.0, "active": False, "pending": True}
    user_states[user_id] = {"action": "crash_amount"}
    text = "Введи сумму\n\nМинимум: 100\n\n/cancel"
    if message_id:
        edit_message(chat_id, message_id, text, back_keyboard())
    else:
        send_message(chat_id, text, back_keyboard())


def process_crash_amount(chat_id, user_id, text):
    try:
        amount = int(text)
        if amount < 100:
            send_message(chat_id, "Минимум 100!")
            return
        balance = get_balance(user_id)
        if amount > balance:
            send_message(chat_id, "Баланс: " + format(balance, ","))
            return
        if user_id in user_states:
            del user_states[user_id]
        try:
            with DB_LOCK:
                with _conn() as conn:
                    c = conn.cursor()
                    c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                              (amount, user_id, amount))
                    if c.rowcount == 0:
                        conn.rollback()
                        send_message(chat_id, "Ошибка!")
                        with CRASH_LOCK:
                            user_crash.pop(user_id, None)
                        return
                    c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                              (user_id, -amount, "crash_bet", "crash", None))
                    conn.commit()
        except Exception as e:
            send_message(chat_id, "❌ " + str(e))
            with CRASH_LOCK:
                user_crash.pop(user_id, None)
            return
        with CRASH_LOCK:
            user_crash[user_id] = {"amount": amount, "multiplier": 1.0, "active": True, "chat_id": chat_id}
        send_message(chat_id, "СТАРТ!\n" + format(amount, ",") + "\nx1.00", crash_game_keyboard())
        thread = threading.Thread(target=crash_process, args=(chat_id, user_id, amount))
        thread.daemon = True
        thread.start()
    except ValueError:
        send_message(chat_id, "Число!")


def crash_process(chat_id, user_id, amount):
    multiplier = 1.0
    message_id = None
    message_created = False
    while True:
        with CRASH_LOCK:
            if user_id not in user_crash or not user_crash[user_id].get("active", False):
                return
            user_crash[user_id]["multiplier"] = multiplier
        multiplier += 0.05
        multiplier = round(multiplier, 2)
        with CRASH_LOCK:
            if user_id not in user_crash or not user_crash[user_id].get("active", False):
                return
            user_crash[user_id]["multiplier"] = multiplier
        if random.random() < 0.03 or multiplier >= 4.0:
            with CRASH_LOCK:
                if user_id not in user_crash or not user_crash[user_id].get("active", False):
                    return
                user_crash[user_id]["active"] = False
                user_crash.pop(user_id, None)
            add_transaction(user_id, -amount, "crash_lose", "crash", "x" + str(multiplier))
            text_crash = "КРАШ!\nx" + str(multiplier) + "\n-" + format(amount, ",") + "\n\nБаланс: " + format(get_balance(user_id), ",")
            if message_id:
                edit_message(chat_id, message_id, text_crash, crash_keyboard())
            else:
                send_message(chat_id, text_crash, crash_keyboard())
            return
        text = "КРАШ\n" + format(amount, ",") + "\nx" + str(multiplier) + "\nЗабрать: " + format(int(amount * multiplier), ",")
        if not message_created:
            response = send_message(chat_id, text, crash_game_keyboard())
            if response and response.get("ok"):
                message_id = response["result"]["message_id"]
                message_created = True
        else:
            edit_message(chat_id, message_id, text, crash_game_keyboard())
        time.sleep(0.5)


def handle_crash_cashout(chat_id, message_id, user_id):
    with CRASH_LOCK:
        data = user_crash.get(user_id)
        if not data or not data.get("active", False):
            send_message(chat_id, "Нет активной игры!", crash_keyboard())
            return
        data["active"] = False
        amount = data.get("amount", 0)
        multiplier = data.get("multiplier", 1.0)
        user_crash.pop(user_id, None)
        win = int(amount * multiplier)
        try:
            with DB_LOCK:
                with _conn() as conn:
                    c = conn.cursor()
                    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (win, user_id))
                    c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                              (user_id, win, "crash_win", "crash", "x" + str(multiplier)))
                    conn.commit()
        except Exception as e:
            print("⚠️ crash cashout error: " + str(e))
    text = "ВЫИГРЫШ!\n" + format(amount, ",") + "\nx" + str(multiplier) + "\n+" + format(win, ",") + "\n\nБаланс: " + format(get_balance(user_id), ",")
    if message_id:
        edit_message(chat_id, message_id, text, crash_keyboard())
    else:
        send_message(chat_id, text, crash_keyboard())


# ========== КОСТИ ==========
def handle_dice(chat_id, message_id, user_id):
    balance = get_balance(user_id)
    text = "КОСТИ\n\nБаланс: " + format(balance, ",") + "\nШанс 1/6\nx7"
    if message_id:
        edit_message(chat_id, message_id, text, dice_keyboard())
    else:
        send_message(chat_id, text, dice_keyboard())


def handle_dice_amount(chat_id, message_id, user_id, bet_type):
    balance = get_balance(user_id)
    if bet_type == "all":
        amount = balance
    elif bet_type == "custom":
        user_states[user_id] = {"action": "dice_custom_amount"}
        text = "СТАВКА\n\nБаланс: " + format(balance, ",") + "\nМинимум: 100"
        if message_id:
            edit_message(chat_id, message_id, text, back_keyboard())
        else:
            send_message(chat_id, text, back_keyboard())
        return
    else:
        try:
            amount = int(bet_type)
        except Exception:
            send_message(chat_id, "Ошибка!")
            return
    if amount < 100:
        send_message(chat_id, "Минимум 100!")
        return
    if amount > balance:
        send_message(chat_id, "Баланс: " + format(balance, ","))
        return
    user_states[user_id] = {"action": "dice_bet", "bet_amount": amount}
    text = "ВЫБЕРИ ЧИСЛО\n\n" + format(amount, ",") + "\nВыигрыш: " + format(amount * 7, ",")
    if message_id:
        edit_message(chat_id, message_id, text, dice_choose_number_keyboard())
    else:
        send_message(chat_id, text, dice_choose_number_keyboard())


def process_dice_custom_amount(chat_id, user_id, text):
    try:
        amount = int(text.strip())
        if amount < 100:
            send_message(chat_id, "Минимум 100!")
            return
        balance = get_balance(user_id)
        if amount > balance:
            send_message(chat_id, "Баланс: " + format(balance, ","))
            return
        user_states[user_id] = {"action": "dice_bet", "bet_amount": amount}
        send_message(chat_id, "ВЫБЕРИ ЧИСЛО\n\n" + format(amount, ",") + "\nВыигрыш: " + format(amount * 7, ","), dice_choose_number_keyboard())
    except ValueError:
        send_message(chat_id, "Число!")


def process_dice_bet(chat_id, message_id, user_id, chosen):
    if user_id not in user_states or user_states[user_id].get("action") != "dice_bet":
        send_message(chat_id, "Сначала ставку!", dice_keyboard())
        return
    if chosen not in range(1, 7):
        send_message(chat_id, "1-6!")
        return
    state = user_states.pop(user_id, None)
    bet = state.get("bet_amount", 0) if state else 0
    if bet <= 0:
        send_message(chat_id, "Ошибка!", dice_keyboard())
        return
    try:
        with DB_LOCK:
            with _conn() as conn:
                c = conn.cursor()
                c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                          (bet, user_id, bet))
                if c.rowcount == 0:
                    conn.rollback()
                    send_message(chat_id, "Ошибка списания!")
                    return
                conn.commit()
    except Exception as e:
        send_message(chat_id, "❌ " + str(e))
        return
    dice_result = random.randint(1, 6)
    win = (chosen == dice_result)
    if win:
        prize = bet * 7
        try:
            with DB_LOCK:
                with _conn() as conn:
                    c = conn.cursor()
                    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (prize, user_id))
                    c.execute("INSERT INTO transactions (user_id, amount, type, game, details) VALUES (?, ?, ?, ?, ?)",
                              (user_id, prize, "dice_win", "dice", "x7 на " + str(chosen)))
                    conn.commit()
        except Exception as e:
            print("⚠️ dice win error: " + str(e))
        win_text = "ПОБЕДА! +" + format(prize, ",")
    else:
        add_transaction(user_id, -bet, "dice_lose", "dice", "не угадал " + str(chosen))
        win_text = "Проигрыш -" + format(bet, ",")
    result_msg = "Результат: " + str(dice_result) + "\nТвоё: " + str(chosen) + "\nСтавка: " + format(bet, ",") + "\n" + win_text + "\n\nБаланс: " + format(get_balance(user_id), ",")
    send_message(chat_id, result_msg, dice_keyboard())


# ========== AZ МЕНЮ ==========
def handle_az_menu(chat_id, message_id, user_id):
    rate = get_az_rate()
    az_per = get_az_amount()
    balance = get_balance(user_id)
    az_balance = get_az_balance(user_id)
    enabled = is_az_enabled()
    possible = balance // rate if rate > 0 else 0
    text = "ОБМЕННИК AZ\n\n"
    text += "Курс: " + format(rate, ",") + " → " + str(az_per) + " Az\n\n"
    text += "Поинты: " + format(balance, ",") + "\n"
    text += "Az: " + str(az_balance) + "\n\n"
    text += "Можно: до " + str(possible) + "\n"
    text += "Статус: " + ("ON" if enabled else "OFF")
    if message_id:
        edit_message(chat_id, message_id, text, az_exchange_keyboard())
    else:
        send_message(chat_id, text, az_exchange_keyboard())


def handle_az_exchange(chat_id, message_id, user_id, times):
    success, result = exchange_az(user_id, times)
    send_message(chat_id, result)
    if message_id:
        handle_az_menu(chat_id, message_id, user_id)


def handle_az_exchange_max(chat_id, message_id, user_id):
    rate = get_az_rate()
    balance = get_balance(user_id)
    if balance < rate:
        send_message(chat_id, "Нужно: " + format(rate, ",") + ", есть: " + format(balance, ","))
        return
    max_times = min(balance // rate, 100)
    handle_az_exchange(chat_id, message_id, user_id, max_times)


def handle_az_custom(chat_id, message_id, user_id):
    user_states[user_id] = {"action": "az_custom"}
    rate = get_az_rate()
    az_per = get_az_amount()
    balance = get_balance(user_id)
    text = "СВОЁ\n\nБаланс: " + format(balance, ",") + "\n" + format(rate, ",") + " → " + str(az_per) + " Az\n\nНапиши (1-100):\n/cancel"
    if message_id:
        edit_message(chat_id, message_id, text, back_keyboard())
    else:
        send_message(chat_id, text, back_keyboard())


def process_az_custom(chat_id, user_id, text):
    try:
        times = int(text.strip())
        if times < 1 or times > 100:
            send_message(chat_id, "1-100!")
            return
        if user_id in user_states:
            del user_states[user_id]
        success, result = exchange_az(user_id, times)
        send_message(chat_id, result)
    except ValueError:
        send_message(chat_id, "Число!")


def handle_az_history(chat_id, message_id, user_id):
    history = get_az_history(user_id, 10)
    az_balance = get_az_balance(user_id)
    if not history:
        text = "ИСТОРИЯ\n\nAz: " + str(az_balance) + "\n\nПусто."
    else:
        text = "ИСТОРИЯ\n\nAz: " + str(az_balance) + "\n\n"
        for points, az, timestamp in history:
            text += str(timestamp)[:16] + " | -" + format(points, ",") + " → +" + str(az) + "\n"
    if message_id:
        edit_message(chat_id, message_id, text, az_exchange_keyboard())
    else:
        send_message(chat_id, text, az_exchange_keyboard())


def handle_az_top(chat_id, message_id, user_id):
    top = get_az_top(10)
    if not top:
        text = "ТОП AZ\n\nПусто."
    else:
        text = "ТОП AZ\n\n"
        for i, (uid, username, amount, total) in enumerate(top, 1):
            name = username or str(uid)
            text += str(i) + ". " + str(name) + " | " + str(amount) + "\n"
    text += "\nТвой: " + str(get_az_balance(user_id))
    if message_id:
        edit_message(chat_id, message_id, text, az_exchange_keyboard())
    else:
        send_message(chat_id, text, az_exchange_keyboard())


# ========== ПАРСЕР ==========
def parse_command(text):
    if not text or not text.startswith('/'):
        return None, None
    parts = text.split()
    if not parts:
        return None, None
    first = parts[0]
    if '@' in first:
        first = first.split('@')[0]
    return first.lower(), parts[1:]


# ========== MAIN ==========
def main():
    try:
        r = urllib.request.urlopen("https://api.telegram.org/bot" + TOKEN + "/deleteWebhook?drop_pending_updates=true", timeout=10)
        print("deleteWebhook: " + r.read().decode())
    except Exception as e:
        print("deleteWebhook err: " + str(e))
    print("Инициализация...")
    if not init_db():
        print("Ошибка БД!")
        return
    print("Бот запущен!")
    print("=" * 60)
    offset = 0
    try:
        r = urllib.request.urlopen("https://api.telegram.org/bot" + TOKEN + "/getUpdates?offset=-1", timeout=10)
        data = json.loads(r.read().decode())
        if data.get("ok") and data.get("result"):
            offset = data["result"][-1]["update_id"] + 1
            print("Пропускаем до offset=" + str(offset))
    except Exception as e:
        print("skip old err: " + str(e))

    while True:
        try:
            data = get_updates(offset)
            if data.get("ok"):
                for update in data.get("result", []):
                    try:
                        offset = update["update_id"] + 1

                        if "message" in update:
                            msg = update["message"]
                            chat_id = msg["chat"]["id"]
                            user_id = msg["from"]["id"]
                            username = msg["from"].get("username") or msg["from"].get("first_name", str(user_id))
                            update_last_active(user_id)
                            if "text" in msg:
                                text = msg["text"]
                                print("MSG user_id=" + str(user_id) + " chat_id=" + str(chat_id) + " " + str(username) + ": " + text)
                                cmd, args = parse_command(text)

                                if cmd == "/transfer" and "reply_to_message" in msg:
                                    reply_msg = msg["reply_to_message"]
                                    reply_user = reply_msg.get("from")
                                    if not reply_user:
                                        send_message(chat_id, "Нельзя перевести этому пользователю!")
                                        continue
                                    reply_to_user_id = reply_user.get("id")
                                    reply_to_name = reply_user.get("username") or reply_user.get("first_name") or str(reply_to_user_id)
                                    if len(args) != 1:
                                        send_message(chat_id, "Формат: /transfer СУММА")
                                    else:
                                        try:
                                            amount = int(args[0])
                                            process_transfer_reply(chat_id, user_id, reply_to_user_id, reply_to_name, amount)
                                        except ValueError:
                                            send_message(chat_id, "Сумма числом!")
                                    continue

                                if cmd is not None:
                                    if cmd == "/start":
                                        handle_start(chat_id, user_id, username)
                                    elif cmd == "/ping":
                                        send_message(chat_id, "Pong!")
                                    elif cmd == "/cancel":
                                        had = False
                                        if user_id in user_states:
                                            del user_states[user_id]
                                            had = True
                                        with CRASH_LOCK:
                                            if user_id in user_crash and user_crash[user_id].get("pending"):
                                                user_crash.pop(user_id, None)
                                                had = True
                                        send_message(chat_id, "Отменено!" if had else "Нет действий!")
                                    elif cmd == "/az":
                                        handle_az_menu(chat_id, None, user_id)
                                    elif cmd == "/az_top":
                                        handle_az_top(chat_id, None, user_id)
                                    elif cmd == "/titles" or cmd == "/титулы":
                                        handle_titles_menu(chat_id, None, user_id)
                                    elif cmd == "/my_titles":
                                        handle_titles_my(chat_id, None, user_id)
                                    elif cmd == "/titles_list":
                                        handle_titles_list(chat_id, None, user_id)
                                    elif cmd == "/cases":
                                        handle_cases_menu(chat_id, None, user_id)
                                    elif cmd == "/case_stats":
                                        handle_case_stats(chat_id, None, user_id)
                                    elif cmd == "/case_top":
                                        handle_case_top(chat_id, None, user_id)
                                    elif cmd == "/roulette":
                                        handle_roulette(chat_id, None, user_id)
                                    elif cmd == "/promo":
                                        if len(args) >= 1:
                                            code = args[0].strip().strip('"\'`#')
                                            success, result = use_promocode(user_id, code)
                                            send_message(chat_id, result)
                                        else:
                                            send_message(chat_id, "/promo КОД")
                                    elif cmd == "/duel":
                                        process_duel_command(chat_id, user_id, args)
                                    elif cmd == "/accept":
                                        process_accept_command(chat_id, user_id, args)
                                    elif cmd == "/donate":
                                        if len(args) == 1:
                                            try:
                                                success, result = donate_to_treasury(chat_id, user_id, int(args[0]))
                                                send_message(chat_id, result)
                                            except Exception:
                                                send_message(chat_id, "/donate Сумма")
                                    elif cmd == "/transfer":
                                        process_transfer(chat_id, user_id, args)
                                    elif cmd == "/mybets":
                                        show_my_bets(chat_id, user_id)
                                    else:
                                        send_message(chat_id, "Неизвестно: " + str(cmd))

                                elif text.strip().lower() in ("го рулетка", "го рулетку", "go roulette", "гоу рулетка"):
                                    go_roulette(chat_id, None, user_id)

                                elif user_id in user_states:
                                    state = user_states[user_id]
                                    action = state.get("action")
                                    if action == "crash_amount":
                                        process_crash_amount(chat_id, user_id, text)
                                    elif action == "dice_custom_amount":
                                        process_dice_custom_amount(chat_id, user_id, text)
                                    elif action == "az_custom":
                                        process_az_custom(chat_id, user_id, text)
                                    elif action == "case_custom":
                                        process_case_custom(chat_id, user_id, text)
                                    else:
                                        send_message(chat_id, "Напиши /start")

                                elif text and text[0].isdigit() and parse_roulette_bets(text):
                                    add_roulette_bet(chat_id, user_id, text)

                        if "callback_query" in update:
                            cb = update["callback_query"]
                            cb_id = cb["id"]
                            data = cb["data"]
                            chat_id = cb["message"]["chat"]["id"]
                            message_id = cb["message"]["message_id"]
                            user_id = cb["from"]["id"]
                            update_last_active(user_id)

                            if data == "back":
                                user_states.pop(user_id, None)
                                with CRASH_LOCK:
                                    if user_id in user_crash and user_crash[user_id].get("pending"):
                                        user_crash.pop(user_id, None)
                                handle_start(chat_id, user_id, None)
                            elif data == "roulette":
                                handle_roulette(chat_id, message_id, user_id)
                            elif data == "roulette_go":
                                go_roulette(chat_id, message_id, user_id)
                            elif data == "roulette_clear":
                                clear_roulette_bets(chat_id, user_id)
                                handle_roulette(chat_id, message_id, user_id)
                            elif data == "roulette_my_bets":
                                show_my_bets(chat_id, user_id)
                            elif data == "titles_menu":
                                handle_titles_menu(chat_id, message_id, user_id)
                            elif data == "titles_my":
                                handle_titles_my(chat_id, message_id, user_id)
                            elif data == "titles_list":
                                handle_titles_list(chat_id, message_id, user_id)
                            elif data == "dice":
                                handle_dice(chat_id, message_id, user_id)
                            elif data.startswith("dice_amt_"):
                                handle_dice_amount(chat_id, message_id, user_id, data.replace("dice_amt_", ""))
                            elif data.startswith("dice_choose_"):
                                process_dice_bet(chat_id, message_id, user_id, int(data.replace("dice_choose_", "")))
                            elif data == "dice_back_to_amount":
                                handle_dice(chat_id, message_id, user_id)
                            elif data == "crash":
                                handle_crash(chat_id, message_id, user_id)
                            elif data == "crash_start":
                                handle_crash_start(chat_id, message_id, user_id)
                            elif data == "crash_cashout":
                                handle_crash_cashout(chat_id, message_id, user_id)
                            elif data == "profile":
                                handle_profile(chat_id, message_id, user_id)
                            elif data == "bonus":
                                handle_bonus(chat_id, message_id, user_id)
                            elif data == "history":
                                handle_history(chat_id, message_id, user_id)
                            elif data == "transfer":
                                handle_transfer(chat_id, message_id, user_id)
                            elif data == "duel":
                                handle_duel(chat_id, message_id, user_id)
                            elif data == "duel_challenge":
                                send_message(chat_id, "Используйте: /duel @username Сумма")
                            elif data == "treasury":
                                handle_treasury(chat_id, message_id, user_id)
                            elif data == "treasury_stats":
                                handle_treasury_stats(chat_id, message_id, user_id)
                            elif data == "az_menu":
                                handle_az_menu(chat_id, message_id, user_id)
                            elif data == "az_ex_1":
                                handle_az_exchange(chat_id, message_id, user_id, 1)
                            elif data == "az_ex_5":
                                handle_az_exchange(chat_id, message_id, user_id, 5)
                            elif data == "az_ex_10":
                                handle_az_exchange(chat_id, message_id, user_id, 10)
                            elif data == "az_ex_max":
                                handle_az_exchange_max(chat_id, message_id, user_id)
                            elif data == "az_ex_custom":
                                handle_az_custom(chat_id, message_id, user_id)
                            elif data == "az_history":
                                handle_az_history(chat_id, message_id, user_id)
                            elif data == "az_top":
                                handle_az_top(chat_id, message_id, user_id)
                            elif data == "cases_menu":
                                handle_cases_menu(chat_id, message_id, user_id)
                            elif data.startswith("case_menu_"):
                                handle_case_menu(chat_id, message_id, user_id, data.replace("case_menu_", ""))
                            elif data.startswith("case_open_"):
                                parts = data.replace("case_open_", "").split("_")
                                if len(parts) == 2:
                                    handle_case_open(chat_id, message_id, user_id, parts[0], int(parts[1]))
                            elif data.startswith("case_custom_"):
                                handle_case_custom(chat_id, message_id, user_id, data.replace("case_custom_", ""))
                            elif data == "case_stats":
                                handle_case_stats(chat_id, message_id, user_id)
                            elif data == "case_top":
                                handle_case_top(chat_id, message_id, user_id)

                            try:
                                answer_callback(cb_id)
                            except Exception:
                                pass

                    except Exception as e:
                        print("Ошибка апдейта: " + str(e))
                        import traceback
                        traceback.print_exc()

            time.sleep(1)

        except Exception as e:
            print("Ошибка цикла: " + str(e))
            import traceback
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nБот остановлен")
    except Exception as e:
        print("Фатальная ошибка: " + str(e))
