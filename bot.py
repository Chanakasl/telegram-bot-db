import os
import telebot
from telebot import types
import requests
import json
import string
import random
import threading
import time
from github import Github

# Railway Environment Variables
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME")
SHORTENER_API = os.environ.get("SHORTENER_API")
BOT_USERNAME = os.environ.get("BOT_USERNAME")
BLOG_URL = os.environ.get("BLOG_URL") # උදා: mysite.blogspot.com (https:// හෝ / නැතුව)

bot = telebot.TeleBot(TELEGRAM_TOKEN)
github = Github(GITHUB_TOKEN)
repo = github.get_repo(GITHUB_REPO_NAME)

# Random ID එකක් හැදීමට
def generate_id(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

# GitHub DB එක කියවීම
def get_db():
    try:
        file_content = repo.get_contents("database.json")
        return json.loads(file_content.decoded_content.decode()), file_content.sha
    except Exception:
        # ෆයිල් එක නැත්නම් අලුතින් හිස් එකක් දෙනවා
        return {}, None

# GitHub DB එකට ලිවීම
def save_db(data, sha):
    if sha:
        repo.update_file("database.json", "Update DB", json.dumps(data), sha)
    else:
        repo.create_file("database.json", "Create DB", json.dumps(data))

# ShrinkMe URL එක සෑදීම
def create_short_link(long_url):
    api_url = f"https://shrinkme.io/api?api={SHORTENER_API}&url={long_url}"
    try:
        response = requests.get(api_url).json()
        if response.get('status') == 'success':
            return response['shortenedUrl']
    except Exception as e:
        print(f"Shortener Error: {e}")
    return long_url

# විනාඩි 30කින් මැසේජ් එක delete කරන function එක
def auto_delete_message(chat_id, message_id, delay=1800): # 1800 seconds = 30 minutes
    def delay_delete():
        time.sleep(delay)
        try:
            bot.delete_message(chat_id, message_id)
            print(f"Message {message_id} in chat {chat_id} auto-deleted.")
        except Exception as e:
            print(f"Delete Error (Maybe user already deleted it): {e}")

    # මේක background එකේ run වෙන්න thread එකක් විදිහට ස්ටාර්ට් කරනවා
    threading.Thread(target=delay_delete).start()

# Blogger එකෙන් වීඩියෝ ලිස්ට් එක Inline Buttons විදිහට ගැනීම
def get_blogger_videos_keyboard():
    # Blogger JSON API එක (අලුත්ම පෝස්ට් 50ක් දක්වා ඇදලා ගන්නවා)
    feed_url = f"https://{BLOG_URL}/feeds/posts/default/-/Video?alt=json&max-results=50"
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    try:
        response = requests.get(feed_url).json()
        entries = response.get('feed', {}).get('entry', [])
        
        if not entries:
            return None

        # දැනට තියෙන DB එක ගන්නවා ලින්ක්ස් අප්ඩේට් කරන්න
        db, sha = get_db()
        db_changed = False

        for entry in entries:
            title = entry.get('title', {}).get('$t', 'වීඩියෝවක්')
            content = entry.get('content', {}).get('$t', '')
            
            # පෝස්ට් එක ඇතුලෙන් වීඩියෝ ලින්ක් එකක් හෝ iframe ලින්ක් එකක් සෙවීම
            # (Blogger direct video/mp4 ලින්ක් එකක් හෝ youtube ලින්ක් එකක්)
            import re
            links = re.findall(r'src=["\'](https?://[^"\']+)["\']', content)
            
            # ලින්ක් එකක් හමුවුනොත් පමණක් බටන් එකක් හදන්න
            if links:
                real_video_url = links[0]
                
                # මේ ලින්ක් එක දැනටමත් DB එකේ තියෙද බලනවා, නැත්නම් අලුත් ID එකක් හදනවා
                video_id = None
                for k, v in db.items():
                    if v == real_video_url:
                        video_id = k
                        break
                
                if not video_id:
                    video_id = generate_id()
                    db[video_id] = real_video_url
                    db_changed = True
                
                # Ad short link එක හදනවා
                deep_link = f"https://t.me/{BOT_USERNAME}?start={video_id}"
                short_url = create_short_link(deep_link)
                
                # URL button එක ලිස්ට් එකට එකතු කරනවා
                button = types.InlineKeyboardButton(text=f"🎬 {title}", url=short_url)
                markup.add(button)

        if db_changed:
            save_db(db, sha)
            
        return markup
    except Exception as e:
        print(f"Blogger Fetch Error: {e}")
        return None

# සාමාන්‍ය යූසර් /start කරද්දී හෝ Ad එක බලලා ආවම වෙන දේ
@bot.message_handler(commands=['start'])
def handle_start(message):
    text = message.text.split()
    chat_id = message.chat.id
    
    # 1. සාමාන්‍යයෙන් Bot ව ස්ටාර්ට් කරද්දී (Blogger වීඩියෝ ලිස්ට් එක බටන් විදිහට පෙන්නනවා)
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
        
    # 2. යූසර් Ad එක බලලා බෝට් ගාවට රීඩිරෙක්ට් වෙලා ආවම (/start VID_123)
    video_id = text[1]
    db, _ = get_db()
    
    if video_id in db:
        real_video_url = db[video_id]
        
        sent_msg = bot.send_message(
            chat_id, 
            f"✅ ස්තූතියි! මෙන්න ඔබ ඉල්ලූ වීඩියෝව:\n\n🔗 {real_video_url}\n\n⚠️ ආරක්ෂක හේතූන් මත මෙම පණිවිඩය විනාඩි 30කින් ස්වයංක්‍රීයව මැකී යනු ඇත!"
        )
        
        # විනාඩි 30කින් (තත්පර 1800කින්) මේ මැසේජ් එක ඩිලීට් කරන්න ටයිමර් එකක් දානවා
        auto_delete_message(chat_id, sent_msg.message_id, delay=1800)
        
    else:
        bot.send_message(chat_id, "❌ මෙම ලින්ක් එක වලංගු නැත හෝ කල් ඉකුත් වී ඇත.")

print("Bot is running...")
bot.polling(none_stop=True)
