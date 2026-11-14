# ==============================================================================
# PRO QUANT HYBRID AI TRADING BOT 24/7 (100% NATIVE INDODAX V2 + GEMINI AI)
# ==============================================================================
# Fitur Unggulan Edisi Ultimate Pro Scalper (Poin 1, 3, & 5 Terintegrasi Penuh):
# 1. NATIVE INDODAX IDR CANDLESTICK API (tradingview/history_v2 tf=5 Menit)
# 2. EARLY PROFIT & SCRATCH EXIT (> +0.60% Harga Bid Langsung Konsultasi Gemini)
# 3. 100% DYNAMIC ENTRY TIAP 5 MENIT (Geser Harga Beli / Batal & Pindah Koin Instan)
# 4. PRO ASYMMETRIC RECOVERY & SL COOLDOWN 45 MENIT (Strategi Balik Modal Pro)
# 5. FILTER KOMPAS BITCOIN (BTCIDR), SPREAD ORDER BOOK, & CIRCUIT BREAKER HARIAN
# 6. LAPORAN GOOGLE SHEETS BERSIH (Hanya kirim saat terjadi transaksi nyata)
# ==============================================================================

import os
import time
import math
import hmac
import hashlib
import urllib.parse
import urllib.request
import json
from datetime import datetime, timedelta, timezone

# ==============================================================================
# BAGIAN 1: KONFIGURASI UTAMA, PARAMETER SCALPING 5M & PROTEKSI MODAL
# ==============================================================================
MAX_BOT_CAPITAL_IDR = float(os.getenv("MAX_BOT_CAPITAL_IDR", "100000"))
MIN_LIMIT_ORDER_INDODAX_IDR = 25000.0  # Syarat minimum nilai Limit Order Indodax
MIN_SAFE_SL_BUFFER_IDR = 28500.0       # Nilai bersih koin wajib >= Rp28.500 agar saat SL tetap > Rp25.000
MIN_NEW_BUY_ALLOCATION_IDR = 32000.0   # Minimal alokasi beli baru per koin agar 100% aman saat eksekusi SL
MAX_SINGLE_COIN_CAP_PCT = 0.45         # Maksimal porsi modal pada 1 koin jika hanya ada 1 sinyal siap_entry
FEE_ROUNDTRIP_MAKER_PCT = 0.0055       # Estimasi total biaya beli+jual+PPN+CFX Indodax ~0.55%

MIN_CONVICTION_SCORE = 64.0            # Skor kelayakan minimal normal (0 - 100)
RECOVERY_SCORE_BOOST = 3.5             # Tambahan syarat skor minimal (+3.5) saat mode balik modal (Recovery) aktif
MAX_CONCURRENT_COINS = 3               # Maksimal 3 koin bersamaan (dengan modal Rp100rb -> ~Rp32rb-Rp35rb/koin)
MAX_SPREAD_INDODAX_PCT = 0.0035        # Maksimal toleransi Bid-Ask Spread Indodax (0.35%) untuk scalping
DAILY_LOSS_LIMIT_PCT = -0.025          # Batas rugi harian (-2.5% modal) untuk menyalakan Circuit Breaker
SL_COOLDOWN_MINUTES = 45               # Masa tenang 45 menit untuk koin yang baru terkena SL (Anti-Whipsaw)

# Parameter Target TP & SL Dinamis (Menyesuaikan Volatilitas ATR Rupiah Indodax)
TP_GRID_MIN_PCT = 0.0135               # +1.35% Target TP minimal mode Grid saat pasar sepi
TP_GRID_MAX_PCT = 0.0220               # +2.20% Target TP maksimal mode Grid saat volatilitas tinggi
SL_GRID_BASE_PCT = 0.0180              # -1.80% Batas Hard SL mode Grid

TP_SNIPER_MIN_PCT = 0.0180             # +1.80% Target TP minimal mode Sniper saat pasar moderat
TP_SNIPER_MAX_PCT = 0.0340             # +3.40% Target TP maksimal mode Sniper saat breakout kencang
SL_SNIPER_BASE_PCT = 0.0160            # -1.60% Batas Hard SL mode Sniper
EMERGENCY_SL_PCT = -0.0300             # -3.00% Batas Darurat Mutlak (Wajib Cut Loss tanpa bisa ditahan)

# Parameter Penyelamatan Profit Berlapis (Poin 1) & Entry Dinamis (Poin 3)
SCRATCH_PROFIT_BID_PCT = 0.0060        # > +0.60% pada harga Bid (sudah untung di atas fee 0.55%) saat tren patah
TP_RANGE_MIN_PROFIT_PCT = 0.0095       # >= +0.95% untuk pengamanan puncak terlewat (TP Range)
TIME_STOP_HOURS = 2.5                  # Jika posisi ditahan >= 2.5 jam & profit >= +1.00% melambat, cairkan profit
TIME_STOP_MIN_PROFIT_PCT = 0.0100      # Minimal profit +1.00% untuk Time-Based Exit
DYNAMIC_ENTRY_SHIFT_PCT = 0.0035       # Geser antrean Limit Buy jika harga entry ideal berubah >= 0.35%
REVIEW_ENTRY_HOURS = 1.5               # Batas maksimal antrean Limit Buy yang belum terjemput (1.5 jam)

ACTIVE_WATCH_MINUTES = int(os.getenv("ACTIVE_WATCH_MINUTES", "4"))
WATCH_INTERVAL_SECONDS = int(os.getenv("WATCH_INTERVAL_SECONDS", "60"))
FORCE_CONTINUOUS_WATCH = os.getenv("FORCE_CONTINUOUS_WATCH", "false").lower() == "true"

WATCHLIST_COINS = {
    "BTC":  {"v2_symbol": "BTCIDR",  "indodax_key": "btc_idr",  "kraken_pair": "XXBTZUSD", "step_decimals": 6, "price_step": 1000},
    "SOL":  {"v2_symbol": "SOLIDR",  "indodax_key": "sol_idr",  "kraken_pair": "SOLUSD",   "step_decimals": 4, "price_step": 1},
    "ETH":  {"v2_symbol": "ETHIDR",  "indodax_key": "eth_idr",  "kraken_pair": "XETHZUSD", "step_decimals": 5, "price_step": 1000},
    "XRP":  {"v2_symbol": "XRPIDR",  "indodax_key": "xrp_idr",  "kraken_pair": "XXRPZUSD", "step_decimals": 2, "price_step": 1},
    "ADA":  {"v2_symbol": "ADAIDR",  "indodax_key": "ada_idr",  "kraken_pair": "ADAUSD",   "step_decimals": 2, "price_step": 1},
    "SUI":  {"v2_symbol": "SUIIDR",  "indodax_key": "sui_idr",  "kraken_pair": "SUIUSD",   "step_decimals": 2, "price_step": 1},
    "DOGE": {"v2_symbol": "DOGEIDR", "indodax_key": "doge_idr", "kraken_pair": "XDGUSD",   "step_decimals": 0, "price_step": 1}
}

KNOWN_ENTRY_REFERENCE = {}
STATE_FILE = "bot_state_tokocrypto.json"

INDODAX_API_KEY = os.getenv("INDODAX_API_KEY", os.getenv("TOKOCRYPTO_API_KEY", "")).strip()
INDODAX_SECRET_KEY = os.getenv("INDODAX_SECRET_KEY", os.getenv("TOKOCRYPTO_SECRET_KEY", "")).strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GOOGLE_SHEETS_WEBHOOK_URL = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"

# ==============================================================================
# BAGIAN 2: MANAJEMEN MEMORI POSISI, TRACKER RECOVERY & COOLDOWN SL
# ==============================================================================
def tanggal_wib_hari_ini():
    tz_wib = timezone(timedelta(hours=7))
    return datetime.now(tz_wib).strftime("%Y-%m-%d")

def muat_state_bot():
    tgl_skrg = tanggal_wib_hari_ini()
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
            if state.get("last_reset_date") != tgl_skrg:
                state["realized_profit_today_idr"] = 0.0
                state["completed_trades_today"] = 0
                state["last_reset_date"] = tgl_skrg
            state.setdefault("loss_to_recover_idr", 0.0)
            state.setdefault("sl_cooldown_until", {})
            return state
        except Exception:
            pass
    return {
        "active_slots": [],
        "realized_profit_today_idr": 0.0,
        "completed_trades_today": 0,
        "loss_to_recover_idr": 0.0,
        "sl_cooldown_until": {},
        "last_reset_date": tgl_skrg
    }

def simpan_state_bot(state):
    state["last_reset_date"] = tanggal_wib_hari_ini()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def catat_hasil_transaksi_ke_recovery(state, pnl_bersih_idr, coin=None):
    state["realized_profit_today_idr"] = round(float(state.get("realized_profit_today_idr", 0.0)) + pnl_bersih_idr, 0)
    state["completed_trades_today"] = int(state.get("completed_trades_today", 0)) + 1

    defisit_lama = float(state.get("loss_to_recover_idr", 0.0))
    if pnl_bersih_idr < 0:
        state["loss_to_recover_idr"] = round(defisit_lama + abs(pnl_bersih_idr), 0)
        if coin:
            state.setdefault("sl_cooldown_until", {})[coin] = time.time() + (SL_COOLDOWN_MINUTES * 60)
    else:
        state["loss_to_recover_idr"] = round(max(0.0, defisit_lama - pnl_bersih_idr), 0)

# ==============================================================================
# BAGIAN 3: KONEKSI RESMI INDODAX TRADE API V2 & CEK SPREAD ORDER BOOK
# ==============================================================================
def panggil_indodax_v2(endpoint, method="GET", params=None):
    if params is None:
        params = {}
    if not INDODAX_API_KEY or not INDODAX_SECRET_KEY:
        return {"code": -1, "msg": "API Key / Secret Indodax belum diisi"}

    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 15000
    query_str = urllib.parse.urlencode(params)
    sign = hmac.new(
        INDODAX_SECRET_KEY.encode("utf-8"),
        query_str.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    base_url = "https://api.indodax.com"
    url = f"{base_url}{endpoint}?{query_str}" if method in ["GET", "DELETE"] else f"{base_url}{endpoint}"
    headers = {
        "X-APIKEY": INDODAX_API_KEY,
        "Sign": sign,
        "User-Agent": "Mozilla/5.0"
    }
    body = None
    if method == "POST":
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = query_str.encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"code": e.code, "msg": str(e)}
    except Exception as e:
        return {"code": -1, "msg": str(e)}

def ambil_saldo_lengkap_indodax():
    dompet = {"idr_free": 0.0, "idr_locked": 0.0, "coins_free": {}, "coins_locked": {}, "terhubung": False}
    if not LIVE_TRADING_ENABLED or not INDODAX_API_KEY:
        dompet["idr_free"] = MAX_BOT_CAPITAL_IDR
        return dompet

    res = panggil_indodax_v2("/api/v2/account", method="GET")
    if isinstance(res, dict) and "balances" in res:
        dompet["terhubung"] = True
        for b in res.get("balances", []):
            asset = str(b.get("asset", "")).upper()
            free_val = float(b.get("free", 0) or 0)
            locked_val = float(b.get("locked", 0) or 0)
            if asset == "IDR":
                dompet["idr_free"] = free_val
                dompet["idr_locked"] = locked_val
            else:
                dompet["coins_free"][asset] = free_val
                dompet["coins_locked"][asset] = locked_val
        print(f"✅ [AKUN INDODAX UID:{res.get('uid')} TERHUBUNG] Saldo IDR Bebas: Rp{dompet['idr_free']:,.0f} | IDR Antre Order: Rp{dompet['idr_locked']:,.0f}")
    else:
        print(f"⚠️ [PERINGATAN CEK SALDO V2]: {res}")
    return dompet

def bulatkan_harga_indodax(coin, harga_idr):
    step = WATCHLIST_COINS[coin].get("price_step", 1)
    return int(round(harga_idr / step) * step)

def format_qty_koin(coin, raw_qty):
    decimals = WATCHLIST_COINS[coin]["step_decimals"]
    factor = 10 ** decimals
    qty = math.floor((float(raw_qty) + 1e-9) * factor) / factor
    return int(qty) if decimals == 0 else round(qty, decimals)

def hitung_kuantitas_koin(coin, nominal_idr, harga_idr):
    if harga_idr <= 0:
        return 0
    return format_qty_koin(coin, nominal_idr / harga_idr)

