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
GITHUB_PAGES_URL = os.environ.get("GITHUB_PAGES_URL") # උදා: https://user.github.io/repo/

bot = telebot.TeleBot(TELEGRAM_TOKEN)
github = Github(GITHUB_TOKEN)
repo = github.get_repo(GITHUB_REPO_NAME)

def generate_id(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def get_db():
    try:
        file_content = repo.get_contents("database.json")
        return json.loads(file_content.decoded_content.decode()), file_content.sha
    except Exception:
        return {}, None

def save_db(data, sha):
    if sha:
        repo.update_file("database.json", "Update DB", json.dumps(data), sha)
    else:
        repo.create_file("database.json", "Create DB", json.dumps(data))

def create_short_link(long_url):
    api_url = f"https://shrinkme.io/api?api={SHORTENER_API}&url={long_url}"
    try:
        response = requests.get(api_url).json()
        if response.get('status') == 'success':
            return response['shortenedUrl']
    except Exception as e:
        print(f"Shortener Error: {e}")
    return long_url

def auto_delete_message(chat_id, message_id, delay=1800): 
    def delay_delete():
        time.sleep(delay)
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass
    threading.Thread(target=delay_delete).start()

def session_cleanup_task():
    while True:
        time.sleep(180) 
        try:
            db, sha = get_db()
            changes_made = False
            expired_users = []
            
            for key in list(db.keys()):
                if key.startswith("auth_"):
                    expire_time = db[key]
                    if time.time() > expire_time:
                        chat_id = key.split("_")[1]
                        expired_users.append(chat_id)
                        del db[key]
                        changes_made = True
            
            if changes_made:
                save_db(db, sha)
                for chat_id in expired_users:
                    try:
                        bot.send_message(
                            chat_id, 
                            "⏱️ **Your 1-hour VIP session has ended!**\n\nYou will need to watch an Ad again to unlock the next video."
                        )
                    except Exception:
                        pass
        except Exception as e:
            print(f"Cleanup Error: {e}")

threading.Thread(target=session_cleanup_task, daemon=True).start()

def get_blogger_videos_keyboard():
    feed_url = f"https://{BLOG_URL}/feeds/posts/default/-/Video?alt=json&max-results=50"
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    try:
        response = requests.get(feed_url).json()
        entries = response.get('feed', {}).get('entry', [])
        
        if not entries:
            return None

        db, sha = get_db()
        db_changed = False

        for entry in entries:
            title = entry.get('title', {}).get('$t', 'Video')
            content = entry.get('content', {}).get('$t', '')
            
            images = re.findall(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', content, re.IGNORECASE)
            all_links = re.findall(r'(?:src|href)=["\'](https?://[^"\']+)["\']', content, re.IGNORECASE)
            videos = []
            
            for link in all_links:
                link_lower = link.lower()
                if link not in images and not link_lower.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.css', '.js')):
                    if 'video.g' in link_lower or 'youtube.com' in link_lower or 'youtu.be' in link_lower or '.mp4' in link_lower:
                        if link not in videos:
                            videos.append(link)
            
            real_video_url = videos[0] if videos else None
            
            if images or real_video_url:
                post_data = {
                    "images": images,
                    "video": real_video_url
                }
                
                video_id = None
                for k, v in db.items():
                    if isinstance(v, dict):
                        if v.get("video") == real_video_url and v.get("images") == images:
                            video_id = k
                            break
                
                if not video_id:
                    video_id = generate_id()
                    db[video_id] = post_data
                    db_changed = True
                
                button = types.InlineKeyboardButton(text=f"🎬 {title}", callback_data=f"getvid_{video_id}")
                markup.add(button)

        if db_changed:
            save_db(db, sha)
            
        return markup
    except Exception as e:
        print(f"Blogger Fetch Error: {e}")
        return None

# අලුත් Media යවන Function එක (Video එක Download කරන්නේ නැත)
def process_and_send_media(chat_id, media_data):
    images = media_data.get("images", [])
    video_url = media_data.get("video")
    
    # 1. Photos තියෙනවා නම් සාමාන්‍ය විදිහට යවනවා
    if images:
        try:
            media_group = [types.InputMediaPhoto(url) for url in images[:10]]
            sent_photos = bot.send_media_group(chat_id, media_group)
            for p_msg in sent_photos:
                auto_delete_message(chat_id, p_msg.message_id, delay=1800)
        except Exception as e:
            print(f"Photos Send Error: {e}")

    # 2. Video එක තියෙනවා නම් අලුත් Player Link එක හදනවා
    if video_url:
        # Video URL එක Base64 වලින් Encrypt කිරීම
        encoded_url = base64.b64encode(video_url.encode('utf-8')).decode('utf-8')
        
        # GitHub Pages URL එකේ අගට player.html සම්බන්ධ කිරීම
        base_page_url = GITHUB_PAGES_URL.rstrip('/')
        if base_page_url.endswith('index.html'):
            base_page_url = base_page_url.replace('/index.html', '')
            
        secure_player_link = f"{base_page_url}/player.html?src={encoded_url}"
        
        # Inline Button එකක් විදිහට Player Link එක යැවීම
        markup = types.InlineKeyboardMarkup()
        watch_btn = types.InlineKeyboardButton(text="🍿 Watch Video Now", url=secure_player_link)
        markup.add(watch_btn)
        
        sent_msg = bot.send_message(
            chat_id,
            "✅ **Your Video is Ready!**\n\nClick the button below to watch it in our secure web player.",
            reply_markup=markup
        )
        auto_delete_message(chat_id, sent_msg.message_id, delay=1800)

@bot.callback_query_handler(func=lambda call: call.data.startswith('getvid_'))
def handle_video_request(call):
    video_id = call.data.split('_')[1]
    chat_id = call.message.chat.id
    
    db, sha = get_db()
    
    auth_key = f"auth_{chat_id}"
    if auth_key in db:
        expire_time = db[auth_key]
        if time.time() < expire_time:
            media_data = db.get(video_id)
            if media_data:
                bot.answer_callback_query(call.id, "✅ Unlocked! Generating player link...")
                threading.Thread(target=process_and_send_media, args=(chat_id, media_data)).start()
                return
        else:
            del db[auth_key]
            save_db(db, sha)
            db, sha = get_db()

    unique_token = str(uuid.uuid4().hex)[:10]
    db[f"token_{unique_token}"] = video_id
    save_db(db, sha)
    
    base_page_url = GITHUB_PAGES_URL.rstrip('/')
    if base_page_url.endswith('index.html'):
        base_page_url = base_page_url.replace('/index.html', '')
        
    key_page_url = f"{base_page_url}/index.html?key={unique_token}"
    short_url = create_short_link(key_page_url)
    
    bot.send_message(
        chat_id, 
        f"🔗 Click the link below, watch the Ad, and get your verification key!\n\n👉 {short_url}\n\n⚠️ **Instruction:** Send the key back to me. **(This will unlock ALL videos for 1 hour!)**"
    )
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda message: True)
def handle_text_and_start(message):
    text = message.text.strip()
    chat_id = message.chat.id
    
    if text == '/start':
        bot.send_chat_action(chat_id, 'typing')
        keyboard = get_blogger_videos_keyboard()
        if keyboard:
            bot.send_message(chat_id, "👋 Welcome!\n\nClick on a video below to generate your unique Ad link:", reply_markup=keyboard)
        else:
            bot.send_message(chat_id, "No videos found at the moment. Please try again later.")
        return

    if text.startswith('/start '):
        token = text.split()[1] 
    else:
        token = text 
        
    db, sha = get_db()
    token_key = f"token_{token}"
    
    if token_key in db:
        video_id = db[token_key]
        
        db[f"auth_{chat_id}"] = time.time() + 3600
        
        media_data = db.get(video_id)
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

print("Bot is running...")
bot.polling(none_stop=True)
