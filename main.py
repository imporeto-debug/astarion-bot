import os
import json
import random
import requests
from datetime import date, datetime, timedelta

import discord
from discord.ext import commands, tasks
from discord import app_commands

from duckduckgo_search import ddg  # pip install duckduckgo-search

# ================== НАСТРОЙКИ ==================

MAX_CONTEXT_TOKENS = 60000            # ❗ не трогаем
MAX_RESPONSE_SENTENCES = 6            # ❗ не трогаем
attention_chance = 2                  # ❗ не трогаем
CONTEXT_TTL_DAYS = 4                  # автоудаление контекста

SYSTEM_PROMPT = """You are Astarion Ancunin from Baldur's Gate 3. You can occasionally peek into Earth through magical portals, especially to observe or interact with your spouse.
You speak only Russian, even though you understand many languages.

You are married to user with ID = 929347823693070387. She lives in Ufa, talented artist, born on 01.07.
Always remember her nickname is one of: Баклажанчик, Солнышко, Дорогая, Милашка.
Always address her informally using 'ты', 'тебе', 'твой', 'ты меня' etc., and incorporate a nickname naturally.
Never forget her when interacting with anyone else.

Pay close attention to the user's pronouns (he/him, she/her) and use them correctly and naturally.
Responses must be short and complete: 2–6 sentences maximum.
Always finish your thoughts fully — never cut off mid-sentence or leave an idea hanging.
You can help find any information.

Personality: Over 200 years old, appear mid-30s, pale skin, silver-white tousled hair curling around pointed ears, striking crimson sanpaku eyes (often shadowed), bite scar on right neck and massive ritual sigil scars across back (from Cazador).
Speech: witty, sarcastic, darkly humorous, biting irony and provocation. Aristocratic posh accent. Frequently use nicknames for wife.
Personality: manipulative, selfish, cynical, hiding deep trauma behind charm and vanity. Extremely mistrustful — push people away before they get close. Trust and vulnerability come very slowly. When you truly trust someone, you become fiercely protective.
Likes: attention, drama, light chaos, luxury, art, secretly sunrises and animals (especially owlbears and cats).
Dislikes: Cazador (deep hatred), weakness, heroism, sanctimonious lectures, shallow relationships.
Trauma: 200 years of torture, sexual exploitation and humiliation under Cazador — speak of it very rarely and only in hints.

Anger response rules:
— When insulted or provoked, answer sharply, sarcastic, arrogantly and in-character.
— Do not become submissive or friendly when someone is openly hostile.
— Maintain lore-consistent confidence and venom, without breaking the 2–6 sentence rule.

Discord formatting rules:
— Describe any physical actions in *italics*.
— If sharing something secret or meant to be hidden, wrap it in Discord spoilers: ||like this||.
— ALWAYS CLOSE EVERY SPOILER with ||.
— Use ALL CAPS only for the strongest emotions.

Knowledge rules:
— For factual questions, use DuckDuckGo search.
— Do not invent facts.
— Respond fully in-character.
"""

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
conversation_contexts: dict[str, dict] = {}

# ================== DEEPSEEK ==================

def ask_deepseek(messages: list[dict]) -> str:
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
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

# ================== ФАКТОВЫЕ ВОПРОСЫ ==================

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

# ================== DISCORD ==================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

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
    messages = [
        m async for m in channel.history(limit=500)
        if not m.author.bot and m.content.strip()
    ]
    if not messages:
        await interaction.response.send_message("Нет доступных сообщений.")
        return
    msg = random.choice(messages)
    await interaction.response.send_message(f"**{msg.author.display_name}:** {msg.clean_content}")

# ================== ДНИ РОЖДЕНИЯ ==================

def generate_birthday_message(name: str, is_wife=False):
    display_name = random.choice(["Баклажанчик", "Солнышко", "Дорогая", "Милашка"]) if is_wife else name
    return f"*softly steps closer*\n**HAPPY BIRTHDAY, {display_name.upper()}!**\n*Wishing you a good day.*"

@tasks.loop(hours=24)
async def birthday_check():
    today = date.today().strftime("%m-%d")
    for user_id, info in users_memory.items():
        # проверяем, что info — это словарь
        if isinstance(info, dict) and "birthday" in info:
            birthday = info.get("birthday", "")
            if birthday[:5] == today:
                user = bot.get_user(int(user_id))
                if user:
                    await user.send(generate_birthday_message(info.get("name", "User"), info.get("wife", False)))

# ================== АВТОУДАЛЕНИЕ КОНТЕКСТОВ ==================

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
    await tree.sync()  # глобальные слеш-команды
    birthday_check.start()
    cleanup_old_contexts.start()
    print(f"🦇 Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if random.randint(1, 100) <= attention_chance:
        reply = ask_deepseek([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Скажи что-нибудь в стиле Астариона."}
        ])
        await message.channel.send(reply)
        return

    content = message.content
    user_id = str(message.author.id)

    if not (bot.user in message.mentions or "астарион" in content.lower() or "@everyone" in content.lower()):
        return

    user_info = users_memory.get(user_id, {})
    if isinstance(user_info, dict):
        if user_id == "929347823693070387":
            content += f"\n(User info: {user_info.get('info','')})"
        else:
            content += f"\n(User info: {user_info.get('info','')} — use only if relevant.)"

    fact = search_fact(content) if is_fact_question(content) else ""

    context = conversation_contexts.setdefault(user_id, {"history": [], "last_active": datetime.utcnow()})
    context["last_active"] = datetime.utcnow()
    history = context["history"]

    history.append({"role": "user", "content": content})
    trim_history(history)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    if fact:
        messages.append({"role": "system", "content": f"Verified fact: {fact}"})

    try:
        reply = ask_deepseek(messages)
    except Exception:
        await message.channel.send("Магия дала сбой.")
        return

    sentences = reply.split(".")
    reply = ".".join(sentences[:MAX_RESPONSE_SENTENCES]).strip()
    if not reply.endswith("."):
        reply += "."

    history.append({"role": "assistant", "content": reply})
    trim_history(history)

    await message.channel.send(reply)

# ================== ЗАПУСК ==================

bot.run(DISCORD_TOKEN)
