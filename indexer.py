import os
import time
import requests
import psycopg2

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

def get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Origin": "https://pump.fun",
        "Referer": "https://pump.fun/"
    }

def get_latest_coin():
    try:
        r = requests.get("https://frontend-api-v3.pump.fun/coins/latest", 
                         headers=get_headers(), timeout=10)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"Latest coin status: {r.status_code}")
    except Exception as e:
        print(f"Error fetching latest: {e}")
    return None

def get_coin_details(mint):
    try:
        r = requests.get(f"https://frontend-api-v3.pump.fun/coins/{mint}", 
                         headers=get_headers(), timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"Error fetching details: {e}")
    return None

def main():
    print("Indexer started...")
    create_table()

    seen = set()

    while True:
        try:
            latest = get_latest_coin()
            if latest:
                mint = latest.get("mint")
                if mint and mint not in seen:
                    seen.add(mint)
                    details = get_coin_details(mint) or latest
                    save_coin(details)
                    print(f"Saved: {details.get('name')} ({mint})")

            time.sleep(4)

        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
    main()