def eksekusi_order_indodax(coin, side_str, harga_idr, nominal_idr=0.0, qty_koin=0.0, order_type="LIMIT"):
    harga_bulat = bulatkan_harga_indodax(coin, harga_idr)
    qty = format_qty_koin(coin, qty_koin) if qty_koin > 0 else hitung_kuantitas_koin(coin, nominal_idr, harga_bulat)
    if not LIVE_TRADING_ENABLED:
        return {"simulasi": True, "orderId": f"SIM-{int(time.time())}", "qty": qty}

    symbol = WATCHLIST_COINS[coin]["v2_symbol"]
    params = {
        "symbol": symbol,
        "side": side_str.upper(),
        "type": order_type.upper(),
        "quantity": str(qty)
    }
    if order_type.upper() == "LIMIT":
        params["timeInForce"] = "GTC"
        params["price"] = str(harga_bulat)

    res = panggil_indodax_v2("/api/v2/order", method="POST", params=params)
    print(f"👉 [INDODAX V2 {side_str.upper()} {order_type.upper()}] {symbol} | Qty={qty} @ Rp{harga_bulat:,.0f} -> {res}")
    if isinstance(res, dict):
        res["qty"] = qty
    return res

def apakah_order_sukses(res):
    return isinstance(res, dict) and ("orderId" in res or res.get("simulasi") is True)

def batalkan_order_indodax(coin, order_id):
    if not LIVE_TRADING_ENABLED or not order_id or str(order_id).startswith(("SIM-", "ERR-", "HOLD-")):
        return
    symbol = WATCHLIST_COINS[coin]["v2_symbol"]
    params = {"symbol": symbol, "orderId": str(order_id)}
    res = panggil_indodax_v2("/api/v2/order", method="DELETE", params=params)
    print(f"🗑️ [INDODAX V2 CANCEL] {symbol} OrderID={order_id} -> {res}")

def pasang_antrean_tp_di_indodax(slot, koin_free):
    coin = slot["coin"]
    tp_idr = bulatkan_harga_indodax(coin, slot["tp_price_idr"])
    slot["tp_price_idr"] = tp_idr
    qty_target = slot.get("qty", 0.0)
    if koin_free > 0:
        qty_jual = format_qty_koin(coin, min(qty_target, koin_free) if qty_target > 0 else koin_free)
    else:
        qty_jual = format_qty_koin(coin, qty_target)

    if qty_jual <= 0:
        return None

    res_tp = eksekusi_order_indodax(coin, "SELL", tp_idr, qty_koin=qty_jual, order_type="LIMIT")
    if apakah_order_sukses(res_tp):
        tp_oid = str(res_tp.get("orderId"))
        slot["tp_order_id"] = tp_oid
        slot["qty"] = qty_jual
        print(f"📌 [ANTREAN TP INDODAX AKTIF] {coin} LIMIT SELL Qty={qty_jual} @ Rp{tp_idr:,.0f} (OrderID: #{tp_oid})")
        return tp_oid
    return None

def ambil_harga_idr_semua_koin():
    harga_map = {}
    try:
        url = "https://indodax.com/api/tickers"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            tickers = json.loads(resp.read().decode()).get("tickers", {})
        for coin, info in WATCHLIST_COINS.items():
            t = tickers.get(info["indodax_key"], {})
            if "last" in t:
                last_p = float(t["last"])
                buy_p = float(t.get("buy", last_p) or last_p)
                sell_p = float(t.get("sell", last_p) or last_p)
                spread_pct = ((sell_p - buy_p) / buy_p) if buy_p > 0 else 0.0
                harga_map[coin] = {
                    "last": last_p,
                    "buy": buy_p,
                    "sell": sell_p,
                    "spread_pct": round(max(0.0, spread_pct), 5),
                    "high_24h": float(t.get("high", last_p)),
                    "low_24h": float(t.get("low", last_p))
                }
    except Exception as e:
        print("Fallback harga IDR:", e)
    return harga_map

def hitung_tp_sl_dinamis_atr(coin, entry_idr, gaya, atr_5m_pct):
    target_ayunan_pasar = atr_5m_pct * 4.5
    if gaya == "SNIPER":
        tp_pct = min(TP_SNIPER_MAX_PCT, max(TP_SNIPER_MIN_PCT, target_ayunan_pasar))
        sl_pct = SL_SNIPER_BASE_PCT
    else:
        tp_pct = min(TP_GRID_MAX_PCT, max(TP_GRID_MIN_PCT, target_ayunan_pasar * 0.85))
        sl_pct = SL_GRID_BASE_PCT

    tp_idr = bulatkan_harga_indodax(coin, entry_idr * (1.0 + tp_pct))
    sl_idr = bulatkan_harga_indodax(coin, entry_idr * (1.0 - sl_pct))
    return tp_idr, sl_idr, round(tp_pct * 100, 2)

# ==============================================================================
# BAGIAN 4: AUTO-RECOVERY KOIN DOMPET INDODAX (PEMULIHAN POSISI YATIM)
# ==============================================================================
def sinkronkan_koin_dompet_indodax(state, dompet, harga_idr_map):
    log_recovery = []
    if not dompet.get("terhubung"):
        return state, log_recovery

    koin_di_state = {s["coin"] for s in state.get("active_slots", [])}
    for coin in WATCHLIST_COINS.keys():
        if coin in koin_di_state:
            continue
        k_free = dompet["coins_free"].get(coin, 0.0)
        k_locked = dompet["coins_locked"].get(coin, 0.0)
        total_qty = format_qty_koin(coin, k_free + k_locked)
        harga_skrg = harga_idr_map.get(coin, {}).get("last", 0.0)
        nilai_idr = total_qty * harga_skrg

        if nilai_idr >= 10000.0 and total_qty > 0:
            ref = KNOWN_ENTRY_REFERENCE.get(coin, {})
            entry_idr = ref.get("entry_price_idr", bulatkan_harga_indodax(coin, harga_skrg))
            style = ref.get("style", "GRID")
            tp_idr_default, sl_idr_default, _ = hitung_tp_sl_dinamis_atr(coin, entry_idr, style, 0.0035)
            tp_idr = ref.get("tp_price_idr", tp_idr_default)
            sl_idr = sl_idr_default
            modal_idr = ref.get("capital_idr", round(total_qty * entry_idr, 0))

            slot_pulih = {
                "coin": coin,
                "style": style,
                "status": "HOLDING_FOR_TP",
                "capital_idr": modal_idr,
                "qty": total_qty,
                "entry_price_idr": entry_idr,
                "tp_price_idr": tp_idr,
                "sl_price_idr": sl_idr,
                "highest_price_idr": max(entry_idr, harga_skrg),
                "filled_timestamp": time.time(),
                "timestamp": time.time()
            }
            if k_free > 0:
                pasang_antrean_tp_di_indodax(slot_pulih, k_free)

            state["active_slots"].append(slot_pulih)
            log_recovery.append(
                f"♻️ [AUTO-RECOVERY DOMPET] {coin} (Qty:{total_qty}) ditemukan di dompet Indodax! "
                f"Posisi dipulihkan (Acuan: Rp{entry_idr:,.0f} -> Antrean TP: Rp{tp_idr:,.0f})."
            )
    return state, log_recovery

# ==============================================================================
# BAGIAN 5: NATIVE INDODAX IDR CANDLESTICK API (5M+15M+1H) & KONSULTASI GEMINI
# ==============================================================================
def hitung_rsi(closes_list, periode=14):
    if len(closes_list) <= periode:
        return 50.0
    gains, losses = [], []
    for i in range(-periode, 0):
        diff = closes_list[i] - closes_list[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains) / float(periode)
    avg_loss = (sum(losses) / float(periode)) or 0.0001
    return 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))

