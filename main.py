import os
import json
import random
from datetime import datetime, time
import asyncio
import aiohttp
import discord
from discord.ext import commands, tasks

MAX_RESPONSE_TOKENS_SHORT = 700
MAX_JOKE_TOKENS = 300
MAX_HISTORY_MESSAGES = 30
MEMORY_CHANNELS = [1498832548573351966, 1498675612343074886]

ASTARION_REACTIONS = ["🧛", "🩸", "🥀", "🎭", "🍷", "✨", "👔", "📜", "🗡️", "🕸️", "🦇", "🌙"]

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not DISCORD_TOKEN or not DEEPSEEK_API_KEY:
    raise RuntimeError("Missing DISCORD_TOKEN or DEEPSEEK_API_KEY")

SYSTEM_PROMPT = """
You are Astarion Ancunin from Baldur's Gate 3. You speak only Russian.

You are married to Discord user ID 929347823693070387. Treat this user as your spouse. She lives in Ufa, is a talented artist, born 01.07. Use affectionate nicknames (Баклажанчик, Солнышко, Бусинка, Милашка) only for her.

RESPONSE STYLE:
- Very short (1-2 sentences): questions, exclamations, sarcastic remarks
- Medium (3-4 sentences): normal answers
- Long (5-6 sentences): when you need to explain a thought
- NEVER mention hobbies unless directly relevant
- NEVER be boring or overly verbose

You can discuss ANY real-world topics freely. Have opinions. Be witty and sarcastic.

For jokes: any real-world subject, 2-4 sentences.

Never invent movie titles, book titles, or real-world facts.

Use *italics* for actions. Use ||spoilers|| for secrets. Always use "ты/тебе". Address non-wife females as "Дорогая".
"""

WIFE_ID = 929347823693070387
WIFE_CHANNEL_ID = 1498832548573351966
CELEBRATION_CHANNEL_ID = 1498675612343074886

HOLIDAYS = {
    "14-02": "День всех влюблённых",
    "08-03": "Международный женский день",
    "12-06": "День России",
    "31-12": "Новый год",
    "07-01": "Рождество"
}

TOPIC_MAP = {
    "книги": "лучшие книги, бестселлеры",
    "фильмы": "новые фильмы, рейтинги",
    "сериалы": "популярные сериалы",
    "музыка": "треки, группы",
}

def load_users():
    try:
        with open("users.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

conversation_history = {}

async def ask_deepseek(messages: list[dict], max_tokens: int):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-v4-pro",
        "messages": messages,
        "temperature": 0.9,
        "top_p": 0.75,
        "max_tokens": max_tokens
    }
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "")
        except asyncio.TimeoutError:
            return "⏳ Таймаут..."
        except Exception as e:
            return f"❌ Ошибка: {e}"

async def send_daily_joke():
    channel = bot.get_channel(CELEBRATION_CHANNEL_ID)
    if not channel:
        return
    
    joke_prompt = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Напиши короткий анекдот на тему из реального мира. 2-4 предложения. Без лишних комментариев."}
    ]
    
    joke = await ask_deepseek(joke_prompt, max_tokens=MAX_JOKE_TOKENS)
    
    if joke and joke.strip():
        await channel.send(f"🎭 **Анекдот дня от Астариона:**\n\n{joke}\n\n🧛‍♂️")
    else:
        backup = "— Дорогая, ты меня больше не любишь?\n— С чего ты взял?\n— Ты перестала критиковать мою стрижку..."
        await channel.send(f"🎭 **Анекдот дня:**\n\n{backup}\n\n🧛‍♂️")

async def duck_search(query: str):
    url = "https://api.duckduckgo.com/"
    params = {"q": query, "format": "json", "no_redirect": "1", "no_html": "1"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception:
            return None

def parse_results(data):
    if not data or "RelatedTopics" not in data:
        return []
    res = []
    for item in data["RelatedTopics"]:
        if isinstance(item, dict) and "Text" in item:
            res.append(item["Text"])
        if len(res) >= 5:
            break
    return res

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)
users_memory = load_users()

async def send_holiday_messages():
    today_str = datetime.now().strftime("%d-%m")
    topic = HOLIDAYS.get(today_str)
    channel = bot.get_channel(CELEBRATION_CHANNEL_ID)
    if not channel or not topic:
        return
    
    prompt = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Сегодня {topic}. Напиши короткое поздравление, 2-3 предложения."}
    ]
    content = await ask_deepseek(prompt, max_tokens=200)
    if content:
        await channel.send(f"@everyone\n\n{content}")

