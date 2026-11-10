# ==============================================================================
# PRO QUANT HYBRID AI TRADING BOT 24/7 (INDODAX TRADE API V2 + GEMINI AI)
# ==============================================================================
# Fitur Unggulan Versi Dynamic Active-Watch (Mode Siaga Otomatis 30 Menit):
# 1. KONEKSI PENUH INDODAX TRADE API V2 (https://api.indodax.com + HMAC-SHA256)
# 2. ANTREAN TP OTOMATIS DI BUKU ORDER INDODAX (Resting LIMIT SELL):
#    Begitu koin terbeli (HOLDING_FOR_TP), bot langsung memasang order LIMIT SELL
#    di harga TP ke Indodax sehingga muncul di menu Open Orders Indodax 24/7.
# 3. DETEKTOR PUNCAK TERLEWAT (MISSED-PEAK TP RANGE) & SMART SL RANGE:
#    - Jika harga sempat menyentuh >= 70% target TP (termasuk dari riwayat High 2 Jam
#      saat cron delay) lalu turun namun masih untung bersih (>= +1.0%) & tren melemah,
#      bot otomatis membatalkan antrean TP lama dan langsung menjual di harga pasar!
#    - Jika harga turun ke zona waspada SL Range (-1.2% s/d -2.0%) dan tren patah,
#      bot membatalkan antrean TP lama dan langsung memotong kerugian lebih awal.
# 4. DYNAMIC TWO-SPEED ENGINE (PATROLI 5 MENIT + MODE SIAGA AKTIF 30 MENIT):
#    - Saat pasar tenang, bot mengecek 1x (~12 detik) lalu selesai.
#    - Saat terdeteksi sinyal kritis (koin mendekati TP >= +0.9%, riwayat puncak >= 55% TP,
#      mendekati SL <= -0.95%, atau antrean beli tinggal <= 0.8%), bot OTOMATIS tetap hidup
#      mengawasi pasar selama 30 menit penuh (cek harga tiap 60 detik) di dalam 1 sesi run!
# ==============================================================================

import os
import time
import math
import hmac
import hashlib
import urllib.parse
import urllib.request
import json
from datetime import datetime

# ==============================================================================
# BAGIAN 1: KONFIGURASI UTAMA, BIAYA INDODAX & PARAMETER MODE SIAGA DINAMIS
# ==============================================================================
MAX_BOT_CAPITAL_IDR = float(os.getenv("MAX_BOT_CAPITAL_IDR", "100000"))
MIN_ORDER_IDR_INDODAX = 11000.0     # Batas aman minimum order Indodax (https://help.indodax.com/hc/id/articles/4416667599897)
FEE_ROUNDTRIP_MAKER_PCT = 0.0055    # Estimasi total biaya beli+jual+PPN+CFX Indodax ~0.55%

MIN_CONVICTION_SCORE = 62.0         # Skor kelayakan minimal agar AI mengizinkan beli (0 - 100)
MAX_CONCURRENT_COINS = 4            # Maksimal diversifikasi 4 koin berbeda

TP_GRID_BASE_PCT = 0.020            # +2.0% Target dasar mode Grid (Mean-Reversion)
SL_GRID_BASE_PCT = 0.020            # -2.0% Batas Hard SL mode Grid
TP_SNIPER_BASE_PCT = 0.036          # +3.6% Target dasar mode Sniper (Momentum Breakout)
SL_SNIPER_BASE_PCT = 0.018          # -1.8% Batas Hard SL mode Sniper

# Parameter Mode Pengawasan Intensif Dinamis (Dynamic In-Run Active Watch)
ACTIVE_WATCH_MINUTES = int(os.getenv("ACTIVE_WATCH_MINUTES", "30"))     # Aktif mengawasi 30 menit saat ada sinyal kritis
WATCH_INTERVAL_SECONDS = int(os.getenv("WATCH_INTERVAL_SECONDS", "60")) # Cek harga live setiap 60 detik selama mode siaga
FORCE_CONTINUOUS_WATCH = os.getenv("FORCE_CONTINUOUS_WATCH", "false").lower() == "true"

