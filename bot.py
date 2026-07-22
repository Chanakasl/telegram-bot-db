import os
import telebot
from telebot import types
import requests
import json
import string
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
ADMIN_ID = os.environ.get("ADMIN_ID")  # Optional: for admin commands

# Validate required variables
required_vars = [TELEGRAM_TOKEN, GITHUB_TOKEN, GITHUB_REPO_NAME, BOT_USERNAME, BLOG_URL, VERCEL_URL]
if not all(required_vars):
    logger.warning("One or more required environment variables are missing. Bot may not work correctly.")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# GitHub Authentication
auth = Auth.Token(GITHUB_TOKEN)
github = Github(auth=auth)
repo = github.get_repo(GITHUB_REPO_NAME)

pending_users = {}

# --- Database Helper Functions (with initialization) ---
def get_db():
    """Retrieve database from GitHub, create if not exists."""
    try:
        content = repo.get_contents("database.json")
        data = json.loads(content.decoded_content.decode())
        return data, content.sha
    except Exception as e:
        logger.warning(f"Database not found or corrupted: {e}. Creating new one.")
        # Create empty database
        empty_db = {"users": [], "used_refs": [], "last_post_id": None}
        try:
            repo.create_file("database.json", "Initial commit", json.dumps(empty_db))
            content = repo.get_contents("database.json")
            return json.loads(content.decoded_content.decode()), content.sha
        except Exception as create_err:
            logger.error(f"Failed to create database: {create_err}")
            return empty_db, None

def save_db(data, sha):
    """Save database to GitHub."""
    try:
        if sha is None:
            # File doesn't exist, create it
            repo.create_file("database.json", "Create DB", json.dumps(data))
        else:
            repo.update_file("database.json", "Update DB", json.dumps(data), sha)
    except Exception as e:
        logger.error(f"Failed to save database: {e}")

# --- Shortener with fallback ---
def create_short_link(long_url):
    """Create short link using primary API, fallback to another if needed."""
    if not SHORTENER_API:
        logger.warning("SHORTENER_API not set. Returning original URL.")
        return long_url
    try:
        # Primary shortener
        api = f"https://shrinkearn.com/api?api={SHORTENER_API}&url={long_url}"
        resp = requests.get(api, timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            short = result.get('shortenedUrl')
            if short:
                return short
        # Fallback (example: using is.gd if shrinkearn fails)
        fallback = f"https://is.gd/create.php?format=simple&url={long_url}"
        resp2 = requests.get(fallback, timeout=10)
        if resp2.status_code == 200:
            return resp2.text.strip()
    except Exception as e:
        logger.error(f"Shortener error: {e}")
    return long_url

# --- Subscription Check ---
def check_sub(user_id):
    if not CHANNEL_USERNAME:
        return True
    try:
        status = bot.get_chat_member(CHANNEL_USERNAME, user_id).status
        return status in ['creator', 'administrator', 'member']
    except Exception as e:
        logger.error(f"Subscription check failed for {user_id}: {e}")
        return False

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

    bot.send_message(
        chat_id,
        f"🛡️ **Anti-Bot Verification**\n\nTo prove you are a human, please select the correct answer for the following math problem:\n\n**{num1} + {num2} = ?**",
        reply_markup=markup
    )

# --- Background Tasks ---
def session_cleanup_task():
    """Remove expired auth tokens and old referral records."""
    while True:
        time.sleep(180)
        try:
            db, sha = get_db()
            changes_made = False
            now = time.time()
            # Clean auth keys
            for key in list(db.keys()):
                if key.startswith("auth_"):
                    if now > db[key]:
                        del db[key]
                        changes_made = True
            # Clean old used_refs (older than 30 days)
            if "used_refs" in db and isinstance(db["used_refs"], list):
                if len(db["used_refs"]) > 1000:
                    db["used_refs"] = db["used_refs"][-1000:]
                    changes_made = True
            if changes_made:
                save_db(db, sha)
                logger.info("Session cleanup: removed expired tokens and trimmed used_refs.")
        except Exception as e:
            logger.error(f"Session cleanup error: {e}")

def check_new_posts_task():
    """Monitor Blogger for new video posts and notify users."""
    if not BLOG_URL:
        logger.warning("BLOG_URL not set. Disabling post checker.")
        return
    while True:
        try:
            feed_url = f"https://{BLOG_URL}/feeds/posts/default/-/Video?alt=json&max-results=1"
            data = requests.get(feed_url, timeout=10).json()
            entries = data.get('feed', {}).get('entry', [])
            if entries:
                latest_post = entries[0]
                post_id = latest_post.get('id', {}).get('$t')
                title = latest_post.get('title', {}).get('$t', 'New Video')
                db, sha = get_db()
                saved_last_id = db.get("last_post_id")
                if saved_last_id != post_id:
                    db["last_post_id"] = post_id
                    users = db.get("users", [])
                    save_db(db, sha)
                    if saved_last_id is not None:  # Only notify if we had a previous post
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton("🚀 Watch Now", url=f"https://t.me/{BOT_USERNAME}?start=menu"))
                        msg = f"🔥 **New Video Uploaded!**\n\n🎬 {title}\n\nClick the button below to watch it now 👇"
                        for user_id in users:
                            try:
                                bot.send_message(user_id, msg, reply_markup=markup)
                                time.sleep(0.3)
                            except Exception as e:
                                logger.warning(f"Failed to notify user {user_id}: {e}")
        except Exception as e:
            logger.error(f"Post checker error: {e}")
        time.sleep(30)

