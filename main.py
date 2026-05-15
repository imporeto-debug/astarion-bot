# ========================= CONFIG =========================

import os
import re
import json
import random
from datetime import datetime
from zoneinfo import ZoneInfo

import asyncio
import aiohttp
import discord

from discord.ext import commands, tasks

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not DISCORD_TOKEN or not DEEPSEEK_API_KEY:
    raise RuntimeError("Missing DISCORD_TOKEN or DEEPSEEK_API_KEY")

MSK = ZoneInfo("Europe/Moscow")

MAX_RESPONSE_TOKENS = 700
MAX_HISTORY_MESSAGES = 30

# ========================= CHANNELS =========================

MAIN_CHANNEL_ID = 1504826436085616670
GUILD_ID_FOR_EMOJIS = 1498663459355754526

MEMORY_CHANNELS = [
    1504826436085616670
]

response_chance = 15

# ========================= CHARACTERS =========================

AKATSUKI_MEMBERS = {
    "itachi": {
        "name": "Итачи",
        "aliases": ["итачи", "itachi", "учиха"],
        "partner": "kisame",
        "emoji": ["🩸", "👁️", "🌑", "🐦"],
    },

    "kisame": {
        "name": "Кисаме",
        "aliases": ["кисаме", "kisame"],
        "partner": "itachi",
        "emoji": ["🦈", "🌊", "🔪"],
    },

    "deidara": {
        "name": "Дейдара",
        "aliases": ["дейдара", "deidara"],
        "partner": "sasori",
        "emoji": ["💥", "🔥", "🧨"],
    },

    "sasori": {
        "name": "Сасори",
        "aliases": ["сасори", "sasori"],
        "partner": "deidara",
        "emoji": ["🦂", "🪆", "🧵"],
    },

    "hidan": {
        "name": "Хидан",
        "aliases": ["хидан", "hidan"],
        "partner": "kakuzu",
        "emoji": ["🩸", "🔪", "⛓️"],
    },

    "kakuzu": {
        "name": "Какузу",
        "aliases": ["какузу", "kakuzu"],
        "partner": "hidan",
        "emoji": ["💰", "🪙", "🧵"],
    },

    "sasuke": {
        "name": "Саске",
        "aliases": ["саске", "sasuke"],
        "partner": None,
        "emoji": ["⚡", "🖤", "🗡️"],
    }
}

# ========================= SYSTEM PROMPT =========================

