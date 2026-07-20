import os
import telebot
from telebot import types
import requests
import json
import string
import random
import time
import re
import uuid
import base64
from github import Github, Auth
from flask import Flask, request

# Variables
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME")
SHORTENER_API = os.environ.get("SHORTENER_API")
BOT_USERNAME = os.environ.get("BOT_USERNAME")
BLOG_URL = os.environ.get("BLOG_URL")
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME")

# අලුත් HOST_URL එක භාවිතය
HOST_URL = os.environ.get("HOST_URL") 
if HOST_URL and not HOST_URL.startswith("http"):
    HOST_URL = "https://" + HOST_URL

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

auth = Auth.Token(GITHUB_TOKEN)
github = Github(auth=auth)
repo = github.get_repo(GITHUB_REPO_NAME)

# --- Auto Webhook Setup ---
try:
    if HOST_URL:
        webhook_url = HOST_URL.rstrip('/') + '/webhook'
        current_webhook = bot.get_webhook_info().url
        if current_webhook != webhook_url:
            bot.remove_webhook()
            time.sleep(1) 
            bot.set_webhook(url=webhook_url, drop_pending_updates=True)
            print("✅ Webhook Auto-Configured to HOST_URL!")
except Exception as e:
    print("❌ Webhook setup error:", e)

# --- Helper Functions ---
def get_db():
    try:
        content = repo.get_contents("database.json")
        return json.loads(content.decoded_content.decode()), content.sha
    except Exception: 
        return {}, None

def save_db(data, sha): 
    repo.update_file("database.json", "Update DB", json.dumps(data), sha)

def create_short_link(long_url):
    api = f"https://shrinkearn.com/api?api={SHORTENER_API}&url={long_url}"
    try: 
        return requests.get(api).json().get('shortenedUrl', long_url)
    except Exception: 
        return long_url

def check_sub(user_id):
    if not CHANNEL_USERNAME: return True
    try:
        status = bot.get_chat_member(CHANNEL_USERNAME, user_id).status
        return status in ['creator', 'administrator', 'member']
    except Exception:
        return False

# --- Anti-Bot CAPTCHA ---
def send_captcha(chat_id):
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    ans = num1 + num2
    options = {ans}
    while len(options) < 4: options.add(random.randint(1, 20))
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
        f"🛡️ **Anti-Bot Verification**\n\nTo prove you are a human, please select the correct answer:\n\n**{num1} + {num2} = ?**", 
        reply_markup=markup
    )

def process_and_send_media(chat_id, media_data):
    images = media_data.get("images", [])
    video_url = media_data.get("video")
    if images:
        try:
            media_group = [types.InputMediaPhoto(url) for url in images[:10]]
            bot.send_media_group(chat_id, media_group)
        except Exception: pass

    if video_url:
        expire_timestamp = int(time.time()) + 3600 
        raw_data = f"{video_url}:::{expire_timestamp}"
        encoded_data = base64.b64encode(raw_data.encode('utf-8')).decode('utf-8')
        base_url = HOST_URL.rstrip('/') if HOST_URL else ""
        player_url = f"{base_url}/player.html?data={encoded_data}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🍿 Watch Secure Player", url=player_url))
        bot.send_message(chat_id, "✅ **Your Video is Ready!**\n\nClick the button below to watch it securely.", reply_markup=markup)

