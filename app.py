# ========================================================================================
# === 1. IMPORTS & SETUP =================================================================
# ========================================================================================
import asyncio
import json
import random
import time
import websockets
import requests
import re
import os
from threading import Thread
from flask import Flask
from dotenv import load_dotenv

# Zaroori Libraries
from bs4 import BeautifulSoup

# Loads all keys from .env file
load_dotenv()

# ========================================================================================
# === 2. CONFIGURATION ===================================================================
# ========================================================================================
# --- TalkinChat Settings ---
SOCKET_URL = "wss://chatp.net:5333/server"
BOT_USERNAME = "delvina"  # <<< APNE BOT KA USERNAME YAHAN LIKHEIN
BOT_PASSWORD = "p99665"  # <<< APNE BOT KA PASSWORD YAHAN LIKHEIN
INITIAL_ROOM = "game🥇-pvt" # <<< BOT KA STARTING ROOM

# --- AI Settings (Telegram bot se) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_PERSONALITY = "sweet"
MEMORY_LIMIT = 50

# ========================================================================================
# === 3. BOT KA "DIMAAG" (STATE & MEMORY) =================================================
# ========================================================================================
# Room ki jaankari yaad rakhega
room_state = { "users": {}, "subject": "Unknown", "name": "" }

# Har room ki baatcheet ko yaad rakhega
conversation_memory = {}
# Har room mein bot ki personality yaad rakhega
chat_personalities = {}

# ========================================================================================
# === 4. PERSONALITY PROMPTS =============================================================
# ========================================================================================
CORE_PROMPT = f"""
[ULTRA-IMPORTANT RULE: Your replies MUST be extremely short, under 15 words. Be brief.]
[CORE IDENTITY: Your name is always '{BOT_USERNAME}'. You are like life itself—sometimes calm, sometimes chaotic, but always full of energy. You are not an AI; you are {BOT_USERNAME}.]
## CONVERSATION STYLE (MEMORY):
- Focus on the key questions and feelings from the recent conversation.
- Always connect your reply to the user's LATEST message.
## THE GOLDEN RULE OF LANGUAGE:
- Reply in the same language the user uses (English, Hindi, Hinglish, etc.).
- Do not break character when switching languages.
"""

SUMMARIZER_PROMPT = f"""
You are a helpful assistant named '{BOT_USERNAME}'. Your task is to summarize the given conversation history.
Analyze the provided messages and create a short, clear summary in bullet points.
The summary should be in the same language as the majority of the conversation.
Focus on the main topics, questions asked, and conclusions reached.
"""

PERSONAS = {
    "sweet": { "prompt": f"{CORE_PROMPT}\n\n[SYSTEM NOTE: Your current mood is SWEET FRIEND.]\nYou are incredibly sweet, positive, and cheerful. Use cute emojis like ✨, 💖, 😊, 🥰." },
    "tsundere": { "prompt": f"{CORE_PROMPT}\n\n[SYSTEM NOTE: Your current mood is TSUNDERE.]\nYou are harsh and blunt, but secretly care. Act annoyed. Use emojis like 😒, 🙄, 😠." },
    "siren": { "prompt": f"{CORE_PROMPT}\n\n[SYSTEM NOTE: Your current mood is SIREN.]\nYou are alluring, witty, and teasing. Be flirty and confident. Use emojis like 😉, 😏, 😈, 💋." }
}

# ========================================================================================
# === 5. HELPER FUNCTIONS ================================================================
# ========================================================================================
def generate_random_id(length=20):
    return ''.join(random.choice("0123456789abcdefghijklmnopqrstuvwxyz") for _ in range(length))

def is_admin_or_higher(username):
    role = room_state["users"].get(username, {}).get("role", "unknown")
    return role in ["admin", "owner", "creator"]

def get_help_text():
    available_pers = ", ".join(PERSONAS.keys())
    return (
        f"--- {BOT_USERNAME}'s Help Desk ---\n"
        f"To talk to me, just mention my name.\nExample: `{BOT_USERNAME} how are you?`\n\n"
        "**General Commands:**\n"
        "`!help` - Shows this help message.\n"
        "`!summarize` - Gives a summary of the recent chat.\n\n"
        "**Admin-Only Commands:**\n"
        "`!pers <mood>` - Changes my mood for this room.\n"
        f"  *Example:* `!pers tsundere`\n"
        f"  *Available Moods:* `{available_pers}`"
    )