def ambil_data_ohlc_5m_indodax(coin, info):
    now_ts = int(time.time())
    from_ts = now_ts - (400 * 5 * 60)
    symbol = info["v2_symbol"]
    url_indodax = f"https://indodax.com/tradingview/history_v2?symbol={symbol}&tf=5&from={from_ts}&to={now_ts}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json"
    }
    try:
        req = urllib.request.Request(url_indodax, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        if isinstance(data, list) and len(data) >= 30:
            raw = data[-360:]
            closes = [float(r.get("Close", r.get("close", 0))) for r in raw]
            highs = [float(r.get("High", r.get("high", 0))) for r in raw]
            lows = [float(r.get("Low", r.get("low", 0))) for r in raw]
            vols = [float(r.get("Volume", r.get("volume", 0)) or 0) for r in raw]
            if closes and closes[-1] > 0:
                return closes, highs, lows, vols, "INDODAX-IDR"

        if isinstance(data, dict) and "c" in data and len(data["c"]) >= 30:
            closes = [float(x) for x in data["c"][-360:]]
            highs = [float(x) for x in data["h"][-360:]]
            lows = [float(x) for x in data["l"][-360:]]
            vols = [float(x) for x in data.get("v", [1.0] * len(closes))[-360:]]
            if closes and closes[-1] > 0:
                return closes, highs, lows, vols, "INDODAX-IDR"
    except Exception:
        pass

    url_kraken = f"https://api.kraken.com/0/public/OHLC?pair={info['kraken_pair']}&interval=5"
    req_k = urllib.request.Request(url_kraken, headers=headers)
    with urllib.request.urlopen(req_k, timeout=10) as resp_k:
        res_k = json.loads(resp_k.read().decode())
    result_key = [k for k in res_k["result"].keys() if k != "last"][0]
    raw_k = res_k["result"][result_key][-360:]
    closes = [float(r[4]) for r in raw_k]
    highs = [float(r[2]) for r in raw_k]
    lows = [float(r[3]) for r in raw_k]
    vols = [float(r[6]) for r in raw_k]
    return closes, highs, lows, vols, "KRAKEN-FALLBACK"

def analisa_teknikal_lengkap_pasar(harga_idr_map):
    peta_analisa = {}
    for coin, info in WATCHLIST_COINS.items():
        data_ticker = harga_idr_map.get(coin)
        if not data_ticker or data_ticker["last"] <= 0:
            continue
        harga_idr = data_ticker["last"]
        harga_bid = data_ticker.get("buy", harga_idr)
        harga_ask = data_ticker.get("sell", harga_idr)
        spread_pct = data_ticker.get("spread_pct", 0.0)
        try:
            closes, highs, lows, vols, sumber_ohlc = ambil_data_ohlc_5m_indodax(coin, info)

            ema20_5m = sum(closes[-20:]) / len(closes[-20:])
            ema50_5m = sum(closes[-50:]) / len(closes[-50:])
            tren_5m_naik = ema20_5m > ema50_5m
            rsi_5m = hitung_rsi(closes, 14)

            closes_15m = closes[::3]
            ema20_15m = sum(closes_15m[-20:]) / len(closes_15m[-20:])
            ema50_15m = sum(closes_15m[-50:]) / len(closes_15m[-50:])
            tren_15m_naik = ema20_15m > ema50_15m
            rsi_15m = hitung_rsi(closes_15m, 14)

            ema_1h_cepat = sum(closes[-180:]) / len(closes[-180:])
            ema_1h_lambat = sum(closes[-360:]) / len(closes[-360:])
            tren_1h_naik = ema_1h_cepat > ema_1h_lambat

            periode_atr = min(14, len(closes) - 1)
            tr_list = [highs[i] - lows[i] for i in range(-periode_atr, 0)]
            atr_5m_pct = ((sum(tr_list) / float(periode_atr)) / closes[-1]) if closes[-1] > 0 else 0.003

            if sumber_ohlc == "INDODAX-IDR":
                high_2jam_idr = round(max(harga_idr, max(highs[-24:])), 0)
            else:
                rasio_high_2jam = max(highs[-24:]) / closes[-1] if closes[-1] > 0 else 1.0
                high_2jam_idr = round(harga_idr * max(1.0, rasio_high_2jam), 0)

            vol_rata = sum(vols[-20:-1]) / 19.0 if len(vols) >= 20 else (vols[-1] or 1.0)
            rasio_vol = vols[-1] / (vol_rata or 1.0)

                        # Wajib ada kenaikan harga nyata & minimal volume aktif (bukan candle datar volume 0.0x)
            vol_aktif = rasio_vol >= 0.15
            candle_5m_hijau = (closes[-1] > closes[-2]) or (closes[-1] == closes[-2] and closes[-2] > closes[-3] and vol_aktif)
            dua_candle_5m_naik = (closes[-1] > closes[-3]) and (closes[-1] >= closes[-2] >= closes[-3]) and vol_aktif
            candle_jatuh_beruntun = (closes[-1] < closes[-2] < closes[-3])
            spread_aman = spread_pct <= MAX_SPREAD_INDODAX_PCT

            if tren_5m_naik and tren_15m_naik and 42.0 <= rsi_5m <= 65.0 and candle_5m_hijau and vol_aktif and not candle_jatuh_beruntun:
                gaya = "SNIPER"
                bonus_1h = 5.0 if tren_1h_naik else 0.0
                skor_dasar = 78.0 + bonus_1h + min(12.0, (rasio_vol - 0.8) * 9.0) - abs(52.0 - rsi_5m) * 0.3
                diskon_entry_pct = min(max(atr_5m_pct * 0.40, 0.0015), 0.0045)
                prediksi = "🚀 BERPELUANG UNTUNG / BREAKOUT (5M & 15M Indodax Naik - SIAP ENTRY)"
                teknikal_valid = True
                faktor_bobot_status = 1.30
            elif (tren_15m_naik or tren_1h_naik) and 28.0 <= rsi_5m <= 48.0 and candle_5m_hijau and vol_aktif and not candle_jatuh_beruntun:
                gaya = "GRID"
                skor_dasar = 72.0 + (48.0 - rsi_5m) * 0.55 + (4.0 if dua_candle_5m_naik else 0.0)
                diskon_entry_pct = min(max(atr_5m_pct * 0.65, 0.0020), 0.0075)
                prediksi = "🟢 POTENSI REBOUND KUAT (Pullback 5M di Tren Naik - SIAP ENTRY)"
                teknikal_valid = True
                faktor_bobot_status = 1.15
            elif (rsi_5m <= 33.0 or (rsi_15m <= 35.0 and rsi_5m <= 46.0)) and dua_candle_5m_naik and not candle_jatuh_beruntun:
                gaya = "GRID"
                skor_dasar = 67.0 + max(0.0, (35.0 - min(rsi_5m, rsi_15m)) * 0.85)
                diskon_entry_pct = min(max(atr_5m_pct * 0.60, 0.0020), 0.0070)
                prediksi = "🟢 POTENSI REBOUND CEPAT (Oversold 5M/15M Indodax Memantul - SIAP ENTRY)"
                teknikal_valid = True
                faktor_bobot_status = 1.05
            elif tren_5m_naik and dua_candle_5m_naik and 38.0 <= rsi_5m <= 62.0 and rasio_vol >= 0.85 and not candle_jatuh_beruntun:
                gaya = "GRID"
                skor_dasar = 68.0 + min(6.0, (rasio_vol - 0.85) * 6.0) + (2.0 if rsi_15m >= 45.0 else 0.0)
                diskon_entry_pct = min(max(atr_5m_pct * 0.55, 0.0020), 0.0065)
                prediksi = "🟢 AWAL KEBANGKITAN TREN 5M (Momentum 5M Naik & Volume Aktif - SIAP ENTRY)"
                teknikal_valid = True
                faktor_bobot_status = 1.10
            elif (tren_15m_naik or tren_1h_naik) and not candle_jatuh_beruntun:
                gaya = "WAIT_PULLBACK"
                skor_dasar = 58.0
                diskon_entry_pct = 0.005
                prediksi = "🟢 POTENSI REBOUND (Tren makro naik, menunggu candle 5M memantul hijau)"
                teknikal_valid = False
                faktor_bobot_status = 0.0
            elif not tren_5m_naik and not tren_15m_naik and (candle_jatuh_beruntun or (rsi_5m < 40.0 and rasio_vol >= 1.25)):
                gaya = "WAIT_DOWNTREND"
                skor_dasar = 25.0
                diskon_entry_pct = 0.012
                prediksi = "🔴 BAHAYA JATUH LEBIH DALAM (Tekanan jual 5M & 15M deras - JANGAN BELI)"
                teknikal_valid = False
                faktor_bobot_status = 0.0
            else:
                gaya = "WAIT_SIDEWAYS"
                skor_dasar = 45.0
                diskon_entry_pct = 0.008
                prediksi = "🟡 SIDEWAYS WAJAR (Konsolidasi 5M/15M normal, aman ditahan / jangan beli dulu)"
                teknikal_valid = False
                faktor_bobot_status = 0.0

            siap_entry = teknikal_valid and spread_aman
            if teknikal_valid and not spread_aman:
                prediksi = f"⚠️ SPREAD LEBAR ({spread_pct*100:.2f}% > 0.35%) - Tunda beli baru agar tidak rugi spread"
            conviction_score = round(max(10.0, min(98.0, skor_dasar)), 1)
            acuan_beli_dasar = min(harga_idr, harga_ask)
            entry_ideal_idr = bulatkan_harga_indodax(coin, acuan_beli_dasar * (1.0 - diskon_entry_pct))
            tp_ideal_idr, sl_ideal_idr, tp_target_pct = hitung_tp_sl_dinamis_atr(
                coin, entry_ideal_idr, gaya if gaya in ["SNIPER", "GRID"] else "GRID", atr_5m_pct
            )

            peta_analisa[coin] = {
                "coin": coin,
                "sumber_ohlc": sumber_ohlc,
                "harga_idr": harga_idr,
                "harga_bid": harga_bid,
                "harga_ask": harga_ask,
                "spread_pct": spread_pct,
                "high_2jam_idr": high_2jam_idr,
                "tren": "UPTREND" if (tren_5m_naik or tren_15m_naik) else "SIDEWAYS/DOWN",
                "tren_5m_naik": tren_5m_naik,
                "tren_15m_naik": tren_15m_naik,
                "candle_5m_hijau": candle_5m_hijau,
                "candle_jatuh_beruntun": candle_jatuh_beruntun,
                "tren_detail": f"5M:{'UP' if tren_5m_naik else 'DN'}/15M:{'UP' if tren_15m_naik else 'DN'}/1H:{'UP' if tren_1h_naik else 'DN'}",
                "rsi": round(rsi_5m, 1),
                "rsi_15m": round(rsi_15m, 1),
                "atr_pct": round(atr_5m_pct, 5),
                "rasio_vol": round(rasio_vol, 2),
                "entry_ideal_idr": entry_ideal_idr,
                "tp_ideal_idr": tp_ideal_idr,
                "sl_ideal_idr": sl_ideal_idr,
                "tp_target_pct": tp_target_pct,
                "gaya": gaya,
                "skor": conviction_score,
                "prediksi": prediksi,
                "siap_entry": siap_entry,
                "teknikal_valid": teknikal_valid,
                "bobot_alokasi": round(conviction_score * faktor_bobot_status, 2)
            }
        except Exception:
            continue
    return peta_analisa

_MODEL_GEMINI_AKTIF = None
_LEVEL_PENALARAN_AKTIF = "MENENGAH (1024 Token Penalaran)"

def dapatkan_daftar_model_gemini_aktif():
    """
    Mengunci prioritas #1 pada 'gemini-3-flash-preview' dan memblokir model '-pro' / 'customtools'
    yang tidak memiliki kuota gratis (HTTP 429) pada akun Non-Pro.
    """
    global _MODEL_GEMINI_AKTIF
    prioritas_utama = [
        "gemini-3-flash-preview",
        "gemini-3.1-flash-preview"
    ]
    cadangan_darurat = [
        "gemini-3.1-flash-lite-preview",
        "gemini-flash-lite-latest"
    ]

    if _MODEL_GEMINI_AKTIF and "lite" not in _MODEL_GEMINI_AKTIF.lower():
        daftar_awal = [_MODEL_GEMINI_AKTIF] + [m for m in prioritas_utama if m != _MODEL_GEMINI_AKTIF]
    else:
        daftar_awal = list(prioritas_utama)

    try:
        url_list = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
        req = urllib.request.Request(url_list, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            model_server_utama = []
            model_server_lite = []
            for m in data.get("models", []):
                methods = m.get("supportedGenerationMethods", [])
                nama = str(m.get("name", "")).replace("models/", "")
                nama_kecil = nama.lower()
                # Hanya ambil keluarga FLASH generasi terbaru (Blokir 'pro', 'customtools', '2.5', '2.0', '1.5')
                if (
                    "generateContent" in methods
                    and "gemini" in nama_kecil
                    and "flash" in nama_kecil
                    and nama_kecil != "gemini-flash-latest"
                    and not any(x in nama_kecil for x in ["pro", "custom", "2.5", "2.0", "1.5", "tts", "image", "vision", "embedding", "aqa"])
                ):
                    if "lite" in nama_kecil:
                        model_server_lite.append(nama)
                    else:
                        model_server_utama.append(nama)

            urutan_final = []
            for k in daftar_awal + model_server_utama:
                if (k in model_server_utama or k == "gemini-3-flash-preview") and k not in urutan_final:
                    urutan_final.append(k)
            for k in cadangan_darurat + model_server_lite:
                if k not in urutan_final:
                    urutan_final.append(k)
            if urutan_final:
                return urutan_final[:3]
    except Exception:
        pass
    return ["gemini-3-flash-preview", "gemini-flash-lite-latest"]

def panggil_teks_gemini_ai(prompt, timeout_detik=25, mode_penalaran="MENENGAH"):
    """
    Memanggil API Gemini dengan mengutamakan 'gemini-3-flash-preview' + Tingkat Penalaran Menengah
    (thinkingBudget: 1024 tokens) serta jeda retry 6 detik jika terkena antrean kuota menitan (HTTP 429).
    """
    global _MODEL_GEMINI_AKTIF, _LEVEL_PENALARAN_AKTIF
    daftar_model = dapatkan_daftar_model_gemini_aktif()
    catatan_err = []

    budget_pikir = 256 if mode_penalaran == "RENDAH" else 1024

    for nama_model in daftar_model:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{nama_model}:generateContent?key={GEMINI_API_KEY}"
        daftar_payload = [
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 2048,
                    "thinkingConfig": {"thinkingBudget": budget_pikir}
                }
            },
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 2048
                }
            }
        ]

        maks_coba_model = 2 if "lite" not in nama_model.lower() else 1

        for percobaan in range(maks_coba_model):
            perlu_coba_ulang_model = False
            jeda_tunggu_detik = 2.0
            for idx_p, payload_dict in enumerate(daftar_payload):
                try:
                    body = json.dumps(payload_dict).encode("utf-8")
                    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
                    with urllib.request.urlopen(req, timeout=timeout_detik) as resp:
                        hasil = json.loads(resp.read().decode())
                        parts = hasil.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                        teks_list = [str(p.get("text", "")).strip() for p in parts if "text" in p and not p.get("thought", False)]
                        teks = "\n".join([t for t in teks_list if t]).strip()
                        if not teks and parts:
                            teks = str(parts[-1].get("text", "")).strip()
                        if teks:
                            if "lite" not in nama_model.lower():
                                _MODEL_GEMINI_AKTIF = nama_model
                            _LEVEL_PENALARAN_AKTIF = f"MENENGAH ({budget_pikir} Token)" if idx_p == 0 else "MENENGAH (Default Server)"
                            return f"[{nama_model}] {teks}", None
                except urllib.error.HTTPError as e:
                    try:
                        detail_err = json.loads(e.read().decode()).get("error", {}).get("message", str(e))[:90]
                    except Exception:
                        detail_err = str(e)[:90]
                    if e.code == 400 and idx_p == 0:
                        continue
                    if e.code in [429, 500, 502, 503, 504] and percobaan == 0 and maks_coba_model > 1:
                        perlu_coba_ulang_model = True
                        jeda_tunggu_detik = 6.0 if e.code == 429 else 2.0
                        break
                    catatan_err.append(f"{nama_model}->HTTP {e.code}({detail_err})")
                    break
                except Exception as e:
                    if percobaan == 0 and maks_coba_model > 1:
                        perlu_coba_ulang_model = True
                        break
                    catatan_err.append(f"{nama_model}->{str(e)[:60]}")
                    break

            if perlu_coba_ulang_model:
                time.sleep(jeda_tunggu_detik)
                continue
            break

    return None, " | ".join(catatan_err)

def bersihkan_awalan_model(teks):
    """Menghapus label '[nama-model] ' di awal kalimat saat mengecek kata kunci YA/TUNDA/TAHAN."""
    if teks.startswith("[") and "]" in teks:
        teks = teks.split("]", 1)[1]
    return teks.upper().lstrip("*_ \t\"'-")

