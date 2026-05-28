import logging
import asyncio
import os
import json
from telethon import TelegramClient, events, Button
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from telethon.tl.types import Chat, Channel
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
    return "البوت يعمل بنجاح!"

def run():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

# Global variables
bot = None
active_clients = {} # {phone: TelegramClient}
login_states = {} # {user_id: {'step': 'phone/code', 'phone': '...', 'hash': '...'}}

async def import_groups(client):
    """استيراد كافة المجموعات التي ينتمي إليها الحساب."""
    config = load_json_config()
    current_groups = config.get('TARGET_GROUPS', [])
    new_groups_count = 0
    
    async for dialog in client.iter_dialogs():
        if dialog.is_group or dialog.is_channel:
            if dialog.id not in current_groups:
                current_groups.append(dialog.id)
                new_groups_count += 1
    
    config['TARGET_GROUPS'] = current_groups
    update_json_config(config)
    return new_groups_count

async def start_monitoring(client, phone):
    """بدء مراقبة الرسائل للحساب المرتبط."""
    @client.on(events.NewMessage())
    async def handler(event):
        config = load_json_config()
        keywords = config.get('KEYWORDS', [])
        ignore_users = config.get('IGNORE_USERS', [])
        target_groups = config.get('TARGET_GROUPS', [])
        
        if event.is_group:
            if target_groups and event.chat_id not in target_groups:
                return
                
            sender_id = event.sender_id
            if sender_id in ignore_users:
                return
            
            message_text = event.message.message or ""
            if any(kw.lower() in message_text.lower() for kw in keywords):
                try:
                    chat = await event.get_chat()
                    chat_title = getattr(chat, 'title', 'مجموعة غير معروفة')
                    
                    link = ""
                    if event.chat:
                        if getattr(event.chat, 'username', None):
                            link = f"https://t.me/{event.chat.username}/{event.id}"
                        else:
                            c_id = str(event.chat_id).replace('-100', '')
                            link = f"https://t.me/c/{c_id}/{event.id}"
                    
                    forward_text = (
                        f"📢 **تم العثور على رسالة مطابقة!**\n\n"
                        f"👥 **المجموعة:** {chat_title}\n"
                        f"👤 **معرف المرسل:** `{sender_id}`\n"
                        f"📝 **الرسالة:**\n{message_text}\n"
                    )
                    
                    buttons = [[Button.url("عرض الرسالة الأصلية", url=link)]] if link else None
                    await bot.send_message(CHANNEL_ID, forward_text, buttons=buttons)
                    logger.info(f"تم توجيه رسالة من الحساب {phone}")
                except Exception as e:
                    logger.error(f"خطأ في توجيه الرسالة: {e}")

    logger.info(f"بدأت المراقبة للحساب {phone}")
    try:
        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"انقطع اتصال الحساب {phone}: {e}")