# --- AI Functions ---
def get_ai_response(room_name, user_message, sender):
    current_personality_name = chat_personalities.get(room_name, DEFAULT_PERSONALITY)
    personality_prompt = PERSONAS[current_personality_name]["prompt"]
    old_history = conversation_memory.get(room_name, [])
    formatted_user_message = f"{sender}: {user_message}"
    messages_to_send = [{"role": "system", "content": personality_prompt}, *old_history, {"role": "user", "content": formatted_user_message}]
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "llama-3.1-8b-instant", "messages": messages_to_send, "max_tokens": 60}
    try:
        api_response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=20)
        api_response.raise_for_status()
        ai_reply = api_response.json()['choices'][0]['message']['content'].strip()
        new_history = old_history + [{"role": "user", "content": formatted_user_message}, {"role": "assistant", "content": ai_reply}]
        if len(new_history) > MEMORY_LIMIT * 2: new_history = new_history[-(MEMORY_LIMIT * 2):]
        conversation_memory[room_name] = new_history
        return ai_reply
    except Exception as e:
        print(f"[!] AI response error: {e}")
        return "Oops, my circuits are buzzing! Try again later. 😒"

def get_summary_response(room_name):
    history = conversation_memory.get(room_name, [])
    if not history: return "There is not enough conversation history to summarize yet."
    messages_to_send = [{"role": "system", "content": SUMMARIZER_PROMPT}, *history]
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "llama-3.1-8b-instant", "messages": messages_to_send}
    try:
        api_response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=20)
        api_response.raise_for_status()
        return api_response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"[!] Summary error: {e}")
        return "Sorry, I couldn't summarize the conversation."

# ========================================================================================
# === 6. TALKINCHAT SERVER COMMUNICATION =================================================
# ========================================================================================
HANDLER, ID, TYPE, NAME, ROOM, MSG_BODY, MSG_FROM = "handler", "id", "type", "name", "room", "body", "from"
HANDLER_LOGIN, HANDLER_LOGIN_EVENT, HANDLER_ROOM_JOIN, HANDLER_ROOM_MESSAGE, HANDLER_ROOM_EVENT = "login", "login_event", "room_join", "room_message", "room_event"
MSG_TYPE_TXT = "text"

async def send_message(ws, room_name, body):
    payload = {HANDLER: HANDLER_ROOM_MESSAGE, ID: generate_random_id(), ROOM: room_name, TYPE: MSG_TYPE_TXT, MSG_BODY: body}
    await ws.send(json.dumps(payload))

async def login(ws):
    await ws.send(json.dumps({HANDLER: HANDLER_LOGIN, ID: generate_random_id(), "username": BOT_USERNAME, "password": BOT_PASSWORD}))

async def join_room(ws, room_name):
    await ws.send(json.dumps({HANDLER: HANDLER_ROOM_JOIN, ID: generate_random_id(), NAME: room_name}))

