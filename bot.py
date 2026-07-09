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
GITHUB_PAGES_URL = os.environ.get("GITHUB_PAGES_URL") # ඔයාගේ අලුත් වෙබ් අඩවියේ ලින්ක් එක (උදා: https://chakybea.github.io/bot-unlock-page)

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
    
    unique_token = str(uuid.uuid4().hex)[:10]
    
    db, sha = get_db()
    # පැයකින් (තත්පර 3600 කින්) කල් ඉකුත් වන වේලාව සේව් කිරීම
    expire_time = time.time() + 3600 
    
    db[f"token_{unique_token}"] = {
        "video_id": video_id, 
        "expire_time": expire_time
    }
    save_db(db, sha)
    
    # GitHub Pages වෙබ් අඩවියට URL Parameter එකක් විදිහට Key එක යැවීම
    # GITHUB_PAGES_URL එක අගට slash (/) එකක් තියෙනවා නම් ඒක අයින් කරලා ලින්ක් එක හදන්න
    base_url = GITHUB_PAGES_URL.rstrip('/') if GITHUB_PAGES_URL else "https://example.com"
    key_page_url = f"{base_url}?key={unique_token}"
    
    short_url = create_short_link(key_page_url)
    
    bot.send_message(
        chat_id, 
        f"🔗 Click the link below, watch the Ad, and get your verification key!\n\n👉 {short_url}\n\n⚠️ **Instruction:** After getting the key from the website, come back here and send it to me. (This key is valid for 1 hour)"
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

    # යූසර් Key එකක් Paste කරලා යැව්වම
    if text.startswith('/start '):
        token = text.split()[1] 
    else:
        token = text 
        
    db, sha = get_db()
    token_key = f"token_{token}"
    
    if token_key in db:
        token_data = db[token_key]
        
        if isinstance(token_data, dict):
            video_id = token_data.get("video_id")
            expire_time = token_data.get("expire_time", 0)
            
            # පැය ඉවර වෙලාද කියලා බලනවා
            if time.time() > expire_time:
                bot.send_message(chat_id, "❌ This Key has expired! Please generate a new one from the menu.")
                del db[token_key]
                save_db(db, sha)
                return
        else:
            video_id = token_data 
            
        media_data = db.get(video_id)
        
        if media_data:
            threading.Thread(target=process_and_send_media, args=(chat_id, media_data)).start()
            # මින් පෙර මෙහි තිබූ "del db[token_key]" ඉවත් කර ඇත. 
            # එබැවින් පැයක් යනතුරු කීප සැරයක් වුවද වීඩියෝව ගත හැක.
        else:
            bot.send_message(chat_id, "❌ Error retrieving video data.")
    else:
        if not text.startswith('/'):
            bot.send_message(chat_id, "❌ Invalid Key! The key is incorrect or has expired.")

print("Bot is running...")
bot.polling(none_stop=True)