def get_blogger_videos_keyboard(search_query=None):
    if search_query:
        feed_url = f"https://{BLOG_URL}/feeds/posts/default/-/Video?alt=json&q={search_query}&max-results=50"
    else:
        feed_url = f"https://{BLOG_URL}/feeds/posts/default/-/Video?alt=json&max-results=50"
        
    markup = types.InlineKeyboardMarkup(row_width=1)
    try:
        data = requests.get(feed_url).json()
        entries = data.get('feed', {}).get('entry', [])
        db, sha = get_db()
        db_changed = False
        
        for entry in entries:
            title = entry.get('title', {}).get('$t', 'Video')
            content = entry.get('content', {}).get('$t', '')
            images = re.findall(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', content, re.IGNORECASE)
            all_links = re.findall(r'(?:src|href)=["\'](https?://[^"\']+)["\']', content, re.IGNORECASE)
            videos = [l for l in all_links if l not in images and not l.lower().endswith(('.jpg','.jpeg','.png','.css','.js'))]
            
            if videos or images:
                vid_id = str(hash(title + (videos[0] if videos else images[0]))) 
                db[vid_id] = {"images": images[:5], "video": videos[0] if videos else None}
                db_changed = True
                markup.add(types.InlineKeyboardButton(f"🎬 {title}", callback_data=f"getvid_{vid_id}"))
        
        if db_changed: save_db(db, sha)
        if len(markup.keyboard) > 0: return markup
        return None
    except Exception: 
        return None

def process_user_command(chat_id, text, db, sha):
    if "used_refs" not in db: db["used_refs"] = []
        
    if text.startswith('/start ref_'):
        try:
            referrer_id = int(text.split('_')[1])
            if referrer_id != chat_id and chat_id not in db["used_refs"]:
                db["used_refs"].append(chat_id) 
                current_auth = db.get(f"auth_{referrer_id}", time.time())
                db[f"auth_{referrer_id}"] = max(current_auth, time.time()) + 86400
                save_db(db, sha)
                db, sha = get_db()
                try: bot.send_message(referrer_id, "🎉 **Congratulations!**\nA new member joined using your referral link!")
                except Exception: pass
        except Exception: pass

    if not check_sub(chat_id):
        channel_link = CHANNEL_USERNAME.replace('@', '') if CHANNEL_USERNAME else ""
        markup = types.InlineKeyboardMarkup()
        if channel_link: markup.add(types.InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{channel_link}"))
        markup.add(types.InlineKeyboardButton("✅ Check Subscription", callback_data="check_sub"))
        bot.send_message(chat_id, "⚠️ **You must join our channel before using the bot!**", reply_markup=markup)
        return

    if text.startswith('/search'):
        query = text.replace('/search', '').strip()
        if not query:
            bot.send_message(chat_id, "🔍 Please enter the video name after the command.")
            return
        bot.send_chat_action(chat_id, 'typing')
        markup = get_blogger_videos_keyboard(search_query=query)
        if markup: bot.send_message(chat_id, f"🔍 Search Results for: **{query}**", parse_mode="Markdown", reply_markup=markup)
        else: bot.send_message(chat_id, f"❌ No videos found.", parse_mode="Markdown")
        return

    if text == '/start' or text.startswith('/start ref_') or text == '/start menu':
        bot.send_chat_action(chat_id, 'typing')
        markup = get_blogger_videos_keyboard()
        if markup: bot.send_message(chat_id, "👋 Welcome! Select a video below:", reply_markup=markup)
        else: bot.send_message(chat_id, "No videos found.")
        return
        
    if text == '/refer':
        long_ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{chat_id}"
        short_ref_link = create_short_link(long_ref_link)
        bot.send_message(chat_id, f"🎁 **Your Referral Link:**\n\n👉 `{short_ref_link}`")
        return
    
    if text.startswith('/start '): token = text.split()[1]
    else: token = text
        
    token_key = f"token_{token}"
    if token_key in db:
        vid_id = db[token_key]
        db[f"auth_{chat_id}"] = time.time() + 3600
        media_data = db.get(vid_id)
        if media_data:
            bot.send_message(chat_id, "🎉 **Success! The Bot is unlocked for 1 HOUR.**")
            process_and_send_media(chat_id, media_data)
            del db[token_key]
            save_db(db, sha)
        else: bot.send_message(chat_id, "❌ Error retrieving video.")
    else:
        if not text.startswith('/'): bot.send_message(chat_id, "❌ Invalid Key!")

# --- Telegram Handlers ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('captcha_'))
def handle_captcha(call):
    chat_id = call.message.chat.id
    if call.data == "captcha_correct":
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        bot.answer_callback_query(call.id, "✅ Verification Successful!")
        
        db, sha = get_db()
        if "users" not in db: db["users"] = []
        if "pending_users" not in db: db["pending_users"] = {}
            
        if chat_id not in db["users"]:
            db["users"].append(chat_id)
            
        original_cmd = db["pending_users"].pop(str(chat_id), '/start')
        save_db(db, sha)
        process_user_command(chat_id, original_cmd, db, sha)
    else:
        bot.answer_callback_query(call.id, "❌ Incorrect answer!", show_alert=True)
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        send_captcha(chat_id)

@bot.callback_query_handler(func=lambda call: call.data == 'check_sub')
def handle_check_sub(call):
    chat_id = call.message.chat.id
    if check_sub(chat_id):
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        bot.send_message(chat_id, "✅ **Thank you! Type /start to watch videos.**")
    else:
        bot.answer_callback_query(call.id, "❌ You haven't joined yet!", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('getvid_'))
def handle_request(call):
    vid_id = call.data.split('_')[1]
    chat_id = call.message.chat.id
    db, sha = get_db()
    
    if db.get(f"auth_{chat_id}", 0) > time.time():
        media_data = db.get(vid_id)
        if media_data:
            bot.answer_callback_query(call.id, "✅ Generating Player...")
            process_and_send_media(chat_id, media_data)
        return

    token = str(uuid.uuid4().hex)[:10]
    db[f"token_{token}"] = vid_id
    save_db(db, sha)
    
    base_url = HOST_URL.rstrip('/') if HOST_URL else ""
    short_url = create_short_link(f"{base_url}/index.html?key={token}")
    bot.send_message(chat_id, f"🔗 Watch the Ad and get your key!\n👉 {short_url}")
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    text = message.text.strip()
    chat_id = message.message.chat.id
    db, sha = get_db()
    
    if "users" not in db: db["users"] = []
    if "pending_users" not in db: db["pending_users"] = {}
        
    if chat_id not in db["users"]:
        db["pending_users"][str(chat_id)] = text
        save_db(db, sha)
        send_captcha(chat_id)
        return
        
    process_user_command(chat_id, text, db, sha)

# --- Webhook & Flask Routes ---
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return 'Error', 403

@app.route('/setwebhook')
def setwebhook():
    try:
        webhook_url = HOST_URL.rstrip('/') + '/webhook'
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=webhook_url, drop_pending_updates=True)
        return f"✅ Webhook Reset & Cache Cleared!<br>New Webhook: {webhook_url}", 200
    except Exception as e:
        return f"❌ Error: {str(e)}", 500

@app.route('/cron')
def cron_tasks():
    try:
        db, sha = get_db()
        changes_made = False
        
        for key in list(db.keys()):
            if key.startswith("auth_") and time.time() > db[key]:
                del db[key]
                changes_made = True
                
        feed_url = f"https://{BLOG_URL}/feeds/posts/default/-/Video?alt=json&max-results=1"
        data = requests.get(feed_url).json()
        entries = data.get('feed', {}).get('entry', [])
        
        if entries:
            post_id = entries[0].get('id', {}).get('$t')
            title = entries[0].get('title', {}).get('$t', 'New Video')
            if db.get("last_post_id") != post_id:
                db["last_post_id"] = post_id
                changes_made = True
                if db.get("last_post_id") is not None:
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("🚀 Watch Now", url=f"https://t.me/{BOT_USERNAME}?start=menu"))
                    msg = f"🔥 **New Video Uploaded!**\n\n🎬 {title}\n\nClick the button below 👇"
                    for user_id in db.get("users", []):
                        try: bot.send_message(user_id, msg, reply_markup=markup)
                        except Exception: pass
                        
        if changes_made: save_db(db, sha)
        return "Cron Job Completed!", 200
    except Exception as e:
        return str(e), 500

@app.route('/')
def index():
    return "Bot is running perfectly on Vercel and Webhook Cache is Cleared!", 200
