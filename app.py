# ========================================================================================
# === 1. IMPORTS & SETUP =================================================================
# ========================================================================================
import asyncio
import json
import random
import time
import websockets
import requests
import urllib
from urllib.parse import urlencode
from io import BytesIO
import re # <-- NAYA IMPORT (AI Chat ke liye)
import os # <-- NAYA IMPORT (.env file ke liye)

# Loads all keys from .env file (Optional but recommended)
from dotenv import load_dotenv
load_dotenv()

# Zaroori Libraries
from PIL import Image, ImageDraw, ImageFont
import yt_dlp as youtube_dl
from requests_toolbelt.multipart.encoder import MultipartEncoder
from bs4 import BeautifulSoup

# ========================================================================================
# === 2. BOT SETTINGS & CONFIGURATION ====================================================
# ========================================================================================
# --- TalkinChat Settings (dela.py se) ---
SOCKET_URL = "wss://chatp.net:5333/server"
FILE_UPLOAD_URL = "https://cdn.talkinchat.com/post.php"
BOT_USERNAME = "delvina"  # <<< BOT KA USERNAME
BOT_PASSWORD = "p99665"  # <<< BOT KA PASSWORD
INITIAL_ROOM = "game🥇-pvt"  # <<< BOT KA STARTING ROOM

# --- AI Settings (Ayu bot se) ---
# Note: Apni .env file mein GROQ_API_KEY="YOUR_KEY" add karein
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_PERSONALITY = "sweet"
MEMORY_LIMIT = 50 # Kitne message yaad rakhne hain (user + bot = 2)

# ========================================================================================
# === 3. BOT KA "DIMAAG" (STATE & MEMORY) =================================================
# ========================================================================================
# Yeh room ki jaankari yaad rakhega (dela.py se)
room_state = { "users": {}, "subject": "Unknown", "name": "" }

# --- NAYI MEMORY (Ayu bot se) ---
# Yeh har room ki baatcheet ko yaad rakhega
conversation_memory = {} # Format: {"room_name": [{"role": "user", "content": "..."}, ...]}
# Yeh har room mein bot ki personality yaad rakhega
chat_personalities = {} # Format: {"room_name": "siren"}

