import os
import asyncio
import json
import websockets
import psycopg2
import requests
import random

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def create_table():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pumpfun_coins (
            mint TEXT PRIMARY KEY,
            name TEXT,
            symbol TEXT,
            twitter TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("Table ready.")

def save_coin(coin_data):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO pumpfun_coins (mint, name, symbol, twitter, description)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (mint) DO NOTHING;
        """, (
            coin_data.get("mint"),
            coin_data.get("name"),
            coin_data.get("symbol"),
            coin_data.get("twitter"),
            coin_data.get("description")
        ))
        conn.commit()
    except Exception as e:
        print(f"DB Error: {e}")
    finally:
        cur.close()
        conn.close()

def get_coin_details(mint):
    try:
        r = requests.get(f"https://frontend-api-v3.pump.fun/coins/{mint}", timeout=8)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

def get_ipfs_metadata(uri):
    if not uri or not uri.startswith("https://"):
        return None
    try:
        r = requests.get(uri, timeout=10)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

def enrich_coin_data(data):
    mint = data.get("mint")
    if not mint:
        return data

    details = get_coin_details(mint) or {}

    twitter = details.get("twitter") or data.get("twitter")
    description = details.get("description") or data.get("description")

    if not twitter and data.get("uri"):
        ipfs_data = get_ipfs_metadata(data["uri"])
        if ipfs_data:
            twitter = twitter or ipfs_data.get("twitter")
            description = description or ipfs_data.get("description")

    return {
        "mint": mint,
        "name": details.get("name") or data.get("name"),
        "symbol": details.get("symbol") or data.get("symbol"),
        "twitter": twitter,
        "description": description
    }

async def indexer():
    print("Indexer started...")
    create_table()

    uri = "wss://pumpdev.io/ws"
    delay = 5          # Starting delay
    max_delay = 60

    while True:
        try:
            async with websockets.connect(
                uri,
                open_timeout=30,       # Timeout for opening handshake
                ping_interval=20,
                ping_timeout=30,
                close_timeout=10
            ) as ws:
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                print("Connected to WebSocket")

                delay = 5  # Reset delay after successful connection

                async for message in ws:
                    try:
                        data = json.loads(message)

                        if data.get("txType") == "create":
                            mint = data.get("mint")
                            if mint:
                                enriched = enrich_coin_data(data)
                                save_coin(enriched)
                                print(f"Saved: {enriched.get('name')} ({mint})")

                    except Exception as e:
                        print(f"Message error: {e}")

        except Exception as e:
            print(f"WebSocket error: {e}. Reconnecting in {delay} seconds...")
            await asyncio.sleep(delay)
            # Exponential backoff with jitter
            delay = min(delay * 2 + random.uniform(0, 3), max_delay)

if __name__ == "__main__":
    asyncio.run(indexer())
