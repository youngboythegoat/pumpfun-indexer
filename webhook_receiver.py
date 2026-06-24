from fastapi import FastAPI, Request
import uvicorn
import json

app = FastAPI(title="Helius Webhook Receiver")

@app.post("/webhook")
async def helius_webhook(request: Request):
    try:
        payload = await request.json()
        print("=== Helius Webhook Received ===")
        print(json.dumps(payload, indent=2))
        print("===============================")
        
        # Later we will add logic here to extract the mint and save to DB
        return {"status": "received"}
    except Exception as e:
        print(f"Error processing webhook: {e}")
        return {"status": "error"}

@app.get("/")
async def health_check():
    return {"status": "Helius Webhook Receiver is running"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
