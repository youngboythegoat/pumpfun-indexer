from fastapi import FastAPI, Request
import uvicorn
import psycopg2
import requests
import os

app = FastAPI(title="Helius Webhook Receiver for Pump.fun")

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def save_coin(coin_data):
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
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Origin": "https://pump.fun",
        "Referer": "https://pump.fun/"
    }

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

def enrich_coin_data(mint):
    details = get_coin_details(mint) or {}
    return {
        "mint": mint,
        "name": details.get("name"),
        "symbol": details.get("symbol"),
        "twitter": details.get("twitter"),
        "description": details.get("description")
    }

@app.post("/webhook")
async def helius_webhook(request: Request):
    try:
        payload = await request.json()

        if isinstance(payload, list):
            for tx in payload:
                for account in tx.get("accountData", []):
                    for change in account.get("tokenBalanceChanges", []):
                        mint = change.get("mint")
                        if mint and mint.endswith("pump"):
                            enriched = enrich_coin_data(mint)
                            was_saved = save_coin(enriched)
                            if was_saved:
                                name = enriched.get("name") or "Unknown"
                                print(f"Saved new coin: {name} ({mint})")
        return {"status": "processed"}

    except Exception as e:
        print(f"Error processing webhook: {e}")
        return {"status": "error"}

@app.get("/")
async def health_check():
    return {"status": "Helius Webhook Receiver is running"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False, log_level="warning")
