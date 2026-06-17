import os
import discord
from discord.ext import commands, tasks
import asyncio

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SOURCE_CHANNEL_ID = 1515729737367031828
TARGET_CHANNEL_ID = 1516526798102466651
TARGET_USER_ID = 1515735234237300787

BACKFILL_COUNT = 10

# Handle both discord.py and discord.py-self
try:
    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix="!", self_bot=True, intents=intents)
except AttributeError:
    bot = commands.Bot(command_prefix="!", self_bot=True)

message_map = {}
last_content = {}

def embed_to_text(embed):
    data = embed.to_dict() if hasattr(embed, 'to_dict') else embed
    lines = []

    title = data.get("title")
    desc = data.get("description")

    if title:
        lines.append(f"📌 **{title}**")
    if desc:
        lines.append(f"\n{desc}")

    fields = data.get("fields", [])
    if fields:
        lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
        for field in fields:
            lines.append(f"\n🔹 **{field['name']}**")
            lines.append(f"   {field['value']}")

    if data.get("image"):
        lines.append(f"\n🖼️ {data['image']['url']}")
    if data.get("thumbnail"):
        lines.append(f"\n{data['thumbnail']['url']}")

    footer = data.get("footer", {})
    if footer.get("text"):
        lines.append(f"\n📝 *{footer['text']}*")

    return "\n".join(lines)

def get_message_text(message):
    if message.embeds:
        return embed_to_text(message.embeds[0])
    return message.content

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    source = bot.get_channel(SOURCE_CHANNEL_ID)
    target = bot.get_channel(TARGET_CHANNEL_ID)

    print(f"Backfilling last {BACKFILL_COUNT} messages...")
    count = 0
    async for message in source.history(limit=BACKFILL_COUNT):
        if message.author.id != TARGET_USER_ID:
            continue
        text = get_message_text(message)
        sent = await target.send(text)
        message_map[message.id] = sent.id
        last_content[message.id] = text
        count += 1
        await asyncio.sleep(0.5)
    
    print(f"Backfilled {count} messages")
    check_edits.start()
    print("Ready")

@tasks.loop(seconds=1)
async def check_edits():
    source = bot.get_channel(SOURCE_CHANNEL_ID)
    target = bot.get_channel(TARGET_CHANNEL_ID)
    if not source or not target:
        return

    for msg_id, target_msg_id in list(message_map.items()):
        try:
            message = await source.fetch_message(msg_id)
            if message.author.id != TARGET_USER_ID:
                continue
            current = get_message_text(message)
            previous = last_content.get(msg_id)

            if current != previous:
                print(f"Edit detected for {msg_id}")
                try:
                    target_msg = await target.fetch_message(target_msg_id)
                    await target_msg.edit(content=current)
                    last_content[msg_id] = current
                except discord.NotFound:
                    del message_map[msg_id]
                    last_content.pop(msg_id, None)
                except Exception as e:
                    print(f"Error editing: {e}")
        except discord.NotFound:
            del message_map[msg_id]
            last_content.pop(msg_id, None)
        except:
            pass

@bot.event
async def on_message(message):
    if message.author.id != TARGET_USER_ID:
        return
    if message.channel.id != SOURCE_CHANNEL_ID:
        return

    target = bot.get_channel(TARGET_CHANNEL_ID)
    if not target:
        return

    try:
        text = get_message_text(message)
        sent = await target.send(text)
        message_map[message.id] = sent.id
        last_content[message.id] = text
    except Exception as e:
        print(f"Error: {e}")

bot.run(DISCORD_TOKEN)
