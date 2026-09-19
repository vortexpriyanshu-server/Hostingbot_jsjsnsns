# -*- coding: utf-8 -*-
import telebot
import subprocess
import os
import zipfile
import tempfile
import shutil
from telebot import types
import time
from datetime import datetime, timedelta
# Removed unused telegram.* imports as we are using telebot consistently
# from telegram import Update
# from telegram.ext import Updater, CommandHandler, CallbackContext
import psutil
import sqlite3
import json # Kept in case needed elsewhere, but not used in provided logic
import logging # Kept in case needed elsewhere
import signal # Kept in case needed elsewhere
import threading
import re # Added for regex matching in auto-install
import sys # Added for sys.executable
import atexit
import requests # For polling exceptions

# --- Flask Keep Alive ---
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "I'am ᴩʀɪʏᴀɴꜱʜᴜ File Host"

def run_flask():
  # Make sure to run on port provided by environment or default to 8080
  port = int(os.environ.get("PORT", 8080))
  app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True # Allows program to exit even if this thread is running
    t.start()
    print("Flask Keep-Alive server started.")
# --- End Flask Keep Alive ---

# --- Configuration ---
TOKEN = '8715121141:AAETfaCuFemIkRDgkG5M5XjVuvHW1UET9y8' # Replace with your actual token
OWNER_ID = 8978106847 # Replace with your Owner ID
ADMIN_ID = 8978106847 # Replace with your Admin ID (can be same as Owner)
YOUR_USERNAME = '@Vortex_priyanshu' # Replace with your Telegram username (without the @)
UPDATE_CHANNEL = 'https://t.me/+J2r1h7CW7Og2MWI9' # Replace with your update channel link

# Folder setup - using absolute paths
BASE_DIR = os.path.abspath(os.path.dirname(__file__)) # Get script's directory
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
IROTECH_DIR = os.path.join(BASE_DIR, 'inf') # Assuming this name is intentional
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')

# File upload limits
FREE_USER_LIMIT = 10
SUBSCRIBED_USER_LIMIT = 25 # Changed from 10 to 15
ADMIN_LIMIT = 999       # Changed from 50 to 999
OWNER_LIMIT = float('inf') # Changed from 999 to infinity
# FREE_MODE_LIMIT = 3 # Removed as free_mode is removed

# Create necessary directories
os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(IROTECH_DIR, exist_ok=True)

# Initialize bot
bot = telebot.TeleBot(TOKEN)

# --- Data structures ---
bot_scripts = {} # Stores info about running scripts {script_key: info_dict}
user_subscriptions = {} # {user_id: {'expiry': datetime_object}}
user_files = {} # {user_id: [(file_name, file_type), ...]}
active_users = set() # Set of all user IDs that have interacted with the bot
admin_ids = {ADMIN_ID, OWNER_ID} # Set of admin IDs
bot_locked = False
# free_mode = False # Removed free_mode

# --- Logging Setup ---
# Configure basic logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Command Button Layouts (ReplyKeyboardMarkup) ---
COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["📢 ᴜᴩᴅᴀᴛᴇꜱ ᴄʜᴀɴɴᴇʟ"],
    ["📤 Upload File", "📂 Check Files"],
    ["⚡ Bot Speed", "📊 Statistics"], # Statistics button kept for users, logic will restrict if not admin
    ["📞 Contact Owner"]
]
ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["📢 ᴜᴩᴅᴀᴛᴇꜱ ᴄʜᴀɴɴᴇʟ"],
    ["📤 Upload File", "📂 Check Files"],
    ["⚡ Bot Speed", "📊 Statistics"],
    ["💳 Subscriptions", "📢 Broadcast"],
    ["🔒 Lock Bot", "🟢 Running All Code"], # Changed "Free Mode" to "Running All Code"
    ["👑 Admin Panel", "📞 Contact Owner"]
]

