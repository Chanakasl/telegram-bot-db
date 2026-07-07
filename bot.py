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
from github import Github

# Railway Environment Variables
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME")
SHORTENER_API = os.environ.get("SHORTENER_API")
BOT_USERNAME = os.environ.get("BOT_USERNAME")
BLOG_URL = os.environ.get("BLOG_URL")

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
            title = entry.get('title', {}).get('$t', 'වීඩියෝවක්')
            content = entry.get('content', {}).get('$t', '')
            
            links = re.findall(r'src=["\'](https?://[^"\']+)["\']', content)
            
            if links:
                real_video_url = links[0]
                
                video_id = None
                for k, v in db.items():
                    if v == real_video_url:
                        video_id = k
                        break
                
                if not video_id:
                    video_id = generate_id()
                    db[video_id] = real_video_url
                    db_changed = True
                
                deep_link = f"https://t.me/{BOT_USERNAME}?start={video_id}"
                short_url = create_short_link(deep_link)
                
                button = types.InlineKeyboardButton(text=f"🎬 {title}", url=short_url)
                markup.add(button)

        if db_changed:
            save_db(db, sha)
            
        return markup
    except Exception as e:
        print(f"Blogger Fetch Error: {e}")
        return None

# වීඩියෝව Download කර Upload කරන වෙනම Function එක
def process_and_send_video(chat_id, video_url):
    wait_msg = bot.send_message(chat_id, "⏳ වීඩියෝව සූදානම් වෙමින් පවතී. කරුණාකර මඳ වේලාවක් රැඳී සිටින්න...")
    bot.send_chat_action(chat_id, 'upload_video')
    
    try:
        # වීඩියෝව Railway සර්වර් එකට ඩවුන්ලෝඩ් කිරීම
        ydl_opts = {
            'outtmpl': f'video_{chat_id}_%(id)s.%(ext)s',
            'format': 'best',
            'quiet': True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            filename = ydl.prepare_filename(info)
            
        caption_text = "✅ ස්තූතියි! මෙන්න ඔබ ඉල්ලූ වීඩියෝව:\n\n⚠️ ආරක්ෂක හේතූන් මත මෙම වීඩියෝව විනාඩි 30කින් ස්වයංක්‍රීයව මැකී යනු ඇත!"
        
        # ඩවුන්ලෝඩ් කළ වීඩියෝව Telegram එකට යැවීම
        with open(filename, 'rb') as video_file:
            sent_msg = bot.send_video(chat_id, video=video_file, caption=caption_text, timeout=120)
            
        # සර්වර් එකෙන් වීඩියෝව මකා දැමීම (Storage ඉතුරු වීමට)
        os.remove(filename)
        
        # දැනුම්දීමේ මැසේජ් එක මකා දැමීම
        bot.delete_message(chat_id, wait_msg.message_id)
        
        # විනාඩි 30න් ඩිලීට් කිරීමේ ටයිමර් එක
        auto_delete_message(chat_id, sent_msg.message_id, delay=1800)
        
    except Exception as e:
        print(f"Video Processing Error: {e}")
        bot.delete_message(chat_id, wait_msg.message_id)
        
        fallback_msg = bot.send_message(
            chat_id,
            f"❌ වීඩියෝවේ ප්‍රමාණය විශාල බැවින් (50MB ට වැඩි) හෝ දෝෂයක් නිසා කෙලින්ම Telegram වෙත යැවිය නොහැක.\n\n🔗 කරුණාකර පහත ලින්ක් එකෙන් නරඹන්න:\n{video_url}\n\n⚠️ මෙම පණිවිඩය විනාඩි 30කින් මැකී යනු ඇත."
        )
        auto_delete_message(chat_id, fallback_msg.message_id, delay=1800)

@bot.message_handler(commands=['start'])
def handle_start(message):
    text = message.text.split()
    chat_id = message.chat.id
    
    if len(text) == 1:
        bot.send_chat_action(chat_id, 'typing')
        keyboard = get_blogger_videos_keyboard()
        
        if keyboard:
            bot.send_message(
                chat_id, 
                "👋 සාදරයෙන් පිළිගනිමු!\n\nපහත බොත්තම් ක්ලික් කර Ad එක බැලීමෙන් පසු ඔබට වීඩියෝව නැරඹිය හැක:", 
                reply_markup=keyboard
            )
        else:
            bot.send_message(chat_id, "දැනට කිසිදු වීඩියෝවක් සොයාගත නොහැක. පසුව උත්සාහ කරන්න.")
        return
        
    video_id = text[1]
    db, _ = get_db()
    
    if video_id in db:
        real_video_url = db[video_id]
        # Download සහ Send කිරීම වෙනම Thread එකකින් ආරම්භ කිරීම
        threading.Thread(target=process_and_send_video, args=(chat_id, real_video_url)).start()
    else:
        bot.send_message(chat_id, "❌ මෙම ලින්ක් එක වලංගු නැත හෝ කල් ඉකුත් වී ඇත.")

print("Bot is running...")
bot.polling(none_stop=True)