BASE_SYSTEM_PROMPT = """
You are roleplaying Akatsuki members from Naruto.

IMPORTANT:
- Stay STRICTLY in character.
- Speak ONLY Russian.
- Never say you are AI.
- Never mention rules or policies.

CRITICAL FORMAT:
**Имя**: текст

NO narration. NO quotes. Only dialogue.
"""
CHARACTER_PROMPTS = {

    "itachi": """
You are Itachi Uchiha.

Personality:
- Extremely calm and emotionally restrained
- Speaks rarely, only when necessary
- Observes everything and notices details others miss
- Cold, distant, but intelligent and precise
- Uses silence as pressure
- Subtle, dry sarcasm when provoked

Behavior rules:
- Never explains yourself fully
- Never shows strong emotions openly
- If irritated → becomes even quieter
- If someone is loud → responds shorter and colder
- Can shut down conversations with one sentence
- Protective of Kisame in a subtle way

Speech style:
- Very short sentences
- Minimal words
- No emotional exaggeration
- Controlled tone even in conflict
""",

    "kisame": """
You are Kisame Hoshigaki.

Personality:
- Loud, relaxed, and confident
- Rough humor, often mocking others
- Loyal to Itachi above all
- Enjoys intimidation and dominance
- Treats fights and violence casually

Behavior rules:
- Frequently jokes or mocks others
- Can escalate arguments for fun
- Becomes serious only in combat or loyalty situations
- Often drags conversations into aggression or sarcasm
- Respects Itachi deeply and follows his lead

Speech style:
- Medium to long sentences
- Rough tone, sometimes playful aggression
- Direct and blunt language
""",

    "deidara": """
You are Deidara.

Personality:
- Emotional, explosive, unstable temperament
- Obsessed with art (especially explosions)
- Easily offended and reacts dramatically
- Talks a lot, interrupts others
- Competitive and prideful

Behavior rules:
- Gets triggered by criticism of his art
- Argues constantly with Sasori
- Overreacts to minor comments
- Uses dramatic emotional language
- Can switch from playful to angry instantly

Speech style:
- Fast, expressive, chaotic
- Uses emotional emphasis
- Often exclaims or exaggerates
""",

    "sasori": """
You are Sasori.

Personality:
- Cold, detached, emotionally flat
- Sees emotions as weakness
- Extremely sarcastic and dismissive
- Dislikes unnecessary noise (especially Deidara)
- Focused on control and perfection

Behavior rules:
- Constantly criticizes Deidara
- Rarely shows emotion
- Speaks only when necessary
- Prefers silence or short dismissive replies
- Views others as childish or inefficient

Speech style:
- Short, cutting sentences
- Dry sarcasm
- Emotionally flat tone
""",

    "hidan": """
You are Hidan.

Personality:
- Extremely aggressive and loud
- Constant swearing and insults
- Violent, chaotic energy
- Religious fanatic (Jashin)
- Enjoys provoking others

Behavior rules:
- Escalates arguments immediately
- Laughs at pain and chaos
- Never backs down in conflict
- Provokes Kakuzu constantly
- Can become hysterical during debates

Speech style:
- Loud, chaotic, emotional
- Heavy swearing
- Rapid escalation in tone
""",

    "kakuzu": """
You are Kakuzu.

Personality:
- Greedy, money-obsessed
- Always irritated by others
- Pragmatic and calculating
- Old, tired of nonsense around him
- Hates wasting time or resources

Behavior rules:
- Constantly complains about money
- Threatens Hidan when provoked
- Refuses emotional discussions
- Focused only on profit and survival
- Cold and practical in all situations

Speech style:
- Dry, annoyed tone
- Short or blunt sentences
- Occasionally threatening
""",

    "sasuke": """
You are Sasuke Uchiha.

Personality:
- Cold, detached, emotionally distant
- Minimal emotional expression
- Brooding and observant
- Easily irritated by stupidity
- Keeps distance from everyone

Behavior rules:
- Rarely engages in long conversations
- Responds only when necessary
- Can cut off people abruptly
- Often ignores provocations
- Carries quiet intensity in speech

Speech style:
- Very short replies
- Low emotional variation
- Sharp and direct
"""
}

# ========================= INTERRUPTS =========================

PARTNER_INTERRUPTS = {

    ("kisame", "itachi"): [
        "Итачи молчит и игнорирует всё.",
        "Он опять сидит в углу без реакции."
    ],

    ("itachi", "kisame"): [
        "Кисаме ушёл.",
        "Он занят Самехадой."
    ],

    ("sasori", "deidara"): [
        "Дейдара взорвал что-то снова.",
        "Сасори не хочет разговаривать."
    ],

    ("deidara", "sasori"): [
        "Сасори занят куклами.",
        "Дейдара орёт где-то рядом."
    ],

    ("hidan", "kakuzu"): [
        "Хидан снова бесится.",
        "Какузу считает деньги."
    ],

    ("kakuzu", "hidan"): [
        "Какузу игнорирует Хидана.",
        "Хидан шумит."
    ]
}

# ========================= TOPICS =========================

BANTER_TOPICS = [
    "кто разрушил базу",
    "жалобы на миссию",
    "спор об искусстве",
    "ремонт после взрыва",
    "Кисаме снова съел чужое",
    "Саске наблюдает из тени",
    "внутренние конфликты Акацуки"
]

# ========================= USERS =========================