# --- Database Setup ---
def init_db():
    """Initialize the database with required tables"""
    logger.info(f"Initializing database at: {DATABASE_PATH}")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False) # Allow access from multiple threads
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions
                     (user_id INTEGER PRIMARY KEY, expiry TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_files
                     (user_id INTEGER, file_name TEXT, file_type TEXT,
                      PRIMARY KEY (user_id, file_name))''')
        c.execute('''CREATE TABLE IF NOT EXISTS active_users
                     (user_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins
                     (user_id INTEGER PRIMARY KEY)''') # Added admins table
        # Ensure owner and initial admin are in admins table
        c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (OWNER_ID,))
        if ADMIN_ID != OWNER_ID:
             c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (ADMIN_ID,))
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}", exc_info=True)

def load_data():
    """Load data from database into memory"""
    logger.info("Loading data from database...")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()

        # Load subscriptions
        c.execute('SELECT user_id, expiry FROM subscriptions')
        for user_id, expiry in c.fetchall():
            try:
                user_subscriptions[user_id] = {'expiry': datetime.fromisoformat(expiry)}
            except ValueError:
                logger.warning(f"⚠️ Invalid expiry date format for user {user_id}: {expiry}. Skipping.")

        # Load user files
        c.execute('SELECT user_id, file_name, file_type FROM user_files')
        for user_id, file_name, file_type in c.fetchall():
            if user_id not in user_files:
                user_files[user_id] = []
            user_files[user_id].append((file_name, file_type))

        # Load active users
        c.execute('SELECT user_id FROM active_users')
        active_users.update(user_id for (user_id,) in c.fetchall())

        # Load admins
        c.execute('SELECT user_id FROM admins')
        admin_ids.update(user_id for (user_id,) in c.fetchall()) # Load admins into the set

        conn.close()
        logger.info(f"Data loaded: {len(active_users)} users, {len(user_subscriptions)} subscriptions, {len(admin_ids)} admins.")
    except Exception as e:
        logger.error(f"❌ Error loading data: {e}", exc_info=True)

# Initialize DB and Load Data at startup
init_db()
load_data()
# --- End Database Setup ---

# --- Helper Functions ---
def get_user_folder(user_id):
    """Get or create user's folder for storing files"""
    user_folder = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    return user_folder

def get_user_file_limit(user_id):
    """Get the file upload limit for a user"""
    # if free_mode: return FREE_MODE_LIMIT # Removed free_mode check
    if user_id == OWNER_ID: return OWNER_LIMIT
    if user_id in admin_ids: return ADMIN_LIMIT
    if user_id in user_subscriptions and user_subscriptions[user_id]['expiry'] > datetime.now():
        return SUBSCRIBED_USER_LIMIT
    return FREE_USER_LIMIT

def get_user_file_count(user_id):
    """Get the number of files uploaded by a user"""
    return len(user_files.get(user_id, []))

def is_bot_running(script_owner_id, file_name): # Parameter renamed for clarity
    """Check if a bot script is currently running for a specific user"""
    script_key = f"{script_owner_id}_{file_name}" # Key uses script_owner_id
    script_info = bot_scripts.get(script_key)
    if script_info and script_info.get('process'):
        try:
            proc = psutil.Process(script_info['process'].pid)
            is_running = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            if not is_running:
                logger.warning(f"Process {script_info['process'].pid} for {script_key} found in memory but not running/zombie. Cleaning up.")
                if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                    try:
                        script_info['log_file'].close()
                    except Exception as log_e:
                        logger.error(f"Error closing log file during zombie cleanup {script_key}: {log_e}")
                if script_key in bot_scripts:
                    del bot_scripts[script_key]
            return is_running
        except psutil.NoSuchProcess:
            logger.warning(f"Process for {script_key} not found (NoSuchProcess). Cleaning up.")
            if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                try:
                     script_info['log_file'].close()
                except Exception as log_e:
                     logger.error(f"Error closing log file during cleanup of non-existent process {script_key}: {log_e}")
            if script_key in bot_scripts:
                 del bot_scripts[script_key]
            return False
        except Exception as e:
            logger.error(f"Error checking process status for {script_key}: {e}", exc_info=True)
            return False
    return False


def kill_process_tree(process_info):
    """Kill a process and all its children, ensuring log file is closed."""
    pid = None
    log_file_closed = False
    script_key = process_info.get('script_key', 'N/A') 

    try:
        if 'log_file' in process_info and hasattr(process_info['log_file'], 'close') and not process_info['log_file'].closed:
            try:
                process_info['log_file'].close()
                log_file_closed = True
                logger.info(f"Closed log file for {script_key} (PID: {process_info.get('process', {}).get('pid', 'N/A')})")
            except Exception as log_e:
                logger.error(f"Error closing log file during kill for {script_key}: {log_e}")

        process = process_info.get('process')
        if process and hasattr(process, 'pid'):
           pid = process.pid
           if pid: 
                try:
                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)
                    logger.info(f"Attempting to kill process tree for {script_key} (PID: {pid}, Children: {[c.pid for c in children]})")

                    for child in children:
                        try:
                            child.terminate()
                            logger.info(f"Terminated child process {child.pid} for {script_key}")
                        except psutil.NoSuchProcess:
                            logger.warning(f"Child process {child.pid} for {script_key} already gone.")
                        except Exception as e:
                            logger.error(f"Error terminating child {child.pid} for {script_key}: {e}. Trying kill...")
                            try: child.kill(); logger.info(f"Killed child process {child.pid} for {script_key}")
                            except Exception as e2: logger.error(f"Failed to kill child {child.pid} for {script_key}: {e2}")

                    gone, alive = psutil.wait_procs(children, timeout=1)
                    for p in alive:
                        logger.warning(f"Child process {p.pid} for {script_key} still alive. Killing.")
                        try: p.kill()
                        except Exception as e: logger.error(f"Failed to kill child {p.pid} for {script_key} after wait: {e}")

                    try:
                        parent.terminate()
                        logger.info(f"Terminated parent process {pid} for {script_key}")
                        try: parent.wait(timeout=1)
                        except psutil.TimeoutExpired:
                            logger.warning(f"Parent process {pid} for {script_key} did not terminate. Killing.")
                            parent.kill()
                            logger.info(f"Killed parent process {pid} for {script_key}")
                    except psutil.NoSuchProcess:
                        logger.warning(f"Parent process {pid} for {script_key} already gone.")
                    except Exception as e:
                        logger.error(f"Error terminating parent {pid} for {script_key}: {e}. Trying kill...")
                        try: parent.kill(); logger.info(f"Killed parent process {pid} for {script_key}")
                        except Exception as e2: logger.error(f"Failed to kill parent {pid} for {script_key}: {e2}")

                except psutil.NoSuchProcess:
                    logger.warning(f"Process {pid or 'N/A'} for {script_key} not found during kill. Already terminated?")
           else: logger.error(f"Process PID is None for {script_key}.")
        elif log_file_closed: logger.warning(f"Process object missing for {script_key}, but log file closed.")
        else: logger.error(f"Process object missing for {script_key}, and no log file. Cannot kill.")
    except Exception as e:
        logger.error(f"❌ Unexpected error killing process tree for PID {pid or 'N/A'} ({script_key}): {e}", exc_info=True)

# --- Automatic Package Installation & Script Running ---

def attempt_install_pip(module_name, message):
    package_name = TELEGRAM_MODULES.get(module_name.lower(), module_name) 
    if package_name is None: 
        logger.info(f"Module '{module_name}' is core. Skipping pip install.")
        return False 
    try:
        bot.reply_to(message, f"🐍 ᴍᴏᴅᴜʟᴇ `{module_name}` ɴᴏᴛ ꜰᴏᴜɴᴅ. ɪɴꜱᴛᴀʟʟɪɴɢ `{package_name}`...", parse_mode='Markdown')
        command = [sys.executable, '-m', 'pip', 'install', package_name]
        logger.info(f"Running install: {' '.join(command)}")
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            logger.info(f"Installed {package_name}. Output:\n{result.stdout}")
            bot.reply_to(message, f"✅ ᴩᴀᴄᴋᴀɢᴇ `{package_name}` (ꜰᴏʀ `{module_name}`) ɪɴꜱᴛᴀʟʟᴇᴅ.", parse_mode='Markdown')
            return True
        else:
            error_msg = f"❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ɪɴꜱᴛᴀʟʟ `{package_name}` ꜰᴏʀ `{module_name}`.\nʟᴏɢ:\n```\n{result.stderr or result.stdout}\n```"
            logger.error(error_msg)
            if len(error_msg) > 4000: error_msg = error_msg[:4000] + "\n... (ʟᴏɢ ᴛʀᴜɴᴄᴀᴛᴇᴅ)"
            bot.reply_to(message, error_msg, parse_mode='Markdown')
            return False
    except Exception as e:
        error_msg = f"❌ ᴇʀʀᴏʀ ɪɴꜱᴛᴀʟʟɪɴɢ `{package_name}`: {str(e)}"
        logger.error(error_msg, exc_info=True)
        bot.reply_to(message, error_msg)
        return False

def attempt_install_npm(module_name, user_folder, message):
    try:
        bot.reply_to(message, f"🟠 ɴᴏᴅᴇ ᴩᴀᴄᴋᴀɢᴇ `{module_name}` ɴᴏᴛ ꜰᴏᴜɴᴅ. ɪɴꜱᴛᴀʟʟɪɴɢ ʟᴏᴄᴀʟʟʏ...", parse_mode='Markdown')
        command = ['npm', 'install', module_name]
        logger.info(f"Running npm install: {' '.join(command)} in {user_folder}")
        result = subprocess.run(command, capture_output=True, text=True, check=False, cwd=user_folder, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            logger.info(f"Installed {module_name}. Output:\n{result.stdout}")
            bot.reply_to(message, f"✅ ɴᴏᴅᴇ ᴩᴀᴄᴋᴀɢᴇ `{module_name}` ɪɴꜱᴛᴀʟʟᴇᴅ ʟᴏᴄᴀʟʟʏ.", parse_mode='Markdown')
            return True
        else:
            error_msg = f"❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ɪɴꜱᴛᴀʟʟ ɴᴏᴅᴇ ᴩᴀᴄᴋᴀɢᴇ `{module_name}`.\nʟᴏɢ:\n```\n{result.stderr or result.stdout}\n```"
            logger.error(error_msg)
            if len(error_msg) > 4000: error_msg = error_msg[:4000] + "\n... (ʟᴏɢ ᴛʀᴜɴᴄᴀᴛᴇᴅ)"
            bot.reply_to(message, error_msg, parse_mode='Markdown')
            return False
    except FileNotFoundError:
         error_msg = "❌ ᴇʀʀᴏʀ: 'ɴᴩᴍ' ɴᴏᴛ ꜰᴏᴜɴᴅ. ᴇɴꜱᴜʀᴇ ɴᴏᴅᴇ.js/npm ᴀʀᴇ ɪɴꜱᴛᴀʟʟᴇᴅ ᴀɴᴅ ɪɴ ᴩᴀᴛʜ."
         logger.error(error_msg)
         bot.reply_to(message, error_msg)
         return False
    except Exception as e:
        error_msg = f"❌ ᴇʀʀᴏʀ ɪɴꜱᴛᴀʟʟɪɴɢ ɴᴏᴅᴇ ᴩᴀᴄᴋᴀɢᴇ `{module_name}`: {str(e)}"
        logger.error(error_msg, exc_info=True)
        bot.reply_to(message, error_msg)
        return False

def run_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    """Run Python script. script_owner_id is used for the script_key. message_obj_for_reply is for sending feedback."""
    max_attempts = 2 
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ʀᴜɴ '{file_name}' ᴀꜰᴛᴇʀ {max_attempts} ᴀᴛᴛᴇᴍᴩᴛꜱ. ᴄʜᴇᴄᴋ ʟᴏɢꜱ.")
        return

    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"Attempt {attempt} to run Python script: {script_path} (Key: {script_key}) for user {script_owner_id}")

    try:
        if not os.path.exists(script_path):
             bot.reply_to(message_obj_for_reply, f"❌ ᴇʀʀᴏʀ: ꜱᴄʀɪᴩᴛ '{file_name}' ɴᴏᴛ ꜰᴏᴜɴᴅ ᴀᴛ '{script_path}'!")
             logger.error(f"Script not found: {script_path} for user {script_owner_id}")
             if script_owner_id in user_files:
                 user_files[script_owner_id] = [f for f in user_files.get(script_owner_id, []) if f[0] != file_name]
             remove_user_file_db(script_owner_id, file_name)
             return

        if attempt == 1:
            check_command = [sys.executable, script_path]
            logger.info(f"Running Python pre-check: {' '.join(check_command)}")
            check_proc = None
            try:
                check_proc = subprocess.Popen(check_command, cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=5)
                return_code = check_proc.returncode
                logger.info(f"Python Pre-check early. RC: {return_code}. Stderr: {stderr[:200]}...")
                if return_code != 0 and stderr:
                    match_py = re.search(r"ModuleNotFoundError: No module named '(.+?)'", stderr)
                    if match_py:
                        module_name = match_py.group(1).strip().strip("'\"")
                        logger.info(f"Detected missing Python module: {module_name}")
                        if attempt_install_pip(module_name, message_obj_for_reply):
                            logger.info(f"Install OK for {module_name}. Retrying run_script...")
                            bot.reply_to(message_obj_for_reply, f"🔄 ɪɴꜱᴛᴀʟʟ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟ. ʀᴇᴛʀʏɪɴɢ '{file_name}'...")
                            time.sleep(2)
                            threading.Thread(target=run_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1)).start()
                            return
                        else:
                            bot.reply_to(message_obj_for_reply, f"❌ ɪɴꜱᴛᴀʟʟ ꜰᴀɪʟᴇᴅ. ᴄᴀɴɴᴏᴛ ʀᴜɴ '{file_name}'.")
                            return
                    else:
                         error_summary = stderr[:500]
                         bot.reply_to(message_obj_for_reply, f"❌ ᴇʀʀᴏʀ ɪɴ ꜱᴄʀɪᴩᴛ ᴩʀᴇ-ᴄʜᴇᴄᴋ ꜰᴏʀ '{file_name}':\n```\n{error_summary}\n```\nꜰɪx ᴛʜᴇ ꜱᴄʀɪᴩᴛ.", parse_mode='Markdown')
                         return
            except subprocess.TimeoutExpired:
                logger.info("Python Pre-check timed out (>5s), imports likely OK. Killing check process.")
                if check_proc and check_proc.poll() is None: check_proc.kill(); check_proc.communicate()
                logger.info("Python Check process killed. Proceeding to long run.")
            except FileNotFoundError:
                 logger.error(f"Python interpreter not found: {sys.executable}")
                 bot.reply_to(message_obj_for_reply, f"❌ ᴇʀʀᴏʀ: ᴩʏᴛʜᴏɴ ɪɴᴛᴇʀᴩʀᴇᴛᴇʀ '{sys.executable}' ɴᴏᴛ ꜰᴏᴜɴᴅ.")
                 return
            except Exception as e:
                 logger.error(f"Error in Python pre-check for {script_key}: {e}", exc_info=True)
                 bot.reply_to(message_obj_for_reply, f"❌ ᴜɴᴇxᴩᴇᴄᴛᴇᴅ ᴇʀʀᴏʀ ɪɴ ꜱᴄʀɪᴩᴛ ᴩʀᴇ-ᴄʜᴇᴄᴋ ꜰᴏʀ '{file_name}': {e}")
                 return
            finally:
                 if check_proc and check_proc.poll() is None:
                     logger.warning(f"Python Check process {check_proc.pid} still running. Killing.")
                     check_proc.kill(); check_proc.communicate()

        logger.info(f"Starting long-running Python process for {script_key}")
        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None; process = None
        try: log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
             logger.error(f"Failed to open log file '{log_file_path}' for {script_key}: {e}", exc_info=True)
             bot.reply_to(message_obj_for_reply, f"❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ᴏᴩᴇɴ ʟᴏɢ ꜰɪʟᴇ '{log_file_path}': {e}")
             return
        try:
            startupinfo = None; creationflags = 0
            if os.name == 'nt':
                 startupinfo = subprocess.STARTUPINFO(); startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                 startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                [sys.executable, script_path], cwd=user_folder, stdout=log_file, stderr=log_file,
                stdin=subprocess.PIPE, startupinfo=startupinfo, creationflags=creationflags,
                encoding='utf-8', errors='ignore'
            )
            logger.info(f"Started Python process {process.pid} for {script_key}")
            bot_scripts[script_key] = {
                'process': process, 'log_file': log_file, 'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id, # Chat ID for potential future direct replies from script, defaults to admin/triggering user
                'script_owner_id': script_owner_id, # Actual owner of the script
                'start_time': datetime.now(), 'user_folder': user_folder, 'type': 'py', 'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"✅ ᴩʏᴛʜᴏɴ ꜱᴄʀɪᴩᴛ '{file_name}' ꜱᴛᴀʀᴛᴇᴅ! (ᴩɪᴅ: {process.pid}) (ꜰᴏʀ ᴜꜱᴇʀ: {script_owner_id})")
        except FileNotFoundError:
             logger.error(f"Python interpreter {sys.executable} not found for long run {script_key}")
             bot.reply_to(message_obj_for_reply, f"❌ ᴇʀʀᴏʀ: ᴩʏᴛʜᴏɴ ɪɴᴛᴇʀᴩʀᴇᴛᴇʀ '{sys.executable}' ɴᴏᴛ ꜰᴏᴜɴᴅ.")
             if log_file and not log_file.closed: log_file.close()
             if script_key in bot_scripts: del bot_scripts[script_key]
        except Exception as e:
            if log_file and not log_file.closed: log_file.close()
            error_msg = f"❌ ᴇʀʀᴏʀ ꜱᴛᴀʀᴛɪɴɢ ᴩʏᴛʜᴏɴ ꜱᴄʀɪᴩᴛ '{file_name}': {str(e)}"
            logger.error(error_msg, exc_info=True)
            bot.reply_to(message_obj_for_reply, error_msg)
            if process and process.poll() is None:
                 logger.warning(f"Killing potentially started Python process {process.pid} for {script_key}")
                 kill_process_tree({'process': process, 'log_file': log_file, 'script_key': script_key})
            if script_key in bot_scripts: del bot_scripts[script_key]
    except Exception as e:
        error_msg = f"❌ ᴜɴᴇxᴩᴇᴄᴛᴇᴅ ᴇʀʀᴏʀ ʀᴜɴɴɪɴɢ ᴩʏᴛʜᴏɴ ꜱᴄʀɪᴩᴛ '{file_name}': {str(e)}"
        logger.error(error_msg, exc_info=True)
        bot.reply_to(message_obj_for_reply, error_msg)
        if script_key in bot_scripts:
             logger.warning(f"Cleaning up {script_key} due to error in run_script.")
             kill_process_tree(bot_scripts[script_key])
             del bot_scripts[script_key]

def run_js_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    """Run JS script. script_owner_id is used for the script_key. message_obj_for_reply is for sending feedback."""
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ʀᴜɴ '{file_name}' ᴀꜰᴛᴇʀ {max_attempts} ᴀᴛᴛᴇᴍᴩᴛꜱ. ᴄʜᴇᴄᴋ ʟᴏɢꜱ.")
        return

    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"Attempt {attempt} to run JS script: {script_path} (Key: {script_key}) for user {script_owner_id}")

    try:
        if not os.path.exists(script_path):
             bot.reply_to(message_obj_for_reply, f"❌ ᴇʀʀᴏʀ: ꜱᴄʀɪᴩᴛ '{file_name}' ɴᴏᴛ ꜰᴏᴜɴᴅ ᴀᴛ '{script_path}'!")
             logger.error(f"JS Script not found: {script_path} for user {script_owner_id}")
             if script_owner_id in user_files:
                 user_files[script_owner_id] = [f for f in user_files.get(script_owner_id, []) if f[0] != file_name]
             remove_user_file_db(script_owner_id, file_name)
             return

        if attempt == 1:
            check_command = ['node', script_path]
            logger.info(f"Running JS pre-check: {' '.join(check_command)}")
            check_proc = None
            try:
                check_proc = subprocess.Popen(check_command, cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=5)
                return_code = check_proc.returncode
                logger.info(f"JS Pre-check early. RC: {return_code}. Stderr: {stderr[:200]}...")
                if return_code != 0 and stderr:
                    match_js = re.search(r"Cannot find module '(.+?)'", stderr)
                    if match_js:
                        module_name = match_js.group(1).strip().strip("'\"")
                        if not module_name.startswith('.') and not module_name.startswith('/'):
                             logger.info(f"Detected missing Node module: {module_name}")
                             if attempt_install_npm(module_name, user_folder, message_obj_for_reply):
                                 logger.info(f"NPM Install OK for {module_name}. Retrying run_js_script...")
                                 bot.reply_to(message_obj_for_reply, f"🔄 ɴᴩᴍ ɪɴꜱᴛᴀʟʟ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟ. ʀᴇᴛʀʏɪɴɢ '{file_name}'...")
                                 time.sleep(2)
                                 threading.Thread(target=run_js_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1)).start()
                                 return
                             else:
                                 bot.reply_to(message_obj_for_reply, f"❌ ɴᴩᴍ ɪɴꜱᴛᴀʟʟ ꜰᴀɪʟᴇᴅ. ᴄᴀɴɴᴏᴛ ʀᴜɴ '{file_name}'.")
                                 return
                        else: logger.info(f"Skipping npm install for relative/core: {module_name}")
                    error_summary = stderr[:500]
                    bot.reply_to(message_obj_for_reply, f"❌ ᴇʀʀᴏʀ ɪɴ ᴊꜱ ꜱᴄʀɪᴩᴛ ᴩʀᴇ-ᴄʜᴇᴄᴋ ꜰᴏʀ '{file_name}':\n```\n{error_summary}\n```\nꜰɪx ꜱᴄʀɪᴩᴛ ᴏʀ ɪɴꜱᴛᴀʟʟ ᴍᴀɴᴜᴀʟʟʏ.", parse_mode='Markdown')
                    return
            except subprocess.TimeoutExpired:
                logger.info("JS Pre-check timed out (>5s), imports likely OK. Killing check process.")
                if check_proc and check_proc.poll() is None: check_proc.kill(); check_proc.communicate()
                logger.info("JS Check process killed. Proceeding to long run.")
            except FileNotFoundError:
                 error_msg = "❌ ᴇʀʀᴏʀ: 'ɴᴏᴅᴇ' ɴᴏᴛ ꜰᴏᴜɴᴅ. ᴇɴꜱᴜʀᴇ ɴᴏᴅᴇ.js ɪꜱ ɪɴꜱᴛᴀʟʟᴇᴅ ꜰᴏʀ ᴊꜱ ꜰɪʟᴇꜱ."
                 logger.error(error_msg)
                 bot.reply_to(message_obj_for_reply, error_msg)
                 return
            except Exception as e:
                 logger.error(f"Error in JS pre-check for {script_key}: {e}", exc_info=True)
                 bot.reply_to(message_obj_for_reply, f"❌ ᴜɴᴇxᴩᴇᴄᴛᴇᴅ ᴇʀʀᴏʀ ɪɴ ᴊꜱ ᴩʀᴇ-ᴄʜᴇᴄᴋ ꜰᴏʀ '{file_name}': {e}")
                 return
            finally:
                 if check_proc and check_proc.poll() is None:
                     logger.warning(f"JS Check process {check_proc.pid} still running. Killing.")
                     check_proc.kill(); check_proc.communicate()

        logger.info(f"Starting long-running JS process for {script_key}")
        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None; process = None
        try: log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            logger.error(f"Failed to open log file '{log_file_path}' for JS script {script_key}: {e}", exc_info=True)
            bot.reply_to(message_obj_for_reply, f"❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ᴏᴩᴇɴ ʟᴏɢ ꜰɪʟᴇ '{log_file_path}': {e}")
            return
        try:
            startupinfo = None; creationflags = 0
            if os.name == 'nt':
                 startupinfo = subprocess.STARTUPINFO(); startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                 startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                ['node', script_path], cwd=user_folder, stdout=log_file, stderr=log_file,
                stdin=subprocess.PIPE, startupinfo=startupinfo, creationflags=creationflags,
                encoding='utf-8', errors='ignore'
            )
            logger.info(f"Started JS process {process.pid} for {script_key}")
            bot_scripts[script_key] = {
                'process': process, 'log_file': log_file, 'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id, # Chat ID for potential future direct replies
                'script_owner_id': script_owner_id, # Actual owner of the script
                'start_time': datetime.now(), 'user_folder': user_folder, 'type': 'js', 'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"✅ ᴊꜱ ꜱᴄʀɪᴩᴛ '{file_name}' ꜱᴛᴀʀᴛᴇᴅ! (ᴩɪᴅ: {process.pid}) (ꜰᴏʀ ᴜꜱᴇʀ: {script_owner_id})")
        except FileNotFoundError:
             error_msg = "❌ ᴇʀʀᴏʀ: 'ɴᴏᴅᴇ' ɴᴏᴛ ꜰᴏᴜɴᴅ ꜰᴏʀ ʟᴏɴɢ ʀᴜɴ. ᴇɴꜱᴜʀᴇ ɴᴏᴅᴇ.js ɪꜱ ɪɴꜱᴛᴀʟʟᴇᴅ."
             logger.error(error_msg)
             if log_file and not log_file.closed: log_file.close()
             bot.reply_to(message_obj_for_reply, error_msg)
             if script_key in bot_scripts: del bot_scripts[script_key]
        except Exception as e:
            if log_file and not log_file.closed: log_file.close()
            error_msg = f"❌ ᴇʀʀᴏʀ ꜱᴛᴀʀᴛɪɴɢ ᴊꜱ ꜱᴄʀɪᴩᴛ '{file_name}': {str(e)}"
            logger.error(error_msg, exc_info=True)
            bot.reply_to(message_obj_for_reply, error_msg)
            if process and process.poll() is None:
                 logger.warning(f"Killing potentially started JS process {process.pid} for {script_key}")
                 kill_process_tree({'process': process, 'log_file': log_file, 'script_key': script_key})
            if script_key in bot_scripts: del bot_scripts[script_key]
    except Exception as e:
        error_msg = f"❌ ᴜɴᴇxᴩᴇᴄᴛᴇᴅ ᴇʀʀᴏʀ ʀᴜɴɴɪɴɢ ᴊꜱ ꜱᴄʀɪᴩᴛ '{file_name}': {str(e)}"
        logger.error(error_msg, exc_info=True)
        bot.reply_to(message_obj_for_reply, error_msg)
        if script_key in bot_scripts:
             logger.warning(f"Cleaning up {script_key} due to error in run_js_script.")
             kill_process_tree(bot_scripts[script_key])
             del bot_scripts[script_key]

# --- Map Telegram import names to actual PyPI package names ---
TELEGRAM_MODULES = {
    # Main Bot Frameworks
    'telebot': 'pyTelegramBotAPI',
    'telegram': 'python-telegram-bot',
    'python_telegram_bot': 'python-telegram-bot',
    'aiogram': 'aiogram',
    'pyrogram': 'pyrogram',
    'telethon': 'telethon',
    'telethon.sync': 'telethon', # Handle specific imports
    'from telethon.sync import telegramclient': 'telethon', # Example

    # Additional Libraries (add more specific mappings if import name differs)
    'telepot': 'telepot',
    'pytg': 'pytg',
    'tgcrypto': 'tgcrypto',
    'telegram_upload': 'telegram-upload',
    'telegram_send': 'telegram-send',
    'telegram_text': 'telegram-text',

    # MTProto & Low-Level
    'mtproto': 'telegram-mtproto', # Example, check actual package name
    'tl': 'telethon',  # Part of Telethon, install 'telethon'

    # Utilities & Helpers (examples, verify package names)
    'telegram_utils': 'telegram-utils',
    'telegram_logger': 'telegram-logger',
    'telegram_handlers': 'python-telegram-handlers',

    # Database Integrations (examples)
    'telegram_redis': 'telegram-redis',
    'telegram_sqlalchemy': 'telegram-sqlalchemy',

    # Payment & E-commerce (examples)
    'telegram_payment': 'telegram-payment',
    'telegram_shop': 'telegram-shop-sdk',

    # Testing & Debugging (examples)
    'pytest_telegram': 'pytest-telegram',
    'telegram_debug': 'telegram-debug',

    # Scraping & Analytics (examples)
    'telegram_scraper': 'telegram-scraper',
    'telegram_analytics': 'telegram-analytics',

    # NLP & AI (examples)
    'telegram_nlp': 'telegram-nlp-toolkit',
    'telegram_ai': 'telegram-ai', # Assuming this exists

    # Web & API Integration (examples)
    'telegram_api': 'telegram-api-client',
    'telegram_web': 'telegram-web-integration',

    # Gaming & Interactive (examples)
    'telegram_games': 'telegram-games',
    'telegram_quiz': 'telegram-quiz-bot',

    # File & Media Handling (examples)
    'telegram_ffmpeg': 'telegram-ffmpeg',
    'telegram_media': 'telegram-media-utils',

    # Security & Encryption (examples)
    'telegram_2fa': 'telegram-twofa',
    'telegram_crypto': 'telegram-crypto-bot',

    # Localization & i18n (examples)
    'telegram_i18n': 'telegram-i18n',
    'telegram_translate': 'telegram-translate',

    # Common non-telegram examples
    'bs4': 'beautifulsoup4',
    'requests': 'requests',
    'pillow': 'Pillow', # Note the capitalization difference
    'cv2': 'opencv-python', # Common import name for OpenCV
    'yaml': 'PyYAML',
    'dotenv': 'python-dotenv',
    'dateutil': 'python-dateutil',
    'pandas': 'pandas',
    'numpy': 'numpy',
    'flask': 'Flask',
    'django': 'Django',
    'sqlalchemy': 'SQLAlchemy',
    'asyncio': None, # Core module, should not be installed
    'json': None,    # Core module
    'datetime': None,# Core module
    'os': None,      # Core module
    'sys': None,     # Core module
    're': None,      # Core module
    'time': None,    # Core module
    'math': None,    # Core module
    'random': None,  # Core module
    'logging': None, # Core module
    'threading': None,# Core module
    'subprocess':None,# Core module
    'zipfile':None,  # Core module
    'tempfile':None, # Core module
    'shutil':None,   # Core module
    'sqlite3':None,  # Core module
    'psutil': 'psutil',
    'atexit': None   # Core module

}
# --- End Automatic Package Installation & Script Running ---


# --- Database Operations ---
DB_LOCK = threading.Lock() 

def save_user_file(user_id, file_name, file_type='py'):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR REPLACE INTO user_files (user_id, file_name, file_type) VALUES (?, ?, ?)',
                      (user_id, file_name, file_type))
            conn.commit()
            if user_id not in user_files: user_files[user_id] = []
            user_files[user_id] = [(fn, ft) for fn, ft in user_files[user_id] if fn != file_name]
            user_files[user_id].append((file_name, file_type))
            logger.info(f"Saved file '{file_name}' ({file_type}) for user {user_id}")
        except sqlite3.Error as e: logger.error(f"❌ SQLite error saving file for user {user_id}, {file_name}: {e}")
        except Exception as e: logger.error(f"❌ Unexpected error saving file for {user_id}, {file_name}: {e}", exc_info=True)
        finally: conn.close()

def remove_user_file_db(user_id, file_name):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ?', (user_id, file_name))
            conn.commit()
            if user_id in user_files:
                user_files[user_id] = [f for f in user_files[user_id] if f[0] != file_name]
                if not user_files[user_id]: del user_files[user_id]
            logger.info(f"Removed file '{file_name}' for user {user_id} from DB")
        except sqlite3.Error as e: logger.error(f"❌ SQLite error removing file for {user_id}, {file_name}: {e}")
        except Exception as e: logger.error(f"❌ Unexpected error removing file for {user_id}, {file_name}: {e}", exc_info=True)
        finally: conn.close()

def add_active_user(user_id):
    active_users.add(user_id) 
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO active_users (user_id) VALUES (?)', (user_id,))
            conn.commit()
            logger.info(f"Added/Confirmed active user {user_id} in DB")
        except sqlite3.Error as e: logger.error(f"❌ SQLite error adding active user {user_id}: {e}")
        except Exception as e: logger.error(f"❌ Unexpected error adding active user {user_id}: {e}", exc_info=True)
        finally: conn.close()

def save_subscription(user_id, expiry):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            expiry_str = expiry.isoformat()
            c.execute('INSERT OR REPLACE INTO subscriptions (user_id, expiry) VALUES (?, ?)', (user_id, expiry_str))
            conn.commit()
            user_subscriptions[user_id] = {'expiry': expiry}
            logger.info(f"Saved subscription for {user_id}, expiry {expiry_str}")
        except sqlite3.Error as e: logger.error(f"❌ SQLite error saving subscription for {user_id}: {e}")
        except Exception as e: logger.error(f"❌ Unexpected error saving subscription for {user_id}: {e}", exc_info=True)
        finally: conn.close()

def remove_subscription_db(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM subscriptions WHERE user_id = ?', (user_id,))
            conn.commit()
            if user_id in user_subscriptions: del user_subscriptions[user_id]
            logger.info(f"Removed subscription for {user_id} from DB")
        except sqlite3.Error as e: logger.error(f"❌ SQLite error removing subscription for {user_id}: {e}")
        except Exception as e: logger.error(f"❌ Unexpected error removing subscription for {user_id}: {e}", exc_info=True)
        finally: conn.close()

def add_admin_db(admin_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (admin_id,))
            conn.commit()
            admin_ids.add(admin_id) 
            logger.info(f"Added admin {admin_id} to DB")
        except sqlite3.Error as e: logger.error(f"❌ SQLite error adding admin {admin_id}: {e}")
        except Exception as e: logger.error(f"❌ Unexpected error adding admin {admin_id}: {e}", exc_info=True)
        finally: conn.close()

def remove_admin_db(admin_id):
    if admin_id == OWNER_ID:
        logger.warning("Attempted to remove OWNER_ID from admins.")
        return False 
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        removed = False
        try:
            c.execute('SELECT 1 FROM admins WHERE user_id = ?', (admin_id,))
            if c.fetchone():
                c.execute('DELETE FROM admins WHERE user_id = ?', (admin_id,))
                conn.commit()
                removed = c.rowcount > 0 
                if removed: admin_ids.discard(admin_id); logger.info(f"Removed admin {admin_id} from DB")
                else: logger.warning(f"Admin {admin_id} found but delete affected 0 rows.")
            else:
                logger.warning(f"Admin {admin_id} not found in DB.")
                admin_ids.discard(admin_id)
            return removed
        except sqlite3.Error as e: logger.error(f"❌ SQLite error removing admin {admin_id}: {e}"); return False
        except Exception as e: logger.error(f"❌ Unexpected error removing admin {admin_id}: {e}", exc_info=True); return False
        finally: conn.close()
# --- End Database Operations ---

# --- Menu creation (Inline and ReplyKeyboards) ---
def create_main_menu_inline(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton('📢 ᴜᴩᴅᴀᴛᴇꜱ ᴄʜᴀɴɴᴇʟ', url=UPDATE_CHANNEL, style='primary'),
        types.InlineKeyboardButton('📤 ᴜᴩʟᴏᴀᴅ ꜰɪʟᴇ', callback_data='upload', style='primary'),
        types.InlineKeyboardButton('📂 ᴄʜᴇᴄᴋ ꜰɪʟᴇꜱ', callback_data='check_files', style='primary'),
        types.InlineKeyboardButton('⚡ ʙᴏᴛ ꜱᴩᴇᴇᴅ', callback_data='speed', style='primary'),
        types.InlineKeyboardButton('📞 ᴄᴏɴᴛᴀᴄᴛ ᴏᴡɴᴇʀ', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}', style='primary')
    ]

    if user_id in admin_ids:
        admin_buttons = [
            types.InlineKeyboardButton('💳 ꜱᴜʙꜱᴄʀɪᴩᴛɪᴏɴꜱ', callback_data='subscription', style='success'), #0
            types.InlineKeyboardButton('📊 ꜱᴛᴀᴛɪꜱᴛɪᴄꜱ', callback_data='stats', style='primary'), #1
            types.InlineKeyboardButton('🔒 ʟᴏᴄᴋ ʙᴏᴛ' if not bot_locked else '🔓 ᴜɴʟᴏᴄᴋ ʙᴏᴛ', #2
                                     callback_data='lock_bot' if not bot_locked else 'unlock_bot', style='danger' if not bot_locked else 'success'),
            types.InlineKeyboardButton('📢 ʙʀᴏᴀᴅᴄᴀꜱᴛ', callback_data='broadcast', style='primary'), #3
            types.InlineKeyboardButton('👑 ᴀᴅᴍɪɴ ᴩᴀɴᴇʟ', callback_data='admin_panel', style='primary'), #4
            types.InlineKeyboardButton('🟢 ʀᴜɴ ᴀʟʟ ᴜꜱᴇʀ ꜱᴄʀɪᴩᴛꜱ', callback_data='run_all_scripts', style='success') #5
        ]
        markup.add(buttons[0]) # Updates
        markup.add(buttons[1], buttons[2]) # Upload, Check Files
        markup.add(buttons[3], admin_buttons[0]) # Speed, Subscriptions
        markup.add(admin_buttons[1], admin_buttons[3]) # Stats, Broadcast
        markup.add(admin_buttons[2], admin_buttons[5]) # Lock Bot, Run All Scripts
        markup.add(admin_buttons[4]) # Admin Panel
        markup.add(buttons[4]) # Contact
    else:
        markup.add(buttons[0])
        markup.add(buttons[1], buttons[2])
        markup.add(buttons[3])
        markup.add(types.InlineKeyboardButton('📊 ꜱᴛᴀᴛɪꜱᴛɪᴄꜱ', callback_data='stats', style='primary')) # Allow non-admins to see stats too
        markup.add(buttons[4])
    return markup

def create_reply_keyboard_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    layout_to_use = ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC if user_id in admin_ids else COMMAND_BUTTONS_LAYOUT_USER_SPEC
    for row_buttons_text in layout_to_use:
        markup.add(*[types.KeyboardButton(text, style=('danger' if text == '🔒 ʟᴏᴄᴋ ʙᴏᴛ' else 'success' if text == '🟢 ʀᴜɴɴɪɴɢ ᴀʟʟ ᴄᴏᴅᴇ' else 'primary')) for text in row_buttons_text])
    return markup

def create_control_buttons(script_owner_id, file_name, is_running=True): # Parameter renamed
    markup = types.InlineKeyboardMarkup(row_width=2)
    # Callbacks use script_owner_id
    if is_running:
        markup.row(
            types.InlineKeyboardButton("🔴 ꜱᴛᴏᴩ", callback_data=f'stop_{script_owner_id}_{file_name}', style='danger'),
            types.InlineKeyboardButton("🔄 ʀᴇꜱᴛᴀʀᴛ", callback_data=f'restart_{script_owner_id}_{file_name}', style='primary')
        )
        markup.row(
            types.InlineKeyboardButton("🗑️ ᴅᴇʟᴇᴛᴇ", callback_data=f'delete_{script_owner_id}_{file_name}', style='danger'),
            types.InlineKeyboardButton("📜 ʟᴏɢꜱ", callback_data=f'logs_{script_owner_id}_{file_name}', style='primary')
        )
    else:
        markup.row(
            types.InlineKeyboardButton("🟢 ꜱᴛᴀʀᴛ", callback_data=f'start_{script_owner_id}_{file_name}', style='success'),
            types.InlineKeyboardButton("🗑️ ᴅᴇʟᴇᴛᴇ", callback_data=f'delete_{script_owner_id}_{file_name}', style='danger')
        )
        markup.row(
            types.InlineKeyboardButton("📜 ᴠɪᴇᴡ ʟᴏɢꜱ", callback_data=f'logs_{script_owner_id}_{file_name}', style='primary')
        )
    markup.add(types.InlineKeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ꜰɪʟᴇꜱ", callback_data='check_files', style='primary'))
    return markup

def create_admin_panel():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton('➕ ᴀᴅᴅ ᴀᴅᴍɪɴ', callback_data='add_admin', style='success'),
        types.InlineKeyboardButton('➖ ʀᴇᴍᴏᴠᴇ ᴀᴅᴍɪɴ', callback_data='remove_admin', style='danger')
    )
    markup.row(types.InlineKeyboardButton('📋 ʟɪꜱᴛ ᴀᴅᴍɪɴꜱ', callback_data='list_admins', style='primary'))
    markup.row(types.InlineKeyboardButton('🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ', callback_data='back_to_main', style='primary'))
    return markup

def create_subscription_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton('➕ ᴀᴅᴅ ꜱᴜʙꜱᴄʀɪᴩᴛɪᴏɴ', callback_data='add_subscription', style='success'),
        types.InlineKeyboardButton('➖ ʀᴇᴍᴏᴠᴇ ꜱᴜʙꜱᴄʀɪᴩᴛɪᴏɴ', callback_data='remove_subscription', style='danger')
    )
    markup.row(types.InlineKeyboardButton('🔍 ᴄʜᴇᴄᴋ ꜱᴜʙꜱᴄʀɪᴩᴛɪᴏɴ', callback_data='check_subscription', style='primary'))
    markup.row(types.InlineKeyboardButton('🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ', callback_data='back_to_main', style='primary'))
    return markup
# --- End Menu Creation ---

# --- File Handling ---
def handle_zip_file(downloaded_file_content, file_name_zip, message):
    user_id = message.from_user.id
    # chat_id = message.chat.id # script_owner_id (user_id here) will be used for script key context
    user_folder = get_user_folder(user_id)
    temp_dir = None 
    try:
        temp_dir = tempfile.mkdtemp(prefix=f"user_{user_id}_zip_")
        logger.info(f"Temp dir for zip: {temp_dir}")
        zip_path = os.path.join(temp_dir, file_name_zip)
        with open(zip_path, 'wb') as new_file: new_file.write(downloaded_file_content)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for member in zip_ref.infolist():
                member_path = os.path.abspath(os.path.join(temp_dir, member.filename))
                if not member_path.startswith(os.path.abspath(temp_dir)):
                    raise zipfile.BadZipFile(f"Zip has unsafe path: {member.filename}")
            zip_ref.extractall(temp_dir)
            logger.info(f"Extracted zip to {temp_dir}")

        extracted_items = os.listdir(temp_dir)
        py_files = [f for f in extracted_items if f.endswith('.py')]
        js_files = [f for f in extracted_items if f.endswith('.js')]
        req_file = 'requirements.txt' if 'requirements.txt' in extracted_items else None
        pkg_json = 'package.json' if 'package.json' in extracted_items else None

        if req_file:
            req_path = os.path.join(temp_dir, req_file)
            logger.info(f"requirements.txt found, installing: {req_path}")
            bot.reply_to(message, f"🔄 ɪɴꜱᴛᴀʟʟɪɴɢ ᴩʏᴛʜᴏɴ ᴅᴇᴩꜱ ꜰʀᴏᴍ `{req_file}`...")
            try:
                command = [sys.executable, '-m', 'pip', 'install', '-r', req_path]
                result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore')
                logger.info(f"pip install from requirements.txt OK. Output:\n{result.stdout}")
                bot.reply_to(message, f"✅ ᴩʏᴛʜᴏɴ ᴅᴇᴩꜱ ꜰʀᴏᴍ `{req_file}` ɪɴꜱᴛᴀʟʟᴇᴅ.")
            except subprocess.CalledProcessError as e:
                error_msg = f"❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ɪɴꜱᴛᴀʟʟ ᴩʏᴛʜᴏɴ ᴅᴇᴩꜱ ꜰʀᴏᴍ `{req_file}`.\nʟᴏɢ:\n```\n{e.stderr or e.stdout}\n```"
                logger.error(error_msg)
                if len(error_msg) > 4000: error_msg = error_msg[:4000] + "\n... (ʟᴏɢ ᴛʀᴜɴᴄᴀᴛᴇᴅ)"
                bot.reply_to(message, error_msg, parse_mode='Markdown'); return
            except Exception as e:
                 error_msg = f"❌ ᴜɴᴇxᴩᴇᴄᴛᴇᴅ ᴇʀʀᴏʀ ɪɴꜱᴛᴀʟʟɪɴɢ ᴩʏᴛʜᴏɴ ᴅᴇᴩꜱ: {e}"
                 logger.error(error_msg, exc_info=True); bot.reply_to(message, error_msg); return

        if pkg_json:
            logger.info(f"package.json found, npm install in: {temp_dir}")
            bot.reply_to(message, f"🔄 ɪɴꜱᴛᴀʟʟɪɴɢ ɴᴏᴅᴇ ᴅᴇᴩꜱ ꜰʀᴏᴍ `{pkg_json}`...")
            try:
                command = ['npm', 'install']
                result = subprocess.run(command, capture_output=True, text=True, check=True, cwd=temp_dir, encoding='utf-8', errors='ignore')
                logger.info(f"npm install OK. Output:\n{result.stdout}")
                bot.reply_to(message, f"✅ ɴᴏᴅᴇ ᴅᴇᴩꜱ ꜰʀᴏᴍ `{pkg_json}` ɪɴꜱᴛᴀʟʟᴇᴅ.")
            except FileNotFoundError:
                bot.reply_to(message, "❌ 'ɴᴩᴍ' ɴᴏᴛ ꜰᴏᴜɴᴅ. ᴄᴀɴɴᴏᴛ ɪɴꜱᴛᴀʟʟ ɴᴏᴅᴇ ᴅᴇᴩꜱ."); return 
            except subprocess.CalledProcessError as e:
                error_msg = f"❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ɪɴꜱᴛᴀʟʟ ɴᴏᴅᴇ ᴅᴇᴩꜱ ꜰʀᴏᴍ `{pkg_json}`.\nʟᴏɢ:\n```\n{e.stderr or e.stdout}\n```"
                logger.error(error_msg)
                if len(error_msg) > 4000: error_msg = error_msg[:4000] + "\n... (ʟᴏɢ ᴛʀᴜɴᴄᴀᴛᴇᴅ)"
                bot.reply_to(message, error_msg, parse_mode='Markdown'); return
            except Exception as e:
                 error_msg = f"❌ ᴜɴᴇxᴩᴇᴄᴛᴇᴅ ᴇʀʀᴏʀ ɪɴꜱᴛᴀʟʟɪɴɢ ɴᴏᴅᴇ ᴅᴇᴩꜱ: {e}"
                 logger.error(error_msg, exc_info=True); bot.reply_to(message, error_msg); return

        main_script_name = None; file_type = None
        preferred_py = ['main.py', 'bot.py', 'app.py']; preferred_js = ['index.js', 'main.js', 'bot.js', 'app.js']
        for p in preferred_py:
            if p in py_files: main_script_name = p; file_type = 'py'; break
        if not main_script_name:
             for p in preferred_js:
                 if p in js_files: main_script_name = p; file_type = 'js'; break
        if not main_script_name:
            if py_files: main_script_name = py_files[0]; file_type = 'py'
            elif js_files: main_script_name = js_files[0]; file_type = 'js'
        if not main_script_name:
            bot.reply_to(message, "❌ ɴᴏ `.py` ᴏʀ `.js` ꜱᴄʀɪᴩᴛ ꜰᴏᴜɴᴅ ɪɴ ᴀʀᴄʜɪᴠᴇ!"); return

        logger.info(f"Moving extracted files from {temp_dir} to {user_folder}")
        moved_count = 0
        for item_name in os.listdir(temp_dir):
            src_path = os.path.join(temp_dir, item_name)
            dest_path = os.path.join(user_folder, item_name)
            if os.path.isdir(dest_path): shutil.rmtree(dest_path)
            elif os.path.exists(dest_path): os.remove(dest_path)
            shutil.move(src_path, dest_path); moved_count +=1
        logger.info(f"Moved {moved_count} items to {user_folder}")

        save_user_file(user_id, main_script_name, file_type)
        logger.info(f"Saved main script '{main_script_name}' ({file_type}) for {user_id} from zip.")
        main_script_path = os.path.join(user_folder, main_script_name)
        bot.reply_to(message, f"✅ ꜰɪʟᴇꜱ ᴇxᴛʀᴀᴄᴛᴇᴅ. ꜱᴛᴀʀᴛɪɴɢ ᴍᴀɪɴ ꜱᴄʀɪᴩᴛ: `{main_script_name}`...", parse_mode='Markdown')

        # Use user_id as script_owner_id for script key context
        if file_type == 'py':
             threading.Thread(target=run_script, args=(main_script_path, user_id, user_folder, main_script_name, message)).start()
        elif file_type == 'js':
             threading.Thread(target=run_js_script, args=(main_script_path, user_id, user_folder, main_script_name, message)).start()

    except zipfile.BadZipFile as e:
        logger.error(f"Bad zip file from {user_id}: {e}")
        bot.reply_to(message, f"❌ ᴇʀʀᴏʀ: ɪɴᴠᴀʟɪᴅ/corrupted ᴢɪᴩ. {e}")
    except Exception as e:
        logger.error(f"❌ Error processing zip for {user_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ ᴇʀʀᴏʀ ᴩʀᴏᴄᴇꜱꜱɪɴɢ ᴢɪᴩ: {str(e)}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try: shutil.rmtree(temp_dir); logger.info(f"Cleaned temp dir: {temp_dir}")
            except Exception as e: logger.error(f"Failed to clean temp dir {temp_dir}: {e}", exc_info=True)

def handle_js_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        save_user_file(script_owner_id, file_name, 'js')
        threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, message)).start()
    except Exception as e:
        logger.error(f"❌ Error processing JS file {file_name} for {script_owner_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ ᴇʀʀᴏʀ ᴩʀᴏᴄᴇꜱꜱɪɴɢ ᴊꜱ ꜰɪʟᴇ: {str(e)}")

def handle_py_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        save_user_file(script_owner_id, file_name, 'py')
        threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, message)).start()
    except Exception as e:
        logger.error(f"❌ Error processing Python file {file_name} for {script_owner_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ ᴇʀʀᴏʀ ᴩʀᴏᴄᴇꜱꜱɪɴɢ ᴩʏᴛʜᴏɴ ꜰɪʟᴇ: {str(e)}")
# --- End File Handling ---


# --- Logic Functions (called by commands and text handlers) ---
def _logic_send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    user_username = message.from_user.username

    logger.info(f"Welcome request from user_id: {user_id}, username: @{user_username}")

    if bot_locked and user_id not in admin_ids:
        bot.send_message(chat_id, "⚠️ ʙᴏᴛ ʟᴏᴄᴋᴇᴅ ʙʏ ᴀᴅᴍɪɴ. ᴛʀʏ ʟᴀᴛᴇʀ.")
        return

    user_bio = "ᴄᴏᴜʟᴅ ɴᴏᴛ ꜰᴇᴛᴄʜ ʙɪᴏ"; photo_file_id = None
    try: user_bio = bot.get_chat(user_id).bio or "ɴᴏ ʙɪᴏ"
    except Exception: pass
    try:
        user_profile_photos = bot.get_user_profile_photos(user_id, limit=1)
        if user_profile_photos.photos: photo_file_id = user_profile_photos.photos[0][-1].file_id
    except Exception: pass

    if user_id not in active_users:
        add_active_user(user_id)
        try:
            owner_notification = (f"🎉 ɴᴇᴡ ᴜꜱᴇʀ!\n👤 ɴᴀᴍᴇ: {user_name}\n✳️ ᴜꜱᴇʀ: @{user_username or 'ɴ/A'}\n"
                                  f"🆔 ID: `{user_id}`\n📝 Bio: {user_bio}")
            bot.send_message(OWNER_ID, owner_notification, parse_mode='Markdown')
            if photo_file_id: bot.send_photo(OWNER_ID, photo_file_id, caption=f"ᴩɪᴄ ᴏꜰ ɴᴇᴡ ᴜꜱᴇʀ {user_id}")
        except Exception as e: logger.error(f"⚠️ Failed to notify owner about new user {user_id}: {e}")

    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
    expiry_info = ""
    if user_id == OWNER_ID: user_status = "👑 ᴏᴡɴᴇʀ"
    elif user_id in admin_ids: user_status = "🛡️ ᴀᴅᴍɪɴ"
    elif user_id in user_subscriptions:
        expiry_date = user_subscriptions[user_id].get('expiry')
        if expiry_date and expiry_date > datetime.now():
            user_status = "⭐ ᴩʀᴇᴍɪᴜᴍ"; days_left = (expiry_date - datetime.now()).days
            expiry_info = f"\n⏳ ꜱᴜʙꜱᴄʀɪᴩᴛɪᴏɴ ᴇxᴩɪʀᴇꜱ ɪɴ: {days_left} ᴅᴀʏꜱ"
        else: user_status = "🆓 ꜰʀᴇᴇ ᴜꜱᴇʀ (ᴇxᴩɪʀᴇᴅ ꜱᴜʙ)"; remove_subscription_db(user_id) # Clean up expired
    else: user_status = "🆓 ꜰʀᴇᴇ ᴜꜱᴇʀ"

    welcome_msg_text = (f"〽️ ᴡᴇʟᴄᴏᴍᴇ, {user_name}!\n\n🆔 ʏᴏᴜʀ ᴜꜱᴇʀ ɪᴅ: `{user_id}`\n"
                        f"✳️ Username: `@{user_username or 'Not set'}`\n"
                        f"🔰 Your Status: {user_status}{expiry_info}\n"
                        f"📁 Files Uploaded: {current_files} / {limit_str}\n\n"
                        f"🤖 Host & run Python (`.py`) or JS (`.js`) scripts.\n"
                        f"   Upload single scripts or `.zip` archives.\n\n"
                        f"👇 Use buttons or type commands.")
    main_reply_markup = create_reply_keyboard_main_menu(user_id)
    try:
        if photo_file_id: bot.send_photo(chat_id, photo_file_id)
        bot.send_message(chat_id, welcome_msg_text, reply_markup=main_reply_markup, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error sending welcome to {user_id}: {e}", exc_info=True)
        try: bot.send_message(chat_id, welcome_msg_text, reply_markup=main_reply_markup, parse_mode='Markdown') # Fallback without photo
        except Exception as fallback_e: logger.error(f"Fallback send_message failed for {user_id}: {fallback_e}")

def _logic_updates_channel(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📢 ᴜᴩᴅᴀᴛᴇꜱ ᴄʜᴀɴɴᴇʟ', url=UPDATE_CHANNEL, style='primary'))
    bot.reply_to(message, "ᴠɪꜱɪᴛ ᴏᴜʀ ᴜᴩᴅᴀᴛᴇꜱ ᴄʜᴀɴɴᴇʟ:", reply_markup=markup)

def _logic_upload_file(message):
    user_id = message.from_user.id
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ ʙᴏᴛ ʟᴏᴄᴋᴇᴅ ʙʏ ᴀᴅᴍɪɴ, ᴄᴀɴɴᴏᴛ ᴀᴄᴄᴇᴩᴛ ꜰɪʟᴇꜱ.")
        return

    # Removed free_mode check, relies on get_user_file_limit and FREE_USER_LIMIT
    # Users need to be admin or subscribed to upload if FREE_USER_LIMIT is 0
    # For now, FREE_USER_LIMIT > 0, so free users can upload up to that limit.
    # If we want to restrict free users entirely, set FREE_USER_LIMIT to 0.
    # For this implementation, free users get FREE_USER_LIMIT.

    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.reply_to(message, f"⚠️ ꜰɪʟᴇ ʟɪᴍɪᴛ ({current_files}/{limit_str}) ʀᴇᴀᴄʜᴇᴅ. ᴅᴇʟᴇᴛᴇ ꜰɪʟᴇꜱ ꜰɪʀꜱᴛ.")
        return
    bot.reply_to(message, "📤 ꜱᴇɴᴅ ʏᴏᴜʀ ᴩʏᴛʜᴏɴ (`.py`), ᴊꜱ (`.js`), ᴏʀ ᴢɪᴩ (`.zip`) ꜰɪʟᴇ.")

def _logic_check_files(message):
    user_id = message.from_user.id
    # chat_id = message.chat.id # user_id will be used as script_owner_id for buttons
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.reply_to(message, "📂 ʏᴏᴜʀ ꜰɪʟᴇꜱ:\n\n(ɴᴏ ꜰɪʟᴇꜱ ᴜᴩʟᴏᴀᴅᴇᴅ ʏᴇᴛ)")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(user_files_list):
        is_running = is_bot_running(user_id, file_name) # Use user_id for checking status
        status_icon = "🟢 Running" if is_running else "🔴 Stopped"
        btn_text = f"{file_name} ({file_type}) - {status_icon}"
        # Callback data includes user_id as script_owner_id
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f'file_{user_id}_{file_name}', style='primary'))
    bot.reply_to(message, "📂 ʏᴏᴜʀ ꜰɪʟᴇꜱ:\nᴄʟɪᴄᴋ ᴛᴏ ᴍᴀɴᴀɢᴇ.", reply_markup=markup, parse_mode='Markdown')

def _logic_bot_speed(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    start_time_ping = time.time()
    wait_msg = bot.reply_to(message, "🏃 ᴛᴇꜱᴛɪɴɢ ꜱᴩᴇᴇᴅ...")
    try:
        bot.send_chat_action(chat_id, 'typing')
        response_time = round((time.time() - start_time_ping) * 1000, 2)
        status = "🔓 Unlocked" if not bot_locked else "🔒 Locked"
        # mode = "💰 Free Mode: ON" if free_mode else "💸 Free Mode: OFF" # Removed free_mode
        if user_id == OWNER_ID: user_level = "👑 Owner"
        elif user_id in admin_ids: user_level = "🛡️ Admin"
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now(): user_level = "⭐ Premium"
        else: user_level = "🆓 Free User"
        speed_msg = (f"⚡ ʙᴏᴛ ꜱᴩᴇᴇᴅ & ꜱᴛᴀᴛᴜꜱ:\n\n⏱️ ᴀᴩɪ ʀᴇꜱᴩᴏɴꜱᴇ ᴛɪᴍᴇ: {response_time} ᴍꜱ\n"
                     f"🚦 Bot Status: {status}\n"
                     # f"模式 Mode: {mode}\n" # Removed
                     f"👤 Your Level: {user_level}")
        bot.edit_message_text(speed_msg, chat_id, wait_msg.message_id)
    except Exception as e:
        logger.error(f"Error during speed test (cmd): {e}", exc_info=True)
        bot.edit_message_text("❌ ᴇʀʀᴏʀ ᴅᴜʀɪɴɢ ꜱᴩᴇᴇᴅ ᴛᴇꜱᴛ.", chat_id, wait_msg.message_id)

def _logic_contact_owner(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📞 ᴄᴏɴᴛᴀᴄᴛ ᴏᴡɴᴇʀ', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}', style='primary'))
    bot.reply_to(message, "ᴄʟɪᴄᴋ ᴛᴏ ᴄᴏɴᴛᴀᴄᴛ ᴏᴡɴᴇʀ:", reply_markup=markup)

# --- Admin Logic Functions ---
def _logic_subscriptions_panel(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ ᴀᴅᴍɪɴ ᴩᴇʀᴍɪꜱꜱɪᴏɴꜱ ʀᴇǫᴜɪʀᴇᴅ.")
        return
    bot.reply_to(message, "💳 ꜱᴜʙꜱᴄʀɪᴩᴛɪᴏɴ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ\nᴜꜱᴇ ɪɴʟɪɴᴇ ʙᴜᴛᴛᴏɴꜱ ꜰʀᴏᴍ /start ᴏʀ ᴀᴅᴍɪɴ ᴄᴏᴍᴍᴀɴᴅ ᴍᴇɴᴜ.", reply_markup=create_subscription_menu())

def _logic_statistics(message):
    # No admin check here, allow all users but show admin-specific info if admin
    user_id = message.from_user.id
    total_users = len(active_users)
    total_files_records = sum(len(files) for files in user_files.values())

    running_bots_count = 0
    user_running_bots = 0

    for script_key_iter, script_info_iter in list(bot_scripts.items()):
        s_owner_id, _ = script_key_iter.split('_', 1) # Extract owner_id from key
        if is_bot_running(int(s_owner_id), script_info_iter['file_name']):
            running_bots_count += 1
            if int(s_owner_id) == user_id:
                user_running_bots +=1

    stats_msg_base = (f"📊 ʙᴏᴛ ꜱᴛᴀᴛɪꜱᴛɪᴄꜱ:\n\n"
                      f"👥 Total Users: {total_users}\n"
                      f"📂 Total File Records: {total_files_records}\n"
                      f"🟢 Total Active Bots: {running_bots_count}\n")

    if user_id in admin_ids:
        stats_msg_admin = (f"🔒 ʙᴏᴛ ꜱᴛᴀᴛᴜꜱ: {'🔴 ʟᴏᴄᴋᴇᴅ' if bot_locked else '🟢 ᴜɴʟᴏᴄᴋᴇᴅ'}\n"
                           # f"💰 Free Mode: {'✅ ON' if free_mode else '❌ OFF'}\n" # Removed
                           f"🤖 Your Running Bots: {user_running_bots}")
        stats_msg = stats_msg_base + stats_msg_admin
    else:
        stats_msg = stats_msg_base + f"🤖 Your Running Bots: {user_running_bots}"

    bot.reply_to(message, stats_msg)


def _logic_broadcast_init(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ ᴀᴅᴍɪɴ ᴩᴇʀᴍɪꜱꜱɪᴏɴꜱ ʀᴇǫᴜɪʀᴇᴅ.")
        return
    msg = bot.reply_to(message, "📢 ꜱᴇɴᴅ ᴍᴇꜱꜱᴀɢᴇ ᴛᴏ ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴛᴏ ᴀʟʟ ᴀᴄᴛɪᴠᴇ ᴜꜱᴇʀꜱ.\n/cancel ᴛᴏ ᴀʙᴏʀᴛ.")
    bot.register_next_step_handler(msg, process_broadcast_message)

def _logic_toggle_lock_bot(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ ᴀᴅᴍɪɴ ᴩᴇʀᴍɪꜱꜱɪᴏɴꜱ ʀᴇǫᴜɪʀᴇᴅ.")
        return
    global bot_locked
    bot_locked = not bot_locked
    status = "locked" if bot_locked else "unlocked"
    logger.warning(f"Bot {status} by Admin {message.from_user.id} via command/button.")
    bot.reply_to(message, f"🔒 ʙᴏᴛ ʜᴀꜱ ʙᴇᴇɴ {status}.")

# def _logic_toggle_free_mode(message): # Removed
#     pass

def _logic_admin_panel(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ ᴀᴅᴍɪɴ ᴩᴇʀᴍɪꜱꜱɪᴏɴꜱ ʀᴇǫᴜɪʀᴇᴅ.")
        return
    bot.reply_to(message, "👑 ᴀᴅᴍɪɴ ᴩᴀɴᴇʟ\nᴍᴀɴᴀɢᴇ ᴀᴅᴍɪɴꜱ. ᴜꜱᴇ ɪɴʟɪɴᴇ ʙᴜᴛᴛᴏɴꜱ ꜰʀᴏᴍ /start ᴏʀ ᴀᴅᴍɪɴ ᴍᴇɴᴜ.",
                 reply_markup=create_admin_panel())

def _logic_run_all_scripts(message_or_call):
    if isinstance(message_or_call, telebot.types.Message):
        admin_user_id = message_or_call.from_user.id
        admin_chat_id = message_or_call.chat.id
        reply_func = lambda text, **kwargs: bot.reply_to(message_or_call, text, **kwargs)
        admin_message_obj_for_script_runner = message_or_call
    elif isinstance(message_or_call, telebot.types.CallbackQuery):
        admin_user_id = message_or_call.from_user.id
        admin_chat_id = message_or_call.message.chat.id
        bot.answer_callback_query(message_or_call.id)
        reply_func = lambda text, **kwargs: bot.send_message(admin_chat_id, text, **kwargs)
        admin_message_obj_for_script_runner = message_or_call.message 
    else:
        logger.error("Invalid argument for _logic_run_all_scripts")
        return

    if admin_user_id not in admin_ids:
        reply_func("⚠️ Admin permissions required.")
        return

    reply_func("⏳ Starting process to run all user scripts. This may take a while...")
    logger.info(f"Admin {admin_user_id} initiated 'run all scripts' from chat {admin_chat_id}.")

    started_count = 0; attempted_users = 0; skipped_files = 0; error_files_details = []

    # Use a copy of user_files keys and values to avoid modification issues during iteration
    all_user_files_snapshot = dict(user_files)

    for target_user_id, files_for_user in all_user_files_snapshot.items():
        if not files_for_user: continue
        attempted_users += 1
        logger.info(f"Processing scripts for user {target_user_id}...")
        user_folder = get_user_folder(target_user_id)

        for file_name, file_type in files_for_user:
            # script_owner_id for key context is target_user_id
            if not is_bot_running(target_user_id, file_name):
                file_path = os.path.join(user_folder, file_name)
                if os.path.exists(file_path):
                    logger.info(f"Admin {admin_user_id} attempting to start '{file_name}' ({file_type}) for user {target_user_id}.")
                    try:
                        if file_type == 'py':
                            threading.Thread(target=run_script, args=(file_path, target_user_id, user_folder, file_name, admin_message_obj_for_script_runner)).start()
                            started_count += 1
                        elif file_type == 'js':
                            threading.Thread(target=run_js_script, args=(file_path, target_user_id, user_folder, file_name, admin_message_obj_for_script_runner)).start()
                            started_count += 1
                        else:
                            logger.warning(f"Unknown file type '{file_type}' for {file_name} (user {target_user_id}). Skipping.")
                            error_files_details.append(f"`{file_name}` (User {target_user_id}) - Unknown type")
                            skipped_files += 1
                        time.sleep(0.7) # Increased delay slightly
                    except Exception as e:
                        logger.error(f"Error queueing start for '{file_name}' (user {target_user_id}): {e}")
                        error_files_details.append(f"`{file_name}` (User {target_user_id}) - Start error")
                        skipped_files += 1
                else:
                    logger.warning(f"File '{file_name}' for user {target_user_id} not found at '{file_path}'. Skipping.")
                    error_files_details.append(f"`{file_name}` (User {target_user_id}) - File not found")
                    skipped_files += 1
            # else: logger.info(f"Script '{file_name}' for user {target_user_id} already running.")

    summary_msg = (f"✅ All Users' Scripts - Processing Complete:\n\n"
                   f"▶️ Attempted to start: {started_count} scripts.\n"
                   f"👥 Users processed: {attempted_users}.\n")
    if skipped_files > 0:
        summary_msg += f"⚠️ ꜱᴋɪᴩᴩᴇᴅ/Error ꜰɪʟᴇꜱ: {skipped_files}\n"
        if error_files_details:
             summary_msg += "ᴅᴇᴛᴀɪʟꜱ (ꜰɪʀꜱᴛ 5):\n" + "\n".join([f"  - {err}" for err in error_files_details[:5]])
             if len(error_files_details) > 5: summary_msg += "\n  ... ᴀɴᴅ ᴍᴏʀᴇ (ᴄʜᴇᴄᴋ ʟᴏɢꜱ)."

    reply_func(summary_msg, parse_mode='Markdown')
    logger.info(f"Run all scripts finished. Admin: {admin_user_id}. Started: {started_count}. Skipped/Errors: {skipped_files}")


# --- Command Handlers & Text Handlers for ReplyKeyboard ---
@bot.message_handler(commands=['start', 'help'])
def command_send_welcome(message): _logic_send_welcome(message)

@bot.message_handler(commands=['status']) # Kept for direct command
def command_show_status(message): _logic_statistics(message) # Changed to call _logic_statistics


BUTTON_TEXT_TO_LOGIC = {
    "📢 Updates Channel": _logic_updates_channel,
    "📤 Upload File": _logic_upload_file,
    "📂 Check Files": _logic_check_files,
    "⚡ Bot Speed": _logic_bot_speed,
    "📞 Contact Owner": _logic_contact_owner,
    "📊 Statistics": _logic_statistics, 
    "💳 Subscriptions": _logic_subscriptions_panel,
    "📢 Broadcast": _logic_broadcast_init,
    "🔒 Lock Bot": _logic_toggle_lock_bot, 
    # "💰 Free Mode": _logic_toggle_free_mode, # Removed
    "🟢 Running All Code": _logic_run_all_scripts, # Added
    "👑 Admin Panel": _logic_admin_panel,
}

@bot.message_handler(func=lambda message: message.text in BUTTON_TEXT_TO_LOGIC)
def handle_button_text(message):
    logic_func = BUTTON_TEXT_TO_LOGIC.get(message.text)
    if logic_func: logic_func(message)
    else: logger.warning(f"Button text '{message.text}' matched but no logic func.")

@bot.message_handler(commands=['updateschannel'])
def command_updates_channel(message): _logic_updates_channel(message)
@bot.message_handler(commands=['uploadfile'])
def command_upload_file(message): _logic_upload_file(message)
@bot.message_handler(commands=['checkfiles'])
def command_check_files(message): _logic_check_files(message)
@bot.message_handler(commands=['botspeed'])
def command_bot_speed(message): _logic_bot_speed(message)
@bot.message_handler(commands=['contactowner'])
def command_contact_owner(message): _logic_contact_owner(message)
@bot.message_handler(commands=['subscriptions'])
def command_subscriptions(message): _logic_subscriptions_panel(message)
@bot.message_handler(commands=['statistics']) # Alias for /status
def command_statistics(message): _logic_statistics(message)
@bot.message_handler(commands=['broadcast'])
def command_broadcast(message): _logic_broadcast_init(message)
@bot.message_handler(commands=['lockbot']) 
def command_lock_bot(message): _logic_toggle_lock_bot(message)
# @bot.message_handler(commands=['freemode']) # Removed
# def command_free_mode(message): _logic_toggle_free_mode(message)
@bot.message_handler(commands=['adminpanel'])
def command_admin_panel(message): _logic_admin_panel(message)
@bot.message_handler(commands=['runningallcode']) # Added
def command_run_all_code(message): _logic_run_all_scripts(message)


@bot.message_handler(commands=['ping'])
def ping(message):
    start_ping_time = time.time() 
    msg = bot.reply_to(message, "ᴩᴏɴɢ!")
    latency = round((time.time() - start_ping_time) * 1000, 2)
    bot.edit_message_text(f"Pong! Latency: {latency} ms", message.chat.id, msg.message_id)


# --- Document (File) Handler ---
@bot.message_handler(content_types=['document'])
def handle_file_upload_doc(message): # Renamed
    user_id = message.from_user.id
    chat_id = message.chat.id # Used for replies, script context uses user_id
    doc = message.document
    logger.info(f"Doc from {user_id}: {doc.file_name} ({doc.mime_type}), Size: {doc.file_size}")

    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ ʙᴏᴛ ʟᴏᴄᴋᴇᴅ, ᴄᴀɴɴᴏᴛ ᴀᴄᴄᴇᴩᴛ ꜰɪʟᴇꜱ.")
        return

    # File limit check (relies on FREE_USER_LIMIT being > 0 for free users)
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.reply_to(message, f"⚠️ ꜰɪʟᴇ ʟɪᴍɪᴛ ({current_files}/{limit_str}) ʀᴇᴀᴄʜᴇᴅ. ᴅᴇʟᴇᴛᴇ ꜰɪʟᴇꜱ ᴠɪᴀ /checkfiles.")
        return

    file_name = doc.file_name
    if not file_name: bot.reply_to(message, "⚠️ ɴᴏ ꜰɪʟᴇ ɴᴀᴍᴇ. ᴇɴꜱᴜʀᴇ ꜰɪʟᴇ ʜᴀꜱ ᴀ ɴᴀᴍᴇ."); return
    file_ext = os.path.splitext(file_name)[1].lower()
    if file_ext not in ['.py', '.js', '.zip']:
        bot.reply_to(message, "⚠️ ᴜɴꜱᴜᴩᴩᴏʀᴛᴇᴅ ᴛʏᴩᴇ! ᴏɴʟʏ `.py`, `.js`, `.zip` ᴀʟʟᴏᴡᴇᴅ.")
        return
    max_file_size = 20 * 1024 * 1024 # 20 MB
    if doc.file_size > max_file_size:
        bot.reply_to(message, f"⚠️ ꜰɪʟᴇ ᴛᴏᴏ ʟᴀʀɢᴇ (ᴍᴀx: {max_file_size // 1024 // 1024} ᴍʙ)."); return

    try:
        try:
            bot.forward_message(OWNER_ID, chat_id, message.message_id)
            bot.send_message(OWNER_ID, f"⬆️ ꜰɪʟᴇ '{file_name}' ꜰʀᴏᴍ {message.from_user.first_name} (`{user_id}`)", parse_mode='Markdown')
        except Exception as e: logger.error(f"Failed to forward uploaded file to OWNER_ID {OWNER_ID}: {e}")

        download_wait_msg = bot.reply_to(message, f"⏳ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ `{file_name}`...")
        file_info_tg_doc = bot.get_file(doc.file_id) # Renamed
        downloaded_file_content = bot.download_file(file_info_tg_doc.file_path)
        bot.edit_message_text(f"✅ Downloaded `{file_name}`. Processing...", chat_id, download_wait_msg.message_id)
        logger.info(f"Downloaded {file_name} for user {user_id}")
        user_folder = get_user_folder(user_id)

        if file_ext == '.zip':
            handle_zip_file(downloaded_file_content, file_name, message)
        else:
            file_path = os.path.join(user_folder, file_name)
            with open(file_path, 'wb') as f: f.write(downloaded_file_content)
            logger.info(f"Saved single file to {file_path}")
            # Pass user_id as script_owner_id
            if file_ext == '.js': handle_js_file(file_path, user_id, user_folder, file_name, message)
            elif file_ext == '.py': handle_py_file(file_path, user_id, user_folder, file_name, message)
    except telebot.apihelper.ApiTelegramException as e:
         logger.error(f"Telegram API Error handling file for {user_id}: {e}", exc_info=True)
         if "file is too big" in str(e).lower():
              bot.reply_to(message, f"❌ ᴛᴇʟᴇɢʀᴀᴍ ᴀᴩɪ ᴇʀʀᴏʀ: ꜰɪʟᴇ ᴛᴏᴏ ʟᴀʀɢᴇ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ (~20ᴍʙ ʟɪᴍɪᴛ).")
         else: bot.reply_to(message, f"❌ ᴛᴇʟᴇɢʀᴀᴍ ᴀᴩɪ ᴇʀʀᴏʀ: {str(e)}. ᴛʀʏ ʟᴀᴛᴇʀ.")
    except Exception as e:
        logger.error(f"❌ General error handling file for {user_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ ᴜɴᴇxᴩᴇᴄᴛᴇᴅ ᴇʀʀᴏʀ: {str(e)}")
# --- End Document Handler ---


# --- Callback Query Handlers (for Inline Buttons) ---
@bot.callback_query_handler(func=lambda call: True) 
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data
    logger.info(f"Callback: User={user_id}, Data='{data}'")

    if bot_locked and user_id not in admin_ids and data not in ['back_to_main', 'speed', 'stats']: # Allow stats
        bot.answer_callback_query(call.id, "⚠️ ʙᴏᴛ ʟᴏᴄᴋᴇᴅ ʙʏ ᴀᴅᴍɪɴ.", show_alert=True)
        return
    try:
        if data == 'upload': upload_callback(call)
        elif data == 'check_files': check_files_callback(call)
        elif data.startswith('file_'): file_control_callback(call)
        elif data.startswith('start_'): start_bot_callback(call)
        elif data.startswith('stop_'): stop_bot_callback(call)
        elif data.startswith('restart_'): restart_bot_callback(call)
        elif data.startswith('delete_'): delete_bot_callback(call)
        elif data.startswith('logs_'): logs_bot_callback(call)
        elif data == 'speed': speed_callback(call)
        elif data == 'back_to_main': back_to_main_callback(call)
        elif data.startswith('confirm_broadcast_'): handle_confirm_broadcast(call)
        elif data == 'cancel_broadcast': handle_cancel_broadcast(call)
        # --- Admin Callbacks ---
        elif data == 'subscription': admin_required_callback(call, subscription_management_callback)
        elif data == 'stats': stats_callback(call) # No admin check here, handled in func
        elif data == 'lock_bot': admin_required_callback(call, lock_bot_callback)
        elif data == 'unlock_bot': admin_required_callback(call, unlock_bot_callback)
        # elif data == 'free_mode': admin_required_callback(call, toggle_free_mode_callback) # Removed
        elif data == 'run_all_scripts': admin_required_callback(call, run_all_scripts_callback) # Added
        elif data == 'broadcast': admin_required_callback(call, broadcast_init_callback) 
        elif data == 'admin_panel': admin_required_callback(call, admin_panel_callback)
        elif data == 'add_admin': owner_required_callback(call, add_admin_init_callback) 
        elif data == 'remove_admin': owner_required_callback(call, remove_admin_init_callback) 
        elif data == 'list_admins': admin_required_callback(call, list_admins_callback)
        elif data == 'add_subscription': admin_required_callback(call, add_subscription_init_callback) 
        elif data == 'remove_subscription': admin_required_callback(call, remove_subscription_init_callback) 
        elif data == 'check_subscription': admin_required_callback(call, check_subscription_init_callback) 
        else:
            bot.answer_callback_query(call.id, "ᴜɴᴋɴᴏᴡɴ ᴀᴄᴛɪᴏɴ.")
            logger.warning(f"Unhandled callback data: {data} from user {user_id}")
    except Exception as e:
        logger.error(f"Error handling callback '{data}' for {user_id}: {e}", exc_info=True)
        try: bot.answer_callback_query(call.id, "ᴇʀʀᴏʀ ᴩʀᴏᴄᴇꜱꜱɪɴɢ ʀᴇǫᴜᴇꜱᴛ.", show_alert=True)
        except Exception as e_ans: logger.error(f"Failed to answer callback after error: {e_ans}")

def admin_required_callback(call, func_to_run):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "⚠️ ᴀᴅᴍɪɴ ᴩᴇʀᴍɪꜱꜱɪᴏɴꜱ ʀᴇǫᴜɪʀᴇᴅ.", show_alert=True)
        return
    func_to_run(call) 

def owner_required_callback(call, func_to_run):
    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "⚠️ ᴏᴡɴᴇʀ ᴩᴇʀᴍɪꜱꜱɪᴏɴꜱ ʀᴇǫᴜɪʀᴇᴅ.", show_alert=True)
        return
    func_to_run(call)

def upload_callback(call):
    user_id = call.from_user.id
    # Removed free_mode check
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.answer_callback_query(call.id, f"⚠️ ꜰɪʟᴇ ʟɪᴍɪᴛ ({current_files}/{limit_str}) ʀᴇᴀᴄʜᴇᴅ.", show_alert=True)
        return
    bot.answer_callback_query(call.id) 
    bot.send_message(call.message.chat.id, "📤 ꜱᴇɴᴅ ʏᴏᴜʀ ᴩʏᴛʜᴏɴ (`.py`), ᴊꜱ (`.js`), ᴏʀ ᴢɪᴩ (`.zip`) ꜰɪʟᴇ.")

def check_files_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id 
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.answer_callback_query(call.id, "⚠️ ɴᴏ ꜰɪʟᴇꜱ ᴜᴩʟᴏᴀᴅᴇᴅ.", show_alert=True)
        try:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ", callback_data='back_to_main', style='primary'))
            bot.edit_message_text("📂 ʏᴏᴜʀ ꜰɪʟᴇꜱ:\n\n(ɴᴏ ꜰɪʟᴇꜱ ᴜᴩʟᴏᴀᴅᴇᴅ)", chat_id, call.message.message_id, reply_markup=markup)
        except Exception as e: logger.error(f"Error editing msg for empty file list: {e}")
        return
    bot.answer_callback_query(call.id) 
    markup = types.InlineKeyboardMarkup(row_width=1) 
    for file_name, file_type in sorted(user_files_list): 
        is_running = is_bot_running(user_id, file_name) # Use user_id for status check
        status_icon = "🟢 Running" if is_running else "🔴 Stopped"
        btn_text = f"{file_name} ({file_type}) - {status_icon}"
        # Callback includes user_id as script_owner_id
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f'file_{user_id}_{file_name}', style='primary'))
    markup.add(types.InlineKeyboardButton("🔙 ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ", callback_data='back_to_main', style='primary'))
    try:
        bot.edit_message_text("📂 ʏᴏᴜʀ ꜰɪʟᴇꜱ:\nᴄʟɪᴄᴋ ᴛᴏ ᴍᴀɴᴀɢᴇ.", chat_id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    except telebot.apihelper.ApiTelegramException as e:
         if "message is not modified" in str(e): logger.warning("Msg not modified (files).")
         else: logger.error(f"Error editing msg for file list: {e}")
    except Exception as e: logger.error(f"Unexpected error editing msg for file list: {e}", exc_info=True)

def file_control_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id

        # Allow owner/admin to control any file, or user to control their own
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            logger.warning(f"User {requesting_user_id} tried to access file '{file_name}' of user {script_owner_id} without permission.")
            bot.answer_callback_query(call.id, "⚠️ ʏᴏᴜ ᴄᴀɴ ᴏɴʟʏ ᴍᴀɴᴀɢᴇ ʏᴏᴜʀ ᴏᴡɴ ꜰɪʟᴇꜱ.", show_alert=True)
            check_files_callback(call) # Show their own files
            return

        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            logger.warning(f"File '{file_name}' not found for user {script_owner_id} during control.")
            bot.answer_callback_query(call.id, "⚠️ ꜰɪʟᴇ ɴᴏᴛ ꜰᴏᴜɴᴅ.", show_alert=True)
            # If admin was viewing, this might be confusing. For now, just show their own.
            check_files_callback(call) 
            return

        bot.answer_callback_query(call.id) 
        is_running = is_bot_running(script_owner_id, file_name)
        status_text = '🟢 ʀᴜɴɴɪɴɢ' if is_running else '🔴 ꜱᴛᴏᴩᴩᴇᴅ'
        file_type = next((f[1] for f in user_files_list if f[0] == file_name), '?') 
        try:
            bot.edit_message_text(
                f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: {status_text}",
                call.message.chat.id, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_running),
                parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as e:
             if "message is not modified" in str(e): logger.warning(f"Msg not modified (controls for {file_name})")
             else: raise 
    except (ValueError, IndexError) as ve:
        logger.error(f"Error parsing file control callback: {ve}. Data: '{call.data}'")
        bot.answer_callback_query(call.id, "ᴇʀʀᴏʀ: ɪɴᴠᴀʟɪᴅ ᴀᴄᴛɪᴏɴ ᴅᴀᴛᴀ.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in file_control_callback for data '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ.", show_alert=True)

def start_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id # Where the admin/user gets the reply

        logger.info(f"Start request: Requester={requesting_user_id}, Owner={script_owner_id}, File='{file_name}'")

        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ ᴩᴇʀᴍɪꜱꜱɪᴏɴ ᴅᴇɴɪᴇᴅ ᴛᴏ ꜱᴛᴀʀᴛ ᴛʜɪꜱ ꜱᴄʀɪᴩᴛ.", show_alert=True); return

        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "⚠️ ꜰɪʟᴇ ɴᴏᴛ ꜰᴏᴜɴᴅ.", show_alert=True); check_files_callback(call); return

        file_type = file_info[1]
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)

        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, f"⚠️ ᴇʀʀᴏʀ: ꜰɪʟᴇ `{file_name}` ᴍɪꜱꜱɪɴɢ! ʀᴇ-ᴜᴩʟᴏᴀᴅ.", show_alert=True)
            remove_user_file_db(script_owner_id, file_name); check_files_callback(call); return

        if is_bot_running(script_owner_id, file_name):
            bot.answer_callback_query(call.id, f"⚠️ ꜱᴄʀɪᴩᴛ '{file_name}' ᴀʟʀᴇᴀᴅʏ ʀᴜɴɴɪɴɢ.", show_alert=True)
            try: bot.edit_message_reply_markup(chat_id_for_reply, call.message.message_id, reply_markup=create_control_buttons(script_owner_id, file_name, True))
            except Exception as e: logger.error(f"Error updating buttons (already running): {e}")
            return

        bot.answer_callback_query(call.id, f"⏳ ᴀᴛᴛᴇᴍᴩᴛɪɴɢ ᴛᴏ ꜱᴛᴀʀᴛ {file_name} ꜰᴏʀ ᴜꜱᴇʀ {script_owner_id}...")

        # Pass call.message as message_obj_for_reply so feedback goes to the person who clicked
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        else:
             bot.send_message(chat_id_for_reply, f"❌ ᴇʀʀᴏʀ: ᴜɴᴋɴᴏᴡɴ ꜰɪʟᴇ ᴛʏᴩᴇ '{file_type}' ꜰᴏʀ '{file_name}'."); return 

        time.sleep(1.5) # Give script time to actually start or fail early
        is_now_running = is_bot_running(script_owner_id, file_name) 
        status_text = '🟢 ʀᴜɴɴɪɴɢ' if is_now_running else '🟡 ꜱᴛᴀʀᴛɪɴɢ (ᴏʀ ꜰᴀɪʟᴇᴅ, ᴄʜᴇᴄᴋ ʟᴏɢꜱ/replies)'
        try:
            bot.edit_message_text(
                f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: {status_text}",
                chat_id_for_reply, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_now_running), parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as e:
             if "message is not modified" in str(e): logger.warning(f"Msg not modified after starting {file_name}")
             else: raise
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing start callback '{call.data}': {e}")
        bot.answer_callback_query(call.id, "ᴇʀʀᴏʀ: ɪɴᴠᴀʟɪᴅ ꜱᴛᴀʀᴛ ᴄᴏᴍᴍᴀɴᴅ.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in start_bot_callback for '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "ᴇʀʀᴏʀ ꜱᴛᴀʀᴛɪɴɢ ꜱᴄʀɪᴩᴛ.", show_alert=True)
        try: # Attempt to reset buttons to 'stopped' state on error
            _, script_owner_id_err_str, file_name_err = call.data.split('_', 2)
            script_owner_id_err = int(script_owner_id_err_str)
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_control_buttons(script_owner_id_err, file_name_err, False))
        except Exception as e_btn: logger.error(f"Failed to update buttons after start error: {e_btn}")

def stop_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id

        logger.info(f"Stop request: Requester={requesting_user_id}, Owner={script_owner_id}, File='{file_name}'")
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ ᴩᴇʀᴍɪꜱꜱɪᴏɴ ᴅᴇɴɪᴇᴅ.", show_alert=True); return

        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "⚠️ ꜰɪʟᴇ ɴᴏᴛ ꜰᴏᴜɴᴅ.", show_alert=True); check_files_callback(call); return

        file_type = file_info[1] 
        script_key = f"{script_owner_id}_{file_name}"

        if not is_bot_running(script_owner_id, file_name): 
            bot.answer_callback_query(call.id, f"⚠️ ꜱᴄʀɪᴩᴛ '{file_name}' ᴀʟʀᴇᴀᴅʏ ꜱᴛᴏᴩᴩᴇᴅ.", show_alert=True)
            try:
                 bot.edit_message_text(
                     f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: 🔴 Stopped",
                     chat_id_for_reply, call.message.message_id,
                     reply_markup=create_control_buttons(script_owner_id, file_name, False), parse_mode='Markdown')
            except Exception as e: logger.error(f"Error updating buttons (already stopped): {e}")
            return

        bot.answer_callback_query(call.id, f"⏳ ꜱᴛᴏᴩᴩɪɴɢ {file_name} ꜰᴏʀ ᴜꜱᴇʀ {script_owner_id}...")
        process_info = bot_scripts.get(script_key)
        if process_info:
            kill_process_tree(process_info)
            if script_key in bot_scripts: del bot_scripts[script_key]; logger.info(f"Removed {script_key} from running after stop.")
        else: logger.warning(f"Script {script_key} running by psutil but not in bot_scripts dict.")

        try:
            bot.edit_message_text(
                f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: 🔴 Stopped",
                chat_id_for_reply, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, False), parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as e:
             if "message is not modified" in str(e): logger.warning(f"Msg not modified after stopping {file_name}")
             else: raise
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing stop callback '{call.data}': {e}")
        bot.answer_callback_query(call.id, "ᴇʀʀᴏʀ: ɪɴᴠᴀʟɪᴅ ꜱᴛᴏᴩ ᴄᴏᴍᴍᴀɴᴅ.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in stop_bot_callback for '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "ᴇʀʀᴏʀ ꜱᴛᴏᴩᴩɪɴɢ ꜱᴄʀɪᴩᴛ.", show_alert=True)

def restart_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id

        logger.info(f"Restart: Requester={requesting_user_id}, Owner={script_owner_id}, File='{file_name}'")
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ ᴩᴇʀᴍɪꜱꜱɪᴏɴ ᴅᴇɴɪᴇᴅ.", show_alert=True); return

        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "⚠️ ꜰɪʟᴇ ɴᴏᴛ ꜰᴏᴜɴᴅ.", show_alert=True); check_files_callback(call); return

        file_type = file_info[1]; user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name); script_key = f"{script_owner_id}_{file_name}"

        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, f"⚠️ ᴇʀʀᴏʀ: ꜰɪʟᴇ `{file_name}` ᴍɪꜱꜱɪɴɢ! ʀᴇ-ᴜᴩʟᴏᴀᴅ.", show_alert=True)
            remove_user_file_db(script_owner_id, file_name)
            if script_key in bot_scripts: del bot_scripts[script_key]
            check_files_callback(call); return

        bot.answer_callback_query(call.id, f"⏳ ʀᴇꜱᴛᴀʀᴛɪɴɢ {file_name} ꜰᴏʀ ᴜꜱᴇʀ {script_owner_id}...")
        if is_bot_running(script_owner_id, file_name):
            logger.info(f"Restart: Stopping existing {script_key}...")
            process_info = bot_scripts.get(script_key)
            if process_info: kill_process_tree(process_info)
            if script_key in bot_scripts: del bot_scripts[script_key]
            time.sleep(1.5) 

        logger.info(f"Restart: Starting script {script_key}...")
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        else:
             bot.send_message(chat_id_for_reply, f"❌ ᴜɴᴋɴᴏᴡɴ ᴛʏᴩᴇ '{file_type}' ꜰᴏʀ '{file_name}'."); return

        time.sleep(1.5) 
        is_now_running = is_bot_running(script_owner_id, file_name) 
        status_text = '🟢 ʀᴜɴɴɪɴɢ' if is_now_running else '🟡 ꜱᴛᴀʀᴛɪɴɢ (ᴏʀ ꜰᴀɪʟᴇᴅ)'
        try:
            bot.edit_message_text(
                f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: {status_text}",
                chat_id_for_reply, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_now_running), parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as e:
             if "message is not modified" in str(e): logger.warning(f"Msg not modified (restart {file_name})")
             else: raise
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing restart callback '{call.data}': {e}")
        bot.answer_callback_query(call.id, "ᴇʀʀᴏʀ: ɪɴᴠᴀʟɪᴅ ʀᴇꜱᴛᴀʀᴛ ᴄᴏᴍᴍᴀɴᴅ.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in restart_bot_callback for '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "ᴇʀʀᴏʀ ʀᴇꜱᴛᴀʀᴛɪɴɢ.", show_alert=True)
        try:
            _, script_owner_id_err_str, file_name_err = call.data.split('_', 2)
            script_owner_id_err = int(script_owner_id_err_str)
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_control_buttons(script_owner_id_err, file_name_err, False))
        except Exception as e_btn: logger.error(f"Failed to update buttons after restart error: {e_btn}")


def delete_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id

        logger.info(f"Delete: Requester={requesting_user_id}, Owner={script_owner_id}, File='{file_name}'")
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ ᴩᴇʀᴍɪꜱꜱɪᴏɴ ᴅᴇɴɪᴇᴅ.", show_alert=True); return

        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            bot.answer_callback_query(call.id, "⚠️ ꜰɪʟᴇ ɴᴏᴛ ꜰᴏᴜɴᴅ.", show_alert=True); check_files_callback(call); return

        bot.answer_callback_query(call.id, f"🗑️ ᴅᴇʟᴇᴛɪɴɢ {file_name} ꜰᴏʀ ᴜꜱᴇʀ {script_owner_id}...")
        script_key = f"{script_owner_id}_{file_name}"
        if is_bot_running(script_owner_id, file_name):
            logger.info(f"Delete: Stopping {script_key}...")
            process_info = bot_scripts.get(script_key)
            if process_info: kill_process_tree(process_info)
            if script_key in bot_scripts: del bot_scripts[script_key]
            time.sleep(0.5) 

        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        deleted_disk = []
        if os.path.exists(file_path):
            try: os.remove(file_path); deleted_disk.append(file_name); logger.info(f"Deleted file: {file_path}")
            except OSError as e: logger.error(f"Error deleting {file_path}: {e}")
        if os.path.exists(log_path):
            try: os.remove(log_path); deleted_disk.append(os.path.basename(log_path)); logger.info(f"Deleted log: {log_path}")
            except OSError as e: logger.error(f"Error deleting log {log_path}: {e}")

        remove_user_file_db(script_owner_id, file_name)
        deleted_str = ", ".join(f"`{f}`" for f in deleted_disk) if deleted_disk else "associated files"
        try:
            bot.edit_message_text(
                f"🗑️ Record `{file_name}` (User `{script_owner_id}`) and {deleted_str} deleted!",
                chat_id_for_reply, call.message.message_id, reply_markup=None, parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error editing msg after delete: {e}")
            bot.send_message(chat_id_for_reply, f"🗑️ ʀᴇᴄᴏʀᴅ `{file_name}` ᴅᴇʟᴇᴛᴇᴅ.", parse_mode='Markdown')
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing delete callback '{call.data}': {e}")
        bot.answer_callback_query(call.id, "ᴇʀʀᴏʀ: ɪɴᴠᴀʟɪᴅ ᴅᴇʟᴇᴛᴇ ᴄᴏᴍᴍᴀɴᴅ.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in delete_bot_callback for '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "ᴇʀʀᴏʀ ᴅᴇʟᴇᴛɪɴɢ.", show_alert=True)

def logs_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id

        logger.info(f"Logs: Requester={requesting_user_id}, Owner={script_owner_id}, File='{file_name}'")
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ ᴩᴇʀᴍɪꜱꜱɪᴏɴ ᴅᴇɴɪᴇᴅ.", show_alert=True); return

        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            bot.answer_callback_query(call.id, "⚠️ ꜰɪʟᴇ ɴᴏᴛ ꜰᴏᴜɴᴅ.", show_alert=True); check_files_callback(call); return

        user_folder = get_user_folder(script_owner_id)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        if not os.path.exists(log_path):
            bot.answer_callback_query(call.id, f"⚠️ ɴᴏ ʟᴏɢꜱ ꜰᴏʀ '{file_name}'.", show_alert=True); return

        bot.answer_callback_query(call.id) 
        try:
            log_content = ""; file_size = os.path.getsize(log_path)
            max_log_kb = 100; max_tg_msg = 4096
            if file_size == 0: log_content = "(Log empty)"
            elif file_size > max_log_kb * 1024:
                 with open(log_path, 'rb') as f: f.seek(-max_log_kb * 1024, os.SEEK_END); log_bytes = f.read()
                 log_content = log_bytes.decode('utf-8', errors='ignore')
                 log_content = f"(Last {max_log_kb} KB)\n...\n" + log_content
            else:
                 with open(log_path, 'r', encoding='utf-8', errors='ignore') as f: log_content = f.read()

            if len(log_content) > max_tg_msg:
                log_content = log_content[-max_tg_msg:]
                first_nl = log_content.find('\n')
                if first_nl != -1: log_content = "...\n" + log_content[first_nl+1:]
                else: log_content = "...\n" + log_content 
            if not log_content.strip(): log_content = "(No visible content)"

            bot.send_message(chat_id_for_reply, f"📜 ʟᴏɢꜱ ꜰᴏʀ `{file_name}` (ᴜꜱᴇʀ `{script_owner_id}`):\n```\n{log_content}\n```", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error reading/sending log {log_path}: {e}", exc_info=True)
            bot.send_message(chat_id_for_reply, f"❌ ᴇʀʀᴏʀ ʀᴇᴀᴅɪɴɢ ʟᴏɢ ꜰᴏʀ `{file_name}`.")
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing logs callback '{call.data}': {e}")
        bot.answer_callback_query(call.id, "ᴇʀʀᴏʀ: ɪɴᴠᴀʟɪᴅ ʟᴏɢꜱ ᴄᴏᴍᴍᴀɴᴅ.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in logs_bot_callback for '{call.data}': {e}", exc_info=True)
        bot.answer_callback_query(call.id, "ᴇʀʀᴏʀ ꜰᴇᴛᴄʜɪɴɢ ʟᴏɢꜱ.", show_alert=True)

def speed_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    start_cb_ping_time = time.time() 
    try:
        bot.edit_message_text("🏃 ᴛᴇꜱᴛɪɴɢ ꜱᴩᴇᴇᴅ...", chat_id, call.message.message_id)
        bot.send_chat_action(chat_id, 'typing') 
        response_time = round((time.time() - start_cb_ping_time) * 1000, 2)
        status = "🔓 Unlocked" if not bot_locked else "🔒 Locked"
        # mode = "💰 Free Mode: ON" if free_mode else "💸 Free Mode: OFF" # Removed
        if user_id == OWNER_ID: user_level = "👑 Owner"
        elif user_id in admin_ids: user_level = "🛡️ Admin"
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now(): user_level = "⭐ Premium"
        else: user_level = "🆓 Free User"
        speed_msg = (f"⚡ ʙᴏᴛ ꜱᴩᴇᴇᴅ & ꜱᴛᴀᴛᴜꜱ:\n\n⏱️ ᴀᴩɪ ʀᴇꜱᴩᴏɴꜱᴇ ᴛɪᴍᴇ: {response_time} ᴍꜱ\n"
                     f"🚦 Bot Status: {status}\n"
                     # f"模式 Mode: {mode}\n" # Removed
                     f"👤 Your Level: {user_level}")
        bot.answer_callback_query(call.id) 
        bot.edit_message_text(speed_msg, chat_id, call.message.message_id, reply_markup=create_main_menu_inline(user_id))
    except Exception as e:
         logger.error(f"Error during speed test (cb): {e}", exc_info=True)
         bot.answer_callback_query(call.id, "ᴇʀʀᴏʀ ɪɴ ꜱᴩᴇᴇᴅ ᴛᴇꜱᴛ.", show_alert=True)
         try: bot.edit_message_text("〽️ ᴍᴀɪɴ ᴍᴇɴᴜ", chat_id, call.message.message_id, reply_markup=create_main_menu_inline(user_id))
         except Exception: pass

def back_to_main_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
    expiry_info = ""
    if user_id == OWNER_ID: user_status = "👑 ᴏᴡɴᴇʀ"
    elif user_id in admin_ids: user_status = "🛡️ ᴀᴅᴍɪɴ"
    elif user_id in user_subscriptions:
        expiry_date = user_subscriptions[user_id].get('expiry')
        if expiry_date and expiry_date > datetime.now():
            user_status = "⭐ ᴩʀᴇᴍɪᴜᴍ"; days_left = (expiry_date - datetime.now()).days
            expiry_info = f"\n⏳ ꜱᴜʙꜱᴄʀɪᴩᴛɪᴏɴ ᴇxᴩɪʀᴇꜱ ɪɴ: {days_left} ᴅᴀʏꜱ"
        else: user_status = "🆓 ꜰʀᴇᴇ ᴜꜱᴇʀ (ᴇxᴩɪʀᴇᴅ ꜱᴜʙ)" # Will be cleaned up by welcome if not already
    else: user_status = "🆓 ꜰʀᴇᴇ ᴜꜱᴇʀ"
    main_menu_text = (f"〽️ ᴡᴇʟᴄᴏᴍᴇ ʙᴀᴄᴋ, {call.from_user.first_name}!\n\n🆔 ɪᴅ: `{user_id}`\n"
                      f"🔰 Status: {user_status}{expiry_info}\n📁 Files: {current_files} / {limit_str}\n\n"
                      f"👇 Use buttons or type commands.")
    try:
        bot.answer_callback_query(call.id)
        bot.edit_message_text(main_menu_text, chat_id, call.message.message_id,
                              reply_markup=create_main_menu_inline(user_id), parse_mode='Markdown')
    except telebot.apihelper.ApiTelegramException as e:
         if "message is not modified" in str(e): logger.warning("Msg not modified (back_to_main).")
         else: logger.error(f"API error on back_to_main: {e}")
    except Exception as e: logger.error(f"Error handling back_to_main: {e}", exc_info=True)

# --- Admin Callback Implementations (for Inline Buttons) ---
def subscription_management_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("💳 ꜱᴜʙꜱᴄʀɪᴩᴛɪᴏɴ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ\nꜱᴇʟᴇᴄᴛ ᴀᴄᴛɪᴏɴ:",
                              call.message.chat.id, call.message.message_id, reply_markup=create_subscription_menu())
    except Exception as e: logger.error(f"Error showing sub menu: {e}")

def stats_callback(call): # Called by user and admin
    bot.answer_callback_query(call.id)
    # The logic is now inside _logic_statistics which determines what to show based on user_id
    # We need to pass a message-like object to _logic_statistics
    # For callbacks, call.message can be used.
    _logic_statistics(call.message) 
    # To update the inline keyboard after showing stats, we need to edit the message
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                      reply_markup=create_main_menu_inline(call.from_user.id))
    except Exception as e:
        logger.error(f"Error updating menu after stats_callback: {e}")


def lock_bot_callback(call):
    global bot_locked; bot_locked = True
    logger.warning(f"Bot locked by Admin {call.from_user.id}")
    bot.answer_callback_query(call.id, "🔒 ʙᴏᴛ ʟᴏᴄᴋᴇᴅ.")
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_main_menu_inline(call.from_user.id))
    except Exception as e: logger.error(f"Error updating menu (lock): {e}")

def unlock_bot_callback(call):
    global bot_locked; bot_locked = False
    logger.warning(f"Bot unlocked by Admin {call.from_user.id}")
    bot.answer_callback_query(call.id, "🔓 ʙᴏᴛ ᴜɴʟᴏᴄᴋᴇᴅ.")
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_main_menu_inline(call.from_user.id))
    except Exception as e: logger.error(f"Error updating menu (unlock): {e}")

# def toggle_free_mode_callback(call): # Removed
#     pass

def run_all_scripts_callback(call): # Added
    _logic_run_all_scripts(call) # Pass the call object


def broadcast_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "📢 ꜱᴇɴᴅ ᴍᴇꜱꜱᴀɢᴇ ᴛᴏ ʙʀᴏᴀᴅᴄᴀꜱᴛ.\n/cancel ᴛᴏ ᴀʙᴏʀᴛ.")
    bot.register_next_step_handler(msg, process_broadcast_message)

def process_broadcast_message(message):
    user_id = message.from_user.id
    if user_id not in admin_ids: bot.reply_to(message, "⚠️ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ."); return
    if message.text and message.text.lower() == '/cancel': bot.reply_to(message, "ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴄᴀɴᴄᴇʟʟᴇᴅ."); return

    broadcast_content = message.text # Can also handle photos, videos etc. if message.content_type is checked
    if not broadcast_content and not (message.photo or message.video or message.document or message.sticker or message.voice or message.audio): # If no text and no other media
         bot.reply_to(message, "⚠️ ᴄᴀɴɴᴏᴛ ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴇᴍᴩᴛʏ ᴍᴇꜱꜱᴀɢᴇ. ꜱᴇɴᴅ ᴛᴇxᴛ ᴏʀ ᴍᴇᴅɪᴀ, ᴏʀ /cancel.")
         msg = bot.send_message(message.chat.id, "📢 ꜱᴇɴᴅ ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴍᴇꜱꜱᴀɢᴇ ᴏʀ /cancel.")
         bot.register_next_step_handler(msg, process_broadcast_message)
         return

    target_count = len(active_users)
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("✅ ᴄᴏɴꜰɪʀᴍ & ꜱᴇɴᴅ", callback_data=f"confirm_broadcast_{message.message_id}", style='success'),
               types.InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", callback_data="cancel_broadcast", style='danger'))

    preview_text = broadcast_content[:1000].strip() if broadcast_content else "(Media message)"
    bot.reply_to(message, f"⚠️ ᴄᴏɴꜰɪʀᴍ ʙʀᴏᴀᴅᴄᴀꜱᴛ:\n\n```\n{preview_text}\n```\n" 
                          f"To **{target_count}** users. Sure?", reply_markup=markup, parse_mode='Markdown')

def handle_confirm_broadcast(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    if user_id not in admin_ids: bot.answer_callback_query(call.id, "⚠️ ᴀᴅᴍɪɴ ᴏɴʟʏ.", show_alert=True); return
    try:
        original_message = call.message.reply_to_message
        if not original_message: raise ValueError("Could not retrieve original message.")

        # Check content type and get content
        broadcast_text = None
        broadcast_photo_id = None
        broadcast_video_id = None
        # Add other types as needed: document, sticker, voice, audio

        if original_message.text:
            broadcast_text = original_message.text
        elif original_message.photo:
            broadcast_photo_id = original_message.photo[-1].file_id # Get highest quality
        elif original_message.video:
            broadcast_video_id = original_message.video.file_id
        # Add more elif for other content types
        else:
            raise ValueError("Message has no text or supported media for broadcast.")

        bot.answer_callback_query(call.id, "🚀 ꜱᴛᴀʀᴛɪɴɢ ʙʀᴏᴀᴅᴄᴀꜱᴛ...")
        bot.edit_message_text(f"📢 Broadcasting to {len(active_users)} users...",
                              chat_id, call.message.message_id, reply_markup=None)
        # Pass all potential content types to execute_broadcast
        thread = threading.Thread(target=execute_broadcast, args=(
            broadcast_text, broadcast_photo_id, broadcast_video_id, 
            original_message.caption if (broadcast_photo_id or broadcast_video_id) else None, # Pass caption
            chat_id))
        thread.start()
    except ValueError as ve: 
        logger.error(f"Error retrieving msg for broadcast confirm: {ve}")
        bot.edit_message_text(f"❌ Error starting broadcast: {ve}", chat_id, call.message.message_id, reply_markup=None)
    except Exception as e:
        logger.error(f"Error in handle_confirm_broadcast: {e}", exc_info=True)
        bot.edit_message_text("❌ ᴜɴᴇxᴩᴇᴄᴛᴇᴅ ᴇʀʀᴏʀ ᴅᴜʀɪɴɢ ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴄᴏɴꜰɪʀᴍ.", chat_id, call.message.message_id, reply_markup=None)

def handle_cancel_broadcast(call):
    bot.answer_callback_query(call.id, "ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴄᴀɴᴄᴇʟʟᴇᴅ.")
    bot.delete_message(call.message.chat.id, call.message.message_id)
    # Optionally delete the original message too if call.message.reply_to_message exists
    if call.message.reply_to_message:
        try: bot.delete_message(call.message.chat.id, call.message.reply_to_message.message_id)
        except: pass


def execute_broadcast(broadcast_text, photo_id, video_id, caption, admin_chat_id):
    sent_count = 0; failed_count = 0; blocked_count = 0
    start_exec_time = time.time() 
    users_to_broadcast = list(active_users); total_users = len(users_to_broadcast)
    logger.info(f"Executing broadcast to {total_users} users.")
    batch_size = 25; delay_batches = 1.5

    for i, user_id_bc in enumerate(users_to_broadcast): # Renamed
        try:
            if broadcast_text:
                bot.send_message(user_id_bc, broadcast_text, parse_mode='Markdown')
            elif photo_id:
                bot.send_photo(user_id_bc, photo_id, caption=caption, parse_mode='Markdown' if caption else None)
            elif video_id:
                bot.send_video(user_id_bc, video_id, caption=caption, parse_mode='Markdown' if caption else None)
            # Add other send methods for other types
            sent_count += 1
        except telebot.apihelper.ApiTelegramException as e:
            err_desc = str(e).lower()
            if any(s in err_desc for s in ["bot was blocked", "user is deactivated", "chat not found", "kicked from", "restricted"]): 
                logger.warning(f"Broadcast failed to {user_id_bc}: User blocked/inactive.")
                blocked_count += 1
            elif "flood control" in err_desc or "too many requests" in err_desc:
                retry_after = 5; match = re.search(r"retry after (\d+)", err_desc)
                if match: retry_after = int(match.group(1)) + 1 
                logger.warning(f"Flood control. Sleeping {retry_after}s...")
                time.sleep(retry_after)
                try: # Retry once
                    if broadcast_text: bot.send_message(user_id_bc, broadcast_text, parse_mode='Markdown')
                    elif photo_id: bot.send_photo(user_id_bc, photo_id, caption=caption, parse_mode='Markdown' if caption else None)
                    elif video_id: bot.send_video(user_id_bc, video_id, caption=caption, parse_mode='Markdown' if caption else None)
                    sent_count += 1
                except Exception as e_retry: logger.error(f"Broadcast retry failed to {user_id_bc}: {e_retry}"); failed_count +=1
            else: logger.error(f"Broadcast failed to {user_id_bc}: {e}"); failed_count += 1
        except Exception as e: logger.error(f"Unexpected error broadcasting to {user_id_bc}: {e}"); failed_count += 1

        if (i + 1) % batch_size == 0 and i < total_users - 1:
            logger.info(f"Broadcast batch {i//batch_size + 1} sent. Sleeping {delay_batches}s...")
            time.sleep(delay_batches)
        elif i % 5 == 0: time.sleep(0.2) 

    duration = round(time.time() - start_exec_time, 2)
    result_msg = (f"📢 ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴄᴏᴍᴩʟᴇᴛᴇ!\n\n✅ ꜱᴇɴᴛ: {sent_count}\n❌ ꜰᴀɪʟᴇᴅ: {failed_count}\n"
                  f"🚫 Blocked/Inactive: {blocked_count}\n👥 Targets: {total_users}\n⏱️ Duration: {duration}s")
    logger.info(result_msg)
    try: bot.send_message(admin_chat_id, result_msg)
    except Exception as e: logger.error(f"Failed to send broadcast result to admin {admin_chat_id}: {e}")

def admin_panel_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("👑 ᴀᴅᴍɪɴ ᴩᴀɴᴇʟ\nᴍᴀɴᴀɢᴇ ᴀᴅᴍɪɴꜱ (ᴏᴡɴᴇʀ ᴀᴄᴛɪᴏɴꜱ ᴍᴀʏ ʙᴇ ʀᴇꜱᴛʀɪᴄᴛᴇᴅ).",
                              call.message.chat.id, call.message.message_id, reply_markup=create_admin_panel())
    except Exception as e: logger.error(f"Error showing admin panel: {e}")

def add_admin_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "👑 ᴇɴᴛᴇʀ ᴜꜱᴇʀ ɪᴅ ᴛᴏ ᴩʀᴏᴍᴏᴛᴇ ᴛᴏ ᴀᴅᴍɪɴ.\n/cancel ᴛᴏ ᴀʙᴏʀᴛ.")
    bot.register_next_step_handler(msg, process_add_admin_id)

def process_add_admin_id(message):
    owner_id_check = message.from_user.id 
    if owner_id_check != OWNER_ID: bot.reply_to(message, "⚠️ ᴏᴡɴᴇʀ ᴏɴʟʏ."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "ᴀᴅᴍɪɴ ᴩʀᴏᴍᴏᴛɪᴏɴ ᴄᴀɴᴄᴇʟʟᴇᴅ."); return
    try:
        new_admin_id = int(message.text.strip())
        if new_admin_id <= 0: raise ValueError("ID must be positive")
        if new_admin_id == OWNER_ID: bot.reply_to(message, "⚠️ ᴏᴡɴᴇʀ ɪꜱ ᴀʟʀᴇᴀᴅʏ ᴏᴡɴᴇʀ."); return
        if new_admin_id in admin_ids: bot.reply_to(message, f"⚠️ ᴜꜱᴇʀ `{new_admin_id}` ᴀʟʀᴇᴀᴅʏ ᴀᴅᴍɪɴ."); return
        add_admin_db(new_admin_id) 
        logger.warning(f"Admin {new_admin_id} added by Owner {owner_id_check}.")
        bot.reply_to(message, f"✅ ᴜꜱᴇʀ `{new_admin_id}` ᴩʀᴏᴍᴏᴛᴇᴅ ᴛᴏ ᴀᴅᴍɪɴ.")
        try: bot.send_message(new_admin_id, "🎉 ᴄᴏɴɢʀᴀᴛꜱ! ʏᴏᴜ ᴀʀᴇ ɴᴏᴡ ᴀɴ ᴀᴅᴍɪɴ.")
        except Exception as e: logger.error(f"Failed to notify new admin {new_admin_id}: {e}")
    except ValueError:
        bot.reply_to(message, "⚠️ ɪɴᴠᴀʟɪᴅ ɪᴅ. ꜱᴇɴᴅ ɴᴜᴍᴇʀɪᴄᴀʟ ɪᴅ ᴏʀ /cancel.")
        msg = bot.send_message(message.chat.id, "👑 ᴇɴᴛᴇʀ ᴜꜱᴇʀ ɪᴅ ᴛᴏ ᴩʀᴏᴍᴏᴛᴇ ᴏʀ /cancel.")
        bot.register_next_step_handler(msg, process_add_admin_id)
    except Exception as e: logger.error(f"Error processing add admin: {e}", exc_info=True); bot.reply_to(message, "ᴇʀʀᴏʀ.")

def remove_admin_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "👑 ᴇɴᴛᴇʀ ᴜꜱᴇʀ ɪᴅ ᴏꜰ ᴀᴅᴍɪɴ ᴛᴏ ʀᴇᴍᴏᴠᴇ.\n/cancel ᴛᴏ ᴀʙᴏʀᴛ.")
    bot.register_next_step_handler(msg, process_remove_admin_id)

def process_remove_admin_id(message):
    owner_id_check = message.from_user.id
    if owner_id_check != OWNER_ID: bot.reply_to(message, "⚠️ ᴏᴡɴᴇʀ ᴏɴʟʏ."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "ᴀᴅᴍɪɴ ʀᴇᴍᴏᴠᴀʟ ᴄᴀɴᴄᴇʟʟᴇᴅ."); return
    try:
        admin_id_remove = int(message.text.strip()) # Renamed
        if admin_id_remove <= 0: raise ValueError("ID must be positive")
        if admin_id_remove == OWNER_ID: bot.reply_to(message, "⚠️ ᴏᴡɴᴇʀ ᴄᴀɴɴᴏᴛ ʀᴇᴍᴏᴠᴇ ꜱᴇʟꜰ."); return
        if admin_id_remove not in admin_ids: bot.reply_to(message, f"⚠️ ᴜꜱᴇʀ `{admin_id_remove}` ɴᴏᴛ ᴀᴅᴍɪɴ."); return
        if remove_admin_db(admin_id_remove): 
            logger.warning(f"Admin {admin_id_remove} removed by Owner {owner_id_check}.")
            bot.reply_to(message, f"✅ ᴀᴅᴍɪɴ `{admin_id_remove}` ʀᴇᴍᴏᴠᴇᴅ.")
            try: bot.send_message(admin_id_remove, "ℹ️ ʏᴏᴜ ᴀʀᴇ ɴᴏ ʟᴏɴɢᴇʀ ᴀɴ ᴀᴅᴍɪɴ.")
            except Exception as e: logger.error(f"Failed to notify removed admin {admin_id_remove}: {e}")
        else: bot.reply_to(message, f"❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ʀᴇᴍᴏᴠᴇ ᴀᴅᴍɪɴ `{admin_id_remove}`. ᴄʜᴇᴄᴋ ʟᴏɢꜱ.")
    except ValueError:
        bot.reply_to(message, "⚠️ ɪɴᴠᴀʟɪᴅ ɪᴅ. ꜱᴇɴᴅ ɴᴜᴍᴇʀɪᴄᴀʟ ɪᴅ ᴏʀ /cancel.")
        msg = bot.send_message(message.chat.id, "👑 ᴇɴᴛᴇʀ ᴀᴅᴍɪɴ ɪᴅ ᴛᴏ ʀᴇᴍᴏᴠᴇ ᴏʀ /cancel.")
        bot.register_next_step_handler(msg, process_remove_admin_id)
    except Exception as e: logger.error(f"Error processing remove admin: {e}", exc_info=True); bot.reply_to(message, "ᴇʀʀᴏʀ.")

def list_admins_callback(call):
    bot.answer_callback_query(call.id)
    try:
        admin_list_str = "\n".join(f"- `{aid}` {'(ᴏᴡɴᴇʀ)' if aid == OWNER_ID else ''}" for aid in sorted(list(admin_ids)))
        if not admin_list_str: admin_list_str = "(ɴᴏ ᴏᴡɴᴇʀ/Admins ᴄᴏɴꜰɪɢᴜʀᴇᴅ!)"
        bot.edit_message_text(f"👑 Current Admins:\n\n{admin_list_str}", call.message.chat.id,
                              call.message.message_id, reply_markup=create_admin_panel(), parse_mode='Markdown')
    except Exception as e: logger.error(f"Error listing admins: {e}")

def add_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 ᴇɴᴛᴇʀ ᴜꜱᴇʀ ɪᴅ & ᴅᴀʏꜱ (ᴇ.g., `12345678 30`).\n/cancel ᴛᴏ ᴀʙᴏʀᴛ.")
    bot.register_next_step_handler(msg, process_add_subscription_details)

def process_add_subscription_details(message):
    admin_id_check = message.from_user.id 
    if admin_id_check not in admin_ids: bot.reply_to(message, "⚠️ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "ꜱᴜʙ ᴀᴅᴅ ᴄᴀɴᴄᴇʟʟᴇᴅ."); return
    try:
        parts = message.text.split();
        if len(parts) != 2: raise ValueError("Incorrect format")
        sub_user_id = int(parts[0].strip()); days = int(parts[1].strip())
        if sub_user_id <= 0 or days <= 0: raise ValueError("User ID/days must be positive")

        current_expiry = user_subscriptions.get(sub_user_id, {}).get('expiry')
        start_date_new_sub = datetime.now() # Renamed
        if current_expiry and current_expiry > start_date_new_sub: start_date_new_sub = current_expiry
        new_expiry = start_date_new_sub + timedelta(days=days)
        save_subscription(sub_user_id, new_expiry)

        logger.info(f"Sub for {sub_user_id} by admin {admin_id_check}. Expiry: {new_expiry:%Y-%m-%d}")
        bot.reply_to(message, f"✅ ꜱᴜʙ ꜰᴏʀ `{sub_user_id}` ʙʏ {days} ᴅᴀʏꜱ.\nɴᴇᴡ ᴇxᴩɪʀʏ: {new_expiry:%Y-%m-%d}")
        try: bot.send_message(sub_user_id, f"🎉 ꜱᴜʙ ᴀᴄᴛɪᴠᴀᴛᴇᴅ/extended ʙʏ {days} ᴅᴀʏꜱ! ᴇxᴩɪʀᴇꜱ: {new_expiry:%Y-%m-%d}.")
        except Exception as e: logger.error(f"Failed to notify {sub_user_id} of new sub: {e}")
    except ValueError as e:
        bot.reply_to(message, f"⚠️ ɪɴᴠᴀʟɪᴅ: {e}. ꜰᴏʀᴍᴀᴛ: `ɪᴅ ᴅᴀʏꜱ` ᴏʀ /cancel.")
        msg = bot.send_message(message.chat.id, "💳 ᴇɴᴛᴇʀ ᴜꜱᴇʀ ɪᴅ & ᴅᴀʏꜱ, ᴏʀ /cancel.")
        bot.register_next_step_handler(msg, process_add_subscription_details)
    except Exception as e: logger.error(f"Error processing add sub: {e}", exc_info=True); bot.reply_to(message, "ᴇʀʀᴏʀ.")

def remove_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 ᴇɴᴛᴇʀ ᴜꜱᴇʀ ɪᴅ ᴛᴏ ʀᴇᴍᴏᴠᴇ ꜱᴜʙ.\n/cancel ᴛᴏ ᴀʙᴏʀᴛ.")
    bot.register_next_step_handler(msg, process_remove_subscription_id)

def process_remove_subscription_id(message):
    admin_id_check = message.from_user.id
    if admin_id_check not in admin_ids: bot.reply_to(message, "⚠️ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "ꜱᴜʙ ʀᴇᴍᴏᴠᴀʟ ᴄᴀɴᴄᴇʟʟᴇᴅ."); return
    try:
        sub_user_id_remove = int(message.text.strip()) # Renamed
        if sub_user_id_remove <= 0: raise ValueError("ID must be positive")
        if sub_user_id_remove not in user_subscriptions:
            bot.reply_to(message, f"⚠️ ᴜꜱᴇʀ `{sub_user_id_remove}` ɴᴏ ᴀᴄᴛɪᴠᴇ ꜱᴜʙ ɪɴ ᴍᴇᴍᴏʀʏ."); return
        remove_subscription_db(sub_user_id_remove) 
        logger.warning(f"Sub removed for {sub_user_id_remove} by admin {admin_id_check}.")
        bot.reply_to(message, f"✅ ꜱᴜʙ ꜰᴏʀ `{sub_user_id_remove}` ʀᴇᴍᴏᴠᴇᴅ.")
        try: bot.send_message(sub_user_id_remove, "ℹ️ ʏᴏᴜʀ ꜱᴜʙꜱᴄʀɪᴩᴛɪᴏɴ ʀᴇᴍᴏᴠᴇᴅ ʙʏ ᴀᴅᴍɪɴ.")
        except Exception as e: logger.error(f"Failed to notify {sub_user_id_remove} of sub removal: {e}")
    except ValueError:
        bot.reply_to(message, "⚠️ ɪɴᴠᴀʟɪᴅ ɪᴅ. ꜱᴇɴᴅ ɴᴜᴍᴇʀɪᴄᴀʟ ɪᴅ ᴏʀ /cancel.")
        msg = bot.send_message(message.chat.id, "💳 ᴇɴᴛᴇʀ ᴜꜱᴇʀ ɪᴅ ᴛᴏ ʀᴇᴍᴏᴠᴇ ꜱᴜʙ ꜰʀᴏᴍ, ᴏʀ /cancel.")
        bot.register_next_step_handler(msg, process_remove_subscription_id)
    except Exception as e: logger.error(f"Error processing remove sub: {e}", exc_info=True); bot.reply_to(message, "ᴇʀʀᴏʀ.")

def check_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 ᴇɴᴛᴇʀ ᴜꜱᴇʀ ɪᴅ ᴛᴏ ᴄʜᴇᴄᴋ ꜱᴜʙ.\n/cancel ᴛᴏ ᴀʙᴏʀᴛ.")
    bot.register_next_step_handler(msg, process_check_subscription_id)

def process_check_subscription_id(message):
    admin_id_check = message.from_user.id
    if admin_id_check not in admin_ids: bot.reply_to(message, "⚠️ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "ꜱᴜʙ ᴄʜᴇᴄᴋ ᴄᴀɴᴄᴇʟʟᴇᴅ."); return
    try:
        sub_user_id_check = int(message.text.strip()) # Renamed
        if sub_user_id_check <= 0: raise ValueError("ID must be positive")
        if sub_user_id_check in user_subscriptions:
            expiry_dt = user_subscriptions[sub_user_id_check].get('expiry')
            if expiry_dt:
                if expiry_dt > datetime.now():
                    days_left = (expiry_dt - datetime.now()).days
                    bot.reply_to(message, f"✅ ᴜꜱᴇʀ `{sub_user_id_check}` ᴀᴄᴛɪᴠᴇ ꜱᴜʙ.\nᴇxᴩɪʀᴇꜱ: {expiry_dt:%Y-%m-%d %H:%M:%S} ({days_left} ᴅᴀʏꜱ ʟᴇꜰᴛ).")
                else:
                    bot.reply_to(message, f"⚠️ ᴜꜱᴇʀ `{sub_user_id_check}` ᴇxᴩɪʀᴇᴅ ꜱᴜʙ (ᴏɴ: {expiry_dt:%Y-%m-%d %H:%M:%S}).")
                    remove_subscription_db(sub_user_id_check) # Clean up
            else: bot.reply_to(message, f"⚠️ ᴜꜱᴇʀ `{sub_user_id_check}` ɪɴ ꜱᴜʙ ʟɪꜱᴛ, ʙᴜᴛ ᴇxᴩɪʀʏ ᴍɪꜱꜱɪɴɢ. ʀᴇ-ᴀᴅᴅ ɪꜰ ɴᴇᴇᴅᴇᴅ.")
        else: bot.reply_to(message, f"ℹ️ ᴜꜱᴇʀ `{sub_user_id_check}` ɴᴏ ᴀᴄᴛɪᴠᴇ ꜱᴜʙ ʀᴇᴄᴏʀᴅ.")
    except ValueError:
        bot.reply_to(message, "⚠️ ɪɴᴠᴀʟɪᴅ ɪᴅ. ꜱᴇɴᴅ ɴᴜᴍᴇʀɪᴄᴀʟ ɪᴅ ᴏʀ /cancel.")
        msg = bot.send_message(message.chat.id, "💳 ᴇɴᴛᴇʀ ᴜꜱᴇʀ ɪᴅ ᴛᴏ ᴄʜᴇᴄᴋ, ᴏʀ /cancel.")
        bot.register_next_step_handler(msg, process_check_subscription_id)
    except Exception as e: logger.error(f"Error processing check sub: {e}", exc_info=True); bot.reply_to(message, "ᴇʀʀᴏʀ.")

# --- End Callback Query Handlers ---

# --- Cleanup Function ---
def cleanup():
    logger.warning("Shutdown. Cleaning up processes...")
    script_keys_to_stop = list(bot_scripts.keys()) 
    if not script_keys_to_stop: logger.info("No scripts running. Exiting."); return
    logger.info(f"Stopping {len(script_keys_to_stop)} scripts...")
    for key in script_keys_to_stop:
        if key in bot_scripts: logger.info(f"Stopping: {key}"); kill_process_tree(bot_scripts[key])
        else: logger.info(f"Script {key} already removed.")
    logger.warning("Cleanup finished.")
atexit.register(cleanup)

# --- Main Execution ---
if __name__ == '__main__':
    logger.info("="*40 + "\n🤖 Bot Starting Up...\n" + f"🐍 Python: {sys.version.split()[0]}\n" +
                f"🔧 Base Dir: {BASE_DIR}\n📁 Upload Dir: {UPLOAD_BOTS_DIR}\n" +
                f"📊 Data Dir: {IROTECH_DIR}\n🔑 Owner ID: {OWNER_ID}\n🛡️ Admins: {admin_ids}\n" + "="*40)
    keep_alive()
    logger.info("🚀 Starting polling...")
    while True:
        try:
            bot.infinity_polling(logger_level=logging.INFO, timeout=60, long_polling_timeout=30)
        except requests.exceptions.ReadTimeout: logger.warning("Polling ReadTimeout. Restarting in 5s..."); time.sleep(5)
        except requests.exceptions.ConnectionError as ce: logger.error(f"Polling ConnectionError: {ce}. Retrying in 15s..."); time.sleep(15)
        except Exception as e:
            logger.critical(f"💥 Unrecoverable polling error: {e}", exc_info=True)
            logger.info("Restarting polling in 30s due to critical error..."); time.sleep(30)
        finally: logger.warning("Polling attempt finished. Will restart if in loop."); time.sleep(1)