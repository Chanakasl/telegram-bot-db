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
import yt_dlp
import uuid
from github import Github

# Railway Environment Variables
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME")
SHORTENER_API = os.environ.get("SHORTENER_API") # අලුත් API Key එක Railway එකෙන් ගනී
BOT_USERNAME = os.environ.get("BOT_USERNAME")
BLOG_URL = os.environ.get("BLOG_URL")
VERCEL_URL = os.environ.get("VERCEL_URL") 

bot = telebot.TeleBot(TELEGRAM_TOKEN)
github = Github(GITHUB_TOKEN)
repo = github.get_repo(GITHUB_REPO_NAME)

# --- Background Task (Session Cleanup) ---
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
        except Exception: 
            pass

threading.Thread(target=session_cleanup_task, daemon=True).start()

# --- Helper Functions ---
def get_db():
    try:
        content = repo.get_contents("database.json")
        return json.loads(content.decoded_content.decode()), content.sha
    except Exception: 
        return {}, None

def save_db(data, sha): 
    repo.update_file("database.json", "Update DB", json.dumps(data), sha)

# --- ShrinkEarn API එකට යාවත්කාලීන කළ කොටස ---
def create_short_link(long_url):
    api = f"https://shrinkearn.com/api?api={SHORTENER_API}&url={long_url}"
    try: 
        return requests.get(api).json().get('shortenedUrl', long_url)
    except Exception as e: 
        print(f"Shortener Error: {e}")
        return long_url

# --- Media Processing (Photos + Video Download & Send) ---
def process_and_send_media(chat_id, media_data):
    images = media_data.get("images", [])
    video_url = media_data.get("video")
    
    wait_msg = bot.send_message(chat_id, "⏳ ගොනු සූදානම් වෙමින් පවතී. කරුණාකර රැඳී සිටින්න...")
    
    if images:
        try:
            media_group = [types.InputMediaPhoto(url) for url in images[:10]]
            bot.send_media_group(chat_id, media_group)
        except Exception as e:
            print(f"Photos Error: {e}")

    if video_url:
        bot.send_chat_action(chat_id, 'upload_video')
        try:
            ydl_opts = {'outtmpl': f'video_{chat_id}_%(id)s.%(ext)s', 'format': 'best', 'quiet': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                filename = ydl.prepare_filename(info)
            
            with open(filename, 'rb') as f:
                bot.send_video(chat_id, f, caption="✅ ස්තූතියි! මෙන්න ඔබගේ වීඩියෝව.")
            
            os.remove(filename)
        except Exception as e:
            bot.send_message(chat_id, f"❌ වීඩියෝවේ ප්‍රමාණය විශාල බැවින් කෙලින්ම යැවීමට නොහැක. කරුණාකර පහත ලින්ක් එකෙන් නරඹන්න:\n\n🔗 {video_url}")
            
    try:
        bot.delete_message(chat_id, wait_msg.message_id)
    except Exception:
        pass

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
            videos = [l for l in all_links if l not in images and not l.lower().endswith(('.jpg','.jpeg','.png','.css','.js'))]
            
            if videos or images:
                vid_id = str(hash(title + (videos[0] if videos else images[0]))) 
                db[vid_id] = {"images": images[:5], "video": videos[0] if videos else None}
                db_changed = True
                markup.add(types.InlineKeyboardButton(f"🎬 {title}", callback_data=f"getvid_{vid_id}"))
        
        if db_changed: 
            save_db(db, sha)
        return markup
    except Exception as e: 
        print(f"Blogger Fetch Error: {e}")
        return None

# --- Bot Commands & Callbacks ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('getvid_'))
def handle_request(call):
    vid_id = call.data.split('_')[1]
    chat_id = call.message.chat.id
    db, sha = get_db()
    
    # 1 Hour VIP check
    if db.get(f"auth_{chat_id}", 0) > time.time():
        media_data = db.get(vid_id)
        if media_data:
            bot.answer_callback_query(call.id, "✅ Unlocked! Sending...")
            threading.Thread(target=process_and_send_media, args=(chat_id, media_data)).start()
        return

    # Generate Token and Send Link
    token = str(uuid.uuid4().hex)[:10]
    db[f"token_{token}"] = vid_id
    save_db(db, sha)
    
    base_url = VERCEL_URL.rstrip('/')
    short_url = create_short_link(f"{base_url}/?key={token}")
    
    bot.send_message(
        chat_id, 
        f"🔗 Click the link below, watch the Ad, and get your verification key!\n\n👉 {short_url}\n\n⚠️ **Instruction:** Send the key back to me. **(This will unlock ALL videos for 1 hour!)**"
    )
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    text = message.text.strip()
    chat_id = message.chat.id
    
    if text == '/start':
        bot.send_chat_action(chat_id, 'typing')
        markup = get_blogger_videos_keyboard()
        if markup:
            bot.send_message(chat_id, "👋 Welcome!\n\nSelect a video below to generate your unique Ad link:", reply_markup=markup)
        else:
            bot.send_message(chat_id, "No videos found. Please try again later.")
        return
    
    # Key Verification
    db, sha = get_db()
    
    if text.startswith('/start '):
        token = text.split()[1]
    else:
        token = text
        
    token_key = f"token_{token}"
    
    if token_key in db:
        vid_id = db[token_key]
        
        # Grant 1 Hour Access
        db[f"auth_{chat_id}"] = time.time() + 3600
        
        media_data = db.get(vid_id)
        if media_data:
            bot.send_message(chat_id, "🎉 **Success! The Bot is now unlocked for 1 HOUR.**")
            threading.Thread(target=process_and_send_media, args=(chat_id, media_data)).start()
            
            # Delete token
            del db[token_key]
            save_db(db, sha)
        else:
            bot.send_message(chat_id, "❌ Error retrieving video data.")
    else:
        if not text.startswith('/'):
            bot.send_message(chat_id, "❌ Invalid Key! The key is incorrect, expired, or has already been used.")

print("Bot is running...")
bot.polling(none_stop=True)
