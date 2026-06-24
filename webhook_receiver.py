from fastapi import FastAPI, Request
import uvicorn
import psycopg2
import requests
import os
import time

app = FastAPI(title="Helius Webhook Receiver for Pump.fun")

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def save_coin(coin_data):
    if not coin_data.get("name"):
        return False

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO pumpfun_coins (mint, name, symbol, twitter, description)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (mint) DO NOTHING
            RETURNING mint;
        """, (
            coin_data.get("mint"),
            coin_data.get("name"),
            coin_data.get("symbol"),
            coin_data.get("twitter"),
            coin_data.get("description")
        ))
        inserted = cur.fetchone()
        conn.commit()
        return inserted is not None
    except Exception as e:
        print(f"DB Error: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Origin": "https://pump.fun",
        "Referer": "https://pump.fun/"
    }

def get_coin_details(mint, retries=2):
    for attempt in range(retries):
        try:
            r = requests.get(
                f"https://frontend-api-v3.pump.fun/coins/{mint}",
                headers=get_headers(),
                timeout=8
            )
            if r.status_code == 200:
                return r.json()
            time.sleep(0.5)
        except:
            time.sleep(0.5)
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

def enrich_coin_data(mint):
    details = get_coin_details(mint)
    if not details:
        return {"mint": mint}  # Return minimal data so we don't lose the mint

    twitter = details.get("twitter")
    description = details.get("description")

    if not twitter and details.get("uri"):
        ipfs_data = get_ipfs_metadata(details["uri"])
        if ipfs_data:
            twitter = ipfs_data.get("twitter")
            description = ipfs_data.get("description")

    return {
        "mint": mint,
        "name": details.get("name"),
        "symbol": details.get("symbol"),
        "twitter": twitter,
        "description": description
    }

@app.post("/webhook")
async def helius_webhook(request: Request):
    try:
        payload = await request.json()

        if isinstance(payload, list):
            for tx in payload:
                account_data = tx.get("accountData", [])
                for account in account_data:
                    for change in account.get("tokenBalanceChanges", []):
                        mint = change.get("mint")
                        if mint and mint.endswith("pump"):
                            enriched = enrich_coin_data(mint)
                            was_saved = save_coin(enriched)
                            if was_saved:
                                print(f"Saved new coin: {enriched.get('name')} ({mint})")
                            else:
                                # Only log detection if we couldn't save it
                                if enriched.get("name"):
                                    print(f"Already exists or failed to save: {mint}")
        return {"status": "processed"}

    except Exception as e:
        print(f"Error processing webhook: {e}")
        return {"status": "error"}

@app.get("/")
async def health_check():
    return {"status": "Helius Webhook Receiver is running"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)
