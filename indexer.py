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

async def indexer():
    print("Starting WebSocket Indexer (DEBUG MODE)...")
    create_table()

    uri = "wss://pumpdev.io/ws"

    while True:
        try:
            async with websockets.connect(uri) as ws:
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                print("Connected to pumpdev.io WebSocket")

                async for message in ws:
                    print("RAW MESSAGE:", message)   # ← Debug line

                    try:
                        data = json.loads(message)

                        # Only process newToken events
                        if data.get("method") == "newToken":
                            mint = data.get("mint")
                            if mint:
                                # Try to enrich with more data
                                try:
                                    details = requests.get(f"https://frontend-api-v3.pump.fun/coins/{mint}", timeout=6).json()
                                except:
                                    details = data

                                save_coin(details)
                                print(f"Saved: {details.get('name')} ({mint})")
                        else:
                            print("Other message received:", data.get("method"))

                    except Exception as e:
                        print(f"Message processing error: {e}")

        except Exception as e:
            print(f"WebSocket error: {e}. Reconnecting...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(indexer())
    main()
