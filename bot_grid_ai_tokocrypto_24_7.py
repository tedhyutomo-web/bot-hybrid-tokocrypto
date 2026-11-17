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
RECOVERY_SCORE_BOOST = 1.0             # Tambahan syarat skor (+1.0 -> 66.0) agar Early 5M (Skor 67+) tetap lancar masuk!
MAX_CONCURRENT_COINS = 3               # Maksimal 3 koin bersamaan (dengan modal Rp100rb -> ~Rp32rb-Rp35rb/koin)
MAX_SPREAD_INDODAX_PCT = 0.0035        # Maksimal toleransi Bid-Ask Spread Indodax (0.35%) untuk scalping
DAILY_LOSS_LIMIT_PCT = -0.025          # Batas rugi harian (-2.5% modal) untuk menyalakan Circuit Breaker
SL_COOLDOWN_MINUTES = 45               # Masa tenang 45 menit untuk koin yang baru terkena SL (Anti-Whipsaw)

# Parameter Target TP & SL Dinamis (Menyesuaikan Volatilitas ATR Rupiah Indodax)
TP_EARLY_EMAS_PCT = 0.0110             # +1.10% Target TP realistis khusus Lapis 2 (Early Entry Emas 5M)
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
TIME_STOP_HOURS = 1.0                  # Jika posisi ditahan >= 1.0 jam & profit >= +0.62% di pasar sepi, cairkan profit
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