REVIEW_ENTRY_HOURS = 4.0            # Evaluasi ulang antrean Limit Buy setelah 4 jam
PRE_TIMESTOP_HOURS = 40.0           # Evaluasi target realistis setelah 40 jam

WATCHLIST_COINS = {
    "SOL":  {"v2_symbol": "SOLIDR",  "indodax_key": "sol_idr",  "kraken_pair": "SOLUSD",   "step_decimals": 4, "price_step": 1},
    "BTC":  {"v2_symbol": "BTCIDR",  "indodax_key": "btc_idr",  "kraken_pair": "XXBTZUSD", "step_decimals": 6, "price_step": 1000},
    "ETH":  {"v2_symbol": "ETHIDR",  "indodax_key": "eth_idr",  "kraken_pair": "XETHZUSD", "step_decimals": 5, "price_step": 1000},
    "XRP":  {"v2_symbol": "XRPIDR",  "indodax_key": "xrp_idr",  "kraken_pair": "XXRPZUSD", "step_decimals": 2, "price_step": 1},
    "ADA":  {"v2_symbol": "ADAIDR",  "indodax_key": "ada_idr",  "kraken_pair": "ADAUSD",   "step_decimals": 2, "price_step": 1},
    "SUI":  {"v2_symbol": "SUIIDR",  "indodax_key": "sui_idr",  "kraken_pair": "SUIUSD",   "step_decimals": 2, "price_step": 1},
    "DOGE": {"v2_symbol": "DOGEIDR", "indodax_key": "doge_idr", "kraken_pair": "XDGUSD",   "step_decimals": 0, "price_step": 1}
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

def eksekusi_order_indodax(coin, side_str, harga_idr, nominal_idr=0.0, qty_koin=0.0):
    harga_bulat = bulatkan_harga_indodax(coin, harga_idr)
    qty = format_qty_koin(coin, qty_koin) if qty_koin > 0 else hitung_kuantitas_koin(coin, nominal_idr, harga_bulat)
    if not LIVE_TRADING_ENABLED:
        return {"simulasi": True, "orderId": f"SIM-{int(time.time())}", "qty": qty}

    symbol = WATCHLIST_COINS[coin]["v2_symbol"]
    params = {
        "symbol": symbol,
        "side": side_str.upper(),
        "type": "LIMIT",
        "timeInForce": "GTC",
        "price": str(harga_bulat),
        "quantity": str(qty)
    }
    res = panggil_indodax_v2("/api/v2/order", method="POST", params=params)
    print(f"👉 [INDODAX V2 {side_str.upper()}] {symbol} | Qty={qty} @ Rp{harga_bulat:,.0f} -> {res}")
    if isinstance(res, dict):
        res["qty"] = qty
    return res

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

    res_tp = eksekusi_order_indodax(coin, "SELL", tp_idr, qty_koin=qty_jual)
    if isinstance(res_tp, dict) and ("orderId" in res_tp or res_tp.get("simulasi")):
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
# BAGIAN 4: ANALISIS KUANTITATIF, RIWAYAT HIGH 2 JAM & CONVICTION SCORE AI
# ==============================================================================
def analisa_teknikal_lengkap_pasar(harga_idr_map):
    peta_analisa = {}
    for coin, info in WATCHLIST_COINS.items():
        data_ticker = harga_idr_map.get(coin)
        if not data_ticker or data_ticker["last"] <= 0:
            continue
        harga_idr = data_ticker["last"]
        try:
            url = f"https://api.kraken.com/0/public/OHLC?pair={info['kraken_pair']}&interval=60"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                res = json.loads(resp.read().decode())
            result_key = [k for k in res["result"].keys() if k != "last"][0]
            raw = res["result"][result_key][-60:]
            closes = [float(r[4]) for r in raw]
            highs = [float(r[2]) for r in raw]
            lows = [float(r[3]) for r in raw]
            vols = [float(r[6]) for r in raw]

            ema20 = sum(closes[-20:]) / 20.0
            ema50 = sum(closes[-50:]) / 50.0
            gains, losses = [], []
            for i in range(-14, 0):
                diff = closes[i] - closes[i - 1]
                gains.append(max(diff, 0))
                losses.append(max(-diff, 0))
            rsi = 100 - (100 / (1 + (sum(gains) / 14.0) / ((sum(losses) / 14.0) or 0.0001)))
            tr_list = [highs[i] - lows[i] for i in range(-14, 0)]
            atr_pct = (sum(tr_list) / 14.0) / closes[-1]

            # Estimasi puncak harga dalam 2-3 jam terakhir (mendeteksi jika puncak terlewat saat jeda cron)
            rasio_high_2jam = max(highs[-3:]) / closes[-1] if closes[-1] > 0 else 1.0
            high_2jam_idr = round(harga_idr * max(1.0, rasio_high_2jam), 0)

            vol_rata = sum(vols[-20:-1]) / 19.0 if len(vols) >= 20 else (vols[-1] or 1.0)
            rasio_vol = vols[-1] / (vol_rata or 1.0)

            # Perhitungan Conviction Score & Mode (SNIPER vs GRID)
            if ema20 > ema50 and 38 <= rsi <= 60:
                gaya = "SNIPER"
                skor_dasar = 76.0 + min(14.0, (rasio_vol - 0.8) * 10.0) - abs(48.0 - rsi) * 0.4
                diskon_entry_pct = min(max(atr_pct * 0.25, 0.002), 0.008)
            elif 30 <= rsi <= 58:
                gaya = "GRID"
                skor_dasar = 66.0 + (50.0 - rsi) * 0.45
                diskon_entry_pct = min(max(atr_pct * 0.45, 0.004), 0.015)
            else:
                gaya = "WAIT_NO_SETUP"
                skor_dasar = 35.0
                diskon_entry_pct = 0.01

            conviction_score = round(max(10.0, min(98.0, skor_dasar)), 1)
            entry_ideal_idr = bulatkan_harga_indodax(coin, harga_idr * (1.0 - diskon_entry_pct))
            potensi_naik_pct = round(max(atr_pct * 2.2, 0.012), 4)

            peta_analisa[coin] = {
                "coin": coin,
                "harga_idr": harga_idr,
                "high_2jam_idr": high_2jam_idr,
                "tren": "UPTREND" if ema20 > ema50 else "SIDEWAYS/DOWN",
                "rsi": round(rsi, 1),
                "atr_pct": round(atr_pct, 4),
                "rasio_vol": round(rasio_vol, 2),
                "potensi_naik_pct": potensi_naik_pct,
                "entry_ideal_idr": entry_ideal_idr,
                "gaya": gaya,
                "skor": conviction_score
            }
        except Exception:
            continue
    return peta_analisa

def konsultasi_keputusan_exit_gemini(coin, mode_slot, beli_idr, skrg_idr, tp_idr, puncak_idr, rsi, tren, jenis_kasus):
    """Meminta pertimbangan Gemini AI saat koin berada di zona Missed-Peak TP Range atau SL Range."""
    if not GEMINI_API_KEY:
        return True, "Eksekusi otomatis sesuai indikator teknikal."
    try:
        prompt = (
            f"Koin {coin} ({mode_slot}) dibeli di Rp{beli_idr:,.0f}, target TP Rp{tp_idr:,.0f}. "
            f"Riwayat harga tertinggi sempat menyentuh Rp{puncak_idr:,.0f}, sekarang di Rp{skrg_idr:,.0f} "
            f"(Tren 1H: {tren}, RSI: {rsi}). Kasus: {jenis_kasus}. "
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
# BAGIAN 5: EVALUASI POSISI AKTIF, ANTREAN TP INDODAX, TP RANGE & SL RANGE
# ==============================================================================
def evaluasi_dan_kawal_posisi_dinamis(state, peta_analisa, dompet):
    slot_tetap_aktif = []
    log_aksi = []
    ada_eksekusi_penting = False
    now_ts = time.time()

    semua_kandidat = sorted(peta_analisa.values(), key=lambda x: x["skor"], reverse=True)
    koin_terbaik_pasar = semua_kandidat[0] if semua_kandidat else None

    for slot in state["active_slots"]:
        coin = slot["coin"]
        info_pasar = peta_analisa.get(coin)
        harga_sekarang = info_pasar["harga_idr"] if info_pasar else slot["entry_price_idr"]
        high_2jam_idr = info_pasar["high_2jam_idr"] if info_pasar else harga_sekarang
        rsi_sekarang = info_pasar["rsi"] if info_pasar else 50.0
        tren_sekarang = info_pasar["tren"] if info_pasar else "SIDEWAYS/DOWN"
        skor_koin_ini = info_pasar["skor"] if info_pasar else 50.0

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

        # Sinkronisasi status WAITING_BUY -> HOLDING_FOR_TP jika koin sudah ada di dompet Indodax
        if slot["status"] == "WAITING_BUY":
            if (dompet["terhubung"] and nilai_koin_idr >= 5000) or (not dompet["terhubung"] and harga_sekarang <= entry_idr):
                slot["status"] = "HOLDING_FOR_TP"
                slot["filled_timestamp"] = now_ts
                slot["highest_price_idr"] = max(harga_sekarang, high_2jam_idr)
                pasang_antrean_tp_di_indodax(slot, koin_free)
                ada_eksekusi_penting = True
                log_aksi.append(
                    f"✅ [TERBELI & PASANG TP INDODAX] {coin} ({mode_slot}) aktif di Rp{entry_idr:,.0f}! "
                    f"Antrean Jual TP otomatis dipasang di Rp{slot['tp_price_idr']:,.0f}."
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

            # Evaluasi antrean > 4 Jam
            jarak_ke_entry_pct = (harga_sekarang - entry_idr) / entry_idr
            if jarak_ke_entry_pct <= 0.012 and rsi_sekarang <= 54:
                log_aksi.append(f"🔍 [PERTAHANKAN ANTREAN] {coin} dekat titik beli ({jarak_ke_entry_pct*100:.2f}%).")
                slot_tetap_aktif.append(slot)
            else:
                batalkan_order_indodax(coin, slot.get("buy_order_id"))
                ada_eksekusi_penting = True
                log_aksi.append(
                    f"🔄 [BATAL & REALOKASI] Antrean {coin} >{REVIEW_ENTRY_HOURS:.0f}j dibatalkan agar modal dialihkan ke sinyal terbaru."
                )
            continue

        # ======================================================================
        # KASUS B: KOIN SUDAH TERBELI (HOLDING_FOR_TP)
        # ======================================================================
        if slot["status"] == "HOLDING_FOR_TP":
            # 1. Cek apakah order LIMIT SELL (TP) di Indodax sudah laku terjual otomatis!
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

            # 2. Jika belum punya antrean LIMIT SELL (TP) di Indodax, langsung pasangkan sekarang!
            if not slot.get("tp_order_id") and (not dompet["terhubung"] or koin_free > 0):
                pasang_antrean_tp_di_indodax(slot, koin_free)
                ada_eksekusi_penting = True

            # Perbarui rekor harga tertinggi (gabungan memori bot + riwayat High 2 jam terakhir)
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

            # 3. FITUR DETEKTOR PUNCAK TERLEWAT (MISSED-PEAK / TP RANGE DETECTOR)
            # Jika harga pernah mencapai >= 70% dari target TP (atau >= +1.4%), lalu turun dari puncak,
            # masih berada di zona untung >= +0.95% (untung bersih setelah fee), dan momentum melemah:
            if (
                pencapaian_puncak_ke_tp >= 0.70
                and harga_sekarang < puncak_tercatat * 0.996
                and kenaikan_skrg_pct >= 0.0095
                and (tren_sekarang != "UPTREND" or rsi_sekarang < 56.0 or rsi_sekarang >= 67.0)
            ):
                setuju_jual, alasan_ai = konsultasi_keputusan_exit_gemini(
                    coin, mode_slot, entry_idr, harga_sekarang, tp_idr, puncak_tercatat, rsi_sekarang, tren_sekarang,
                    "Harga sempat menyentuh area dekat TP namun terkoreksi & momentum melambat (TP Range)"
                )
                if setuju_jual:
                    if slot.get("tp_order_id"):
                        batalkan_order_indodax(coin, slot["tp_order_id"])
                        time.sleep(1)
                    qty_eksekusi = koin_free if (dompet["terhubung"] and koin_free > 0) else slot.get("qty", 0)
                    eksekusi_order_indodax(coin, "SELL", harga_sekarang * 0.998, qty_koin=qty_eksekusi)
                    profit_bersih = round(slot["capital_idr"] * (kenaikan_skrg_pct - FEE_ROUNDTRIP_MAKER_PCT), 0)
                    state["realized_profit_today_idr"] += profit_bersih
                    state["completed_trades_today"] += 1
                    ada_eksekusi_penting = True
                    log_aksi.append(
                        f"⚡ [TP RANGE / PUNCAK TERLEWAT DIEKSEKUSI] {coin} pernah menyentuh Rp{puncak_tercatat:,.0f} "
                        f"({pencapaian_puncak_ke_tp*100:.0f}% menuju TP) & melemah. Dijual di Rp{harga_sekarang:,.0f} "
                        f"(+{kenaikan_skrg_pct*100:.2f}%, Profit Bersih: +Rp{profit_bersih:,.0f}) | AI: {alasan_ai}"
                    )
                    continue

            # 4. FITUR SMART SL RANGE (-1.2% s/d -2.0%) & HARD STOP LOSS (<= sl_idr)
            if harga_sekarang <= sl_idr or (kenaikan_skrg_pct <= -0.012 and tren_sekarang != "UPTREND" and rsi_sekarang < 39.0):
                label_sl = "HARD STOP LOSS" if harga_sekarang <= sl_idr else "SMART SL RANGE (-1.2% PATAH TREN)"
                if slot.get("tp_order_id"):
                    batalkan_order_indodax(coin, slot["tp_order_id"])
                    time.sleep(1)
                qty_eksekusi = koin_free if (dompet["terhubung"] and koin_free > 0) else slot.get("qty", 0)
                eksekusi_order_indodax(coin, "SELL", harga_sekarang * 0.997, qty_koin=qty_eksekusi)
                pnl_bersih = round(slot["capital_idr"] * (kenaikan_skrg_pct - FEE_ROUNDTRIP_MAKER_PCT), 0)
                state["realized_profit_today_idr"] += pnl_bersih
                state["completed_trades_today"] += 1
                ada_eksekusi_penting = True
                log_aksi.append(
                    f"🛡️ [{label_sl}] {coin} ({mode_slot}) diamankan di Rp{harga_sekarang:,.0f} "
                    f"({kenaikan_skrg_pct*100:+.2f}%). PnL Bersih: Rp{pnl_bersih:,.0f}."
                )
                continue

            # 5. TRAILING PROFIT LOCK OTOMATIS
            if kenaikan_skrg_pct >= 0.016:
                sl_kunci_untung = bulatkan_harga_indodax(coin, entry_idr * 1.009)
                if sl_kunci_untung > slot["sl_price_idr"]:
                    slot["sl_price_idr"] = sl_kunci_untung
                    log_aksi.append(
                        f"🔒 [TRAILING PROFIT LOCK] {coin} naik +{kenaikan_skrg_pct*100:.2f}%! SL dinaikkan ke Rp{sl_kunci_untung:,.0f} (kunci untung bersih)."
                    )

            status_tp_order = f"OrderTP:#{slot.get('tp_order_id')}" if slot.get("tp_order_id") else "TP-Siap"
            log_aksi.append(
                f"🎯 [KAWAL TP {status_tp_order}] {coin} ({mode_slot}) | Skrg: Rp{harga_sekarang:,.0f} ({kenaikan_skrg_pct*100:+.2f}%) "
                f"| Puncak: Rp{puncak_tercatat:,.0f} -> TP: Rp{tp_idr:,.0f} | SL: Rp{slot['sl_price_idr']:,.0f}"
            )
            slot_tetap_aktif.append(slot)

    state["active_slots"] = slot_tetap_aktif
    return state, log_aksi, ada_eksekusi_penting

# ==============================================================================
# BAGIAN 6: ALOKASI MODAL DINAMIS (KELLY CRITERION & CONVICTION SCORE)
# ==============================================================================
def kelola_anggaran_kosong_dengan_analisa(state, peta_analisa, dompet):
    modal_aktif_state = sum(float(s.get("capital_idr", 0)) for s in state["active_slots"])
    sisa_plafon_bot = max(0.0, MAX_BOT_CAPITAL_IDR - modal_aktif_state)
    saldo_idr_tersedia = min(dompet["idr_free"], sisa_plafon_bot) if dompet["terhubung"] else sisa_plafon_bot

    slot_terisi = len(state["active_slots"])
    sisa_slot_maks = max(0, MAX_CONCURRENT_COINS - slot_terisi)

    if saldo_idr_tersedia < MIN_ORDER_IDR_INDODAX or sisa_slot_maks <= 0:
        return state, [
            f"[MODAL AKTIF BEKERJA] Rp{modal_aktif_state:,.0f} di {slot_terisi} koin berbeda (Sisa IDR bebas: Rp{dompet['idr_free']:,.0f})."
        ], False

    koin_sudah_ada = {s["coin"] for s in state["active_slots"]}
    kandidat_layak = sorted(
        [
            v for v in peta_analisa.values()
            if v["coin"] not in koin_sudah_ada and v["gaya"] != "WAIT_NO_SETUP" and v["skor"] >= MIN_CONVICTION_SCORE
        ],
        key=lambda x: x["skor"],
        reverse=True
    )[:sisa_slot_maks]

    if not kandidat_layak:
        return state, [
            f"⏸️ [AI WAIT / CASH IS KING] Saldo Rp{saldo_idr_tersedia:,.0f} ditahan karena belum ada koin dengan Conviction Score >= {MIN_CONVICTION_SCORE}."
        ], False

    total_skor = sum(k["skor"] for k in kandidat_layak)
    log_alokasi = []
    ada_order_baru = False
    sisa_kas = saldo_idr_tersedia

    for idx, kandidat in enumerate(kandidat_layak):
        if sisa_kas < MIN_ORDER_IDR_INDODAX:
            break
        if idx == len(kandidat_layak) - 1:
            alokasi_idr = math.floor(sisa_kas)
        else:
            porsi = kandidat["skor"] / total_skor
            alokasi_idr = max(MIN_ORDER_IDR_INDODAX, min(sisa_kas, math.floor(saldo_idr_tersedia * porsi)))

        if alokasi_idr < MIN_ORDER_IDR_INDODAX:
            continue

        coin = kandidat["coin"]
        gaya = kandidat["gaya"]
        entry_idr = kandidat["entry_ideal_idr"]
        tp_pct = TP_SNIPER_BASE_PCT if gaya == "SNIPER" else TP_GRID_BASE_PCT
        sl_pct = SL_SNIPER_BASE_PCT if gaya == "SNIPER" else SL_GRID_BASE_PCT
        tp_idr = bulatkan_harga_indodax(coin, entry_idr * (1.0 + tp_pct))
        sl_idr = bulatkan_harga_indodax(coin, entry_idr * (1.0 - sl_pct))

        res_order = eksekusi_order_indodax(coin, "BUY", entry_idr, nominal_idr=alokasi_idr)
        if isinstance(res_order, dict) and ("orderId" in res_order or res_order.get("simulasi")):
            order_id = str(res_order.get("orderId"))
            qty_koin = res_order.get("qty", hitung_kuantitas_koin(coin, alokasi_idr, entry_idr))
            state["active_slots"].append({
                "coin": coin,
                "style": gaya,
                "status": "WAITING_BUY",
                "capital_idr": alokasi_idr,
                "qty": qty_koin,
                "entry_price_idr": entry_idr,
                "tp_price_idr": tp_idr,
                "sl_price_idr": sl_idr,
                "highest_price_idr": entry_idr,
                "rsi_at_entry": kandidat["rsi"],
                "buy_order_id": order_id,
                "timestamp": time.time()
            })
            sisa_kas -= alokasi_idr
            ada_order_baru = True
            log_alokasi.append(
                f"🚀 [INDODAX ORDER #{order_id} - {gaya}] {coin} (Skor {kandidat['skor']}) | "
                f"Modal: Rp{alokasi_idr:,.0f} (Qty:{qty_koin}) | Beli: Rp{entry_idr:,.0f} -> TP: Rp{tp_idr:,.0f}"
            )

    return state, log_alokasi, ada_order_baru

# ==============================================================================
# BAGIAN 7: DETEKTOR SINYAL SIAGA DINAMIS (APAKAH PERLU AKTIF 30 MENIT?)
# ==============================================================================
def cek_apakah_butuh_pengawasan_intensif(state, peta_analisa):
    """
    Memeriksa apakah ada koin yang sedang berada di Zona Panas/Kritis sehingga bot
    harus tetap terjaga selama 30 menit (mengecek harga tiap 60 detik):
    1. Posisi HOLDING_FOR_TP sudah naik >= +0.90% atau riwayat puncak >= 55% menuju TP.
    2. Posisi HOLDING_FOR_TP sedang turun mendekati zona SL Range (<= -0.95%).
    3. Posisi WAITING_BUY sudah sangat dekat dengan harga pasar (jarak <= 0.80%).
    """
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

        if slot["status"] == "HOLDING_FOR_TP":
            pnl_pct = (skrg - entry) / entry
            target_pct = max(0.008, (tp - entry) / entry)
            rasio_puncak_ke_tp = ((puncak - entry) / entry) / target_pct

            if pnl_pct >= 0.009:
                alasan_siaga.append(f"{coin} di zona profit +{pnl_pct*100:.2f}% (kawal ketat TP Range)")
            elif rasio_puncak_ke_tp >= 0.55:
                alasan_siaga.append(f"{coin} pernah menyentuh {rasio_puncak_ke_tp*100:.0f}% target TP (kawal Missed-Peak)")
            elif pnl_pct <= -0.0095:
                alasan_siaga.append(f"{coin} turun {pnl_pct*100:.2f}% mendekati SL Range (kawal penyelamatan SL)")

        elif slot["status"] == "WAITING_BUY":
            jarak_beli_pct = abs(skrg - entry) / entry
            if jarak_beli_pct <= 0.008:
                alasan_siaga.append(f"Antrean beli {coin} tinggal berjarak {jarak_beli_pct*100:.2f}% (siap pasang TP begitu terbeli)")

    return (len(alasan_siaga) > 0), alasan_siaga

# ==============================================================================
# BAGIAN 8: LAPORAN OTOMATIS KE GOOGLE SHEETS (WEBHOOK TAB 4)
# ==============================================================================
def lapor_ke_google_sheets(state, semua_log, dompet):
    ringkasan_slot = ", ".join(
        [f"{s['coin']}[{s['style']}:Rp{s['capital_idr']:,.0f}@Rp{s['entry_price_idr']:,.0f}]" for s in state["active_slots"]]
    ) or "Semua slot kosong"
    catatan_lengkap = " | ".join(semua_log)[:490]

    payload = {
        "tanggal": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pasangan": f"PRO KELLY AI ({len(state['active_slots'])} Posisi)",
        "modal_aktif_idr": sum(s["capital_idr"] for s in state["active_slots"]),
        "harga_acuan_idr": round(dompet.get("idr_free", 0.0), 0),
        "jumlah_grid_tereksekusi": state["completed_trades_today"],
        "profit_terealisasi_idr": state["realized_profit_today_idr"],
        "floating_pnl_idr": 0,
        "tren_1h": ringkasan_slot,
        "rsi_14": "Dynamic-Watch-AI",
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
# BAGIAN 9: PROGRAM UTAMA (MODE PATROLI 5 MENIT + MODE SIAGA 30 MENIT OTOMATIS)
# ==============================================================================
def jalankan_satu_siklus_penuh(state, kirim_sheets_selalu=True):
    dompet = ambil_saldo_lengkap_indodax()
    harga_live_map = ambil_harga_idr_semua_koin()
    peta_analisa_pasar = analisa_teknikal_lengkap_pasar(harga_live_map)

    state, log_kawal, ada_aksi_kawal = evaluasi_dan_kawal_posisi_dinamis(state, peta_analisa_pasar, dompet)
    state, log_alokasi, ada_aksi_beli = kelola_anggaran_kosong_dengan_analisa(state, peta_analisa_pasar, dompet)
    simpan_state_bot(state)

    butuh_siaga, alasan_siaga = cek_apakah_butuh_pengawasan_intensif(state, peta_analisa_pasar)
    if butuh_siaga:
        info_siaga = f"🔥 [MODE SIAGA {ACTIVE_WATCH_MINUTES}M AKTIF: {'; '.join(alasan_siaga)}]"
        semua_log = [info_siaga] + log_kawal + log_alokasi
    else:
        semua_log = log_kawal + log_alokasi

    if kirim_sheets_selalu or ada_aksi_kawal or ada_aksi_beli:
        lapor_ke_google_sheets(state, semua_log, dompet)

    return state, butuh_siaga, alasan_siaga, (ada_aksi_kawal or ada_aksi_beli)

if __name__ == "__main__":
    waktu_mulai = time.time()
    batas_waktu_siaga = waktu_mulai + (ACTIVE_WATCH_MINUTES * 60)

    state = muat_state_bot()
    state, butuh_siaga, alasan_siaga, _ = jalankan_satu_siklus_penuh(state, kirim_sheets_selalu=True)

    # Jika terdeteksi sinyal kritis (mendekati TP Range / SL Range / Entry), aktifkan pengawasan 30 menit!
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

            # Cek pasar lagi; kirim ke Google Sheets hanya jika ada eksekusi jual/beli penting agar tidak spam baris
            state, masih_butuh_siaga, alasan_baru, ada_eksekusi = jalankan_satu_siklus_penuh(
                state, kirim_sheets_selalu=False
            )
            if ada_eksekusi:
                print("✅ [EKSEKUSI REAL-TIME BERHASIL] State & Google Sheets telah diperbarui!")
            if not masih_butuh_siaga:
                print("🟢 [KONDISI KEMBALI TENANG] Semua posisi sudah aman/tereksekusi. Mengakhiri mode siaga lebih awal.")
                break
    else:
        print("\n🟢 [MODE PATROLI CEPAT SELESAI] Pasar masih berada di zona tenang & TP sudah terpasang di Indodax.")
