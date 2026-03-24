import asyncio
import requests
import json
import os
from telegram import Bot
from datetime import datetime, timedelta
from dotenv import load_dotenv
import time

# -------------------- Ayarlar --------------------
load_dotenv()

BOT_TOKEN = "8692693177:AAFcn02RjYA1nKZLHYjsgh58-05vrd0-54k"
CHAT_ID = "87850554139"
API_URL = "https://camlicasupermarket.myideasoft.com/admin-api/orders"

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
TOKEN_URL = "https://www.camlicasupermarket.com/oauth/v2/token"

SEEN_ORDERS_FILE = "seen_orders.json"

bot = Bot(token=BOT_TOKEN)
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")

# -------------------- Daha önce görülen siparişleri yükle --------------------
def load_seen_orders():
    if os.path.exists(SEEN_ORDERS_FILE):
        with open(SEEN_ORDERS_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen_orders(seen_orders):
    with open(SEEN_ORDERS_FILE, "w") as f:
        json.dump(list(seen_orders), f)

# -------------------- Token yenileme --------------------
def refresh_token():
    global ACCESS_TOKEN, REFRESH_TOKEN
    try:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": REFRESH_TOKEN,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        response = requests.post(TOKEN_URL, data=data, headers=headers)
        response.raise_for_status()
        token_data = response.json()
        ACCESS_TOKEN = token_data["access_token"]
        REFRESH_TOKEN = token_data["refresh_token"]
        print("Token yenilendi!")
        # .env güncelle
        with open(".env", "w") as f:
            f.write(f"ACCESS_TOKEN={ACCESS_TOKEN}\n")
            f.write(f"REFRESH_TOKEN={REFRESH_TOKEN}\n")
            f.write(f"CLIENT_ID={CLIENT_ID}\n")
            f.write(f"CLIENT_SECRET={CLIENT_SECRET}\n")
    except Exception as e:
        print("Token yenileme hatası:", e)

# -------------------- Siparişleri Çek --------------------
def get_orders():
    global ACCESS_TOKEN
    yesterday = datetime.now() - timedelta(days=1)
    start_date = yesterday.strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    params = {
        "startCreatedAt": start_date,
        "endCreatedAt": end_date,
        "limit": 100,
        "page": 1
    }

    try:
        response = requests.get(API_URL, headers=headers, params=params)
        if response.status_code == 401:
            print("Access token süresi dolmuş, yenileniyor...")
            refresh_token()
            headers["Authorization"] = f"Bearer {ACCESS_TOKEN}"
            response = requests.get(API_URL, headers=headers, params=params)
        response.raise_for_status()
        orders = response.json()
        if isinstance(orders, dict) and "orders" in orders:
            return orders["orders"]
        elif isinstance(orders, list):
            return orders
        else:
            print("Beklenmeyen JSON formatı:", orders)
            return []
    except requests.exceptions.RequestException as e:
        print("Sipariş çekme hatası:", e)
        return []

# -------------------- Telegram mesajı gönder --------------------
async def send_telegram_message(order):
    total = order.get("finalAmount") or order.get("totals", {}).get("total_price", "Bilinmiyor")
    customer_name = order.get("customerFirstname") or order.get("billingFullname") or "Bilinmiyor"
    created_at = order.get("createdAt", "Bilinmiyor")
    order_id = order.get("id", "Bilinmiyor")

    message = (
        f"🛒 Yeni Sipariş!\n"
        f"ID: {order_id}\n"
        f"Müşteri: {customer_name}\n"
        f"Toplam: {total} TL\n"
        f"Tarih: {created_at}"
    )
    try:
        await bot.send_message(chat_id=CHAT_ID, text=message)
    except Exception as e:
        print("Telegram gönderme hatası:", e)

# -------------------- Ana Döngü --------------------
async def main_loop():
    seen_orders = load_seen_orders()
    refresh_token()  # Başlangıçta token al

    token_refresh_time = time.time()
    while True:
        # Token 50 dakikada bir yenilenir
        if time.time() - token_refresh_time > 3000:
            refresh_token()
            token_refresh_time = time.time()

        orders = get_orders()
        new_orders = [o for o in orders if o.get("id") not in seen_orders]
        if new_orders:
            print(f"{len(new_orders)} yeni sipariş bulundu.")
            for order in new_orders:
                await send_telegram_message(order)
                seen_orders.add(order.get("id"))
            save_seen_orders(seen_orders)
        else:
            print("Yeni sipariş yok.")

        await asyncio.sleep(60)  # 60 saniyede bir kontrol

if __name__ == "__main__":
    asyncio.run(main_loop())