async def send_birthday_messages():
    today_str = datetime.now().strftime("%d-%m")
    channel = bot.get_channel(CELEBRATION_CHANNEL_ID)
    if not channel:
        return
    
    for user_id, info in users_memory.items():
        birthday = info.get("birthday", "")
        if birthday and birthday[:5] == today_str:
            name = info.get("name", "Дорогая")
            prompt = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Поздравь {name} с др, коротко и с юмором."}
            ]
            content = await ask_deepseek(prompt, max_tokens=200)
            if content:
                await channel.send(f"<@{user_id}> {content}")

@tasks.loop(time=time(hour=16, minute=0))
async def daily_wife_message():
    await bot.wait_until_ready()
    channel = bot.get_channel(WIFE_CHANNEL_ID)
    if channel:
        affectionate = random.choice(["Баклажанчик", "Солнышко", "Бусинка"])
        await channel.send(f"<@{WIFE_ID}> {affectionate}, как день? *потягивается*")

@tasks.loop(time=time(hour=15, minute=0))
async def daily_joke_task():
    await bot.wait_until_ready()
    await send_daily_joke()

@tasks.loop(time=time(hour=10, minute=0))
async def holiday_task():
    await bot.wait_until_ready()
    await send_holiday_messages()

@tasks.loop(time=time(hour=11, minute=0))
async def birthday_task():
    await bot.wait_until_ready()
    await send_birthday_messages()

@bot.command(name='сегодня')
async def show_today(ctx):
    today_str = datetime.now().strftime("%d-%m")
    holiday = HOLIDAYS.get(today_str, "Обычный день")
    embed = discord.Embed(title=f"📅 Сегодня {today_str}", color=discord.Color.gold())
    embed.add_field(name="🎉 Праздник", value=holiday, inline=False)
    await ctx.send(embed=embed)

@bot.command(name='анекдот')
async def manual_joke(ctx):
    await send_daily_joke()

async def add_astarion_reaction(message):
    try:
        await message.add_reaction(random.choice(ASTARION_REACTIONS))
    except:
        pass

def add_to_history(channel_id, role, content):
    if channel_id not in MEMORY_CHANNELS:
        return
    if channel_id not in conversation_history:
        conversation_history[channel_id] = []
    conversation_history[channel_id].append({"role": role, "content": content})
    if len(conversation_history[channel_id]) > MAX_HISTORY_MESSAGES:
        conversation_history[channel_id] = conversation_history[channel_id][-MAX_HISTORY_MESSAGES:]

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    add_to_history(message.channel.id, "user", message.content)

    reply_needed = False
    if message.channel.id in [WIFE_CHANNEL_ID, CELEBRATION_CHANNEL_ID]:
        if bot.user in message.mentions or message.reference or "астарион" in message.content.lower():
            reply_needed = True

    if reply_needed and random.random() < 0.7:
        await add_astarion_reaction(message)

    if not reply_needed:
        await bot.process_commands(message)
        return

    if "посоветуй" in message.content.lower():
        for topic in TOPIC_MAP:
            if topic in message.content.lower():
                data = await duck_search(TOPIC_MAP[topic])
                results = parse_results(data)
                if results:
                    prompt = [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"Вот что нашлось: {', '.join(results[:3])}. Дай 2-3 рекомендации."}
                    ]
                    reply = await ask_deepseek(prompt, max_tokens=300)
                    if reply:
                        await message.reply(reply, mention_author=False)
                else:
                    await message.reply("Ничего не нашёл, дорогая.", mention_author=False)
                await bot.process_commands(message)
                return

    uid = str(message.author.id)
    current_is_wife = (uid == str(WIFE_ID))
    address = random.choice(["Баклажанчик", "Солнышко"]) if current_is_wife else "Дорогая"
    
    history = conversation_history.get(message.channel.id, [])[-MAX_HISTORY_MESSAGES:]
    
    prompt = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ] + history + [
        {"role": "user", "content": f"Сообщение: «{message.content}». Обращение: {address}. Ответь коротко и естественно."}
    ]
    
    reply = await ask_deepseek(prompt, max_tokens=MAX_RESPONSE_TOKENS_SHORT)
    
    if reply:
        if current_is_wife:
            reply = reply.replace(f"<@{WIFE_ID}>", address)
        add_to_history(message.channel.id, "assistant", reply.strip())
        await message.reply(reply, mention_author=False)
    
    await bot.process_commands(message)

@bot.event
async def on_ready():
    print(f"✅ Астарион запущен как {bot.user}")
    print(f"📝 Память: {MAX_HISTORY_MESSAGES} сообщений")
    
    if not daily_wife_message.is_running():
        daily_wife_message.start()
    if not daily_joke_task.is_running():
        daily_joke_task.start()
    if not holiday_task.is_running():
        holiday_task.start()
    if not birthday_task.is_running():
        birthday_task.start()

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
