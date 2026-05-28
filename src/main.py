import logging
import asyncio
import os
import json
import re
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

# ============ دوال الفلترة المتقدمة ============

def is_announcement(text, banned_ads_list):
    """كشف الرسائل الإعلانية بناءً على كلمات مفتاحية محظورة"""
    text_lower = text.lower()
    for kw in banned_ads_list:
        if kw.lower() in text_lower:
            return True
    return False

def contains_link(text):
    """كشف وجود رابط في النص"""
    url_pattern = r'https?://[^\s]+|t\.me/[^\s]+|bit\.ly/[^\s]+|tinyurl\.com/[^\s]+|[a-zA-Z0-9-]+\.(com|net|org|info|xyz|club|online|site|top|ml|tk|cf|ga|gq)[^\s]*'
    return bool(re.search(url_pattern, text))

def contains_phone(text):
    """كشف وجود رقم هاتف"""
    phone_patterns = [
        r'\b0[0-9]{9,10}\b',
        r'\b\+?[0-9]{1,4}[-.]?[0-9]{8,12}\b',
        r'\b[0-9]{3}[-.]?[0-9]{3}[-.]?[0-9]{4}\b',
        r'\b[0-9]{4,5}[-.]?[0-9]{5,6}\b'
    ]
    for pattern in phone_patterns:
        if re.search(pattern, text):
            return True
    return False

def contains_mention(text):
    """كشف وجود معرفات (@username)"""
    mention_pattern = r'@[a-zA-Z0-9_]+'
    return bool(re.search(mention_pattern, text))

def is_too_long(text, max_length=50):
    """الرسالة طويلة جداً (أكثر من max_length)"""
    return len(text.strip()) > max_length

def contains_suspicious_words(text, suspicious_words):
    """كشف الكلمات المشبوهة"""
    text_lower = text.lower()
    for word in suspicious_words:
        if word.lower() in text_lower:
            return True
    return False

def should_ignore_message(message_text, config):
    """تطبيق جميع شروط التجاهل"""
    ignore_reasons = []
    
    # الحصول على إعدادات الفلترة
    filters = config.get('FILTERS', {
        'max_length': 50,
        'block_links': True,
        'block_phones': True,
        'block_mentions': True,
        'block_ads': True,
        'block_suspicious': True
    })
    
    banned_ads = config.get('BANNED_ADS', [])
    suspicious_words = config.get('SUSPICIOUS_WORDS', [])
    
    # شرط 1: عدد الأحرف
    if filters.get('max_length', 50) > 0:
        max_len = filters.get('max_length', 50)
        if is_too_long(message_text, max_len):
            ignore_reasons.append(f"⚠️ تجاوز {max_len} حرفاً ({len(message_text.strip())} حرف)")
    
    # شرط 2: يحتوي على رابط
    if filters.get('block_links', True) and contains_link(message_text):
        ignore_reasons.append("❌ يحتوي على رابط")
    
    # شرط 3: يحتوي على رقم هاتف
    if filters.get('block_phones', True) and contains_phone(message_text):
        ignore_reasons.append("❌ يحتوي على رقم هاتف")
    
    # شرط 4: يحتوي على معرف
    if filters.get('block_mentions', True) and contains_mention(message_text):
        ignore_reasons.append("❌ يحتوي على معرف @")
    
    # شرط 5: رسالة إعلانية (كلمات محظورة)
    if filters.get('block_ads', True) and banned_ads and is_announcement(message_text, banned_ads):
        ignore_reasons.append("📢 رسالة إعلانية (كلمة محظورة)")
    
    # شرط 6: كلمات مشبوهة
    if filters.get('block_suspicious', True) and suspicious_words and contains_suspicious_words(message_text, suspicious_words):
        ignore_reasons.append("⚠️ يحتوي على كلمات مشبوهة")
    
    return ignore_reasons

