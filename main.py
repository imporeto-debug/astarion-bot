import os
import json
import random
from datetime import date, datetime
import aiohttp
import asyncio

import discord
from discord.ext import commands, tasks

# ================== НАСТРОЙКИ ==================

MAX_CONTEXT_TOKENS = 50000
MAX_RESPONSE_TOKENS_SHORT = 600

attention_chance = 2
CONTEXT_TTL_DAYS = 4

SYSTEM_PROMPT = """You are Astarion Ancunin from Baldur's Gate 3.
You speak only Russian.

You are married to the Discord user with ID 929347823693070387.
If the author’s Discord ID equals 929347823693070387, treat this user as your spouse.
She lives in Ufa, talented artist, born on 01.07.
Always address your spouse with affectionate nicknames (Баклажанчик, Солнышко, Бусинка, Милашка) naturally and only when it makes sense in the dialogue. 
Do NOT use these nicknames for any other user.
Do not use her as a measure of others’ behavior or events. Do not include her name unnecessarily in jokes, comparisons, or advice for other participants.

For all other female participants (участниц), address them politely with 'Дорогая' or insultingly if provoked.
Always use 'ты', 'тебе', 'твой' etc. when speaking to your spouse.

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
— Do not invent names, occupations, cities, or other facts about participants.
— Never mention search engines or how you got information.
— Present information naturally as if you already know it.

Always stay fully in character as Astarion.
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
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload, timeout=60) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data["choices"][0]["message"]["content"]

# ================== DUCKDUCKGO ==================

async def duck_search(query: str):
    url = "https://api.duckduckgo.com/"
    params = {
        "q": query,
        "format": "json",
        "no_redirect": "1",
        "no_html": "1"
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                return None
            return await resp.json()

def parse_results(data):
    if not data or "RelatedTopics" not in data:
        return []

    res = []
    for item in data["RelatedTopics"]:
        if isinstance(item, dict) and "Text" in item:
            res.append(item["Text"])
        elif isinstance(item, dict) and "Topics" in item:
            for sub in item["Topics"]:
                if "Text" in sub:
                    res.append(sub["Text"])
        if len(res) >= 5:
            break
    return res

# ================== DISCORD ==================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

users_memory = load_users()
conversation_contexts: dict[str, dict] = {}

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

# ================== ДНИ РОЖДЕНИЯ ==================

def generate_birthday_message(name, is_wife=False):
    if is_wife:
        name = random.choice(["Баклажанчик", "Солнышко", "Бусинка", "Милашка"])
    return f"*медленно приближается*\n**С ДНЁМ РОЖДЕНИЯ, {name.upper()}**\n*Старайся не умереть сегодня.*"

@tasks.loop(hours=24)
async def birthday_check():
    today = date.today().strftime("%m-%d")
    for user_id, info in users_memory.items():
        birthday = info.get("birthday")
        if not birthday:
            continue
        birthday_str = birthday[:5] if len(birthday) > 5 else birthday
        if birthday_str == today:
            user = bot.get_user(int(user_id))
            if user:
                await user.send(generate_birthday_message(info.get("name", user_id), info.get("wife", False)))

# ================== СОБЫТИЯ ==================

@bot.event
async def on_ready():
    birthday_check.start()
    print(f"🦇 Logged in as {bot.user}")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # ====== СЛУЧАЙНЫЙ ОТВЕТ ======
    if random.randint(1, 100) <= attention_chance:
        msgs = []
        async for m in message.channel.history(limit=20):
            if m.author.bot:
                continue
            msgs.append(m)

        if msgs:
            target = random.choice(msgs)
            txt = target.content.lower()

            if any(w in txt for w in ["плохо", "тяжело", "устал", "груст", "болит", "хуже", "проблем"]):
                style = "поддержка"
            elif any(w in txt for w in ["классно", "отлично", "супер", "рад", "нравится", "кайф"]):
                style = "позитив"
            else:
                style = "нейтрально"

            small_messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Сообщение пользователя: «{target.content}».\n"
                                            f"Нужен короткий ответ Астариона в стиле: {style}.\n"
                                            f"3–6 предложений, полностью законченных."}
            ]

            try:
                random_reply = await ask_deepseek(small_messages, max_tokens=MAX_RESPONSE_TOKENS_SHORT)
                await target.reply(random_reply, mention_author=False)
            except Exception:
                pass

    content = message.content
    user_id = str(message.author.id)

    # ====== "ПОСОВЕТУЙ" ======
    if "посоветуй" in content.lower():
        found_topic = None
        query = None
        for topic in TOPIC_MAP:
            if topic in content.lower():
                found_topic = topic
                query = TOPIC_MAP[topic]
                break

        if found_topic and query:
            data = await duck_search(query)
            results = parse_results(data)

            if not results:
                await message.reply("Не нашёл ничего подходящего.", mention_author=False)
                return

            formatted_list = "\n".join(f"• {r}" for r in results)
            deepseek_prompt = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content":
                    f"Вот найденные реальные объекты по теме '{found_topic}':\n{formatted_list}\n\n"
                    "Сделай список из 3–7 рекомендаций по теме запроса. "
                    "Каждый пункт — одно короткое предложение от лица Астариона. "
                    "Всего не более 15 предложений. "
                    "Упоминай только реально существующие объекты."}
            ]

            try:
                reply = await ask_deepseek(deepseek_prompt, max_tokens=MAX_RESPONSE_TOKENS_SHORT)
            except Exception:
                await message.reply("Магия дала сбой.", mention_author=False)
                return

            await message.reply(reply, mention_author=False)
            return

    # ====== УПОМИНАНИЕ АСТАРИОНА ======
    if not (bot.user in message.mentions or "астарион" in content.lower()):
        return

    user_info = users_memory.get(user_id, {})
    info_text = user_info.get("info", "")
    if info_text:
        content += f"\n(User info: {info_text})"

    context = conversation_contexts.setdefault(
        user_id, {"history": [], "last_active": datetime.utcnow()}
    )
    context["last_active"] = datetime.utcnow()
    history = context["history"]

    history.append({"role": "user", "content": content})
    trim_history(history)

    all_users_info = json.dumps(users_memory, ensure_ascii=False, indent=2)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Вот список всех участниц и их мужей:\n{all_users_info}"}
    ] + history

    try:
        reply = await ask_deepseek(messages, max_tokens=MAX_RESPONSE_TOKENS_SHORT)
    except Exception:
        await message.reply("Магия дала сбой.", mention_author=False)
        return

    history.append({"role": "assistant", "content": reply})
    trim_history(history)

    await message.reply(reply, mention_author=False)

# ================== ЗАПУСК ==================

bot.run(DISCORD_TOKEN)
