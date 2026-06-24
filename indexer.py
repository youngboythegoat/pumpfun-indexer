import os
import asyncio
import json
import websockets
import psycopg2
import requests
import random
import time

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Origin": "https://pump.fun",
        "Referer": "https://pump.fun/"
    }

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
        r = requests.get(
            f"https://frontend-api-v3.pump.fun/coins/{mint}",
            headers=get_headers(),
            timeout=8
        )
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

async def poll_latest_coins():
    """Fallback polling when WebSocket is down"""
    print("Polling mode active (WebSocket down)...")
    while True:
        try:
            r = requests.get(
                "https://frontend-api-v3.pump.fun/coins/latest",
                headers=get_headers(),
                timeout=8
            )
            if r.status_code == 200:
                coin = r.json()
                if coin and coin.get("mint"):
                    enriched = enrich_coin_data(coin)
                    save_coin(enriched)
                    print(f"[Poll] Saved: {enriched.get('name')} ({enriched.get('mint')})")
            await asyncio.sleep(8)  # Poll every 8 seconds
        except Exception as e:
            print(f"Polling error: {e}")
            await asyncio.sleep(10)

async def indexer():
    print("Indexer started (WebSocket + fallback)...")
    create_table()

    uri = "wss://pumpdev.io/ws"
    delay = 5
    max_delay = 60
    websocket_healthy = True

    while True:
        try:
            async with websockets.connect(
                uri,
                open_timeout=20,
                ping_interval=20,
                ping_timeout=25
            ) as ws:
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                print("Connected to pumpdev.io WebSocket")
                delay = 5
                websocket_healthy = True

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
            print(f"WebSocket error: {e}. Switching to polling mode...")
            websocket_healthy = False

            # Run polling as fallback
            try:
                await asyncio.wait_for(poll_latest_coins(), timeout=30)
            except asyncio.TimeoutError:
                print("Polling timeout, trying WebSocket again...")

            await asyncio.sleep(delay)
            delay = min(delay * 2 + random.uniform(0, 3), max_delay)

if __name__ == "__main__":
    asyncio.run(indexer())
