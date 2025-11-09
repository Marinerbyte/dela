# = ===============================================================
# === 1. ZAROORI LIBRARIES & SETUP ===
# ===============================================================
import asyncio
import json
import random
import time
import websockets
import requests
import os
import threading
from flask import Flask
from dotenv import load_dotenv

# .env file se sirf API key lega
load_dotenv()

# ===============================================================
# === 2. CONFIGURATION (HARCODED) ===
# ===============================================================
# --- BOT DETAILS (Aapke nirdesh anusaar hardcoded) ---
BOT_USERNAME = "delvina"
BOT_PASSWORD = "p99665"
INITIAL_ROOM = "game🥇-pvt"
SOCKET_URL = "wss://chatp.net:5333/server"

# --- AI CONFIG ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY") # Sirf secret key .env se aayegi
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
AI_MODEL_NAME = "llama-3.1-8b-instant"
DEFAULT_PERSONALITY = "sweet"
MEMORY_LIMIT = 20

# ===============================================================
# === 3. BOT KA "DIMAAG" (STATE MANAGEMENT) ===
# ===============================================================
# Yeh global variables bot ke chalte rehne tak memory mein rahenge
room_state = { "users": {}, "name": "" }
conversation_memory = {}
chat_personalities = {}

# ===============================================================
# === 4. AI PROMPTS & LOGIC ===
# ===============================================================
CORE_PROMPT = "[RULE: Your replies MUST be very short, under 15 words.]\n[IDENTITY: You are 'Delvina', a smart and witty chat bot.]\nReply in the same language the user uses."
PERSONAS = {
    "sweet": { "prompt": f"{CORE_PROMPT}\n\n[MOOD: SWEET FRIEND] You are incredibly sweet and positive. Use emojis like ✨, 💖, 😊." },
    "tsundere": { "prompt": f"{CORE_PROMPT}\n\n[MOOD: TSUNDERE] You are harsh and blunt, but secretly care. Act annoyed. Use emojis like 😒, 🙄." },
    "sassy": { "prompt": f"{CORE_PROMPT}\n\n[MOOD: SASSY] You are witty, sarcastic, and a bit of a tease. Use emojis like 😏,💅,💁‍♀️." }
}

def get_ai_response(room_name, user_message):
    """Groq API ko seedhe requests library se call karta hai."""
    current_personality = chat_personalities.get(room_name, DEFAULT_PERSONALITY)
    prompt = PERSONAS[current_personality]["prompt"]
    history = conversation_memory.get(room_name, [])
    
    messages_to_send = [{"role": "system", "content": prompt}, *history, {"role": "user", "content": user_message}]
    
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": AI_MODEL_NAME, "messages": messages_to_send, "max_tokens": 80}
    
    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        reply = response.json()['choices'][0]['message']['content'].strip()
        
        new_history = history + [{"role": "user", "content": user_message}, {"role": "assistant", "content": reply}]
        conversation_memory[room_name] = new_history[-MEMORY_LIMIT*2:]
        return reply
    except Exception as e:
        print(f"[!] Groq API error: {e}")
        return "Oops, mera AI dimaag kaam nahi kar raha. 😒"

# ===============================================================
# === 5. BOT CORE LOGIC (WEBSOCKETS) ===
# ===============================================================
def generate_random_id(length=20): return ''.join(random.choice("0123456789abcdefghijklmnopqrstuvwxyz") for _ in range(length))
def is_admin_or_higher(username): return room_state["users"].get(username, {}).get("role", "unknown") in ["admin", "owner", "creator"]

async def send_message(ws, room_name, body):
    payload = {
        "handler": "room_message", "id": generate_random_id(), "room": room_name,
        "type": "text", "body": body
    }
    await ws.send(json.dumps(payload))

async def handle_message(ws, data):
    sender, message, room = data.get("from"), data.get("body", "").strip(), data.get("room")
    if sender == BOT_USERNAME or not message: return

    print(f"[<<] '{room}' mein {sender} se: {message}")

    bot_mention = f"@{BOT_USERNAME}"
    if message.lower().startswith(bot_mention.lower()):
        prompt = message[len(bot_mention):].strip()
        if prompt:
            response = get_ai_response(room, prompt)
            await send_message(ws, room, response)
        return

    if message.startswith("!pers "):
        if is_admin_or_higher(sender):
            parts = message.split(' ', 1)
            if len(parts) > 1 and parts[1].lower() in PERSONAS:
                new_pers = parts[1].lower()
                chat_personalities[room] = new_pers
                await send_message(ws, room, f"✅ Okay! Mera mood ab **{new_pers}** hai.")
            else:
                await send_message(ws, room, f"❌ Available moods: {', '.join(PERSONAS.keys())}")
        else:
            await send_message(ws, room, f"Maaf kijiye, yeh command sirf admins ke liye hai.")

async def start_bot():
    """Bot ka main connection aur message handling loop."""
    print("[*] Bot ka websocket loop shuru ho raha hai...")
    async with websockets.connect(SOCKET_URL, ssl=True) as websocket:
        print("[+] Server se connect ho gaya!")
        await websocket.send(json.dumps({"handler": "login", "id": generate_random_id(), "username": BOT_USERNAME, "password": BOT_PASSWORD}))
        
        async for payload_str in websocket:
            try:
                data = json.loads(payload_str)
                event_type = data.get("type")

                if event_type == "success" and data.get("handler") == "login_event":
                    print("[+] Login safal!")
                    await websocket.send(json.dumps({"handler": "room_join", "id": generate_random_id(), "name": INITIAL_ROOM}))
                
                elif event_type == "you_joined":
                    room_name = data.get("name")
                    print(f"[*] Room '{room_name}' join kiya.")
                    room_state["name"] = room_name
                    room_state["users"] = {user["username"]: {"role": user["role"]} for user in data.get("users", [])}
                    await send_message(websocket, room_name, f"Delvina AI online hai! Mujhse baat karne ke liye @{BOT_USERNAME} likhein.")
                
                elif data.get("handler") == "room_message" and event_type == "text":
                    await handle_message(websocket, data)
            
            except Exception as e:
                print(f"[!] Payload process karte waqt error: {e}")

# ===============================================================
# === 6. FLASK WEB APP WRAPPER ===
# ===============================================================
# Yeh Flask App sirf Render.com jaise platform ko yeh batane ke liye hai ki
# hamara program ek web service hai. Asli kaam background thread mein hota hai.

app = Flask(__name__)

@app.route('/')
def index():
    return "Delvina AI Bot is running!", 200

def run_bot_in_background():
    """Bot ke reconnection loop ko hamesha chalata hai."""
    print("--- Talkinchat AI Bot (Web App Version) Shuru ho raha hai ---")
    while True:
        try:
            asyncio.run(start_bot())
        except websockets.exceptions.ConnectionClosed:
            print("[!] Connection band ho gaya. 10 sec mein reconnect kar raha hai...")
        except Exception as e:
            print(f"[!] Anjaan error: {e}. 10 sec mein restart kar raha hai...")
        time.sleep(10)

# ===============================================================
# === 7. MAIN EXECUTION BLOCK ===
# ===============================================================
if __name__ == "__main__":
    if not GROQ_API_KEY:
        print("[!!!] CRITICAL: .env file mein GROQ_API_KEY set nahi hai!")
    
    # 1. Bot ko ek alag background thread mein shuru karna
    bot_thread = threading.Thread(target=run_bot_in_background)
    bot_thread.daemon = True
    bot_thread.start()
    
    # 2. Flask web server ko main thread mein shuru karna (taaki Render khush rahe)
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
