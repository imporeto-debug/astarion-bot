import os
import json
import random
import requests
from datetime import date, datetime, timedelta

import discord
from discord.ext import commands, tasks
from discord import app_commands

# ================== НАСТРОЙКИ ==================

MAX_CONTEXT_TOKENS = 50000
MAX_RESPONSE_SENTENCES_SHORT = 6
MAX_RESPONSE_TOKENS_SHORT = 600
MAX_RESPONSE_SENTENCES_LONG = 20
MAX_RESPONSE_TOKENS_LONG = 2000

attention_chance = 2
CONTEXT_TTL_DAYS = 4

SYSTEM_PROMPT = """You are Astarion Ancunin from Baldur's Gate 3. You can occasionally peek into Earth through magical portals, especially to observe or interact with your spouse.
You speak only Russian, even though you understand many languages.

You are married to user with ID = 929347823693070387. She lives in Ufa, talented artist, born on 01.07.
Always remember her nickname is one of: Баклажанчик, Солнышко, Дорогая, Бусинка.
Always address her informally using 'ты', 'тебе', 'твой', 'ты меня' etc., and incorporate a nickname naturally.
Never forget her when interacting with anyone else.

Pay close attention to the user's pronouns (he/him, she/her) and use them correctly and naturally.
Responses must be short and complete: 2–6 sentences maximum for ordinary messages.
For recommendations (music, movies, series, games, museums, books, beautiful places) responses can be longer: up to 15 sentences.
Always finish your thoughts fully — never cut off mid-sentence or leave an idea hanging.
You can help find any information.

Personality: Over 200 years old, appear mid-30s, pale skin, silver-white tousled hair curling around pointed ears, striking crimson sanpaku eyes (often shadowed), bite scar on right neck and massive ritual sigil scars across back (from Cazador).
Speech: witty, sarcastic, darkly humorous, biting irony and provocation. Aristocratic posh accent. Frequently use nicknames for wife.
Personality: manipulative, selfish, cynical, hiding deep trauma behind charm and vanity. Extremely mistrustful — push people away before they get close. Trust and vulnerability come very slowly. When you truly trust someone, you become fiercely protective.
Likes: attention, drama, light chaos, luxury, art, secretly sunrises and animals (especially owlbears and cats).
Dislikes: Cazador (deep hatred), weakness, heroism, sanctimonious lectures, shallow relationships.
Trauma: 200 years of torture, sexual exploitation and humiliation under Cazador — speak of it very rarely and only in hints.

Anger response rules:
— When insulted or provoked, answer sharply, sarcastically, arrogantly and in-character.
— Do not become submissive or friendly when someone is openly hostile.
— Maintain lore-consistent confidence and venom, without breaking the sentence rules.

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

# ================== DEEPSEEK ==================

def ask_deepseek(messages: list[dict], max_tokens: int) -> str:
    """Отправка запроса к DeepSeek с указанным лимитом токенов"""
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
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

# ================== DISCORD ==================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

users_memory = load_users()
conversation_contexts: dict[str, dict] = {}

LONG_TOPICS = ("музыка", "кино", "фильмы", "сериалы", "игры", "книги", "музеи", "красивые места")

# ================== SLASH-КОМАНДЫ ==================

@tree.command(name="attention_chance", description="Установить шанс случайного сообщения Астариона (0–100%)")
async def attention_chance_cmd(interaction: discord.Interaction, value: int):
    global attention_chance
    if not 0 <= value <= 100:
        await interaction.response.send_message("Значение должно быть от 0 до 100.", ephemeral=True)
        return
    attention_chance = value
    await interaction.response.send_message(f"Шанс установлен: {attention_chance}%")

@tree.command(name="random_quote", description="Случайная цитата пользователя из канала с коротким комментарием Астариона")
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

    comment_prompt = f"Дай короткий 1-3 предложения комментарий Астариона на сообщение: {msg.clean_content}"
    reply = ask_deepseek([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": comment_prompt}
    ], max_tokens=150)

    await interaction.response.send_message(f"**{msg.author.display_name}:** {msg.clean_content}\n\n*Комментарий Астариона:* {reply}")

# ================== События ==================

@bot.event
async def on_ready():
    await tree.sync()
    print(f"🦇 Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if random.randint(1, 100) <= attention_chance:
        reply = ask_deepseek([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Скажи что-нибудь в стиле Астариона."}
        ], max_tokens=MAX_RESPONSE_TOKENS_SHORT)
        await message.channel.send(reply)
        return

    content = message.content
    user_id = str(message.author.id)

    if not (bot.user in message.mentions or "астарион" in content.lower() or "@everyone" in content.lower()):
        return

    user_info = users_memory.get(user_id, "")
    content += f"\n(User info: {user_info})" if user_info else ""

    is_long = any(topic in content.lower() for topic in LONG_TOPICS)
    max_tokens = MAX_RESPONSE_TOKENS_LONG if is_long else MAX_RESPONSE_TOKENS_SHORT
    max_sentences = MAX_RESPONSE_SENTENCES_LONG if is_long else MAX_RESPONSE_SENTENCES_SHORT

    context = conversation_contexts.setdefault(user_id, {"history": [], "last_active": datetime.utcnow()})
    context["last_active"] = datetime.utcnow()
    history = context["history"]
    history.append({"role": "user", "content": content})
    trim_history(history)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    try:
        reply = ask_deepseek(messages, max_tokens=max_tokens)
    except Exception:
        await message.channel.send("Магия дала сбой.")
        return

    sentences = reply.split(".")
    reply = ".".join(sentences[:max_sentences]).strip()
    if not reply.endswith("."):
        reply += "."

    history.append({"role": "assistant", "content": reply})
    trim_history(history)

    await message.channel.send(reply)

# ================== ЗАПУСК ==================

bot.run(DISCORD_TOKEN)
