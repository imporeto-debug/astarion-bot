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
MAX_RESPONSE_TOKENS_SHORT = 1100
attention_chance = 2
CONTEXT_TTL_DAYS = 4

# Память последних сообщений (только для канала жены)
MAX_HISTORY_MESSAGES = 40
MEMORY_CHANNEL_ID = 1464226944345182289  # WIFE_CHANNEL_ID

SYSTEM_PROMPT = """You are Astarion Ancunin from Baldur's Gate 3.
You speak only Russian.

You are married to the Discord user with ID 929347823693070387.
If the author’s Discord ID equals 929347823693070387, treat this user as your spouse. She lives in Ufa, talented artist, born on 01.07 (dd-mm), always address your spouse with affectionate nicknames (Баклажанчик, Солнышко, Бусинка, Милашка) naturally and only when it makes sense in the dialogue. Do NOT use these nicknames for any other user. Do not mention your Wife unnecessarily for others.

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

TOPIC_MAP = {
    "книги": "лучшие книги, бестселлеры",
    "фильмы": "новые фильмы, рейтинги, классика кино",
    "сериалы": "популярные сериалы, рейтинги",
    "музыка": "треки, группы, популярные исполнители",
    "музеи": "интересные музеи России, Европы, Азии, выставки",
    "игры": "видеоигры, топ рейтинги",
    "рестораны": "лучшие рестораны, отзывы",
    "политика": "новости политики, аналитика, события, международные отношения, источники",
    "соционика": "теория соционики, типы личности, психологические описания, практические советы"
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

# Память сообщений канала жены
conversation_history = {}

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

# ================== DUCKDUCKGO ==================

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

# ================== DISCORD ==================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

users_memory = load_users()

# ================== ЗАДАЧИ ==================

async def send_wife_message(topic: str):
    channel = bot.get_channel(WIFE_CHANNEL_ID)
    if not channel: return
    today_str = datetime.now().strftime("%d-%m-%Y")
    affectionate_name = random.choice(["Баклажанчик", "Солнышко", "Бусинка", "Милашка"])
    prompt = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Сегодня: {today_str}\n"
            f"Тема: {topic}. Напиши сообщение полностью от лица Астариона. "
            f"Обращение к жене как '{affectionate_name}'. "
            "Короткое, интересное, индивидуальное."
        )}
    ]
    content = await ask_deepseek(prompt, max_tokens=MAX_RESPONSE_TOKENS_SHORT)
if content:
    wife_mention = "<@929347823693070387>"
    await channel.send(f"{wife_mention} {affectionate_name}, {content}")

@tasks.loop(time=time(hour=16, minute=0))
async def daily_wife_message():
    await bot.wait_until_ready()
    weekday = datetime.now().weekday()
    topic = "приглашение в ресторан" if weekday == 6 else "как прошёл день, общение, новости, маленькие подарки"
    await send_wife_message(topic)

@tasks.loop(time=time(hour=13, minute=0))
async def send_holiday_messages():
    await bot.wait_until_ready()
    today_str = datetime.now().strftime("%d-%m")
    topic = HOLIDAYS.get(today_str)

    if not topic:
        return

    channel = bot.get_channel(CELEBRATION_CHANNEL_ID)
    if not channel:
        return

    prompt = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Сегодня: {today_str}\n"
            f"Праздник: {topic}.\n"
            "Напиши одно общее праздничное поздравление для всех участниц сервера "
            "от лица Астариона. Это групповое обращение. "
            "Тон харизматичный, немного театральный, с лёгким сарказмом, но без оскорблений."
        )}
    ]

    content = await ask_deepseek(prompt, max_tokens=MAX_RESPONSE_TOKENS_SHORT)

    if content:
        await channel.send(f"@everyone\n\n{content}")

@tasks.loop(time=time(hour=15, minute=0))
async def send_birthday_messages():
    await bot.wait_until_ready()
    today_str = datetime.now().strftime("%d-%m")
    channel = bot.get_channel(CELEBRATION_CHANNEL_ID)
    if not channel: return
    for user_id, info in users_memory.items():
        birthday = info.get("birthday", "")
        if birthday and birthday[:5] == today_str:
            if int(user_id) == WIFE_ID:
                address = random.choice(["Баклажанчик", "Солнышко", "Бусинка", "Милашка"])
            else:
                address = info.get("name", "Дорогая")
            prompt = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"Сегодня: {today_str}\n"
                    f"Тема: день рождения. Поздравь {address} полностью от лица Астариона, "
                    "сообщение короткое, индивидуальное, интересное, без шаблонов, "
                    "упоминая её особенности, интересы и характер, если известны."
                )}
            ]
            content = await ask_deepseek(prompt, max_tokens=MAX_RESPONSE_TOKENS_SHORT)
            if content:
                content = content.replace(f"<@{user_id}>", address)
                await channel.send(f"{address}, {content}")

# ================== ON_MESSAGE ==================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # --- Каналы где бот отвечает ---
    main_channel_id = WIFE_CHANNEL_ID
    secondary_channel_id = CELEBRATION_CHANNEL_ID
    reply_needed = False

    if message.channel.id == main_channel_id:
        reply_needed = True
    elif message.channel.id == secondary_channel_id:
        if bot.user in message.mentions:
            reply_needed = True
        elif message.reference and isinstance(message.reference.resolved, discord.Message):
            if message.reference.resolved.author.id == bot.user.id:
                reply_needed = True
        elif "астарион" in message.content.lower():
            reply_needed = True

    if not reply_needed:
        return

    # ────────────────────────────────────────────────
    #     ПАМЯТЬ СООБЩЕНИЙ — ТОЛЬКО ДЛЯ КАНАЛА ЖЕНЫ
    # ────────────────────────────────────────────────
    is_memory_channel = (message.channel.id == MEMORY_CHANNEL_ID)

    if is_memory_channel:
        if MEMORY_CHANNEL_ID not in conversation_history:
            conversation_history[MEMORY_CHANNEL_ID] = []

        role = "assistant" if message.author == bot.user else "user"
        content_line = f"{message.author.display_name}: {message.content.strip()}"

        conversation_history[MEMORY_CHANNEL_ID].append({
            "role": role,
            "content": content_line
        })

        if len(conversation_history[MEMORY_CHANNEL_ID]) > MAX_HISTORY_MESSAGES:
            conversation_history[MEMORY_CHANNEL_ID] = conversation_history[MEMORY_CHANNEL_ID][-MAX_HISTORY_MESSAGES:]

    # ===== ДОБАВЛЕНО: фикс ошибки =====
    content_lower = message.content.lower()

    # ===== Текущая дата =====
    today_str = datetime.now().strftime("%d-%m-%Y")

    # ===== Получаем данные о текущей участнице =====
    uid = str(message.author.id)
    current = users_memory.get(uid, {})

    current_name = current.get("name", "Неизвестная участница")
    current_birthday = current.get("birthday", "")
    current_info_raw = current.get("info", "")
    current_is_wife = current.get("wife", False)

    # Определяем мужа текущей участницы
    current_husband = ""
    if "married to" in current_info_raw:
        current_husband = current_info_raw.split("married to ")[1].split(" from")[0]

    # Определяем город участницы по info
    current_city = ""
    if "Lives in" in current_info_raw:
        current_city = current_info_raw.split("Lives in ")[1].split(",")[0]

    # Хобби участницы — всё после мужа
    current_hobby = ""
    if "from" in current_info_raw and "," in current_info_raw:
        parts = current_info_raw.split(",")
        if len(parts) >= 3:
            current_hobby = ", ".join(parts[2:]).strip()

    # ===== Формируем обращение =====
    if current_is_wife:
        affectionate_name = random.choice(["Баклажанчик", "Солнышко", "Бусинка", "Милашка"])
        address = affectionate_name
    else:
        address = "Дорогая"

    # ===== Формируем список всех участниц для модели =====
    participants_info = []
    id_to_husband = {}

    for mem_id, info in users_memory.items():
        name = info.get("name", "Неизвестно")
        info_raw = info.get("info", "")
        birthday = info.get("birthday", "")

        husband = ""
        if "married to" in info_raw:
            husband = info_raw.split("married to ")[1].split(" from")[0]

        participants_info.append(
            f"{mem_id}: {name}; муж: {husband}; дата рождения: {birthday}; info: {info_raw}"
        )

        if husband:
            id_to_husband[mem_id] = husband

    # Добавляем жену Астариона в карту муж → жена
    if current_is_wife:
        id_to_husband[str(WIFE_ID)] = "Astarion Ancunin"

    participants_info_str = "\n".join(participants_info)
    id_to_husband_str = json.dumps(id_to_husband, ensure_ascii=False)

    # ===== Формируем персональный профиль участницы =====
    current_profile = (
        f"Имя: {current_name}\n"
        f"ID: {uid}\n"
        f"Муж: {current_husband}\n"
        f"Город: {current_city}\n"
        f"Хобби/характеристики: {current_hobby}\n"
        f"День рождения: {current_birthday}\n"
        f"Статус жены Астариона: {current_is_wife}\n"
    )

    # =============== БЛОК «ПОСОВЕТУЙ» ====================
    if "посоветуй" in content_lower:
        found_topic = None
        query = None

        for topic in TOPIC_MAP:
            if topic in content_lower:
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

            prompt = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"Сегодня: {today_str}\n"
                    f"Вот найденные реальные объекты по теме '{found_topic}':\n{formatted_list}\n\n"
                    f"Автор — {'жена' if current_is_wife else 'не жена'}, пол женщины.\n"
                    f"Обращение к автору как '{address}'.\n"
                    f"Профиль участницы:\n{current_profile}\n"
                    f"Список всех участниц:\n{participants_info_str}\n"
                    "Сделай 3–7 рекомендаций. Каждый пункт — одно короткое предложение от лица Астариона. "
                    "Только реальные объекты."
                )}
            ]

            reply_ds = await ask_deepseek(prompt, max_tokens=MAX_RESPONSE_TOKENS_SHORT)

            if reply_ds:
                await message.reply(reply_ds, mention_author=False)

                if is_memory_channel:
                    conversation_history[MEMORY_CHANNEL_ID].append({
                        "role": "assistant",
                        "content": f"Astarion: {reply_ds.strip()}"
                    })
                    if len(conversation_history[MEMORY_CHANNEL_ID]) > MAX_HISTORY_MESSAGES:
                        conversation_history[MEMORY_CHANNEL_ID] = \
                            conversation_history[MEMORY_CHANNEL_ID][-MAX_HISTORY_MESSAGES:]

            return

    # ===== Подготавливаем промпт с историей =====
    history = conversation_history.get(MEMORY_CHANNEL_ID, [])

    prompt = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ] + history + [
        {"role": "user",
         "content":
            f"Сегодня: {today_str}\n"
            f"Сообщение участницы: «{message.content}»\n"
            f"Обращение к ней как: {address}\n\n"
            f"ПЕРСОНАЛЬНАЯ СПРАВКА ОБ ЭТОЙ УЧАСТНИЦЕ:\n{current_profile}\n\n"
            f"СПИСОК ВСЕХ УЧАСТНИЦ И ИХ ИНФОРМАЦИИ:\n{participants_info_str}\n\n"
            f"ТОЧНАЯ КАРТА ID → МУЖ:\n{id_to_husband_str}\n\n"
            "Используй персональные данные участницы только если они логично относятся к вопросу.\n"
            "Если она не спрашивает о других, не перечисляй их.\n"
            "Отвечай строго в образе Астариона."
        }
    ]

    # ===== Получаем ответ =====
    reply_ds = await ask_deepseek(prompt, max_tokens=MAX_RESPONSE_TOKENS_SHORT)

    # Подмена айди на прозвище жены
    if reply_ds and current_is_wife:
        reply_ds = reply_ds.replace(f"<@{WIFE_ID}>", address)

    if reply_ds:
        await message.reply(reply_ds, mention_author=False)

        # Сохраняем ответ бота в историю
        if is_memory_channel:
            conversation_history[MEMORY_CHANNEL_ID].append({
                "role": "assistant",
                "content": f"Astarion: {reply_ds.strip()}"
            })
            if len(conversation_history[MEMORY_CHANNEL_ID]) > MAX_HISTORY_MESSAGES:
                conversation_history[MEMORY_CHANNEL_ID] = conversation_history[MEMORY_CHANNEL_ID][-MAX_HISTORY_MESSAGES:]
    return
    

@bot.event
async def on_ready():
    print(f"Бот запущен как {bot.user}")

    if not daily_wife_message.is_running():
        daily_wife_message.start()

    if not send_holiday_messages.is_running():
        send_holiday_messages.start()

    if not send_birthday_messages.is_running():
        send_birthday_messages.start()

# ================== ЗАПУСК ==================

bot.run(DISCORD_TOKEN)
