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
from github import Github

# Railway Environment Variables
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME")
SHORTENER_API = os.environ.get("SHORTENER_API")
BOT_USERNAME = os.environ.get("BOT_USERNAME")
BLOG_URL = os.environ.get("BLOG_URL")
GITHUB_PAGES_URL = os.environ.get("GITHUB_PAGES_URL")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
github = Github(GITHUB_TOKEN)
repo = github.get_repo(GITHUB_REPO_NAME)

# Session Cleanup Task (පැය ඉවර වූ අය ස්වයංක්‍රීයව ඉවත් කිරීම)
def session_cleanup_task():
    while True:
        time.sleep(180)
        try:
            db, sha = get_db()
            changes_made = False
            for key in list(db.keys()):
                if key.startswith("auth_"):
                    if time.time() > db[key]:
                        del db[key]
                        changes_made = True
            if changes_made:
                save_db(db, sha)
        except: pass

threading.Thread(target=session_cleanup_task, daemon=True).start()

# --- Helpers ---
def get_db():
    try:
        file_content = repo.get_contents("database.json")
        return json.loads(file_content.decoded_content.decode()), file_content.sha
    except: return {}, None

def save_db(data, sha):
    repo.update_file("database.json", "Update DB", json.dumps(data), sha)

def create_short_link(long_url):
    api_url = f"https://shrinkme.io/api?api={SHORTENER_API}&url={long_url}"
    try:
        res = requests.get(api_url).json()
        return res.get('shortenedUrl', long_url)
    except: return long_url

# --- Main Logic ---
def get_blogger_videos_keyboard():
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
            videos = [l for l in all_links if l not in images and not l.lower().endswith(('.jpg','.png','.css','.js'))]
            
            if videos:
                vid_id = str(hash(videos[0]))
                db[vid_id] = {"images": images[:5], "video": videos[0]}
                db_changed = True
                markup.add(types.InlineKeyboardButton(f"🎬 {title}", callback_data=f"getvid_{vid_id}"))
        
        if db_changed: save_db(db, sha)
        return markup
    except: return None

@bot.callback_query_handler(func=lambda call: call.data.startswith('getvid_'))
def handle_video_request(call):
    vid_id = call.data.split('_')[1]
    chat_id = call.message.chat.id
    db, _ = get_db()
    
    # VIP Session check
    if db.get(f"auth_{chat_id}", 0) > time.time():
        send_final_links(chat_id, db[vid_id])
        return

    # Generate new UUID Key
    token = str(uuid.uuid4().hex)[:10]
    db[f"token_{token}"] = vid_id
    save_db(db, _)
    
    short_url = create_short_link(f"{GITHUB_PAGES_URL.rstrip('/')}/index.html?key={token}")
    bot.send_message(chat_id, f"🔗 Click to get your VIP Key: {short_url}\n\n⚠️ Send the key back to me to unlock ALL videos for 1 hour!")

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    chat_id = message.chat.id
    text = message.text.strip()
    
    if text == '/start':
        markup = get_blogger_videos_keyboard()
        bot.send_message(chat_id, "🎬 Welcome! Select a video:", reply_markup=markup)
        return
        
    db, sha = get_db()
    if f"token_{text}" in db:
        vid_id = db[f"token_{text}"]
        db[f"auth_{chat_id}"] = time.time() + 3600
        del db[f"token_{text}"]
        save_db(db, sha)
        bot.send_message(chat_id, "🎉 **VIP Unlocked!** You can now watch videos for 1 hour.")
        send_final_links(chat_id, db[vid_id])
    else:
        if not text.startswith('/'): bot.send_message(chat_id, "❌ Invalid or Expired Key.")

def send_final_links(chat_id, media):
    if media.get("images"):
        bot.send_media_group(chat_id, [types.InputMediaPhoto(u) for u in media["images"]])
    
    # වීඩියෝ ලින්ක් එක Base64 කරලා රීඩිරෙක්ට් පේජ් එකට යවනවා
    encoded = base64.b64encode(media["video"].encode()).decode()
    redirect_url = f"{GITHUB_PAGES_URL.rstrip('/')}/redirect.html?src={encoded}"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🍿 Unlock Video", url=redirect_url))
    bot.send_message(chat_id, "✅ Your verification is successful. Click below to access:", reply_markup=markup)


print("Bot is running...")
bot.polling()
