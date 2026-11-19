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
SL_GRID_BASE_PCT = 0.0105              # -1.05% Batas Hard SL mode Grid (Kalibrasi Pro)

TP_SNIPER_MIN_PCT = 0.0180             # +1.80% Target TP minimal mode Sniper saat pasar moderat
TP_SNIPER_MAX_PCT = 0.0340             # +3.40% Target TP maksimal mode Sniper saat breakout kencang
SL_SNIPER_BASE_PCT = 0.0105            # -1.05% Batas Hard SL mode Sniper (Kalibrasi Pro)
SMART_SL_TRIGGER_PCT = -0.0070         # -0.70% Pemicu Smart SL (hanya aktif saat terdeteksi Ramai Turun)
SL_WATCH_MIN_PCT = -0.0040             # -0.40% Batas minimal Mode Siaga SL (lolos spread 0.35%)
SL_WATCH_MAX_PCT = -0.0045             # -0.45% Batas normal Mode Siaga SL berbasis 1x ATR
EMERGENCY_SL_PCT = -0.0145             # -1.45% Batas Darurat Mutlak (Market Order, rugi bersih maks ~-2.00%)
SL_THROTTLE_SECONDS = 300.0            # Rem Anti-Spam SL: jeda 5 menit (300 detik) antar-konsultasi AI
SL_MEMORY_RETENTION_HOURS = 72.0       # Memori pengalaman EVAL_TAHAN_SL disimpan selama 72 jam
MAX_SL_MEMORY_ITEMS = 40               # Maksimal menyimpan 40 riwayat keputusan tahan SL

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
            state.setdefault("sl_experience_memory", [])
            state.setdefault("sl_trade_outcome_memory", [])
            return state
        except Exception:
            pass
    return {
        "active_slots": [],
        "realized_profit_today_idr": 0.0,
        "completed_trades_today": 0,
        "loss_to_recover_idr": 0.0,
        "sl_cooldown_until": {},
        "sl_experience_memory": [],
        "sl_trade_outcome_memory": [],
        "last_reset_date": tgl_skrg
    }

def simpan_state_bot(state):
    state["last_reset_date"] = tanggal_wib_hari_ini()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def rekam_memori_tahan_sl(state, slot, pnl_bersih_idr, pnl_exit_pct=None):
    """
    Merekam memori 72 jam secara berimbang untuk pertimbangan SL Gemini AI:
    1. sl_trade_outcome_memory: seluruh hasil transaksi selesai (MENANG TP/Lock/Scratch vs KALAH SL).
    2. sl_experience_memory: khusus hasil akhir posisi yang sempat ditahan SL (SUKSES_BANGKIT vs GAGAL_PANTUL).
    """
    if not slot:
        return

    now_ts = time.time()
    batas_kadaluarsa = now_ts - (SL_MEMORY_RETENTION_HOURS * 3600.0)
    tz_wib = timezone(timedelta(hours=7))
    waktu_str = datetime.now(tz_wib).strftime("%d/%m %H:%M")

    is_menang = pnl_bersih_idr >= 0
    if pnl_exit_pct is None:
        modal = max(1.0, float(slot.get("capital_idr", 1.0)))
        pnl_exit_pct = pnl_bersih_idr / modal

    riwayat_tahan_sl = slot.get("sl_hold_history", [])

    # 1. Rekam semua hasil transaksi selesai (Menang & Kalah) selama 72 jam sebagai pembanding objektif
    outcome_aktif = [
        m for m in state.get("sl_trade_outcome_memory", [])
        if float(m.get("ts", now_ts)) >= batas_kadaluarsa
    ]
    outcome_aktif.append({
        "hasil": "MENANG" if is_menang else "KALAH",
        "ts": now_ts,
        "waktu": waktu_str,
        "coin": slot.get("coin", "?"),
        "style": slot.get("style", "GRID"),
        "pnl_pct": round(pnl_exit_pct * 100.0, 2),
        "pnl_idr": round(pnl_bersih_idr, 0),
        "sempat_tahan_sl": len(riwayat_tahan_sl) > 0
    })
    state["sl_trade_outcome_memory"] = outcome_aktif[-60:]

    # 2. Rekam khusus riwayat keputusan TAHAN SL (Bangkit jadi Menang vs Gagal Pantul jadi SL)
    if not riwayat_tahan_sl:
        return

    memori_aktif = [
        m for m in state.get("sl_experience_memory", [])
        if float(m.get("ts", now_ts)) >= batas_kadaluarsa
    ]
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
        "minus_awal_pct": round(float(tahan_terakhir.get("pnl_bid_pct", -0.007)) * 100.0, 2),
        "pnl_akhir_pct": round(pnl_exit_pct * 100.0, 2),
        "pnl_idr": round(pnl_bersih_idr, 0)
    })
    state["sl_experience_memory"] = memori_aktif[-MAX_SL_MEMORY_ITEMS:]

def tarik_konteks_memori_tahan_sl(state, coin, tren_detail, rsi_5m, rsi_15m, rasio_vol):
    """
    Menghasilkan konteks pembanding 72 jam yang berimbang khusus untuk prompt Batch SL:
    - Bagian A: Statistik pola mirip keputusan TAHAN SL (Bangkit vs Gagal vs Seimbang 50%).
    - Bagian B: Rekor objektif Menang vs Kalah 72 jam terakhir (koin ini & keseluruhan bot).
    """
    now_ts = time.time()
    batas_kadaluarsa = now_ts - (SL_MEMORY_RETENTION_HOURS * 3600.0)
    teks_konteks = ""

    # Bagian A: Evaluasi Pola Mirip Keputusan TAHAN SL
    memori_list = [
        m for m in state.get("sl_experience_memory", [])
        if float(m.get("ts", now_ts)) >= batas_kadaluarsa and m.get("kategori") == "EVAL_TAHAN_SL"
    ]
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

    if cocok_list:
        jml_bangkit = sum(1 for _, m in cocok_list if m.get("hasil") == "SUKSES_BANGKIT")
        jml_gagal = sum(1 for _, m in cocok_list if m.get("hasil") == "GAGAL_PANTUL")
        total_pola = jml_bangkit + jml_gagal
        wr_bangkit = (jml_bangkit / float(total_pola)) * 100.0 if total_pola > 0 else 50.0
        bangkit_terbaru = next((m for _, m in cocok_list if m.get("hasil") == "SUKSES_BANGKIT"), None)
        gagal_terbaru = next((m for _, m in cocok_list if m.get("hasil") == "GAGAL_PANTUL"), None)

        if jml_gagal > jml_bangkit and gagal_terbaru:
            teks_konteks += (
                f" | ⚠️ MEMORI TAHAN SL (72J: {jml_bangkit}x Bangkit vs {jml_gagal}x Gagal [{wr_bangkit:.0f}%]; "
                f"terakhir {gagal_terbaru['coin']} ditahan di {gagal_terbaru['minus_awal_pct']}% jatuh ke {gagal_terbaru['pnl_akhir_pct']}%): "
                f"Jangan paksakan TAHAN jika tren 5M/15M patah!"
            )
        elif jml_bangkit > jml_gagal and bangkit_terbaru:
            teks_konteks += (
                f" | ✅ MEMORI TAHAN SL (72J: {jml_bangkit}x Bangkit vs {jml_gagal}x Gagal [{wr_bangkit:.0f}%]; "
                f"terakhir {bangkit_terbaru['coin']} dari {bangkit_terbaru['minus_awal_pct']}% berbalik +{bangkit_terbaru['pnl_akhir_pct']}%): "
                f"Pola historis cenderung memantul, layak TAHAN jika oversold & jual mereda."
            )
        elif total_pola > 0:
            info_b = f"{bangkit_terbaru['coin']} {bangkit_terbaru['minus_awal_pct']}%->{bangkit_terbaru['pnl_akhir_pct']:+}%" if bangkit_terbaru else "-"
            info_g = f"{gagal_terbaru['coin']} {gagal_terbaru['minus_awal_pct']}%->{gagal_terbaru['pnl_akhir_pct']}%" if gagal_terbaru else "-"
            teks_konteks += (
                f" | ⚖️ MEMORI TAHAN SL SEIMBANG (72J: {jml_bangkit}x Bangkit vs {jml_gagal}x Gagal [50%]; "
                f"Bangkit:{info_b}, Gagal:{info_g}): Putuskan objektif berdasarkan tren & volume saat ini."
            )

    # Bagian B: Pembanding Objektif Menang vs Kalah 72 Jam (Seluruh Transaksi Selesai)
    outcome_list = [
        m for m in state.get("sl_trade_outcome_memory", [])
        if float(m.get("ts", now_ts)) >= batas_kadaluarsa
    ]
    if outcome_list:
        all_w = [m for m in outcome_list if m.get("hasil") == "MENANG"]
        all_l = [m for m in outcome_list if m.get("hasil") == "KALAH"]
        total_w = len(all_w)
        total_l = len(all_l)
        wr_all = (total_w / float(total_w + total_l)) * 100.0
        avg_all_w = (sum(float(m.get("pnl_pct", 0.0)) for m in all_w) / total_w) if all_w else 0.0
        avg_all_l = (sum(float(m.get("pnl_pct", 0.0)) for m in all_l) / total_l) if all_l else 0.0

        outcome_koin = [m for m in outcome_list if m.get("coin") == coin]
        if outcome_koin:
            k_w = [m for m in outcome_koin if m.get("hasil") == "MENANG"]
            k_l = [m for m in outcome_koin if m.get("hasil") == "KALAH"]
            wr_k = (len(k_w) / float(len(outcome_koin))) * 100.0
            avg_w = (sum(float(m.get("pnl_pct", 0.0)) for m in k_w) / len(k_w)) if k_w else 0.0
            avg_l = (sum(float(m.get("pnl_pct", 0.0)) for m in k_l) / len(k_l)) if k_l else 0.0
            teks_konteks += (
                f" | 📊 REKOR 72J {coin}: {len(k_w)}x Menang (avg +{avg_w:.2f}%) vs {len(k_l)}x Kalah (avg {avg_l:.2f}%) "
                f"[WR {wr_k:.0f}%] | Total Bot 72J: {total_w}W (avg +{avg_all_w:.2f}%) vs {total_l}L (avg {avg_all_l:.2f}%) [WR {wr_all:.0f}%]"
            )
        else:
            teks_konteks += (
                f" | 📊 REKOR BOT 72J: {total_w}x Menang (avg +{avg_all_w:.2f}%) vs {total_l}x Kalah (avg {avg_all_l:.2f}%) [WR {wr_all:.0f}%]"
            )

    return teks_konteks

