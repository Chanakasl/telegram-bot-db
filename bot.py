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
from flask import Flask

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

# GitHub Authentication
auth = Auth.Token(GITHUB_TOKEN)
github = Github(auth=auth)
repo = github.get_repo(GITHUB_REPO_NAME)

pending_users = {}

# --- Database Helper Functions ---
def get_db():
    try:
        content = repo.get_contents("database.json")
        data = json.loads(content.decoded_content.decode())
        return data, content.sha
    except Exception as e:
        empty_db = {"users": [], "used_refs": [], "last_post_id": None}
        try:
            repo.create_file("database.json", "Initial commit", json.dumps(empty_db))
            content = repo.get_contents("database.json")
            return json.loads(content.decoded_content.decode()), content.sha
        except:
            return empty_db, None

def save_db(data, sha):
    try:
        if sha is None:
            repo.create_file("database.json", "Create DB", json.dumps(data))
        else:
            repo.update_file("database.json", "Update DB", json.dumps(data), sha)
    except:
        pass

# --- Shortener ---
def create_short_link(long_url):
    if not SHORTENER_API: return long_url
    try:
        api = f"https://shrinkearn.com/api?api={SHORTENER_API}&url={long_url}"
        resp = requests.get(api, timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            short = result.get('shortenedUrl')
            if short: return short
        fallback = f"https://is.gd/create.php?format=simple&url={long_url}"
        resp2 = requests.get(fallback, timeout=10)
        if resp2.status_code == 200:
            return resp2.text.strip()
    except: pass
    return long_url

# --- Feature: Auto-Delete ---
def auto_delete_message(chat_id, message_id, delay=300):
    def task():
        time.sleep(delay)
        try: bot.delete_message(chat_id, message_id)
        except: pass
    threading.Thread(target=task, daemon=True).start()

# --- Feature: Contact Admin ---
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

@bot.message_handler(func=lambda m: m.reply_to_message is not None and ADMIN_ID and str(m.chat.id) == str(ADMIN_ID))
def admin_reply(message):
    if "New Message from User:" in message.reply_to_message.text:
        try:
            user_id = message.reply_to_message.text.split('User: ')[1].split('\n')[0].strip()
            bot.send_message(user_id, f"👨‍💻 **Admin Reply:**\n\n{message.text}")
            bot.reply_to(message, "✅ Reply sent to user.")
        except:
            bot.reply_to(message, "❌ Failed to send reply. User ID not found.")

# --- Subscription Check ---
def check_sub(user_id):
    if not CHANNEL_USERNAME: return True
    try:
        status = bot.get_chat_member(CHANNEL_USERNAME, user_id).status
        return status in ['creator', 'administrator', 'member']
    except: return False

# --- Anti-Bot CAPTCHA ---
def send_captcha(chat_id):
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    ans = num1 + num2
    options = {ans}
    while len(options) < 4:
        options.add(random.randint(1, 20))
    options = list(options)
    random.shuffle(options)
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for opt in options:
        cb_data = "captcha_correct" if opt == ans else "captcha_wrong"
        buttons.append(types.InlineKeyboardButton(str(opt), callback_data=cb_data))
    markup.add(*buttons)
    bot.send_message(chat_id, f"🛡️ **Anti-Bot Verification**\n\nTo prove you are a human, please select the correct answer:\n\n**{num1} + {num2} = ?**", reply_markup=markup)

# --- Fetch Blogger Videos ---
def get_blogger_videos_keyboard(page=1, search_query=None, per_page=10):
    if search_query:
        feed_url = f"https://{BLOG_URL}/feeds/posts/default/-/Video?alt=json&q={search_query}&max-results=50"
    else:
        feed_url = f"https://{BLOG_URL}/feeds/posts/default/-/Video?alt=json&max-results=50"
    try:
        data = requests.get(feed_url, timeout=10).json()
        entries = data.get('feed', {}).get('entry', [])
        db, sha = get_db()
        db_changed = False
        video_items = []
        for entry in entries:
            title = entry.get('title', {}).get('$t', 'Video')
            content = entry.get('content', {}).get('$t', '')
            images = re.findall(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', content, re.IGNORECASE)
            all_links = re.findall(r'(?:src|href)=["\'](https?://[^"\']+)["\']', content, re.IGNORECASE)
            videos = [l for l in all_links if l not in images and not l.lower().endswith(('.jpg','.jpeg','.png','.css','.js','.gif'))]
            if videos or images:
                vid_id = str(hash(title + (videos[0] if videos else images[0])))
                db[vid_id] = {"images": images[:5], "video": videos[0] if videos else None}
                db_changed = True
                video_items.append((vid_id, title))
        if db_changed:
            save_db(db, sha)
        total = len(video_items)
        start = (page - 1) * per_page
        end = start + per_page
        page_items = video_items[start:end]
        markup = types.InlineKeyboardMarkup(row_width=1)
        for vid_id, title in page_items:
            markup.add(types.InlineKeyboardButton(f"🎬 {title}", callback_data=f"getvid_{vid_id}"))
        nav_buttons = []
        if page > 1:
            nav_buttons.append(types.InlineKeyboardButton("◀️ Back", callback_data=f"page_{page-1}"))
        if end < total:
            nav_buttons.append(types.InlineKeyboardButton("Next ▶️", callback_data=f"page_{page+1}"))
        if nav_buttons:
            markup.add(*nav_buttons)
        return markup if page_items else None
    except: return None

# --- Media Processing ---
def process_and_send_media(chat_id, media_data):
    images = media_data.get("images", [])
    video_url = media_data.get("video")
    if images:
        try:
            media_group = [types.InputMediaPhoto(url) for url in images[:10]]
            bot.send_media_group(chat_id, media_group)
        except: pass
    if video_url:
        expire_timestamp = int(time.time()) + 3600
        raw_data = f"{video_url}:::{expire_timestamp}"
        encoded_data = base64.b64encode(raw_data.encode('utf-8')).decode('utf-8')
        base_url = VERCEL_URL.rstrip('/') if VERCEL_URL else ""
        player_url = f"{base_url}/player.html?data={encoded_data}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🍿 Watch Secure Player", url=player_url))
        bot.send_message(chat_id, "✅ **Your Video is Ready!**\n\nClick the button below to watch it securely.\n⚠️ *(This player link will automatically expire in 1 hour)*", reply_markup=markup)
    else:
        bot.send_message(chat_id, "⚠️ No video link found for this entry.")

