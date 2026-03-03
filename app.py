import os
import time
import threading
import requests
from flask import Flask, jsonify

app = Flask(__name__)

# ===== ENV =====
IDEASOFT_BASE_URL = os.getenv("IDEASOFT_BASE_URL", "").rstrip("/")
IDEASOFT_CLIENT_ID = os.getenv("IDEASOFT_CLIENT_ID", "")
IDEASOFT_CLIENT_SECRET = os.getenv("IDEASOFT_CLIENT_SECRET", "")
IDEASOFT_REFRESH_TOKEN = os.getenv("IDEASOFT_REFRESH_TOKEN", "")

ONESIGNAL_APP_ID = os.getenv("ONESIGNAL_APP_ID", "")
ONESIGNAL_REST_API_KEY = os.getenv("ONESIGNAL_REST_API_KEY", "")

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))

# ===== TOKEN CACHE =====
access_token = None
token_expire_time = 0

# ===== LAST SEEN ORDER =====
LAST_SEEN_FILE = "last_seen.txt"


# ================= TOKEN =================

def refresh_access_token():
    global access_token, token_expire_time

    print("Access token yenileniyor...")

    url = f"{IDEASOFT_BASE_URL}/oauth/v2/token"

    data = {
        "grant_type": "refresh_token",
        "client_id": IDEASOFT_CLIENT_ID,
        "client_secret": IDEASOFT_CLIENT_SECRET,
        "refresh_token": IDEASOFT_REFRESH_TOKEN,
    }

    r = requests.post(url, data=data, timeout=20)
    r.raise_for_status()
    j = r.json()

    access_token = j["access_token"]
    expires_in = int(j.get("expires_in", 3600))

    token_expire_time = int(time.time()) + expires_in - 60

    print("Access token yenilendi.")


def get_token():
    global access_token, token_expire_time

    if not access_token or time.time() >= token_expire_time:
        refresh_access_token()

    return access_token


# ================= ORDER FETCH =================

def fetch_orders():
    url = f"{IDEASOFT_BASE_URL}/admin-api/orders"
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Accept": "application/json"
    }

    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()

    data = r.json()

    if isinstance(data, dict) and "data" in data:
        return data["data"]

    return data


# ================= PUSH =================

def send_push(order_id):
    url = "https://onesignal.com/api/v1/notifications"

    headers = {
        "Authorization": f"Basic {ONESIGNAL_REST_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "app_id": ONESIGNAL_APP_ID,
        "included_segments": ["Subscribed Users"],
        "headings": {"tr": "Pişt!"},
        "contents": {"tr": f"Yeni sipariş geldi! (#{order_id})"}
    }

    r = requests.post(url, headers=headers, json=payload, timeout=20)
    r.raise_for_status()

    print("Push gönderildi:", order_id)


# ================= LAST SEEN =================

def load_last():
    try:
        with open(LAST_SEEN_FILE, "r") as f:
            return int(f.read().strip())
    except:
        return None


def save_last(order_id):
    with open(LAST_SEEN_FILE, "w") as f:
        f.write(str(order_id))


# ================= POLLING =================

def poll_loop():
    print("Polling başladı...")

    last_seen = load_last()

    while True:
        try:
            orders = fetch_orders()

            if not orders:
                time.sleep(POLL_SECONDS)
                continue

            newest = int(orders[0]["id"])

            if last_seen is None:
                save_last(newest)
                last_seen = newest

            elif newest > last_seen:
                new_orders = [o for o in orders if int(o["id"]) > last_seen]
                new_orders.sort(key=lambda x: int(x["id"]))

                for order in new_orders:
                    oid = int(order["id"])
                    send_push(oid)
                    save_last(oid)
                    last_seen = oid

        except Exception as e:
            print("Polling hata:", e)

        time.sleep(POLL_SECONDS)


# ================= FLASK =================

@app.route("/")
def home():
    return jsonify({"status": "ok"})


def start_background():
    t = threading.Thread(target=poll_loop, daemon=True)
    t.start()


start_background()
