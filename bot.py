import os
import telebot
import requests
import json
import string
import random
from github import Github

# Railway එකෙන් ලබාගන්නා දත්ත
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME") # උදා: Chanakasl/telegram-bot-db
SHORTENER_API = os.environ.get("SHORTENER_API")
BOT_USERNAME = os.environ.get("BOT_USERNAME") # උදා: @MyVideoBot

bot = telebot.TeleBot(TELEGRAM_TOKEN)
github = Github(GITHUB_TOKEN)
repo = github.get_repo(GITHUB_REPO_NAME)

# Random ID එකක් හැදීමට
def generate_id(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

# GitHub එකෙන් දත්ත කියවීම
def get_db():
    file_content = repo.get_contents("database.json")
    return json.loads(file_content.decoded_content.decode()), file_content.sha

# GitHub එකට දත්ත ලිවීම
def save_db(data, sha):
    repo.update_file("database.json", "Update DB", json.dumps(data), sha)

# Ad Link එක හැදීම (ShrinkEarn උදාහරණයක් ලෙස)
def create_short_link(long_url):
    api_url = f"https://shrinkme.io/api?api={SHORTENER_API}&url={long_url}"
    response = requests.get(api_url).json()
    if response['status'] == 'success':
        return response['shortenedUrl']
    return long_url

# Admin Video එකක් Bot ට දුන්නම වෙන දේ
@bot.message_handler(commands=['addvideo'])
def add_video(message):
    # උදාහරණය: /addvideo https://blogger-video-link.mp4
    video_url = message.text.replace("/addvideo ", "").strip()
    
    if not video_url:
        bot.reply_to(message, "කරුණාකර ලින්ක් එක ලබා දෙන්න.")
        return

    video_id = generate_id()
    
    # GitHub එකට සේව් කිරීම
    db, sha = get_db()
    db[video_id] = video_url
    save_db(db, sha)
    
    # Deep Link එක හදලා ඒක Short කිරීම
    deep_link = f"https://t.me/{BOT_USERNAME}?start={video_id}"
    short_url = create_short_link(deep_link)
    
    bot.reply_to(message, f"ඔබගේ Ad Link එක සූදානම්:\n{short_url}")

# යූසර් Ad එක බලලා Bot ගාවට ආවම වෙන දේ
@bot.message_handler(commands=['start'])
def handle_start(message):
    text = message.text.split()
    
    # සාමාන්‍ය /start එකක් නම්
    if len(text) == 1:
        bot.reply_to(message, "හායි! වීඩියෝ ලබා ගැනීමට අදාල ලින්ක් එක භාවිතා කරන්න.")
        return
        
    # Ad එක බලලා එන කෙනෙක් නම් (/start VID_123)
    video_id = text[1]
    db, _ = get_db()
    
    if video_id in db:
        real_video_url = db[video_id]
        bot.reply_to(message, f"මෙන්න ඔබගේ වීඩියෝව: \n{real_video_url}")
    else:
        bot.reply_to(message, "මෙම ලින්ක් එක කල් ඉකුත් වී හෝ වැරදියි.")

print("Bot is running...")
bot.polling(none_stop=True)
