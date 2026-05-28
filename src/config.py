import os
import json
from dotenv import load_dotenv

# Load environment variables from .env file (for local development only)
load_dotenv()

# Load values from environment variables
API_ID = os.getenv('API_ID')
if API_ID:
    API_ID = int(API_ID)

API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
if CHANNEL_ID:
    CHANNEL_ID = int(CHANNEL_ID)

SESSION_NAME = os.getenv('SESSION_NAME', 'telegram_monitor_session')

# Load configuration from config.json
# Use absolute path relative to this file to avoid issues
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

def load_json_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return {"TARGET_GROUPS": [], "KEYWORDS": [], "IGNORE_USERS": []}
    return {"TARGET_GROUPS": [], "KEYWORDS": [], "IGNORE_USERS": []}

def update_json_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

# Load dynamic config from JSON
json_config = load_json_config()

TARGET_GROUPS = json_config.get('TARGET_GROUPS', [])
KEYWORDS = json_config.get('KEYWORDS', [])
IGNORE_USERS = json_config.get('IGNORE_USERS', [])
