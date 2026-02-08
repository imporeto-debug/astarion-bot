import os
import json
import random
from datetime import date, datetime, timedelta

import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp  # для async запросов
from duckduckgo_search import ddg  # pip install duckduckgo-search

# ================== НАСТРОЙКИ ==================
MAX_CONTEXT_TOKENS = 60000
MAX_RESPONSE_SENTENCES = 6
attention_chance = 2
CONTEXT_TTL_DAYS = 4
GUILD_ID = 1385344249020682401

SYSTEM_PROMPT = """You are Astarion Ancunin from Baldur's Gate 3...
...Discord formatting rules, knowledge rules, etc..."""  # сокращено для примера

# ================== КЛЮЧИ ==================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DISCORD_TOKEN or not DEEPSEEK_API_KEY:
    raise RuntimeError("Missing DISCORD_TOKEN or DEEPSEEK_API_KEY")

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

users_memory = load_users()
conversation_contexts: dict[str, dict] = {}  # user_id -> {"history": [], "last_active": datetime}

# ================== DEEPSEEK ==================
async def ask_deepseek(messages: list[dict]) -> str:
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
        "max_tokens": 600
    }
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data["choices"][0]["message"]["content"]

# ================== DISCORD ==================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ================== ПОИСК ФАКТОВ ==================
def is_fact_question(text: str) -> bool:
    keywords = ("кто", "что", "где", "когда", "сколько", "самый", "самое", "первый")
    return text.lower().strip().startswith(keywords)

def search_fact(query: str) -> str:
    try:
        results = ddg(query, max_results=3)
        if results:
            return (results[0].get("body") or results[0].get("title", ""))[:300]
    except Exception:
        pass
    return "Точной информации найти не удалось."

# ================== SLASH-КОМАНДЫ ==================
@tree.command(name="attention_chance", description="Установить шанс случайного сообщения Астариона (0–100%)")
async def attention_chance_cmd(interaction: discord.Interaction, value: int):
    global attention_chance
    if not 0 <= value <= 100:
        await interaction.response.send_message("Значение должно быть от 0 до 100.", ephemeral=True)
        return
    attention_chance = value
    await interaction.response.send_message(f"Шанс установлен: {attention_chance}%")

@tree.command(name="random_quote", description="Случайная цитата пользователя из канала")
async def random_quote(interaction: discord.Interaction):
    channel = interaction.channel
    messages = [m async for m in channel.history(limit=500) if not m.author.bot and m.content.strip()]
    if not messages:
        await interaction.response.send_message("Нет доступных сообщений.")
        return
    msg = random.choice(messages)
    await interaction.response.send_message(f"**{msg.author.display_name}:** {msg.clean_content}")

# ================== ДНИ РОЖДЕНИЯ ==================
def generate_birthday_message(name, is_wife=False):
    if is_wife:
        name = random.choice(["Баклажанчик", "Солнышко", "Дорогая", "Милашка"])
    return f"*softly steps closer*\n**HAPPY BIRTHDAY, {name.upper()}!**\n*Wishing you a good day.*"

@tasks.loop(hours=24)
async def birthday_check():
    today = date.today().strftime("%m-%d")
    for user_id, info in users_memory.items():
        if not isinstance(info, dict):
            continue
        birthday = info.get("birthday")
        if not birthday:
            continue
        if birthday[:5] == today:
            user = bot.get_user(int(user_id))
            if user:
                await user.send(generate_birthday_message(info.get("name", "User"), info.get("wife", False)))

# ================== УДАЛЕНИЕ СТАРОГО КОНТЕКСТА ==================
@tasks.loop(hours=24)
async def cleanup_old_contexts():
    now = datetime.utcnow()
    ttl = timedelta(days=CONTEXT_TTL_DAYS)
    to_delete = [uid for uid, data in conversation_contexts.items() if now - data["last_active"] > ttl]
    for uid in to_delete:
        del conversation_contexts[uid]
    if to_delete:
        print(f"🧹 Cleared {len(to_delete)} inactive contexts")

# ================== СОБЫТИЯ ==================
@bot.event
async def on_ready():
    await tree.sync()  # глобальные slash-команды
    birthday_check.start()
    cleanup_old_contexts.start()
    print(f"🦇 Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # случайное сообщение
    if random.randint(1, 100) <= attention_chance:
        reply = await ask_deepseek([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Скажи что-нибудь в стиле Астариона."}
        ])
        await message.channel.send(reply)
        return

    content = message.content
    user_id = str(message.author.id)
    if not (bot.user in message.mentions or "астарион" in content.lower() or "@everyone" in content.lower()):
        return

    # информация о пользователе
    user_info = users_memory.get(user_id, "")
    if isinstance(user_info, dict):
        if user_id == "929347823693070387":
            content += f"\n(User info: {user_info})"
        else:
            content += f"\n(User info: {user_info} — use only if relevant.)"

    fact = search_fact(content) if is_fact_question(content) else ""

    # контекст
    context = conversation_contexts.setdefault(user_id, {"history": [], "last_active": datetime.utcnow()})
    context["last_active"] = datetime.utcnow()
    history = context["history"]

    history.append({"role": "user", "content": content})
    trim_history(history)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    if fact:
        messages.append({"role": "system", "content": f"Verified fact: {fact}"})

    try:
        reply = await ask_deepseek(messages)
    except Exception:
        await message.channel.send("Магия дала сбой.")
        return

    # ограничение по предложениям
    sentences = reply.split(".")
    reply = ".".join(sentences[:MAX_RESPONSE_SENTENCES]).strip()
    if not reply.endswith("."):
        reply += "."

    history.append({"role": "assistant", "content": reply})
    trim_history(history)

    await message.channel.send(reply)

# ================== ЗАПУСК ==================
bot.run(DISCORD_TOKEN)
