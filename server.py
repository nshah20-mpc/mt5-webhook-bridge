# ==============================================================================
# TradingView to MT5 Webhook Bridge Server (Flask Version)
# Receives TradingView webhook JSON alerts & serves MT5 EA poll requests
# ==============================================================================
# Setup Instructions:
# 1. Install dependencies:
#    pip install flask requests
# 2. Run server:
#    python server.py
# 3. Expose to internet for TradingView (e.g. using Ngrok, Cloudflare Tunnel, or VPS):
#    ngrok http 5000
# ==============================================================================

import json
import os
import time
from flask import Flask, request, jsonify

app = Flask(__name__)

# Server Configuration
PORT = 5000
PASSPHRASE = "MY_SECRET_KEY"
DEFAULT_MAGIC = 123456
MAX_SIGNAL_AGE_SECONDS = 300
SYMBOL_MAPPING = {
    "EURUSD": "EURUSD.a",
    "XAUUSD": "GOLD.m",
    "BTCUSD": "BTCUSD"
}

TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""

SIGNAL_FILE = "pending_signals.json"
HISTORY_FILE = "signal_history.json"

pending_signals = []
signal_history = []

def load_storage():
    global pending_signals, signal_history
    if os.path.exists(SIGNAL_FILE):
        try:
            with open(SIGNAL_FILE, "r") as f:
                pending_signals = json.load(f)
        except Exception as e:
            print(f"[WARN] Error loading signals: {e}")
            pending_signals = []
            
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                signal_history = json.load(f)
        except Exception as e:
            signal_history = []

def save_storage():
    try:
        with open(SIGNAL_FILE, "w") as f:
            json.dump(pending_signals, f, indent=2)
        with open(HISTORY_FILE, "w") as f:
            json.dump(signal_history[-200:], f, indent=2)
    except Exception as e:
        print(f"[ERROR] Failed to save storage: {e}")

load_storage()

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=3)
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")

def map_symbol(tv_symbol):
    cleaned = str(tv_symbol).upper().replace("FX:", "").replace("OANDA:", "").replace("BINANCE:", "")
    return SYMBOL_MAPPING.get(cleaned, cleaned)

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "online",
        "service": "TradingView-to-MT5 Bridge Server",
        "pending_signals_count": len(pending_signals),
        "history_count": len(signal_history)
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"status": "error", "message": "Invalid JSON format"}), 400

    # Passphrase check
    provided_key = data.get("passphrase") or data.get("secret") or data.get("key")
    if PASSPHRASE and provided_key != PASSPHRASE:
        print(f"[UNAUTHORIZED] Invalid secret attempt: {provided_key}")
        return jsonify({"status": "error", "message": "Unauthorized passphrase"}), 401

    action = str(data.get("action", "")).upper()
    if action not in ["BUY", "SELL", "CLOSE", "CLOSE_BUY", "CLOSE_SELL", "MODIFY"]:
        return jsonify({"status": "error", "message": "Invalid action. Allowed: BUY, SELL, CLOSE, CLOSE_BUY, CLOSE_SELL, MODIFY"}), 400

    raw_symbol = str(data.get("symbol", "EURUSD"))
    mt5_symbol = map_symbol(raw_symbol)

    signal_id = f"SIG_{int(time.time() * 1000)}"
    signal = {
        "id": signal_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "time_unix": int(time.time()),
        "action": action,
        "symbol": mt5_symbol,
        "original_symbol": raw_symbol,
        "lots": data.get("lots") or data.get("volume"),
        "risk_percent": data.get("risk_percent"),
        "sl": data.get("sl"),
        "tp": data.get("tp"),
        "sl_pips": data.get("sl_pips"),
        "tp_pips": data.get("tp_pips"),
        "magic": data.get("magic", DEFAULT_MAGIC),
        "comment": data.get("comment", "TV_Alert"),
        "status": "PENDING"
    }

    pending_signals.append(signal)
    signal_history.append(signal)
    save_storage()

    msg = f"🚀 [SIGNAL RECEIVED] {action} {mt5_symbol} | Lots: {signal.get('lots')} | Magic: {signal.get('magic')}"
    print(msg)
    send_telegram_alert(msg)

    return jsonify({"status": "success", "message": "Signal queued for MT5 EA", "signal_id": signal_id, "data": signal})

@app.route("/api/pending-orders", methods=["GET"])
def pending_orders():
    secret = request.args.get("secret")
    if PASSPHRASE and secret != PASSPHRASE:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    magic_filter = request.args.get("magic", type=int)
    current_time = int(time.time())

    valid_orders = []
    expired_indices = []

    for i, sig in enumerate(pending_signals):
        if sig["status"] == "PENDING":
            age = current_time - sig.get("time_unix", current_time)
            if age > MAX_SIGNAL_AGE_SECONDS:
                sig["status"] = "EXPIRED"
                expired_indices.append(i)
                continue
            
            if magic_filter is None or sig.get("magic") == magic_filter:
                valid_orders.append(sig)

    for idx in reversed(expired_indices):
        pending_signals.pop(idx)
    if expired_indices:
        save_storage()

    return jsonify({"status": "ok", "count": len(valid_orders), "orders": valid_orders})

@app.route("/api/order-result", methods=["POST"])
def order_result():
    data = request.get_json(force=True)
    signal_id = data.get("signal_id")
    ticket = data.get("ticket")
    status = data.get("status", "EXECUTED")
    error_msg = data.get("error")

    global pending_signals
    pending_signals = [s for s in pending_signals if s["id"] != signal_id]

    for s in signal_history:
        if s["id"] == signal_id:
            s["status"] = status
            s["execution_result"] = {
                "ticket": ticket,
                "executed_price": data.get("executed_price"),
                "error": error_msg,
                "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            break

    save_storage()
    print(f"✅ [MT5 EXECUTED] Signal {signal_id} -> {status} (Ticket #{ticket})")
    send_telegram_alert(f"✅ MT5 Order #{ticket} Executed at {data.get('executed_price')}")

    return jsonify({"status": "ok", "message": "Result stored"})

if __name__ == "__main__":
    print(f"Starting Python Flask Bridge Server on port {PORT}...")
    app.run(host="0.0.0.0", port=PORT, debug=False)
