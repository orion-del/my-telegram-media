
# main.py
import logging
import uuid
import asyncio
import sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    InlineQueryResultArticle, InputTextMessageContent
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes,
    filters, InlineQueryHandler
)
from telegram.constants import ParseMode

# === BOT CONFIG ===
# IMPORTANT: Replace these placeholder values with your actual bot token and admin ID.
BOT_TOKEN = "8231161168:AAE82yLP1XlJXgIdV7E3c_UTo2BPW20_oM8"
ADMIN_CHAT_ID = 6379258244 # Replace with your numeric Telegram user ID
# === End of Configuration ===

# === Logging ===
# Set up logging to monitor the bot's activity and catch errors.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
# Use __name__ which is a special Python variable that holds the name of the current module.
logger = logging.getLogger(__name__)

# === In-Memory Data Storage ===
# Note: This data will be lost if the bot restarts.
user_files = defaultdict(list)      # Stores files uploaded by each user: user_id -> list of file dicts
public_files = {}                   # Stores all public files: file_id -> file data dict
tag_counter = Counter()             # Counts the usage of each tag
favorites = defaultdict(list)       # Stores favorite files for each user: user_id -> list of file_ids
user_stats = Counter()              # Counts the number of uploads per user: user_id -> count
banned_users = set()                # A set of banned user IDs for quick lookups

# --- Helper Functions ---
def generate_file_id():
    """Generates a shorter, unique integer ID for a file."""
    return uuid.uuid4().int >> 64

