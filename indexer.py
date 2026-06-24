import os
import asyncio
import json
import websockets
import psycopg2
import requests

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
    """Get coin data from Pump.fun frontend API"""
    try:
        r = requests.get(f"https://frontend-api-v3.pump.fun/coins/{mint}", timeout=8)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

def get_ipfs_metadata(uri):
    """Try to fetch full metadata from IPFS"""
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
    """Merge data from Pump.fun API + IPFS metadata"""
    mint = data.get("mint")
    if not mint:
        return data

    # First try Pump.fun API
    details = get_coin_details(mint) or {}

    # Fallback to IPFS if twitter is missing
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
    print("Indexer started (with IPFS fallback)...")
    create_table()

    uri = "wss://pumpdev.io/ws"

    while True:
        try:
            async with websockets.connect(uri) as ws:
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                print("Connected to WebSocket")

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
            print(f"WebSocket error: {e}. Reconnecting...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(indexer())
