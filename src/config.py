import os
import json
from dotenv import load_dotenv

# Load environment variables from .env file (for local development only)
load_dotenv()

# Load values from environment variables
API_ID = os.getenv('API_ID')
if API_ID:
    API_ID = int(API_ID)
else:
    raise ValueError("❌ API_ID غير موجود! تأكد من إضافته في متغيرات البيئة (.env)")

API_HASH = os.getenv('API_HASH')
if not API_HASH:
    raise ValueError("❌ API_HASH غير موجود! تأكد من إضافته في متغيرات البيئة (.env)")

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN غير موجود! تأكد من إضافته في متغيرات البيئة (.env)")

CHANNEL_ID = os.getenv('CHANNEL_ID')
if CHANNEL_ID:
    CHANNEL_ID = int(CHANNEL_ID)
else:
    raise ValueError("❌ CHANNEL_ID غير موجود! تأكد من إضافته في متغيرات البيئة (.env)")

SESSION_NAME = os.getenv('SESSION_NAME', 'telegram_monitor_session')

# ============ إعدادات ملف JSON ============
# استخدام نفس المجلد الذي يوجد فيه config.py لتخزين config_data.json
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config_data.json')

def load_json_config():
    """تحميل جميع الإعدادات من ملف JSON مع القيم الافتراضية"""
    default_config = {
        "KEYWORDS": [],
        "IGNORE_USERS": [],
        "TARGET_GROUPS": [],
        "BANNED_ADS": ["عرض", "خصم", "تخفيض", "سعر", "شراء", "بيع", "كوبون", "تسويق", "إعلان"],
        "SUSPICIOUS_WORDS": ["احتيال", "نصبة", "فيروس", "اختراق", "تزوير", "فدية", "سرقة"],
        "FILTERS": {
            "max_length": 4096,
            "block_links": False,
            "block_phones": True,
            "block_mentions": False,
            "block_ads": True,
            "block_suspicious": True
        }
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # دمج القيم المحملة مع القيم الافتراضية (لأي مفاتيح مفقودة)
            for key, value in default_config.items():
                if key not in config:
                    config[key] = value
            
            # التأكد من وجود FILTERS بالكامل مع كل المفاتيح
            if 'FILTERS' not in config:
                config['FILTERS'] = default_config['FILTERS']
            else:
                for fk, fv in default_config['FILTERS'].items():
                    if fk not in config['FILTERS']:
                        config['FILTERS'][fk] = fv
            
            return config
        except Exception as e:
            print(f"خطأ في تحميل config_data.json: {e}")
            return default_config
    else:
        return default_config

def update_json_config(config):
    """حفظ الإعدادات إلى ملف JSON"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"خطأ في حفظ config_data.json: {e}")

# تحميل الإعدادات الديناميكية من JSON (للاستخدام المباشر إذا أردت)
json_config = load_json_config()
TARGET_GROUPS = json_config.get('TARGET_GROUPS', [])
KEYWORDS = json_config.get('KEYWORDS', [])
IGNORE_USERS = json_config.get('IGNORE_USERS', [])
BANNED_ADS = json_config.get('BANNED_ADS', [])
SUSPICIOUS_WORDS = json_config.get('SUSPICIOUS_WORDS', [])
FILTERS = json_config.get('FILTERS', {})