# --- User Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message and a guide when the /start command is issued."""
    user = update.effective_user
    # We will use HTML parse mode for simplicity and robustness.
    welcome_text = (
        f"👋 Hello, <b>{user.first_name}</b>!\n\n"
        "Here’s a quick guide to use this bot:\n\n"
        "<b>User Commands:</b>\n"
        "📤 /upload - Send media to the bot.\n"
        "📁 /myfiles - View your uploaded files.\n"
        "🌐 /publicfiles - Browse all public files.\n"
        "⭐ /favorites - See your favorite files.\n"
        "➕ /favorite <code>&lt;file_id&gt;</code> - Add a file to your favorites.\n"
        "🏆 /topusers - See the top contributors.\n"
        "📖 /help - Show this help message again.\n\n"
        "<b>How it works:</b>\n"
        "1. Use /upload to start the process.\n"
        "2. Send your media file.\n"
        "3. Add comma-separated tags (e.g., <code>nature, sky, blue</code>).\n"
        "4. Your file will become public and searchable!\n\n"
        "<b>Inline Search:</b>\n"
        "You can search for files in any chat by typing @YourBotUsername followed by a tag."
    )
    await update.message.reply_html(welcome_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays a detailed list of commands."""
    help_text = (
        "<b>User Commands:</b>\n"
        "  /upload - Start the file upload process.\n"
        "📁 /myfiles - View your personal uploads.\n"
        "🌐 /publicfiles - Browse all public files.\n"
        "📝 /info <code>&lt;file_id&gt;</code> - Get info and a download link for a file.\n"
        "⭐ /favorites - List your favorite files.\n"
        "➕ /favorite <code>&lt;file_id&gt;</code> - Add a file to your favorites.\n"
        "🏆 /topusers - Show top 10 contributors.\n\n"
        "<b>Admin Commands:</b>\n"
        "📣 /broadcast <code>&lt;message&gt;</code> - Send a message to all users.\n"
        "❌ /ban <code>&lt;user_id&gt;</code> - Ban a user from uploading.\n"
        "✅ /unban <code>&lt;user_id&gt;</code> - Unban a user.\n"
        "👥 /listusers - List all users who have uploaded files.\n"
    )
    await update.message.reply_html(help_text)

async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiates the file upload process."""
    user_id = update.effective_user.id
    if user_id in banned_users:
        await update.message.reply_text("❌ You are banned from uploading files.")
        return
    await update.message.reply_text("📤 Please send your media file now (photo, video, audio, document, etc.).")
    # Set a flag to indicate the bot is waiting for a media file from this user.
    context.user_data['waiting_for_media'] = True
    context.user_data['waiting_for_tags'] = False # Ensure tags flag is reset

async def myfiles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the files uploaded by the user."""
    user_id = update.effective_user.id
    files = user_files.get(user_id, [])
    if not files:
        await update.message.reply_text("You haven't uploaded any files yet. Use /upload to start.")
        return
    
    response_text = "📁 <b>Your Uploaded Files:</b>\n\n"
    for f in files:
        tags = ", ".join(f['tags']) if f['tags'] else 'No tags'
        response_text += f"<b>ID:</b> <code>{f['file_id']}</code>\n<b>Type:</b> {f['type']}\n<b>Tags:</b> {tags}\n\n"
        
    await update.message.reply_html(response_text)

async def public_files_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays all public files with download buttons."""
    if not public_files:
        await update.message.reply_text("There are no public files yet.")
        return
    
    await update.message.reply_text("🌐 Here are the latest public files:")
    # Display the most recent 10 files to avoid spamming the chat
    for file_id, f in reversed(list(public_files.items())[-10:]):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬇️ Download", url=f['download_link'])
        ]])
        tags = ", ".join(f['tags'])
        caption = f"<b>ID:</b> <code>{file_id}</code>\n<b>Type:</b> {f['type']}\n<b>Tags:</b> {tags}"
        await update.message.reply_html(caption, reply_markup=keyboard)

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Provides information and a download link for a specific file."""
    if not context.args:
        await update.message.reply_text("<b>Usage:</b> /info <code>&lt;file_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        file_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid File ID. It should be a number.")
        return

    file_entry = public_files.get(file_id)
    if not file_entry:
        await update.message.reply_text("❌ File not found.")
        return
        
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬇️ Download", url=file_entry['download_link'])
    ]])
    tags = ", ".join(file_entry['tags'])
    info_text = (
        f"📝 <b>File Info</b>\n\n"
        f"<b>ID:</b> <code>{file_id}</code>\n"
        f"<b>Type:</b> {file_entry['type']}\n"
        f"<b>Tags:</b> {tags}\n"
        f"<b>Uploaded on:</b> {file_entry['date']}"
    )
    await update.message.reply_html(info_text, reply_markup=keyboard)

async def favorites_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists the user's favorite files."""
    user_id = update.effective_user.id
    fav_ids = favorites.get(user_id, [])
    if not fav_ids:
        await update.message.reply_text("You have no favorite files yet. Use /favorite <file_id> to add one.")
        return

    await update.message.reply_text("⭐ Your Favorite Files:")
    for fid in fav_ids:
        f = public_files.get(fid)
        if f:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("⬇️ Download", url=f['download_link'])
            ]])
            tags = ", ".join(f['tags'])
            caption = f"<b>ID:</b> <code>{fid}</code>\n<b>Type:</b> {f['type']}\n<b>Tags:</b> {tags}"
            await update.message.reply_html(caption, reply_markup=keyboard)

async def favorite_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adds a file to the user's favorites list."""
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("<b>Usage:</b> /favorite <code>&lt;file_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        file_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid File ID. It should be a number.")
        return

    if file_id not in public_files:
        await update.message.reply_text("❌ Public file with this ID not found.")
        return
    
    if file_id in favorites[user_id]:
        await update.message.reply_text("✅ This file is already in your favorites.")
        return

    favorites[user_id].append(file_id)
    await update.message.reply_text("✅ File added to your favorites!")

