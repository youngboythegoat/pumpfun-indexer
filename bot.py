import os
import discord
from discord import app_commands
from discord.ext import tasks
import psycopg2
from datetime import datetime, timedelta

# ==================== CONFIG ====================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Only sync to your testing server for fast development
GUILD_IDS = [
    1519304243532529775   # Testing server only
]

intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# ==================== DATABASE FUNCTIONS ====================

def add_subscription(user_id: int, tweet_id: str, channel_id: int = None):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO user_subscriptions (user_id, tweet_id, channel_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, tweet_id) DO UPDATE 
            SET channel_id = EXCLUDED.channel_id;
        """, (user_id, tweet_id, channel_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def get_user_subscriptions(user_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT tweet_id, channel_id FROM user_subscriptions 
            WHERE user_id = %s 
            ORDER BY created_at DESC
        """, (user_id,))
        return [{"tweet_id": row[0], "channel_id": row[1]} for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

def remove_subscription(user_id: int, tweet_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            DELETE FROM user_subscriptions 
            WHERE user_id = %s AND tweet_id = %s
        """, (user_id, tweet_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def search_coins_by_tweet(tweet_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT mint, name, symbol, created_at
            FROM pumpfun_coins
            WHERE twitter ILIKE %s OR description ILIKE %s
            ORDER BY created_at DESC
            LIMIT 5
        """, (f"%{tweet_id}%", f"%{tweet_id}%"))
        
        rows = cur.fetchall()
        results = []
        for row in rows:
            results.append({
                "mint": row[0],
                "name": row[1],
                "symbol": row[2],
                "created_at": row[3],
                "pump_link": f"https://pump.fun/coin/{row[0]}"
            })
        return results
    finally:
        cur.close()
        conn.close()

def get_recent_coins(minutes: int = 10):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        since = datetime.utcnow() - timedelta(minutes=minutes)
        cur.execute("""
            SELECT mint, name, symbol, twitter, created_at
            FROM pumpfun_coins
            WHERE created_at >= %s
            ORDER BY created_at DESC
        """, (since,))
        
        rows = cur.fetchall()
        results = []
        for row in rows:
            results.append({
                "mint": row[0],
                "name": row[1],
                "symbol": row[2],
                "twitter": row[3],
                "created_at": row[4],
                "pump_link": f"https://pump.fun/coin/{row[0]}"
            })
        return results
    finally:
        cur.close()
        conn.close()

def get_subscribers_for_tweet(tweet_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT user_id, channel_id FROM user_subscriptions 
            WHERE tweet_id = %s
        """, (tweet_id,))
        return [{"user_id": row[0], "channel_id": row[1]} for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

def has_been_notified(user_id: int, mint: str):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT 1 FROM sent_notifications 
            WHERE user_id = %s AND mint = %s
        """, (user_id, mint))
        return cur.fetchone() is not None
    finally:
        cur.close()
        conn.close()

def record_notification(user_id: int, mint: str):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO sent_notifications (user_id, mint)
            VALUES (%s, %s)
            ON CONFLICT (user_id, mint) DO NOTHING;
        """, (user_id, mint))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def extract_tweet_id(text: str):
    import re
    if text.isdigit():
        return text
    for pattern in [r"(?:x\.com|twitter\.com)/[^/]+/status/(\d+)", r"status/(\d+)"]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None

# ==================== NOTIFICATION TASK ====================

@tasks.loop(seconds=45)
async def check_for_new_coins():
    try:
        recent_coins = get_recent_coins(minutes=10)
        
        for coin in recent_coins:
            subscribers = get_subscribers_for_tweet(coin.get("twitter") or "")
            
            for sub in subscribers:
                user_id = sub["user_id"]
                channel_id = sub["channel_id"]

                if has_been_notified(user_id, coin["mint"]):
                    continue

                embed = discord.Embed(
                    title=f"New Coin Found: {coin['name']} (${coin['symbol']})",
                    description=f"A new coin matching your notification was just deployed!",
                    color=discord.Color.green()
                )
                embed.add_field(name="Mint", value=f"`{coin['mint']}`", inline=False)
                embed.add_field(name="View on pump.fun", value=coin['pump_link'], inline=False)
                embed.set_footer(text="marv's pumpfun alpha tweet search")

                try:
                    if channel_id:
                        channel = bot.get_channel(channel_id)
                        if channel:
                            await channel.send(content=f"<@{user_id}>", embed=embed)
                        else:
                            user = await bot.fetch_user(user_id)
                            await user.send(embed=embed)
                    else:
                        user = await bot.fetch_user(user_id)
                        await user.send(embed=embed)

                    record_notification(user_id, coin["mint"])
                    print(f"Sent notification to {user_id} for {coin['mint']}")

                except Exception as e:
                    print(f"Failed to send notification to {user_id}: {e}")

    except Exception as e:
        print(f"Notification task error: {e}")

# ==================== COMMANDS ====================

@tree.command(name="find", description="Find coins linked to a tweet")
@app_commands.describe(tweet="Tweet URL or Tweet ID")
async def find(interaction: discord.Interaction, tweet: str):
    await interaction.response.defer()
    tweet_id = extract_tweet_id(tweet)
    if not tweet_id:
        await interaction.followup.send("Invalid tweet URL or ID.")
        return

    results = search_coins_by_tweet(tweet_id)
    if not results:
        await interaction.followup.send("No matching coins found.")
        return

    message = f"**Found {len(results)} matching coin(s):**\n\n"
    for coin in results:
        message += f"**{coin['name']} (${coin['symbol']})**\n"
        message += f"Mint: `{coin['mint']}`\n"
        message += f"[View on pump.fun]({coin['pump_link']})\n\n"

    await interaction.followup.send(message)

@tree.command(name="notify", description="Get notified when a coin matching this tweet appears")
@app_commands.describe(
    tweet="Tweet URL or Tweet ID",
    channel="Channel where you want notifications (optional - leave empty for DM)"
)
async def notify(interaction: discord.Interaction, tweet: str, channel: discord.TextChannel = None):
    tweet_id = extract_tweet_id(tweet)
    if not tweet_id:
        await interaction.response.send_message("Invalid tweet URL or ID.", ephemeral=True)
        return

    channel_id = channel.id if channel else None
    add_subscription(interaction.user.id, tweet_id, channel_id)

    if channel:
        await interaction.response.send_message(
            f"✅ You will be notified in {channel.mention} when a coin matching this tweet appears.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"✅ You will be notified via **DM** when a coin matching this tweet appears.\nTweet ID: `{tweet_id}`",
            ephemeral=True
        )

@tree.command(name="mynotifications", description="See all tweets you're subscribed to")
async def mynotifications(interaction: discord.Interaction):
    subscriptions = get_user_subscriptions(interaction.user.id)
    if not subscriptions:
        await interaction.response.send_message("You have no active notifications.", ephemeral=True)
        return

    message = "**Your active notifications:**\n"
    for sub in subscriptions:
        ch = f" → <#{sub['channel_id']}>" if sub['channel_id'] else " (DM)"
        message += f"• `{sub['tweet_id']}`{ch}\n"
    await interaction.response.send_message(message, ephemeral=True)

@tree.command(name="stopnotify", description="Stop getting notifications for a tweet")
@app_commands.describe(tweet="Tweet URL or Tweet ID")
async def stopnotify(interaction: discord.Interaction, tweet: str):
    tweet_id = extract_tweet_id(tweet)
    if not tweet_id:
        await interaction.response.send_message("Invalid tweet URL or ID.", ephemeral=True)
        return

    remove_subscription(interaction.user.id, tweet_id)
    await interaction.response.send_message(
        f"✅ You will no longer receive notifications for tweet ID: `{tweet_id}`",
        ephemeral=True
    )

# ==================== BOT EVENTS ====================

@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")
    
    # Sync commands only to your testing server
    for guild_id in GUILD_IDS:
        guild = discord.Object(id=guild_id)
        await tree.sync(guild=guild)
        print(f"Commands synced to testing server ({guild_id})")
    
    if not check_for_new_coins.is_running():
        check_for_new_coins.start()
        print("Notification task started.")

# ==================== RUN BOT ====================

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
