import os
import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")

COINS_PER_TAP = 1
COINS_PER_USDT = 1000
MIN_WITHDRAW_COINS = 1000

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN secret/environment variable is missing.")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

db = sqlite3.connect("mining.db", check_same_thread=False)
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    coins INTEGER DEFAULT 0,
    wallet TEXT DEFAULT ''
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    coins INTEGER,
    usdt REAL,
    wallet TEXT,
    status TEXT DEFAULT 'pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
db.commit()


def create_user(user):
    cur.execute(
        "INSERT OR IGNORE INTO users(user_id, username) VALUES (?, ?)",
        (user.id, user.username or "")
    )
    cur.execute(
        "UPDATE users SET username=? WHERE user_id=?",
        (user.username or "", user.id)
    )
    db.commit()


def get_user(user_id):
    cur.execute(
        "SELECT coins, wallet FROM users WHERE user_id=?",
        (user_id,)
    )
    return cur.fetchone() or (0, "")


def add_coins(user_id, amount):
    cur.execute(
        "UPDATE users SET coins=coins+? WHERE user_id=?",
        (amount, user_id)
    )
    db.commit()


def set_wallet(user_id, wallet):
    cur.execute(
        "UPDATE users SET wallet=? WHERE user_id=?",
        (wallet, user_id)
    )
    db.commit()


def create_withdrawal(user_id, coins, usdt, wallet):
    cur.execute(
        """INSERT INTO withdrawals(user_id, coins, usdt, wallet)
           VALUES (?, ?, ?, ?)""",
        (user_id, coins, usdt, wallet)
    )
    cur.execute(
        "UPDATE users SET coins=coins-? WHERE user_id=?",
        (coins, user_id)
    )
    db.commit()


def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⛏️ TAP TO MINE", callback_data="mine")],
        [
            InlineKeyboardButton("💰 Balance", callback_data="balance"),
            InlineKeyboardButton("🏧 Withdraw", callback_data="withdraw"),
        ],
        [
            InlineKeyboardButton("👥 Referral", callback_data="referral"),
            InlineKeyboardButton("ℹ️ Help", callback_data="help"),
        ],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):    print("START COMMAND RECEIVED")
    user = update.effective_user
    create_user(user)

    # Simple referral reward: only when /start <user_id> is used.
    if context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user.id:
                # Prevent repeated reward with a small one-time marker table.
                cur.execute("""
                CREATE TABLE IF NOT EXISTS referrals(
                    referred_id INTEGER PRIMARY KEY,
                    referrer_id INTEGER
                )
                """)
                cur.execute(
                    "SELECT 1 FROM referrals WHERE referred_id=?",
                    (user.id,)
                )
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO referrals(referred_id, referrer_id) VALUES (?, ?)",
                        (user.id, referrer_id)
                    )
                    cur.execute(
                        "UPDATE users SET coins=coins+50 WHERE user_id=?",
                        (referrer_id,)
                    )
                    db.commit()
        except ValueError:
            pass

    coins, wallet = get_user(user.id)
    usdt = coins / COINS_PER_USDT

    await update.message.reply_text(
        f"""🪙 *MINING BOT*

⛏️ Tap the mining button to earn coins.

🪙 Coins: `{coins}`
💵 USDT: `{usdt:.3f}`

📌 Rate: `1000 Coins = 1 USDT`
📌 Minimum withdrawal: `1000 Coins`

⚠️ Withdrawals are recorded as requests. Real USDT payout is not connected yet.""",
        parse_mode="Markdown",
        reply_markup=menu(),
    )


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user = q.from_user
    create_user(user)

    if q.data == "mine":
        add_coins(user.id, COINS_PER_TAP)
        coins, _ = get_user(user.id)
        usdt = coins / COINS_PER_USDT

        await q.edit_message_text(
            f"""⛏️ *MINING ACTIVE*

🪙 Coins: `{coins}`
💵 USDT: `{usdt:.3f}`

👆 Tap again to mine more!""",
            parse_mode="Markdown",
            reply_markup=menu(),
        )

    elif q.data == "balance":
        coins, wallet = get_user(user.id)
        usdt = coins / COINS_PER_USDT
        await q.edit_message_text(
            f"""💰 *YOUR BALANCE*

🪙 Coins: `{coins}`
💵 USDT: `{usdt:.3f}`

🏦 Wallet:
`{wallet or "Not added"}`""",
            parse_mode="Markdown",
            reply_markup=menu(),
        )

    elif q.data == "withdraw":
        coins, wallet = get_user(user.id)

        if coins < MIN_WITHDRAW_COINS:
            await q.edit_message_text(
                f"""🏧 *WITHDRAW*

❌ Minimum: `1000 Coins`
🪙 Your balance: `{coins}`
⏳ Needed: `{MIN_WITHDRAW_COINS - coins}` more coins.""",
                parse_mode="Markdown",
                reply_markup=menu(),
            )
            return

        if not wallet:
            await q.edit_message_text(
                """🏧 *WITHDRAW*

✅ You reached the minimum.

First add your USDT TRC20 wallet:

`/wallet YOUR_TRC20_ADDRESS`

⚠️ Use only your own wallet address.""",
                parse_mode="Markdown",
                reply_markup=menu(),
            )
            return

        amount = coins / COINS_PER_USDT
        create_withdrawal(user.id, coins, amount, wallet)

        await q.edit_message_text(
            f"""✅ *WITHDRAWAL REQUEST CREATED*

💵 Amount: `{amount:.3f} USDT`
🪙 Coins used: `{coins}`
🏦 Wallet: `{wallet}`

⏳ Status: `Pending`

⚠️ Demo payout mode: no real USDT has been sent.""",
            parse_mode="Markdown",
            reply_markup=menu(),
        )

    elif q.data == "referral":
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start={user.id}"
        await q.edit_message_text(
            f"""👥 *REFERRAL*

Invite friends:
`{link}`

🎁 When a new user joins through your link, you receive 50 coins.""",
            parse_mode="Markdown",
            reply_markup=menu(),
        )

    elif q.data == "help":
        await q.edit_message_text(
            """ℹ️ *HELP*

⛏️ Tap mining to earn coins.
💰 1000 coins = 1 USDT.
🏧 Minimum withdrawal = 1000 coins.
🏦 Add your TRC20 wallet with:

`/wallet YOUR_ADDRESS`

⚠️ This version records withdrawal requests but does not send real USDT yet.""",
            parse_mode="Markdown",
            reply_markup=menu(),
        )


async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user)

    if not context.args:
        await update.message.reply_text(
            "🏦 Send your USDT TRC20 address like:\n\n"
            "/wallet YOUR_TRC20_ADDRESS"
        )
        return

    address = context.args[0].strip()

    if len(address) < 20:
        await update.message.reply_text("❌ That wallet address looks too short.")
        return

    set_wallet(user.id, address)
    await update.message.reply_text("✅ USDT TRC20 wallet saved.")


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user)
    coins, wallet_address = get_user(user.id)

    await update.message.reply_text(
        f"🪙 Coins: {coins}\n"
        f"💵 USDT: {coins / COINS_PER_USDT:.3f}\n"
        f"🏦 Wallet: {wallet_address or 'Not added'}"
    )


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("wallet", wallet))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CallbackQueryHandler(buttons))

    print("🚀 TM-Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