async def setup_bot_handlers():
    @bot.on(events.NewMessage(pattern='/start'))
    async def start_handler(event):
        buttons = [
            [Button.inline('➕ إضافة حساب', b'add_acc'), Button.inline('📋 الحسابات المرتبطة', b'list_acc')],
            [Button.inline('🔑 الكلمات المفتاحية', b'manage_kw'), Button.inline('🚫 قائمة التجاهل', b'manage_ignore')],
            [Button.inline('👥 المجموعات المستهدفة', b'manage_groups'), Button.inline('❌ حذف حساب', b'rem_acc')]
        ]
        await event.respond('👋 **أهلاً بك في مدير مراقبة تيليجرام**\n\nتحكم في حساباتك وإعدادات المراقبة من هنا:', buttons=buttons)

    @bot.on(events.CallbackQuery())
    async def callback_handler(event):
        user_id = event.sender_id
        data = event.data
        config = load_json_config()
        
        if data == b'add_acc':
            login_states[user_id] = {'step': 'await_phone'}
            await event.respond("📱 من فضلك أرسل **رقم الهاتف** مع مفتاح الدولة (مثال: +9665xxxxxxxx):")
        
        elif data == b'list_acc':
            if not active_clients:
                await event.respond("❌ لا توجد حسابات مرتبطة حالياً.")
            else:
                msg = "✅ **الحسابات المرتبطة:**\n" + "\n".join([f"- `{p}`" for p in active_clients.keys()])
                await event.respond(msg)

        elif data == b'manage_kw':
            kw_list = config.get('KEYWORDS', [])
            msg = "🔑 **الكلمات المفتاحية الحالية:**\n" + ("\n".join([f"- `{k}`" for k in kw_list]) if kw_list else "لا توجد كلمات.")
            buttons = [[Button.inline('➕ إضافة', b'add_kw'), Button.inline('➖ حذف', b'rem_kw')], [Button.inline('🔙 رجوع', b'back_main')]]
            await event.respond(msg, buttons=buttons)

        elif data == b'manage_ignore':
            ignore_list = config.get('IGNORE_USERS', [])
            msg = "🚫 **قائمة التجاهل (ID المستخدمين):**\n" + ("\n".join([f"- `{u}`" for u in ignore_list]) if ignore_list else "القائمة فارغة.")
            buttons = [[Button.inline('➕ إضافة', b'add_ignore'), Button.inline('➖ حذف', b'rem_ignore')], [Button.inline('🔙 رجوع', b'back_main')]]
            await event.respond(msg, buttons=buttons)

        elif data == b'manage_groups':
            group_list = config.get('TARGET_GROUPS', [])
            msg = f"👥 **المجموعات المستهدفة:** تم استيراد `{len(group_list)}` مجموعة.\n" + "(يتم مراقبة جميع المجموعات المستوردة)" if group_list else "لا توجد مجموعات مستوردة."
            buttons = [[Button.inline('➕ إضافة يدوي', b'add_group'), Button.inline('➖ حذف يدوي', b'rem_group')], 
                       [Button.inline('🔄 تحديث واستيراد', b'refresh_groups')],
                       [Button.inline('🔙 رجوع', b'back_main')]]
            await event.respond(msg, buttons=buttons)

        elif data == b'refresh_groups':
            if not active_clients:
                await event.respond("❌ يجب ربط حساب واحد على الأقل للاستيراد.")
            else:
                total_new = 0
                for phone, client in active_clients.items():
                    total_new += await import_groups(client)
                await event.respond(f"✅ تم الانتهاء! تم استيراد `{total_new}` مجموعة جديدة.")

        elif data == b'rem_acc':
            if not active_clients:
                await event.respond("❌ لا توجد حسابات لحذفها.")
            else:
                buttons = [[Button.inline(p, f"del_acc_{p}".encode())] for p in active_clients.keys()]
                buttons.append([Button.inline('🔙 رجوع', b'back_main')])
                await event.respond("🗑 اختر الحساب الذي تريد حذفه:", buttons=buttons)

        elif data.startswith(b'del_acc_'):
            phone = data.decode().replace('del_acc_', '')
            if phone in active_clients:
                await active_clients[phone].disconnect()
                del active_clients[phone]
                if os.path.exists(f'session_{phone}.session'):
                    os.remove(f'session_{phone}.session')
                await event.respond(f"✅ تم حذف الحساب `{phone}` بنجاح.")
            else:
                await event.respond("❌ الحساب غير موجود.")

        elif data == b'back_main':
            await start_handler(event)

        elif data in [b'add_kw', b'rem_kw', b'add_ignore', b'rem_ignore', b'add_group', b'rem_group']:
            login_states[user_id] = {'step': data.decode()}
            await event.respond(f"📝 من فضلك أرسل القيمة التي تريد تنفيذ الإجراء عليها:")

    @bot.on(events.NewMessage())
    async def input_handler(event):
        user_id = event.sender_id
        if user_id not in login_states: return
        state = login_states[user_id]
        text = event.message.message.strip()
        config = load_json_config()
        
        if state['step'] == 'await_phone':
            phone = text
            new_client = TelegramClient(f'session_{phone}', API_ID, API_HASH)
            await new_client.connect()
            try:
                sent_code = await new_client.send_code_request(phone)
                login_states[user_id] = {'step': 'await_code', 'phone': phone, 'hash': sent_code.phone_code_hash, 'client': new_client}
                await event.respond(f"📩 تم إرسال الكود إلى `{phone}`. من فضلك أرسل الكود هنا:")
            except Exception as e:
                await event.respond(f"❌ خطأ: {e}"); del login_states[user_id]
        
        elif state['step'] == 'await_code':
            try:
                client = state['client']
                await client.sign_in(state['phone'], text, phone_code_hash=state['hash'])
                await event.respond(f"✅ تم ربط الحساب `{state['phone']}` بنجاح! جاري استيراد المجموعات...")
                
                # تلقائياً استيراد المجموعات عند الإضافة
                new_count = await import_groups(client)
                await event.respond(f"📦 تم استيراد `{new_count}` مجموعة جديدة من هذا الحساب.")
                
                active_clients[state['phone']] = client
                asyncio.create_task(start_monitoring(client, state['phone']))
                del login_states[user_id]
            except SessionPasswordNeededError:
                state['step'] = 'await_password'
                await event.respond("🔐 هذا الحساب محمي بكلمة سر (2FA). من فضلك أرسل كلمة السر:")
            except Exception as e:
                await event.respond(f"❌ خطأ: {e}"); del login_states[user_id]

        elif state['step'] == 'await_password':
            try:
                client = state['client']
                await client.sign_in(password=text)
                await event.respond(f"✅ تم ربط الحساب `{state['phone']}` بنجاح! جاري استيراد المجموعات...")
                
                new_count = await import_groups(client)
                await event.respond(f"📦 تم استيراد `{new_count}` مجموعة جديدة.")
                
                active_clients[state['phone']] = client
                asyncio.create_task(start_monitoring(client, state['phone']))
                del login_states[user_id]
            except Exception as e:
                await event.respond(f"❌ خطأ: {e}"); del login_states[user_id]

        elif state['step'] == 'add_kw':
            config['KEYWORDS'] = list(set(config.get('KEYWORDS', []) + [text]))
            update_json_config(config)
            await event.respond(f"✅ تم إضافة الكلمة: `{text}`"); del login_states[user_id]

        elif state['step'] == 'rem_kw':
            config['KEYWORDS'] = [k for k in config.get('KEYWORDS', []) if k != text]
            update_json_config(config)
            await event.respond(f"✅ تم حذف الكلمة: `{text}`"); del login_states[user_id]

        elif state['step'] == 'add_ignore':
            try:
                config['IGNORE_USERS'] = list(set(config.get('IGNORE_USERS', []) + [int(text)]))
                update_json_config(config)
                await event.respond(f"✅ تم إضافة المعرف `{text}` لقائمة التجاهل."); del login_states[user_id]
            except: await event.respond("❌ المعرف غير صحيح.")

        elif state['step'] == 'rem_ignore':
            try:
                config['IGNORE_USERS'] = [u for u in config.get('IGNORE_USERS', []) if u != int(text)]
                update_json_config(config)
                await event.respond(f"✅ تم حذف المعرف `{text}` من قائمة التجاهل."); del login_states[user_id]
            except: await event.respond("❌ المعرف غير صحيح.")

async def main():
    global bot
    keep_alive()
    logger.info("جاري تشغيل البوت...")
    bot = TelegramClient('bot_session', API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)
    await setup_bot_handlers()
    
    # Resume existing sessions
    for f in os.listdir('.'):
        if f.startswith('session_') and f.endswith('.session') and f != 'bot_session.session':
            phone = f.replace('session_', '').replace('.session', '')
            try:
                client = TelegramClient(f.replace('.session', ''), API_ID, API_HASH)
                await client.connect()
                if await client.is_user_authorized():
                    active_clients[phone] = client
                    asyncio.create_task(start_monitoring(client, phone))
                    logger.info(f"تم استئناف الحساب {phone}")
                else:
                    logger.warning(f"الجلسة {phone} غير مصرحة.")
            except Exception as e:
                logger.error(f"فشل استئناف الحساب {phone}: {e}")

    logger.info("البوت يعمل الآن بكامل طاقته.")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
