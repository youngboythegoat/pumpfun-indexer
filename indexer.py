import os
import asyncio
import json
import websockets
import psycopg2
import requests

DATABASE_URL = os.getenv("DATABASE_URL")
HELIUS_API_KEY = "1d048ec7-f627-49aa-81dc-6ef329fc8028"

PUMP_FUN_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

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
    print("Indexer started with Helius (improved parsing)...")
    create_table()

    uri = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

    while True:
        try:
            async with websockets.connect(uri) as ws:
                subscribe_msg = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "transactionSubscribe",
                    "params": [
                        {
                            "commitment": "confirmed",
                            "filter": {
                                "mentions": [PUMP_FUN_PROGRAM_ID]
                            }
                        }
                    ]
                }
                await ws.send(json.dumps(subscribe_msg))
                print("Subscribed to Pump.fun via Helius")

                async for message in ws:
                    try:
                        data = json.loads(message)

                        if data.get("method") != "transactionNotification":
                            continue

                        result = data.get("params", {}).get("result", {})
                        transaction = result.get("transaction", {})
                        meta = transaction.get("meta", {})

                        found_mint = None

                        # Method 1: Check postTokenBalances
                        for balance in meta.get("postTokenBalances", []):
                            mint = balance.get("mint")
                            if mint and mint.endswith("pump"):
                                found_mint = mint
                                break

                        # Method 2: Check accountKeys for newly created pump addresses
                        if not found_mint:
                            account_keys = transaction.get("message", {}).get("accountKeys", [])
                            for key in account_keys:
                                if isinstance(key, str) and key.endswith("pump"):
                                    found_mint = key
                                    break

                        if found_mint:
                            enriched = enrich_coin_data({"mint": found_mint})
                            save_coin(enriched)
                            print(f"Saved: {enriched.get('name')} ({found_mint})")

                    except Exception as e:
                        print(f"Message error: {e}")

        except Exception as e:
            print(f"WebSocket error: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(indexer())