# --- Main Command Processor ---
def process_user_command(chat_id, text, db, sha):
    if "used_refs" not in db: db["used_refs"] = []

    if text.startswith('/start ref_'):
        try:
            referrer_id = int(text.split('_')[1])
            if referrer_id != chat_id and chat_id not in db["used_refs"]:
                db["used_refs"].append(chat_id)
                current_auth = db.get(f"auth_{referrer_id}", time.time())
                if current_auth < time.time(): current_auth = time.time()
                db[f"auth_{referrer_id}"] = current_auth + 86400
                save_db(db, sha)
                db, sha = get_db()
                try: bot.send_message(referrer_id, "🎉 **Congratulations!**\nA new member joined using your referral link, so you have received an **additional 24 hours of VIP Access!**")
                except: pass
        except: pass

    if not check_sub(chat_id):
        channel_link = CHANNEL_USERNAME.replace('@', '') if CHANNEL_USERNAME else ""
        markup = types.InlineKeyboardMarkup()
        if channel_link: markup.add(types.InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{channel_link}"))
        markup.add(types.InlineKeyboardButton("✅ Check Subscription", callback_data="check_sub"))
        bot.send_message(chat_id, "⚠️ **You must join our channel before using the bot!**\n\nClick the button below to join, then click 'Check Subscription'.", reply_markup=markup)
        return

    if text.startswith('/search'):
        query = text.replace('/search', '').strip()
        if not query:
            bot.send_message(chat_id, "🔍 **Search Videos**\n\nPlease enter the movie/video name.\nExample: `/search Avengers`", parse_mode="Markdown")
            return
        bot.send_chat_action(chat_id, 'typing')
        markup = get_blogger_videos_keyboard(page=1, search_query=query)
        if markup: bot.send_message(chat_id, f"🔍 Search Results for: **{query}**", parse_mode="Markdown", reply_markup=markup)
        else: bot.send_message(chat_id, f"❌ No videos found for: **{query}**", parse_mode="Markdown")
        return

    if text == '/start' or text.startswith('/start ref_') or text == '/start menu':
        bot.send_chat_action(chat_id, 'typing')
        markup = get_blogger_videos_keyboard(page=1)
        if markup:
            bot.send_message(chat_id, "👋 Welcome!\n\nSelect a video below to generate your unique Ad link:\n\n*(Type /refer to invite friends and get VIP access. Type /contact to message admin.)*", reply_markup=markup)
        else:
            bot.send_message(chat_id, "No videos found. Please try again later.")
        return

    if text == '/refer':
        long_ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{chat_id}"
        short_ref_link = create_short_link(long_ref_link)
        bot.send_message(chat_id, f"🎁 **Your Referral Link:**\n\n👉 `{short_ref_link}`", parse_mode="Markdown")
        return

    if text == '/help':
        help_text = "🤖 **Commands**\n/start - Show video list\n/search <name> - Search\n/refer - Get your referral link\n/contact <msg> - Message Admin"
        if ADMIN_ID and str(chat_id) == ADMIN_ID:
            help_text += "\n\n**Admin Commands:**\n/stats - Users count\n/admin broadcast <message> - Send broadcast"
        bot.send_message(chat_id, help_text, parse_mode="Markdown")
        return

    if text == '/stats' and ADMIN_ID and str(chat_id) == ADMIN_ID:
        users_count = len(db.get("users", []))
        bot.send_message(chat_id, f"📊 **Bot Statistics**\n\n👥 Total Users: {users_count}")
        return

    if text.startswith('/admin broadcast') and ADMIN_ID and str(chat_id) == ADMIN_ID:
        msg = text.replace('/admin broadcast', '', 1).strip()
        if not msg:
            bot.send_message(chat_id, "Please provide a message. Example: `/admin broadcast Hello!`")
            return
        users = db.get("users", [])
        sent = 0
        for uid in users:
            try:
                bot.send_message(uid, f"📢 **Broadcast Message**\n\n{msg}")
                sent += 1
                time.sleep(0.2)
            except: pass
        bot.send_message(chat_id, f"✅ Broadcast sent to {sent} users.")
        return

    if text.startswith('/'): return

    # Token Logic + Auto Delete
    token = text
    token_key = f"token_{token}"
    if token_key in db:
        vid_id = db[token_key]
        db[f"auth_{chat_id}"] = time.time() + 3600
        media_data = db.get(vid_id)
        if media_data:
            bot.send_message(chat_id, "🎉 **Success! The Bot is now unlocked for 1 HOUR.**")
            threading.Thread(target=process_and_send_media, args=(chat_id, media_data)).start()
            del db[token_key]
            save_db(db, sha)
        else:
            bot.send_message(chat_id, "❌ Error retrieving video data.")
    else:
        msg = bot.send_message(chat_id, "❌ Invalid Key! The key is incorrect or expired.")
        auto_delete_message(chat_id, msg.message_id, 10)  # Deletes warning in 10s

# --- Callbacks ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('captcha_'))
def handle_captcha(call):
    chat_id = call.message.chat.id
    if call.data == "captcha_correct":
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        bot.answer_callback_query(call.id, "✅ Verification Successful!")
        db, sha = get_db()
        if "users" not in db: db["users"] = []
        if chat_id not in db["users"]:
            db["users"].append(chat_id)
            save_db(db, sha)
            db, sha = get_db()
        original_cmd = pending_users.pop(chat_id, '/start')
        process_user_command(chat_id, original_cmd, db, sha)
    else:
        bot.answer_callback_query(call.id, "❌ Incorrect! Try again.", show_alert=True)
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        send_captcha(chat_id)

@bot.callback_query_handler(func=lambda call: call.data == 'check_sub')
def handle_check_sub(call):
    chat_id = call.message.chat.id
    if check_sub(chat_id):
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        bot.send_message(chat_id, "✅ **Thank you!**\n\nType /start to watch videos.")
    else:
        bot.answer_callback_query(call.id, "❌ Join the channel first!", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('getvid_'))
def handle_request(call):
    vid_id = call.data.split('_')[1]
    chat_id = call.message.chat.id
    db, sha = get_db()

    if db.get(f"auth_{chat_id}", 0) > time.time():
        media_data = db.get(vid_id)
        if media_data:
            bot.answer_callback_query(call.id, "✅ Unlocked!")
            threading.Thread(target=process_and_send_media, args=(chat_id, media_data)).start()
        return

    token = str(uuid.uuid4().hex)[:10]
    db[f"token_{token}"] = vid_id
    save_db(db, sha)

    base_url = VERCEL_URL.rstrip('/') if VERCEL_URL else ""
    short_url = create_short_link(f"{base_url}/index.html?key={token}")

    msg = bot.send_message(
        chat_id,
        f"🔗 Click the link below, watch the Ad, and get your verification key!\n\n👉 {short_url}\n\n⚠️ **Instruction:** Send the key back to me. **(This will unlock ALL videos for 1 hour!)**\n⏳ _(This link will auto-delete in 5 mins)_"
    )
    bot.answer_callback_query(call.id)
    auto_delete_message(chat_id, msg.message_id, 300) # Delete Ad link in 5 mins

@bot.callback_query_handler(func=lambda call: call.data.startswith('page_'))
def handle_pagination(call):
    page = int(call.data.split('_')[1])
    chat_id = call.message.chat.id
    markup = get_blogger_videos_keyboard(page=page)
    if markup: bot.edit_message_text("📹 **Video List**:", chat_id, call.message.message_id, reply_markup=markup)
    else: bot.answer_callback_query(call.id, "No more videos.", show_alert=True)

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    text = message.text.strip()
    chat_id = message.chat.id
    db, sha = get_db()
    if "users" not in db: db["users"] = []
    if chat_id not in db["users"]:
        pending_users[chat_id] = text
        send_captcha(chat_id)
        return
    process_user_command(chat_id, text, db, sha)

# --- Flask App ---
app = Flask(__name__)
@app.route('/')
def health_check(): return "Bot is alive!", 200

def run_bot():
    logger.info("Bot is running...")
    bot.infinity_polling()

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
