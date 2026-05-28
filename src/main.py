import logging
import asyncio
import os
import json
from telethon import TelegramClient, events, Button
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from flask import Flask
from threading import Thread
from config import API_ID, API_HASH, BOT_TOKEN, CHANNEL_ID, load_json_config, update_json_config

# Logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flask for Keep Alive (Render)
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

# Global variables to manage sessions
bot = TelegramClient('bot_session', API_ID, API_HASH)
active_clients = {} # {phone: TelegramClient}
login_states = {} # {user_id: {'step': 'phone/code', 'phone': '...', 'hash': '...'}}

async def start_monitoring(client, phone):
    """Start monitoring for a specific account client."""
    @client.on(events.NewMessage())
    async def handler(event):
        config = load_json_config()
        keywords = config.get('KEYWORDS', [])
        ignore_users = config.get('IGNORE_USERS', [])
        target_groups = config.get('TARGET_GROUPS', [])
        
        if event.is_group and (not target_groups or event.chat_id in target_groups):
            sender_id = event.sender_id
            if sender_id in ignore_users:
                return
            
            message_text = event.message.message or ""
            if any(kw.lower() in message_text.lower() for kw in keywords):
                try:
                    # Construct forward message
                    chat = await event.get_chat()
                    chat_title = getattr(chat, 'title', 'Unknown Group')
                    
                    link = ""
                    if event.chat:
                        if getattr(event.chat, 'username', None):
                            link = f"https://t.me/{event.chat.username}/{event.id}"
                        else:
                            c_id = str(event.chat_id).replace('-100', '')
                            link = f"https://t.me/c/{c_id}/{event.id}"
                    
                    forward_text = (
                        f"📢 **New Match Found!**\n\n"
                        f"👥 **Group:** {chat_title}\n"
                        f"👤 **User ID:** `{sender_id}`\n"
                        f"📝 **Message:**\n{message_text}\n"
                    )
                    
                    buttons = [[Button.url("View Message", url=link)]] if link else None
                    await bot.send_message(CHANNEL_ID, forward_text, buttons=buttons)
                    logger.info(f"Forwarded message from {phone}")
                except Exception as e:
                    logger.error(f"Error forwarding message: {e}")

    logger.info(f"Started monitoring for {phone}")
    await client.run_until_disconnected()

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    buttons = [
        [Button.inline('➕ Add Account', b'add_acc')],
        [Button.inline('📋 List Accounts', b'list_acc')],
        [Button.inline('⚙️ Keywords', b'manage_kw')],
        [Button.inline('🚫 Ignore List', b'manage_ignore')]
    ]
    await event.respond('👋 **Welcome to Telegram Monitor Manager**\n\nChoose an option:', buttons=buttons)

@bot.on(events.CallbackQuery())
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data
    
    if data == b'add_acc':
        login_states[user_id] = {'step': 'await_phone'}
        await event.respond("📱 Please send the **Phone Number** in international format (e.g., +1234567890):")
    
    elif data == b'list_acc':
        if not active_clients:
            await event.respond("❌ No active accounts linked.")
        else:
            msg = "✅ **Linked Accounts:**\n"
            for phone in active_clients.keys():
                msg += f"- `{phone}`\n"
            await event.respond(msg)

    elif data == b'manage_kw':
        config = load_json_config()
        kw_list = config.get('KEYWORDS', [])
        msg = "🔑 **Current Keywords:**\n" + ("\n".join([f"- `{k}`" for k in kw_list]) if kw_list else "None")
        buttons = [[Button.inline('➕ Add Keyword', b'add_kw')], [Button.inline('🔙 Back', b'back_main')]]
        await event.respond(msg, buttons=buttons)

@bot.on(events.NewMessage())
async def input_handler(event):
    user_id = event.sender_id
    if user_id not in login_states:
        return
    
    state = login_states[user_id]
    text = event.message.message
    
    if state['step'] == 'await_phone':
        phone = text.strip()
        new_client = TelegramClient(f'session_{phone}', API_ID, API_HASH)
        await new_client.connect()
        
        try:
            sent_code = await new_client.send_code_request(phone)
            login_states[user_id] = {
                'step': 'await_code',
                'phone': phone,
                'hash': sent_code.phone_code_hash,
                'client': new_client
            }
            await event.respond(f"📩 Code sent to `{phone}`. Please enter the code:")
        except Exception as e:
            await event.respond(f"❌ Error: {e}")
            del login_states[user_id]

    elif state['step'] == 'await_code':
        code = text.strip()
        phone = state['phone']
        client = state['client']
        phone_hash = state['hash']
        
        try:
            await client.sign_in(phone, code, phone_code_hash=phone_hash)
            await event.respond(f"✅ Successfully linked `{phone}`!")
            active_clients[phone] = client
            asyncio.create_task(start_monitoring(client, phone))
            del login_states[user_id]
        except SessionPasswordNeededError:
            login_states[user_id]['step'] = 'await_password'
            await event.respond("🔐 2FA is enabled. Please enter your password:")
        except PhoneCodeInvalidError:
            await event.respond("❌ Invalid code. Try again:")
        except Exception as e:
            await event.respond(f"❌ Error: {e}")
            del login_states[user_id]

    elif state['step'] == 'await_password':
        password = text.strip()
        client = state['client']
        phone = state['phone']
        try:
            await client.sign_in(password=password)
            await event.respond(f"✅ Successfully linked `{phone}` with 2FA!")
            active_clients[phone] = client
            asyncio.create_task(start_monitoring(client, phone))
            del login_states[user_id]
        except Exception as e:
            await event.respond(f"❌ Error: {e}")
            del login_states[user_id]

async def main():
    keep_alive()
    logger.info("Starting Bot...")
    await bot.start(bot_token=BOT_TOKEN)
    
    # Try to resume existing sessions
    session_files = [f for f in os.listdir('.') if f.startswith('session_') and f.endswith('.session')]
    for f in session_files:
        phone = f.replace('session_', '').replace('.session', '')
        if phone == "bot": continue
        try:
            client = TelegramClient(f.replace('.session', ''), API_ID, API_HASH)
            await client.start()
            active_clients[phone] = client
            asyncio.create_task(start_monitoring(client, phone))
            logger.info(f"Resumed session for {phone}")
        except Exception as e:
            logger.error(f"Failed to resume {phone}: {e}")

    logger.info("Bot is fully operational.")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