def catat_hasil_transaksi_ke_recovery(state, pnl_bersih_idr, coin=None, slot=None, pnl_exit_pct=None):
    """Memperbarui saldo profit harian, target balik modal (loss_to_recover_idr), cooldown SL & memori 72J."""
    state["realized_profit_today_idr"] = round(float(state.get("realized_profit_today_idr", 0.0)) + pnl_bersih_idr, 0)
    state["completed_trades_today"] = int(state.get("completed_trades_today", 0)) + 1

    defisit_lama = float(state.get("loss_to_recover_idr", 0.0))
    if pnl_bersih_idr < 0:
        state["loss_to_recover_idr"] = round(defisit_lama + abs(pnl_bersih_idr), 0)
        if coin:
            state.setdefault("sl_cooldown_until", {})[coin] = time.time() + (SL_COOLDOWN_MINUTES * 60)
    else:
        state["loss_to_recover_idr"] = round(max(0.0, defisit_lama - pnl_bersih_idr), 0)

    if slot is not None:
        rekam_memori_tahan_sl(state, slot, pnl_bersih_idr, pnl_exit_pct)

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
    """Mengambil harga last, bid (buy), ask (sell), dan menghitung spread order book Indodax."""
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
    """Menentukan harga TP & SL secara dinamis berdasarkan volatilitas (ATR) Rupiah Indodax."""
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
    """Mengambil data candlestick 5 menit Rupiah asli dari Indodax (dengan fallback Kraken)."""
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

            # 1. Indikator Timeframe 5 Menit Asli Indodax
            ema20_5m = sum(closes[-20:]) / len(closes[-20:])
            ema50_5m = sum(closes[-50:]) / len(closes[-50:])
            tren_5m_naik = ema20_5m > ema50_5m
            rsi_5m = hitung_rsi(closes, 14)

            # 2. Indikator Setara Timeframe 15 Menit
            closes_15m = closes[::3]
            ema20_15m = sum(closes_15m[-20:]) / len(closes_15m[-20:])
            ema50_15m = sum(closes_15m[-50:]) / len(closes_15m[-50:])
            tren_15m_naik = ema20_15m > ema50_15m
            rsi_15m = hitung_rsi(closes_15m, 14)

            # 3. Indikator Setara Timeframe 1 Jam
            ema_1h_cepat = sum(closes[-180:]) / len(closes[-180:])
            ema_1h_lambat = sum(closes[-360:]) / len(closes[-360:])
            tren_1h_naik = ema_1h_cepat > ema_1h_lambat

            # 4. ATR 5M & High 2 Jam Terakhir
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

            candle_5m_hijau = closes[-1] >= closes[-2]
            dua_candle_5m_naik = (closes[-1] >= closes[-2] >= closes[-3])
            candle_jatuh_beruntun = (closes[-1] < closes[-2] < closes[-3])
            spread_aman = spread_pct <= MAX_SPREAD_INDODAX_PCT

            # Klasifikasi Setup Scalping Pro (5M + 15M + 1H)
            if tren_5m_naik and tren_15m_naik and 42.0 <= rsi_5m <= 65.0 and candle_5m_hijau and not candle_jatuh_beruntun:
                gaya = "SNIPER"
                bonus_1h = 5.0 if tren_1h_naik else 0.0
                skor_dasar = 78.0 + bonus_1h + min(12.0, (rasio_vol - 0.8) * 9.0) - abs(52.0 - rsi_5m) * 0.3
                diskon_entry_pct = min(max(atr_5m_pct * 0.40, 0.0015), 0.0045)
                prediksi = "🚀 BERPELUANG UNTUNG / BREAKOUT (5M & 15M Indodax Naik - SIAP ENTRY)"
                siap_entry = spread_aman
                faktor_bobot_status = 1.30
            elif (tren_15m_naik or tren_1h_naik) and 28.0 <= rsi_5m <= 48.0 and candle_5m_hijau and not candle_jatuh_beruntun:
                gaya = "GRID"
                skor_dasar = 72.0 + (48.0 - rsi_5m) * 0.55 + (4.0 if dua_candle_5m_naik else 0.0)
                diskon_entry_pct = min(max(atr_5m_pct * 0.65, 0.0020), 0.0075)
                prediksi = "🟢 POTENSI REBOUND KUAT (Pullback 5M di Tren Naik - SIAP ENTRY)"
                siap_entry = spread_aman
                faktor_bobot_status = 1.15
            elif (rsi_5m <= 33.0 or rsi_15m <= 35.0) and dua_candle_5m_naik and not candle_jatuh_beruntun:
                gaya = "GRID"
                skor_dasar = 67.0 + max(0.0, (35.0 - min(rsi_5m, rsi_15m)) * 0.85)
                diskon_entry_pct = min(max(atr_5m_pct * 0.60, 0.0020), 0.0070)
                prediksi = "🟢 POTENSI REBOUND CEPAT (Oversold 5M/15M Indodax Memantul - SIAP ENTRY)"
                siap_entry = spread_aman
                faktor_bobot_status = 1.05
            elif (tren_15m_naik or tren_1h_naik) and not candle_jatuh_beruntun:
                gaya = "WAIT_PULLBACK"
                skor_dasar = 58.0
                diskon_entry_pct = 0.005
                prediksi = "🟢 POTENSI REBOUND (Tren makro naik, menunggu candle 5M memantul hijau)"
                siap_entry = False
                faktor_bobot_status = 0.0
            elif not tren_5m_naik and not tren_15m_naik and (candle_jatuh_beruntun or (rsi_5m < 40.0 and rasio_vol >= 1.25)):
                gaya = "WAIT_DOWNTREND"
                skor_dasar = 25.0
                diskon_entry_pct = 0.012
                prediksi = "🔴 BAHAYA JATUH LEBIH DALAM (Tekanan jual 5M & 15M deras - JANGAN BELI)"
                siap_entry = False
                faktor_bobot_status = 0.0
            else:
                gaya = "WAIT_SIDEWAYS"
                skor_dasar = 45.0
                diskon_entry_pct = 0.008
                prediksi = "🟡 SIDEWAYS WAJAR (Konsolidasi 5M/15M normal, aman ditahan / jangan beli dulu)"
                siap_entry = False
                faktor_bobot_status = 0.0

            if not spread_aman and siap_entry:
                siap_entry = False
                prediksi = f"⚠️ SPREAD LEBAR ({spread_pct*100:.2f}% > 0.35%) - Tunda beli agar tidak rugi spread"

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
                "bobot_alokasi": round(conviction_score * faktor_bobot_status, 2)
            }
        except Exception:
            continue
    return peta_analisa

