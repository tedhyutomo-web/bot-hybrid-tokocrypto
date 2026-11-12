# ==============================================================================
# PRO QUANT HYBRID AI TRADING BOT 24/7 (INDODAX TRADE API V2 + GEMINI AI)
# ==============================================================================
# Fitur Unggulan Versi Scalping Multi-Timeframe (15M + 1H) & Smart Allocation:
# 1. AUTO-RECOVERY DOMPET INDODAX (SINKRONISASI KOIN YATIM / ORPHAN COIN)
# 2. PROTEKSI MUTLAK SL (>= Rp32.000/KOIN) AGAR TIDAK TERTOLAK BATAS Rp25.000 INDODAX
# 3. FILTER SELEKSI KETAT "SIAP ENTRY" + VALIDASI BELI & JUAL OLEH GEMINI AI
# 4. ALOKASI MODAL PROPORSIONAL BERDASARKAN JUMLAH KOIN SIAP ENTRY & STATUSNYA
# 5. ANALISIS SCALPING MULTI-TIMEFRAME (15M + 1H) & DIAGNOSA ARAH PER KOIN
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
# BAGIAN 1: KONFIGURASI UTAMA, PROTEKSI SL & PARAMETER MODE SIAGA DINAMIS
# ==============================================================================
MAX_BOT_CAPITAL_IDR = float(os.getenv("MAX_BOT_CAPITAL_IDR", "100000"))
MIN_LIMIT_ORDER_INDODAX_IDR = 25000.0  # Syarat minimum nilai Limit Order Indodax
MIN_SAFE_SL_BUFFER_IDR = 28500.0       # Nilai bersih koin setelah pembulatan qty wajib >= Rp28.500 agar saat SL -3% tetap > Rp25.000
MIN_NEW_BUY_ALLOCATION_IDR = 32000.0   # Minimal alokasi beli baru per koin agar 100% aman saat eksekusi SL
MAX_SINGLE_COIN_CAP_PCT = 0.45         # Maksimal porsi modal pada 1 koin jika hanya ada 1 sinyal siap_entry (45% plafon)
FEE_ROUNDTRIP_MAKER_PCT = 0.0055       # Estimasi total biaya beli+jual+PPN+CFX Indodax ~0.55%

MIN_CONVICTION_SCORE = 64.0            # Skor kelayakan minimal agar koin masuk nominasi siap_entry (0 - 100)
MAX_CONCURRENT_COINS = 3               # Maksimal 3 koin bersamaan (dengan modal Rp100rb -> ~Rp32rb-Rp35rb/koin)

TP_GRID_BASE_PCT = 0.020               # +2.0% Target dasar mode Grid (Mean-Reversion / Rebound)
SL_GRID_BASE_PCT = 0.020               # -2.0% Batas Hard SL mode Grid
TP_SNIPER_BASE_PCT = 0.036             # +3.6% Target dasar mode Sniper (Momentum Breakout)
SL_SNIPER_BASE_PCT = 0.018             # -1.8% Batas Hard SL mode Sniper

ACTIVE_WATCH_MINUTES = int(os.getenv("ACTIVE_WATCH_MINUTES", "30"))
WATCH_INTERVAL_SECONDS = int(os.getenv("WATCH_INTERVAL_SECONDS", "60"))
FORCE_CONTINUOUS_WATCH = os.getenv("FORCE_CONTINUOUS_WATCH", "false").lower() == "true"

REVIEW_ENTRY_HOURS = 4.0               # Evaluasi ulang antrean Limit Buy setelah 4 jam

WATCHLIST_COINS = {
    "SOL":  {"v2_symbol": "SOLIDR",  "indodax_key": "sol_idr",  "kraken_pair": "SOLUSD",   "step_decimals": 4, "price_step": 1},
    "BTC":  {"v2_symbol": "BTCIDR",  "indodax_key": "btc_idr",  "kraken_pair": "XXBTZUSD", "step_decimals": 6, "price_step": 1000},
    "ETH":  {"v2_symbol": "ETHIDR",  "indodax_key": "eth_idr",  "kraken_pair": "XETHZUSD", "step_decimals": 5, "price_step": 1000},
    "XRP":  {"v2_symbol": "XRPIDR",  "indodax_key": "xrp_idr",  "kraken_pair": "XXRPZUSD", "step_decimals": 2, "price_step": 1},
    "ADA":  {"v2_symbol": "ADAIDR",  "indodax_key": "ada_idr",  "kraken_pair": "ADAUSD",   "step_decimals": 2, "price_step": 1},
    "SUI":  {"v2_symbol": "SUIIDR",  "indodax_key": "sui_idr",  "kraken_pair": "SUIUSD",   "step_decimals": 2, "price_step": 1},
    "DOGE": {"v2_symbol": "DOGEIDR", "indodax_key": "doge_idr", "kraken_pair": "XDGUSD",   "step_decimals": 0, "price_step": 1}
}

# Referensi harga beli untuk posisi lama yang sedang berjalan
KNOWN_ENTRY_REFERENCE = {
    "XRP":  {"entry_price_idr": 19742.0,      "tp_price_idr": 20137.0,      "capital_idr": 25000.0, "style": "GRID"},
    "SUI":  {"entry_price_idr": 15238.0,      "tp_price_idr": 15787.0,      "capital_idr": 25000.0, "style": "SNIPER"},
    "BTC":  {"entry_price_idr": 1346695584.0, "tp_price_idr": 1373629496.0, "capital_idr": 25000.0, "style": "GRID"},
    "DOGE": {"entry_price_idr": 1261.0,       "tp_price_idr": 1286.0,       "capital_idr": 23335.0, "style": "GRID"}
}

STATE_FILE = "bot_state_tokocrypto.json"

INDODAX_API_KEY = os.getenv("INDODAX_API_KEY", os.getenv("TOKOCRYPTO_API_KEY", "")).strip()
INDODAX_SECRET_KEY = os.getenv("INDODAX_SECRET_KEY", os.getenv("TOKOCRYPTO_SECRET_KEY", "")).strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GOOGLE_SHEETS_WEBHOOK_URL = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"

# ==============================================================================
# BAGIAN 2: MANAJEMEN MEMORI POSISI BOT (STATE TRACKER)
# ==============================================================================
def muat_state_bot():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "active_slots": [],
        "realized_profit_today_idr": 0.0,
        "completed_trades_today": 0
    }

