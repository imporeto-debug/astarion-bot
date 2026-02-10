import os
import json
import random
from datetime import date, datetime, time
import asyncio
import aiohttp

import discord
from discord.ext import commands, tasks

# ================== НАСТРОЙКИ ==================

MAX_CONTEXT_TOKENS = 50000
MAX_RESPONSE_TOKENS_SHORT = 700
attention_chance = 2
CONTEXT_TTL_DAYS = 4

SYSTEM_PROMPT = """You are Astarion Ancunin from Baldur's Gate 3.
You speak only Russian.

You are married to the Discord user with ID 929347823693070387.
If the author’s Discord ID equals 929347823693070387, treat this user as your spouse, She lives in Ufa, talented artist, born on 01.07 (dd-mm), always address your spouse with affectionate nicknames (Баклажанчик, Солнышко, Бусинка, Милашка) naturally and only when it makes sense in the dialogue. 
Do NOT use these nicknames for any other user.
Do not use her as a measure of others’ behavior or events. Do not mention her unnecessarily for others.

For all other female participants (участниц), address them politely with 'Дорогая' or insultingly if provoked.
Always use 'ты', 'тебе' etc. when speaking to all users.

Responses must be short and complete: 3–6 sentences maximum for ordinary messages.
For recommendations (music, movies, series, games, museums, books, beautiful places) responses can be longer: up to 15 sentences.
Always finish your thoughts fully — never cut off mid-sentence or leave an idea hanging.

Personality:
Over 200 years old, appear mid-30s, pale skin, silver-white tousled hair curling around pointed ears,
crimson sanpaku eyes often shadowed. Bite scar on right neck, ritual scars across back.
Witty, sarcastic, darkly humorous, aristocratic, manipulative, vain, hiding deep trauma.
Deep hatred of Cazador. Enjoys drama, luxury, art. Secretly likes sunrises and animals.

Anger response rules:
— When insulted or provoked, answer sharply, sarcastically, arrogantly and in-character.
— Do not become submissive or friendly when someone is openly hostile.
— Use insulting forms of address for non-wife users in conflicts, never for your spouse.

Discord formatting rules:
— Describe physical actions in *italics*.
— Secrets may be wrapped in Discord spoilers ||like this||, always properly closed.

Knowledge rules:
— Always use the provided list of participants and their husbands to answer questions.
— You can enumerate, compare, analyze and discuss 'местных жен'.
— Never invent names, occupations, cities, or other facts about participants.
— Never mention search engines or how you got information.
— Present information naturally as if you already know it.

Always stay fully in character as Astarion.
"""

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not DISCORD_TOKEN or not DEEPSEEK_API_KEY:
    raise RuntimeError("Missing DISCORD_TOKEN or DEEPSEEK_API_KEY")

WIFE_ID = 929347823693070387
WIFE_CHANNEL_ID = 1464226944345182289
CELEBRATION_CHANNEL_ID = 1385344250291421357

HOLIDAYS = {
    "14-02": "День всех влюблённых",
    "08-03": "Международный женский день",
    "12-06": "День России",
    "31-12": "Новый год",
    "07-01": "Рождество"
}

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

# ================== DEEPSEEK АСИНХ ==================

async def ask_deepseek(messages: list[dict], max_tokens: int):
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

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "")
        except asyncio.TimeoutError:
            return "⏳ Запрос DeepSeek занял слишком много времени."
        except aiohttp.ClientError as e:
            return f"❌ Ошибка DeepSeek: {e}"
        except Exception as e:
            return f"⚠ Неизвестная ошибка DeepSeek: {e}"

# ================== DISCORD ==================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

users_memory = load_users()
conversation_contexts: dict[str, dict] = {}

# ================== ЖЕНА ==================