def konsultasi_keputusan_entry_gemini(kandidat, alokasi_idr, status_kompas_btc, defisit_recovery_idr=0.0):
    if not GEMINI_API_KEY:
        return True, "Validasi kuantitatif Native Indodax (5M+15M+1H) terpenuhi."
    try:
        konteks_recovery = (
            f"MODE RECOVERY AKTIF (Target tutup defisit Rp{defisit_recovery_idr:,.0f}, hanya terima setup A+)."
            if defisit_recovery_idr > 0 else "Mode Normal."
        )
        prompt = (
            f"Evaluasi sinyal scalping 5M Native Indodax ({konteks_recovery}): Koin {kandidat['coin']} ({kandidat['gaya']}), "
            f"Harga Rp{kandidat['harga_idr']:,.0f}, Rencana Beli Rp{kandidat['entry_ideal_idr']:,.0f}, "
            f"Target TP Dinamis +{kandidat['tp_target_pct']}% (Modal Rp{alokasi_idr:,.0f}). "
            f"Tren {kandidat['tren_detail']}, RSI 5M:{kandidat['rsi']}, RSI 15M:{kandidat['rsi_15m']}, "
            f"Spread:{kandidat['spread_pct']*100:.2f}%, Kompas BTC:{status_kompas_btc}. "
            f"Apakah layak dieksekusi BELI sekarang (jawab YA) atau TUNDA (jawab TUNDA)? "
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
        return True, "Lolos filter kuantitatif Native Indodax."

def konsultasi_keputusan_exit_gemini(coin, mode_slot, beli_idr, skrg_idr, tp_idr, puncak_idr, rsi, tren, jenis_kasus):
    if not GEMINI_API_KEY:
        return True, "Eksekusi otomatis sesuai indikator teknikal 5M/15M Indodax."
    try:
        prompt = (
            f"Koin {coin} ({mode_slot}) dibeli di Rp{beli_idr:,.0f}, target TP Rp{tp_idr:,.0f}. "
            f"Harga tertinggi sempat Rp{puncak_idr:,.0f}, sekarang Rp{skrg_idr:,.0f} "
            f"(Tren Indodax: {tren}, RSI 5M: {rsi}). Kasus: {jenis_kasus}. "
            f"Apakah sebaiknya langsung JUAL SEKARANG (jawab YA) atau TAHAN (jawab TAHAN)? "
            f"Jawab singkat: YA/TAHAN - alasan maksimal 12 kata."
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

_MODEL_SL_HABIS_KUOTA = set()

def ambil_daftar_kunci_api_gemini_sl():
    """Mendukung multi-API key (dipisah koma di GEMINI_API_KEY atau GEMINI_API_KEY_2..5) khusus SL."""
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

def dapatkan_daftar_model_gemini_sl():
    """Jalur model cepat khusus SL: gemini-3-flash-preview -> fallback gemini-flash-lite-latest."""
    semua_model = [
        "gemini-3-flash-preview",
        "gemini-flash-lite-latest"
    ]
    model_tersedia = [m for m in semua_model if m not in _MODEL_SL_HABIS_KUOTA]
    return model_tersedia if model_tersedia else semua_model

def panggil_teks_gemini_sl(prompt, timeout_detik=15, mode_penalaran="RENDAH"):
    """Panggilan Gemini khusus SL dengan Multi-Key Rotation, Model Fallback, & thinkingBudget=256 (RENDAH)."""
    global _MODEL_SL_HABIS_KUOTA
    daftar_kunci = ambil_daftar_kunci_api_gemini_sl()
    if not daftar_kunci:
        return None, "GEMINI_API_KEY kosong"

    daftar_model = dapatkan_daftar_model_gemini_sl()
    catatan_err = []
    budget_pikir = 256 if mode_penalaran == "RENDAH" else 1024

    for nama_model in daftar_model:
        semua_kunci_429 = True
        for idx_kunci, api_key_aktif in enumerate(daftar_kunci):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{nama_model}:generateContent?key={api_key_aktif}"
            daftar_payload = [
                {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 1024,
                        "thinkingConfig": {"thinkingBudget": budget_pikir}
                    }
                },
                {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 1024
                    }
                }
            ]

            ganti_kunci = False
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
                            label_key = f"#K{idx_kunci+1}" if len(daftar_kunci) > 1 else ""
                            return f"[{nama_model}{label_key}] {teks}", None
                except urllib.error.HTTPError as e:
                    if e.code == 400 and idx_p == 0:
                        continue
                    catatan_err.append(f"{nama_model}(K{idx_kunci+1})->HTTP {e.code}")
                    if e.code != 429:
                        semua_kunci_429 = False
                    ganti_kunci = True
                    break
                except Exception as e:
                    semua_kunci_429 = False
                    catatan_err.append(f"{nama_model}->{str(e)[:40]}")
                    ganti_kunci = True
                    break
            if ganti_kunci:
                continue

        if semua_kunci_429:
            _MODEL_SL_HABIS_KUOTA.add(nama_model)

    return None, " | ".join(catatan_err)

def konsultasi_batch_sl_gemini(daftar_tugas_sl, status_kompas_btc, defisit_recovery_idr=0.0):
    """1x Batch Call khusus semua evaluasi SL per siklus + Quant Fallback jika kuota habis."""
    hasil_batch = {}
    if not daftar_tugas_sl:
        return hasil_batch

    if not ambil_daftar_kunci_api_gemini_sl():
        for t in daftar_tugas_sl:
            hasil_batch[t["id"]] = (
                bool(t.get("default_jika_error", False)),
                f"[QUANT-FALLBACK] {t.get('alasan_fallback', 'Tanpa API Key Gemini.')}",
                True
            )
        return hasil_batch

    konteks_mode = (
        f"MODE RECOVERY (Defisit Rp{defisit_recovery_idr:,.0f})"
        if defisit_recovery_idr > 0 else "Mode Normal"
    )
    baris_tugas = [f"[{t['id']}] {t['deskripsi']}" for t in daftar_tugas_sl]
    prompt_batch = (
        f"Anda adalah Risk Manager Scalping 5M Indodax ({konteks_mode}). Evaluasi seluruh kasus Stop Loss berikut sekaligus.\n"
        f"Konteks Pasar: Kompas BTCIDR={status_kompas_btc}.\n"
        f"Batas Emergency SL mutlak ada di -1.45% (rugi bersih maks -2.00%). Tugas Anda memutuskan apakah tren sudah patah "
        f"sehingga harus CUT LOSS sekarang (jawab YA) atau masih koreksi wajar/oversold yang berpotensi memantul (jawab TAHAN).\n"
        f"Daftar Evaluasi SL ({len(daftar_tugas_sl)} item):\n"
        + "\n".join(baris_tugas) + "\n\n"
        f"INSTRUKSI JAWABAN:\n"
        f"Jawab WAJIB 1 baris per ID dengan format persis:\n"
        f"[ID]: YA/TAHAN - alasan singkat maksimal 10 kata"
    )

    teks_respons, err_info = panggil_teks_gemini_sl(prompt_batch, timeout_detik=15, mode_penalaran="RENDAH")
    if not teks_respons:
        print(f"⚠️ [SL GEMINI LIMIT -> QUANT FALLBACK AKTIF]: {err_info}")
        for t in daftar_tugas_sl:
            hasil_batch[t["id"]] = (
                bool(t.get("default_jika_error", False)),
                f"[QUANT-FALLBACK] {t.get('alasan_fallback', str(err_info)[:45])}",
                True
            )
        return hasil_batch

    model_tag = "[gemini-sl]"
    if teks_respons.startswith("[") and "]" in teks_respons:
        model_tag = teks_respons.split("]", 1)[0] + "]"
        isi_murni = teks_respons.split("]", 1)[1].strip()
    else:
        isi_murni = teks_respons.strip()

    for t in daftar_tugas_sl:
        tid = t["id"]
        potongan_alasan = ""
        for segmen in isi_murni.replace(" | ", "\n").split("\n"):
            segmen_rapi = segmen.strip()
            if tid in segmen_rapi:
                bagian_kanan = segmen_rapi.split(tid, 1)[1].lstrip("]: -*_\t")
                bagian_kanan = bagian_kanan.split("[")[0].strip()
                if bagian_kanan:
                    potongan_alasan = bagian_kanan
                    break

        if not potongan_alasan and len(daftar_tugas_sl) == 1:
            potongan_alasan = isi_murni.replace("\n", " ").strip()

        if potongan_alasan:
            teks_cek = potongan_alasan.upper().lstrip("*_ \t\"'-:")
            setuju_sl = teks_cek.startswith("YA") and ("TAHAN" not in teks_cek[:20])
            hasil_batch[tid] = (setuju_sl, f"{model_tag} {potongan_alasan}", False)
        else:
            hasil_batch[tid] = (
                bool(t.get("default_jika_error", False)),
                f"[QUANT-FALLBACK] {t.get('alasan_fallback', isi_murni[:45])}",
                True
            )

    return hasil_batch