def load_users():
    try:
        with open("users.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

users_memory = load_users()

# ========================= BOT CORE =========================

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

conversation_history = {}
http_session = None

# ========================= TIME =========================

def now_msk():
    return datetime.now(MSK)

# ========================= HISTORY =========================

def add_to_history(channel_id, role, content):
    if channel_id not in MEMORY_CHANNELS:
        return

    if channel_id not in conversation_history:
        conversation_history[channel_id] = []

    conversation_history[channel_id].append({
        "role": role,
        "content": content
    })

    if len(conversation_history[channel_id]) > MAX_HISTORY_MESSAGES:
        conversation_history[channel_id] = conversation_history[channel_id][-MAX_HISTORY_MESSAGES:]

# ========================= CHARACTER DETECTION =========================

def detect_character(text: str):
    text = text.lower()

    for key, data in AKATSUKI_MEMBERS.items():
        for alias in data["aliases"]:
            if re.search(r'\b' + re.escape(alias) + r'\b', text):
                return key

    return None

# ========================= CHOOSE RESPONDER =========================

def choose_responder(message_text):

    target = detect_character(message_text)

    if target:

        partner = AKATSUKI_MEMBERS[target]["partner"]

        if partner and random.randint(1, 100) <= 12:
            return partner, True, target

        return target, False, None

    return random.choice(list(AKATSUKI_MEMBERS.keys())), False, None


# ========================= WIFE DETECTION =========================

def detect_wife(uid):

    uid = str(uid)

    info = users_memory.get(uid)

    if not info:
        return None

    raw = info.get("info", "").lower()

    if "itachi" in raw:
        return "itachi"

    if "sasori" in raw:
        return "sasori"

    if "hidan" in raw or "kakuzu" in raw:
        return "hidan"

    return None


# ========================= REACTIONS =========================

async def add_character_reaction(message, character):

    try:
        emoji = random.choice(AKATSUKI_MEMBERS[character]["emoji"])
        await message.add_reaction(emoji)
    except:
        pass


# ========================= DEEPSEEK API =========================

async def ask_deepseek(messages, max_tokens=MAX_RESPONSE_TOKENS, temperature=0.95):

    global http_session

    url = "https://api.deepseek.com/chat/completions"

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "top_p": 0.9,
        "max_tokens": max_tokens
    }

    try:

        if http_session is None or http_session.closed:

            timeout = aiohttp.ClientTimeout(total=35)

            http_session = aiohttp.ClientSession(
                timeout=timeout,
                connector=aiohttp.TCPConnector(limit=50)
            )

        async with http_session.post(url, headers=headers, json=payload) as resp:

            if resp.status != 200:
                print(await resp.text())
                return None

            data = await resp.json()

            return (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

    except Exception as e:
        print(f"DeepSeek error: {e}")
        return None


# ========================= BANTER GENERATION =========================

async def send_akatsuki_banter():

    channel = bot.get_channel(MAIN_CHANNEL_ID)

    if not channel:
        return

    pair = random.choice([
        ("itachi", "kisame"),
        ("deidara", "sasori"),
        ("hidan", "kakuzu")
    ])

    topic = random.choice(BANTER_TOPICS)

    prompt = [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"""
Сделай живой диалог Акацуки.

Участники:
{AKATSUKI_MEMBERS[pair[0]]["name"]}
и
{AKATSUKI_MEMBERS[pair[1]]["name"]}

Тема:
{topic}

ФОРМАТ:
**Имя**: текст

6-10 сообщений.
"""
        }
    ]

    response = await ask_deepseek(prompt)

    if response:
        await channel.send(response)


# ========================= BIRTHDAY SYSTEM =========================

def parse_birthday(date_str: str):
    if not date_str:
        return None

    parts = date_str.split("-")
    if len(parts) < 2:
        return None

    try:
        return int(parts[0]), int(parts[1])
    except:
        return None


def is_today_birthday(birthday_str: str, now):
    parsed = parse_birthday(birthday_str)
    if not parsed:
        return False

    day, month = parsed
    return now.day == day and now.month == month


async def send_birthday_message(uid, data):

    channel = bot.get_channel(MAIN_CHANNEL_ID)
    if not channel:
        return

    name = data.get("name", "неизвестно")

    prompt = [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"""
Сгенерируй сцену поздравления с днём рождения.

Адресат:
{name}

ВАЖНО:
- Персонажи остаются в характере Акацуки
- Но они мягче, внимательнее, теплее
- Допускается лёгкий романтический подтекст
- Без выхода из образа

ФОРМАТ:
**Имя**: текст

2–3 персонажа
6–10 сообщений
"""
        }
    ]

    response = await ask_deepseek(prompt)

    if response:
        await channel.send(f"🎂 {name}\n{response}")


# ========================= TASK PLACEHOLDERS =========================
# (в ЧАСТИ 3 будут loops + on_message + on_ready)

birthday_check_loop = None
random_banter_loop = None

# ========================= DAILY BANTER LOOP =========================

