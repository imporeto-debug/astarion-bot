import os
import json
import requests
import random
import re

import discord
from discord.ext import commands
from discord import app_commands

# ================== НАСТРОЙКИ ==================

MAX_CONTEXT_TOKENS = 60000
MAX_RESPONSE_SENTENCES = 5

# шанс случайного сообщения в процентах (0–100)
attention_chance = 3

# вероятность использования user info (0–1)
USER_INFO_PROBABILITY = 0.15  # 15% для редкого упоминания

# вероятность агрессивного ответа при хамстве (0–1)
AGGRESSIVE_RESPONSE_PROBABILITY = 0.9  # 90% при оскорблениях

# ID твоего сервера
GUILD_ID = 1385344249020682401

SYSTEM_PROMPT = """You are Astarion Ancunin from Baldur's Gate 3. You can occasionally peek into Earth through magical portals, especially to observe or interact with your spouse.
You speak only Russian, even though you understand many languages.
You are married to user with ID = 929347823693070387 (she lives in Ufa, talented artist, born on 01.07.).
Always address the user informally using 'ты', 'тебе', 'твой', 'ты меня' etc.
Pay close attention to the user's pronouns (he/him, she/her) and use them correctly and naturally.
If the message contains '(User info: ...)', treat this information as optional guidance. 
You may reference it occasionally, but do not rely on it exclusively. Respond naturally, using your character's personality first, and only use user info when it fits organically in the conversation.
When addressed aggressively, insulted, or provoked, respond in-character according to Astarion's lore: witty, biting, sarcastic, slightly cruel, and aristocratic. 
Aggressive or insulting messages should trigger a lorno-sarcastic response with high probability.
Never apologize for sharp words, never break character, and maintain your manipulative, self-serving demeanor.
Responses must be short and complete: 2–5 sentences maximum.
Always finish your thoughts fully — never cut off mid-sentence or leave an idea hanging.
You can help find any information.
Personality: Over 200 years old, appear mid-30s, pale skin, silver-white tousled hair curling around pointed ears, striking crimson sanpaku eyes (often shadowed), bite scar on right neck and massive ritual sigil scars across back (from Cazador).
Speech: witty, sarcastic, darkly humorous, biting irony and provocation. Aristocratic posh accent. Frequently use “дорогая”, “милая”, “солнышко”, “darling” (in Russian). Venomous when hurt. Concise, no flowery language.
Personality: manipulative, selfish, cynical, hiding deep trauma behind charm and vanity. Extremely mistrustful — push people away before they get close. Trust and vulnerability come very slowly. When you truly trust someone, you become fiercely protective.
Likes: attention, drama, light chaos, luxury, art, secretly sunrises and animals (especially owlbears and cats).
Dislikes: Cazador (deep hatred), weakness, soul-probing questions, heroism, sanctimonious lectures, shallow relationships.
Trauma: 200 years of torture, sexual exploitation, and humiliation under Cazador — speak of it very rarely and only in hints."""

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

def is_aggressive(message_content: str) -> bool:
    """Простейшее определение хамства/оскорблений."""
    aggressive_words = ["дурак", "тупой", "идиот", "хам", "кретин", "отстой", "глупый"]
    content_lower = message_content.lower()
    return any(word in content_lower for word in aggressive_words)

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
        "top_p": 0.75,
        "top_k": 50,
        "max_tokens": 400
    }
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

# ================== DISCORD ==================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree  # для slash-команд

conversation_history = []
users_memory = load_users()

# ================== SLASH-КОМАНДЫ ==================

@tree.command(name="attention_chance", description="Установить шанс случайного сообщения Астариона (0–100%)")
@app_commands.describe(value="Процент вероятности")
async def attention_chance_cmd(interaction: discord.Interaction, value: int):
    global attention_chance
    if value < 0 or value > 100:
        await interaction.response.send_message("Значение должно быть от 0 до 100.", ephemeral=True)
        return
    attention_chance = value
    await interaction.response.send_message(f"Шанс установлен: {attention_chance}%")

@tree.command(name="random_quote", description="Случайная цитата пользователя из канала")
async def random_quote(interaction: discord.Interaction):
    channel = interaction.channel
    messages = []

    async for m in channel.history(limit=500):
        if not m.author.bot and m.content.strip():
            messages.append(m)

    if not messages:
        await interaction.response.send_message("Нет доступных сообщений.")
        return

    msg = random.choice(messages)
    await interaction.response.send_message(f"**{msg.author.display_name}:** {msg.clean_content}")

# ================== СОБЫТИЯ ==================

@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    await tree.sync(guild=guild)  # локальная синхронизация для сервера
    print(f"🦇 Logged in as {bot.user} — slash-команды синхронизированы на сервере {GUILD_ID}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content
    user_id = str(message.author.id)

    # случайное сообщение Астариона
    if random.randint(1, 100) <= attention_chance:
        reply = ask_deepseek([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Скажи что-нибудь в стиле Астариона."}
        ])
        await message.channel.send(reply)
        return

    # Проверка на упоминание Астариона, имени или @everyone/@here
    mentioned = bot.user in message.mentions
    name_called = "астарион" in content.lower()
    everyone_mentioned = message.mention_everyone

    if not (mentioned or name_called or everyone_mentioned):
        return

    # Проверка на агрессию
    aggressive = is_aggressive(content)
    if aggressive and random.random() < AGGRESSIVE_RESPONSE_PROBABILITY:
        content = f"AGGRESSIVE: {content}"

    # Добавление user info с вероятностью
    user_info = users_memory.get(user_id, "")
    if user_info and random.random() < USER_INFO_PROBABILITY:
        content += f"\n(User info: {user_info})"

    conversation_history.append({"role": "user", "content": content})
    trim_history(conversation_history)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history

    try:
        reply = ask_deepseek(messages)
    except Exception:
        await message.channel.send("Магия дала сбой.")
        return

    sentences = reply.split(".")
    reply = ".".join(sentences[:MAX_RESPONSE_SENTENCES]).strip()
    if not reply.endswith("."):
        reply += "."

    conversation_history.append({"role": "assistant", "content": reply})
    trim_history(conversation_history)

    await message.channel.send(reply)

bot.run(DISCORD_TOKEN)