# ==============================================================================
# BAGIAN 6: EVALUASI POSISI (DYNAMIC ENTRY TIAP 5M, SCRATCH >+0.60%, TP & SL)
# ==============================================================================
def evaluasi_dan_kawal_posisi_dinamis(state, peta_analisa, dompet):
    slot_tetap_aktif = []
    log_aksi = []
    log_transaksi = []
    ada_eksekusi_penting = False
    now_ts = time.time()
    defisit_recovery = float(state.get("loss_to_recover_idr", 0.0))
    antrean_batch_sl = []

    for idx_slot, slot in enumerate(state["active_slots"]):
        coin = slot["coin"]
        info_pasar = peta_analisa.get(coin)
        harga_sekarang = info_pasar["harga_idr"] if info_pasar else float(slot["entry_price_idr"])
        harga_bid_asli = info_pasar.get("harga_bid", harga_sekarang) if info_pasar else harga_sekarang
        high_2jam_idr = info_pasar["high_2jam_idr"] if info_pasar else harga_sekarang
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
        koin_locked = dompet["coins_locked"].get(coin, 0.0)
        total_koin_dimiliki = koin_free + koin_locked
        nilai_koin_idr = total_koin_dimiliki * harga_sekarang

        # ======================================================================
        # KASUS A: WAITING_BUY (100% DYNAMIC ENTRY TIAP 5 MENIT - POIN 3)
        # ======================================================================
        if slot["status"] == "WAITING_BUY":
            # 1. Cek apakah Limit Buy sudah terjemput/terbeli di Indodax
            if (dompet["terhubung"] and nilai_koin_idr >= 5000) or (not dompet["terhubung"] and harga_sekarang <= entry_idr):
                slot["status"] = "HOLDING_FOR_TP"
                slot["filled_timestamp"] = now_ts
                slot["highest_price_idr"] = max(harga_sekarang, high_2jam_idr)
                pasang_antrean_tp_di_indodax(slot, koin_free)
                ada_eksekusi_penting = True
                pesan = (
                    f"✅ [TERBELI & PASANG TP] {coin} ({mode_slot}) aktif di Rp{entry_idr:,.0f}! "
                    f"Antrean Jual TP Dinamis dipasang di Rp{slot['tp_price_idr']:,.0f}."
                )
                log_aksi.append(pesan)
                log_transaksi.append(pesan)
                slot_tetap_aktif.append(slot)
                continue

            umur_antre_menit = (now_ts - float(slot.get("timestamp", now_ts))) / 60.0
            umur_antre_jam = umur_antre_menit / 60.0

            # 2. BATAL INSTAN & PINDAH KOIN: Jika hasil analisa terbaru menyatakan koin TIDAK LAGI layak entry
            masih_layak_entry = bool(info_pasar and info_pasar.get("siap_entry") is True and info_pasar.get("skor", 0) >= MIN_CONVICTION_SCORE)
            if not masih_layak_entry:
                batalkan_order_indodax(coin, slot.get("buy_order_id"))
                # Kembalikan dana ke saldo bebas di memori agar langsung bisa dipakai beli koin lain detik ini juga!
                dompet["idr_free"] = float(dompet.get("idr_free", 0.0)) + float(slot.get("capital_idr", 0.0))
                ada_eksekusi_penting = True
                pesan = (
                    f"🔄 [DYNAMIC CANCEL & REALOKASI INSTAN] Antrean beli {coin} dibatalkan karena status berubah "
                    f"({prediksi_koin}). Modal Rp{slot.get('capital_idr', 0):,.0f} langsung dialihkan ke koin siap_entry lainnya!"
                )
                log_aksi.append(pesan)
                log_transaksi.append(pesan)
                continue

            # 3. GESER HARGA ENTRY OTOMATIS (NAIK / TURUN): Jika koin masih siap_entry tapi harga ideal bergeser >= 0.35%
            entry_ideal_baru = float(info_pasar["entry_ideal_idr"])
            selisih_entry_pct = abs(entry_ideal_baru - entry_idr) / entry_idr
            if selisih_entry_pct >= DYNAMIC_ENTRY_SHIFT_PCT and umur_antre_menit >= 8.0:
                arah_geser = "DINAIKKAN" if entry_ideal_baru > entry_idr else "DITURUNKAN"
                batalkan_order_indodax(coin, slot.get("buy_order_id"))
                time.sleep(1)
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
                        f"(TP Baru: Rp{slot['tp_price_idr']:,.0f}, OrderID: #{oid_baru})."
                    )
                    log_aksi.append(pesan)
                    log_transaksi.append(pesan)
                    slot_tetap_aktif.append(slot)
                    continue

            # 4. Evaluasi batas waktu antre maksimal (1.5 Jam)
            if umur_antre_jam >= REVIEW_ENTRY_HOURS:
                batalkan_order_indodax(coin, slot.get("buy_order_id"))
                dompet["idr_free"] = float(dompet.get("idr_free", 0.0)) + float(slot.get("capital_idr", 0.0))
                ada_eksekusi_penting = True
                pesan = f"🔄 [BATAL TIMEOUT ANTREAN] Order {coin} >{REVIEW_ENTRY_HOURS:.1f}j belum terjemput, dibatalkan untuk realokasi."
                log_aksi.append(pesan)
                log_transaksi.append(pesan)
                continue

            log_aksi.append(
                f"⏳ [ANTRE BELI DINAMIS {umur_antre_menit:.0f}m] {coin} ({mode_slot}) di Rp{entry_idr:,.0f} (Skrg: Rp{harga_sekarang:,.0f})."
            )
            slot_tetap_aktif.append(slot)
            continue

        # ======================================================================
        # KASUS B: KOIN SUDAH TERBELI (HOLDING_FOR_TP - POIN 1 & POIN 5)
        # ======================================================================
        if slot["status"] == "HOLDING_FOR_TP":
            # 1. Cek apakah order LIMIT SELL (TP) di Indodax sudah laku terjual otomatis
            if dompet["terhubung"] and nilai_koin_idr < 5000 and slot.get("tp_order_id"):
                kenaikan_tp_pct = (tp_idr - entry_idr) / entry_idr
                profit_bersih = round(slot["capital_idr"] * (kenaikan_tp_pct - FEE_ROUNDTRIP_MAKER_PCT), 0)
                catat_hasil_transaksi_ke_recovery(state, profit_bersih, coin, slot=slot, pnl_exit_pct=(kenaikan_tp_pct - FEE_ROUNDTRIP_MAKER_PCT))
                ada_eksekusi_penting = True
                sisa_rec = state.get("loss_to_recover_idr", 0.0)
                info_rec = f" | Sisa Target Recovery: Rp{sisa_rec:,.0f}" if sisa_rec > 0 else ""
                pesan = (
                    f"🎉 [TP TERJUAL OTOMATIS!] {coin} ({mode_slot}) laku di Rp{tp_idr:,.0f} "
                    f"(+{kenaikan_tp_pct*100:.2f}%). Profit Bersih: Rp{profit_bersih:,.0f}!{info_rec}"
                )
                log_aksi.append(pesan)
                log_transaksi.append(pesan)
                continue

            puncak_tercatat = max(
                float(slot.get("highest_price_idr", harga_sekarang)),
                harga_sekarang,
                high_2jam_idr if high_2jam_idr <= tp_idr * 1.03 else harga_sekarang
            )
            slot["highest_price_idr"] = puncak_tercatat

            # Perhitungan persentase di harga Last dan harga Bid Asli Indodax (bebas slippage buta 0.998)
            harga_eksekusi_jual = bulatkan_harga_indodax(coin, harga_bid_asli)
            kenaikan_skrg_pct = (harga_sekarang - entry_idr) / entry_idr
            kenaikan_bid_pct = (harga_eksekusi_jual - entry_idr) / entry_idr
            kenaikan_puncak_pct = (puncak_tercatat - entry_idr) / entry_idr
            target_tp_pct = max(0.008, (tp_idr - entry_idr) / entry_idr)
            pencapaian_puncak_ke_tp = kenaikan_puncak_pct / target_tp_pct
            lama_pegang_jam = (now_ts - float(slot.get("filled_timestamp", slot.get("timestamp", now_ts)))) / 3600.0

            qty_dimiliki = format_qty_koin(coin, total_koin_dimiliki if total_koin_dimiliki > 0 else slot.get("qty", 0))
            estimasi_nilai_jual_skrg = qty_dimiliki * harga_eksekusi_jual

            # ==================================================================
            # 0. EMERGENCY SL MUTLAK (-1.45%): BYPASS GEMINI AI & MARKET ORDER
            # ==================================================================
            if min(kenaikan_skrg_pct, kenaikan_bid_pct) <= EMERGENCY_SL_PCT and qty_dimiliki > 0 and estimasi_nilai_jual_skrg >= 10000.0:
                if slot.get("tp_order_id"):
                    batalkan_order_indodax(coin, slot["tp_order_id"])
                    slot["tp_order_id"] = None
                    time.sleep(1.0)
                res_emg = eksekusi_order_indodax(coin, "SELL", harga_eksekusi_jual, qty_koin=qty_dimiliki, order_type="MARKET")
                if not apakah_order_sukses(res_emg):
                    harga_emg_fallback = bulatkan_harga_indodax(coin, min(harga_bid_asli, harga_sekarang * 0.995))
                    res_emg = eksekusi_order_indodax(coin, "SELL", harga_emg_fallback, qty_koin=qty_dimiliki, order_type="LIMIT")
                if apakah_order_sukses(res_emg):
                    pnl_exit_pct = kenaikan_bid_pct - FEE_ROUNDTRIP_MAKER_PCT
                    pnl_bersih = round(slot["capital_idr"] * pnl_exit_pct, 0)
                    catat_hasil_transaksi_ke_recovery(state, pnl_bersih, coin, slot=slot, pnl_exit_pct=pnl_exit_pct)
                    ada_eksekusi_penting = True
                    pesan = (
                        f"🚨 [EMERGENCY SL MARKET DIEKSEKUSI] {coin} ({mode_slot}) dipotong paksa @ Bid Rp{harga_eksekusi_jual:,.0f} "
                        f"(Bid:{kenaikan_bid_pct*100:+.2f}%, PnL Bersih: Rp{pnl_bersih:,.0f} | Bypass AI, Cooldown {SL_COOLDOWN_MINUTES}m Aktif)."
                    )
                    log_aksi.append(pesan)
                    log_transaksi.append(pesan)
                    continue
                else:
                    pasang_antrean_tp_di_indodax(slot, qty_dimiliki)

            # ==================================================================
            # TRAILING PROFIT LOCK 2-TINGKAT (PEMICU +1.15% & +1.00% + LANTAI MUTLAK)
            # ==================================================================
            tren_masih_kuat_ke_tp = bool(
                info_pasar
                and info_pasar.get("tren_5m_naik", False)
                and info_pasar.get("candle_5m_hijau", False)
                and not info_pasar.get("candle_jatuh_beruntun", False)
                and 48.0 <= rsi_sekarang <= 72.0
            )

            # Aktifkan pengunci di memori slot saat pemicu tersentuh
            if kenaikan_bid_pct >= 0.0115:
                slot["lock_115_armed"] = True
                slot["lock_100_armed"] = True
            elif kenaikan_bid_pct >= 0.0100:
                slot["lock_100_armed"] = True

            eksekusi_trailing_lock = False
            label_trailing = ""

            # Prioritas 1: Pemicu +1.15% -> Jual mutlak jika jebol <= +1.01%, atau jual jika tren melemah
            if slot.get("lock_115_armed"):
                if kenaikan_bid_pct <= 0.0101:
                    eksekusi_trailing_lock = True
                    label_trailing = "TRAILING LOCK +1.15% (JEBOL LANTAI +1.01% - JUAL MUTLAK)"
                elif not tren_masih_kuat_ke_tp:
                    eksekusi_trailing_lock = True
                    label_trailing = "TRAILING LOCK +1.15% (EKSEKUSI > +1.00%)"
                else:
                    log_aksi.append(
                        f"🚀 [KAWAL KE TP | +1.15% ARMED] {coin} Bid:{kenaikan_bid_pct*100:+.2f}% tren kuat (RSI:{rsi_sekarang}), kawal menuju TP Rp{tp_idr:,.0f}."
                    )

            # Prioritas 2: Pemicu +1.00% -> Jual mutlak jika jebol <= +0.91%, atau jual jika tren melemah
            elif slot.get("lock_100_armed"):
                if kenaikan_bid_pct <= 0.0091:
                    eksekusi_trailing_lock = True
                    label_trailing = "TRAILING LOCK +1.00% (JEBOL LANTAI +0.91% - JUAL MUTLAK)"
                elif not tren_masih_kuat_ke_tp:
                    eksekusi_trailing_lock = True
                    label_trailing = "TRAILING LOCK +1.00% (EKSEKUSI > +0.90%)"
                else:
                    log_aksi.append(
                        f"🚀 [KAWAL KE TP | +1.00% ARMED] {coin} Bid:{kenaikan_bid_pct*100:+.2f}% tren kuat (RSI:{rsi_sekarang}), kawal menuju TP Rp{tp_idr:,.0f}."
                    )

            # Eksekusi langsung tanpa bisa ditahan Gemini AI
            if eksekusi_trailing_lock and estimasi_nilai_jual_skrg >= MIN_LIMIT_ORDER_INDODAX_IDR:
                if slot.get("tp_order_id"):
                    batalkan_order_indodax(coin, slot["tp_order_id"])
                    slot["tp_order_id"] = None
                    time.sleep(2)
                res_lock_jual = eksekusi_order_indodax(coin, "SELL", harga_eksekusi_jual, qty_koin=qty_dimiliki)
                if apakah_order_sukses(res_lock_jual):
                    profit_bersih = round(slot["capital_idr"] * (kenaikan_bid_pct - FEE_ROUNDTRIP_MAKER_PCT), 0)
                    catat_hasil_transaksi_ke_recovery(state, profit_bersih, coin, slot=slot, pnl_exit_pct=(kenaikan_bid_pct - FEE_ROUNDTRIP_MAKER_PCT))
                    ada_eksekusi_penting = True
                    pesan = (
                        f"🔒 [{label_trailing}] {coin} terjual di Rp{harga_eksekusi_jual:,.0f} "
                        f"(Bid: {kenaikan_bid_pct*100:.2f}%, Profit Bersih: +Rp{profit_bersih:,.0f})."
                    )
                    log_aksi.append(pesan)
                    log_transaksi.append(pesan)
                    continue
                else:
                    pasang_antrean_tp_di_indodax(slot, qty_dimiliki)

            # 2. PENYELAMATAN PROFIT 3 LAPIS (POIN 1: SCRATCH >+0.60% BID, TP RANGE >=+0.95%, & TIME-STOP)

            # Data analisa teknikal (tren melemah & RSI) untuk menilai kekuatan naik
            tren_mulai_turun = (
                not info_pasar.get("tren_5m_naik", True)
                and (not info_pasar.get("candle_5m_hijau", True) or rsi_sekarang < 46.0)
            ) if info_pasar else False

            kekuatan_naik_masih_ada = (
                tren_sekarang == "UPTREND"
                and not tren_mulai_turun
                and rsi_sekarang >= 48.0
                and (not info_pasar.get("candle_jatuh_beruntun", False) if info_pasar else True)
            )

            # Lapis A: Scratch Profit aktif mutlak di range > +0.60% s/d +0.99% (sebelum Trailing Lock +1.00% aktif)
            zona_scratch_aktif = (
                kenaikan_bid_pct > SCRATCH_PROFIT_BID_PCT
                and kenaikan_bid_pct < 0.0100
                and not slot.get("lock_100_armed")
                and not slot.get("lock_115_armed")
            )

            kondisi_scratch_profit = False
            if zona_scratch_aktif:
                if kekuatan_naik_masih_ada:
                    log_aksi.append(
                        f"🛡️ [KAWAL SCRATCH +0.60%~+0.99%] {coin} Bid:{kenaikan_bid_pct*100:+.2f}% masih ada kekuatan naik "
                        f"({tren_detail}, RSI:{rsi_sekarang}), kejar pemicu Trailing Lock +1.00%."
                    )
                else:
                    kondisi_scratch_profit = True

            trailing_lock_aktif = bool(slot.get("lock_115_armed") or slot.get("lock_100_armed"))

            # Lapis B: TP Range (Hanya bekerja sebelum Trailing Lock +1.00%/+1.15% mengambil alih)
            kondisi_tp_range = (
                not trailing_lock_aktif
                and pencapaian_puncak_ke_tp >= 0.68
                and harga_sekarang < puncak_tercatat * 0.996
                and kenaikan_bid_pct >= TP_RANGE_MIN_PROFIT_PCT
                and (tren_sekarang != "UPTREND" or rsi_sekarang < 54.0 or rsi_sekarang >= 67.0)
            )
            # Lapis C: Time-Based Scalp Exit (Hanya bekerja sebelum Trailing Lock mengambil alih)
            kondisi_time_stop = (
                not trailing_lock_aktif
                and lama_pegang_jam >= TIME_STOP_HOURS
                and kenaikan_bid_pct >= TIME_STOP_MIN_PROFIT_PCT
                and (tren_sekarang != "UPTREND" or rsi_sekarang < 52.0)
            )

            if (kondisi_scratch_profit or kondisi_tp_range or kondisi_time_stop) and estimasi_nilai_jual_skrg >= MIN_LIMIT_ORDER_INDODAX_IDR:
                if kondisi_tp_range:
                    label_exit = "TP RANGE"
                elif kondisi_time_stop:
                    label_exit = f"TIME-STOP {lama_pegang_jam:.1f}JAM"
                else:
                    label_exit = "SCRATCH PROFIT (>+0.60% TREN MELEMAH)"

                estimasi_untung_bersih_pct = (kenaikan_bid_pct - FEE_ROUNDTRIP_MAKER_PCT) * 100.0
                deskripsi_kasus = (
                    f"Posisi sudah untung kotor {kenaikan_bid_pct*100:.2f}% di harga Bid (Untung Bersih +{estimasi_untung_bersih_pct:.2f}% "
                    f"setelah fee Indodax) [{label_exit}], namun indikator mendeteksi pelemahan ({prediksi_koin}). "
                    f"JUAL SEKARANG mumpung masih untung sebelum harga berbalik turun?"
                )
                setuju_jual, alasan_ai = konsultasi_keputusan_exit_gemini(
                    coin, mode_slot, entry_idr, harga_eksekusi_jual, tp_idr, puncak_tercatat, rsi_sekarang, tren_detail, deskripsi_kasus
                )
                if setuju_jual:
                    if slot.get("tp_order_id"):
                        batalkan_order_indodax(coin, slot["tp_order_id"])
                        slot["tp_order_id"] = None
                        time.sleep(2)
                    res_jual = eksekusi_order_indodax(coin, "SELL", harga_eksekusi_jual, qty_koin=qty_dimiliki)
                    if apakah_order_sukses(res_jual):
                        profit_bersih = round(slot["capital_idr"] * (kenaikan_bid_pct - FEE_ROUNDTRIP_MAKER_PCT), 0)
                        catat_hasil_transaksi_ke_recovery(state, profit_bersih, coin, slot=slot, pnl_exit_pct=(kenaikan_bid_pct - FEE_ROUNDTRIP_MAKER_PCT))
                        ada_eksekusi_penting = True
                        pesan = (
                            f"⚡ [{label_exit} DIEKSEKUSI] {coin} dijual di Rp{harga_eksekusi_jual:,.0f} "
                            f"({kenaikan_bid_pct*100:.2f}%, Profit Bersih: Rp{profit_bersih:,.0f}) | AI: {alasan_ai}"
                        )
                        log_aksi.append(pesan)
                        log_transaksi.append(pesan)
                        continue
                    else:
                        pasang_antrean_tp_di_indodax(slot, qty_dimiliki)

            # 3. FITUR SMART SL (-0.70% RAMAI TURUN) & HARD SL (-1.05%) + THROTTLING 5M + ANTREAN 1X BATCH
            atr_pct_k = float(info_pasar.get("atr_pct", 0.0035)) if info_pasar else 0.0035
            vol_k = float(info_pasar.get("rasio_vol", 1.0)) if info_pasar else 1.0
            rsi_15m_k = float(info_pasar.get("rsi_15m", rsi_sekarang)) if info_pasar else rsi_sekarang
            candle_5m_merah = not (info_pasar.get("candle_5m_hijau", True) if info_pasar else True)
            tren_5m_patah = not (info_pasar.get("tren_5m_naik", True) if info_pasar else True)
            candle_jatuh = bool(info_pasar.get("candle_jatuh_beruntun", False)) if info_pasar else False

            pasar_ramai = (vol_k >= 1.20) or (atr_pct_k >= 0.0045)
            ramai_turun = (
                pasar_ramai
                and candle_5m_merah
                and (candle_jatuh or (tren_5m_patah and rsi_sekarang < 45.0))
            )

            acuan_pnl_sl = min(kenaikan_skrg_pct, kenaikan_bid_pct)
            acuan_harga_eval_skrg = min(harga_sekarang, harga_eksekusi_jual)
            kena_hard_sl = (harga_sekarang <= sl_idr) or (harga_eksekusi_jual <= sl_idr)
            kena_smart_sl = (acuan_pnl_sl <= SMART_SL_TRIGGER_PCT) and ramai_turun

            waktu_eval_sl_terakhir = float(slot.get("last_sl_eval_ts", 0.0))
            harga_eval_sl_terakhir = float(slot.get("last_sl_eval_price_idr", entry_idr))
            lewat_jeda_eval_sl = (now_ts - waktu_eval_sl_terakhir) >= SL_THROTTLE_SECONDS
            turun_makin_dalam = (
                harga_eval_sl_terakhir > 0
                and ((acuan_harga_eval_skrg - harga_eval_sl_terakhir) / harga_eval_sl_terakhir) <= -0.0020
            )
            naik_level_ke_hard_sl = kena_hard_sl and not bool(slot.get("last_eval_was_hard_sl", False))
            tekanan_makin_deras = (
                ramai_turun
                and candle_jatuh
                and not bool(slot.get("last_eval_was_ramai_turun", False))
            )
            lolos_throttle_sl = (
                lewat_jeda_eval_sl
                or turun_makin_dalam
                or naik_level_ke_hard_sl
                or tekanan_makin_deras
            )

            butuh_sl = (not trailing_lock_aktif) and (kena_hard_sl or kena_smart_sl)
            if butuh_sl and estimasi_nilai_jual_skrg >= MIN_LIMIT_ORDER_INDODAX_IDR:
                if lolos_throttle_sl:
                    label_sl = "HARD STOP LOSS (-1.05%)" if kena_hard_sl else "SMART SL (-0.70% RAMAI TURUN)"
                    arah_candle = "Merah/Turun" if candle_5m_merah else "Hijau/Tertahan"
                    sl_cadangan_setuju = bool(
                        kena_hard_sl or (ramai_turun and (candle_jatuh or rsi_sekarang < 38.0))
                    )
                    alasan_sl_cadangan = (
                        f"YA - Quant Fallback memotong rugi ({acuan_pnl_sl*100:+.2f}%) karena tekanan jual deras."
                        if sl_cadangan_setuju else
                        f"TAHAN - Quant Fallback menunggu pantulan sementara di atas Hard SL."
                    )
                    konteks_memori_sl = tarik_konteks_memori_tahan_sl(
                        state, coin, tren_detail, rsi_sekarang, rsi_15m_k, vol_k
                    )
                    info_ditahan = (
                        f" [Sudah ditahan {len(slot.get('sl_hold_history', []))}x]"
                        if slot.get("sl_hold_history") else ""
                    )
                    antrean_batch_sl.append({
                        "id": f"SL_{coin}_{idx_slot}",
                        "slot": slot,
                        "coin": coin,
                        "mode_slot": mode_slot,
                        "entry_idr": entry_idr,
                        "tp_idr": tp_idr,
                        "sl_idr": sl_idr,
                        "harga_sekarang": harga_sekarang,
                        "harga_bid_asli": harga_bid_asli,
                        "harga_eksekusi_jual": harga_eksekusi_jual,
                        "acuan_harga_eval_skrg": acuan_harga_eval_skrg,
                        "kenaikan_skrg_pct": kenaikan_skrg_pct,
                        "kenaikan_bid_pct": kenaikan_bid_pct,
                        "qty_dimiliki": qty_dimiliki,
                        "koin_free": koin_free,
                        "lama_pegang_jam": lama_pegang_jam,
                        "label_sl": label_sl,
                        "kena_hard_sl": kena_hard_sl,
                        "ramai_turun": ramai_turun,
                        "tren_detail": tren_detail,
                        "rsi_5m": rsi_sekarang,
                        "rsi_15m": rsi_15m_k,
                        "rasio_vol": vol_k,
                        "default_jika_error": sl_cadangan_setuju,
                        "alasan_fallback": alasan_sl_cadangan,
                        "deskripsi": (
                            f"Koin {coin} ({mode_slot}) Beli:Rp{entry_idr:,.0f}, minus Bid:{kenaikan_bid_pct*100:+.2f}% "
                            f"(Last:{kenaikan_skrg_pct*100:+.2f}%) [{label_sl}]{info_ditahan} | Hard SL:Rp{sl_idr:,.0f}, "
                            f"Tren:{tren_detail}, RSI 5M:{rsi_sekarang}, RSI 15M:{rsi_15m_k}, Candle:{arah_candle}, "
                            f"ATR:{atr_pct_k*100:.2f}%, Vol:{vol_k}x, RamaiTurun:{'YA' if ramai_turun else 'TIDAK'}, "
                            f"Diagnosa:{prediksi_koin}{konteks_memori_sl}."
                        )
                    })
                    continue
                else:
                    sisa_jeda_m = max(0.0, (SL_THROTTLE_SECONDS - (now_ts - waktu_eval_sl_terakhir)) / 60.0)
                    log_aksi.append(
                        f"🛑 [SL THROTTLE 5M | Cek ulang {sisa_jeda_m:.1f}m] {coin} (Bid:{kenaikan_bid_pct*100:+.2f}%) "
                        f"masih ditahan | AI Terakhir: {slot.get('last_sl_eval_reason', '-')}"
                    )

            # 4. Pastikan antrean LIMIT SELL (TP) terpasang di buku order Indodax
            if not slot.get("tp_order_id") and (not dompet["terhubung"] or koin_free > 0):
                pasang_antrean_tp_di_indodax(slot, koin_free)
                ada_eksekusi_penting = True
                pesan = f"📌 [PASANG ULANG TP] Antrean TP {coin} diaktifkan di Rp{slot['tp_price_idr']:,.0f}."
                log_aksi.append(pesan)
                log_transaksi.append(pesan)

            # 5. SINKRONISASI SL PENGAMAN CADANGAN UNTUK TRAILING PROFIT LOCK
            if slot.get("lock_115_armed"):
                sl_kunci_untung = bulatkan_harga_indodax(coin, entry_idr * 1.0101)
                if sl_kunci_untung > slot["sl_price_idr"]:
                    slot["sl_price_idr"] = sl_kunci_untung
                    log_aksi.append(
                        f"🔒 [SL FLOOR +1.00% TERKUNCI] {coin} lantai pengaman naik ke Rp{sl_kunci_untung:,.0f}."
                    )
            elif slot.get("lock_100_armed"):
                sl_kunci_untung = bulatkan_harga_indodax(coin, entry_idr * 1.0091)
                if sl_kunci_untung > slot["sl_price_idr"]:
                    slot["sl_price_idr"] = sl_kunci_untung
                    log_aksi.append(
                        f"🔒 [SL FLOOR +0.90% TERKUNCI] {coin} lantai pengaman naik ke Rp{sl_kunci_untung:,.0f}."
                    )

            status_tp_order = f"OrderTP:#{slot.get('tp_order_id')}" if slot.get("tp_order_id") else "TP-Aktif"
            log_aksi.append(
                f"🎯 [KAWAL {status_tp_order} | {lama_pegang_jam:.1f}j] {coin} ({mode_slot}) | Skrg: Rp{harga_sekarang:,.0f} (Bid:{kenaikan_bid_pct*100:+.2f}%) "
                f"-> TP: Rp{tp_idr:,.0f} | SL: Rp{slot['sl_price_idr']:,.0f}"
            )
            slot_tetap_aktif.append(slot)