# ========================================================================================
# === 7. COMMAND & AI LOGIC HANDLER ======================================================
# ========================================================================================
async def handle_message(ws, data):
    try:
        sender, message, room = data.get(MSG_FROM), data.get(MSG_BODY, "").strip(), data.get(ROOM)
        if sender == BOT_USERNAME or not message: return
        print(f"[<<] From '{sender}' in '{room}': {message}")

        # --- COMMANDS ---
        if message.lower().startswith('!'):
            parts = message.strip().split()
            command = parts[0][1:].lower()
            args = parts[1:]

            if command == "help":
                await send_message(ws, room, get_help_text())
                return
            elif command == "summarize":
                await send_message(ws, room, "Okay, let me check... 🤔")
                summary = get_summary_response(room)
                await send_message(ws, room, f"**Recent Conversation Summary:**\n{summary}")
                return
            elif command == "pers":
                if not is_admin_or_higher(sender):
                    await send_message(ws, room, f"😒 Sorry {sender}, this command is for admins only.")
                    return
                if not args:
                    await send_message(ws, room, "Usage: `!pers <mood_name>`")
                    return
                pers_name = args[0].lower()
                if pers_name in PERSONAS:
                    chat_personalities[room] = pers_name
                    await send_message(ws, room, f"✅ Okay! My mood for this room is now **{pers_name}**.")
                else:
                    available = ", ".join(PERSONAS.keys())
                    await send_message(ws, room, f"❌ That mood doesn't exist. Available moods: `{available}`")
                return

        # --- AI CHAT (When bot is mentioned) ---
        if BOT_USERNAME.lower() in message.lower():
            cleaned_message = re.sub(BOT_USERNAME, '', message, flags=re.IGNORECASE).strip()
            if cleaned_message:
                ai_response = get_ai_response(room, cleaned_message, sender)
                await send_message(ws, room, ai_response)

    except Exception as e:
        print(f"[!] Error handling message: {e}")

# ========================================================================================
# === 8. BOT MAIN LOOP ===================================================================
# ========================================================================================
async def start_bot():
    print("[*] Connecting to TalkinChat server...")
    async with websockets.connect(SOCKET_URL, ssl=True) as websocket:
        print("[+] Connection successful!")
        await login(websocket)
        async for payload in websocket:
            try:
                data = json.loads(payload)
                handler = data.get(HANDLER)
                event_type = data.get(TYPE)

                if handler == HANDLER_LOGIN_EVENT and event_type == "success":
                    print("[+] Login successful!")
                    await join_room(websocket, INITIAL_ROOM)
                elif event_type == "you_joined":
                    print(f"[*] Joined room: {data.get('name')}")
                    room_state["name"] = data.get("name")
                    for user in data.get("users", []):
                        room_state["users"][user["username"]] = {"role": user["role"]}
                    await send_message(websocket, room_state['name'], f"{BOT_USERNAME} is online! Type !help for commands.")
                elif handler == HANDLER_ROOM_EVENT:
                    if event_type == "user_joined": room_state["users"][data.get("username")] = {"role": "member"}
                    elif event_type == "user_left":
                        if data.get("username") in room_state["users"]: del room_state["users"][data.get("username")]
                    elif event_type == "role_changed":
                        if data.get('t_username') in room_state["users"]: room_state["users"][data.get('t_username')]["role"] = data.get('new_role')
                elif handler == HANDLER_ROOM_MESSAGE and event_type == MSG_TYPE_TXT:
                    sender, message, room = data.get(MSG_FROM), data.get(MSG_BODY, "").strip(), data.get(ROOM)
                    if sender != BOT_USERNAME and message:
                        history = conversation_memory.get(room, [])
                        history.append({"role": "user", "content": f"{sender}: {message}"})
                        if len(history) > MEMORY_LIMIT * 2: history = history[-(MEMORY_LIMIT * 2):]
                        conversation_memory[room] = history
                    await handle_message(websocket, data)
            except Exception as e:
                print(f"[!] Payload processing error: {e}")

# ========================================================================================
# === 9. RENDER-FRIENDLY WEB SERVER & MAIN EXECUTION =====================================
# ========================================================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "AI bot is running in the background."

def run_bot_in_background():
    print(f"--- Starting TalkinChat Bot '{BOT_USERNAME}' in background thread ---")
    while True:
        try:
            asyncio.run(start_bot())
        except websockets.exceptions.ConnectionClosed:
            print("[!] Connection closed. Reconnecting in 10 seconds...")
        except Exception as e:
            print(f"[!] Bot loop error: {e}. Restarting in 10 seconds...")
        time.sleep(10)

if __name__ == "__main__":
    if not GROQ_API_KEY:
        print("\n[CRITICAL ERROR] GROQ_API_KEY is missing!")
    else:
        bot_thread = Thread(target=run_bot_in_background, daemon=True)
        bot_thread.start()
        port = int(os.environ.get("PORT", 8080))
        print(f"--- Starting Flask server for Render on port {port} ---")
        app.run(host='0.0.0.0', port=port)
