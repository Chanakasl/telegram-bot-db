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
SHORTENER_API = os.environ.get("SHORTENER_API")
BOT_USERNAME = os.environ.get("BOT_USERNAME")
BLOG_URL = os.environ.get("BLOG_URL")
GITHUB_PAGES_URL = os.environ.get("GITHUB_PAGES_URL")

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

# --- අලුත් කොටස: හැම විනාඩි 3කට වරක් Expire වූ අය පරීක්ෂා කිරීම ---
def session_cleanup_task():
    while True:
        time.sleep(180) # තත්පර 180 (විනාඩි 3යි)
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
            
            # වෙනස්කම් තියෙනවා නම් පමණක් GitHub එකට සේව් කිරීම
            if changes_made:
                save_db(db, sha)
                
                # Expire වූ අයට දැනුම් දීම
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

# Background Task එක ආරම්භ කිරීම
threading.Thread(target=session_cleanup_task, daemon=True).start()
# -----------------------------------------------------------------

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
                    elif isinstance(v, str): 
                        if v == real_video_url and not images:
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

def process_and_send_media(chat_id, media_data):
    if isinstance(media_data, str):
        images = []
        video_url = media_data
    else:
        images = media_data.get("images", [])
        video_url = media_data.get("video")

    wait_msg = bot.send_message(chat_id, "⏳ Preparing your files. Please wait...")
    
    if images:
        try:
            bot.edit_message_text("🖼️ Sending photos...", chat_id, wait_msg.message_id)
            media_group = [types.InputMediaPhoto(url) for url in images[:10]]
            sent_photos = bot.send_media_group(chat_id, media_group)
            
            for p_msg in sent_photos:
                auto_delete_message(chat_id, p_msg.message_id, delay=1800)
        except Exception as e:
            print(f"Photos Send Error: {e}")

    if video_url:
        try:
            bot.edit_message_text("📥 Downloading video to the server. Please hold on (this might take a few minutes)...", chat_id, wait_msg.message_id)
            bot.send_chat_action(chat_id, 'upload_video')
            
            ydl_opts = {
                'outtmpl': f'video_{chat_id}_%(id)s.%(ext)s',
                'format': 'best',
                'quiet': True,
                'no_warnings': True
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                filename = ydl.prepare_filename(info)
                
            caption_text = "✅ Thank you! Here is your requested video:\n\n⚠️ For security reasons, these files will be automatically deleted in 30 minutes!"
            
            bot.edit_message_text("📤 Uploading video to Telegram...", chat_id, wait_msg.message_id)
            
            with open(filename, 'rb') as video_file:
                sent_msg = bot.send_video(chat_id, video=video_file, caption=caption_text, timeout=300)
                
            os.remove(filename)
            auto_delete_message(chat_id, sent_msg.message_id, delay=1800)
            
        except Exception as e:
            print(f"Video Processing Error: {e}")
            fallback_msg = bot.send_message(
                chat_id,
                f"❌ An error occurred while downloading, or the video size is too large.\n\n🔗 Please watch it via the link below:\n{video_url}\n\n⚠️ This message will be deleted in 30 minutes."
            )
            auto_delete_message(chat_id, fallback_msg.message_id, delay=1800)
    elif not images and not video_url:
        bot.send_message(chat_id, "⚠️ No video or image was detected in this post.")

    try:
        bot.delete_message(chat_id, wait_msg.message_id)
    except Exception:
        pass

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
                bot.answer_callback_query(call.id, "✅ Unlocked! Sending video...")
                threading.Thread(target=process_and_send_media, args=(chat_id, media_data)).start()
                return
        else:
            del db[auth_key]
            save_db(db, sha)
            db, sha = get_db()

    unique_token = str(uuid.uuid4().hex)[:10]
    db[f"token_{unique_token}"] = video_id
    save_db(db, sha)
    
    key_page_url = f"{GITHUB_PAGES_URL}?key={unique_token}"
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
        
        # පැයකට (තත්පර 3600කට) අන්ලොක් කිරීම
        db[f"auth_{chat_id}"] = time.time() + 3600
        
        media_data = db.get(video_id)
        if media_data:
            bot.send_message(chat_id, "🎉 **Success! The Bot is now unlocked for 1 HOUR.**\nYou can download any video directly without ads!")
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
