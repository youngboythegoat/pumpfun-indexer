import os
import discord
from discord import app_commands
import psycopg2

# ==================== CONFIG ====================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# ==================== DATABASE FUNCTIONS ====================

def add_subscription(user_id: int, tweet_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO user_subscriptions (user_id, tweet_id)
            VALUES (%s, %s)
            ON CONFLICT (user_id, tweet_id) DO NOTHING;
        """, (user_id, tweet_id))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def get_user_subscriptions(user_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT tweet_id FROM user_subscriptions 
            WHERE user_id = %s 
            ORDER BY created_at DESC
        """, (user_id,))
        return [row[0] for row in cur.fetchall()]
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

def extract_tweet_id(text: str):
    import re
    if text.isdigit():
        return text
    for pattern in [r"(?:x\.com|twitter\.com)/[^/]+/status/(\d+)", r"status/(\d+)"]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None

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
@app_commands.describe(tweet="Tweet URL or Tweet ID")
async def notify(interaction: discord.Interaction, tweet: str):
    tweet_id = extract_tweet_id(tweet)
    if not tweet_id:
        await interaction.response.send_message("Invalid tweet URL or ID.", ephemeral=True)
        return

    add_subscription(interaction.user.id, tweet_id)
    await interaction.response.send_message(
        f"✅ You will now be notified when a coin matching this tweet appears.\nTweet ID: `{tweet_id}`",
        ephemeral=True
    )


@tree.command(name="mynotifications", description="See all tweets you're subscribed to")
async def mynotifications(interaction: discord.Interaction):
    subscriptions = get_user_subscriptions(interaction.user.id)
    if not subscriptions:
        await interaction.response.send_message("You have no active notifications.", ephemeral=True)
        return

    message = "**Your active notifications:**\n"
    for tweet_id in subscriptions:
        message += f"• `{tweet_id}`\n"
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
    await tree.sync()
    print("Slash commands synced.")

# ==================== RUN BOT ====================

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