async def top_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the top 10 users with the most uploads."""
    top = user_stats.most_common(10)
    if not top:
        await update.message.reply_text("No one has uploaded any files yet.")
        return
        
    text = "🏆 <b>Top 10 Contributors:</b>\n\n"
    for i, (user_id, count) in enumerate(top):
        try:
            user = await context.bot.get_chat(user_id)
            username = user.first_name
        except Exception:
            username = f"User (<code>{user_id}</code>)"
        text += f"{i+1}. {username} - {count} uploads\n"
        
    await update.message.reply_html(text)

# --- Media and Text Message Handlers ---
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles receiving media after the /upload command."""
    user = update.effective_user
    if user.id in banned_users:
        return # Ignore media from banned users

    if not context.user_data.get('waiting_for_media'):
        await update.message.reply_text("Please use the /upload command before sending a file.")
        return

    message = update.message
    media_type, file_id_attr = None, None

    if message.photo:
        media_type, file_id_attr = "photo", message.photo[-1].file_id
    elif message.video:
        media_type, file_id_attr = "video", message.video.file_id
    elif message.audio:
        media_type, file_id_attr = "audio", message.audio.file_id
    elif message.document:
        media_type, file_id_attr = "document", message.document.file_id
    elif message.voice:
        media_type, file_id_attr = "voice", message.voice.file_id
    elif message.video_note:
        media_type, file_id_attr = "video_note", message.video_note.file_id
    else:
        return

    if any(f['telegram_file_id'] == file_id_attr for f in public_files.values()):
        await update.message.reply_text("⚠️ This exact file has already been uploaded by someone and is public.")
        context.user_data['waiting_for_media'] = False
        return

    await update.message.reply_text("✅ Media received! Now, please provide tags for this file, separated by commas (e.g., <code>nature, sky, blue</code>).", parse_mode=ParseMode.HTML)
    
    context.user_data['pending_file'] = {
        'file_id': generate_file_id(),
        'type': media_type,
        'date': datetime.now().strftime("%Y-%m-%d %H:%M"),
        'telegram_file_id': file_id_attr
    }
    context.user_data['waiting_for_media'] = False
    context.user_data['waiting_for_tags'] = True

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles receiving text, checking if it's tags for a pending file."""
    if not context.user_data.get('waiting_for_tags'):
        await update.message.reply_text("I'm not sure what you mean. Use /help to see available commands.")
        return

    tags = [t.strip().lower() for t in update.message.text.split(",") if t.strip()]
    if not tags:
        await update.message.reply_text("You must provide at least one tag. Please try again.")
        return

    file_entry = context.user_data.pop('pending_file')
    
    try:
        file_obj = await context.bot.get_file(file_entry['telegram_file_id'])
        download_link = file_obj.file_path
    except Exception as e:
        logger.error(f"Could not get file path for {file_entry['telegram_file_id']}: {e}")
        await update.message.reply_text("❌ Sorry, I couldn't process this file. It might be too old or inaccessible.")
        context.user_data.pop('waiting_for_tags', None)
        return

    file_entry['download_link'] = download_link
    file_entry['tags'] = tags
    user_id = update.effective_user.id

    user_files[user_id].append(file_entry)
    public_files[file_entry['file_id']] = file_entry
    for t in tags:
        tag_counter[t] += 1
    user_stats[user_id] += 1
    
    context.user_data.pop('waiting_for_tags', None)

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬇️ Download", url=download_link)]])
    await update.message.reply_html(
        f"✅ Success! Your file is now public.\n<b>File ID:</b> <code>{file_entry['file_id']}</code>",
        reply_markup=keyboard
    )

