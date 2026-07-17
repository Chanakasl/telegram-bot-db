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
VERCEL_URL = os.environ.get("VERCEL_URL") 
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME") # අලුතින් එකතු කළ චැනල් යූසර්නේම් එක

bot = telebot.TeleBot(TELEGRAM_TOKEN)
github = Github(GITHUB_TOKEN)
repo = github.get_repo(GITHUB_REPO_NAME)

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

# Force Subscribe Check Function
def check_sub(user_id):
    if not CHANNEL_USERNAME: 
        return True # චැනල් එකක් දීලා නැත්නම් අනිවාර්ය කරන්නේ නෑ
    try:
        status = bot.get_chat_member(CHANNEL_USERNAME, user_id).status
        return status in ['creator', 'administrator', 'member']
    except Exception:
        return False

# --- Background Task 1: Session Cleanup ---
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

# --- Background Task 2: Auto-Broadcast New Posts ---
def check_new_posts_task():
    while True:
        try:
            feed_url = f"https://{BLOG_URL}/feeds/posts/default/-/Video?alt=json&max-results=1"
            data = requests.get(feed_url).json()
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
                    
                    if saved_last_id is not None:
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton("🚀 දැන්ම බලන්න", url=f"https://t.me/{BOT_USERNAME}?start=menu"))
                        message_text = f"🔥 **අලුත් වීඩියෝ එකක් ඇවිත් තියෙන්නේ!**\n\n🎬 {title}\n\nපහළ බටන් එක ඔබලා දැන්ම බලන්න 👇"
                        
                        for user_id in users:
                            try:
                                bot.send_message(user_id, message_text, reply_markup=markup)
                                time.sleep(0.5) 
                            except Exception:
                                pass 
                                
        except Exception as e:
            print(f"Broadcast Error: {e}")
            
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
            print(f"Photos Error: {e}")

    if video_url:
        expire_timestamp = int(time.time()) + 3600 
        raw_data = f"{video_url}:::{expire_timestamp}"
        encoded_data = base64.b64encode(raw_data.encode('utf-8')).decode('utf-8')
        
        base_url = VERCEL_URL.rstrip('/')
        player_url = f"{base_url}/player.html?data={encoded_data}"

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🍿 Watch Secure Player", url=player_url))

        bot.send_message(
            chat_id,
            "✅ **Your Video is Ready!**\n\nClick the button below to watch it securely.\n⚠️ *(This player link will automatically expire in 1 hour)*",
            reply_markup=markup
        )

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
    except Exception: 
        return None

# --- Bot Commands & Callbacks ---
@bot.callback_query_handler(func=lambda call: call.data == 'check_sub')
def handle_check_sub(call):
    chat_id = call.message.chat.id
    if check_sub(chat_id):
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        bot.send_message(chat_id, "✅ **ස්තූතියි! ඔබ සාර්ථකව චැනල් එකට සම්බන්ධ වී ඇත.**\n\nවීඩියෝ නැරඹීමට /start ලෙස type කරන්න.")
    else:
        bot.answer_callback_query(call.id, "❌ ඔබ තවමත් චැනල් එකට සම්බන්ධ වී නොමැත! කරුණාකර Join වී නැවත උත්සාහ කරන්න.", show_alert=True)

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

    token = str(uuid.uuid4().hex)[:10]
    db[f"token_{token}"] = vid_id
    save_db(db, sha)
    
    base_url = VERCEL_URL.rstrip('/')
    short_url = create_short_link(f"{base_url}/index.html?key={token}")
    
    bot.send_message(
        chat_id, 
        f"🔗 Click the link below, watch the Ad, and get your verification key!\n\n👉 {short_url}\n\n⚠️ **Instruction:** Send the key back to me. **(This will unlock ALL videos for 1 hour!)**"
    )
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    text = message.text.strip()
    chat_id = message.chat.id
    db, sha = get_db()
    
    # 1. යූසර් ලියාපදිංචිය
    if "users" not in db:
        db["users"] = []
    if chat_id not in db["users"]:
        db["users"].append(chat_id)
        save_db(db, sha)
        db, sha = get_db()
        
    # 2. Referral ක්‍රමය හැසිරවීම (වඩාත් නිවැරදි ක්‍රමය)
    if "used_refs" not in db:
        db["used_refs"] = []
        
    if text.startswith('/start ref_'):
        try:
            referrer_id = int(text.split('_')[1])
            # තමන්ගෙම ලින්ක් එක ක්ලික් කිරීම වළක්වා, කලින් රෙෆරල් පාවිච්චි කර ඇතිදැයි බැලීම
            if referrer_id != chat_id and chat_id not in db["used_refs"]:
                db["used_refs"].append(chat_id) # මේ යූසර්ව රෙෆරල් ලිස්ට් එකට දානවා
                
                # Refer කළ කෙනාට පැය 24 (තත්පර 86400) දීම
                current_auth = db.get(f"auth_{referrer_id}", time.time())
                if current_auth < time.time():
                    current_auth = time.time()
                db[f"auth_{referrer_id}"] = current_auth + 86400
                
                save_db(db, sha)
                db, sha = get_db()
                
                # Refer කළ කෙනාට මැසේජ් එක යැවීම
                try:
                    bot.send_message(referrer_id, "🎉 **සුබ පැතුම්!**\nඔබේ යොමු කිරීමේ ලින්ක් එකෙන් සාමාජිකයෙක් එකතු වූ නිසා ඔබට **පැය 24ක අමතර VIP Access** එකක් ලැබුණා!")
                except Exception:
                    pass
        except Exception as e:
            print(f"Ref Error: {e}")

    # 3. Force Subscribe පරීක්ෂා කිරීම
    if not check_sub(chat_id):
        channel_link = CHANNEL_USERNAME.replace('@', '')
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{channel_link}"))
        markup.add(types.InlineKeyboardButton("✅ Check Subscription", callback_data="check_sub"))
        
        bot.send_message(
            chat_id, 
            "⚠️ **බොට් භාවිතා කිරීමට ප්‍රථමයෙන් අපගේ චැනල් එකට සම්බන්ධ වී සිටිය යුතුය!**\n\nපහත බටන් එක ඔබලා Join වෙලා, ඉන්පසු 'Check Subscription' ඔබන්න.", 
            reply_markup=markup
        )
        return

    # 4. ප්‍රධාන විධාන (Commands)
    if text == '/start' or text.startswith('/start ref_') or text == '/start menu':
        bot.send_chat_action(chat_id, 'typing')
        markup = get_blogger_videos_keyboard()
        if markup:
            bot.send_message(
                chat_id, 
                "👋 Welcome!\n\nSelect a video below to generate your unique Ad link:\n\n*(යාළුවන්ට Invite කරලා පැය 24ක අඛණ්ඩ VIP සේවාවක් ලබා ගැනීමට /refer ලෙස type කරන්න)*", 
                reply_markup=markup
            )
        else:
            bot.send_message(chat_id, "No videos found. Please try again later.")
        return
        
    # Referral ලින්ක් එක ලබාගැනීම සඳහා /refer විධානය
    if text == '/refer':
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{chat_id}"
        bot.send_message(
            chat_id, 
            f"🎁 **ඔබේ Referral Link එක:**\n\n`{ref_link}`\n\nමේ ලින්ක් එකෙන් යාළුවෙක්ව බොට් වෙත ගෙන ආවොත්, ඔබට **පැය 24ක VIP Access එකක්** සම්පූර්ණයෙන්ම නොමිලේ ලැබෙනවා! (Ads බලන්න ඕන නෑ)"
        )
        return
    
    # 5. Token Verification 
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
