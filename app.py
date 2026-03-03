import os
import time
import threading
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify

app = Flask(__name__)

# ---- ENV ----
IDEASOFT_BASE_URL = (os.getenv("IDEASOFT_BASE_URL") or "").rstrip("/")  # https://camlicasupermarket.myideasoft.com
IDEASOFT_CLIENT_ID = os.getenv("IDEASOFT_CLIENT_ID") or ""
IDEASOFT_CLIENT_SECRET = os.getenv("IDEASOFT_CLIENT_SECRET") or ""
IDEASOFT_REFRESH_TOKEN = os.getenv("IDEASOFT_REFRESH_TOKEN") or ""

# İlk access token env’de var ama yoksa refresh ile zaten alınır
IDEASOFT_ACCESS_TOKEN = os.getenv("IDEASOFT_ACCESS_TOKEN") or ""

ONESIGNAL_APP_ID = os.getenv("ONESIGNAL_APP_ID") or ""
ONESIGNAL_API_KEY = os.getenv("ONESIGNAL_API_KEY") or ""

# ---- GLOBAL STATE (RAM) ----
state = {
    "access_token": IDEASOFT_ACCESS_TOKEN,
    "last_order_id": None,
    "last_poll_at": None,
    "last_error": None,
}

session = requests.Session()
session.headers.update({"User-Agent": "camlica-polling/1.0"})


def onesignal_push(title: str, message: str):
    """Send push to all subscribed users."""
    if not (ONESIGNAL_APP_ID and ONESIGNAL_API_KEY):
        app.logger.warning("OneSignal env eksik: bildirim atlanıyor.")
        return

    url = "https://onesignal.com/api/v1/notifications"
    headers = {
        "Authorization": f"Basic {ONESIGNAL_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "app_id": ONESIGNAL_APP_ID,
        "included_segments": ["Subscribed Users"],
        "headings": {"en": title, "tr": title},
        "contents": {"en": message, "tr": message},
    }

    r = session.post(url, json=payload, headers=headers, timeout=20)
    if r.status_code >= 300:
        raise RuntimeError(f"OneSignal hata {r.status_code}: {r.text[:300]}")


def refresh_access_token():
    """Refresh access token using refresh_token. Sets state['access_token']."""
    if not (IDEASOFT_BASE_URL and IDEASOFT_CLIENT_ID and IDEASOFT_CLIENT_SECRET and IDEASOFT_REFRESH_TOKEN):
        raise RuntimeError("Ideasoft refresh için env eksik (BASE_URL/CLIENT_ID/CLIENT_SECRET/REFRESH_TOKEN).")

    token_url = f"{IDEASOFT_BASE_URL}/oauth/v2/token"

    data = {
        "grant_type": "refresh_token",
        "client_id": IDEASOFT_CLIENT_ID,
        "client_secret": IDEASOFT_CLIENT_SECRET,
        "refresh_token": IDEASOFT_REFRESH_TOKEN,
    }

    r = session.post(token_url, data=data, timeout=25)
    r.raise_for_status()
    js = r.json()

    access = js.get("access_token")
    if not access:
        raise RuntimeError(f"Refresh cevap access_token yok: {js}")

    state["access_token"] = access
    return access


def ideasoft_get(path: str, params=None):
    """Authorized GET to IdeaSoft admin-api"""
    if not state["access_token"]:
        refresh_access_token()

    url = f"{IDEASOFT_BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {state['access_token']}"}

    r = session.get(url, headers=headers, params=params, timeout=25)

    # Token expired vs → 401/403 olursa bir kere refresh dene
    if r.status_code in (401, 403):
        refresh_access_token()
        headers = {"Authorization": f"Bearer {state['access_token']}"}
        r = session.get(url, headers=headers, params=params, timeout=25)

    r.raise_for_status()
    return r.json()


def fetch_latest_order():
    """
    En yeni siparişi çek.
    IdeaSoft Admin API sipariş listesi çoğu kurulumda /admin-api/orders.
    """
    # sadece 1 kayıt alalım
    data = ideasoft_get("/admin-api/orders", params={"page": 1, "per_page": 1})

    # DÖNÜŞ ŞEKLİ ideashop’a göre değişebiliyor:
    # bazen {"data":[...]} bazen direkt [...]
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
        arr = data["data"]
    elif isinstance(data, list):
        arr = data
    else:
        arr = []

    if not arr:
        return None

    return arr[0]


def polling_loop():
    """
    Her 20 sn yeni sipariş var mı kontrol et.
    Yeni sipariş görünce push at.
    """
    app.logger.info("Polling başladı...")

    # İlk çalıştırmada bildirim spam olmasın diye mevcut en yeniyi last_order_id yapıyoruz
    try:
        latest = fetch_latest_order()
        if latest:
            state["last_order_id"] = latest.get("id") or latest.get("orderId")
            app.logger.info(f"Başlangıç last_order_id set: {state['last_order_id']}")
    except Exception as e:
        state["last_error"] = str(e)
        app.logger.exception("Başlangıç sipariş çekme hatası")

    while True:
        try:
            state["last_poll_at"] = datetime.now(timezone.utc).isoformat()

            latest = fetch_latest_order()
            if latest:
                oid = latest.get("id") or latest.get("orderId")
                if oid and state["last_order_id"] and str(oid) != str(state["last_order_id"]):
                    # Yeni sipariş var
                    state["last_order_id"] = oid

                    customer = (latest.get("customer", {}) or {})
                    cname = customer.get("fullName") or customer.get("name") or "Yeni müşteri"
                    msg = f"İnternet sitesinden yeni sipariş geldi: {cname}"

                    app.logger.info(f"Yeni sipariş yakalandı: {oid} -> push atılıyor")
                    onesignal_push("Pişt!", msg)

            state["last_error"] = None

        except Exception as e:
            state["last_error"] = str(e)
            app.logger.exception("Polling hata")

        time.sleep(20)


# ---- Start background thread once ----
_started = False
_lock = threading.Lock()

@app.before_request
def _start_once():
    global _started
    with _lock:
        if _started:
            return
        _started = True
        t = threading.Thread(target=polling_loop, daemon=True)
        t.start()


# ---- Health endpoints ----
@app.get("/")
def home():
    return "OK"

@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "base_url": IDEASOFT_BASE_URL,
        "last_order_id": state["last_order_id"],
        "last_poll_at": state["last_poll_at"],
        "last_error": state["last_error"],
    })
