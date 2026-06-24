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

# ==================== COMMANDS ====================

@tree.command(name="find", description="Find coins linked to a tweet")
@app_commands.describe(tweet="Tweet URL or Tweet ID")
async def find(interaction: discord.Interaction, tweet: str):
    await interaction.response.defer()  # Show "thinking..." while searching

    tweet_id = extract_tweet_id(tweet)
    if not tweet_id:
        await interaction.followup.send("Invalid tweet URL or ID.")
        return

    results = search_coins_by_tweet(tweet_id)

    if not results:
        await interaction.followup.send("No matching coins found in the database.")
        return

    # Send results
    message = f"**Found {len(results)} matching coin(s):**\n\n"
    for coin in results[:5]:  # Limit to 5 results for now
        message += f"**{coin['name']} (${coin['symbol']})**\n"
        message += f"Mint: `{coin['mint']}`\n"
        message += f"[View on pump.fun]({coin['pump_link']})\n\n"

    await interaction.followup.send(message)

# ==================== HELPERS ====================

def extract_tweet_id(text: str):
    import re
    if text.isdigit():
        return text
    for pattern in [r"(?:x\.com|twitter\.com)/[^/]+/status/(\d+)", r"status/(\d+)"]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None

def search_coins_by_tweet(tweet_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT mint, name, symbol, created_at
            FROM pumpfun_coins
            WHERE twitter ILIKE %s OR description ILIKE %s
            ORDER BY created_at DESC
            LIMIT 10
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

# ==================== BOT EVENTS ====================

@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")
    await tree.sync()  # Sync slash commands

# ==================== RUN BOT ====================

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
