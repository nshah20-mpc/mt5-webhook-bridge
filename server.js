const express = require('express');
const app = express();

app.use(express.json());

// In-Memory Storage for Pending Signals
let pendingSignals = [];
let signalHistory = [];

const PASSPHRASE = process.env.PASSPHRASE || "MY_SECRET_KEY";
const MAX_SIGNAL_AGE_SECONDS = 300;

// Health Check
app.get('/api/health', (req, res) => {
    res.json({ status: "ok", pending_count: pendingSignals.length, timestamp: new Date().toISOString() });
});

// 1. TradingView Webhook Endpoint
app.post('/webhook', (req, res) => {
    try {
        const payload = req.body;
        console.log("📥 Received Webhook:", payload);

        if (!payload || payload.passphrase !== PASSPHRASE) {
            return res.status(401).json({ status: "error", message: "Unauthorized passphrase mismatch" });
        }

        const signal = {
            id: `sig_${Date.now()}_${Math.floor(Math.random() * 1000)}`,
            received_at: Math.floor(Date.now() / 1000),
            action: (payload.action || "BUY").toUpperCase(),
            symbol: (payload.symbol || "EURUSD").toUpperCase(),
            lot_mode: payload.lot_mode || "fixed",
            lots: parseFloat(payload.lots) || 0.01,
            risk_percent: parseFloat(payload.risk_percent) || 0,
            risk_cash: parseFloat(payload.risk_cash) || 0,
            sl: parseFloat(payload.sl) || 0,
            tp: parseFloat(payload.tp) || 0,
            sl_pips: parseFloat(payload.sl_pips) || 0,
            tp_pips: parseFloat(payload.tp_pips) || 0,
            magic: parseInt(payload.magic) || 123456,
            comment: payload.comment || "TV_Signal",
            status: "PENDING"
        };

        pendingSignals.push(signal);
        signalHistory.unshift(signal);
        if (signalHistory.length > 100) signalHistory.pop();

        res.json({ status: "success", signal_id: signal.id, message: "Signal queued for MT5" });
    } catch (err) {
        res.status(500).json({ status: "error", message: err.message });
    }
});

// 2. MT5 Poll Endpoint (Get Pending Orders)
app.get('/api/pending-orders', (req, res) => {
    const secret = req.query.secret;
    if (secret !== PASSPHRASE) {
        return res.status(401).json({ status: "error", message: "Unauthorized" });
    }

    const now = Math.floor(Date.now() / 1000);
    const validSignals = [];
    const remainingSignals = [];

    for (const sig of pendingSignals) {
        if ((now - sig.received_at) <= MAX_SIGNAL_AGE_SECONDS) {
            validSignals.push(sig);
        } else {
            sig.status = "EXPIRED";
        }
    }

    // Clear polled signals from queue
    pendingSignals = [];

    res.json({ status: "ok", count: validSignals.length, orders: validSignals });
});

// 3. MT5 Execution Result Reporting
app.post('/api/order-result', (req, res) => {
    const { signal_id, ticket, status, error, executed_price } = req.body;
    const item = signalHistory.find(s => s.id === signal_id);
    if (item) {
        item.status = status;
        item.ticket = ticket;
        item.executed_price = executed_price;
        item.error = error;
    }
    res.json({ status: "acknowledged" });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, '0.0.0.0', () => {
    console.log(`🚀 Hostinger Webhook Bridge running on port ${PORT}`);
});