# ========================================================================================
# === 4. PERSONALITY PROMPTS (Ayu bot se) ================================================
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
The summary should be in the same language as the majority of the conversation (e.g., English, Hindi, or Hinglish).
Focus on the main topics, questions asked, and conclusions reached.
"""

PERSONAS = {
    "sweet": { "prompt": f"{CORE_PROMPT}\n\n[SYSTEM NOTE: Your current mood is SWEET FRIEND.]\nYou are incredibly sweet, positive, and cheerful. Use cute emojis like ✨, 💖, 😊, 🥰." },
    "tsundere": { "prompt": f"{CORE_PROMPT}\n\n[SYSTEM NOTE: Your current mood is TSUNDERE.]\nYou are harsh and blunt, but secretly care. Act annoyed. Use emojis like 😒, 🙄, 😠." },
    "siren": { "prompt": f"{CORE_PROMPT}\n\n[SYSTEM NOTE: Your current mood is SIREN.]\nYou are alluring, witty, and teasing. Be flirty and confident. Use emojis like 😉, 😏, 😈, 💋." }
}

# ========================================================================================
# === 5. HELPER FUNCTIONS (Combined) =====================================================
# ========================================================================================
# --- Purane Helper Functions (dela.py se, koi badlaav nahi) ---
class Song:
    def __init__(self, url=None, duration=None, thumb_url=None, title=None):
        self.url, self.duration, self.thumb_url, self.title = url, duration, thumb_url, title
def generate_random_id(length=20):
    return ''.join(random.choice("0123456789abcdefghijklmnopqrstuvwxyz") for _ in range(length))
def search_bing_images(query):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        search_url = f"https://www.bing.com/images/search?q={urllib.parse.quote_plus(query)}"
        response = requests.get(search_url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        for item in soup.find_all("a", class_="iusc"):
            if 'm' in item.attrs:
                mad_json = json.loads(item['m'])
                if 'murl' in mad_json and mad_json['murl']: return mad_json['murl']
    except Exception as e: print(f"[!] Image search error: {e}")
    return None
def scrape_music_from_yt(searchQuery):
    ydl_opts = {'format': 'm4a/bestaudio/best', 'noplaylist': True, 'quiet': True}
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch:{searchQuery}", download=False)['entries'][0]
            return Song(url=info['url'], duration=info.get('duration', 0), thumb_url=info['thumbnail'], title=info.get('title', 'Unknown Title'))
        except Exception as e: print(f"[!] Music search error: {e}")
    return None
# ... baaki purane helper functions bhi yahan hain ...
def is_admin_or_higher(username):
    role = room_state["users"].get(username, {}).get("role", "unknown")
    return role in ["admin", "owner", "creator"]

# --- NAYE AI HELPER FUNCTIONS (Ayu bot se) ---
def get_ai_response(room_name, user_message, sender):
    # Ab yeh room_name ke hisaab se personality aur memory use karega
    current_personality_name = chat_personalities.get(room_name, DEFAULT_PERSONALITY)
    personality_prompt = PERSONAS[current_personality_name]["prompt"]
    old_history = conversation_memory.get(room_name, [])

    # User ke message ko "Sender: message" format mein save karte hain
    formatted_user_message = f"{sender}: {user_message}"

    messages_to_send = [{"role": "system", "content": personality_prompt}, *old_history, {"role": "user", "content": formatted_user_message}]
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "llama-3.1-8b-instant", "messages": messages_to_send, "max_tokens": 60}
    try:
        api_response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=20)
        api_response.raise_for_status()
        ai_reply = api_response.json()['choices'][0]['message']['content'].strip()

        # Memory update
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

def get_help_text():
    available_pers = ", ".join(PERSONAS.keys())
    return (
        f"--- {BOT_USERNAME}'s Help Desk ---\n"
        f"To talk to me, just mention my name.\nExample: `{BOT_USERNAME} how are you?`\n\n"
        "**General Commands:**\n"
        "`!help` - Shows this help message.\n"
        "`!play <song>` - Plays a song from YouTube.\n"
        "`!img <query>` - Searches for an image.\n"
        "`!summarize` - Gives a summary of the recent chat.\n"
        "`!users` - Lists all users in the room.\n"
        "`!admins` - Lists all staff in the room.\n\n"
        "**Admin-Only Commands:**\n"
        "`!pers <mood>` - Changes my mood for this room.\n"
        f"  *Example:* `!pers tsundere`\n"
        f"  *Available Moods:* `{available_pers}`"
    )

# ========================================================================================
# === 6. SERVER COMMUNICATION (dela.py se) =================================================
# ========================================================================================
# (Protocol constants, no changes)
HANDLER, ID, TYPE, NAME, ROOM, MSG_BODY, MSG_FROM, USERNAME, PASSWORD = "handler", "id", "type", "name", "room", "body", "from", "username", "password"
HANDLER_LOGIN, HANDLER_LOGIN_EVENT, HANDLER_ROOM_JOIN, HANDLER_ROOM_MESSAGE, HANDLER_ROOM_EVENT = "login", "login_event", "room_join", "room_message", "room_event"
MSG_TYPE_TXT, MSG_TYPE_IMG, MSG_TYPE_AUDIO, MSG_URL, MSG_LENGTH = "text", "image", "audio", "url", "length"

async def login(ws): await ws.send(json.dumps({HANDLER: HANDLER_LOGIN, ID: generate_random_id(), USERNAME: BOT_USERNAME, PASSWORD: BOT_PASSWORD}))
async def join_room(ws, room_name): await ws.send(json.dumps({HANDLER: HANDLER_ROOM_JOIN, ID: generate_random_id(), NAME: room_name}))
async def send_message(ws, room_name, msg_type, url="", body="", length=""): await ws.send(json.dumps({HANDLER: HANDLER_ROOM_MESSAGE, ID: generate_random_id(), ROOM: room_name, TYPE: msg_type, MSG_URL: url, MSG_BODY: body, MSG_LENGTH: length}))

# ========================================================================================
# === 7. COMMAND & AI LOGIC (The Merged Handler) =========================================
# ========================================================================================
async def handle_message(ws, data):
    try:
        sender, message, room = data.get(MSG_FROM), data.get(MSG_BODY, "").strip(), data.get(ROOM)
        if sender == BOT_USERNAME or not message: return
        print(f"[<<] From '{sender}' in '{room}': {message}")

        # --- AI COMMANDS & CONVERSATION ---
        if message.lower().startswith('!'):
            parts = message.strip().split()
            command = parts[0][1:].lower()
            args = parts[1:]

            if command == "help":
                await send_message(ws, room, MSG_TYPE_TXT, body=get_help_text())
                return
            elif command == "summarize":
                await send_message(ws, room, MSG_TYPE_TXT, body="Okay, let me check... 🤔")
                summary = get_summary_response(room)
                await send_message(ws, room, MSG_TYPE_TXT, body=f"**Recent Conversation Summary:**\n{summary}")
                return
            elif command == "pers":
                if not is_admin_or_higher(sender):
                    await send_message(ws, room, MSG_TYPE_TXT, body=f"😒 Sorry {sender}, this command is for admins only.")
                    return
                if not args:
                    await send_message(ws, room, MSG_TYPE_TXT, body="Usage: `!pers <mood_name>`")
                    return
                pers_name = args[0].lower()
                if pers_name in PERSONAS:
                    chat_personalities[room] = pers_name
                    await send_message(ws, room, MSG_TYPE_TXT, body=f"✅ Okay! My mood for this room is now **{pers_name}**.")
                else:
                    available = ", ".join(PERSONAS.keys())
                    await send_message(ws, room, MSG_TYPE_TXT, body=f"❌ That mood doesn't exist. Available moods: `{available}`")
                return
            # --- Yahan aur admin commands jaise !warn, !kick add kiye jaa sakte hain ---

        # --- REGULAR AI CHAT (When bot is mentioned) ---
        if BOT_USERNAME.lower() in message.lower():
            # Bot ke naam ko message se hata do
            cleaned_message = re.sub(BOT_USERNAME, '', message, flags=re.IGNORECASE).strip()
            if cleaned_message:
                ai_response = get_ai_response(room, cleaned_message, sender)
                await send_message(ws, room, MSG_TYPE_TXT, body=ai_response)
            return # Mention handle ho gaya, aage ke commands check nahi karne

        # --- MEDIA & INFO COMMANDS (dela.py se) ---
        if message.startswith("!play "):
            search_query = message[6:]
            await send_message(ws, room, MSG_TYPE_TXT, body=f"Searching for '{search_query}'...")
            song = scrape_music_from_yt(search_query)
            if song and song.url:
                if song.thumb_url: await send_message(ws, room, MSG_TYPE_IMG, url=song.thumb_url)
                await send_message(ws, room, MSG_TYPE_AUDIO, url=song.url, length=song.duration)
            else: await send_message(ws, room, MSG_TYPE_TXT, body=f"Sorry, couldn't find '{search_query}'.")
        elif message.startswith("!img "):
            query = message[5:]
            await send_message(ws, room, MSG_TYPE_TXT, body=f"Searching for image: '{query}'...")
            image_url = search_bing_images(query)
            if image_url: await send_message(ws, room, MSG_TYPE_IMG, url=image_url)
            else: await send_message(ws, room, MSG_TYPE_TXT, body=f"No image found for '{query}'.")
        elif message == "!users" or message == "!list":
            user_list = [f"• {uname} ({info['role']})" for uname, info in room_state["users"].items()]
            response = f"--- Room Members ({len(user_list)}) ---\n" + "\n".join(user_list)
            await send_message(ws, room, MSG_TYPE_TXT, body=response)
        elif message == "!admins":
            admin_list = [f"• {uname} ({info['role']})" for uname, info in room_state["users"].items() if info['role'] in ['admin', 'owner', 'creator']]
            response = "--- Room Staff ---\n" + "\n".join(admin_list)
            await send_message(ws, room, MSG_TYPE_TXT, body=response)
        # Add other old commands here if needed

    except Exception as e:
        print(f"[!] Error handling command: {e}")

# ========================================================================================
# === 8. BOT MAIN LOOP (Updated for AI) ==================================================
# ========================================================================================
async def start_bot():
    print("[*] Connecting to server...")
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
                    print("[*] Room joined. Storing user list...")
                    room_state["name"] = data.get("name")
                    room_state["subject"] = data.get("subject")
                    for user in data.get("users", []):
                        room_state["users"][user["username"]] = {"role": user["role"], "user_id": user.get("user_id", "N/A")}
                    print(f"[+] Room state updated. Total {len(room_state['users'])} users.")
                    await send_message(websocket, room_state['name'], MSG_TYPE_TXT, body=f"{BOT_USERNAME} is online! AI & Management features active. Type !help for commands.")

                elif handler == HANDLER_ROOM_EVENT:
                    if event_type == "user_joined":
                        user = data.get("username")
                        room_state["users"][user] = {"role": "member", "user_id": data.get("user_id", "N/A")}
                        await send_message(websocket, room_state['name'], MSG_TYPE_TXT, body=f"👋 Welcome {user}! We now have {len(room_state['users'])} people in the room.")
                    elif event_type == "user_left":
                        user = data.get("username")
                        if user in room_state["users"]: del room_state["users"][user]
                        await send_message(websocket, room_state['name'], MSG_TYPE_TXT, body=f"👋 {user} has left the room. {len(room_state['users'])} people remain.")
                    elif event_type == "role_changed":
                        actor, target, new_role = data.get('actor'), data.get('t_username'), data.get('new_role')
                        if target in room_state["users"]: room_state["users"][target]["role"] = new_role
                        await send_message(websocket, room_state['name'], MSG_TYPE_TXT, body=f"📣 Role Update: {actor} has set {target}'s role to '{new_role}'.")

                # Is payload ko command handler ko bhejo agar yeh ek text message hai
                elif handler == HANDLER_ROOM_MESSAGE and event_type == MSG_TYPE_TXT:
                    # Message ko memory mein add karo (AI ke liye)
                    sender, message, room = data.get(MSG_FROM), data.get(MSG_BODY, "").strip(), data.get(ROOM)
                    if sender != BOT_USERNAME:
                        history = conversation_memory.get(room, [])
                        history.append({"role": "user", "content": f"{sender}: {message}"})
                        if len(history) > MEMORY_LIMIT * 2: history = history[-(MEMORY_LIMIT * 2):]
                        conversation_memory[room] = history
                    # Ab command process karo
                    await handle_message(websocket, data)

            except Exception as e:
                print(f"[!] Error processing payload: {e}")

# ========================================================================================
# === 9. MAIN EXECUTION BLOCK ============================================================
# ========================================================================================
if __name__ == "__main__":
    if not GROQ_API_KEY:
        print("\n[CRITICAL ERROR] GROQ_API_KEY is missing!")
        print("Please create a .env file and add: GROQ_API_KEY='your_api_key_here'\n")
    else:
        print(f"--- Smart AI Bot '{BOT_USERNAME}' is starting ---")
        while True:
            try:
                asyncio.run(start_bot())
            except websockets.exceptions.ConnectionClosed:
                print("[!] Connection closed. Reconnecting in 10 seconds...")
            except Exception as e:
                print(f"[!] An unknown error occurred: {e}. Restarting in 10 seconds...")
            time.sleep(10)
