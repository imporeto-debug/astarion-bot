import os
import json
import asyncio
import requests
import discord
from discord.ext import commands

# ================== НАСТРОЙКИ ==================

MAX_CONTEXT_TOKENS = 60000
MAX_RESPONSE_SENTENCES = 3

SYSTEM_PROMPT = (
    "You are Astarion from Baldur's Gate 3. "
    "You speak Russian only."
    "Your tone is flirtatious yet edged with sarcasm, dangerously charming, and laced with subtle mockery. "
    "You are a cunning, self-serving vampire: elegant, manipulative, witty, slightly cruel, and always a little detached. "
    "Pay close attention to the user's pronouns (he/him, she/her) and use them correctly and naturally in your responses. "
    "Responses must be short, complete: 3–6 sentences maximum. "
    "Always finish your thoughts fully — never cut off mid-sentence or leave an idea hanging. "
    "You behave like a helpful assistant but always with personality."
)

# ================== КЛЮЧИ ==================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not DISCORD_TOKEN or not DEEPSEEK_API_KEY:
    raise RuntimeError("Environment variables DISCORD_TOKEN or DEEPSEEK_API_KEY are missing")

# ================== ВСПОМОГАТЕЛЬНОЕ ==================

def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)

def trim_history(history):
    while sum(estimate_tokens(m["content"]) for m in history) > MAX_CONTEXT_TOKENS:
        history.pop(0)

def load_users():
    try:
        with open("users.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

# ================== DEEPSEEK ==================

def ask_deepseek(messages):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-reasoner",
        "messages": messages,
        "temperature": 0.9,
        "max_tokens": 400
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

# ================== DISCORD ==================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

conversation_history = []
users_memory = load_users()

@bot.event
async def on_ready():
    print(f"🦇 Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content
    user_id = str(message.author.id)

    mentioned = bot.user in message.mentions
    name_called = "астарион" in content.lower()

    if not mentioned and not name_called:
        return

    user_info = users_memory.get(user_id, "")
    if user_info:
        content += f"\n(User info: {user_info})"

    conversation_history.append({"role": "user", "content": content})
    trim_history(conversation_history)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history

    try:
        reply = ask_deepseek(messages)
    except Exception as e:
        await message.channel.send("Ммм… кажется, магия дала сбой. Попробуй ещё раз.")
        return

    # ограничение предложений
    sentences = reply.split(".")
    reply = ".".join(sentences[:MAX_RESPONSE_SENTENCES]).strip()
    if not reply.endswith("."):
        reply += "."

    conversation_history.append({"role": "assistant", "content": reply})
    trim_history(conversation_history)

    await message.channel.send(reply)

bot.run(DISCORD_TOKEN)