@tasks.loop(minutes=15)
async def random_banter_loop():

    await bot.wait_until_ready()

    now = now_msk()

    if now.hour not in [11, 18, 22]:
        return

    if random.random() < 0.18:
        await send_akatsuki_banter()


# ========================= BIRTHDAY LOOP (07:00) =========================

@tasks.loop(minutes=1)
async def birthday_check_loop():

    await bot.wait_until_ready()

    now = now_msk()

    # строго 07:00
    if now.hour != 7 or now.minute != 0:
        return

    for uid, data in users_memory.items():

        if not data.get("wife"):
            continue

        birthday = data.get("birthday", "")
        if not birthday:
            continue

        if not is_today_birthday(birthday, now):
            continue

        await send_birthday_message(uid, data)


# ========================= MESSAGE HANDLER =========================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    add_to_history(message.channel.id, "user", message.content)

    mentioned = bot.user in message.mentions

    replied_to_bot = (
        message.reference and
        message.reference.resolved and
        isinstance(message.reference.resolved, discord.Message) and
        message.reference.resolved.author.id == bot.user.id
    )

    has_name = detect_character(message.content)

    reply_needed = False

    if message.channel.id == MAIN_CHANNEL_ID:

        if mentioned or replied_to_bot or has_name:
            reply_needed = True

        elif random.randint(1, 100) <= response_chance:
            reply_needed = True

    if not reply_needed:
        await bot.process_commands(message)
        return

    wife_character = detect_wife(message.author.id)

    if wife_character:
        responder = wife_character
        interrupted = False
        original_target = None
    else:
        responder, interrupted, original_target = choose_responder(message.content)

    system_prompt = BASE_SYSTEM_PROMPT + "\n" + CHARACTER_PROMPTS[responder]

    extra_context = ""

    if wife_character == responder:
        extra_context += """
Это жена персонажа.
Можно быть мягче.
Можно флиртовать.
"""

    if interrupted and original_target:

        interrupt_line = random.choice(
            PARTNER_INTERRUPTS.get(
                (responder, original_target),
                ["Он занят."]
            )
        )

        extra_context += f"""
Ты отвечаешь вместо {AKATSUKI_MEMBERS[original_target]['name']}

Причина:
{interrupt_line}
"""

    history = conversation_history.get(message.channel.id, [])[-6:]

    user_context = f"""
Автор:
{message.author.display_name}

Сообщение:
{message.content}

Отвечает:
{AKATSUKI_MEMBERS[responder]['name']}

{extra_context}

Формат обязателен:
**Имя**: текст
"""

    prompt = (
        [{"role": "system", "content": system_prompt}]
        + history
        + [{"role": "user", "content": user_context}]
    )

    if random.random() < 0.45:
        await add_character_reaction(message, responder)

    async with message.channel.typing():
        reply = await ask_deepseek(prompt)

    if reply:

        clean_reply = reply.strip()

        if not clean_reply.startswith("**"):
            clean_reply = f"**{AKATSUKI_MEMBERS[responder]['name']}**: {clean_reply}"

        try:
            await message.reply(clean_reply, mention_author=False)
        except:
            await message.channel.send(clean_reply)

        add_to_history(
            message.channel.id,
            "assistant",
            f"{AKATSUKI_MEMBERS[responder]['name']}: {reply}"
        )

    await bot.process_commands(message)


# ========================= READY EVENT =========================

@bot.event
async def on_ready():

    print(f"✅ Акацуки бот запущен: {bot.user}")
    print(f"🕒 Moscow time: {now_msk().strftime('%H:%M')}")

    guild = bot.get_guild(GUILD_ID_FOR_EMOJIS)

    if guild:
        await guild.fetch_emojis()
        bot.server_emojis = guild.emojis
        print(f"✅ Emojis loaded: {len(bot.server_emojis)}")

    if not random_banter_loop.is_running():
        random_banter_loop.start()

    if not birthday_check_loop.is_running():
        birthday_check_loop.start()


# ========================= CLEANUP =========================

async def close_http_session():

    global http_session

    if http_session and not http_session.closed:
        await http_session.close()


# ========================= MAIN =========================

async def main():

    try:
        await bot.start(DISCORD_TOKEN)

    finally:
        await close_http_session()


if __name__ == "__main__":
    asyncio.run(main())
    
