import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from telegram.request import HTTPXRequest
import threading
import database as db

TOKEN = "8568453320:AAEJdxuRaE6lqiq4b-Yx4q0XlZT0jqsT6ik"  # Hardcoded as requested
if not TOKEN:
    raise ValueError("BOT_TOKEN not set")

# States
AGE, GENDER, LOOKING_FOR, CITY, NAME, BIO, PHOTOS = range(7)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Your existing handler functions (unchanged except for show_profile)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Hi! I'm a simple match bot.\n\n"
        "Be safe online. No personal data is shared.\n\n"
        "What's your age? (18–99)"
    )
    return AGE

async def age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        age = int(update.message.text)
        if 18 <= age <= 99:
            context.user_data['age'] = age
            keyboard = [['I\'m male', 'I\'m female', 'Other']]
            await update.message.reply_text("Your gender:", reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True))
            return GENDER
        else:
            await update.message.reply_text("Age must be 18–99.")
            return AGE
    except:
        await update.message.reply_text("Enter a number.")
        return AGE

async def gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    gender = text.split("'")[1] if "'" in text else text
    context.user_data['gender'] = gender
    keyboard = [['Women', 'Men', 'Everyone']]
    await update.message.reply_text("Who are you looking for?", reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True))
    return LOOKING_FOR

async def looking_for(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['looking_for'] = update.message.text
    await update.message.reply_text("Your city? (e.g., Lahore)")
    return CITY

async def city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['city'] = update.message.text
    await update.message.reply_text("Your name?")
    return NAME

async def name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Tell about yourself (bio):")
    return BIO

async def bio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['bio'] = update.message.text
    await update.message.reply_text("Send 1–3 photos (or /done to skip)")
    return PHOTOS

async def photos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if update.message.photo:
        photo_file = update.message.photo[-1]
        path = db.download_photo(context.bot, photo_file, user_id)
        if 'photos' not in context.user_data:
            context.user_data['photos'] = []
        context.user_data['photos'].append(path)
        count = len(context.user_data['photos'])
        if count < 3:
            await update.message.reply_text(f"Photo {count}/3 added. Send more or /done")
            return PHOTOS
    # Save
    db.save_profile(
        user_id,
        context.user_data['name'],
        context.user_data['age'],
        context.user_data['gender'],
        context.user_data['looking_for'],
        context.user_data['city'],
        context.user_data['bio'],
        context.user_data.get('photos', [])
    )
    await update.message.reply_text(
        f"Profile saved!\n\n"
        f"{context.user_data['name']}, {context.user_data['age']}, {context.user_data['city']}\n"
        f"{context.user_data['bio']}\n\n"
        f"Use /swipe to find matches!"
    )
    context.user_data.clear()
    return ConversationHandler.END

async def done_photos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await photos(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Cancelled.")
    context.user_data.clear()
    return ConversationHandler.END

async def swipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = db.get_profile(user_id)
    if not profile:
        await update.message.reply_text("Use /start first.")
        return
    candidates = db.get_candidates(user_id)
    if not candidates:
        await update.message.reply_text("No one nearby. Try later!")
        return
    context.user_data['candidates'] = candidates
    context.user_data['index'] = 0
    await show_profile(update, context)

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data['index']
    if idx >= len(context.user_data['candidates']):
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.message.reply_text("No more profiles. Use /swipe again.")
        else:
            await update.message.reply_text("No more profiles. Use /swipe again.")
        return
    cand_id = context.user_data['candidates'][idx]
    cand = db.get_profile(cand_id)
    caption = f"{cand['name']}, {cand['age']}\n{cand['city']}\n{cand['bio'][:200]}"
    keyboard = [
        [InlineKeyboardButton("Like", callback_data=f"like_{cand_id}"),
         InlineKeyboardButton("Skip", callback_data=f"skip_{cand_id}")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    chat_id = update.effective_chat.id
    if cand['photos']:
        with open(cand['photos'][0], 'rb') as f:
            if hasattr(update, 'callback_query') and update.callback_query:
                await context.bot.send_photo(chat_id, f, caption=caption, reply_markup=markup)
            else:
                await context.bot.send_photo(chat_id, f, caption=caption, reply_markup=markup)
    else:
        text_msg = caption if not hasattr(update, 'callback_query') else None
        if text_msg:
            await update.message.reply_text(caption, reply_markup=markup)
        else:
            await context.bot.send_message(chat_id, caption, reply_markup=markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    if data.startswith('like_'):
        to_id = int(data.split('_')[1])
        mutual = db.add_like(user_id, to_id)
        if mutual:
            await query.edit_message_text("MATCH! Start chatting.")
            other = db.get_profile(to_id)
            await context.bot.send_message(to_id, f"MATCH with {db.get_profile(user_id)['name']}! Reply to chat.")
        else:
            await query.edit_message_text("Like sent.")
        context.user_data['index'] += 1
        await show_profile(update, context)
    elif data.startswith('skip_'):
        context.user_data['index'] += 1
        await show_profile(update, context)

async def matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    matches = db.get_matches(user_id)
    if not matches:
        await update.message.reply_text("No matches yet.")
        return
    text = "Your matches:\n"
    for m in matches:
        text += f"• {m['name']}, {m['age']} ({m['city']})\n"
    await update.message.reply_text(text)

# Webhook entry point
async def webhook_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await application.process_update(update)

def run_bot():
    global application
    # Init DB
    db.init_db()
    # Build app with webhook
    request = HTTPXRequest(connect_timeout=10, read_timeout=10)
    application = Application.builder().token(TOKEN).request(request).build()
    # Add handlers (same as before)
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, age)],
            GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, gender)],
            LOOKING_FOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, looking_for)],
            CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, city)],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name)],
            BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, bio)],
            PHOTOS: [MessageHandler(filters.PHOTO, photos), CommandHandler('done', done_photos)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    application.add_handler(conv)
    application.add_handler(CommandHandler('swipe', swipe))
    application.add_handler(CommandHandler('matches', matches))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.ALL, webhook_update))  # Catch-all for webhook

def main():
    port = int(os.environ.get('PORT', 10000))
    run_bot()
    # Set webhook (replace with your Render URL after deployment)
    webhook_url = f"https://your-app-name.onrender.com/{TOKEN}"  # Update 'your-app-name' post-deploy
    application.bot.set_webhook(url=webhook_url)
    # Run as web server
    from flask import Flask, request
    app = Flask(__name__)
    @app.route(f'/{TOKEN}', methods=['POST'])
    def webhook():
        if request.headers.get('content-type') == 'application/json':
            json_string = request.get_json()
            update = Update.de_json(json_string, application.bot)
            application.process_update(update)
        return 'ok'
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    main()