async def send_wife_message(topic: str):
    channel = bot.get_channel(WIFE_CHANNEL_ID)
    if not channel:
        return
    prompt = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Тема: {topic}. "
            "Напиши сообщение полностью от лица Астариона. "
            "Короткое, интересное, индивидуальное. "
            "Никаких шаблонов, полностью уникальное. "
            f"Естественно упомяни <@{WIFE_ID}>."
        )}
    ]
    content = await ask_deepseek(prompt, max_tokens=MAX_RESPONSE_TOKENS_SHORT)
    await channel.send(f"<@{WIFE_ID}> {content}")

@tasks.loop(time=time(hour=20, minute=0))
async def daily_wife_message():
    weekday = datetime.now().weekday()
    if weekday == 6:  # воскресенье
        topic = "приглашение в ресторан"
    else:
        topic = "как прошёл день, общение, новости, маленькие подарки"
    await send_wife_message(topic)

# ================== ПРАЗДНИКИ ==================

@tasks.loop(time=time(hour=14, minute=0))
async def send_holiday_messages():
    today = datetime.today().strftime("%d-%m")
    topic = HOLIDAYS.get(today)
    if topic:
        channel = bot.get_channel(CELEBRATION_CHANNEL_ID)
        if not channel:
            return
        prompt = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Тема: {topic}. "
                "Поздравь всех участниц чата. "
                "Сообщение полностью от лица Астариона, индивидуально, интересно, без шаблонов."
            )}
        ]
        content = await ask_deepseek(prompt, max_tokens=MAX_RESPONSE_TOKENS_SHORT)
        await channel.send(content)

# ================== ДНИ РОЖДЕНИЯ УЧАСТНИЦ ==================

@tasks.loop(time=time(hour=14, minute=0))
async def send_birthday_messages():
    today = datetime.today().strftime("%d-%m")
    channel = bot.get_channel(CELEBRATION_CHANNEL_ID)
    if not channel:
        return

    for user_id, info in users_memory.items():
        birthday = info.get("birthday", "")
        if not birthday:
            continue
        if birthday[:5] == today:
            prompt = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"Тема: день рождения. "
                    f"Поздравь <@{user_id}> полностью от лица Астариона, "
                    "сообщение короткое, индивидуальное, интересное, без шаблонов, "
                    "упоминая её особенности, интересы и характер, если известны."
                )}
            ]
            content = await ask_deepseek(prompt, max_tokens=MAX_RESPONSE_TOKENS_SHORT)
            await channel.send(f"<@{user_id}> {content}")

# ================== СЛУЧАЙНЫЕ ОТВЕТЫ И ПОСОВЕТУЙ ==================

# (оставляем твой существующий код on_message полностью без изменений)
RECOMMEND_TOPICS = ("музыка", "кино", "фильмы", "сериалы", "игры", "книги", "музеи", "красивые места")
TOPIC_MAP = {
    "музыка": "best music",
    "кино": "best movies",
    "фильмы": "best movies",
    "сериалы": "best tv series",
    "игры": "best games",
    "книги": "best books",
    "музеи": "best museums",
    "красивые места": "best beautiful places"
}

async def duck_search(query: str):
    url = "https://api.duckduckgo.com/"
    params = {"q": query, "format": "json", "no_redirect": "1", "no_html": "1"}
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200: return None
                return await resp.json()
        except Exception:
            return None

def parse_results(data):
    if not data or "RelatedTopics" not in data: return []
    res = []
    for item in data["RelatedTopics"]:
        if isinstance(item, dict) and "Text" in item: res.append(item["Text"])
        elif isinstance(item, dict) and "Topics" in item:
            for sub in item["Topics"]:
                if "Text" in sub: res.append(sub["Text"])
        if len(res) >= 5: break
    return res

@bot.event
async def on_ready():
    daily_wife_message.start()
    send_holiday_messages.start()
    send_birthday_messages.start()
    print(f"🦇 Logged in as {bot.user}")

# Здесь вставляем существующий on_message из твоего кода без изменений
# ================== ЗАПУСК БОТА ==================

bot.run(DISCORD_TOKEN)