def simpan_state_bot(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ==============================================================================
# BAGIAN 3: KONEKSI RESMI INDODAX TRADE API V2 (HMAC-SHA256)
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
    """Mengambil saldo IDR dan koin (free maupun locked) dari Indodax Trade API V2."""
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
    qty = math.floor(raw_qty * factor) / factor
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
    """Memasang antrean LIMIT SELL (Take Profit) langsung di buku order Indodax."""
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
                harga_map[coin] = {
                    "last": float(t["last"]),
                    "high_24h": float(t.get("high", t["last"])),
                    "low_24h": float(t.get("low", t["last"]))
                }
    except Exception as e:
        print("Fallback harga IDR:", e)
    return harga_map

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
            tp_pct = TP_SNIPER_BASE_PCT if style == "SNIPER" else TP_GRID_BASE_PCT
            sl_pct = SL_SNIPER_BASE_PCT if style == "SNIPER" else SL_GRID_BASE_PCT
            tp_idr = ref.get("tp_price_idr", bulatkan_harga_indodax(coin, entry_idr * (1.0 + tp_pct)))
            sl_idr = bulatkan_harga_indodax(coin, entry_idr * (1.0 - sl_pct))
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
            if state.get("realized_profit_today_idr", 0) < 0 and state.get("completed_trades_today", 0) > 0:
                state["realized_profit_today_idr"] = 0.0
                state["completed_trades_today"] = max(0, state["completed_trades_today"] - 1)

            if k_free > 0:
                pasang_antrean_tp_di_indodax(slot_pulih, k_free)

            state["active_slots"].append(slot_pulih)
            log_recovery.append(
                f"♻️ [AUTO-RECOVERY DOMPET] {coin} (Qty:{total_qty}) ditemukan di dompet Indodax! "
                f"Posisi dipulihkan (Beli: Rp{entry_idr:,.0f} -> Antrean TP: Rp{tp_idr:,.0f})."
            )
    return state, log_recovery

# ==============================================================================
# BAGIAN 5: ANALISIS SCALPING (15M + 1H), STATUS SIAP ENTRY & KONSULTASI GEMINI
# ==============================================================================
def analisa_teknikal_lengkap_pasar(harga_idr_map):
    peta_analisa = {}
    for coin, info in WATCHLIST_COINS.items():
        data_ticker = harga_idr_map.get(coin)
        if not data_ticker or data_ticker["last"] <= 0:
            continue
        harga_idr = data_ticker["last"]
        try:
            url = f"https://api.kraken.com/0/public/OHLC?pair={info['kraken_pair']}&interval=15"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                res = json.loads(resp.read().decode())
            result_key = [k for k in res["result"].keys() if k != "last"][0]
            raw = res["result"][result_key][-200:]  # 200 candle 15m = 50 jam terakhir
            closes = [float(r[4]) for r in raw]
            highs = [float(r[2]) for r in raw]
            lows = [float(r[3]) for r in raw]
            vols = [float(r[6]) for r in raw]

            # EMA Timeframe 15 Menit (Momentum Scalping)
            ema20 = sum(closes[-20:]) / len(closes[-20:])
            ema50 = sum(closes[-50:]) / len(closes[-50:])

            # EMA Setara Timeframe 1 Jam (80 candle 15m = 20 jam, 200 candle 15m = 50 jam)
            ema_1h_cepat = sum(closes[-80:]) / len(closes[-80:])
            ema_1h_lambat = sum(closes[-200:]) / len(closes[-200:])
            tren_15m_naik = ema20 > ema50
            tren_1h_naik = ema_1h_cepat > ema_1h_lambat

            # RSI-14 pada Timeframe 15 Menit
            gains, losses = [], []
            for i in range(-14, 0):
                diff = closes[i] - closes[i - 1]
                gains.append(max(diff, 0))
                losses.append(max(-diff, 0))
            rsi = 100 - (100 / (1 + (sum(gains) / 14.0) / ((sum(losses) / 14.0) or 0.0001)))

            # ATR & High 2 Jam Terakhir (8 candle x 15 menit = 2 jam)
            tr_list = [highs[i] - lows[i] for i in range(-14, 0)]
            atr_pct = (sum(tr_list) / 14.0) / closes[-1]
            rasio_high_2jam = max(highs[-8:]) / closes[-1] if closes[-1] > 0 else 1.0
            high_2jam_idr = round(harga_idr * max(1.0, rasio_high_2jam), 0)

            vol_rata = sum(vols[-20:-1]) / 19.0 if len(vols) >= 20 else (vols[-1] or 1.0)
            rasio_vol = vols[-1] / (vol_rata or 1.0)

            # Konfirmasi arah candle 15 menit terakhir
            candle_memantul = closes[-1] >= closes[-2]
            candle_jatuh_beruntun = (closes[-1] < closes[-2] < closes[-3])

            # Klasifikasi Status Koin, Kelayakan "siap_entry", & Bobot Anggaran
            if tren_15m_naik and tren_1h_naik and 42.0 <= rsi <= 63.0 and candle_memantul and not candle_jatuh_beruntun:
                gaya = "SNIPER"
                skor_dasar = 80.0 + min(14.0, (rasio_vol - 0.8) * 10.0) - abs(50.0 - rsi) * 0.35
                diskon_entry_pct = min(max(atr_pct * 0.30, 0.002), 0.006)
                prediksi = "🚀 BERPELUANG UNTUNG / NAIK (Tren 15M & 1H Bullish - SIAP ENTRY)"
                siap_entry = True
                faktor_bobot_status = 1.30  # Prioritas anggaran tertinggi (Momentum Breakout)
            elif tren_1h_naik and 32.0 <= rsi <= 52.0 and candle_memantul and not candle_jatuh_beruntun:
                gaya = "GRID"
                skor_dasar = 72.0 + (50.0 - rsi) * 0.45 + 3.0
                diskon_entry_pct = min(max(atr_pct * 0.50, 0.003), 0.010)
                prediksi = "🟢 POTENSI REBOUND KUAT (Pullback di Tren 1H Naik - SIAP ENTRY)"
                siap_entry = True
                faktor_bobot_status = 1.15  # Prioritas anggaran menengah-atas
            elif rsi <= 35.0 and candle_memantul and not candle_jatuh_beruntun:
                gaya = "GRID"
                skor_dasar = 67.0 + (36.0 - rsi) * 0.8
                diskon_entry_pct = min(max(atr_pct * 0.50, 0.003), 0.010)
                prediksi = "🟢 POTENSI REBOUND (Oversold mulai memantul - SIAP ENTRY)"
                siap_entry = True
                faktor_bobot_status = 1.00  # Prioritas anggaran standar
            elif tren_1h_naik and not candle_jatuh_beruntun:
                gaya = "WAIT_PULLBACK"
                skor_dasar = 58.0
                diskon_entry_pct = 0.008
                prediksi = "🟢 POTENSI REBOUND (Tren 1H naik, tunggu candle 15M hijau untuk beli baru)"
                siap_entry = False
                faktor_bobot_status = 0.0
            elif not tren_15m_naik and not tren_1h_naik and (candle_jatuh_beruntun or (rsi < 42.0 and rasio_vol >= 1.25)):
                gaya = "WAIT_DOWNTREND"
                skor_dasar = 25.0
                diskon_entry_pct = 0.015
                prediksi = "🔴 BAHAYA JATUH LEBIH DALAM (Tekanan jual 15M & 1H kuat - JANGAN BELI)"
                siap_entry = False
                faktor_bobot_status = 0.0
            else:
                gaya = "WAIT_SIDEWAYS"
                skor_dasar = 45.0
                diskon_entry_pct = 0.010
                prediksi = "🟡 SIDEWAYS WAJAR (Konsolidasi normal, aman ditahan / jangan beli dulu)"
                siap_entry = False
                faktor_bobot_status = 0.0

            conviction_score = round(max(10.0, min(98.0, skor_dasar)), 1)
            entry_ideal_idr = bulatkan_harga_indodax(coin, harga_idr * (1.0 - diskon_entry_pct))
            potensi_naik_pct = round(max(atr_pct * 3.0, 0.012), 4)

            peta_analisa[coin] = {
                "coin": coin,
                "harga_idr": harga_idr,
                "high_2jam_idr": high_2jam_idr,
                "tren": "UPTREND" if (tren_15m_naik or tren_1h_naik) else "SIDEWAYS/DOWN",
                "tren_detail": f"15M:{'UP' if tren_15m_naik else 'DOWN'}/1H:{'UP' if tren_1h_naik else 'DOWN'}",
                "rsi": round(rsi, 1),
                "atr_pct": round(atr_pct, 4),
                "rasio_vol": round(rasio_vol, 2),
                "potensi_naik_pct": potensi_naik_pct,
                "entry_ideal_idr": entry_ideal_idr,
                "gaya": gaya,
                "skor": conviction_score,
                "prediksi": prediksi,
                "siap_entry": siap_entry,
                "bobot_alokasi": round(conviction_score * faktor_bobot_status, 2)
            }
        except Exception:
            continue
    return peta_analisa

def konsultasi_keputusan_entry_gemini(kandidat, alokasi_idr):
    """Meminta validasi Gemini AI sebelum mengeksekusi pembelian koin baru."""
    if not GEMINI_API_KEY:
        return True, "Validasi kuantitatif multi-timeframe terpenuhi."
    try:
        prompt = (
            f"Evaluasi sinyal scalping Indodax: Koin {kandidat['coin']} mode {kandidat['gaya']}, "
            f"Harga Rp{kandidat['harga_idr']:,.0f}, Rencana Beli Rp{kandidat['entry_ideal_idr']:,.0f} "
            f"(Modal Rp{alokasi_idr:,.0f}), Tren {kandidat['tren_detail']}, RSI 15M: {kandidat['rsi']}, "
            f"Rasio Volume: {kandidat['rasio_vol']}x, Status: {kandidat['prediksi']}. "
            f"Apakah setup ini layak dieksekusi BELI sekarang (jawab YA) atau TUNDA (jawab TUNDA)? "
            f"Jawab singkat: YA/TUNDA - alasan maksimal 10 kata."
        )
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
        body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            hasil = json.loads(resp.read().decode())
            teks = hasil["candidates"][0]["content"]["parts"][0]["text"].strip().replace("\n", " ")
            setuju_beli = not teks.upper().startswith("TUNDA")
            return setuju_beli, teks
    except Exception:
        return True, "Lolos filter kuantitatif siap_entry."

def konsultasi_keputusan_exit_gemini(coin, mode_slot, beli_idr, skrg_idr, tp_idr, puncak_idr, rsi, tren, jenis_kasus):
    if not GEMINI_API_KEY:
        return True, "Eksekusi otomatis sesuai indikator teknikal."
    try:
        prompt = (
            f"Koin {coin} ({mode_slot}) dibeli di Rp{beli_idr:,.0f}, target TP Rp{tp_idr:,.0f}. "
            f"Riwayat harga tertinggi sempat menyentuh Rp{puncak_idr:,.0f}, sekarang di Rp{skrg_idr:,.0f} "
            f"(Tren: {tren}, RSI 15M: {rsi}). Kasus: {jenis_kasus}. "
            f"Apakah sebaiknya langsung JUAL SEKARANG (jawab YA) atau TAHAN (jawab TAHAN)? "
            f"Jawab dengan format: YA/TAHAN - alasan singkat 12 kata."
        )
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
        body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            hasil = json.loads(resp.read().decode())
            teks = hasil["candidates"][0]["content"]["parts"][0]["text"].strip().replace("\n", " ")
            setuju_jual = not teks.upper().startswith("TAHAN")
            return setuju_jual, teks
    except Exception:
        return True, "Validasi teknikal otomatis aktif."

# ==============================================================================
# BAGIAN 6: EVALUASI POSISI AKTIF, ANTREAN TP INDODAX, TP RANGE & SL RANGE
# ==============================================================================
def evaluasi_dan_kawal_posisi_dinamis(state, peta_analisa, dompet):
    slot_tetap_aktif = []
    log_aksi = []
    ada_eksekusi_penting = False
    now_ts = time.time()

    for slot in state["active_slots"]:
        coin = slot["coin"]
        info_pasar = peta_analisa.get(coin)
        harga_sekarang = info_pasar["harga_idr"] if info_pasar else slot["entry_price_idr"]
        high_2jam_idr = info_pasar["high_2jam_idr"] if info_pasar else harga_sekarang
        rsi_sekarang = info_pasar["rsi"] if info_pasar else 50.0
        tren_sekarang = info_pasar["tren"] if info_pasar else "SIDEWAYS/DOWN"

        mode_slot = slot.get("style", "GRID")
        entry_idr = float(slot["entry_price_idr"])
        tp_default_pct = TP_SNIPER_BASE_PCT if mode_slot == "SNIPER" else TP_GRID_BASE_PCT
        sl_default_pct = SL_SNIPER_BASE_PCT if mode_slot == "SNIPER" else SL_GRID_BASE_PCT

        tp_idr = float(slot.get("tp_price_idr", round(entry_idr * (1.0 + tp_default_pct), 0)))
        sl_idr = float(slot.get("sl_price_idr", round(entry_idr * (1.0 - sl_default_pct), 0)))
        slot["tp_price_idr"] = tp_idr
        slot["sl_price_idr"] = sl_idr

        koin_free = dompet["coins_free"].get(coin, 0.0)
        koin_locked = dompet["coins_locked"].get(coin, 0.0)
        total_koin_dimiliki = koin_free + koin_locked
        nilai_koin_idr = total_koin_dimiliki * harga_sekarang

        # KASUS A: WAITING_BUY
        if slot["status"] == "WAITING_BUY":
            if (dompet["terhubung"] and nilai_koin_idr >= 5000) or (not dompet["terhubung"] and harga_sekarang <= entry_idr):
                slot["status"] = "HOLDING_FOR_TP"
                slot["filled_timestamp"] = now_ts
                slot["highest_price_idr"] = max(harga_sekarang, high_2jam_idr)
                pasang_antrean_tp_di_indodax(slot, koin_free)
                ada_eksekusi_penting = True
                log_aksi.append(
                    f"✅ [TERBELI & PASANG TP INDODAX] {coin} ({mode_slot}) aktif di Rp{entry_idr:,.0f}! "
                    f"Antrean Jual TP dipasang di Rp{slot['tp_price_idr']:,.0f}."
                )
                slot_tetap_aktif.append(slot)
                continue

            umur_antre_jam = (now_ts - slot.get("timestamp", now_ts)) / 3600.0
            if umur_antre_jam <= REVIEW_ENTRY_HOURS:
                log_aksi.append(
                    f"⏳ [ANTRE BELI {umur_antre_jam:.1f}j] {coin} ({mode_slot}) di Rp{entry_idr:,.0f} (Skrg: Rp{harga_sekarang:,.0f})."
                )
                slot_tetap_aktif.append(slot)
                continue

            jarak_ke_entry_pct = (harga_sekarang - entry_idr) / entry_idr
            if jarak_ke_entry_pct <= 0.012 and rsi_sekarang <= 54 and info_pasar and info_pasar.get("siap_entry"):
                log_aksi.append(f"🔍 [PERTAHANKAN ANTREAN] {coin} dekat titik beli ({jarak_ke_entry_pct*100:.2f}%).")
                slot_tetap_aktif.append(slot)
            else:
                batalkan_order_indodax(coin, slot.get("buy_order_id"))
                ada_eksekusi_penting = True
                log_aksi.append(
                    f"🔄 [BATAL & REALOKASI] Antrean {coin} >{REVIEW_ENTRY_HOURS:.0f}j dibatalkan agar modal dialihkan ke sinyal siap_entry terbaru."
                )
            continue

        # ======================================================================
        # KASUS B: KOIN SUDAH TERBELI (HOLDING_FOR_TP)
        # ======================================================================
        if slot["status"] == "HOLDING_FOR_TP":
            # 1. Cek apakah order LIMIT SELL (TP) di Indodax sudah laku terjual otomatis
            if dompet["terhubung"] and nilai_koin_idr < 5000 and slot.get("tp_order_id"):
                kenaikan_tp_pct = (tp_idr - entry_idr) / entry_idr
                profit_bersih = round(slot["capital_idr"] * (kenaikan_tp_pct - FEE_ROUNDTRIP_MAKER_PCT), 0)
                state["realized_profit_today_idr"] += profit_bersih
                state["completed_trades_today"] += 1
                ada_eksekusi_penting = True
                log_aksi.append(
                    f"🎉 [TP INDODAX TERJUAL OTOMATIS!] {coin} ({mode_slot}) laku di Rp{tp_idr:,.0f} "
                    f"(+{kenaikan_tp_pct*100:.2f}%). Profit Bersih: +Rp{profit_bersih:,.0f}!"
                )
                continue

            puncak_tercatat = max(
                float(slot.get("highest_price_idr", harga_sekarang)),
                harga_sekarang,
                high_2jam_idr if high_2jam_idr <= tp_idr * 1.03 else harga_sekarang
            )
            slot["highest_price_idr"] = puncak_tercatat

            kenaikan_skrg_pct = (harga_sekarang - entry_idr) / entry_idr
            kenaikan_puncak_pct = (puncak_tercatat - entry_idr) / entry_idr
            target_tp_pct = max(0.008, (tp_idr - entry_idr) / entry_idr)
            pencapaian_puncak_ke_tp = kenaikan_puncak_pct / target_tp_pct

            qty_dimiliki = format_qty_koin(coin, total_koin_dimiliki if total_koin_dimiliki > 0 else slot.get("qty", 0))
            estimasi_nilai_jual_skrg = qty_dimiliki * harga_sekarang

            # 2. FITUR DETEKTOR PUNCAK TERLEWAT (MISSED-PEAK / TP RANGE DETECTOR)
            if (
                pencapaian_puncak_ke_tp >= 0.70
                and harga_sekarang < puncak_tercatat * 0.996
                and kenaikan_skrg_pct >= 0.0095
                and estimasi_nilai_jual_skrg >= MIN_LIMIT_ORDER_INDODAX_IDR
                and (tren_sekarang != "UPTREND" or rsi_sekarang < 56.0 or rsi_sekarang >= 67.0)
            ):
                setuju_jual, alasan_ai = konsultasi_keputusan_exit_gemini(
                    coin, mode_slot, entry_idr, harga_sekarang, tp_idr, puncak_tercatat, rsi_sekarang, tren_sekarang,
                    "Harga sempat menyentuh area dekat TP namun terkoreksi & momentum melambat (TP Range)"
                )
                if setuju_jual:
                    if slot.get("tp_order_id"):
                        batalkan_order_indodax(coin, slot["tp_order_id"])
                        slot["tp_order_id"] = None
                        time.sleep(2)
                    res_jual = eksekusi_order_indodax(coin, "SELL", harga_sekarang * 0.998, qty_koin=qty_dimiliki)
                    if apakah_order_sukses(res_jual):
                        profit_bersih = round(slot["capital_idr"] * (kenaikan_skrg_pct - FEE_ROUNDTRIP_MAKER_PCT), 0)
                        state["realized_profit_today_idr"] += profit_bersih
                        state["completed_trades_today"] += 1
                        ada_eksekusi_penting = True
                        log_aksi.append(
                            f"⚡ [TP RANGE DIEKSEKUSI] {coin} dijual di Rp{harga_sekarang:,.0f} "
                            f"(+{kenaikan_skrg_pct*100:.2f}%, Profit Bersih: +Rp{profit_bersih:,.0f}) | AI: {alasan_ai}"
                        )
                        continue
                    else:
                        pasang_antrean_tp_di_indodax(slot, qty_dimiliki)

            # 3. FITUR SMART SL RANGE & HARD STOP LOSS (DENGAN PROTEKSI MINIMUM ORDER Rp25.000 INDODAX)
            butuh_sl = (harga_sekarang <= sl_idr) or (kenaikan_skrg_pct <= -0.012 and tren_sekarang != "UPTREND" and rsi_sekarang < 39.0)
            if butuh_sl:
                if estimasi_nilai_jual_skrg >= MIN_LIMIT_ORDER_INDODAX_IDR:
                    label_sl = "HARD STOP LOSS" if harga_sekarang <= sl_idr else "SMART SL RANGE"
                    if slot.get("tp_order_id"):
                        batalkan_order_indodax(coin, slot["tp_order_id"])
                        slot["tp_order_id"] = None
                        time.sleep(2)
                    res_sl = eksekusi_order_indodax(coin, "SELL", harga_sekarang * 0.997, qty_koin=qty_dimiliki)
                    if apakah_order_sukses(res_sl):
                        pnl_bersih = round(slot["capital_idr"] * (kenaikan_skrg_pct - FEE_ROUNDTRIP_MAKER_PCT), 0)
                        state["realized_profit_today_idr"] += pnl_bersih
                        state["completed_trades_today"] += 1
                        ada_eksekusi_penting = True
                        log_aksi.append(
                            f"🛡️ [{label_sl}] {coin} ({mode_slot}) diamankan di Rp{harga_sekarang:,.0f} "
                            f"({kenaikan_skrg_pct*100:+.2f}%). PnL Bersih: Rp{pnl_bersih:,.0f}."
                        )
                        continue
                    else:
                        pasang_antrean_tp_di_indodax(slot, qty_dimiliki)

            # 4. Pastikan antrean LIMIT SELL (TP) terpasang di buku order Indodax
            if not slot.get("tp_order_id") and (not dompet["terhubung"] or koin_free > 0):
                pasang_antrean_tp_di_indodax(slot, koin_free)
                ada_eksekusi_penting = True

            # 5. TRAILING PROFIT LOCK OTOMATIS
            if kenaikan_skrg_pct >= 0.016:
                sl_kunci_untung = bulatkan_harga_indodax(coin, entry_idr * 1.009)
                if sl_kunci_untung > slot["sl_price_idr"]:
                    slot["sl_price_idr"] = sl_kunci_untung
                    log_aksi.append(
                        f"🔒 [TRAILING PROFIT LOCK] {coin} naik +{kenaikan_skrg_pct*100:.2f}%! SL dinaikkan ke Rp{sl_kunci_untung:,.0f}."
                    )

            status_tp_order = f"OrderTP:#{slot.get('tp_order_id')}" if slot.get("tp_order_id") else "TP-Aktif"
            log_aksi.append(
                f"🎯 [KAWAL TP {status_tp_order}] {coin} ({mode_slot}) | Skrg: Rp{harga_sekarang:,.0f} ({kenaikan_skrg_pct*100:+.2f}%) "
                f"| Puncak: Rp{puncak_tercatat:,.0f} -> TP: Rp{tp_idr:,.0f} | SL: Rp{slot['sl_price_idr']:,.0f}"
            )
            slot_tetap_aktif.append(slot)

    state["active_slots"] = slot_tetap_aktif
    return state, log_aksi, ada_eksekusi_penting

# ==============================================================================
# BAGIAN 7: ALOKASI MODAL DINAMIS (HANYA KOIN SIAP ENTRY & AMAN BATAS SL)
# ==============================================================================
def kelola_anggaran_kosong_dengan_analisa(state, peta_analisa, dompet):
    modal_aktif_state = sum(float(s.get("capital_idr", 0)) for s in state["active_slots"])
    sisa_plafon_bot = max(0.0, MAX_BOT_CAPITAL_IDR - modal_aktif_state)
    saldo_idr_tersedia = min(dompet["idr_free"], sisa_plafon_bot) if dompet["terhubung"] else sisa_plafon_bot

    slot_terisi = len(state["active_slots"])
    sisa_slot_maks = max(0, MAX_CONCURRENT_COINS - slot_terisi)

    # Wajib minimal Rp32.000 (MIN_NEW_BUY_ALLOCATION_IDR) agar saat turun terkena SL nilainya tetap >= Rp25.000
    if saldo_idr_tersedia < MIN_NEW_BUY_ALLOCATION_IDR or sisa_slot_maks <= 0:
        return state, [
            f"[MODAL AKTIF BEKERJA] Rp{modal_aktif_state:,.0f} di {slot_terisi} posisi (Sisa IDR: Rp{dompet['idr_free']:,.0f}, min beli baru Rp{MIN_NEW_BUY_ALLOCATION_IDR:,.0f})."
        ], False

    # Hitung berapa maksimal koin baru yang sanggup dibiayai dengan minimal Rp32.000 per koin
    maks_koin_terbiayai_aman = int(saldo_idr_tersedia // MIN_NEW_BUY_ALLOCATION_IDR)
    batas_ambil_kandidat = min(sisa_slot_maks, maks_koin_terbiayai_aman)

    if batas_ambil_kandidat <= 0:
        return state, [
            f"⏸️ [SALDO BELUM CUKUP AMAN UNTUK SL] Sisa IDR Rp{saldo_idr_tersedia:,.0f} < batas aman Rp{MIN_NEW_BUY_ALLOCATION_IDR:,.0f}/koin."
        ], False

    koin_sudah_ada = {s["coin"] for s in state["active_slots"]}

    # FILTER KETAT: Hanya pilih koin yang berstatus siap_entry == True dan skor >= MIN_CONVICTION_SCORE
    kandidat_siap_entry = sorted(
        [
            v for v in peta_analisa.values()
            if (
                v["coin"] not in koin_sudah_ada
                and v.get("siap_entry") is True
                and v["skor"] >= MIN_CONVICTION_SCORE
            )
        ],
        key=lambda x: x.get("bobot_alokasi", x["skor"]),
        reverse=True
    )[:batas_ambil_kandidat]

    if not kandidat_siap_entry:
        return state, [
            f"⏸️ [AI WAIT / CASH IS KING] Dana Rp{saldo_idr_tersedia:,.0f} ditahan karena belum ada koin berstatus SIAP ENTRY (Skor >= {MIN_CONVICTION_SCORE})."
        ], False

    jumlah_siap = len(kandidat_siap_entry)
    total_bobot = sum(k.get("bobot_alokasi", k["skor"]) for k in kandidat_siap_entry)
    log_alokasi = []
    ada_order_baru = False
    sisa_kas = saldo_idr_tersedia

    # Tentukan plafon anggaran sesi ini berdasarkan jumlah koin yang siap_entry & statusnya
    if jumlah_siap == 1 and sisa_slot_maks >= 2 and saldo_idr_tersedia >= (MIN_NEW_BUY_ALLOCATION_IDR * 2):
        # Jika masih ada >=2 slot kosong tapi baru 1 koin yang siap_entry, alokasikan 38%-45% plafon (minimal Rp33.000)
        # agar sisa kas tetap dicadangkan untuk koin kedua/ketiga yang menyusul siap_entry nanti
        k_tunggal = kandidat_siap_entry[0]
        rasio_status = MAX_SINGLE_COIN_CAP_PCT if k_tunggal["gaya"] == "SNIPER" else 0.38
        anggaran_sesi_ini = max(MIN_NEW_BUY_ALLOCATION_IDR + 1000.0, min(saldo_idr_tersedia, math.floor(MAX_BOT_CAPITAL_IDR * rasio_status)))
    else:
        anggaran_sesi_ini = saldo_idr_tersedia

    for idx, kandidat in enumerate(kandidat_siap_entry):
        if sisa_kas < MIN_NEW_BUY_ALLOCATION_IDR:
            break

        if idx == jumlah_siap - 1:
            alokasi_idr = math.floor(min(sisa_kas, anggaran_sesi_ini))
        else:
            porsi = kandidat.get("bobot_alokasi", kandidat["skor"]) / total_bobot
            alokasi_idr = math.floor(anggaran_sesi_ini * porsi)
            # Pastikan koin saat ini >= Rp32.000 dan tidak memakan jatah minimal Rp32.000 untuk kandidat berikutnya
            sisa_kandidat_lain = jumlah_siap - 1 - idx
            maks_boleh_pakai = sisa_kas - (sisa_kandidat_lain * MIN_NEW_BUY_ALLOCATION_IDR)
            alokasi_idr = max(int(MIN_NEW_BUY_ALLOCATION_IDR), min(int(alokasi_idr), int(maks_boleh_pakai)))

        if alokasi_idr < MIN_NEW_BUY_ALLOCATION_IDR:
            continue

        coin = kandidat["coin"]
        gaya = kandidat["gaya"]
        entry_idr = kandidat["entry_ideal_idr"]
        qty_rencana = hitung_kuantitas_koin(coin, alokasi_idr, entry_idr)
        nilai_efektif_idr = round(qty_rencana * entry_idr, 0)

        # Jika akibat pembulatan desimal (misal DOGE) nilai efektif turun di bawah Rp28.500, naikkan qty +1 step jika kas cukup
        if nilai_efektif_idr < MIN_SAFE_SL_BUFFER_IDR:
            step_qty = 10 ** (-WATCHLIST_COINS[coin]["step_decimals"])
            qty_tambah = format_qty_koin(coin, qty_rencana + step_qty)
            if (qty_tambah * entry_idr) <= sisa_kas:
                qty_rencana = qty_tambah
                nilai_efektif_idr = round(qty_rencana * entry_idr, 0)
                alokasi_idr = nilai_efektif_idr

        if nilai_efektif_idr < MIN_SAFE_SL_BUFFER_IDR:
            log_alokasi.append(
                f"⚠️ [SKIP {coin}] Nilai efektif Rp{nilai_efektif_idr:,.0f} terlalu dekat batas minimum Rp25.000 Indodax."
            )
            continue

        # Konsultasi ke Gemini AI sebelum mengeksekusi order BUY
        setuju_beli, alasan_gemini = konsultasi_keputusan_entry_gemini(kandidat, nilai_efektif_idr)
        if not setuju_beli:
            log_alokasi.append(f"⏸️ [GEMINI AI HOLD ENTRY {coin}] Setup ditunda AI: {alasan_gemini}")
            continue

        tp_pct = TP_SNIPER_BASE_PCT if gaya == "SNIPER" else TP_GRID_BASE_PCT
        sl_pct = SL_SNIPER_BASE_PCT if gaya == "SNIPER" else SL_GRID_BASE_PCT
        tp_idr = bulatkan_harga_indodax(coin, entry_idr * (1.0 + tp_pct))
# ==============================================================================
# BAGIAN 7: ALOKASI MODAL DINAMIS (HANYA KOIN SIAP ENTRY & AMAN BATAS SL)
# ==============================================================================
def kelola_anggaran_kosong_dengan_analisa(state, peta_analisa, dompet):
    modal_aktif_state = sum(float(s.get("capital_idr", 0)) for s in state["active_slots"])
    sisa_plafon_bot = max(0.0, MAX_BOT_CAPITAL_IDR - modal_aktif_state)
    saldo_idr_tersedia = min(dompet["idr_free"], sisa_plafon_bot) if dompet["terhubung"] else sisa_plafon_bot

    slot_terisi = len(state["active_slots"])
    sisa_slot_maks = max(0, MAX_CONCURRENT_COINS - slot_terisi)

    if saldo_idr_tersedia < MIN_NEW_BUY_ALLOCATION_IDR or sisa_slot_maks <= 0:
        return state, [
            f"[MODAL AKTIF BEKERJA] Rp{modal_aktif_state:,.0f} di {slot_terisi} posisi (Sisa IDR: Rp{dompet['idr_free']:,.0f}, min beli baru Rp{MIN_NEW_BUY_ALLOCATION_IDR:,.0f})."
        ], False

    maks_koin_terbiayai_aman = int(saldo_idr_tersedia // MIN_NEW_BUY_ALLOCATION_IDR)
    batas_ambil_kandidat = min(sisa_slot_maks, maks_koin_terbiayai_aman)

    if batas_ambil_kandidat <= 0:
        return state, [
            f"⏸️ [SALDO BELUM CUKUP AMAN UNTUK SL] Sisa IDR Rp{saldo_idr_tersedia:,.0f} < batas aman Rp{MIN_NEW_BUY_ALLOCATION_IDR:,.0f}/koin."
        ], False

    koin_sudah_ada = {s["coin"] for s in state["active_slots"]}

    kandidat_siap_entry = sorted(
        [
            v for v in peta_analisa.values()
            if (
                v["coin"] not in koin_sudah_ada
                and v.get("siap_entry") is True
                and v["skor"] >= MIN_CONVICTION_SCORE
            )
        ],
        key=lambda x: x.get("bobot_alokasi", x["skor"]),
        reverse=True
    )[:batas_ambil_kandidat]

    if not kandidat_siap_entry:
        return state, [
            f"⏸️ [AI WAIT / CASH IS KING] Dana Rp{saldo_idr_tersedia:,.0f} ditahan karena belum ada koin berstatus SIAP ENTRY (Skor >= {MIN_CONVICTION_SCORE})."
        ], False

    jumlah_siap = len(kandidat_siap_entry)
    total_bobot = sum(k.get("bobot_alokasi", k["skor"]) for k in kandidat_siap_entry)
    log_alokasi = []
    ada_order_baru = False
    sisa_kas = saldo_idr_tersedia

    if jumlah_siap == 1 and sisa_slot_maks >= 2 and saldo_idr_tersedia >= (MIN_NEW_BUY_ALLOCATION_IDR * 2):
        k_tunggal = kandidat_siap_entry[0]
        rasio_status = MAX_SINGLE_COIN_CAP_PCT if k_tunggal["gaya"] == "SNIPER" else 0.38
        anggaran_sesi_ini = max(MIN_NEW_BUY_ALLOCATION_IDR + 1000.0, min(saldo_idr_tersedia, math.floor(MAX_BOT_CAPITAL_IDR * rasio_status)))
    else:
        anggaran_sesi_ini = saldo_idr_tersedia

    for idx, kandidat in enumerate(kandidat_siap_entry):
        if sisa_kas < MIN_NEW_BUY_ALLOCATION_IDR:
            break

        if idx == jumlah_siap - 1:
            alokasi_idr = math.floor(min(sisa_kas, anggaran_sesi_ini))
        else:
            porsi = kandidat.get("bobot_alokasi", kandidat["skor"]) / total_bobot
            alokasi_idr = math.floor(anggaran_sesi_ini * porsi)
            sisa_kandidat_lain = jumlah_siap - 1 - idx
            maks_boleh_pakai = sisa_kas - (sisa_kandidat_lain * MIN_NEW_BUY_ALLOCATION_IDR)
            alokasi_idr = max(int(MIN_NEW_BUY_ALLOCATION_IDR), min(int(alokasi_idr), int(maks_boleh_pakai)))

        if alokasi_idr < MIN_NEW_BUY_ALLOCATION_IDR:
            continue

        coin = kandidat["coin"]
        gaya = kandidat["gaya"]
        entry_idr = kandidat["entry_ideal_idr"]
        qty_rencana = hitung_kuantitas_koin(coin, alokasi_idr, entry_idr)
        nilai_efektif_idr = round(qty_rencana * entry_idr, 0)

        if nilai_efektif_idr < MIN_SAFE_SL_BUFFER_IDR:
            step_qty = 10 ** (-WATCHLIST_COINS[coin]["step_decimals"])
            qty_tambah = format_qty_koin(coin, qty_rencana + step_qty)
            if (qty_tambah * entry_idr) <= sisa_kas:
                qty_rencana = qty_tambah
                nilai_efektif_idr = round(qty_rencana * entry_idr, 0)
                alokasi_idr = nilai_efektif_idr

        if nilai_efektif_idr < MIN_SAFE_SL_BUFFER_IDR:
            log_alokasi.append(
                f"⚠️ [SKIP {coin}] Nilai efektif Rp{nilai_efektif_idr:,.0f} terlalu dekat batas minimum Rp25.000 Indodax."
            )
            continue

        setuju_beli, alasan_gemini = konsultasi_keputusan_entry_gemini(kandidat, nilai_efektif_idr)
        if not setuju_beli:
            log_alokasi.append(f"⏸️ [GEMINI AI HOLD ENTRY {coin}] Setup ditunda AI: {alasan_gemini}")
            continue

        tp_pct = TP_SNIPER_BASE_PCT if gaya == "SNIPER" else TP_GRID_BASE_PCT
        sl_pct = SL_SNIPER_BASE_PCT if gaya == "SNIPER" else SL_GRID_BASE_PCT
        tp_idr = bulatkan_harga_indodax(coin, entry_idr * (1.0 + tp_pct))
        sl_idr = bulatkan_harga_indodax(coin, entry_idr * (1.0 - sl_pct))
        estimasi_nilai_saat_sl = round(qty_rencana * sl_idr, 0)

        res_order = eksekusi_order_indodax(coin, "BUY", entry_idr, qty_koin=qty_rencana)
        if apakah_order_sukses(res_order):
            order_id = str(res_order.get("orderId"))
            qty_koin = res_order.get("qty", qty_rencana)
            state["active_slots"].append({
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
            sisa_kas -= nilai_efektif_idr
            anggaran_sesi_ini = max(0.0, anggaran_sesi_ini - nilai_efektif_idr)
            ada_order_baru = True
            persen_plafon = (nilai_efektif_idr / MAX_BOT_CAPITAL_IDR) * 100.0
            log_alokasi.append(
                f"🚀 [ORDER BELI #{order_id} - {gaya}] {coin} (Skor:{kandidat['skor']}) | "
                f"Alokasi: Rp{nilai_efektif_idr:,.0f} ({persen_plafon:.0f}% Modal, Nilai saat SL: Rp{estimasi_nilai_saat_sl:,.0f} > Rp25rb) | "
                f"Beli: Rp{entry_idr:,.0f} -> TP: Rp{tp_idr:,.0f} | AI: {alasan_gemini}"
            )

    return state, log_alokasi, ada_order_baru

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
        entry = float(slot["entry_price_idr"])
        tp = float(slot.get("tp_price_idr", entry * 1.02))
        puncak = max(float(slot.get("highest_price_idr", skrg)), skrg, info.get("high_2jam_idr", skrg))
        nilai_skrg = float(slot.get("qty", 0)) * skrg

        if slot["status"] == "HOLDING_FOR_TP":
            pnl_pct = (skrg - entry) / entry
            target_pct = max(0.008, (tp - entry) / entry)
            rasio_puncak_ke_tp = ((puncak - entry) / entry) / target_pct

            if pnl_pct >= 0.009:
                alasan_siaga.append(f"{coin} di zona profit +{pnl_pct*100:.2f}% (kawal ketat TP Range)")
            elif rasio_puncak_ke_tp >= 0.55:
                alasan_siaga.append(f"{coin} pernah menyentuh {rasio_puncak_ke_tp*100:.0f}% target TP (kawal Missed-Peak)")
            elif pnl_pct <= -0.0090 and nilai_skrg >= MIN_LIMIT_ORDER_INDODAX_IDR:
                alasan_siaga.append(f"{coin} turun {pnl_pct*100:.2f}% mendekati SL Range (kawal penyelamatan SL)")

        elif slot["status"] == "WAITING_BUY":
            jarak_beli_pct = abs(skrg - entry) / entry
            if jarak_beli_pct <= 0.008:
                alasan_siaga.append(f"Antrean beli {coin} tinggal berjarak {jarak_beli_pct*100:.2f}% (siap pasang TP begitu terbeli)")

    return (len(alasan_siaga) > 0), alasan_siaga

def buat_kesimpulan_patroli_dinamis(state, peta_analisa):
    """Menghasilkan pesan status, daftar koin siap_entry, & prediksi teknikal per koin."""
    total_koin_pasar = len(peta_analisa)
    koin_uptrend = [k for k, v in peta_analisa.items() if v.get("tren") == "UPTREND"]
    koin_siap_beli = [f"{k}({v['gaya']}:Skor {v['skor']})" for k, v in peta_analisa.items() if v.get("siap_entry")]
    rata_rsi = (sum(v.get("rsi", 50.0) for v in peta_analisa.values()) / total_koin_pasar) if total_koin_pasar > 0 else 50.0
    kandidat_terkuat = max(peta_analisa.values(), key=lambda x: x.get("skor", 0.0)) if peta_analisa else None
    info_skor_tertinggi = f"{kandidat_terkuat['coin']} (Skor:{kandidat_terkuat['skor']})" if kandidat_terkuat else "-"
    ringkasan_pasar = (
        f"Pasar (15M+1H): {len(koin_uptrend)}/{total_koin_pasar} koin UPTREND | "
        f"Rata-rata RSI 15M: {rata_rsi:.1f} | Sinyal Tertinggi: {info_skor_tertinggi}\n"
        f"   -> Koin Berstatus SIAP ENTRY Saat Ini ({len(koin_siap_beli)} koin): {', '.join(koin_siap_beli) or 'Belum ada (menunggu konfirmasi pantulan)'}"
    )

    koin_tertahan_sl = []
    detail_diagnosa_koin = []

    for slot in state.get("active_slots", []):
        if slot.get("status") != "HOLDING_FOR_TP":
            continue
        coin = slot["coin"]
        info = peta_analisa.get(coin, {})
        skrg = info.get("harga_idr", float(slot["entry_price_idr"]))
        entry = float(slot["entry_price_idr"])
        sl_idr = float(slot.get("sl_price_idr", entry * 0.98))
        pnl_pct = (skrg - entry) / entry
        nilai_idr = float(slot.get("qty", 0)) * skrg

        rsi_k = info.get("rsi", 50.0)
        tren_k = info.get("tren_detail", info.get("tren", "-"))
        prediksi_k = info.get("prediksi", "🟡 SIDEWAYS WAJAR")

        status_sl = "Tertahan <Rp25rb" if (skrg <= sl_idr and nilai_idr < MIN_LIMIT_ORDER_INDODAX_IDR) else "Aktif"
        detail_diagnosa_koin.append(
            f"   * {coin} ({pnl_pct*100:+.2f}% | Rp{nilai_idr:,.0f} | {status_sl}) -> {prediksi_k} [Tren {tren_k}, RSI:{rsi_k}]"
        )

        if skrg <= sl_idr and nilai_idr < MIN_LIMIT_ORDER_INDODAX_IDR:
            koin_tertahan_sl.append(f"{coin} ({pnl_pct*100:+.2f}%)")

    teks_diagnosa = "\n".join(detail_diagnosa_koin) if detail_diagnosa_koin else "   * Belum ada posisi aktif."

    if koin_tertahan_sl:
        header = f"⚠️ [PATROLI SELESAI - {len(koin_tertahan_sl)} POSISI LAMA TERTAHAN ATURAN <Rp25.000 INDODAX]"
    else:
        header = "🟢 [PATROLI SELESAI - STATUS & PREDIKSI PORTOFOLIO]"

    return (
        f"{header}\n"
        f"📊 DIAGNOSA & PREDIKSI TEKNIKAL PER KOIN (TIMEFRAME SCALPING 15M + 1H):\n"
        f"{teks_diagnosa}\n"
        f"   -> {ringkasan_pasar}"
    )

# ==============================================================================
# BAGIAN 9: LAPORAN OTOMATIS KE GOOGLE SHEETS (WEBHOOK TAB 4)
# ==============================================================================
def lapor_ke_google_sheets(state, semua_log, dompet, harga_live_map=None):
    tz_wib = timezone(timedelta(hours=7))
    waktu_lokal = datetime.now(tz_wib).strftime("%Y-%m-%d %H:%M:%S")

    floating_pnl = 0.0
    if harga_live_map:
        for s in state["active_slots"]:
            if s.get("status") == "HOLDING_FOR_TP":
                harga_skrg = harga_live_map.get(s["coin"], {}).get("last", s["entry_price_idr"])
                floating_pnl += (harga_skrg - float(s["entry_price_idr"])) * float(s.get("qty", 0.0))

    ringkasan_slot = ", ".join(
        [f"{s['coin']}[{s['style']}:Rp{s['capital_idr']:,.0f}@Rp{s['entry_price_idr']:,.0f}]" for s in state["active_slots"]]
    ) or "Semua slot kosong"
    catatan_lengkap = " | ".join(semua_log)[:490]

    payload = {
        "tanggal": waktu_lokal,
        "pasangan": f"PRO KELLY AI ({len(state['active_slots'])} Posisi)",
        "modal_aktif_idr": sum(s["capital_idr"] for s in state["active_slots"]),
        "harga_acuan_idr": round(dompet.get("idr_free", 0.0), 0),
        "jumlah_grid_tereksekusi": state["completed_trades_today"],
        "profit_terealisasi_idr": state["realized_profit_today_idr"],
        "floating_pnl_idr": round(floating_pnl, 0),
        "tren_1h": ringkasan_slot,
        "rsi_14": "Scalping-15M+1H",
        "analisis_ai_gemini": catatan_lengkap
    }

    print("=== RINGKASAN EKSEKUSI PRO QUANT HYBRID BOT (INDODAX V2) ===")
    print(json.dumps(payload, indent=2))

    if GOOGLE_SHEETS_WEBHOOK_URL:
        try:
            req = urllib.request.Request(
                GOOGLE_SHEETS_WEBHOOK_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                print("Sukses kirim ke Google Sheets:", resp.read().decode())
        except Exception as e:
            print("Gagal kirim ke Google Sheets:", e)

# ==============================================================================
# BAGIAN 10: PROGRAM UTAMA (AUTO-RECOVERY + PATROLI 5M + SIAGA 30M)
# ==============================================================================
def jalankan_satu_siklus_penuh(state, kirim_sheets_selalu=True):
    dompet = ambil_saldo_lengkap_indodax()
    if LIVE_TRADING_ENABLED and not dompet.get("terhubung"):
        print("⚠️ Gagal terhubung ke API Indodax. Siklus dilewati agar state tidak rusak.")
        return state, False, [], False, {}

    harga_live_map = ambil_harga_idr_semua_koin()

    # Langkah 1: Pulihkan otomatis koin di dompet yang belum masuk daftar aktif
    state, log_recovery = sinkronkan_koin_dompet_indodax(state, dompet, harga_live_map)
    if log_recovery:
        dompet = ambil_saldo_lengkap_indodax()

    # Langkah 2: Analisa teknikal (15M + 1H) & kawal semua posisi aktif
    peta_analisa_pasar = analisa_teknikal_lengkap_pasar(harga_live_map)
    state, log_kawal, ada_aksi_kawal = evaluasi_dan_kawal_posisi_dinamis(state, peta_analisa_pasar, dompet)
    state, log_alokasi, ada_aksi_beli = kelola_anggaran_kosong_dengan_analisa(state, peta_analisa_pasar, dompet)
    simpan_state_bot(state)

    butuh_siaga, alasan_siaga = cek_apakah_butuh_pengawasan_intensif(state, peta_analisa_pasar)
    if butuh_siaga:
        info_siaga = f"🔥 [MODE SIAGA {ACTIVE_WATCH_MINUTES}M AKTIF: {'; '.join(alasan_siaga)}]"
        semua_log = log_recovery + [info_siaga] + log_kawal + log_alokasi
    else:
        semua_log = log_recovery + log_kawal + log_alokasi

    ada_perubahan = bool(log_recovery) or ada_aksi_kawal or ada_aksi_beli
    if kirim_sheets_selalu or ada_perubahan:
        lapor_ke_google_sheets(state, semua_log, dompet, harga_live_map)

    return state, butuh_siaga, alasan_siaga, ada_perubahan, peta_analisa_pasar

if __name__ == "__main__":
    waktu_mulai = time.time()
    batas_waktu_siaga = waktu_mulai + (ACTIVE_WATCH_MINUTES * 60)

    state = muat_state_bot()
    state, butuh_siaga, alasan_siaga, _, peta_analisa_terakhir = jalankan_satu_siklus_penuh(
        state, kirim_sheets_selalu=True
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
                state, kirim_sheets_selalu=False
            )
            if ada_eksekusi:
                print("✅ [EKSEKUSI REAL-TIME BERHASIL] State & Google Sheets telah diperbarui!")
            if not masih_butuh_siaga:
                print("\n" + buat_kesimpulan_patroli_dinamis(state, peta_analisa_terakhir))
                break
    else:
        print("\n" + buat_kesimpulan_patroli_dinamis(state, peta_analisa_terakhir))
