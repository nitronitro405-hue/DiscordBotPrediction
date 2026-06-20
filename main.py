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

def parse_items_from_text(text):
    """Extract item names and timestamps from field text"""
    items = {}
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        
        # Find timestamps
        timestamps = re.findall(r'<t:(\d+):[RrTtDdFf]>', line)
        best_ts = timestamps[0] if timestamps else None
        
        # Try to extract item name - look for **name** pattern first
        item_match = re.match(r'\*\*(.+?)\*\*', line)
        if item_match:
            item_name = item_match.group(1).strip()
            items[item_name.lower()] = {
                "name": item_name,
                "raw": line,
                "timestamp": best_ts
            }
    return items

def parse_stock_data(message):
    if not message.embeds:
        return
    
    embed = message.embeds[0]
    data = embed.to_dict() if hasattr(embed, 'to_dict') else embed
    
    shop_name = data.get("title", "Unknown Shop")
    desc = data.get("description", "")
    fields = data.get("fields", [])
    
    items = {}
    
    # Parse description for timestamps
    desc_timestamps = re.findall(r'<t:(\d+):[RrTtDdFf]>', desc)
    global_ts = desc_timestamps[0] if desc_timestamps else None
    
    for field in fields:
        field_name = field.get("name", "")
        field_value = field.get("value", "")
        
        # Get timestamps from field name
        field_ts_list = re.findall(r'<t:(\d+):[RrTtDdFf]>', field_name)
        field_ts = field_ts_list[0] if field_ts_list else global_ts
        
        # Parse items from this field
        field_items = parse_items_from_text(field_value)
        
        # If items don't have their own timestamp, use the field's timestamp
        for key, item_data in field_items.items():
            if not item_data["timestamp"]:
                item_data["timestamp"] = field_ts
        
        items.update(field_items)
    
    latest_stock[shop_name.lower()] = {
        "name": shop_name,
        "items": items,
        "fields": fields,
        "raw_data": data
    }
    
    print(f"Parsed {shop_name}: {len(items)} items")

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
    for shop_name in latest_stock:
        print(f"  - {latest_stock[shop_name]['name']}: {len(latest_stock[shop_name]['items'])} items")

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
    print("Ready - try: !when Gear Shop Watering Can")

@bot.command()
async def when(ctx, *, query: str):
    """Check when an item restocks. Usage: !when <item name>"""
    query_lower = query.lower().strip()
    
    # Search all shops for the item
    found_results = []
    
    for shop_key, shop_data in latest_stock.items():
        for item_key, item_data in shop_data["items"].items():
            if query_lower in item_key or item_key in query_lower:
                found_results.append((shop_data["name"], item_data))
    
    if not found_results:
        # List all available items
        all_items = []
        for shop_data in latest_stock.values():
            for item_data in shop_data["items"].values():
                all_items.append(f"• {item_data['name']} ({shop_data['name']})")
        
        items_preview = "\n".join(all_items[:20])
        if len(all_items) > 20:
            items_preview += f"\n...and {len(all_items) - 20} more"
        
        await ctx.send(f"❌ Item '{query}' not found.\n**Available items:**\n{items_preview}")
        return
    
    # Return results
    if len(found_results) == 1:
        shop_name, item = found_results[0]
        ts = item.get("timestamp")
        if ts:
            await ctx.send(f"✅ **{item['name']}** stocks in <t:{ts}:R> (<t:{ts}:f>)")
        else:
            await ctx.send(f"ℹ️ **{item['name']}** is in stock now at **{shop_name}**!")
    else:
        # Multiple matches - show all
        lines = [f"🔍 Found {len(found_results)} matches for '{query}':"]
        for shop_name, item in found_results:
            ts = item.get("timestamp")
            time_str = f"<t:{ts}:R>" if ts else "Now"
            lines.append(f"• **{item['name']}** ({shop_name}) — {time_str}")
        
        await ctx.send("\n".join(lines))

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