threading.Thread(target=session_cleanup_task, daemon=True).start()
threading.Thread(target=check_new_posts_task, daemon=True).start()

# --- Media Processing ---
def process_and_send_media(chat_id, media_data):
    images = media_data.get("images", [])
    video_url = media_data.get("video")

    if images:
        try:
            media_group = [types.InputMediaPhoto(url) for url in images[:10]]
            bot.send_media_group(chat_id, media_group)
        except Exception as e:
            logger.error(f"Failed to send images: {e}")

    if video_url:
        expire_timestamp = int(time.time()) + 3600
        raw_data = f"{video_url}:::{expire_timestamp}"
        encoded_data = base64.b64encode(raw_data.encode('utf-8')).decode('utf-8')
        base_url = VERCEL_URL.rstrip('/') if VERCEL_URL else ""
        player_url = f"{base_url}/player.html?data={encoded_data}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🍿 Watch Secure Player", url=player_url))
        bot.send_message(
            chat_id,
            "✅ **Your Video is Ready!**\n\nClick the button below to watch it securely.\n⚠️ *(This player link will automatically expire in 1 hour)*",
            reply_markup=markup
        )
    else:
        bot.send_message(chat_id, "⚠️ No video link found for this entry.")

# --- Fetch Blogger Videos (with pagination) ---
def get_blogger_videos_keyboard(page=1, search_query=None, per_page=10):
    """Fetch videos from Blogger and return paginated inline keyboard."""
    if search_query:
        feed_url = f"https://{BLOG_URL}/feeds/posts/default/-/Video?alt=json&q={search_query}&max-results=50"
    else:
        feed_url = f"https://{BLOG_URL}/feeds/posts/default/-/Video?alt=json&max-results=50"
    try:
        data = requests.get(feed_url, timeout=10).json()
        entries = data.get('feed', {}).get('entry', [])
        db, sha = get_db()
        db_changed = False
        # Store each video in DB and collect items
        video_items = []
        for entry in entries:
            title = entry.get('title', {}).get('$t', 'Video')
            content = entry.get('content', {}).get('$t', '')
            images = re.findall(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', content, re.IGNORECASE)
            all_links = re.findall(r'(?:src|href)=["\'](https?://[^"\']+)["\']', content, re.IGNORECASE)
            # Heuristic: links that are not images and not typical static file extensions
            videos = [l for l in all_links if l not in images and not l.lower().endswith(('.jpg','.jpeg','.png','.css','.js','.gif'))]
            if videos or images:
                vid_id = str(hash(title + (videos[0] if videos else images[0])))
                db[vid_id] = {"images": images[:5], "video": videos[0] if videos else None}
                db_changed = True
                video_items.append((vid_id, title))
        if db_changed:
            save_db(db, sha)
        # Pagination
        total = len(video_items)
        start = (page - 1) * per_page
        end = start + per_page
        page_items = video_items[start:end]
        markup = types.InlineKeyboardMarkup(row_width=1)
        for vid_id, title in page_items:
            markup.add(types.InlineKeyboardButton(f"🎬 {title}", callback_data=f"getvid_{vid_id}"))
        # Navigation buttons
        nav_buttons = []
        if page > 1:
            nav_buttons.append(types.InlineKeyboardButton("◀️ Back", callback_data=f"page_{page-1}"))
        if end < total:
            nav_buttons.append(types.InlineKeyboardButton("Next ▶️", callback_data=f"page_{page+1}"))
        if nav_buttons:
            markup.add(*nav_buttons)
        return markup if page_items else None
    except Exception as e:
        logger.error(f"Error fetching videos: {e}")
        return None

# --- Main Command Processor ---
def process_user_command(chat_id, text, db, sha):
    if "used_refs" not in db:
        db["used_refs"] = []

    # Handle referral link
    if text.startswith('/start ref_'):
        try:
            referrer_id = int(text.split('_')[1])
            if referrer_id != chat_id and chat_id not in db["used_refs"]:
                db["used_refs"].append(chat_id)
                current_auth = db.get(f"auth_{referrer_id}", time.time())
                if current_auth < time.time():
                    current_auth = time.time()
                db[f"auth_{referrer_id}"] = current_auth + 86400
                save_db(db, sha)
                db, sha = get_db()
                try:
                    bot.send_message(referrer_id, "🎉 **Congratulations!**\nA new member joined using your referral link, so you have received an **additional 24 hours of VIP Access!**")
                except Exception as e:
                    logger.warning(f"Failed to notify referrer {referrer_id}: {e}")
        except Exception as e:
            logger.error(f"Referral processing error: {e}")

    # Check subscription
    if not check_sub(chat_id):
        channel_link = CHANNEL_USERNAME.replace('@', '') if CHANNEL_USERNAME else ""
        markup = types.InlineKeyboardMarkup()
        if channel_link:
            markup.add(types.InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{channel_link}"))
        markup.add(types.InlineKeyboardButton("✅ Check Subscription", callback_data="check_sub"))
        bot.send_message(
            chat_id,
            "⚠️ **You must join our channel before using the bot!**\n\nClick the button below to join, then click 'Check Subscription'.",
            reply_markup=markup
        )
        return

    # Search command
    if text.startswith('/search'):
        query = text.replace('/search', '').strip()
        if not query:
            bot.send_message(chat_id, "🔍 **Search Videos**\n\nPlease enter the movie/video name after the command.\n\nExample: `/search Avengers`", parse_mode="Markdown")
            return
        bot.send_chat_action(chat_id, 'typing')
        markup = get_blogger_videos_keyboard(page=1, search_query=query)
        if markup:
            bot.send_message(chat_id, f"🔍 Search Results for: **{query}**", parse_mode="Markdown", reply_markup=markup)
        else:
            bot.send_message(chat_id, f"❌ No videos found for: **{query}**\nPlease try another keyword.", parse_mode="Markdown")
        return

    # /start or /start menu
    if text == '/start' or text.startswith('/start ref_') or text == '/start menu':
        bot.send_chat_action(chat_id, 'typing')
        markup = get_blogger_videos_keyboard(page=1)
        if markup:
            bot.send_message(
                chat_id,
                "👋 Welcome!\n\nSelect a video below to generate your unique Ad link:\n\n*(Type /refer to invite friends and get VIP access. Type /search <name> to find videos. Type /help for commands.)*",
                reply_markup=markup
            )
        else:
            bot.send_message(chat_id, "No videos found. Please try again later.")
        return

    # /refer
    if text == '/refer':
        bot.send_chat_action(chat_id, 'typing')
        long_ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{chat_id}"
        short_ref_link = create_short_link(long_ref_link)
        bot.send_message(
            chat_id,
            f"🎁 **Your Referral Link:**\n\n👉 `{short_ref_link}`\n\nShare this link with your friends. When they click it and start the bot, you will get **24 hours of VIP Access** completely free!",
            parse_mode="Markdown"
        )
        return

    # /help
    if text == '/help':
        help_text = (
            "🤖 **Available Commands**\n\n"
            "/start - Show video list\n"
            "/search <name> - Search for a video\n"
            "/refer - Get your referral link\n"
            "/stats - View bot statistics (users count)\n"
            "/help - Show this help"
        )
        if ADMIN_ID and str(chat_id) == ADMIN_ID:
            help_text += "\n\n**Admin Commands:**\n/admin broadcast <message> - Send broadcast to all users"
        bot.send_message(chat_id, help_text, parse_mode="Markdown")
        return

    # /stats
    if text == '/stats':
        db, _ = get_db()
        users_count = len(db.get("users", []))
        bot.send_message(chat_id, f"📊 **Bot Statistics**\n\n👥 Total Users: {users_count}")
        return

    # Admin broadcast (only if ADMIN_ID set and matches)
    if ADMIN_ID and str(chat_id) == ADMIN_ID and text.startswith('/admin broadcast'):
        msg = text.replace('/admin broadcast', '', 1).strip()
        if not msg:
            bot.send_message(chat_id, "Please provide a message to broadcast.\nExample: `/admin broadcast Hello everyone!`")
            return
        db, _ = get_db()
        users = db.get("users", [])
        sent = 0
        for uid in users:
            try:
                bot.send_message(uid, f"📢 **Broadcast Message**\n\n{msg}")
                sent += 1
                time.sleep(0.2)
            except Exception as e:
                logger.warning(f"Broadcast failed to {uid}: {e}")
        bot.send_message(chat_id, f"✅ Broadcast sent to {sent} users.")
        return

    # Normal token processing
    if text.startswith('/start '):
        token = text.split()[1]
    else:
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
        if not text.startswith('/'):
            bot.send_message(chat_id, "❌ Invalid Key! The key is incorrect, expired, or has already been used.")

# --- Bot Callbacks ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('captcha_'))
def handle_captcha(call):
    chat_id = call.message.chat.id
    if call.data == "captcha_correct":
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        bot.answer_callback_query(call.id, "✅ Verification Successful!")
        db, sha = get_db()
        if "users" not in db:
            db["users"] = []
        if chat_id not in db["users"]:
            db["users"].append(chat_id)
            save_db(db, sha)
            db, sha = get_db()
        original_cmd = pending_users.pop(chat_id, '/start')
        process_user_command(chat_id, original_cmd, db, sha)
    else:
        bot.answer_callback_query(call.id, "❌ Incorrect answer! Please try again.", show_alert=True)
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        send_captcha(chat_id)

@bot.callback_query_handler(func=lambda call: call.data == 'check_sub')
def handle_check_sub(call):
    chat_id = call.message.chat.id
    if check_sub(chat_id):
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        bot.send_message(chat_id, "✅ **Thank you! You have successfully joined the channel.**\n\nType /start to watch videos.")
    else:
        bot.answer_callback_query(call.id, "❌ You haven't joined the channel yet! Please join and try again.", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('getvid_'))
def handle_request(call):
    vid_id = call.data.split('_')[1]
    chat_id = call.message.chat.id
    db, sha = get_db()

    if db.get(f"auth_{chat_id}", 0) > time.time():
        media_data = db.get(vid_id)
        if media_data:
            bot.answer_callback_query(call.id, "✅ Unlocked! Generating Player...")
            threading.Thread(target=process_and_send_media, args=(chat_id, media_data)).start()
        return

    # Generate token for ad view
    token = str(uuid.uuid4().hex)[:10]
    db[f"token_{token}"] = vid_id
    save_db(db, sha)

    base_url = VERCEL_URL.rstrip('/') if VERCEL_URL else ""
    short_url = create_short_link(f"{base_url}/index.html?key={token}")

    bot.send_message(
        chat_id,
        f"🔗 Click the link below, watch the Ad, and get your verification key!\n\n👉 {short_url}\n\n⚠️ **Instruction:** Send the key back to me. **(This will unlock ALL videos for 1 hour!)**"
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('page_'))
def handle_pagination(call):
    page = int(call.data.split('_')[1])
    chat_id = call.message.chat.id
    markup = get_blogger_videos_keyboard(page=page)
    if markup:
        bot.edit_message_text("📹 **Video List** (choose one):", chat_id, call.message.message_id, reply_markup=markup)
    else:
        bot.answer_callback_query(call.id, "No more videos.", show_alert=True)

# --- Message Handler ---
@bot.message_handler(func=lambda m: True)
def handle_text(message):
    text = message.text.strip()
    chat_id = message.chat.id
    db, sha = get_db()

    if "users" not in db:
        db["users"] = []

    if chat_id not in db["users"]:
        pending_users[chat_id] = text
        send_captcha(chat_id)
        return

    process_user_command(chat_id, text, db, sha)

# --- Flask App for Health Check (Back4App/Railway) ---
from flask import Flask
from waitress import serve  # Added Waitress to fix the warning

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is alive and running successfully!", 200

def run_bot():
    logger.info("Bot Version 2.0 (Polling Mode) is running...")
    bot.infinity_polling()

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    # Used Waitress server instead of the default Flask development server
    serve(app, host="0.0.0.0", port=port)
