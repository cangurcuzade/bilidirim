from flask import Flask, request, jsonify
import os, requests

app = Flask(__name__)

ONESIGNAL_APP_ID = os.environ.get("ONESIGNAL_APP_ID", "")
ONESIGNAL_API_KEY = os.environ.get("ONESIGNAL_API_KEY", "")

def send_push(title: str, body: str):
    url = "https://onesignal.com/api/v1/notifications"
    headers = {
        "Authorization": f"Basic {ONESIGNAL_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "app_id": ONESIGNAL_APP_ID,
        "headings": {"tr": title},
        "contents": {"tr": body},
        "included_segments": ["Subscribed Users"],
    }
    r = requests.post(url, json=payload, headers=headers, timeout=10)
    return r.status_code, r.text[:500]

@app.post("/ideasoft/webhook")
def ideasoft_webhook():
    data = request.get_json(silent=True) or {}
    oid = data.get("id") or data.get("Id")

    title = "Çamlıca Market"
    body = "Yeni sipariş geldi ✅" if not oid else f"Yeni sipariş geldi ✅ (ID: {oid})"

    if not ONESIGNAL_APP_ID or not ONESIGNAL_API_KEY:
        return jsonify({"received": True, "warn": "OneSignal env missing"}), 200

    status, text = send_push(title, body)
    return jsonify({"received": True, "push_status": status, "push_resp": text}), 200

@app.get("/")
def health():
    return "OK", 200