# ==========================================================================
    # EKSEKUSI 1X BATCH GEMINI AI KHUSUS SELURUH TUGAS SL DALAM SIKLUS INI
    # ==========================================================================
    if antrean_batch_sl:
        info_btc = peta_analisa.get("BTC", {})
        status_kompas_btc = f"{info_btc.get('tren_detail', 'N/A')} (RSI 5M:{info_btc.get('rsi', '-')})"
        hasil_batch_sl = konsultasi_batch_sl_gemini(antrean_batch_sl, status_kompas_btc, defisit_recovery)

        for item_sl in antrean_batch_sl:
            slot = item_sl["slot"]
            coin = item_sl["coin"]
            mode_slot = item_sl["mode_slot"]
            entry_idr = item_sl["entry_idr"]
            tp_idr = item_sl["tp_idr"]
            qty_dimiliki = item_sl["qty_dimiliki"]
            label_sl = item_sl["label_sl"]

            setuju_sl_ai, alasan_sl_ai, dari_fallback = hasil_batch_sl.get(
                item_sl["id"], (item_sl["default_jika_error"], item_sl["alasan_fallback"], True)
            )

            if setuju_sl_ai:
                if slot.get("tp_order_id"):
                    batalkan_order_indodax(coin, slot["tp_order_id"])
                    slot["tp_order_id"] = None
                    time.sleep(1.0)
                harga_jual_sl = bulatkan_harga_indodax(coin, min(item_sl["harga_bid_asli"], item_sl["harga_sekarang"] * 0.998))
                res_sl = eksekusi_order_indodax(coin, "SELL", harga_jual_sl, qty_koin=qty_dimiliki)
                if apakah_order_sukses(res_sl):
                    pnl_exit_pct = ((harga_jual_sl - entry_idr) / entry_idr) - FEE_ROUNDTRIP_MAKER_PCT
                    pnl_bersih = round(slot["capital_idr"] * pnl_exit_pct, 0)
                    catat_hasil_transaksi_ke_recovery(state, pnl_bersih, coin, slot=slot, pnl_exit_pct=pnl_exit_pct)
                    ada_eksekusi_penting = True
                    pesan = (
                        f"🛡️ [{label_sl} DIEKSEKUSI] {coin} ({mode_slot}) dijual di Rp{harga_jual_sl:,.0f} "
                        f"(Bid:{item_sl['kenaikan_bid_pct']*100:+.2f}%, PnL: Rp{pnl_bersih:,.0f} | Cooldown {SL_COOLDOWN_MINUTES}m & Mode Recovery Aktif) | AI: {alasan_sl_ai}"
                    )
                    log_aksi.append(pesan)
                    log_transaksi.append(pesan)
                    continue
                else:
                    pasang_antrean_tp_di_indodax(slot, qty_dimiliki)
            else:
                if not dari_fallback:
                    slot["last_sl_eval_ts"] = now_ts
                    slot["last_sl_eval_price_idr"] = item_sl["acuan_harga_eval_skrg"]
                    slot["last_sl_eval_reason"] = alasan_sl_ai
                    slot["last_eval_was_hard_sl"] = item_sl["kena_hard_sl"]
                    slot["last_eval_was_ramai_turun"] = item_sl["ramai_turun"]
                    slot.setdefault("sl_hold_history", []).append({
                        "ts": now_ts,
                        "pnl_bid_pct": item_sl["kenaikan_bid_pct"],
                        "tren_detail": item_sl["tren_detail"],
                        "rsi_5m": item_sl["rsi_5m"],
                        "rsi_15m": item_sl["rsi_15m"],
                        "rasio_vol": item_sl["rasio_vol"],
                        "alasan_ai": alasan_sl_ai
                    })
                log_aksi.append(
                    f"🛑 [{label_sl} DITAHAN GEMINI AI (Jeda 5m)] {coin} (Bid:{item_sl['kenaikan_bid_pct']*100:+.2f}%) ditahan menunggu pantulan | AI: {alasan_sl_ai}"
                )

            if not slot.get("tp_order_id") and (not dompet["terhubung"] or item_sl["koin_free"] > 0):
                pasang_antrean_tp_di_indodax(slot, item_sl["koin_free"])
                ada_eksekusi_penting = True
                pesan = f"📌 [PASANG ULANG TP] Antrean TP {coin} diaktifkan di Rp{slot['tp_price_idr']:,.0f}."
                log_aksi.append(pesan)
                log_transaksi.append(pesan)

            status_tp_order = f"OrderTP:#{slot.get('tp_order_id')}" if slot.get("tp_order_id") else "TP-Aktif"
            log_aksi.append(
                f"🎯 [KAWAL {status_tp_order} | {item_sl['lama_pegang_jam']:.1f}j] {coin} ({mode_slot}) | Skrg: Rp{item_sl['harga_sekarang']:,.0f} "
                f"(Bid:{item_sl['kenaikan_bid_pct']*100:+.2f}%) -> TP: Rp{tp_idr:,.0f} | SL: Rp{slot['sl_price_idr']:,.0f}"
            )
            slot_tetap_aktif.append(slot)

    state["active_slots"] = slot_tetap_aktif
    return state, log_aksi, log_transaksi, ada_eksekusi_penting