def konsultasi_batch_semua_keputusan_gemini(daftar_tugas_ai, status_kompas_btc, defisit_recovery_idr=0.0):
    """
    Menganalisa seluruh tugas (Entry Baru, Geser Entry, Dynamic TP, & Evaluasi SL)
    hanya dalam 1x panggilan Batch ke gemini-3-flash-preview (Penalaran Menengah).
    """
    hasil_batch = {}
    if not daftar_tugas_ai:
        return hasil_batch

    if not GEMINI_API_KEY:
        for t in daftar_tugas_ai:
            hasil_batch[t["id"]] = (
                t.get("default_jika_error", False),
                "Mode tanpa API Key Gemini (mengikuti pengaman default)."
            )
        return hasil_batch

    konteks_mode = (
        f"MODE RECOVERY AKTIF (Target pulihkan defisit Rp{defisit_recovery_idr:,.0f})"
        if defisit_recovery_idr > 0 else "Mode Normal"
    )
    baris_tugas = []
    for t in daftar_tugas_ai:
        baris_tugas.append(f"[{t['id']}] {t['deskripsi']}")

    prompt_batch = (
        f"Anda adalah Chief Quant Scalper 5M Indodax. Evaluasi paket data real-time berikut sekaligus.\n"
        f"Konteks Pasar: Kompas BTCIDR={status_kompas_btc} | Status Bot={konteks_mode}.\n"
        f"Daftar Tugas Evaluasi ({len(daftar_tugas_ai)} item):\n"
        + "\n".join(baris_tugas) + "\n\n"
        f"INSTRUKSI JAWABAN:\n"
        f"Jawab WAJIB 1 baris untuk setiap ID dengan format persis:\n"
        f"[ID]: KEPUTUSAN - alasan singkat maksimal 10 kata\n"
        f"(Gunakan kata keputusan: YA atau TUNDA untuk BELI_BARU, dan YA atau TAHAN untuk GESER_ENTRY / DYNAMIC_TP / EVALUASI_SL)."
    )

    teks_respons, err_info = panggil_teks_gemini_ai(prompt_batch, timeout_detik=25, mode_penalaran="MENENGAH")
    if not teks_respons:
        print(f"⚠️ [INFO KONEKSI BATCH GEMINI]: {err_info}")
        for t in daftar_tugas_ai:
            hasil_batch[t["id"]] = (
                t.get("default_jika_error", False),
                f"Pengaman otomatis aktif (Info AI: {str(err_info)[:45]})."
            )
        return hasil_batch

    model_tag = f"[{_MODEL_GEMINI_AKTIF or 'gemini-3-flash-preview'}]"
    if teks_respons.startswith("[") and "]" in teks_respons:
        model_tag = teks_respons.split("]", 1)[0] + "]"
        isi_murni = teks_respons.split("]", 1)[1].strip()
    else:
        isi_murni = teks_respons.strip()

    for t in daftar_tugas_ai:
        tid = t["id"]
        jenis = t["jenis"]
        potongan_alasan = ""

        # Cari jawaban berdasarkan ID tugas di dalam teks respons batch (tahan banting untuk multi-baris maupun 1 baris)
        for segmen in isi_murni.replace(" | ", "\n").split("\n"):
            segmen_rapi = segmen.strip()
            if tid in segmen_rapi:
                bagian_kanan = segmen_rapi.split(tid, 1)[1].lstrip("]: -*_\t")
                # Potong jika di sebelah kanannya masih ada ID tugas lain (misal '[BELI_...')
                bagian_kanan = bagian_kanan.split("[")[0].strip()
                if bagian_kanan:
                    potongan_alasan = bagian_kanan
                    break

        # Jika hanya ada 1 tugas di dalam batch dan Gemini menjawab langsung tanpa menulis ulang ID
        if not potongan_alasan and len(daftar_tugas_ai) == 1:
            potongan_alasan = isi_murni.replace("\n", " ").strip()

        if potongan_alasan:
            teks_cek = potongan_alasan.upper().lstrip("*_ \t\"'-:")
            if jenis == "BELI_BARU":
                setuju = teks_cek.startswith("YA") and ("TUNDA" not in teks_cek[:20])
            else:
                setuju = teks_cek.startswith("YA") and ("TAHAN" not in teks_cek[:20])
            hasil_batch[tid] = (setuju, f"{model_tag} {potongan_alasan}")
        else:
            hasil_batch[tid] = (
                t.get("default_jika_error", False),
                f"{model_tag} Mengikuti pengaman default ({isi_murni[:45]})."
            )

    return hasil_batch

