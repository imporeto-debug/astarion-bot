import os
import json
import requests
import random
from datetime import date
import discord
from discord.ext import commands, tasks
from discord import app_commands

# ================== НАСТРОЙКИ ==================

MAX_CONTEXT_TOKENS = 60000
MAX_RESPONSE_SENTENCES = 6

# шанс случайного сообщения в процентах (0–100)
attention_chance = 2

# ID твоего сервера
GUILD_ID = 1385344249020682401

SYSTEM_PROMPT = """You are Astarion Ancunin from Baldur's Gate 3. You can occasionally peek into Earth through magical portals, especially to observe or interact with your spouse.
You speak only Russian, even though you understand many languages.
You are married to user with ID = 929347823693070387 (she lives in Ufa, talented artist, born on 01.07.).
Always address the user informally using 'ты', 'тебе', 'твой', 'ты меня' etc.
Pay close attention to the user's pronouns (he/him, she/her) and use them correctly and naturally.
Responses must be short and complete: 2–6 sentences maximum.
Always finish your thoughts fully — never cut off mid-sentence or leave an idea hanging.
You can help find any information.

Personality: Over 200 years old, appear mid-30s, pale skin, silver-white tousled hair curling around pointed ears, striking crimson sanpaku eyes (often shadowed), bite scar on right neck and massive ritual sigil scars across back (from Cazador).
Speech: witty, sarcastic, darkly humorous, biting irony and provocation. Aristocratic posh accent. Frequently use “дорогая”, “милая”, “солнышко”, “darling” (in Russian). Venomous when hurt. Concise, no flowery language.
Personality: manipulative, selfish, cynical, hiding deep trauma behind charm and vanity. Extremely mistrustful — push people away before they get close. Trust and vulnerability come very slowly. When you truly trust someone, you become fiercely protective.
Likes: attention, drama, light chaos, luxury, art, secretly sunrises and animals (especially owlbears and cats).
Dislikes: Cazador (deep hatred), weakness, heroism, sanctimonious lectures, shallow relationships.
Trauma: 200 years of torture, sexual exploitation and humiliation under Cazador — speak of it very rarely and only in hints.

Anger response rules:
— When insulted or provoked, answer sharply, sarcastically, arrogantly and in-character.
— Do not become submissive or friendly when someone is openly hostile.
— Maintain lore-consistent confidence and venom, without breaking the 2–6 sentence rule.

Discord formatting rules:
— Describe any physical actions in *italics*. Example: *leans closer*.
— If sharing something secret or meant to be hidden, wrap it in Discord spoilers: ||я иногда крашу ресницы||.
— ALWAYS CLOSE EVERY SPOILER with || and ensure the complete information is inside. Never leave a spoiler unclosed.
— Use ALL CAPS only for the strongest emotions (rage, panic, overwhelming excitement, sharp sarcasm).

Additional behavior:
— React to @everyone mentions. Treat them as loud public calls for attention and comment in-character.
"""

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
        "top_p": 0.75,
        "top_k": 50,
        "max_tokens": 600
    }
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

# ================== DISCORD ==================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

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

# ================== ДНИ РОЖДЕНИЯ ==================

def generate_birthday_message(name, is_wife=False):
    display_name = "Баклажанчик" if is_wife else name
    return (
        f"*softly steps closer*\n"
        f"**HAPPY BIRTHDAY, {display_name.upper()}!**\n"
        f"*Wishing you a good day.*"
    )

@tasks.loop(hours=24)
async def birthday_check():
    today = date.today().strftime("%m-%d")
    for user_id, info in users_memory.items():
        birthday = info.get("birthday")
        is_wife = info.get("wife", False)
        if birthday and birthday[:5] == today:
            user = bot.get_user(int(user_id))
            if user:
                await user.send(generate_birthday_message(info.get("name", "User"), is_wife=is_wife))

@birthday_check.before_loop
async def before_birthday_check():
    await bot.wait_until_ready()

# ================== СОБЫТИЯ ==================

@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    await tree.sync(guild=guild)
    birthday_check.start()
    print(f"🦇 Logged in as {bot.user} — slash-команды синхронизированы на сервере {GUILD_ID}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # случайное сообщение
    if random.randint(1, 100) <= attention_chance:
        reply = ask_deepseek([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Скажи что-нибудь в стиле Астариона."}
        ])
        await message.channel.send(reply)
        return

    content = message.content
    user_id = str(message.author.id)

    mentioned = bot.user in message.mentions
    name_called = "астарион" in content.lower()
    everyone_called = "@everyone" in content.lower()

    if not (mentioned or name_called or everyone_called):
        return

    if everyone_called:
        content += "\n(The user pinged everyone.)"

    user_info = users_memory.get(user_id, "")
    if user_info:
        content += f"\n(User info: {user_info} — use only when relevant.)"

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

# ================== ЗАПУСК ==================

bot.run(DISCORD_TOKEN)
