import logging
from telethon import TelegramClient, events, Button
from telethon.errors import SessionPasswordNeededError
from config import API_ID, API_HASH, BOT_TOKEN, TARGET_GROUPS, KEYWORDS, CHANNEL_ID, IGNORE_USERS, load_json_config, update_json_config
import asyncio
import os
from flask import Flask
from threading import Thread

# logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask for Keep Alive
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Clients will be initialized inside start_clients to handle errors properly
main_client = None
bot = None
bot2 = None

# process incoming messages
async def process_message(event):
    message = event.message.message
    sender_id = event.message.sender_id
    logger.info(f"Received a new message from {sender_id}")

    # Load Vars
    config = load_json_config()
    ignore_users = config['IGNORE_USERS']
    keywords = config['KEYWORDS']

    # Messages loop
    if sender_id in ignore_users:
        logger.info(f"Ignoring message from {sender_id}")
        return
    if any(keyword.lower() in message.lower() for keyword in keywords):
        try:
            user = await event.message.get_sender()
            user_id = user.id

            text = f"• Text:\n{message}\n• ID: `{user_id}`\n"

            if event.chat:
                if event.chat.username:
                    message_link = f"https://t.me/{event.chat.username}/{event.id}"
                else:
                    chat_id = str(event.chat_id).replace('-100', '', 1)
                    message_link = f"https://t.me/c/{chat_id}/{event.message.id}"

                buttons = [
                    [Button.url("View Message", url=message_link)]
                ]
                await bot.send_message(CHANNEL_ID, text, buttons=buttons, link_preview=False)
                logger.info(f"Message forwarded to channel {CHANNEL_ID} with button")

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)

# Bot2 buttons
async def start_handler(event):
    buttons = [
        [Button.inline('Update Groups', b'update_groups')],
        [Button.inline('Add Keyword', b'add_keyword'), Button.inline('Remove Keyword', b'remove_keyword')],
        [Button.inline('Ignore User', b'ignore_user')],
        [Button.inline('Remove Ignore User', b'remove_ignore_user')],
    ]
    await event.respond('Management Menu', buttons=buttons)

# Handle button clicks
async def callback_handler(event):
    config = load_json_config()
    if event.data == b'update_groups':
        await main_client.start()
        dialogs = await main_client.get_dialogs()
        groups = [dialog.entity.id for dialog in dialogs if dialog.is_group]
        config['TARGET_GROUPS'] = groups
        update_json_config(config)
        await event.answer(f"Groups updated: {groups}")
    elif event.data == b'ignore_user':
        await event.answer('Please enter the user ID to ignore:')
        bot2.add_event_handler(ignore_user_handler, events.NewMessage())
    elif event.data == b'remove_ignore_user':
        await event.answer('Please enter the user ID to remove from ignore list:')
        bot2.add_event_handler(remove_ignore_user_handler, events.NewMessage())
    elif event.data == b'add_keyword':
        await event.answer('Please enter the keyword to add:')
        bot2.add_event_handler(add_keyword_handler, events.NewMessage())
    elif event.data == b'remove_keyword':
        await event.answer('Please enter the keyword to remove:')
        bot2.add_event_handler(remove_keyword_handler, events.NewMessage())

# Handlers for user inputs
async def ignore_user_handler(event):
    config = load_json_config()
    try:
        user_id = int(event.message.message)
        if user_id not in config['IGNORE_USERS']:
            config['IGNORE_USERS'].append(user_id)
            update_json_config(config)
            await event.respond(f"User {user_id} added to ignore list.")
        else:
            await event.respond(f"User {user_id} is already in the ignore list.")
    except ValueError:
        await event.respond("Invalid User ID.")
    bot2.remove_event_handler(ignore_user_handler)

async def remove_ignore_user_handler(event):
    config = load_json_config()
    try:
        user_id = int(event.message.message)
        if user_id in config['IGNORE_USERS']:
            config['IGNORE_USERS'].remove(user_id)
            update_json_config(config)
            await event.respond(f"User {user_id} removed from ignore list.")
        else:
            await event.respond(f"User {user_id} was not in the ignore list.")
    except ValueError:
        await event.respond("Invalid User ID.")
    bot2.remove_event_handler(remove_ignore_user_handler)

async def add_keyword_handler(event):
    config = load_json_config()
    keyword = event.message.message
    if keyword not in config['KEYWORDS']:
        config['KEYWORDS'].append(keyword)
        update_json_config(config)
        await event.respond(f"Keyword '{keyword}' added.")
    else:
        await event.respond(f"Keyword '{keyword}' already exists.")
    bot2.remove_event_handler(add_keyword_handler)

async def remove_keyword_handler(event):
    config = load_json_config()
    keyword = event.message.message
    if keyword in config['KEYWORDS']:
        config['KEYWORDS'].remove(keyword)
        update_json_config(config)
        await event.respond(f"Keyword '{keyword}' removed.")
    else:
        await event.respond(f"Keyword '{keyword}' not found.")
    bot2.remove_event_handler(remove_keyword_handler)

# Start clients
async def start_clients():
    global main_client, bot, bot2
    try:
        if not all([API_ID, API_HASH, BOT_TOKEN, CHANNEL_ID]):
            logger.error("Missing environment variables. Please check your configuration.")
            return

        main_client = TelegramClient("session_main", API_ID, API_HASH)
        bot = TelegramClient('session_bot', API_ID, API_HASH)
        bot2 = TelegramClient("session_bot2", API_ID, API_HASH)

        await main_client.start()
        await bot.start(bot_token=BOT_TOKEN)
        await bot2.start(bot_token=BOT_TOKEN)

        logger.info("All clients started successfully")

        # Register handlers
        main_client.add_event_handler(process_message, events.NewMessage(chats=TARGET_GROUPS))
        bot2.add_event_handler(start_handler, events.NewMessage(pattern='/start'))
        bot2.add_event_handler(callback_handler, events.CallbackQuery())

        # Startup messages
        try:
            await main_client.send_message(CHANNEL_ID, "Monitoring Account Started")
            await bot.send_message(CHANNEL_ID, "Forwarding Bot Started")
        except Exception as e:
            logger.error(f"Could not send startup messages: {e}")

        # Run until disconnected
        await asyncio.gather(
            main_client.run_until_disconnected(),
            bot.run_until_disconnected(),
            bot2.run_until_disconnected()
        )

    except SessionPasswordNeededError:
        logger.error("2FA enabled. This environment doesn't support interactive login.")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        if main_client: await main_client.disconnect()
        if bot: await bot.disconnect()
        if bot2: await bot2.disconnect()

if __name__ == '__main__':
    keep_alive()
    asyncio.run(start_clients())