# ==============================================================================
# BAGIAN 6 & 7 TERPADU: PENGUMPULAN DATA, 1X BATCH GEMINI AI, & EKSEKUSI SERENTAK
# ==============================================================================
def proses_siklus_batch_terpadu(state, peta_analisa, dompet):
    """
    Tahap 1: Jalankan aksi pasti (Fill TP/Buy, Dynamic Cancel) & kumpulkan semua kandidat analisa (Entry, TP, SL).
    Tahap 2: Kirim 1x Batch ke Gemini AI.
    Tahap 3: Eksekusi seluruh keputusan Gemini AI secara serentak.
    """
    log_aksi = []
    log_transaksi = []
    ada_eksekusi_penting = False
    now_ts = time.time()

    sisa_koin_dompet = {
        c: dompet["coins_free"].get(c, 0.0) + dompet["coins_locked"].get(c, 0.0)
        for c in WATCHLIST_COINS.keys()
    }

    daftar_tugas_ai = []
    slot_menunggu_eksekusi = []

    # --------------------------------------------------------------------------
    # TAHAP 1A: PERIKSA POSISI AKTIF & KUMPULKAN TUGAS AI (GESER BELI / TP / SL)
    # --------------------------------------------------------------------------
    for idx_s, slot in enumerate(state["active_slots"]):
        coin = slot["coin"]
        info_pasar = peta_analisa.get(coin)
        harga_sekarang = info_pasar["harga_idr"] if info_pasar else float(slot["entry_price_idr"])
        harga_bid_asli = info_pasar.get("harga_bid", harga_sekarang) if info_pasar else harga_sekarang
        rsi_sekarang = info_pasar["rsi"] if info_pasar else 50.0
        tren_sekarang = info_pasar["tren"] if info_pasar else "SIDEWAYS/DOWN"
        tren_detail = info_pasar.get("tren_detail", tren_sekarang) if info_pasar else tren_sekarang
        prediksi_koin = info_pasar.get("prediksi", "-") if info_pasar else "-"

        mode_slot = slot.get("style", "GRID")
        entry_idr = float(slot["entry_price_idr"])
        tp_idr = float(slot.get("tp_price_idr", round(entry_idr * 1.016, 0)))
        sl_idr = float(slot.get("sl_price_idr", round(entry_idr * 0.982, 0)))
        slot["tp_price_idr"] = tp_idr
        slot["sl_price_idr"] = sl_idr

        koin_free = dompet["coins_free"].get(coin, 0.0)
        total_koin_tersisa = sisa_koin_dompet.get(coin, 0.0)
        qty_slot = float(slot.get("qty", 0.0))

        # KASUS A: WAITING_BUY
        if slot["status"] == "WAITING_BUY":
            nilai_koin_idr = total_koin_tersisa * harga_sekarang
            if (dompet["terhubung"] and nilai_koin_idr >= 5000) or (not dompet["terhubung"] and harga_sekarang <= entry_idr):
                slot["status"] = "HOLDING_FOR_TP"
                slot["filled_timestamp"] = now_ts
                slot["highest_price_idr"] = max(entry_idr, harga_sekarang)
                slot["peak_verified"] = True
                pasang_antrean_tp_di_indodax(slot, koin_free)
                sisa_koin_dompet[coin] = max(0.0, total_koin_tersisa - float(slot.get("qty", 0.0)))
                ada_eksekusi_penting = True
                pesan = (
                    f"✅ [TERBELI & PASANG TP] {coin} ({mode_slot}) aktif di Rp{entry_idr:,.0f}! "
                    f"Antrean Jual TP Dinamis dipasang di Rp{slot['tp_price_idr']:,.0f}."
                )
                log_aksi.append(pesan)
                log_transaksi.append(pesan)
                slot_menunggu_eksekusi.append({"slot": slot, "aksi": "TETAP"})
                continue

            umur_antre_menit = (now_ts - float(slot.get("timestamp", now_ts))) / 60.0
            umur_antre_jam = umur_antre_menit / 60.0

            masih_layak_entry = bool(info_pasar and info_pasar.get("siap_entry") is True and info_pasar.get("skor", 0) >= MIN_CONVICTION_SCORE)
            if not masih_layak_entry:
                batalkan_order_indodax(coin, slot.get("buy_order_id"))
                dompet["idr_free"] = float(dompet.get("idr_free", 0.0)) + float(slot.get("capital_idr", 0.0))
                ada_eksekusi_penting = True
                pesan = (
                    f"🔄 [DYNAMIC CANCEL & REALOKASI INSTAN] Antrean beli {coin} dibatalkan karena status berubah "
                    f"({prediksi_koin}). Modal Rp{slot.get('capital_idr', 0):,.0f} dialihkan ke koin siap_entry lainnya!"
                )
                log_aksi.append(pesan)
                log_transaksi.append(pesan)
                continue

            if umur_antre_jam >= REVIEW_ENTRY_HOURS:
                batalkan_order_indodax(coin, slot.get("buy_order_id"))
                dompet["idr_free"] = float(dompet.get("idr_free", 0.0)) + float(slot.get("capital_idr", 0.0))
                ada_eksekusi_penting = True
                pesan = f"🔄 [BATAL TIMEOUT ANTREAN] Order {coin} >{REVIEW_ENTRY_HOURS:.1f}j belum terjemput, dibatalkan untuk realokasi."
                log_aksi.append(pesan)
                log_transaksi.append(pesan)
                continue

            entry_ideal_baru = float(info_pasar["entry_ideal_idr"])
            selisih_entry_pct = abs(entry_ideal_baru - entry_idr) / entry_idr
            if selisih_entry_pct >= DYNAMIC_ENTRY_SHIFT_PCT:
                arah_geser = "DINAIKKAN" if entry_ideal_baru > entry_idr else "DITURUNKAN"
                tid = f"GESER_{coin}_{idx_s}"
                daftar_tugas_ai.append({
                    "id": tid,
                    "jenis": "GESER_ENTRY",
                    "default_jika_error": (entry_ideal_baru < entry_idr) or (umur_antre_menit >= 5.0),
                    "deskripsi": (
                        f"TIPE: GESER_ENTRY | Koin {coin} ({mode_slot}) antre beli di Rp{entry_idr:,.0f} ({umur_antre_menit:.1f}m). "
                        f"Harga skrg Rp{harga_sekarang:,.0f}, entry ideal bergeser {selisih_entry_pct*100:.2f}% untuk {arah_geser} ke Rp{entry_ideal_baru:,.0f} "
                        f"(Tren:{tren_detail}, RSI 5M:{rsi_sekarang}, Vol:{info_pasar.get('rasio_vol', 1.0)}x). "
                        f"Jawab YA (geser sekarang) atau TAHAN (pertahankan antrean lama)."
                    )
                })
                slot_menunggu_eksekusi.append({
                    "slot": slot,
                    "aksi": "TUNGGU_AI_GESER",
                    "task_id": tid,
                    "arah_geser": arah_geser,
                    "entry_ideal_baru": entry_ideal_baru,
                    "info_pasar": info_pasar,
                    "umur_antre_menit": umur_antre_menit,
                    "harga_sekarang": harga_sekarang
                })
                continue

            log_aksi.append(
                f"⏳ [ANTRE BELI DINAMIS {umur_antre_menit:.0f}m] {coin} ({mode_slot}) di Rp{entry_idr:,.0f} (Skrg: Rp{harga_sekarang:,.0f})."
            )
            slot_menunggu_eksekusi.append({"slot": slot, "aksi": "TETAP"})
            continue

        # KASUS B: HOLDING_FOR_TP
        if slot["status"] == "HOLDING_FOR_TP":
            batas_habis_slot = max(5000.0 / harga_sekarang, qty_slot * 0.50) if harga_sekarang > 0 else 0.0
            if dompet["terhubung"] and total_koin_tersisa < batas_habis_slot and slot.get("tp_order_id"):
                kenaikan_tp_pct = (tp_idr - entry_idr) / entry_idr
                profit_bersih = round(slot["capital_idr"] * (kenaikan_tp_pct - FEE_ROUNDTRIP_MAKER_PCT), 0)
                catat_hasil_transaksi_ke_recovery(state, profit_bersih, coin)
                ada_eksekusi_penting = True
                sisa_rec = state.get("loss_to_recover_idr", 0.0)
                info_rec = f" | Sisa Target Recovery: Rp{sisa_rec:,.0f}" if sisa_rec > 0 else ""
                pesan = (
                    f"🎉 [TP TERJUAL OTOMATIS!] {coin} ({mode_slot}) laku di Rp{tp_idr:,.0f} "
                    f"(+{kenaikan_tp_pct*100:.2f}%). Profit Bersih: +Rp{profit_bersih:,.0f}!{info_rec}"
                )
                log_aksi.append(pesan)
                log_transaksi.append(pesan)
                continue

            selisih_dust = total_koin_tersisa - qty_slot
            target_qty_slot = total_koin_tersisa if (qty_slot <= 0 or (0 < selisih_dust <= qty_slot * 0.02)) else min(qty_slot, total_koin_tersisa)
            qty_milik_slot = format_qty_koin(coin, target_qty_slot)
            sisa_koin_dompet[coin] = round(max(0.0, total_koin_tersisa - qty_milik_slot), 8)

            if not slot.get("peak_verified"):
                slot["highest_price_idr"] = max(entry_idr, harga_sekarang)
                slot["peak_verified"] = True

            puncak_tercatat = max(entry_idr, float(slot.get("highest_price_idr", entry_idr)), harga_sekarang)
            slot["highest_price_idr"] = puncak_tercatat

            harga_eksekusi_jual = bulatkan_harga_indodax(coin, max(harga_bid_asli, harga_sekarang * 0.999))
            kenaikan_skrg_pct = (harga_sekarang - entry_idr) / entry_idr
            kenaikan_bid_pct = (harga_eksekusi_jual - entry_idr) / entry_idr
            kenaikan_puncak_pct = (puncak_tercatat - entry_idr) / entry_idr
            target_tp_pct = max(0.008, (tp_idr - entry_idr) / entry_idr)
            pencapaian_puncak_ke_tp = kenaikan_puncak_pct / target_tp_pct
            lama_pegang_jam = (now_ts - float(slot.get("filled_timestamp", slot.get("timestamp", now_ts)))) / 3600.0
            estimasi_nilai_jual_skrg = qty_milik_slot * harga_eksekusi_jual

            # Cek Pemicu Dynamic Technical TP (>= +0.70% Bid)
            batas_pemicu_eval_tp_pct = 0.0070
            batas_lantai_eksekusi_pct = 0.0065
            sedang_untung_aman_bid = (kenaikan_bid_pct >= batas_pemicu_eval_tp_pct)
            candle_5m_merah = not (info_pasar.get("candle_5m_hijau", True) if info_pasar else True)
            tren_5m_patah = not (info_pasar.get("tren_5m_naik", True) if info_pasar else True)
            candle_jatuh = bool(info_pasar.get("candle_jatuh_beruntun", False)) if info_pasar else False

            sinyal_teknikal_melemah = (
                tren_5m_patah
                or candle_jatuh
                or (candle_5m_merah and (tren_sekarang != "UPTREND" or rsi_sekarang < 52.0))
            )
            sinyal_koreksi_puncak = (
                (pencapaian_puncak_ke_tp >= 0.60 or kenaikan_puncak_pct >= 0.0085)
                and harga_sekarang <= puncak_tercatat * 0.9970
                and (candle_5m_merah or tren_5m_patah)
            )
            sinyal_momentum_melambat = (
                kenaikan_bid_pct >= 0.0090
                and (tren_sekarang != "UPTREND" or info_pasar.get("gaya", "") not in ["SNIPER", "GRID"])
            ) if info_pasar else False

            waktu_eval_tp_terakhir = float(slot.get("last_tp_eval_ts", 0.0))
            bid_eval_tp_terakhir = float(slot.get("last_tp_eval_bid_idr", harga_eksekusi_jual))
            lewat_jeda_eval_tp = (now_ts - waktu_eval_tp_terakhir) >= 300.0
            profit_terkikis = ((harga_eksekusi_jual - bid_eval_tp_terakhir) / entry_idr) <= -0.0020

            butuh_evaluasi_tp_dini = (
                sedang_untung_aman_bid
                and (sinyal_teknikal_melemah or sinyal_koreksi_puncak or sinyal_momentum_melambat)
                and (lewat_jeda_eval_tp or profit_terkikis)
            )

            # Cek Pemicu Evaluasi Minus Dini (<= -1.00%) & Hard SL
            kena_hard_sl = (harga_sekarang <= sl_idr) or (harga_eksekusi_jual <= sl_idr)
            kena_zona_minus_dini = (kenaikan_bid_pct <= -0.0100 or kenaikan_skrg_pct <= -0.0100)
            acuan_harga_eval_skrg = min(harga_sekarang, harga_eksekusi_jual)
            waktu_eval_sl_terakhir = float(slot.get("last_sl_eval_ts", 0.0))
            harga_eval_sl_terakhir = float(slot.get("last_sl_eval_price_idr", entry_idr))
            lewat_jeda_eval_sl = (now_ts - waktu_eval_sl_terakhir) >= 600.0
            turun_makin_dalam = ((acuan_harga_eval_skrg - harga_eval_sl_terakhir) / harga_eval_sl_terakhir) <= -0.0025
            naik_level_ke_hard_sl = kena_hard_sl and not bool(slot.get("last_eval_was_hard_sl", False))

            butuh_sl = (
                (kena_hard_sl and (lewat_jeda_eval_sl or turun_makin_dalam or naik_level_ke_hard_sl))
                or (kena_zona_minus_dini and (lewat_jeda_eval_sl or turun_makin_dalam))
            )

            rsi_15m_k = info_pasar.get("rsi_15m", rsi_sekarang) if info_pasar else rsi_sekarang
            vol_k = info_pasar.get("rasio_vol", 1.0) if info_pasar else 1.0
            arah_candle = "Merah/Turun" if candle_5m_merah else "Hijau/Tertahan"

            if butuh_evaluasi_tp_dini and estimasi_nilai_jual_skrg >= MIN_LIMIT_ORDER_INDODAX_IDR:
                if sinyal_koreksi_puncak:
                    label_exit = f"DYNAMIC TP: KOREKSI DARI PUNCAK ({pencapaian_puncak_ke_tp*100:.0f}% TARGET TP)"
                elif sinyal_momentum_melambat:
                    label_exit = "DYNAMIC TP: MOMENTUM MELAMBAT"
                else:
                    label_exit = "DYNAMIC TP: SINYAL REVERSAL / TREN 5M MELEMAH"

                estimasi_untung_bersih_pct = (kenaikan_bid_pct - FEE_ROUNDTRIP_MAKER_PCT) * 100.0
                tid = f"TP_{coin}_{idx_s}"
                daftar_tugas_ai.append({
                    "id": tid,
                    "jenis": "DYNAMIC_TP",
                    "default_jika_error": False,
                    "deskripsi": (
                        f"TIPE: DYNAMIC_TP | Koin {coin} ({mode_slot}) Beli:Rp{entry_idr:,.0f}, Skrg Bid:Rp{harga_eksekusi_jual:,.0f} "
                        f"(Untung Bersih +{estimasi_untung_bersih_pct:.2f}% setelah fee, Puncak:Rp{puncak_tercatat:,.0f}, Target TP:Rp{tp_idr:,.0f}) "
                        f"[{label_exit}]. Tren:{tren_detail}, RSI 5M:{rsi_sekarang}, RSI 15M:{rsi_15m_k}, Candle 5M:{arah_candle}, Vol:{vol_k}x, "
                        f"Diagnosa:{prediksi_koin}. Jawab YA (Take Profit sekarang) atau TAHAN (kawal ke TP penuh)."
                    )
                })
                slot_menunggu_eksekusi.append({
                    "slot": slot,
                    "aksi": "TUNGGU_AI_TP",
                    "task_id": tid,
                    "label_exit": label_exit,
                    "estimasi_untung_bersih_pct": estimasi_untung_bersih_pct,
                    "harga_eksekusi_jual": harga_eksekusi_jual,
                    "harga_sekarang": harga_sekarang,
                    "harga_bid_asli": harga_bid_asli,
                    "kenaikan_skrg_pct": kenaikan_skrg_pct,
                    "kenaikan_bid_pct": kenaikan_bid_pct,
                    "qty_milik_slot": qty_milik_slot,
                    "koin_free": koin_free,
                    "lama_pegang_jam": lama_pegang_jam,
                    "batas_lantai_eksekusi_pct": batas_lantai_eksekusi_pct
                })
                continue

            if butuh_sl and estimasi_nilai_jual_skrg >= MIN_LIMIT_ORDER_INDODAX_IDR:
                label_sl = "HARD STOP LOSS" if kena_hard_sl else "EVALUASI CUT LOSS DINI (MINUS >1%)"
                tid = f"SL_{coin}_{idx_s}"
                daftar_tugas_ai.append({
                    "id": tid,
                    "jenis": "EVALUASI_SL",
                    "default_jika_error": kena_hard_sl,
                    "deskripsi": (
                        f"TIPE: EVALUASI_SL | Koin {coin} ({mode_slot}) Beli:Rp{entry_idr:,.0f}, sedang minus {kenaikan_bid_pct*100:+.2f}% "
                        f"di harga Bid [{label_sl}] (Last:Rp{harga_sekarang:,.0f}, Bid:Rp{harga_eksekusi_jual:,.0f}, Hard SL:Rp{sl_idr:,.0f}). "
                        f"Tren:{tren_detail}, RSI 5M:{rsi_sekarang}, RSI 15M:{rsi_15m_k}, Candle 5M:{arah_candle}, Vol:{vol_k}x, "
                        f"Diagnosa:{prediksi_koin}. Jawab YA (Cut Loss sekarang untuk perkecil rugi) atau TAHAN (tunggu pantulan)."
                    )
                })
                slot_menunggu_eksekusi.append({
                    "slot": slot,
                    "aksi": "TUNGGU_AI_SL",
                    "task_id": tid,
                    "label_sl": label_sl,
                    "kena_hard_sl": kena_hard_sl,
                    "acuan_harga_eval_skrg": acuan_harga_eval_skrg,
                    "harga_sekarang": harga_sekarang,
                    "harga_bid_asli": harga_bid_asli,
                    "kenaikan_skrg_pct": kenaikan_skrg_pct,
                    "kenaikan_bid_pct": kenaikan_bid_pct,
                    "qty_milik_slot": qty_milik_slot,
                    "koin_free": koin_free,
                    "lama_pegang_jam": lama_pegang_jam
                })
                continue

            slot_menunggu_eksekusi.append({
                "slot": slot,
                "aksi": "KAWAL_NORMAL",
                "harga_sekarang": harga_sekarang,
                "kenaikan_skrg_pct": kenaikan_skrg_pct,
                "kenaikan_bid_pct": kenaikan_bid_pct,
                "qty_milik_slot": qty_milik_slot,
                "koin_free": koin_free,
                "lama_pegang_jam": lama_pegang_jam,
                "sedang_untung_aman_bid": sedang_untung_aman_bid,
                "waktu_eval_tp_terakhir": waktu_eval_tp_terakhir,
                "kena_zona_minus_dini": kena_zona_minus_dini,
                "waktu_eval_sl_terakhir": waktu_eval_sl_terakhir
            })

    # --------------------------------------------------------------------------
    # TAHAP 1B: SIAPKAN KANDIDAT BELI BARU (DIMASUKKAN KE ANTREAN BATCH YANG SAMA)
    # --------------------------------------------------------------------------
    slot_aktif_sementara = [item["slot"] for item in slot_menunggu_eksekusi]
    modal_aktif_state = sum(float(s.get("capital_idr", 0)) for s in slot_aktif_sementara)
    sisa_plafon_bot = max(0.0, MAX_BOT_CAPITAL_IDR - modal_aktif_state)
    saldo_idr_tersedia = min(dompet["idr_free"], sisa_plafon_bot) if dompet["terhubung"] else sisa_plafon_bot

    slot_terisi = len(slot_aktif_sementara)
    sisa_slot_maks = max(0, MAX_CONCURRENT_COINS - slot_terisi)

    defisit_recovery = float(state.get("loss_to_recover_idr", 0.0))
    profit_hari_ini = float(state.get("realized_profit_today_idr", 0.0))
    batas_rugi_harian_ekstrem = MAX_BOT_CAPITAL_IDR * -0.060

    if profit_hari_ini <= batas_rugi_harian_ekstrem:
        skor_minimal_sesi = 75.0
    elif defisit_recovery > 0:
        skor_minimal_sesi = MIN_CONVICTION_SCORE + RECOVERY_SCORE_BOOST
    else:
        skor_minimal_sesi = MIN_CONVICTION_SCORE

    cooldown_map = state.get("sl_cooldown_until", {})
    koin_masih_cooldown = {}
    koin_tembus_cooldown = []

    for k_cd, batas_waktu_cd in cooldown_map.items():
        sisa_detik_cd = float(batas_waktu_cd) - now_ts
        if sisa_detik_cd <= 0:
            continue
        info_k = peta_analisa.get(k_cd, {})
        waktu_sejak_sl_menit = ((SL_COOLDOWN_MINUTES * 60) - sisa_detik_cd) / 60.0
        status_kuat = (
            info_k.get("gaya") == "SNIPER"
            or "REBOUND KUAT" in str(info_k.get("prediksi", ""))
        )
        konfirmasi_reversal = (
            info_k.get("siap_entry") is True
            and waktu_sejak_sl_menit >= 5.0
            and status_kuat
            and (info_k.get("skor", 0.0) >= 74.0 or info_k.get("rasio_vol", 0.0) >= 1.10)
        )
        if konfirmasi_reversal:
            koin_tembus_cooldown.append(f"{k_cd}(Skor:{info_k.get('skor')})")
        else:
            koin_masih_cooldown[k_cd] = batas_waktu_cd

    state["sl_cooldown_until"] = koin_masih_cooldown

    info_btc = peta_analisa.get("BTC", {})
    btc_sedang_dump = str(info_btc.get("prediksi", "")).startswith("🔴 BAHAYA") and info_btc.get("rsi", 50.0) < 36.0
    status_kompas_btc = f"{info_btc.get('tren_detail', 'N/A')} (RSI 5M:{info_btc.get('rsi', '-')})"

    rencana_beli_baru = []
    pesan_status_anggaran = None

    if saldo_idr_tersedia < MIN_NEW_BUY_ALLOCATION_IDR or sisa_slot_maks <= 0:
        pesan_status_anggaran = f"[MODAL AKTIF BEKERJA] Rp{modal_aktif_state:,.0f} di {slot_terisi} posisi (Sisa IDR: Rp{dompet['idr_free']:,.0f})."
    else:
        maks_koin_terbiayai_aman = int(saldo_idr_tersedia // MIN_NEW_BUY_ALLOCATION_IDR)
        batas_ambil_kandidat = min(sisa_slot_maks, maks_koin_terbiayai_aman)
        koin_sudah_ada = {s["coin"] for s in slot_aktif_sementara}

        kandidat_siap_entry = sorted(
            [
                v for v in peta_analisa.values()
                if (
                    v["coin"] not in koin_sudah_ada
                    and v["coin"] not in koin_masih_cooldown
                    and (v.get("siap_entry") is True or v["coin"] in [kc.split("(")[0] for kc in koin_tembus_cooldown])
                    and v["skor"] >= skor_minimal_sesi
                    and (not btc_sedang_dump or v["coin"] == "BTC" or v["skor"] >= 82.0)
                )
            ],
            key=lambda x: x.get("bobot_alokasi", x["skor"]),
            reverse=True
        )[:batas_ambil_kandidat]

        if not kandidat_siap_entry:
            info_cd = f", Cooldown: {list(koin_masih_cooldown.keys())}" if koin_masih_cooldown else ""
            info_rec = f" [Mode Recovery Defisit Rp{defisit_recovery:,.0f}]" if defisit_recovery > 0 else ""
            alasan_tahan = "Kompas BTCIDR dump tajam" if btc_sedang_dump else f"Belum ada koin SIAP ENTRY (Skor >= {skor_minimal_sesi}{info_cd})"
            pesan_status_anggaran = f"⏸️ [AI WAIT / CASH IS KING]{info_rec} Dana Rp{saldo_idr_tersedia:,.0f} aman di Rupiah ({alasan_tahan})."
        else:
            jumlah_siap = len(kandidat_siap_entry)
            total_bobot = sum(k.get("bobot_alokasi", k["skor"]) for k in kandidat_siap_entry)
            sisa_kas_simulasi = saldo_idr_tersedia

            if jumlah_siap == 1 and sisa_slot_maks >= 2 and saldo_idr_tersedia >= (MIN_NEW_BUY_ALLOCATION_IDR * 2):
                k_tunggal = kandidat_siap_entry[0]
                rasio_status = MAX_SINGLE_COIN_CAP_PCT if k_tunggal["gaya"] == "SNIPER" else 0.38
                anggaran_sesi_ini = max(MIN_NEW_BUY_ALLOCATION_IDR + 1000.0, min(saldo_idr_tersedia, math.floor(MAX_BOT_CAPITAL_IDR * rasio_status)))
            else:
                anggaran_sesi_ini = saldo_idr_tersedia

            for idx_k, kandidat in enumerate(kandidat_siap_entry):
                if sisa_kas_simulasi < MIN_NEW_BUY_ALLOCATION_IDR:
                    break
                if idx_k == jumlah_siap - 1:
                    alokasi_idr = math.floor(min(sisa_kas_simulasi, anggaran_sesi_ini))
                else:
                    porsi = kandidat.get("bobot_alokasi", kandidat["skor"]) / total_bobot
                    alokasi_idr = math.floor(anggaran_sesi_ini * porsi)
                    sisa_kandidat_lain = jumlah_siap - 1 - idx_k
                    maks_boleh_pakai = sisa_kas_simulasi - (sisa_kandidat_lain * MIN_NEW_BUY_ALLOCATION_IDR)
                    alokasi_idr = max(int(MIN_NEW_BUY_ALLOCATION_IDR), min(int(alokasi_idr), int(maks_boleh_pakai)))

                if alokasi_idr < MIN_NEW_BUY_ALLOCATION_IDR:
                    continue

                coin = kandidat["coin"]
                entry_idr = kandidat["entry_ideal_idr"]
                qty_rencana = hitung_kuantitas_koin(coin, alokasi_idr, entry_idr)
                nilai_efektif_idr = round(qty_rencana * entry_idr, 0)

                if nilai_efektif_idr < MIN_SAFE_SL_BUFFER_IDR:
                    step_qty = 10 ** (-WATCHLIST_COINS[coin]["step_decimals"])
                    qty_tambah = format_qty_koin(coin, qty_rencana + step_qty)
                    if (qty_tambah * entry_idr) <= sisa_kas_simulasi:
                        qty_rencana = qty_tambah
                        nilai_efektif_idr = round(qty_rencana * entry_idr, 0)

                if nilai_efektif_idr < MIN_SAFE_SL_BUFFER_IDR:
                    log_aksi.append(
                        f"⚠️ [SKIP {coin}] Nilai efektif Rp{nilai_efektif_idr:,.0f} di bawah buffer SL Rp{MIN_SAFE_SL_BUFFER_IDR:,.0f}."
                    )
                    continue

                is_tembus_cd = coin in [kc.split("(")[0] for kc in koin_tembus_cooldown]
                info_rev = " [V-Shape Reversal pasca SL]" if is_tembus_cd else ""
                tid = f"BELI_{coin}"
                daftar_tugas_ai.append({
                    "id": tid,
                    "jenis": "BELI_BARU",
                    "default_jika_error": False,
                    "deskripsi": (
                        f"TIPE: BELI_BARU | Koin {coin} ({kandidat['gaya']}, Skor:{kandidat['skor']}){info_rev}, "
                        f"Harga Skrg:Rp{kandidat['harga_idr']:,.0f}, Rencana Limit Buy:Rp{entry_idr:,.0f}, "
                        f"TP Dinamis:+{kandidat['tp_target_pct']}% (Alokasi:Rp{nilai_efektif_idr:,.0f}). "
                        f"Tren:{kandidat['tren_detail']}, RSI 5M:{kandidat['rsi']}, RSI 15M:{kandidat['rsi_15m']}, "
                        f"Vol:{kandidat['rasio_vol']}x, Spread:{kandidat['spread_pct']*100:.2f}%. "
                        f"Jawab YA (eksekusi beli) atau TUNDA (jangan beli)."
                    )
                })
                rencana_beli_baru.append({
                    "task_id": tid,
                    "kandidat": kandidat,
                    "qty_rencana": qty_rencana,
                    "nilai_efektif_idr": nilai_efektif_idr,
                    "is_tembus_cd": is_tembus_cd
                })
                sisa_kas_simulasi -= nilai_efektif_idr
                anggaran_sesi_ini = max(0.0, anggaran_sesi_ini - nilai_efektif_idr)

    # --------------------------------------------------------------------------
    # TAHAP 2: KIRIM 1X BATCH ANALISA KE GEMINI AI UNTUK SEMUA TUGAS SEKALIGUS
    # --------------------------------------------------------------------------
    hasil_batch_ai = konsultasi_batch_semua_keputusan_gemini(
        daftar_tugas_ai, status_kompas_btc, defisit_recovery
    )

    # --------------------------------------------------------------------------
    # TAHAP 3A: EKSEKUSI KEPUTUSAN GEMINI UNTUK POSISI AKTIF (GESER / TP / SL)
    # --------------------------------------------------------------------------
    slot_tetap_aktif = []
    for item in slot_menunggu_eksekusi:
        slot = item["slot"]
        aksi = item["aksi"]
        coin = slot["coin"]
        mode_slot = slot.get("style", "GRID")
        entry_idr = float(slot["entry_price_idr"])
        tp_idr = float(slot["tp_price_idr"])

        if aksi == "TETAP":
            slot_tetap_aktif.append(slot)
            continue

        if aksi == "TUNGGU_AI_GESER":
            setuju_geser, alasan_geser = hasil_batch_ai.get(item["task_id"], (False, "Pertahankan antrean."))
            arah_geser = item["arah_geser"]
            entry_ideal_baru = item["entry_ideal_baru"]
            info_pasar = item["info_pasar"]
            if setuju_geser:
                batalkan_order_indodax(coin, slot.get("buy_order_id"))
                time.sleep(0.8)
                modal_slot = float(slot.get("capital_idr", MIN_NEW_BUY_ALLOCATION_IDR))
                qty_baru = hitung_kuantitas_koin(coin, modal_slot, entry_ideal_baru)
                res_reentry = eksekusi_order_indodax(coin, "BUY", entry_ideal_baru, qty_koin=qty_baru)
                if apakah_order_sukses(res_reentry):
                    oid_baru = str(res_reentry.get("orderId"))
                    slot["entry_price_idr"] = entry_ideal_baru
                    slot["tp_price_idr"] = info_pasar["tp_ideal_idr"]
                    slot["sl_price_idr"] = info_pasar["sl_ideal_idr"]
                    slot["qty"] = res_reentry.get("qty", qty_baru)
                    slot["buy_order_id"] = oid_baru
                    slot["timestamp"] = now_ts
                    ada_eksekusi_penting = True
                    pesan = (
                        f"🎯 [DYNAMIC ENTRY {arah_geser}] Order beli {coin} digeser dari Rp{entry_idr:,.0f} -> Rp{entry_ideal_baru:,.0f} "
                        f"(TP Baru: Rp{slot['tp_price_idr']:,.0f}, OrderID: #{oid_baru}) | AI: {alasan_geser}"
                    )
                    log_aksi.append(pesan)
                    log_transaksi.append(pesan)
                    slot_tetap_aktif.append(slot)
                    continue
            else:
                log_aksi.append(
                    f"🛑 [DYNAMIC ENTRY TETAP] Antrean {coin} @ Rp{entry_idr:,.0f} dipertahankan (tidak jadi {arah_geser} ke Rp{entry_ideal_baru:,.0f}) | AI: {alasan_geser}"
                )
            log_aksi.append(
                f"⏳ [ANTRE BELI DINAMIS {item['umur_antre_menit']:.0f}m] {coin} ({mode_slot}) di Rp{entry_idr:,.0f} (Skrg: Rp{item['harga_sekarang']:,.0f})."
            )
            slot_tetap_aktif.append(slot)
            continue

        if aksi == "TUNGGU_AI_TP":
            setuju_jual, alasan_ai = hasil_batch_ai.get(item["task_id"], (False, "Tahan TP."))
            label_exit = item["label_exit"]
            qty_milik_slot = item["qty_milik_slot"]
            batas_lantai = item["batas_lantai_eksekusi_pct"]
            if setuju_jual:
                peta_ticker_terbaru = ambil_harga_idr_semua_koin()
                data_koin_terbaru = peta_ticker_terbaru.get(coin, {})
                bid_detik_ini = float(data_koin_terbaru.get("buy", item["harga_bid_asli"]) or item["harga_bid_asli"])
                last_detik_ini = float(data_koin_terbaru.get("last", item["harga_sekarang"]) or item["harga_sekarang"])
                harga_jual_detik_ini = bulatkan_harga_indodax(coin, max(bid_detik_ini, last_detik_ini * 0.999))
                pct_untung_detik_ini = (harga_jual_detik_ini - entry_idr) / entry_idr

                if pct_untung_detik_ini >= batas_lantai:
                    harga_lantai_aman = bulatkan_harga_indodax(coin, entry_idr * (1.0 + batas_lantai))
                    harga_eksekusi_final = max(harga_jual_detik_ini, harga_lantai_aman)
                    pct_final = (harga_eksekusi_final - entry_idr) / entry_idr

                    if slot.get("tp_order_id"):
                        batalkan_order_indodax(coin, slot["tp_order_id"])
                        slot["tp_order_id"] = None
                        time.sleep(0.5)

                    res_jual = eksekusi_order_indodax(coin, "SELL", harga_eksekusi_final, qty_koin=qty_milik_slot)
                    if apakah_order_sukses(res_jual):
                        profit_bersih = round(slot["capital_idr"] * (pct_final - FEE_ROUNDTRIP_MAKER_PCT), 0)
                        catat_hasil_transaksi_ke_recovery(state, profit_bersih, coin)
                        ada_eksekusi_penting = True
                        pesan = (
                            f"⚡ [{label_exit} DIEKSEKUSI] {coin} (Qty:{qty_milik_slot}) dijual di Rp{harga_eksekusi_final:,.0f} "
                            f"(Bid:+{pct_final*100:.2f}%, Profit Bersih: +Rp{profit_bersih:,.0f}) | AI: {alasan_ai}"
                        )
                        log_aksi.append(pesan)
                        log_transaksi.append(pesan)
                        continue
                    else:
                        pasang_antrean_tp_di_indodax(slot, qty_milik_slot)
                else:
                    slot["last_tp_eval_ts"] = now_ts
                    slot["last_tp_eval_bid_idr"] = harga_jual_detik_ini
                    log_aksi.append(
                        f"🛡️ [ANTI-SLIPPAGE GUARD] {coin} batal Dynamic TP karena harga Bid turun ke +{pct_untung_detik_ini*100:.2f}% "
                        f"saat AI berpikir (di bawah batas aman +{batas_lantai*100:.2f}%). Antrean TP Rp{tp_idr:,.0f} tetap dijaga!"
                    )
            else:
                slot["last_tp_eval_ts"] = now_ts
                slot["last_tp_eval_bid_idr"] = item["harga_eksekusi_jual"]
                slot["last_tp_eval_reason"] = alasan_ai
                log_aksi.append(
                    f"💎 [{label_exit} -> DITAHAN GEMINI AI] {coin} (Untung Bersih +{item['estimasi_untung_bersih_pct']:.2f}%) dikawal menuju TP Rp{tp_idr:,.0f} | AI: {alasan_ai}"
                )

        elif aksi == "TUNGGU_AI_SL":
            setuju_sl_ai, alasan_sl_ai = hasil_batch_ai.get(item["task_id"], (item["kena_hard_sl"], "Evaluasi SL."))
            label_sl = item["label_sl"]
            qty_milik_slot = item["qty_milik_slot"]
            if min(item["kenaikan_skrg_pct"], item["kenaikan_bid_pct"]) <= EMERGENCY_SL_PCT and not setuju_sl_ai:
                setuju_sl_ai = True
                alasan_sl_ai = f"Emergency SL ({min(item['kenaikan_skrg_pct'], item['kenaikan_bid_pct'])*100:+.2f}%) dieksekusi otomatis untuk proteksi modal."

            if setuju_sl_ai:
                if slot.get("tp_order_id"):
                    batalkan_order_indodax(coin, slot["tp_order_id"])
                    slot["tp_order_id"] = None
                    time.sleep(1.0)
                harga_jual_sl = bulatkan_harga_indodax(coin, min(item["harga_bid_asli"], item["harga_sekarang"] * 0.998))
                res_sl = eksekusi_order_indodax(coin, "SELL", harga_jual_sl, qty_koin=qty_milik_slot)
                if apakah_order_sukses(res_sl):
                    pnl_bersih = round(slot["capital_idr"] * (((harga_jual_sl - entry_idr) / entry_idr) - FEE_ROUNDTRIP_MAKER_PCT), 0)
                    catat_hasil_transaksi_ke_recovery(state, pnl_bersih, coin)
                    ada_eksekusi_penting = True
                    pesan = (
                        f"🛡️ [{label_sl} DIEKSEKUSI] {coin} (Qty:{qty_milik_slot}) dijual di Rp{harga_jual_sl:,.0f} "
                        f"(Bid:{item['kenaikan_bid_pct']*100:+.2f}%, PnL: Rp{pnl_bersih:,.0f} | Cooldown {SL_COOLDOWN_MINUTES}m & Mode Recovery Aktif) | AI: {alasan_sl_ai}"
                    )
                    log_aksi.append(pesan)
                    log_transaksi.append(pesan)
                    continue
                else:
                    pasang_antrean_tp_di_indodax(slot, qty_milik_slot)
            else:
                slot["last_sl_eval_ts"] = now_ts
                slot["last_sl_eval_price_idr"] = item["acuan_harga_eval_skrg"]
                slot["last_sl_eval_reason"] = alasan_sl_ai
                slot["last_eval_was_hard_sl"] = item["kena_hard_sl"]
                log_aksi.append(
                    f"🛑 [{label_sl} -> DITAHAN GEMINI AI] {coin} (Bid:{item['kenaikan_bid_pct']*100:+.2f}%) ditahan menunggu pantulan | AI: {alasan_sl_ai}"
                )

        elif aksi == "KAWAL_NORMAL":
            if item["sedang_untung_aman_bid"] and slot.get("last_tp_eval_reason"):
                sisa_jeda_tp = max(0.0, (300.0 - (now_ts - item["waktu_eval_tp_terakhir"])) / 60.0)
                log_aksi.append(
                    f"💎 [STATUS PROFIT DINI: DITAHAN GEMINI AI (Cek ulang {sisa_jeda_tp:.1f}m)] {coin} (Bid:+{item['kenaikan_bid_pct']*100:.2f}%) | AI Terakhir: {slot.get('last_tp_eval_reason')}"
                )
            if item["kena_zona_minus_dini"] and slot.get("last_sl_eval_reason"):
                sisa_jeda_m = max(0.0, (600.0 - (now_ts - item["waktu_eval_sl_terakhir"])) / 60.0)
                log_aksi.append(
                    f"🛑 [STATUS MINUS DINI: DITAHAN GEMINI AI (Evaluasi ulang dlm {sisa_jeda_m:.1f}m)] {coin} (Bid:{item['kenaikan_bid_pct']*100:+.2f}%) | AI Terakhir: {slot.get('last_sl_eval_reason')}"
                )

        # Pastikan antrean TP & Trailing Profit Lock tetap terjaga untuk semua slot HOLDING_FOR_TP yang masih bertahan
        if not slot.get("tp_order_id") and (not dompet["terhubung"] or item["koin_free"] > 0):
            pasang_antrean_tp_di_indodax(slot, item["qty_milik_slot"])
            ada_eksekusi_penting = True
            pesan = f"📌 [PASANG ULANG TP] Antrean TP {coin} diaktifkan di Rp{slot['tp_price_idr']:,.0f}."
            log_aksi.append(pesan)
            log_transaksi.append(pesan)

        if item["kenaikan_skrg_pct"] >= 0.0115:
            sl_kunci_untung = bulatkan_harga_indodax(coin, entry_idr * 1.0068)
            if sl_kunci_untung > slot["sl_price_idr"]:
                slot["sl_price_idr"] = sl_kunci_untung
                log_aksi.append(
                    f"🔒 [TRAILING PROFIT LOCK] {coin} naik +{item['kenaikan_skrg_pct']*100:.2f}%! SL dikunci di zona untung Rp{sl_kunci_untung:,.0f}."
                )

        status_tp_order = f"OrderTP:#{slot.get('tp_order_id')}" if slot.get("tp_order_id") else "TP-Aktif"
        log_aksi.append(
            f"🎯 [KAWAL {status_tp_order} | {item['lama_pegang_jam']:.1f}j] {coin} ({mode_slot}) | Skrg: Rp{item['harga_sekarang']:,.0f} (Bid:{item['kenaikan_bid_pct']*100:+.2f}%) "
            f"-> TP: Rp{tp_idr:,.0f} | SL: Rp{slot['sl_price_idr']:,.0f}"
        )
        slot_tetap_aktif.append(slot)

    # --------------------------------------------------------------------------
    # TAHAP 3B: EKSEKUSI KEPUTUSAN GEMINI UNTUK KANDIDAT BELI BARU
    # --------------------------------------------------------------------------
    if pesan_status_anggaran:
        log_aksi.append(pesan_status_anggaran)
    else:
        for rb in rencana_beli_baru:
            kandidat = rb["kandidat"]
            coin = kandidat["coin"]
            gaya = kandidat["gaya"]
            entry_idr = kandidat["entry_ideal_idr"]
            qty_rencana = rb["qty_rencana"]
            nilai_efektif_idr = rb["nilai_efektif_idr"]
            is_tembus_cd = rb["is_tembus_cd"]

            setuju_beli, alasan_gemini = hasil_batch_ai.get(rb["task_id"], (False, "TUNDA - Menunggu konfirmasi Batch AI."))
            if not setuju_beli:
                log_aksi.append(f"⏸️ [GEMINI AI HOLD ENTRY {coin}] Setup ditunda AI: {alasan_gemini}")
                continue

            tp_idr = kandidat["tp_ideal_idr"]
            sl_idr = kandidat["sl_ideal_idr"]
            tp_target_pct = kandidat["tp_target_pct"]

            res_order = eksekusi_order_indodax(coin, "BUY", entry_idr, qty_koin=qty_rencana)
            if apakah_order_sukses(res_order):
                order_id = str(res_order.get("orderId"))
                qty_koin = res_order.get("qty", qty_rencana)
                slot_tetap_aktif.append({
                    "coin": coin,
                    "style": gaya,
                    "status": "WAITING_BUY",
                    "capital_idr": nilai_efektif_idr,
                    "qty": qty_koin,
                    "entry_price_idr": entry_idr,
                    "tp_price_idr": tp_idr,
                    "sl_price_idr": sl_idr,
                    "highest_price_idr": entry_idr,
                    "rsi_at_entry": kandidat["rsi"],
                    "buy_order_id": order_id,
                    "timestamp": time.time()
                })
                ada_eksekusi_penting = True
                persen_plafon = (nilai_efektif_idr / MAX_BOT_CAPITAL_IDR) * 100.0
                label_rec = " [RECOVERY SETUP]" if (defisit_recovery > 0 or is_tembus_cd) else ""
                pesan = (
                    f"🚀 [ENTRY ORDER BELI #{order_id} - {gaya}{label_rec}] {coin} (Skor:{kandidat['skor']}) | "
                    f"Alokasi: Rp{nilai_efektif_idr:,.0f} ({persen_plafon:.0f}% Modal) | "
                    f"Beli: Rp{entry_idr:,.0f} -> TP Dinamis (+{tp_target_pct}%): Rp{tp_idr:,.0f} | AI: {alasan_gemini}"
                )
                log_aksi.append(pesan)
                log_transaksi.append(pesan)

    state["active_slots"] = slot_tetap_aktif
    return state, log_aksi, log_transaksi, ada_eksekusi_penting

# ==============================================================================
# BAGIAN 8: DETEKTOR SINYAL SIAGA & KESIMPULAN DIAGNOSA PASAR DINAMIS
# ==============================================================================
def cek_apakah_butuh_pengawasan_intensif(state, peta_analisa):
    alasan_siaga = []
    if FORCE_CONTINUOUS_WATCH:
        alasan_siaga.append("FORCE_CONTINUOUS_WATCH aktif")

    for slot in state.get("active_slots", []):
        coin = slot["coin"]
        info = peta_analisa.get(coin)
        if not info:
            continue
        skrg = info["harga_idr"]
        harga_bid = info.get("harga_bid", skrg)
        entry = float(slot["entry_price_idr"])
        tp = float(slot.get("tp_price_idr", entry * 1.015))
        puncak = max(entry, float(slot.get("highest_price_idr", entry)), skrg)
        nilai_skrg = float(slot.get("qty", 0)) * skrg

        if slot["status"] == "HOLDING_FOR_TP":
            pnl_bid_pct = (harga_bid - entry) / entry
            target_pct = max(0.008, (tp - entry) / entry)
            rasio_puncak_ke_tp = ((puncak - entry) / entry) / target_pct

            if pnl_bid_pct >= 0.0070:
                alasan_siaga.append(f"{coin} sudah di zona untung bersih Bid +{pnl_bid_pct*100:.2f}% (kawal ketat Dynamic TP)")
            elif rasio_puncak_ke_tp >= 0.60 and pnl_bid_pct > 0:
                alasan_siaga.append(f"{coin} pernah menyentuh {rasio_puncak_ke_tp*100:.0f}% target TP (kawal Missed-Peak)")
            elif pnl_bid_pct <= -0.0085 and nilai_skrg >= MIN_LIMIT_ORDER_INDODAX_IDR:
                alasan_siaga.append(f"{coin} turun {pnl_bid_pct*100:.2f}% mendekati SL Range (kawal penyelamatan SL)")

        elif slot["status"] == "WAITING_BUY":
            jarak_beli_pct = abs(skrg - entry) / entry
            if jarak_beli_pct <= 0.008:
                alasan_siaga.append(f"Antrean beli {coin} berjarak {jarak_beli_pct*100:.2f}% (kawal Dynamic Entry & TP)")

    return (len(alasan_siaga) > 0), alasan_siaga

def buat_kesimpulan_patroli_dinamis(state, peta_analisa):
    total_koin_pasar = len(peta_analisa)
    koin_uptrend = [k for k, v in peta_analisa.items() if v.get("tren") == "UPTREND"]
    koin_siap_beli = [f"{k}({v['gaya']}:Skor {v['skor']}|TP+{v['tp_target_pct']}%)" for k, v in peta_analisa.items() if v.get("siap_entry")]
    rata_rsi_5m = (sum(v.get("rsi", 50.0) for v in peta_analisa.values()) / total_koin_pasar) if total_koin_pasar > 0 else 50.0
    kandidat_terkuat = max(peta_analisa.values(), key=lambda x: x.get("skor", 0.0)) if peta_analisa else None
    info_skor_tertinggi = f"{kandidat_terkuat['coin']} (Skor:{kandidat_terkuat['skor']})" if kandidat_terkuat else "-"
    sumber_grafik = kandidat_terkuat.get("sumber_ohlc", "INDODAX-IDR") if kandidat_terkuat else "INDODAX-IDR"
    info_btc = peta_analisa.get("BTC", {})
    kompas_btc_str = f"BTCIDR {info_btc.get('tren_detail', '-')} (RSI 5M:{info_btc.get('rsi', '-')})"
    defisit_rec = float(state.get("loss_to_recover_idr", 0.0))
    status_rec_str = f"AKTIF (Target Pulihkan Rp{defisit_rec:,.0f})" if defisit_rec > 0 else " Aman (0 Defisit)"

    ringkasan_pasar = (
        f"Pasar [{sumber_grafik} 5M+15M+1H]: {len(koin_uptrend)}/{total_koin_pasar} koin UPTREND | "
        f"Rata-rata RSI 5M: {rata_rsi_5m:.1f} | Kompas: {kompas_btc_str} | Sinyal Tertinggi: {info_skor_tertinggi}\n"
        f"   -> Mode Recovery Balik Modal:{status_rec_str}\n"
        f"   -> Koin Berstatus SIAP ENTRY Saat Ini ({len(koin_siap_beli)} koin): {', '.join(koin_siap_beli) or 'Belum ada (menunggu konfirmasi candle 5M hijau)'}"
    )

    detail_diagnosa_koin = []
    for slot in state.get("active_slots", []):
        coin = slot["coin"]
        info = peta_analisa.get(coin, {})
        skrg = info.get("harga_idr", float(slot["entry_price_idr"]))
        harga_bid = info.get("harga_bid", skrg)
        entry = float(slot["entry_price_idr"])
        tp_idr = float(slot.get("tp_price_idr", entry * 1.015))
        pnl_bid_pct = (harga_bid - entry) / entry
        nilai_idr = float(slot.get("qty", 0)) * harga_bid
        rsi_k = info.get("rsi", 50.0)
        tren_k = info.get("tren_detail", info.get("tren", "-"))
        prediksi_k = info.get("prediksi", "🟡 SIDEWAYS WAJAR")

        if slot.get("status") == "WAITING_BUY":
            detail_diagnosa_koin.append(
                f"   * {coin} [ANTRE BELI DINAMIS @ Rp{entry:,.0f} -> TP Rp{tp_idr:,.0f} | Skrg: Rp{skrg:,.0f}] -> {prediksi_k} [{tren_k}, RSI 5M:{rsi_k}]"
            )
        else:
            detail_diagnosa_koin.append(
                f"   * {coin} (Bid:{pnl_bid_pct*100:+.2f}% | Nilai Rp{nilai_idr:,.0f} -> TP Rp{tp_idr:,.0f}) -> {prediksi_k} [{tren_k}, RSI 5M:{rsi_k}]"
            )

    teks_diagnosa = "\n".join(detail_diagnosa_koin) if detail_diagnosa_koin else "   * Belum ada posisi aktif (100% Cash is King - Memburu Sinyal Scalping 5M Indodax)."

    return (
        f"🟢 [PATROLI PRO SCALPER 5M SELESAI | Profit Hari Ini: Rp{state.get('realized_profit_today_idr', 0):,.0f} ({state.get('completed_trades_today', 0)} Trade)]\n"
        f"📊 DIAGNOSA PORTOFOLIO & PREDIKSI CANDLESTICK RUPIAH INDODAX (5M + 15M + 1H):\n"
        f"{teks_diagnosa}\n"
        f"   -> {ringkasan_pasar}"
    )

# ==============================================================================
# BAGIAN 9: LAPORAN KE GOOGLE SHEETS (KHUSUS SAAT TERJADI TRANSAKSI ENTRY/TP/SL)
# ==============================================================================
def lapor_ke_google_sheets(state, log_khusus_transaksi, dompet, harga_live_map=None):
    tz_wib = timezone(timedelta(hours=7))
    waktu_lokal = datetime.now(tz_wib).strftime("%Y-%m-%d %H:%M:%S")

    floating_pnl = 0.0
    if harga_live_map:
        for s in state["active_slots"]:
            if s.get("status") == "HOLDING_FOR_TP":
                harga_skrg = harga_live_map.get(s["coin"], {}).get("buy", harga_live_map.get(s["coin"], {}).get("last", s["entry_price_idr"]))
                floating_pnl += (harga_skrg - float(s["entry_price_idr"])) * float(s.get("qty", 0.0))

    ringkasan_slot = ", ".join(
        [f"{s['coin']}[{s['style']}:{s['status']}:Rp{s['capital_idr']:,.0f}@Rp{s['entry_price_idr']:,.0f}->TP:Rp{s['tp_price_idr']:,.0f}]" for s in state["active_slots"]]
    ) or "Semua slot kosong"
    catatan_transaksi = " | ".join(log_khusus_transaksi)[:490]

    payload = {
        "tanggal": waktu_lokal,
        "pasangan": f"INDODAX PRO 5M ({len(state['active_slots'])} Posisi)",
        "modal_aktif_idr": sum(s["capital_idr"] for s in state["active_slots"]),
        "harga_acuan_idr": round(dompet.get("idr_free", 0.0), 0),
        "jumlah_grid_tereksekusi": state["completed_trades_today"],
        "profit_terealisasi_idr": state["realized_profit_today_idr"],
        "floating_pnl_idr": round(floating_pnl, 0),
        "tren_1h": ringkasan_slot,
        "rsi_14": f"Rec:Rp{state.get('loss_to_recover_idr', 0):,.0f}",
        "analisis_ai_gemini": catatan_transaksi
    }

    print("📤 [TRANSAKSI TERDETEKSI - KIRIM KE GOOGLE SHEETS]:")
    print(json.dumps(payload, indent=2))

    if GOOGLE_SHEETS_WEBHOOK_URL:
        try:
            req = urllib.request.Request(
                GOOGLE_SHEETS_WEBHOOK_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                print("✅ Sukses kirim transaksi ke Google Sheets:", resp.read().decode())
        except Exception as e:
            print("⚠️ Gagal kirim ke Google Sheets:", e)

# ==============================================================================
# BAGIAN 10: PROGRAM UTAMA (1 SIKLUS = MAKSIMAL 1X BATCH GEMINI AI)
# ==============================================================================
def jalankan_satu_siklus_penuh(state, paksa_kirim_sheets=False):
    dompet = ambil_saldo_lengkap_indodax()
    if LIVE_TRADING_ENABLED and not dompet.get("terhubung"):
        print("⚠️ Gagal terhubung ke API Indodax. Siklus dilewati agar state tidak rusak.")
        return state, False, [], False, {}

    harga_live_map = ambil_harga_idr_semua_koin()

    # Langkah 1: Pulihkan otomatis koin di dompet yang belum masuk daftar aktif
    state, log_recovery = sinkronkan_koin_dompet_indodax(state, dompet, harga_live_map)
    if log_recovery:
        dompet = ambil_saldo_lengkap_indodax()

    # Langkah 2: Analisa Teknikal Indodax (5M+15M+1H) -> Kumpulkan Semua Tugas -> 1x Batch Gemini -> Eksekusi
    peta_analisa_pasar = analisa_teknikal_lengkap_pasar(harga_live_map)
    state, log_siklus, log_tx_siklus, ada_aksi_siklus = proses_siklus_batch_terpadu(state, peta_analisa_pasar, dompet)
    simpan_state_bot(state)

    butuh_siaga, alasan_siaga = cek_apakah_butuh_pengawasan_intensif(state, peta_analisa_pasar)
    semua_log_konsol = log_recovery + log_siklus
    for baris in semua_log_konsol:
        print("  ", baris)

    log_khusus_transaksi = log_recovery + log_tx_siklus
    ada_transaksi_nyata = bool(log_khusus_transaksi) or ada_aksi_siklus

    if ada_transaksi_nyata or paksa_kirim_sheets:
        lapor_ke_google_sheets(state, log_khusus_transaksi or semua_log_konsol, dompet, harga_live_map)
    else:
        print("ℹ️ [TIDAK ADA TRANSAKSI BARU] Sesi patroli tenang, Google Sheets tidak ditambah baris baru agar jurnal tetap bersih.")

    return state, butuh_siaga, alasan_siaga, ada_transaksi_nyata, peta_analisa_pasar

def cek_status_koneksi_gemini_awal():
    """Memverifikasi API Key & kesiapan model utama tanpa membuang kuota generateContent harian."""
    global _MODEL_GEMINI_AKTIF
    if not GEMINI_API_KEY:
        print("⚠️ [STATUS GEMINI AI]: BELUM TERHUBUNG (GEMINI_API_KEY kosong / belum terbaca dari Secrets)")
        return
    daftar = dapatkan_daftar_model_gemini_aktif()
    if daftar:
        model_utama = daftar[0]
        if "lite" not in model_utama.lower():
            _MODEL_GEMINI_AKTIF = model_utama
        print(
            f"✅ [STATUS GEMINI AI SIAP | Model Utama: {model_utama} | Penalaran: {_LEVEL_PENALARAN_AKTIF}] "
            f"(100% kuota dihemat khusus untuk analisa Entry, TP & SL)"
        )
    else:
        print("❌ [STATUS GEMINI AI GAGAL TERHUBUNG] Tidak dapat memuat daftar model dari Google API.")

if __name__ == "__main__":
    waktu_mulai = time.time()
    batas_waktu_siaga = waktu_mulai + (ACTIVE_WATCH_MINUTES * 60)

    cek_status_koneksi_gemini_awal()
    state = muat_state_bot()
    state, butuh_siaga, alasan_siaga, _, peta_analisa_terakhir = jalankan_satu_siklus_penuh(
        state, paksa_kirim_sheets=False
    )

    if butuh_siaga and ACTIVE_WATCH_MINUTES > 0:
        print(f"\n🔥 [SINYAL DETEKSI AKTIF] Bot masuk Mode Pengawasan Intensif selama {ACTIVE_WATCH_MINUTES} menit:")
        for alasan in alasan_siaga:
            print(f"   -> {alasan}")

        putaran = 1
        while time.time() + WATCH_INTERVAL_SECONDS < batas_waktu_siaga:
            sisa_menit = (batas_waktu_siaga - time.time()) / 60.0
            print(f"\n⏱️ [SIAGA PUTARAN #{putaran} | Sisa waktu jaga: {sisa_menit:.1f} menit] Menunggu {WATCH_INTERVAL_SECONDS} detik...")
            time.sleep(WATCH_INTERVAL_SECONDS)
            putaran += 1

            state, masih_butuh_siaga, alasan_baru, ada_eksekusi, peta_analisa_terakhir = jalankan_satu_siklus_penuh(
                state, paksa_kirim_sheets=False
            )
            if ada_eksekusi:
                print("✅ [TRANSAKSI REAL-TIME BERHASIL] State & Google Sheets telah diperbarui!")
            if not masih_butuh_siaga:
                print("\n" + buat_kesimpulan_patroli_dinamis(state, peta_analisa_terakhir))
                break
    else:
        print("\n" + buat_kesimpulan_patroli_dinamis(state, peta_analisa_terakhir))