# --- Inline Search Handler ---
async def inline_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline search queries for files by tag."""
    query = update.inline_query.query.lower().strip()
    results = []
    if not query:
        return

    for fid, f in public_files.items():
        if query in f['tags']: # Exact tag match
            results.append(
                InlineQueryResultArticle(
                    id=str(uuid.uuid4()),
                    title=f"{f['type'].capitalize()}",
                    input_message_content=InputTextMessageContent(
                        f"<b>File ID:</b> <code>{fid}</code> ({f['type']})\n<a href='{f['download_link']}'>Click here to download</a>",
                        parse_mode=ParseMode.HTML
                    ),
                    description=f"Tags: {', '.join(f['tags'])}"
                )
            )
    
    await update.inline_query.answer(results[:50], cache_time=1)

# --- Admin Command Handlers ---
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to send a message to all users."""
    if update.effective_user.id != ADMIN_CHAT_ID: return
    
    if not context.args:
        await update.message.reply_text("<b>Usage:</b> /broadcast <code>&lt;message&gt;</code>", parse_mode=ParseMode.HTML)
        return
        
    msg = " ".join(context.args)
    all_user_ids = set(user_files.keys()) | set(favorites.keys())
    
    sent_count, failed_count = 0, 0
    await update.message.reply_text(f"Starting broadcast to {len(all_user_ids)} users...")
    for user_id in all_user_ids:
        try:
            await context.bot.send_message(chat_id=user_id, text=f"📣 <b>Admin Broadcast:</b>\n\n{msg}", parse_mode=ParseMode.HTML)
            sent_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            failed_count += 1
            logger.warning(f"Could not send broadcast to {user_id}: {e}")
            
    await update.message.reply_text(f"✅ Broadcast finished.\nSent: {sent_count}\nFailed: {failed_count}")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to ban a user."""
    if update.effective_user.id != ADMIN_CHAT_ID: return
    if not context.args:
        await update.message.reply_text("<b>Usage:</b> /ban <code>&lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        user_id = int(context.args[0])
        banned_users.add(user_id)
        await update.message.reply_text(f"✅ User {user_id} has been banned from uploading.")
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID.")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to unban a user."""
    if update.effective_user.id != ADMIN_CHAT_ID: return
    if not context.args:
        await update.message.reply_text("<b>Usage:</b> /unban <code>&lt;user_id&gt;</code>", parse_mode=ParseMode.HTML)
        return
    try:
        user_id = int(context.args[0])
        banned_users.discard(user_id)
        await update.message.reply_text(f"✅ User {user_id} has been unbanned.")
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID.")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to list users and their upload counts."""
    if update.effective_user.id != ADMIN_CHAT_ID: return
    if not user_stats:
        await update.message.reply_text("No users have uploaded files yet.")
        return
        
    text = "📋 <b>Active Users & Uploads:</b>\n\n"
    for user_id, count in user_stats.items():
        text += f"<code>{user_id}</code>: {count} uploads\n"
    await update.message.reply_html(text)

# --- Main Application Setup ---
def main() -> None:
    """Sets up the bot, registers handlers, and starts polling."""
    # --- PRE-RUN CHECKS ---
    if BOT_TOKEN == "YOUR_BOT_TOKEN" or ADMIN_CHAT_ID == 123456789:
        print("!!! CONFIGURATION ERROR !!!")
        print("Please open the main.py file and replace 'YOUR_BOT_TOKEN' and the placeholder ADMIN_CHAT_ID with your actual credentials.")
        sys.exit(1) # Exit the script

    application = Application.builder().token(BOT_TOKEN).build()

    # --- Register Command Handlers ---
    command_handlers = {
        "start": start, "help": help_command, "upload": upload_command,
        "myfiles": myfiles, "publicfiles": public_files_list, "info": info,
        "favorites": favorites_list, "favorite": favorite_add, "topusers": top_users,
        "broadcast": broadcast, "ban": ban, "unban": unban, "listusers": list_users
    }
    for command, handler in command_handlers.items():
        application.add_handler(CommandHandler(command, handler))

    # --- Register Message Handlers ---
    media_filter = filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE | filters.Document.ALL | filters.VIDEO_NOTE
    application.add_handler(MessageHandler(media_filter, handle_media))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # --- Register Inline Query Handler ---
    application.add_handler(InlineQueryHandler(inline_search))

    print("🤖 Bot is running... Press Ctrl+C to stop.")
    application.run_polling()

if __name__ == "__main__":
    main()