MEMORY_RETENTION_HOURS = 72.0          # Durasi simpan memori pengalaman: 72 Jam (3 Hari)
MAX_EPISODIC_MEMORY_ITEMS = 60         # Maksimal menyimpan 60 transaksi selesai terakhir (Menang & Kalah)

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
            state.setdefault("trade_experience_memory", [])
            return state
        except Exception:
            pass
    return {
        "active_slots": [],
        "realized_profit_today_idr": 0.0,
        "completed_trades_today": 0,
        "loss_to_recover_idr": 0.0,
        "sl_cooldown_until": {},
        "trade_experience_memory": [],
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

def rekam_pengalaman_transaksi_bot(state, slot, pnl_bersih_idr, pnl_exit_pct):
    """
    Merekam seluruh pengalaman transaksi selesai (baik MENANG TP maupun KALAH SL, serta hasil keputusan TAHAN SL)
    selama 72 jam terakhir (MEMORY_RETENTION_HOURS) agar Gemini AI memiliki statistik Win-Rate pola yang seimbang.
    """
    now_ts = time.time()
    batas_kadaluarsa = now_ts - (MEMORY_RETENTION_HOURS * 3600.0)
    memori_lama = state.get("trade_experience_memory", [])
    memori_aktif = [m for m in memori_lama if float(m.get("ts", now_ts)) >= batas_kadaluarsa]

    tz_wib = timezone(timedelta(hours=7))
    waktu_str = datetime.now(tz_wib).strftime("%d/%m %H:%M")
    snap_entry = slot.get("entry_snapshot", {})
    riwayat_tahan_sl = slot.get("sl_hold_history", [])
    is_menang = pnl_bersih_idr >= 0

    memori_aktif.append({
        "kategori": "EVAL_ENTRY",
        "hasil": "MENANG" if is_menang else "KALAH",
        "ts": now_ts,
        "waktu": waktu_str,
        "coin": slot.get("coin", "?"),
        "style": slot.get("style", "GRID"),
        "skor": float(snap_entry.get("skor", 70.0)),
        "tren_detail": str(snap_entry.get("tren_detail", "-")),
        "rsi_5m": float(snap_entry.get("rsi_5m", slot.get("rsi_at_entry", 50.0))),
        "rsi_15m": float(snap_entry.get("rsi_15m", 50.0)),
        "rasio_vol": float(snap_entry.get("rasio_vol", 1.0)),
        "pnl_pct": round(pnl_exit_pct * 100.0, 2),
        "pnl_idr": round(pnl_bersih_idr, 0),
        "sempat_tahan_sl": len(riwayat_tahan_sl) > 0
    })

    if riwayat_tahan_sl:
        tahan_terakhir = riwayat_tahan_sl[-1]
        memori_aktif.append({
            "kategori": "EVAL_TAHAN_SL",
            "hasil": "SUKSES_BANGKIT" if is_menang else "GAGAL_PANTUL",
            "ts": now_ts,
            "waktu": waktu_str,
            "coin": slot.get("coin", "?"),
            "tren_detail": str(tahan_terakhir.get("tren_detail", "-")),
            "rsi_5m": float(tahan_terakhir.get("rsi_5m", 40.0)),
            "rsi_15m": float(tahan_terakhir.get("rsi_15m", 40.0)),
            "rasio_vol": float(tahan_terakhir.get("rasio_vol", 1.0)),
            "minus_awal_pct": round(float(tahan_terakhir.get("pnl_bid_pct", -0.011)) * 100.0, 2),
            "pnl_akhir_pct": round(pnl_exit_pct * 100.0, 2),
            "pnl_idr": round(pnl_bersih_idr, 0)
        })

    state["trade_experience_memory"] = memori_aktif[-MAX_EPISODIC_MEMORY_ITEMS:]

def tarik_konteks_memori_pola_mirip(state, kategori_cari, coin, tren_detail, rsi_5m, rsi_15m, rasio_vol):
    """
    Mencocokkan kondisi teknikal koin saat ini dengan memori 72 jam terakhir (Menang vs Kalah)
    dan menghasilkan ringkasan statistik objektif untuk dimasukkan ke dalam Batch Prompt Gemini AI.
    """
    now_ts = time.time()
    batas_kadaluarsa = now_ts - (MEMORY_RETENTION_HOURS * 3600.0)
    memori_list = [
        m for m in state.get("trade_experience_memory", [])
        if float(m.get("ts", now_ts)) >= batas_kadaluarsa and m.get("kategori") == kategori_cari
    ]
    if not memori_list:
        return ""

    cocok_list = []
    for m in reversed(memori_list):
        poin_mirip = 0.0
        if m.get("coin") == coin:
            poin_mirip += 2.0
        if m.get("tren_detail") == tren_detail:
            poin_mirip += 3.0
        elif str(m.get("tren_detail", ""))[:5] == str(tren_detail)[:5]:
            poin_mirip += 1.5

        if abs(float(m.get("rsi_5m", 50.0)) - float(rsi_5m)) <= 7.0:
            poin_mirip += 2.5
        elif abs(float(m.get("rsi_5m", 50.0)) - float(rsi_5m)) <= 12.0:
            poin_mirip += 1.0

        if abs(float(m.get("rasio_vol", 1.0)) - float(rasio_vol)) <= 0.35 or (
            float(m.get("rasio_vol", 1.0)) < 0.60 and float(rasio_vol) < 0.60
        ):
            poin_mirip += 1.5

        if poin_mirip >= 4.0:
            cocok_list.append((poin_mirip, m))

    if not cocok_list:
        return ""

    if kategori_cari == "EVAL_ENTRY":
        jml_menang = sum(1 for _, m in cocok_list if m.get("hasil") == "MENANG")
        jml_kalah = sum(1 for _, m in cocok_list if m.get("hasil") == "KALAH")
        total = jml_menang + jml_kalah
        winrate = round((jml_menang / float(total)) * 100.0, 0) if total > 0 else 50.0

        kalah_terbaru = next((m for _, m in cocok_list if m.get("hasil") == "KALAH"), None)
        menang_terbaru = next((m for _, m in cocok_list if m.get("hasil") == "MENANG"), None)

        if jml_kalah > jml_menang and jml_kalah >= 2:
            info_k = f"{kalah_terbaru['coin']} {kalah_terbaru['pnl_pct']}% pada {kalah_terbaru['waktu']}" if kalah_terbaru else "-"
            return (
                f" | ⚠️ MEMORI 72J (POLA RAWAN SL - Winrate {winrate:.0f}%: {jml_menang}x TP vs {jml_kalah}x SL, "
                f"terakhir kalah {info_k}): Seleksi ekstra ketat, jawab TUNDA jika volume/momentum lemah!"
            )
        elif jml_menang > jml_kalah:
            info_m = f"{menang_terbaru['coin']} +{menang_terbaru['pnl_pct']}% pada {menang_terbaru['waktu']}" if menang_terbaru else "-"
            return (
                f" | ✅ MEMORI 72J (POLA TERBUKTI PROFIT - Winrate {winrate:.0f}%: {jml_menang}x TP vs {jml_kalah}x SL, "
                f"terakhir untung {info_m}): Pola historis mendukung YA jika struktur saat ini valid."
            )
        else:
            info_k = f"{kalah_terbaru['coin']} ({kalah_terbaru['pnl_pct']}% di RSI:{kalah_terbaru['rsi_5m']}, Vol:{kalah_terbaru['rasio_vol']}x)" if kalah_terbaru else "-"
            return (
                f" | ℹ️ MEMORI 72J (Rekor Pola Seimbang {jml_menang}x TP vs {jml_kalah}x SL, "
                f"catatan SL: {info_k}): Pastikan volume & RSI mendukung sebelum jawab YA."
            )
    else:
        jml_bangkit = sum(1 for _, m in cocok_list if m.get("hasil") == "SUKSES_BANGKIT")
        jml_gagal = sum(1 for _, m in cocok_list if m.get("hasil") == "GAGAL_PANTUL")
        gagal_terbaru = next((m for _, m in cocok_list if m.get("hasil") == "GAGAL_PANTUL"), None)

        if jml_gagal > jml_bangkit and gagal_terbaru:
            return (
                f" | ⚠️ MEMORI TAHAN SL (72J: {jml_bangkit}x Bangkit vs {jml_gagal}x Gagal Pantul; "
                f"terakhir {gagal_terbaru['coin']} ditahan saat {gagal_terbaru['minus_awal_pct']}% malah jatuh ke {gagal_terbaru['pnl_akhir_pct']}%): "
                f"Jangan paksakan TAHAN jika tren 5M/15M sudah patah deras!"
            )
        elif jml_bangkit > 0:
            return (
                f" | ✅ MEMORI TAHAN SL (72J: {jml_bangkit}x Berhasil Bangkit jadi TP vs {jml_gagal}x Gagal pada pola serupa): "
                f"Jika indikator oversold & mulai ada pantulan, aman jawab TAHAN."
            )
        return ""

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
    elif gaya == "EARLY_EMAS":
        tp_pct = min(0.0150, max(TP_EARLY_EMAS_PCT, target_ayunan_pasar * 0.75))
        sl_pct = 0.0150  # SL lebih ketat (-1.50%) khusus Lapis 2
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

            # Gunakan volume terbaik antara candle berjalan (vols[-1]) dan candle 5M utuh terakhir (vols[-2])
            vol_acuan = max(vols[-1], vols[-2]) if len(vols) >= 2 else (vols[-1] if vols else 1.0)
            vol_rata = (sum(vols[-21:-2]) / 19.0) if len(vols) >= 21 else (vol_acuan or 1.0)
            rasio_vol = vol_acuan / (vol_rata or 1.0)

            ema8_5m = sum(closes[-8:]) / len(closes[-8:])
            vol_aktif = rasio_vol >= 0.20
            candle_5m_hijau = (closes[-1] > closes[-2]) or (closes[-1] == closes[-2] and closes[-2] > closes[-3] and vol_aktif)
            dua_candle_5m_naik = (closes[-1] > closes[-3]) and (closes[-1] >= closes[-2] >= closes[-3]) and vol_aktif
            candle_jatuh_beruntun = (closes[-1] < closes[-2] < closes[-3])
            momentum_mikro_5m_naik = (closes[-1] >= ema8_5m) or dua_candle_5m_naik
            spread_aman = spread_pct <= MAX_SPREAD_INDODAX_PCT

            # Data tambahan struktur candle sebagai informasi pertimbangan bagi Gemini AI (bukan penghalang kaku)
            struktur_higher_low_5m = (lows[-1] >= lows[-2]) or (lows[-1] >= lows[-3] and dua_candle_5m_naik)
            rentang_hl_terakhir = max(highs[-1] - lows[-1], closes[-1] * 0.0001)
            posisi_close_candle = (closes[-1] - lows[-1]) / rentang_hl_terakhir

            lapis_entry = 0
            catatan_kekurangan_emas = "Lengkap (Lolos Penuh Aturan Emas Lapis 1)"

            # ------------------------------------------------------------------
            # LAPIS 1 (PRIORITAS UTAMA): 3 PINTU ATURAN EMAS
            # ------------------------------------------------------------------
            if tren_5m_naik and tren_15m_naik and 40.0 <= rsi_5m <= 67.0 and candle_5m_hijau and vol_aktif and not candle_jatuh_beruntun:
                gaya = "SNIPER"
                lapis_entry = 1
                bonus_1h = 5.0 if tren_1h_naik else 0.0
                skor_dasar = 78.0 + bonus_1h + min(12.0, (rasio_vol - 0.8) * 9.0) - abs(52.0 - rsi_5m) * 0.3
                diskon_entry_pct = min(max(atr_5m_pct * 0.35, 0.0015), 0.0045)
                prediksi = "🚀 [LAPIS-1 EMAS: SNIPER] Breakout 5M & 15M Indodax Naik - SIAP ENTRY"
                teknikal_valid = True
                faktor_bobot_status = 1.35
            elif (tren_15m_naik or tren_1h_naik) and 25.0 <= rsi_5m <= 52.0 and candle_5m_hijau and vol_aktif and not candle_jatuh_beruntun:
                gaya = "GRID"
                lapis_entry = 1
                skor_dasar = 72.0 + max(0.0, (50.0 - rsi_5m) * 0.50) + (3.5 if dua_candle_5m_naik else 0.0)
                diskon_entry_pct = min(max(atr_5m_pct * 0.60, 0.0020), 0.0070)
                prediksi = "🟢 [LAPIS-1 EMAS: PULLBACK] Rebound Kuat di Tren Makro Naik - SIAP ENTRY"
                teknikal_valid = True
                faktor_bobot_status = 1.20
            elif (rsi_5m <= 36.0 or (rsi_15m <= 38.0 and rsi_5m <= 48.0)) and candle_5m_hijau and vol_aktif and not candle_jatuh_beruntun:
                gaya = "GRID"
                lapis_entry = 1
                skor_dasar = 69.0 + max(0.0, (38.0 - min(rsi_5m, rsi_15m)) * 0.75) + (3.0 if dua_candle_5m_naik else 0.0)
                diskon_entry_pct = min(max(atr_5m_pct * 0.55, 0.0020), 0.0065)
                prediksi = "🟢 [LAPIS-1 EMAS: OVERSOLD] Oversold 5M/15M Memantul Hijau - SIAP ENTRY"
                teknikal_valid = True
                faktor_bobot_status = 1.15

            # ------------------------------------------------------------------
            # LAPIS 2 (PERPUTARAN MODAL CEPAT): RUMUS EARLY 5M SCALP AWAL
            # Persis menggunakan rumus Early 5M awal yang gesit + Target TP Cepat (+1.10%)!
            # ------------------------------------------------------------------
            elif (tren_5m_naik or momentum_mikro_5m_naik) and candle_5m_hijau and 34.0 <= rsi_5m <= 64.0 and rasio_vol >= 0.25 and not candle_jatuh_beruntun:
                gaya = "EARLY_EMAS"
                lapis_entry = 2
                bonus_tren5m = 2.0 if tren_5m_naik else 0.0
                bonus_2c = 2.0 if dua_candle_5m_naik else 0.0
                skor_dasar = 68.0 + bonus_tren5m + bonus_2c + min(6.0, max(0.0, rasio_vol - 0.25) * 4.5)
                diskon_entry_pct = min(max(atr_5m_pct * 0.50, 0.0018), 0.0060)
                info_hl = "Higher-Low=YA" if struktur_higher_low_5m else "Higher-Low=BELUM"
                catatan_kekurangan_emas = (
                    f"Early 5M Scalp (Momentum Mikro 5M Hijau Aktif | Info Struktur: {info_hl}, "
                    f"BodyCandle:{posisi_close_candle*100:.0f}%, 2CandleNaik:{'YA' if dua_candle_5m_naik else 'TIDAK'})"
                )
                prediksi = "🟢 [LAPIS-2: EARLY 5M SCALP] Momentum Mikro 5M Bangkit Hijau - SIAP ENTRY"
                teknikal_valid = True
                faktor_bobot_status = 1.00

            elif (tren_15m_naik or tren_1h_naik) and not candle_jatuh_beruntun:
                gaya = "WAIT_PULLBACK"
                skor_dasar = 58.0
                diskon_entry_pct = 0.005
                prediksi = "🟢 POTENSI REBOUND (Tren makro naik, menunggu candle 5M memantul hijau)"
                teknikal_valid = False
                faktor_bobot_status = 0.0
            elif not tren_5m_naik and not tren_15m_naik and (candle_jatuh_beruntun or (rsi_5m < 40.0 and not candle_5m_hijau)):
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
                prediksi = "🟡 SIDEWAYS WAJAR (Belum ada struktur Higher-Low / Body Hijau Kuat)"
                teknikal_valid = False
                faktor_bobot_status = 0.0

            siap_entry = teknikal_valid and spread_aman
            if teknikal_valid and not spread_aman:
                prediksi = f"⚠️ SPREAD LEBAR ({spread_pct*100:.2f}% > 0.35%) - Tunda beli baru agar tidak rugi spread"
            conviction_score = round(max(10.0, min(98.0, skor_dasar)), 1)
            acuan_beli_dasar = min(harga_idr, harga_ask)
            entry_ideal_idr = bulatkan_harga_indodax(coin, acuan_beli_dasar * (1.0 - diskon_entry_pct))
            tp_ideal_idr, sl_ideal_idr, tp_target_pct = hitung_tp_sl_dinamis_atr(
                coin, entry_ideal_idr, gaya if gaya in ["SNIPER", "GRID", "EARLY_EMAS"] else "GRID", atr_5m_pct
            )

            uptrend_nyata = (tren_5m_naik and rsi_5m >= 42.0) or (tren_15m_naik and rsi_5m >= 40.0)

            peta_analisa[coin] = {
                "coin": coin,
                "sumber_ohlc": sumber_ohlc,
                "harga_idr": harga_idr,
                "harga_bid": harga_bid,
                "harga_ask": harga_ask,
                "spread_pct": spread_pct,
                "high_2jam_idr": high_2jam_idr,
                "tren": "UPTREND" if uptrend_nyata else "SIDEWAYS/DOWN",
                "tren_5m_naik": tren_5m_naik,
                "tren_15m_naik": tren_15m_naik,
                "candle_5m_hijau": candle_5m_hijau,
                "candle_jatuh_beruntun": candle_jatuh_beruntun,
                "struktur_higher_low_5m": struktur_higher_low_5m,
                "posisi_close_candle": round(posisi_close_candle, 2),
                "lapis_entry": lapis_entry,
                "catatan_kekurangan_emas": catatan_kekurangan_emas,
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
_MODEL_SEDANG_HABIS_KUOTA = set()

def ambil_daftar_kunci_api_gemini():
    """
    Mengambil semua API Key Gemini yang tersedia. Mendukung:
    1. Beberapa API Key dipisahkan koma di dalam GEMINI_API_KEY (misal: AIzaSyA...,AIzaSyB...)
    2. Atau secret tambahan GEMINI_API_KEY_2, GEMINI_API_KEY_3 di GitHub Secrets.
    """
    kumpulan_kunci = []
    raw_utama = os.getenv("GEMINI_API_KEY", "").strip()
    for k in raw_utama.replace(";", ",").split(","):
        if k.strip() and k.strip() not in kumpulan_kunci:
            kumpulan_kunci.append(k.strip())
    for nomor in [2, 3, 4, 5]:
        k_ekstra = os.getenv(f"GEMINI_API_KEY_{nomor}", "").strip()
        if k_ekstra and k_ekstra not in kumpulan_kunci:
            kumpulan_kunci.append(k_ekstra)
    return kumpulan_kunci

def dapatkan_daftar_model_gemini_aktif():
    """
    Mengunci jalur cepat 100% stabil tanpa memanggil model eksperimental (seperti 3.5-flash / omni)
    yang menyebabkan timeout dan menghabiskan waktu fallback.
    Urutan:
    1. gemini-3-flash-preview (Otak utama penalaran tajam)
    2. gemini-flash-lite-latest (Penyelamat kuota terpisah jika 3-flash terkena limit harian 429)
    """
    semua_model = [
        "gemini-3-flash-preview",
        "gemini-flash-lite-latest"
    ]
    model_tersedia = [m for m in semua_model if m not in _MODEL_SEDANG_HABIS_KUOTA]
    return model_tersedia if model_tersedia else semua_model

def panggil_teks_gemini_ai(prompt, timeout_detik=20, mode_penalaran="MENENGAH"):
    """
    Memanggil API Gemini dengan sistem Multi-Key Rotation & Fast Fallback ke gemini-flash-lite-latest
    jika gemini-3-flash-preview kehabisan kuota harian (HTTP 429).
    """
    global _MODEL_GEMINI_AKTIF, _LEVEL_PENALARAN_AKTIF, _MODEL_SEDANG_HABIS_KUOTA
    daftar_kunci = ambil_daftar_kunci_api_gemini()
    if not daftar_kunci:
        return None, "GEMINI_API_KEY kosong"

    daftar_model = dapatkan_daftar_model_gemini_aktif()
    catatan_err = []
    budget_pikir = 256 if mode_penalaran == "RENDAH" else 1024

    for nama_model in daftar_model:
        semua_kunci_429_pada_model_ini = True
        for idx_kunci, api_key_aktif in enumerate(daftar_kunci):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{nama_model}:generateContent?key={api_key_aktif}"
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

            berhasil_atau_ganti_kunci = False
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
                            label_key = f"#K{idx_kunci+1}" if len(daftar_kunci) > 1 else ""
                            return f"[{nama_model}{label_key}] {teks}", None
                except urllib.error.HTTPError as e:
                    try:
                        detail_err = json.loads(e.read().decode()).get("error", {}).get("message", str(e))[:80]
                    except Exception:
                        detail_err = str(e)[:80]
                    if e.code == 400 and idx_p == 0:
                        continue
                    catatan_err.append(f"{nama_model}(K{idx_kunci+1})->HTTP {e.code}")
                    if e.code != 429:
                        semua_kunci_429_pada_model_ini = False
                    berhasil_atau_ganti_kunci = True
                    break
                except Exception as e:
                    semua_kunci_429_pada_model_ini = False
                    catatan_err.append(f"{nama_model}->{str(e)[:45]}")
                    berhasil_atau_ganti_kunci = True
                    break
            if berhasil_atau_ganti_kunci:
                continue

        # Jika semua kunci API terkena 429 pada model ini, tandai agar siklus siaga berikutnya langsung memakai model kedua
        if semua_kunci_429_pada_model_ini:
            _MODEL_SEDANG_HABIS_KUOTA.add(nama_model)

    return None, " | ".join(catatan_err)

def bersihkan_awalan_model(teks):
    """Menghapus label '[nama-model] ' di awal kalimat saat mengecek kata kunci YA/TUNDA/TAHAN."""
    if teks.startswith("[") and "]" in teks:
        teks = teks.split("]", 1)[1]
    return teks.upper().lstrip("*_ \t\"'-")

def konsultasi_batch_semua_keputusan_gemini(daftar_tugas_ai, status_kompas_btc, defisit_recovery_idr=0.0):
    """
    Menganalisa seluruh tugas (Entry Baru, Geser Entry, Dynamic TP, & Evaluasi SL)
    dalam 1x panggilan Batch ke Gemini AI. Dilengkapi Sistem Keputusan Cadangan Kuantitatif
    (Smart Quant Fallback) untuk TP, SL, dan Entry jika seluruh kuota Gemini sedang habis (HTTP 429).
    """
    hasil_batch = {}
    if not daftar_tugas_ai:
        return hasil_batch

    if not ambil_daftar_kunci_api_gemini():
        for t in daftar_tugas_ai:
            hasil_batch[t["id"]] = (
                t.get("default_jika_error", False),
                t.get("alasan_fallback", "Mode Kuantitatif Aktif (Tanpa API Key Gemini)."),
                True
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
        f"Anda adalah Chief Quant Scalper 5M Indodax ({konteks_mode}). Evaluasi paket data real-time berikut sekaligus.\n"
        f"Konteks Pasar: Kompas BTCIDR={status_kompas_btc}.\n"
        f"SISTEM SELEKSI 2 LAPIS:\n"
        f"- [LAPIS-1 EMAS]: Kandidat yang sudah lolos penuh 3 Pintu Aturan Emas. Prioritaskan jawab YA kecuali Kompas BTC sedang jatuh beruntun.\n"
        f"- [LAPIS-2 EARLY_EMAS (Early 5M Scalp)]: Kandidat momentum mikro 5M hijau untuk memanen profit cepat (+0.65% Scratch s/d +1.10% TP). "
        f"Jawab YA jika momentum 5M koin kuat DAN Kompas BTCIDR mendukung (Candle 5M BTC Hijau atau stabil/oversold). "
        f"Jawab TUNDA jika Candle 5M BTC sedang merah turun deras disertai struktur koin yang lemah (Higher-Low=BELUM & BodyCandle tipis).\n"
        f"Daftar Tugas Evaluasi ({len(daftar_tugas_ai)} item):\n"
        + "\n".join(baris_tugas) + "\n\n"
        f"INSTRUKSI JAWABAN:\n"
        f"Jawab WAJIB 1 baris untuk setiap ID dengan format persis:\n"
        f"[ID]: KEPUTUSAN - alasan singkat maksimal 10 kata\n"
        f"(Gunakan kata keputusan: YA atau TUNDA untuk BELI_BARU, dan YA atau TAHAN untuk GESER_ENTRY / DYNAMIC_TP / EVALUASI_SL)."
    )

    teks_respons, err_info = panggil_teks_gemini_ai(prompt_batch, timeout_detik=20, mode_penalaran="MENENGAH")
    if not teks_respons:
        print(f"⚠️ [KUOTA GEMINI LIMIT -> AKTIFKAN KEPUTUSAN CADANGAN KUANTITATIF]: {err_info}")
        for t in daftar_tugas_ai:
            keputusan_cadangan = bool(t.get("default_jika_error", False))
            alasan_cadangan = t.get("alasan_fallback", f"Eksekusi Cadangan Kuantitatif ({str(err_info)[:35]}).")
            hasil_batch[t["id"]] = (keputusan_cadangan, f"[QUANT-FALLBACK] {alasan_cadangan}", True)
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

        for segmen in isi_murni.replace(" | ", "\n").split("\n"):
            segmen_rapi = segmen.strip()
            if tid in segmen_rapi:
                bagian_kanan = segmen_rapi.split(tid, 1)[1].lstrip("]: -*_\t")
                bagian_kanan = bagian_kanan.split("[")[0].strip()
                if bagian_kanan:
                    potongan_alasan = bagian_kanan
                    break

        if not potongan_alasan and len(daftar_tugas_ai) == 1:
            potongan_alasan = isi_murni.replace("\n", " ").strip()

        if potongan_alasan:
            teks_cek = potongan_alasan.upper().lstrip("*_ \t\"'-:")
            if jenis == "BELI_BARU":
                setuju = teks_cek.startswith("YA") and ("TUNDA" not in teks_cek[:20])
            else:
                setuju = teks_cek.startswith("YA") and ("TAHAN" not in teks_cek[:20])
            hasil_batch[tid] = (setuju, f"{model_tag} {potongan_alasan}", False)
        else:
            hasil_batch[tid] = (
                bool(t.get("default_jika_error", False)),
                f"[QUANT-FALLBACK] {t.get('alasan_fallback', isi_murni[:45])}",
                True
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
            sudah_terbeli_penuh = (
                (qty_slot > 0 and koin_free >= qty_slot * 0.95)
                or (nilai_koin_idr >= 15000 and float(dompet.get("idr_locked", 0.0)) < 5000.0)
            )
            if (dompet["terhubung"] and sudah_terbeli_penuh) or (not dompet["terhubung"] and harga_sekarang <= entry_idr):
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

            # GRACE PERIOD 15 MENIT: Jangan batalkan antrean beli yang baru berumur < 15 menit hanya karena
            # pergantian candle 5M (SIDEWAYS/PULLBACK). Hanya batalkan instan (< 15m) jika jatuh ke WAIT_DOWNTREND!
            sedang_bahaya_turun = bool(
                info_pasar and (
                    info_pasar.get("gaya") == "WAIT_DOWNTREND"
                    or info_pasar.get("candle_jatuh_beruntun") is True
                    or info_pasar.get("spread_pct", 0.0) > MAX_SPREAD_INDODAX_PCT * 1.5
                )
            )
            masih_layak_entry = bool(
                info_pasar
                and not sedang_bahaya_turun
                and (
                    umur_antre_menit < 15.0
                    or (
                        info_pasar.get("teknikal_valid", info_pasar.get("siap_entry", False)) is True
                        and info_pasar.get("skor", 0) >= MIN_CONVICTION_SCORE
                    )
                )
            )
            if not masih_layak_entry:
                batalkan_order_indodax(coin, slot.get("buy_order_id"))
                dompet["idr_free"] = float(dompet.get("idr_free", 0.0)) + float(slot.get("capital_idr", 0.0))
                ada_eksekusi_penting = True
                pesan = (
                    f"🔄 [DYNAMIC CANCEL & REALOKASI INSTAN] Antrean beli {coin} ({umur_antre_menit:.0f}m) dibatalkan karena status berubah "
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
                    "alasan_fallback": f"Geser otomatis {arah_geser} sesuai rumus Dynamic Entry Indodax.",
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
            # 1. Jika koin di dompet sudah habis (< Rp5.000), berarti sudah TERJUAL (baik 100% maupun 98%-99% menyisakan debu)
            if dompet["terhubung"] and total_koin_tersisa < batas_habis_slot:
                if slot.get("tp_order_id"):
                    batalkan_order_indodax(coin, slot.get("tp_order_id"))
                harga_jual_acuan = tp_idr if slot.get("tp_order_id") else max(tp_idr, harga_bid_asli)
                kenaikan_tp_pct = (harga_jual_acuan - entry_idr) / entry_idr
                pnl_bersih_tp = kenaikan_tp_pct - FEE_ROUNDTRIP_MAKER_PCT
                profit_bersih = round(slot["capital_idr"] * pnl_bersih_tp, 0)
                catat_hasil_transaksi_ke_recovery(state, profit_bersih, coin)
                rekam_pengalaman_transaksi_bot(state, slot, profit_bersih, pnl_bersih_tp)
                ada_eksekusi_penting = True
                sisa_rec = state.get("loss_to_recover_idr", 0.0)
                info_rec = f" | Sisa Target Recovery: Rp{sisa_rec:,.0f}" if sisa_rec > 0 else ""
                pesan = (
                    f"🎉 [TP TERJUAL & SINKRON DOMPET!] {coin} ({mode_slot}) telah terjual di Rp{harga_jual_acuan:,.0f} "
                    f"(+{kenaikan_tp_pct*100:.2f}%). Profit Bersih: +Rp{profit_bersih:,.0f}!{info_rec}"
                )
                log_aksi.append(pesan)
                log_transaksi.append(pesan)
                continue

            # 2. Deteksi otomatis jika Open Order TP terhapus manual di Indodax (koin pindah dari locked ke free)
            koin_locked_skrg = dompet["coins_locked"].get(coin, 0.0)
            if dompet["terhubung"] and slot.get("tp_order_id") and koin_locked_skrg < (qty_slot * 0.30) and koin_free >= (qty_slot * 0.50):
                print(f"♻️ [DETEKSI TP TERBATAL MANUAL] Open Order TP {coin} (#{slot.get('tp_order_id')}) sudah tidak aktif di Indodax, siap pasang ulang!")
                slot["tp_order_id"] = None

            # 3. AUTO-MERGE PARTIAL FILL: Gabungkan pecahan order beli yang masuk bertahap menjadi 1 Order TP utuh
            jml_slot_koin_sama = sum(1 for s in state["active_slots"] if s.get("coin") == coin and s.get("status") == "HOLDING_FOR_TP")
            if dompet["terhubung"] and jml_slot_koin_sama == 1 and total_koin_tersisa > (qty_slot * 1.05) and koin_free > 0:
                qty_gabungan = format_qty_koin(coin, total_koin_tersisa)
                if qty_gabungan > qty_slot:
                    print(f"🔗 [AUTO-MERGE PARTIAL FILL {coin}] Menggabungkan pecahan order ({qty_slot} -> {qty_gabungan} {coin})...")
                    if slot.get("tp_order_id"):
                        batalkan_order_indodax(coin, slot["tp_order_id"])
                        slot["tp_order_id"] = None
                        time.sleep(0.8)
                    slot["qty"] = qty_gabungan
                    qty_slot = qty_gabungan
                    koin_free = qty_gabungan

            qty_milik_slot = format_qty_koin(coin, total_koin_tersisa if jml_slot_koin_sama == 1 else min(qty_slot, total_koin_tersisa))
            slot["qty"] = qty_milik_slot
            sisa_koin_dompet[coin] = round(max(0.0, total_koin_tersisa - qty_milik_slot), 8)

            # Pulihkan otomatis jika SL pernah terkunci naik karena lonjakan Last Price semu padahal Bid asli masih di bawah Entry
            if sl_idr > entry_idr and harga_bid_asli < entry_idr:
                sl_pct_awal = SL_SNIPER_BASE_PCT if mode_slot == "SNIPER" else SL_GRID_BASE_PCT
                sl_idr = bulatkan_harga_indodax(coin, entry_idr * (1.0 - sl_pct_awal))
                slot["sl_price_idr"] = sl_idr
                slot["highest_price_idr"] = entry_idr

            if not slot.get("peak_verified") or float(slot.get("highest_price_idr", entry_idr)) > max(entry_idr, harga_bid_asli * 1.015):
                slot["highest_price_idr"] = max(entry_idr, harga_bid_asli)
                slot["peak_verified"] = True

            puncak_tercatat = max(entry_idr, float(slot.get("highest_price_idr", entry_idr)), harga_bid_asli)
            slot["highest_price_idr"] = puncak_tercatat

            harga_eksekusi_jual = bulatkan_harga_indodax(coin, harga_bid_asli)
            kenaikan_skrg_pct = (harga_sekarang - entry_idr) / entry_idr
            kenaikan_bid_pct = (harga_eksekusi_jual - entry_idr) / entry_idr
            kenaikan_puncak_pct = (puncak_tercatat - entry_idr) / entry_idr
            target_tp_pct = max(0.008, (tp_idr - entry_idr) / entry_idr)
            pencapaian_puncak_ke_tp = kenaikan_puncak_pct / target_tp_pct
            pencapaian_bid_ke_tp = kenaikan_bid_pct / target_tp_pct
            lama_pegang_jam = (now_ts - float(slot.get("filled_timestamp", slot.get("timestamp", now_ts)))) / 3600.0
            estimasi_nilai_jual_skrg = qty_milik_slot * harga_eksekusi_jual

            # Cek Pemicu Dynamic Technical TP (Normal >= +0.70% Bid, atau >= +0.62% jika sudah tertahan >= 1.0 Jam di pasar sepi!)
            sudah_kelamaan_di_pasar_sepi = (lama_pegang_jam >= TIME_STOP_HOURS)
            batas_pemicu_eval_tp_pct = 0.0062 if sudah_kelamaan_di_pasar_sepi else 0.0070
            batas_lantai_eksekusi_pct = 0.0060 if sudah_kelamaan_di_pasar_sepi else 0.0065
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
                and harga_bid_asli <= puncak_tercatat * 0.9970
            )
            sinyal_momentum_melambat = (
                kenaikan_bid_pct >= 0.0090
                and (tren_sekarang != "UPTREND" or info_pasar.get("gaya", "") not in ["SNIPER", "GRID"])
            ) if info_pasar else False
            sinyal_untung_besar_dekat_tp = (kenaikan_bid_pct >= 0.0115 or pencapaian_bid_ke_tp >= 0.75)
            sinyal_time_stop_pasar_sepi = (sudah_kelamaan_di_pasar_sepi and sedang_untung_aman_bid)

            waktu_eval_tp_terakhir = float(slot.get("last_tp_eval_ts", 0.0))
            bid_eval_tp_terakhir = float(slot.get("last_tp_eval_bid_idr", harga_eksekusi_jual))
            lewat_jeda_eval_tp = (now_ts - waktu_eval_tp_terakhir) >= 300.0
            profit_terkikis = ((harga_eksekusi_jual - bid_eval_tp_terakhir) / entry_idr) <= -0.0020
            profit_melonjak_baru = ((harga_eksekusi_jual - bid_eval_tp_terakhir) / entry_idr) >= 0.0030

            butuh_evaluasi_tp_dini = (
                sedang_untung_aman_bid
                and (
                    sinyal_teknikal_melemah
                    or sinyal_koreksi_puncak
                    or sinyal_momentum_melambat
                    or sinyal_untung_besar_dekat_tp
                    or sinyal_time_stop_pasar_sepi
                )
                and (lewat_jeda_eval_tp or profit_terkikis or profit_melonjak_baru)
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
                elif sinyal_untung_besar_dekat_tp and not (sinyal_momentum_melambat or sinyal_teknikal_melemah):
                    label_exit = f"DYNAMIC TP: ZONA PROFIT TINGGI ({pencapaian_bid_ke_tp*100:.0f}% TARGET TP)"
                elif sinyal_time_stop_pasar_sepi and not (sinyal_momentum_melambat or sinyal_teknikal_melemah):
                    label_exit = f"DYNAMIC TP: TIME-STOP {lama_pegang_jam:.1f} JAM (ROTASI MODAL PASAR SEPI)"
                elif sinyal_momentum_melambat:
                    label_exit = "DYNAMIC TP: MOMENTUM MELAMBAT"
                else:
                    label_exit = "DYNAMIC TP: SINYAL REVERSAL / TREN 5M MELEMAH"

                estimasi_untung_bersih_pct = (kenaikan_bid_pct - FEE_ROUNDTRIP_MAKER_PCT) * 100.0
                tp_cadangan_setuju = bool(
                    sinyal_koreksi_puncak
                    or (sinyal_time_stop_pasar_sepi and candle_5m_merah)
                    or (kenaikan_bid_pct >= 0.0085 and (candle_5m_merah or tren_5m_patah or candle_jatuh))
                    or (kenaikan_bid_pct >= 0.0100 and sinyal_momentum_melambat)
                )
                alasan_tp_cadangan = (
                    f"YA - Kuota AI limit, TP Kuantitatif mengunci profit Bid +{kenaikan_bid_pct*100:.2f}% ({label_exit})."
                    if tp_cadangan_setuju else
                    f"TAHAN - Kuota AI limit, tren 5M masih hijau mendukung kawal ke TP Rp{tp_idr:,.0f}."
                )

                tid = f"TP_{coin}_{idx_s}"
                daftar_tugas_ai.append({
                    "id": tid,
                    "jenis": "DYNAMIC_TP",
                    "default_jika_error": tp_cadangan_setuju,
                    "alasan_fallback": alasan_tp_cadangan,
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
                sl_dini_bahaya_kuantitatif = (
                    kenaikan_bid_pct <= -0.0115
                    and tren_5m_patah
                    and (candle_jatuh or (candle_5m_merah and rsi_sekarang < 38.0))
                )
                sl_cadangan_setuju = bool(kena_hard_sl or sl_dini_bahaya_kuantitatif)
                alasan_sl_cadangan = (
                    f"YA - Kuota AI limit, SL Kuantitatif memotong rugi ({kenaikan_bid_pct*100:+.2f}%) karena tekanan jual deras."
                    if sl_cadangan_setuju else
                    f"TAHAN - Kuota AI limit, minus dini ({kenaikan_bid_pct*100:+.2f}%) masih di atas Hard SL & berpeluang pantul."
                )

                konteks_memori_sl = tarik_konteks_memori_pola_mirip(
                    state, "EVAL_TAHAN_SL", coin, tren_detail, rsi_sekarang, rsi_15m_k, vol_k
                )
                info_sudah_ditahan = (
                    f" [Posisi ini sudah ditahan {len(slot.get('sl_hold_history', []))}x]"
                    if slot.get("sl_hold_history") else ""
                )

                tid = f"SL_{coin}_{idx_s}"
                daftar_tugas_ai.append({
                    "id": tid,
                    "jenis": "EVALUASI_SL",
                    "default_jika_error": sl_cadangan_setuju,
                    "alasan_fallback": alasan_sl_cadangan,
                    "deskripsi": (
                        f"TIPE: EVALUASI_SL | Koin {coin} ({mode_slot}) Beli:Rp{entry_idr:,.0f}, sedang minus {kenaikan_bid_pct*100:+.2f}% "
                        f"di harga Bid [{label_sl}]{info_sudah_ditahan} (Last:Rp{harga_sekarang:,.0f}, Bid:Rp{harga_eksekusi_jual:,.0f}, Hard SL:Rp{sl_idr:,.0f}). "
                        f"Tren:{tren_detail}, RSI 5M:{rsi_sekarang}, RSI 15M:{rsi_15m_k}, Candle 5M:{arah_candle}, Vol:{vol_k}x, "
                        f"Diagnosa:{prediksi_koin}{konteks_memori_sl}. Jawab YA (Cut Loss sekarang untuk perkecil rugi) atau TAHAN (tunggu pantulan)."
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
                    "lama_pegang_jam": lama_pegang_jam,
                    "info_pasar": info_pasar
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
    # TAHAP 1B: SIAPKAN KANDIDAT BELI BARU (3 PINTU EMAS + FILTER KOMPAS BTC)
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
    info_btc = peta_analisa.get("BTC", {})
    btc_sedang_dump = str(info_btc.get("prediksi", "")).startswith("🔴 BAHAYA") and info_btc.get("rsi", 50.0) < 36.0
    btc_jatuh_beruntun_5m = bool(info_btc.get("candle_jatuh_beruntun", False))
    btc_candle_hijau_5m = bool(info_btc.get("candle_5m_hijau", False))
    arah_candle_btc = (
        "⚠️ MERAH-JATUH-BERUNTUN" if btc_jatuh_beruntun_5m
        else ("HIJAU-NAIK" if btc_candle_hijau_5m else "MERAH-TERTAHAN")
    )
    status_kompas_btc = (
        f"{info_btc.get('tren_detail', 'N/A')} | Candle5M:{arah_candle_btc} | "
        f"RSI 5M:{info_btc.get('rsi', '-')} | Vol:{info_btc.get('rasio_vol', '-')}x"
    )

    rencana_beli_baru = []
    pesan_status_anggaran = None

    if saldo_idr_tersedia < MIN_NEW_BUY_ALLOCATION_IDR or sisa_slot_maks <= 0:
        pesan_status_anggaran = f"[MODAL AKTIF BEKERJA] Rp{modal_aktif_state:,.0f} di {slot_terisi} posisi (Sisa IDR: Rp{dompet['idr_free']:,.0f})."
    else:
        maks_koin_terbiayai_aman = int(saldo_idr_tersedia // MIN_NEW_BUY_ALLOCATION_IDR)
        batas_ambil_kandidat = min(sisa_slot_maks, maks_koin_terbiayai_aman)
        koin_sudah_ada = {s["coin"] for s in slot_aktif_sementara}
        ai_hold_map = state.setdefault("ai_entry_hold_until", {})

        kandidat_siap_entry = sorted(
            [
                v for v in peta_analisa.values()
                if (
                    v["coin"] not in koin_sudah_ada
                    and v["coin"] not in koin_masih_cooldown
                    and (v.get("siap_entry") is True or v["coin"] in [kc.split("(")[0] for kc in koin_tembus_cooldown])
                    and v["skor"] >= skor_minimal_sesi
                    and (not btc_sedang_dump or v["coin"] == "BTC" or v["skor"] >= 82.0)
                    # Perisai Bantingan 5M BTC: Jika BTC sedang jatuh 2 candle merah beruntun, tahan dulu Lapis-2 Early 5M (kecuali Skor >= 74)
                    and (not btc_jatuh_beruntun_5m or int(v.get("lapis_entry", 1)) == 1 or v["skor"] >= 74.0)
                    and (
                        now_ts >= float(ai_hold_map.get(v["coin"], {}).get("until", 0.0))
                        or v["skor"] >= float(ai_hold_map.get(v["coin"], {}).get("last_score", 0.0)) + 3.0
                    )
                )
            ],
            key=lambda x: x.get("bobot_alokasi", x["skor"]),
            reverse=True
        )[:batas_ambil_kandidat]

        if not kandidat_siap_entry:
            koin_tertahan_ai = [
                k for k, v in ai_hold_map.items()
                if now_ts < float(v.get("until", 0.0)) and peta_analisa.get(k, {}).get("siap_entry")
            ]
            rata_rsi_pasar = (sum(v.get("rsi", 50.0) for v in peta_analisa.values()) / len(peta_analisa)) if peta_analisa else 50.0
            info_cd = f", Cooldown SL: {list(koin_masih_cooldown.keys())}" if koin_masih_cooldown else ""
            info_ai_hold = f", Ditahan AI <5m: {koin_tertahan_ai}" if koin_tertahan_ai else ""
            info_rec = f" [Mode Recovery Defisit Rp{defisit_recovery:,.0f}]" if defisit_recovery > 0 else ""
            if btc_sedang_dump or btc_jatuh_beruntun_5m:
                alasan_tahan = f"Kompas BTCIDR sedang turun beruntun 5M ({arah_candle_btc}), tunggu 1 candle BTC reda{info_cd}"
            elif rata_rsi_pasar > 65.0:
                alasan_tahan = f"Pasar Overbought RSI 5M {rata_rsi_pasar:.1f} > 65, menunggu pullback sehat{info_cd}{info_ai_hold}"
            else:
                alasan_tahan = f"Belum ada koin lolos Lapis-1 Emas / Lapis-2 Early 5M (Skor >= {skor_minimal_sesi}{info_cd}{info_ai_hold})"
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

                konteks_memori_entry = tarik_konteks_memori_pola_mirip(
                    state, "EVAL_ENTRY", coin, kandidat["tren_detail"],
                    kandidat["rsi"], kandidat["rsi_15m"], kandidat["rasio_vol"]
                )

                lapis_k = int(kandidat.get("lapis_entry", 1))
                info_kekurangan = kandidat.get("catatan_kekurangan_emas", "-")
                kekuatan_body = int(float(kandidat.get("posisi_close_candle", 0.7)) * 100)

                # ATURAN CADANGAN SAAT GEMINI LIMIT (HTTP 429):
                # - Lapis 1 (Aturan Emas Penuh): Otomatis setuju (True) karena win-rate dasarnya sudah tinggi.
                # - Lapis 2 (Early Emas 5M): Wajib divalidasi Gemini AI! Jika Gemini mati, otomatis TUNDA (False) demi keamanan modal.
                cadangan_setuju_beli = (lapis_k == 1)
                alasan_cadangan_beli = (
                    f"YA - Lolos Penuh Lapis-1 Aturan Emas Indodax ({kandidat['gaya']}, Skor:{kandidat['skor']})."
                    if cadangan_setuju_beli else
                    f"TUNDA - Kandidat Lapis-2 Early Emas ({coin}) wajib menunggu verifikasi Gemini AI aktif."
                )

                tid = f"BELI_{coin}"
                daftar_tugas_ai.append({
                    "id": tid,
                    "jenis": "BELI_BARU",
                    "default_jika_error": cadangan_setuju_beli,
                    "alasan_fallback": alasan_cadangan_beli,
                    "deskripsi": (
                        f"TIPE: BELI_BARU [LAPIS-{lapis_k}: {kandidat['gaya']}] | Koin {coin} (Skor:{kandidat['skor']}){info_rev}, "
                        f"Harga Skrg:Rp{kandidat['harga_idr']:,.0f}, Rencana Limit Buy:Rp{entry_idr:,.0f}, "
                        f"TP Dinamis:+{kandidat['tp_target_pct']}% (Alokasi:Rp{nilai_efektif_idr:,.0f} | Lapis Scratch TP +0.65% Aktif). "
                        f"Tren:{kandidat['tren_detail']}, RSI 5M:{kandidat['rsi']}, RSI 15M:{kandidat['rsi_15m']}, "
                        f"Vol:{kandidat['rasio_vol']}x, BodyCandle:{kekuatan_body}%, Spread:{kandidat['spread_pct']*100:.2f}% | "
                        f"Status Emas: {info_kekurangan}{konteks_memori_entry}. "
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
    # TAHAP 3A: EKSEKUSI KEPUTUSAN GEMINI / CADANGAN UNTUK POSISI AKTIF (GESER / TP / SL)
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
            setuju_geser, alasan_geser, _ = hasil_batch_ai.get(item["task_id"], (False, "Pertahankan antrean.", True))
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
            setuju_jual, alasan_ai, dari_fallback = hasil_batch_ai.get(item["task_id"], (False, "Tahan TP.", True))
            label_exit = item["label_exit"]
            qty_milik_slot = item["qty_milik_slot"]
            batas_lantai = item["batas_lantai_eksekusi_pct"]
            if setuju_jual:
                peta_ticker_terbaru = ambil_harga_idr_semua_koin()
                data_koin_terbaru = peta_ticker_terbaru.get(coin, {})
                bid_detik_ini = float(data_koin_terbaru.get("buy", item["harga_bid_asli"]) or item["harga_bid_asli"])
                harga_jual_detik_ini = bulatkan_harga_indodax(coin, bid_detik_ini)
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
                        pnl_bersih_tp = pct_final - FEE_ROUNDTRIP_MAKER_PCT
                        profit_bersih = round(slot["capital_idr"] * pnl_bersih_tp, 0)
                        catat_hasil_transaksi_ke_recovery(state, profit_bersih, coin)
                        rekam_pengalaman_transaksi_bot(state, slot, profit_bersih, pnl_bersih_tp)
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
                        f"saat evaluasi (di bawah batas aman +{batas_lantai*100:.2f}%). Antrean TP Rp{tp_idr:,.0f} tetap dijaga!"
                    )
            else:
                if not dari_fallback:
                    slot["last_tp_eval_ts"] = now_ts
                    slot["last_tp_eval_bid_idr"] = item["harga_eksekusi_jual"]
                    slot["last_tp_eval_reason"] = alasan_ai
                log_aksi.append(
                    f"💎 [{label_exit} -> DITAHAN] {coin} (Untung Bersih +{item['estimasi_untung_bersih_pct']:.2f}%) dikawal menuju TP Rp{tp_idr:,.0f} | Info: {alasan_ai}"
                )

        elif aksi == "TUNGGU_AI_SL":
            setuju_sl_ai, alasan_sl_ai, dari_fallback = hasil_batch_ai.get(item["task_id"], (item["kena_hard_sl"], "Evaluasi SL.", True))
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
                    pnl_exit_pct = ((harga_jual_sl - entry_idr) / entry_idr) - FEE_ROUNDTRIP_MAKER_PCT
                    pnl_bersih = round(slot["capital_idr"] * pnl_exit_pct, 0)
                    catat_hasil_transaksi_ke_recovery(state, pnl_bersih, coin)
                    rekam_pengalaman_transaksi_bot(state, slot, pnl_bersih, pnl_exit_pct)
                    ada_eksekusi_penting = True
                    pesan = (
                        f"🛡️ [{label_sl} DIEKSEKUSI] {coin} (Qty:{qty_milik_slot}) dijual di Rp{harga_jual_sl:,.0f} "
                        f"(Bid:{item['kenaikan_bid_pct']*100:+.2f}%, PnL: Rp{pnl_bersih:,.0f} | Cooldown {SL_COOLDOWN_MINUTES}m & Mode Recovery Aktif) | Info: {alasan_sl_ai}"
                    )
                    log_aksi.append(pesan)
                    log_transaksi.append(pesan)
                    continue
                else:
                    pasang_antrean_tp_di_indodax(slot, qty_milik_slot)
            else:
                if not dari_fallback:
                    slot["last_sl_eval_ts"] = now_ts
                    slot["last_sl_eval_price_idr"] = item["acuan_harga_eval_skrg"]
                    slot["last_sl_eval_reason"] = alasan_sl_ai
                    slot["last_eval_was_hard_sl"] = item["kena_hard_sl"]
                    info_p = item.get("info_pasar") or {}
                    slot.setdefault("sl_hold_history", []).append({
                        "ts": now_ts,
                        "pnl_bid_pct": item["kenaikan_bid_pct"],
                        "tren_detail": info_p.get("tren_detail", "-"),
                        "rsi_5m": info_p.get("rsi", 50.0),
                        "rsi_15m": info_p.get("rsi_15m", 50.0),
                        "rasio_vol": info_p.get("rasio_vol", 1.0),
                        "alasan_ai": alasan_sl_ai
                    })
                log_aksi.append(
                    f"🛑 [{label_sl} -> DITAHAN] {coin} (Bid:{item['kenaikan_bid_pct']*100:+.2f}%) ditahan menunggu pantulan | Info: {alasan_sl_ai}"
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

        if not slot.get("tp_order_id") and (not dompet["terhubung"] or item["koin_free"] > 0):
            pasang_antrean_tp_di_indodax(slot, item["qty_milik_slot"])
            ada_eksekusi_penting = True
            pesan = f"📌 [PASANG ULANG TP] Antrean TP {coin} diaktifkan di Rp{slot['tp_price_idr']:,.0f}."
            log_aksi.append(pesan)
            log_transaksi.append(pesan)

        if item["kenaikan_bid_pct"] >= 0.0115:
            sl_kunci_untung = bulatkan_harga_indodax(coin, entry_idr * 1.0068)
            if sl_kunci_untung > slot["sl_price_idr"]:
                slot["sl_price_idr"] = sl_kunci_untung
                log_aksi.append(
                    f"🔒 [TRAILING PROFIT LOCK] {coin} Bid nyata naik +{item['kenaikan_bid_pct']*100:.2f}%! SL dikunci di zona untung Rp{sl_kunci_untung:,.0f}."
                )

        status_tp_order = f"OrderTP:#{slot.get('tp_order_id')}" if slot.get("tp_order_id") else "TP-Aktif"
        log_aksi.append(
            f"🎯 [KAWAL {status_tp_order} | {item['lama_pegang_jam']:.1f}j] {coin} ({mode_slot}) | Skrg: Rp{item['harga_sekarang']:,.0f} (Bid:{item['kenaikan_bid_pct']*100:+.2f}%) "
            f"-> TP: Rp{tp_idr:,.0f} | SL: Rp{slot['sl_price_idr']:,.0f}"
        )
        slot_tetap_aktif.append(slot)

    # --------------------------------------------------------------------------
    # TAHAP 3B: EKSEKUSI KEPUTUSAN GEMINI / OTOMATIS 3 PINTU EMAS UNTUK BELI BARU
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

            setuju_beli, alasan_gemini, dari_fallback = hasil_batch_ai.get(
                rb["task_id"], (True, "Lolos Filter Kuantitatif 3 Pintu Emas.", True)
            )
            if not setuju_beli:
                if not dari_fallback:
                    state.setdefault("ai_entry_hold_until", {})[coin] = {
                        "until": now_ts + 300.0,
                        "last_score": kandidat["skor"],
                        "reason": alasan_gemini
                    }
                log_aksi.append(f"⏸️ [GEMINI AI HOLD ENTRY {coin} (Tahan 5m)] Setup ditunda AI: {alasan_gemini}")
                continue
            state.setdefault("ai_entry_hold_until", {}).pop(coin, None)

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
                    "entry_snapshot": {
                        "skor": kandidat["skor"],
                        "tren_detail": kandidat["tren_detail"],
                        "rsi_5m": kandidat["rsi"],
                        "rsi_15m": kandidat["rsi_15m"],
                        "rasio_vol": kandidat["rasio_vol"],
                        "spread_pct": kandidat["spread_pct"],
                        "kompas_btc": status_kompas_btc,
                        "alasan_ai": alasan_gemini
                    },
                    "sl_hold_history": [],
                    "timestamp": time.time()
                })
                ada_eksekusi_penting = True
                persen_plafon = (nilai_efektif_idr / MAX_BOT_CAPITAL_IDR) * 100.0
                label_rec = " [RECOVERY SETUP]" if (defisit_recovery > 0 or is_tembus_cd) else ""
                pesan = (
                    f"🚀 [ENTRY ORDER BELI #{order_id} - {gaya}{label_rec}] {coin} (Skor:{kandidat['skor']}) | "
                    f"Alokasi: Rp{nilai_efektif_idr:,.0f} ({persen_plafon:.0f}% Modal) | "
                    f"Beli: Rp{entry_idr:,.0f} -> TP Dinamis (+{tp_target_pct}%): Rp{tp_idr:,.0f} | Info: {alasan_gemini}"
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

    ket_siap_entry = (
        ", ".join(koin_siap_beli)
        if koin_siap_beli else
        (f"Belum ada (Pasar Overbought RSI 5M {rata_rsi_5m:.1f} > 65, menunggu pullback sehat)" if rata_rsi_5m > 65.0 else "Belum ada (menunggu setup 3 Pintu Emas & candle 5M hijau)")
    )
    mem_72j = [m for m in state.get("trade_experience_memory", []) if m.get("kategori") == "EVAL_ENTRY"]
    jml_win_72j = sum(1 for m in mem_72j if m.get("hasil") == "MENANG")
    jml_loss_72j = sum(1 for m in mem_72j if m.get("hasil") == "KALAH")
    ringkasan_pasar = (
        f"Pasar [{sumber_grafik} 5M+15M+1H]: {len(koin_uptrend)}/{total_koin_pasar} koin UPTREND | "
        f"Rata-rata RSI 5M: {rata_rsi_5m:.1f} | Kompas: {kompas_btc_str} | Sinyal Tertinggi: {info_skor_tertinggi}\n"
        f"   -> Mode Recovery Balik Modal:{status_rec_str} | Memori Pengalaman 72J: {jml_win_72j} Menang vs {jml_loss_72j} Kalah\n"
        f"   -> Koin Berstatus SIAP ENTRY Saat Ini ({len(koin_siap_beli)} koin): {ket_siap_entry}"
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