# ==============================================================================
# BAGIAN 7: ALOKASI MODAL PRO & STRATEGI BALIK MODAL (POIN 4 & POIN 5)
# ==============================================================================
def kelola_anggaran_kosong_dengan_analisa(state, peta_analisa, dompet):
    modal_aktif_state = sum(float(s.get("capital_idr", 0)) for s in state["active_slots"])
    sisa_plafon_bot = max(0.0, MAX_BOT_CAPITAL_IDR - modal_aktif_state)
    saldo_idr_tersedia = min(dompet["idr_free"], sisa_plafon_bot) if dompet["terhubung"] else sisa_plafon_bot

    slot_terisi = len(state["active_slots"])
    sisa_slot_maks = max(0, MAX_CONCURRENT_COINS - slot_terisi)

    if saldo_idr_tersedia < MIN_NEW_BUY_ALLOCATION_IDR or sisa_slot_maks <= 0:
        return state, [
            f"[MODAL AKTIF BEKERJA] Rp{modal_aktif_state:,.0f} di {slot_terisi} posisi (Sisa IDR: Rp{dompet['idr_free']:,.0f})."
        ], [], False

    now_ts = time.time()
    defisit_recovery = float(state.get("loss_to_recover_idr", 0.0))
    profit_hari_ini = float(state.get("realized_profit_today_idr", 0.0))
    batas_rugi_harian = MAX_BOT_CAPITAL_IDR * DAILY_LOSS_LIMIT_PCT

    # 1. Tentukan Syarat Skor Minimal Berdasarkan Status Recovery & Circuit Breaker (Poin 5)
    if profit_hari_ini <= batas_rugi_harian:
        skor_minimal_sesi = 80.0  # Circuit Breaker aktif: hanya terima sinyal sangat kuat
    elif defisit_recovery > 0:
        skor_minimal_sesi = MIN_CONVICTION_SCORE + RECOVERY_SCORE_BOOST  # Mode Recovery Pro: syarat naik ke 67.5
    else:
        skor_minimal_sesi = MIN_CONVICTION_SCORE

    # 2. Bersihkan & Cek Daftar Cooldown Koin yang Baru Terkena SL (Anti-Whipsaw 45 Menit)
    cooldown_map = state.get("sl_cooldown_until", {})
    koin_masih_cooldown = {k: v for k, v in cooldown_map.items() if float(v) > now_ts}
    state["sl_cooldown_until"] = koin_masih_cooldown

    # 3. Cek Filter Kompas Bitcoin (BTCIDR Indodax Regime Filter)
    info_btc = peta_analisa.get("BTC", {})
    btc_sedang_dump = str(info_btc.get("prediksi", "")).startswith("🔴 BAHAYA") and info_btc.get("rsi", 50.0) < 36.0
    status_kompas_btc = f"{info_btc.get('tren_detail', 'N/A')} (RSI 5M:{info_btc.get('rsi', '-')})"

    maks_koin_terbiayai_aman = int(saldo_idr_tersedia // MIN_NEW_BUY_ALLOCATION_IDR)
    batas_ambil_kandidat = min(sisa_slot_maks, maks_koin_terbiayai_aman)

    koin_sudah_ada = {s["coin"] for s in state["active_slots"]}
    kandidat_siap_entry = sorted(
        [
            v for v in peta_analisa.values()
            if (
                v["coin"] not in koin_sudah_ada
                and v["coin"] not in koin_masih_cooldown
                and v.get("siap_entry") is True
                and v["skor"] >= skor_minimal_sesi
                and (not btc_sedang_dump or v["coin"] == "BTC" or v["skor"] >= 82.0)
            )
        ],
        key=lambda x: x.get("bobot_alokasi", x["skor"]),
        reverse=True
    )[:batas_ambil_kandidat]

    if not kandidat_siap_entry:
        info_cd = f", Cooldown SL: {list(koin_masih_cooldown.keys())}" if koin_masih_cooldown else ""
        info_rec = f" [Mode Recovery Defisit Rp{defisit_recovery:,.0f}]" if defisit_recovery > 0 else ""
        alasan_tahan = "Kompas BTCIDR sedang dump tajam" if btc_sedang_dump else f"Belum ada koin SIAP ENTRY dgn Skor >= {skor_minimal_sesi}{info_cd}"
        return state, [
            f"⏸️ [AI WAIT / CASH IS KING]{info_rec} Dana Rp{saldo_idr_tersedia:,.0f} tetap aman di Rupiah ({alasan_tahan})."
        ], [], False

    jumlah_siap = len(kandidat_siap_entry)
    total_bobot = sum(k.get("bobot_alokasi", k["skor"]) for k in kandidat_siap_entry)
    log_alokasi = []
    log_transaksi_beli = []
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
                f"⚠️ [SKIP {coin}] Nilai efektif Rp{nilai_efektif_idr:,.0f} di bawah buffer aman SL Rp{MIN_SAFE_SL_BUFFER_IDR:,.0f}."
            )
            continue

        setuju_beli, alasan_gemini = konsultasi_keputusan_entry_gemini(
            kandidat, nilai_efektif_idr, status_kompas_btc, defisit_recovery
        )
        if not setuju_beli:
            log_alokasi.append(f"⏸️ [GEMINI AI HOLD ENTRY {coin}] Setup ditunda AI: {alasan_gemini}")
            continue

        tp_idr = kandidat["tp_ideal_idr"]
        sl_idr = kandidat["sl_ideal_idr"]
        tp_target_pct = kandidat["tp_target_pct"]

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
            label_rec = " [RECOVERY SETUP]" if defisit_recovery > 0 else ""
            pesan = (
                f"🚀 [ENTRY ORDER BELI #{order_id} - {gaya}{label_rec}] {coin} (Skor:{kandidat['skor']}) | "
                f"Alokasi: Rp{nilai_efektif_idr:,.0f} ({persen_plafon:.0f}% Modal) | "
                f"Beli: Rp{entry_idr:,.0f} -> TP Dinamis (+{tp_target_pct}%): Rp{tp_idr:,.0f} | AI: {alasan_gemini}"
            )
            log_alokasi.append(pesan)
            log_transaksi_beli.append(pesan)

    return state, log_alokasi, log_transaksi_beli, ada_order_baru

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
        puncak = max(float(slot.get("highest_price_idr", skrg)), skrg, info.get("high_2jam_idr", skrg))
        nilai_skrg = float(slot.get("qty", 0)) * skrg

        if slot["status"] == "HOLDING_FOR_TP":
            pnl_bid_pct = (harga_bid - entry) / entry
            target_pct = max(0.008, (tp - entry) / entry)
            rasio_puncak_ke_tp = ((puncak - entry) / entry) / target_pct
            atr_k = float(info.get("atr_pct", 0.0045))
            batas_siaga_sl = max(SL_WATCH_MAX_PCT, min(SL_WATCH_MIN_PCT, -atr_k))

            if pnl_bid_pct >= 0.0085:
                alasan_siaga.append(f"{coin} sudah di zona profit Bid +{pnl_bid_pct*100:.2f}% (kawal ketat Trailing Lock +1.00%/+1.15%)")
            elif pnl_bid_pct > SCRATCH_PROFIT_BID_PCT:
                alasan_siaga.append(f"{coin} sudah di zona untung bersih Bid +{pnl_bid_pct*100:.2f}% (kawal ketat Scratch/TP)")
            elif pnl_bid_pct <= batas_siaga_sl and nilai_skrg >= 10000.0:
                vol_k = float(info.get("rasio_vol", 1.0))
                arah_pasar = "RAMAI TURUN" if ((vol_k >= 1.20 or atr_k >= 0.0045) and not info.get("candle_5m_hijau", True)) else "KOREKSI/PANTAU"
                alasan_siaga.append(
                    f"{coin} turun {pnl_bid_pct*100:.2f}% <= Siaga SL {batas_siaga_sl*100:.2f}% "
                    f"[{arah_pasar} | ATR:{atr_k*100:.2f}%, Vol:{vol_k}x]"
                )
            elif rasio_puncak_ke_tp >= 0.55:
                alasan_siaga.append(f"{coin} pernah menyentuh {rasio_puncak_ke_tp*100:.0f}% target TP (kawal Missed-Peak)")

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

    # Rekap Win Rate 72 Jam (Keseluruhan Bot + Per Koin + Memori Tahan SL)
    batas_72j = time.time() - (SL_MEMORY_RETENTION_HOURS * 3600.0)
    outcome_72j = [
        m for m in state.get("sl_trade_outcome_memory", [])
        if float(m.get("ts", 0.0)) >= batas_72j
    ]
    tahan_sl_72j = [
        m for m in state.get("sl_experience_memory", [])
        if float(m.get("ts", 0.0)) >= batas_72j and m.get("kategori") == "EVAL_TAHAN_SL"
    ]

    if outcome_72j:
        all_w = [m for m in outcome_72j if m.get("hasil") == "MENANG"]
        all_l = [m for m in outcome_72j if m.get("hasil") == "KALAH"]
        tot_w, tot_l = len(all_w), len(all_l)
        wr_tot = (tot_w / float(tot_w + tot_l)) * 100.0
        avg_w_tot = (sum(float(m.get("pnl_pct", 0.0)) for m in all_w) / tot_w) if tot_w else 0.0
        avg_l_tot = (sum(float(m.get("pnl_pct", 0.0)) for m in all_l) / tot_l) if tot_l else 0.0
        rekap_wr_total = f"{tot_w}W/{tot_l}L (WR {wr_tot:.0f}% | Avg Win:+{avg_w_tot:.2f}% | Avg Loss:{avg_l_tot:.2f}%)"

        koin_unik = sorted({m.get("coin", "?") for m in outcome_72j})
        daftar_wr_koin = []
        for ck in koin_unik:
            mk = [m for m in outcome_72j if m.get("coin") == ck]
            kw = [m for m in mk if m.get("hasil") == "MENANG"]
            kl = [m for m in mk if m.get("hasil") == "KALAH"]
            wrk = (len(kw) / float(len(mk))) * 100.0
            aw = (sum(float(m.get("pnl_pct", 0.0)) for m in kw) / len(kw)) if kw else 0.0
            al = (sum(float(m.get("pnl_pct", 0.0)) for m in kl) / len(kl)) if kl else 0.0
            daftar_wr_koin.append(f"{ck}: {len(kw)}W/{len(kl)}L (WR {wrk:.0f}%, +{aw:.2f}%/{al:.2f}%)")
        rekap_wr_koin = " | ".join(daftar_wr_koin)
    else:
        rekap_wr_total = "Belum ada transaksi selesai dlm 72 jam terakhir"
        rekap_wr_koin = "-"

    jml_bangkit_72j = sum(1 for m in tahan_sl_72j if m.get("hasil") == "SUKSES_BANGKIT")
    jml_gagal_72j = sum(1 for m in tahan_sl_72j if m.get("hasil") == "GAGAL_PANTUL")
    rekap_tahan_sl = (
        f"{jml_bangkit_72j}x Bangkit vs {jml_gagal_72j}x Gagal"
        if tahan_sl_72j else "Belum ada riwayat tahan SL"
    )

    ringkasan_pasar = (
        f"Pasar [{sumber_grafik} 5M+15M+1H]: {len(koin_uptrend)}/{total_koin_pasar} koin UPTREND | "
        f"Rata-rata RSI 5M: {rata_rsi_5m:.1f} | Kompas: {kompas_btc_str} | Sinyal Tertinggi: {info_skor_tertinggi}\n"
        f"   -> Mode Recovery Balik Modal:{status_rec_str}\n"
        f"   -> Statistik Memori 72J (Total Bot): {rekap_wr_total} | Tahan SL: {rekap_tahan_sl}\n"
        f"   -> Win Rate 72J Per Koin: {rekap_wr_koin}\n"
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

    teks_final = (
        f"🟢 [PATROLI PRO SCALPER 5M SELESAI | Profit Hari Ini: Rp{state.get('realized_profit_today_idr', 0):,.0f} ({state.get('completed_trades_today', 0)} Trade)]\n"
        f"📊 DIAGNOSA PORTOFOLIO & PREDIKSI CANDLESTICK RUPIAH INDODAX (5M + 15M + 1H):\n"
        f"{teks_diagnosa}\n"
        f"   -> {ringkasan_pasar}"
    )

    summary_file = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if summary_file:
        try:
            tz_wib = timezone(timedelta(hours=7))
            waktu_run = datetime.now(tz_wib).strftime("%Y-%m-%d %H:%M:%S WIB")
            md_summary = (
                f"### 📊 Ringkasan Patroli & Win Rate 72 Jam ({waktu_run})\n"
                f"- **Profit Hari Ini:** Rp{state.get('realized_profit_today_idr', 0):,.0f} ({state.get('completed_trades_today', 0)} Trade)\n"
                f"- **Win Rate 72J (Total Bot):** {rekap_wr_total}\n"
                f"- **Win Rate 72J (Per Koin):** {rekap_wr_koin}\n"
                f"- **Rekor Tahan SL 72J:** {rekap_tahan_sl}\n"
                f"- **Mode Recovery:** {status_rec_str.strip()}\n\n"
                f"```text\n{teks_final}\n```\n"
            )
            with open(summary_file, "a", encoding="utf-8") as sf:
                sf.write(md_summary)
        except Exception:
            pass

    return teks_final

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
# BAGIAN 10: PROGRAM UTAMA (HANYA KIRIM SHEETS JIKA ADA ENTRY / TP / SL)
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

    # Langkah 2: Analisa Native Indodax (5M + 15M + 1H), kawal posisi & Dynamic Entry
    peta_analisa_pasar = analisa_teknikal_lengkap_pasar(harga_live_map)
    state, log_kawal, log_tx_kawal, ada_aksi_kawal = evaluasi_dan_kawal_posisi_dinamis(state, peta_analisa_pasar, dompet)
    state, log_alokasi, log_tx_beli, ada_aksi_beli = kelola_anggaran_kosong_dengan_analisa(state, peta_analisa_pasar, dompet)
    simpan_state_bot(state)

    butuh_siaga, alasan_siaga = cek_apakah_butuh_pengawasan_intensif(state, peta_analisa_pasar)
    semua_log_konsol = log_recovery + log_kawal + log_alokasi
    for baris in semua_log_konsol:
        print("  ", baris)

    log_khusus_transaksi = log_recovery + log_tx_kawal + log_tx_beli
    ada_transaksi_nyata = bool(log_khusus_transaksi) or ada_aksi_kawal or ada_aksi_beli

    if ada_transaksi_nyata or paksa_kirim_sheets:
        lapor_ke_google_sheets(state, log_khusus_transaksi or semua_log_konsol, dompet, harga_live_map)
    else:
        print("ℹ️ [TIDAK ADA TRANSAKSI BARU] Sesi patroli tenang, Google Sheets tidak ditambah baris baru agar jurnal tetap bersih.")

    return state, butuh_siaga, alasan_siaga, ada_transaksi_nyata, peta_analisa_pasar

if __name__ == "__main__":
    waktu_mulai = time.time()
    batas_waktu_siaga = waktu_mulai + (ACTIVE_WATCH_MINUTES * 60)

    state = muat_state_bot()
    state, butuh_siaga, alasan_siaga, _, peta_analisa_terakhir = jalankan_satu_siklus_penuh(
        state, paksa_kirim_sheets=False
    )

    if butuh_siaga and ACTIVE_WATCH_MINUTES > 0:
        print(f"\n🔥 [SINYAL DETEKSI AKTIF] Bot masuk Mode Pengawasan Intensif selama {ACTIVE_WATCH_MINUTES} menit:")
        for alasan in alasan_siaga:
            print(f"   -> {alasan}")

        putaran = 1
        kesimpulan_sudah_cetak = False
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
                kesimpulan_sudah_cetak = True
                break
        if not kesimpulan_sudah_cetak:
            print("\n" + buat_kesimpulan_patroli_dinamis(state, peta_analisa_terakhir))
    else:
        print("\n" + buat_kesimpulan_patroli_dinamis(state, peta_analisa_terakhir))
