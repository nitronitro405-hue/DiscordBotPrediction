import os
import discord
from discord.ext import commands, tasks
import asyncio
import re

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SOURCE_CHANNEL_ID = 1515729737367031828
TARGET_CHANNEL_ID = 1516526798102466651
TARGET_USER_ID = 1515735234237300787

BACKFILL_COUNT = 10

try:
    intents = discord.Intents.default()
    bot = commands.Bot(command_prefix="!", self_bot=True, intents=intents)
except AttributeError:
    bot = commands.Bot(command_prefix="!", self_bot=True)

message_map = {}
last_content = {}

latest_stock = {}

def parse_stock_data(message):
    if not message.embeds:
        return
    
    embed = message.embeds[0]
    data = embed.to_dict() if hasattr(embed, 'to_dict') else embed
    
    shop_name = data.get("title", "Unknown Shop")
    fields = data.get("fields", [])
    
    items = {}
    for field in fields:
        field_name = field.get("name", "")
        field_value = field.get("value", "")
        
        timestamps = re.findall(r'<t:(\d+):[RrTtDdFf]>', field_name + " " + field_value)
        best_ts = timestamps[0] if timestamps else None
        
        for line in field_value.split('\n'):
            item_match = re.match(r'\*\*(.+?)\*\*', line)
            if item_match:
                item_name = item_match.group(1).strip()
                items[item_name.lower()] = {
                    "name": item_name,
                    "raw": line,
                    "timestamp": best_ts
                }
    
    latest_stock[shop_name.lower()] = {
        "name": shop_name,
        "items": items,
        "fields": fields,
        "raw_data": data
    }

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
        parse_stock_data(message)
        return embed_to_text(message.embeds[0])
    return message.content

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    
    try:
        activity = discord.Activity(type=discord.ActivityType.playing, name="Predicting restocks...")
        await bot.change_presence(activity=activity)
    except:
        pass
    
    source = bot.get_channel(SOURCE_CHANNEL_ID)
    target = bot.get_channel(TARGET_CHANNEL_ID)

    print("Loading stock data...")
    async for message in source.history(limit=50):
        if message.author.id == TARGET_USER_ID and message.embeds:
            parse_stock_data(message)
    
    print(f"Loaded {len(latest_stock)} shops")

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
    print("Ready - try !when ShopName ItemName")

@bot.command()
async def when(ctx, shop: str, *, item: str):
    """Check when an item restocks. Usage: !when ShopName ItemName"""
    shop_key = shop.lower().replace(" ", "")
    item_key = item.lower()
    
    found_shop = None
    for key, shop_data in latest_stock.items():
        if shop_key in key or key in shop_key:
            found_shop = shop_data
            break
    
    if not found_shop:
        await ctx.send(f"❌ Shop '{shop}' not found. Available: {', '.join(s['name'] for s in latest_stock.values())}")
        return
    
    found_item = None
    for key, item_data in found_shop["items"].items():
        if item_key in key or key in item_key:
            found_item = item_data
            break
    
    if not found_item:
        items_list = "\n".join([f"• {i['name']}" for i in found_shop["items"].values()])
        await ctx.send(f"❌ Item '{item}' not found in {found_shop['name']}.\n**Available items:**\n{items_list}")
        return
    
    ts = found_item.get("timestamp")
    
    if ts:
        await ctx.send(f"✅ **{found_item['name']}** stocks in <t:{ts}:R>")
    else:
        all_ts = []
        for field in found_shop["fields"]:
            all_ts.extend(re.findall(r'<t:(\d+):[RrTtDdFf]>', field.get("name", "") + " " + field.get("value", "")))
        
        if all_ts:
            best_ts = all_ts[0]
            await ctx.send(f"✅ **{found_item['name']}** stocks in <t:{best_ts}:R>")
        else:
            await ctx.send(f"ℹ️ **{found_item['name']}** is available now in {found_shop['name']}!")

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
    # Let commands process first
    await bot.process_commands(message)
    
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
