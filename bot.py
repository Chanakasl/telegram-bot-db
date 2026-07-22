import os
import telebot
from telebot import types
import requests
import json
import random
import threading
import time
import re
import uuid
import base64
import logging
from github import Github, Auth

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Environment Variables ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME")
SHORTENER_API = os.environ.get("SHORTENER_API")
BOT_USERNAME = os.environ.get("BOT_USERNAME")
BLOG_URL = os.environ.get("BLOG_URL")
VERCEL_URL = os.environ.get("VERCEL_URL")
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME")
ADMIN_ID = os.environ.get("ADMIN_ID")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
auth = Auth.Token(GITHUB_TOKEN)
github = Github(auth=auth)
repo = github.get_repo(GITHUB_REPO_NAME)
pending_users = {}

# --- Database Functions ---
def get_db():
    try:
        content = repo.get_contents("database.json")
        return json.loads(content.decoded_content.decode()), content.sha
    except:
        empty_db = {"users": [], "used_refs": [], "last_post_id": None}
        repo.create_file("database.json", "Initial DB", json.dumps(empty_db))
        content = repo.get_contents("database.json")
        return json.loads(content.decoded_content.decode()), content.sha

def save_db(data, sha):
    try:
        repo.update_file("database.json", "Update DB", json.dumps(data), sha)
    except Exception as e:
        logger.error(f"Save DB Error: {e}")

# --- Helper Functions ---
def create_short_link(long_url):
    if not SHORTENER_API: return long_url
    try:
        res = requests.get(f"https://shrinkearn.com/api?api={SHORTENER_API}&url={long_url}", timeout=10).json()
        return res.get('shortenedUrl', long_url)
    except:
        return long_url

def check_sub(user_id):
    if not CHANNEL_USERNAME: return True
    try:
        return bot.get_chat_member(CHANNEL_USERNAME, user_id).status in ['creator', 'administrator', 'member']
    except: return False

def auto_delete_message(chat_id, message_id, delay=300):
    """Deletes a message automatically after 'delay' seconds"""
    def task():
        time.sleep(delay)
        try: bot.delete_message(chat_id, message_id)
        except: pass
    threading.Thread(target=task, daemon=True).start()

# --- Admin Features (3, 4) ---

@bot.message_handler(commands=['contact'])
def contact_admin(message):
    text = message.text.replace('/contact', '').strip()
    if not text:
        msg = bot.reply_to(message, "✍️ කරුණාකර /contact විධානයට පසු ඔබේ පණිවිඩය ටයිප් කරන්න.\nඋදා: `/contact මට වීඩියෝ එක පේන්නේ නෑ`", parse_mode="Markdown")
        auto_delete_message(message.chat.id, msg.message_id, 30)
        return
    if ADMIN_ID:
        bot.send_message(ADMIN_ID, f"📩 **New Message from User:** {message.chat.id}\n\n{text}")
        bot.reply_to(message, "✅ ඔබේ පණිවිඩය Admin වෙත සාර්ථකව යවන ලදී. පිළිතුරක් ලැබෙන තුරු රැඳී සිටින්න.")

@bot.message_handler(func=lambda m: str(m.chat.id) == str(ADMIN_ID) and m.reply_to_message is not None)
def admin_reply(message):
    """Admin replies to a forwarded user message"""
    if "New Message from User:" in message.reply_to_message.text:
        try:
            user_id = message.reply_to_message.text.split('User: ')[1].split('\n')[0].strip()
            bot.send_message(user_id, f"👨‍💻 **Admin Reply:**\n\n{message.text}")
            bot.reply_to(message, "✅ Reply sent to user.")
        except:
            bot.reply_to(message, "❌ Failed to send reply. User ID not found.")

@bot.message_handler(commands=['stats', 'broadcast'])
def admin_commands(message):
    if str(message.chat.id) != str(ADMIN_ID): return
    db, _ = get_db()
    
    if message.text.startswith('/stats'):
        users = len(db.get("users", []))
        bot.reply_to(message, f"📊 **Bot Statistics**\n\n👥 Total Users: {users}")
    
    elif message.text.startswith('/broadcast'):
        msg_text = message.text.replace('/broadcast', '').strip()
        if not msg_text:
            bot.reply_to(message, "Please provide a message. Example: `/broadcast Hello!`")
            return
        users = db.get("users", [])
        sent = 0
        for uid in users:
            try:
                bot.send_message(uid, f"📢 **Broadcast**\n\n{msg_text}")
                sent += 1
                time.sleep(0.3)
            except: pass
        bot.reply_to(message, f"✅ Broadcast successfully sent to {sent} users.")

# --- Main Logic ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('getvid_'))
def handle_request(call):
    vid_id = call.data.split('_')[1]
    chat_id = call.message.chat.id
    db, sha = get_db()

    if db.get(f"auth_{chat_id}", 0) > time.time():
        bot.answer_callback_query(call.id, "✅ Unlocked! Generating Player...")
        # Send video logic (simplified for snippet)
        bot.send_message(chat_id, "✅ You have VIP access! (Video logic will trigger here)")
        return

    token = str(uuid.uuid4().hex)[:10]
    db[f"token_{token}"] = vid_id
    save_db(db, sha)

    base_url = VERCEL_URL.rstrip('/') if VERCEL_URL else ""
    short_url = create_short_link(f"{base_url}/index.html?key={token}")

    msg = bot.send_message(
        chat_id,
        f"🔗 Click the link below, watch the Ad, and get your verification key!\n\n👉 {short_url}\n\n⚠️ **Instruction:** Send the key back to me.\n⏳ _This link will be deleted in 5 minutes._",
        parse_mode="Markdown"
    )
    bot.answer_callback_query(call.id)
    # Feature 5: Auto-delete the ad link message after 5 minutes (300 seconds)
    auto_delete_message(chat_id, msg.message_id, 300)

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    text = message.text.strip()
    chat_id = message.chat.id
    
    # Ignore normal commands from being processed as tokens
    if text.startswith(('/start', '/help', '/contact')):
        bot.reply_to(message, "Welcome to the bot! Use the menu to navigate.")
        return

    db, sha = get_db()
    token_key = f"token_{text}"
    
    if token_key in db:
        vid_id = db[token_key]
        db[f"auth_{chat_id}"] = time.time() + 3600
        del db[token_key]
        save_db(db, sha)
        bot.send_message(chat_id, "🎉 **Success! The Bot is now unlocked for 1 HOUR.**")
    else:
        # Auto-delete invalid tokens to keep chat clean
        msg = bot.send_message(chat_id, "❌ Invalid Key! The key is incorrect or expired.")
        auto_delete_message(chat_id, msg.message_id, 10)
        auto_delete_message(chat_id, message.message_id, 10)

from flask import Flask
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is alive!", 200

def run_bot():
    logger.info("Bot is running...")
    bot.infinity_polling()

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
