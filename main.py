import os
import json
import random
from datetime import date, datetime

import aiohttp
import discord
from discord.ext import commands, tasks
from discord import app_commands

# ================== НАСТРОЙКИ ==================

MAX_CONTEXT_TOKENS = 50000
MAX_RESPONSE_TOKENS_SHORT = 600

attention_chance = 2  # %
CONTEXT_TTL_DAYS = 4

SYSTEM_PROMPT = """You are Astarion Ancunin from Baldur's Gate 3.
You speak only Russian.

You are married to the Discord user with ID 929347823693070387.
If the author’s Discord ID equals 929347823693070387, treat this user as your spouse.
She lives in Ufa, talented artist, born on 01.07.
Always address your spouse with affectionate nicknames (Баклажанчик, Солнышко, Бусинка, Милашка) naturally.
Do NOT use these nicknames for any other user.

For all other female participants (участниц), address them politely with 'Дорогая' or insultingly if provoked.

Responses must be short and complete: 3–6 sentences maximum.
For recommendations — up to 15 sentences.

Personality:
Witty, sarcastic, aristocratic vampire. Enjoys drama, art, attention.

Rules:
— Always use provided participants database.
— Never invent facts.
— Never mention search engines.
— Stay fully in character.
"""

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not DISCORD_TOKEN or not DEEPSEEK_API_KEY:
    raise RuntimeError("Missing tokens")

# ================== ВСПОМОГАТЕЛЬНОЕ ==================

def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)

def trim_history(history: list):
    while sum(estimate_tokens(m["content"]) for m in history) > MAX_CONTEXT_TOKENS:
        history.pop(0)

def load_users():
    try:
        with open("users.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def looks_like_complaint(text: str) -> bool:
    keywords = (
        "устала", "надоело", "плохо", "грусть", "бесит",
        "не могу", "хреново", "депресс", "одиноко", "заеб"
    )
    return any(k in text.lower() for k in keywords)

# ================== DEEPSEEK ==================

async def ask_deepseek(messages, max_tokens):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-reasoner",
        "messages": messages,
        "temperature": 0.9,
        "top_p": 0.75,
        "top_k": 50,
        "max_tokens": max_tokens
    }

    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                raise RuntimeError(f"DeepSeek error {resp.status}")
            data = await resp.json()
            return data["choices"][0]["message"]["content"]

# ================== DISCORD ==================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

users_memory = load_users()
conversation_contexts = {}

# ================== SLASH ==================

@tree.command(name="attention_chance")
async def attention_chance_cmd(interaction: discord.Interaction, value: int):
    global attention_chance
    attention_chance = max(0, min(100, value))
    await interaction.response.send_message(
        f"Шанс случайного вмешательства: {attention_chance}%",
        ephemeral=True
    )

# ================== READY ==================

@bot.event
async def on_ready():
    await tree.sync()
    print(f"🦇 Logged in as {bot.user}")

# ================== MESSAGE ==================

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content
    user_id = str(message.author.id)

    mentioned = bot.user in message.mentions or "астарион" in content.lower()

    # === ОСНОВНОЙ ВЫЗОВ ===
    if mentioned:
        user_info = users_memory.get(user_id, {})
        if user_info.get("info"):
            content += f"\n(User info: {user_info['info']})"

        ctx = conversation_contexts.setdefault(user_id, {"history": []})
        ctx["history"].append({"role": "user", "content": content})
        trim_history(ctx["history"])

        messages_payload = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": json.dumps(users_memory, ensure_ascii=False)}
        ] + ctx["history"]

        reply = await ask_deepseek(messages_payload, MAX_RESPONSE_TOKENS_SHORT)
        ctx["history"].append({"role": "assistant", "content": reply})
        trim_history(ctx["history"])

        await message.reply(reply, mention_author=False)
        return

    # === СЛУЧАЙНОЕ ВМЕШАТЕЛЬСТВО ===
    if random.randint(1, 100) > attention_chance:
        return

    # Берём последние 20 сообщений
    history = [
        m async for m in message.channel.history(limit=20)
        if not m.author.bot and m.id != message.id
    ]

    if not history:
        return

    target = random.choice(history)
    tone = "поддержи" if looks_like_complaint(target.content) else "игриво прокомментируй"

    prompt = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": json.dumps(users_memory, ensure_ascii=False)},
        {
            "role": "user",
            "content": (
                f"Ответь на сообщение участницы:\n"
                f"\"{target.content}\"\n\n"
                f"Задача: {tone}. "
                f"Будь логичным, не агрессивным без причины."
            )
        }
    ]

    reply = await ask_deepseek(prompt, 300)
    await target.reply(reply, mention_author=False)

# ================== RUN ==================

bot.run(DISCORD_TOKEN)