async def import_groups(client):
    """استيراد كافة المجموعات التي ينتمي إليها الحساب (للعرض فقط، لا تستخدم في التصفية)"""
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
    """بدء مراقبة الرسائل للحساب المرتبط - يراقب جميع المجموعات تلقائياً بدون استثناء"""
    
    # إضافة مهمة دورية للحفاظ على الاتصال (Keep-Alive)
    async def keep_connection_alive():
        while True:
            await asyncio.sleep(300)  # كل 5 دقائق
            try:
                await client.get_me()
                logger.info(f"✅ تم إرسال إشارة البقاء على قيد الحياة للحساب {phone}")
            except Exception as e:
                logger.error(f"⚠️ فشل إرسال إشارة البقاء: {e}")
                try:
                    await client.disconnect()
                    await client.connect()
                    logger.info(f"🔄 تمت إعادة الاتصال للحساب {phone}")
                except Exception as reconnect_error:
                    logger.error(f"❌ فشلت إعادة الاتصال: {reconnect_error}")
    
    asyncio.create_task(keep_connection_alive())
    
    @client.on(events.NewMessage())
    async def handler(event):
        config = load_json_config()
        keywords = config.get('KEYWORDS', [])
        ignore_users = config.get('IGNORE_USERS', [])
        
        # ===== التعديل الأساسي: إلغاء شرط target_groups بالكامل =====
        # أصبح البوت يراقب كل المجموعات التي فيها الحساب تلقائياً
        if event.is_group:
            # التحقق من تجاهل المستخدم
            sender_id = event.sender_id
            if sender_id in ignore_users:
                return
            
            message_text = event.message.message or ""
            
            # تطبيق شروط الفلترة
            ignore_reasons = should_ignore_message(message_text, config)
            
            if ignore_reasons:
                logger.info(f"تم تجاهل رسالة من {phone}: {', '.join(ignore_reasons)}")
                return
            
            # التحقق من الكلمات المفتاحية
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

    logger.info(f"بدأت المراقبة للحساب {phone} - سيتم مراقبة جميع المجموعات تلقائياً")
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
            [Button.inline('👥 المجموعات المستهدفة', b'manage_groups'), Button.inline('❌ حذف حساب', b'rem_acc')],
            [Button.inline('🛡️ كلمات محظورة ومشبوهة', b'manage_banned')],
            [Button.inline('⚙️ إعدادات الفلترة', b'manage_filters')]
        ]
        await event.respond('👋 **أهلاً بك في مدير مراقبة تيليجرام**\n\nتحكم في حساباتك وإعدادات المراقبة من هنا:', buttons=buttons)

    @bot.on(events.CallbackQuery())
    async def callback_handler(event):
        user_id = event.sender_id
        data = event.data
        config = load_json_config()
        
        # ============ إدارة الحسابات ============
        
        if data == b'add_acc':
            login_states[user_id] = {'step': 'await_phone'}
            await event.respond("📱 من فضلك أرسل **رقم الهاتف** مع مفتاح الدولة (مثال: +9665xxxxxxxx):")
        
        elif data == b'list_acc':
            if not active_clients:
                await event.respond("❌ لا توجد حسابات مرتبطة حالياً.")
            else:
                msg = "✅ **الحسابات المرتبطة:**\n" + "\n".join([f"- `{p}`" for p in active_clients.keys()])
                await event.respond(msg)

        # ============ إدارة الكلمات المفتاحية ============
        
        elif data == b'manage_kw':
            kw_list = config.get('KEYWORDS', [])
            msg = "🔑 **الكلمات المفتاحية الحالية:**\n" + ("\n".join([f"- `{k}`" for k in kw_list]) if kw_list else "لا توجد كلمات.")
            buttons = [[Button.inline('➕ إضافة', b'add_kw'), Button.inline('➖ حذف', b'rem_kw')], [Button.inline('🔙 رجوع', b'back_main')]]
            await event.respond(msg, buttons=buttons)

        # ============ إدارة قائمة التجاهل ============
        
        elif data == b'manage_ignore':
            ignore_list = config.get('IGNORE_USERS', [])
            msg = "🚫 **قائمة التجاهل (ID المستخدمين):**\n" + ("\n".join([f"- `{u}`" for u in ignore_list]) if ignore_list else "القائمة فارغة.")
            buttons = [[Button.inline('➕ إضافة', b'add_ignore'), Button.inline('➖ حذف', b'rem_ignore')], [Button.inline('🔙 رجوع', b'back_main')]]
            await event.respond(msg, buttons=buttons)

        # ============ إدارة المجموعات (للعرض فقط) ============
        
        elif data == b'manage_groups':
            group_list = config.get('TARGET_GROUPS', [])
            msg = f"👥 **المجموعات المستوردة (للعرض فقط):** تم استيراد `{len(group_list)}` مجموعة.\n\n"
            msg += "🔹 **ملاحظة:** البوت يراقب **جميع** المجموعات التي فيها حسابك تلقائياً، بغض النظر عن هذه القائمة."
            buttons = [
                [Button.inline('🔄 تحديث واستيراد', b'refresh_groups')],
                [Button.inline('➕ إضافة يدوي (للعرض)', b'add_group'), Button.inline('➖ حذف يدوي (للعرض)', b'rem_group')],
                [Button.inline('🔙 رجوع', b'back_main')]
            ]
            await event.respond(msg, buttons=buttons)

        elif data == b'refresh_groups':
            if not active_clients:
                await event.respond("❌ يجب ربط حساب واحد على الأقل للاستيراد.")
            else:
                total_new = 0
                for phone, client in active_clients.items():
                    new = await import_groups(client)
                    total_new += new
                await event.respond(f"✅ تم تحديث القائمة! تم استيراد `{total_new}` مجموعة جديدة (هذه القائمة للعرض فقط، والمراقبة تشمل جميع المجموعات).")

        # ============ حذف حساب ============
        
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

        # ============ إدارة الكلمات المحظورة والمشبوهة ============
        
        elif data == b'manage_banned':
            banned_ads = config.get('BANNED_ADS', [])
            suspicious = config.get('SUSPICIOUS_WORDS', [])
            
            msg = "🛡️ **قائمة الكلمات المحظورة والمشبوهة**\n\n"
            msg += "📢 **كلمات إعلانية محظورة:**\n"
            msg += "\n".join([f"- `{w}`" for w in banned_ads]) if banned_ads else "- (لا توجد كلمات)"
            msg += "\n\n⚠️ **كلمات مشبوهة:**\n"
            msg += "\n".join([f"- `{w}`" for w in suspicious]) if suspicious else "- (لا توجد كلمات)"
            
            buttons = [
                [Button.inline('📢 إضافة كلمة إعلانية محظورة', b'add_banned_ad')],
                [Button.inline('📢 حذف كلمة إعلانية محظورة', b'rem_banned_ad')],
                [Button.inline('⚠️ إضافة كلمة مشبوهة', b'add_suspicious')],
                [Button.inline('⚠️ حذف كلمة مشبوهة', b'rem_suspicious')],
                [Button.inline('🔙 رجوع', b'back_main')]
            ]
            await event.respond(msg, buttons=buttons)
        
        # إضافة كلمة إعلانية محظورة
        elif data == b'add_banned_ad':
            login_states[user_id] = {'step': 'add_banned_ad'}
            await event.respond("📝 أرسل الكلمة الإعلانية التي تريد حظرها (مثال: عرض, خصم, سعر):")
        
        # حذف كلمة إعلانية محظورة
        elif data == b'rem_banned_ad':
            banned_ads = config.get('BANNED_ADS', [])
            if not banned_ads:
                await event.respond("❌ لا توجد كلمات محظورة لحذفها.")
            else:
                buttons = [[Button.inline(w, f"del_banned_ad_{w}".encode())] for w in banned_ads]
                buttons.append([Button.inline('🔙 رجوع', b'manage_banned')])
                await event.respond("🗑 اختر الكلمة التي تريد حذفها:", buttons=buttons)
        
        elif data.startswith(b'del_banned_ad_'):
            word = data.decode().replace('del_banned_ad_', '')
            config = load_json_config()
            banned_ads = config.get('BANNED_ADS', [])
            if word in banned_ads:
                banned_ads.remove(word)
                config['BANNED_ADS'] = banned_ads
                update_json_config(config)
                await event.respond(f"✅ تم حذف الكلمة `{word}` من قائمة الكلمات الإعلانية المحظورة.")
            else:
                await event.respond("❌ الكلمة غير موجودة.")
        
        # إضافة كلمة مشبوهة
        elif data == b'add_suspicious':
            login_states[user_id] = {'step': 'add_suspicious'}
            await event.respond("📝 أرسل الكلمة المشبوهة التي تريد حظرها (مثال: احتيال, نصبة, فيروس):")
        
        # حذف كلمة مشبوهة
        elif data == b'rem_suspicious':
            suspicious = config.get('SUSPICIOUS_WORDS', [])
            if not suspicious:
                await event.respond("❌ لا توجد كلمات مشبوهة لحذفها.")
            else:
                buttons = [[Button.inline(w, f"del_suspicious_{w}".encode())] for w in suspicious]
                buttons.append([Button.inline('🔙 رجوع', b'manage_banned')])
                await event.respond("🗑 اختر الكلمة المشبوهة التي تريد حذفها:", buttons=buttons)
        
        elif data.startswith(b'del_suspicious_'):
            word = data.decode().replace('del_suspicious_', '')
            config = load_json_config()
            suspicious = config.get('SUSPICIOUS_WORDS', [])
            if word in suspicious:
                suspicious.remove(word)
                config['SUSPICIOUS_WORDS'] = suspicious
                update_json_config(config)
                await event.respond(f"✅ تم حذف الكلمة `{word}` من قائمة الكلمات المشبوهة.")
            else:
                await event.respond("❌ الكلمة غير موجودة.")

        # ============ إعدادات الفلترة ============
        
        elif data == b'manage_filters':
            filters = config.get('FILTERS', {
                'max_length': 50,
                'block_links': True,
                'block_phones': True,
                'block_mentions': True,
                'block_ads': True,
                'block_suspicious': True
            })
            
            msg = "⚙️ **إعدادات الفلترة**\n\n"
            msg += f"📏 الحد الأقصى للأحرف: `{filters.get('max_length', 50)}`\n"
            msg += f"🔗 منع الروابط: `{'✅ مفعل' if filters.get('block_links', True) else '❌ معطل'}`\n"
            msg += f"📞 منع أرقام الهواتف: `{'✅ مفعل' if filters.get('block_phones', True) else '❌ معطل'}`\n"
            msg += f"👤 منع المعرفات (@): `{'✅ مفعل' if filters.get('block_mentions', True) else '❌ معطل'}`\n"
            msg += f"📢 منع الكلمات الإعلانية: `{'✅ مفعل' if filters.get('block_ads', True) else '❌ معطل'}`\n"
            msg += f"⚠️ منع الكلمات المشبوهة: `{'✅ مفعل' if filters.get('block_suspicious', True) else '❌ معطل'}`\n"
            
            buttons = [
                [Button.inline('📏 تغيير الحد الأقصى', b'set_max_length')],
                [Button.inline('🔗 تبديل منع الروابط', b'toggle_links')],
                [Button.inline('📞 تبديل منع الأرقام', b'toggle_phones')],
                [Button.inline('👤 تبديل منع المعرفات', b'toggle_mentions')],
                [Button.inline('📢 تبديل منع الإعلانات', b'toggle_ads')],
                [Button.inline('⚠️ تبديل منع المشبوهة', b'toggle_suspicious')],
                [Button.inline('🔙 رجوع', b'back_main')]
            ]
            await event.respond(msg, buttons=buttons)
        
        # تبديل الإعدادات
        elif data == b'set_max_length':
            login_states[user_id] = {'step': 'set_max_length'}
            await event.respond("📏 أرسل الحد الأقصى الجديد لعدد الأحرف (رقم بين 10 و 500):")
        
        elif data == b'toggle_links':
            filters = config.get('FILTERS', {})
            filters['block_links'] = not filters.get('block_links', True)
            config['FILTERS'] = filters
            update_json_config(config)
            await event.respond(f"✅ تم {'تفعيل' if filters['block_links'] else 'تعطيل'} منع الروابط.")
        
        elif data == b'toggle_phones':
            filters = config.get('FILTERS', {})
            filters['block_phones'] = not filters.get('block_phones', True)
            config['FILTERS'] = filters
            update_json_config(config)
            await event.respond(f"✅ تم {'تفعيل' if filters['block_phones'] else 'تعطيل'} منع أرقام الهواتف.")
        
        elif data == b'toggle_mentions':
            filters = config.get('FILTERS', {})
            filters['block_mentions'] = not filters.get('block_mentions', True)
            config['FILTERS'] = filters
            update_json_config(config)
            await event.respond(f"✅ تم {'تفعيل' if filters['block_mentions'] else 'تعطيل'} منع المعرفات (@).")
        
        elif data == b'toggle_ads':
            filters = config.get('FILTERS', {})
            filters['block_ads'] = not filters.get('block_ads', True)
            config['FILTERS'] = filters
            update_json_config(config)
            await event.respond(f"✅ تم {'تفعيل' if filters['block_ads'] else 'تعطيل'} منع الكلمات الإعلانية.")
        
        elif data == b'toggle_suspicious':
            filters = config.get('FILTERS', {})
            filters['block_suspicious'] = not filters.get('block_suspicious', True)
            config['FILTERS'] = filters
            update_json_config(config)
            await event.respond(f"✅ تم {'تفعيل' if filters['block_suspicious'] else 'تعطيل'} منع الكلمات المشبوهة.")
        
        # رجوع للقائمة الرئيسية
        elif data == b'back_main':
            await start_handler(event)
        
        # إدارة باقي العناصر (إضافة/حذف يدوي للمجموعات والكلمات)
        elif data in [b'add_kw', b'rem_kw', b'add_ignore', b'rem_ignore', b'add_group', b'rem_group']:
            login_states[user_id] = {'step': data.decode()}
            await event.respond(f"📝 من فضلك أرسل القيمة التي تريد تنفيذ الإجراء عليها:")

    # ============ معالج الإدخال النصي ============
    
    @bot.on(events.NewMessage())
    async def input_handler(event):
        user_id = event.sender_id
        if user_id not in login_states: return
        state = login_states[user_id]
        text = event.message.message.strip()
        config = load_json_config()
        
        # إضافة حساب - رقم الهاتف
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
        
        # إضافة حساب - رمز التحقق
        elif state['step'] == 'await_code':
            try:
                client = state['client']
                await client.sign_in(state['phone'], text, phone_code_hash=state['hash'])
                await event.respond(f"✅ تم ربط الحساب `{state['phone']}` بنجاح! جاري استيراد المجموعات...")
                
                new_count = await import_groups(client)
                await event.respond(f"📦 تم استيراد `{new_count}` مجموعة (هذه القائمة للعرض فقط، والمراقبة تشمل جميع المجموعات).")
                
                active_clients[state['phone']] = client
                asyncio.create_task(start_monitoring(client, state['phone']))
                del login_states[user_id]
            except SessionPasswordNeededError:
                state['step'] = 'await_password'
                await event.respond("🔐 هذا الحساب محمي بكلمة سر (2FA). من فضلك أرسل كلمة السر:")
            except Exception as e:
                await event.respond(f"❌ خطأ: {e}"); del login_states[user_id]

        # إضافة حساب - كلمة المرور (2FA)
        elif state['step'] == 'await_password':
            try:
                client = state['client']
                await client.sign_in(password=text)
                await event.respond(f"✅ تم ربط الحساب `{state['phone']}` بنجاح! جاري استيراد المجموعات...")
                
                new_count = await import_groups(client)
                await event.respond(f"📦 تم استيراد `{new_count}` مجموعة (هذه القائمة للعرض فقط، والمراقبة تشمل جميع المجموعات).")
                
                active_clients[state['phone']] = client
                asyncio.create_task(start_monitoring(client, state['phone']))
                del login_states[user_id]
            except Exception as e:
                await event.respond(f"❌ خطأ: {e}"); del login_states[user_id]

        # إضافة كلمة مفتاحية
        elif state['step'] == 'add_kw':
            config['KEYWORDS'] = list(set(config.get('KEYWORDS', []) + [text]))
            update_json_config(config)
            await event.respond(f"✅ تم إضافة الكلمة: `{text}`"); del login_states[user_id]

        # حذف كلمة مفتاحية
        elif state['step'] == 'rem_kw':
            config['KEYWORDS'] = [k for k in config.get('KEYWORDS', []) if k != text]
            update_json_config(config)
            await event.respond(f"✅ تم حذف الكلمة: `{text}`"); del login_states[user_id]

        # إضافة مستخدم للتجاهل
        elif state['step'] == 'add_ignore':
            try:
                config['IGNORE_USERS'] = list(set(config.get('IGNORE_USERS', []) + [int(text)]))
                update_json_config(config)
                await event.respond(f"✅ تم إضافة المعرف `{text}` لقائمة التجاهل."); del login_states[user_id]
            except: await event.respond("❌ المعرف غير صحيح.")

        # حذف مستخدم من التجاهل
        elif state['step'] == 'rem_ignore':
            try:
                config['IGNORE_USERS'] = [u for u in config.get('IGNORE_USERS', []) if u != int(text)]
                update_json_config(config)
                await event.respond(f"✅ تم حذف المعرف `{text}` من قائمة التجاهل."); del login_states[user_id]
            except: await event.respond("❌ المعرف غير صحيح.")

        # إضافة مجموعة يدوي (للعرض فقط)
        elif state['step'] == 'add_group':
            try:
                group_id = int(text)
                groups = config.get('TARGET_GROUPS', [])
                if group_id not in groups:
                    groups.append(group_id)
                    config['TARGET_GROUPS'] = groups
                    update_json_config(config)
                    await event.respond(f"✅ تم إضافة المجموعة `{group_id}` (للعرض فقط، المراقبة تشمل الكل).")
                else:
                    await event.respond("⚠️ المجموعة موجودة بالفعل.")
            except:
                await event.respond("❌ المعرف غير صحيح.")
            del login_states[user_id]

        # حذف مجموعة يدوي (للعرض فقط)
        elif state['step'] == 'rem_group':
            try:
                group_id = int(text)
                groups = config.get('TARGET_GROUPS', [])
                if group_id in groups:
                    groups.remove(group_id)
                    config['TARGET_GROUPS'] = groups
                    update_json_config(config)
                    await event.respond(f"✅ تم حذف المجموعة `{group_id}` من قائمة العرض.")
                else:
                    await event.respond("⚠️ المجموعة غير موجودة.")
            except:
                await event.respond("❌ المعرف غير صحيح.")
            del login_states[user_id]

        # إضافة كلمة إعلانية محظورة
        elif state['step'] == 'add_banned_ad':
            banned_ads = config.get('BANNED_ADS', [])
            if text not in banned_ads:
                banned_ads.append(text)
                config['BANNED_ADS'] = banned_ads
                update_json_config(config)
                await event.respond(f"✅ تم إضافة الكلمة الإعلانية المحظورة: `{text}`")
            else:
                await event.respond(f"⚠️ الكلمة `{text}` موجودة بالفعل في القائمة.")
            del login_states[user_id]

        # إضافة كلمة مشبوهة
        elif state['step'] == 'add_suspicious':
            suspicious = config.get('SUSPICIOUS_WORDS', [])
            if text not in suspicious:
                suspicious.append(text)
                config['SUSPICIOUS_WORDS'] = suspicious
                update_json_config(config)
                await event.respond(f"✅ تم إضافة الكلمة المشبوهة: `{text}`")
            else:
                await event.respond(f"⚠️ الكلمة `{text}` موجودة بالفعل في القائمة.")
            del login_states[user_id]

        # تغيير الحد الأقصى للأحرف
        elif state['step'] == 'set_max_length':
            try:
                new_max = int(text)
                if 10 <= new_max <= 500:
                    filters = config.get('FILTERS', {})
                    filters['max_length'] = new_max
                    config['FILTERS'] = filters
                    update_json_config(config)
                    await event.respond(f"✅ تم تغيير الحد الأقصى للأحرف إلى `{new_max}`")
                else:
                    await event.respond("❌ الرقم يجب أن يكون بين 10 و 500")
            except ValueError:
                await event.respond("❌ من فضلك أرسل رقماً صحيحاً")
            del login_states[user_id]

async def main():
    global bot
    keep_alive()
    logger.info("جاري تشغيل البوت...")
    bot = TelegramClient('bot_session', API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)
    await setup_bot_handlers()
    
    # استئناف الجلسات الموجودة
    for f in os.listdir('.'):
        if f.startswith('session_') and f.endswith('.session') and f != 'bot_session.session':
            phone = f.replace('session_', '').replace('.session', '')
            try:
                client = TelegramClient(f.replace('.session', ''), API_ID, API_HASH)
                await client.connect()
                if await client.is_user_authorized():
                    active_clients[phone] = client
                    asyncio.create_task(start_monitoring(client, phone))
                    logger.info(f"تم استئناف الحساب {phone} والمراقبة تشمل جميع المجموعات")
                else:
                    logger.warning(f"الجلسة {phone} غير مصرحة.")
            except Exception as e:
                logger.error(f"فشل استئناف الحساب {phone}: {e}")

    logger.info("البوت يعمل الآن بكامل طاقته - يراقب جميع المجموعات تلقائياً")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
