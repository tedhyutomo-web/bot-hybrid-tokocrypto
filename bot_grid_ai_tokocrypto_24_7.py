# ==============================================================================
# PRO QUANT HYBRID AI TRADING BOT 24/7 (100% NATIVE INDODAX V2 + GEMINI AI)
# ==============================================================================
# Edisi Pro Grid Per-Lapis (Perbaikan Menyeluruh):
# 1. PENYELESAIAN PER LAPIS: Tiap Lapis (L1, L2, L3) selesai tuntas di TP b1-nya
# 2. SELF-HEALING MOC + FALLBACK GTC: Bebas posisi yatim & jaring macet
# 3. REKONSILIASI DOMPET + PARTIALLY_FILLED HANDLER: Sinkron 2 arah dgn Indodax
# 4. RSI WILDER (RMA) + ANTI-INCOMPLETE CANDLE + ANTI-SLOW BLEED 4H
# 5. VALIDASI GEMINI AI AKTIF DI GRID (Lapis 1, 2, 3) + INVALIDATION GUARD
# 6. LAPORAN GOOGLE SHEETS AKURAT UNTUK MODE GRID & MODE SCALPER
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
# BAGIAN 1: KONFIGURASI UTAMA, PARAMETER GRID PER-LAPIS & PROTEKSI MODAL
# ==============================================================================
MAX_BOT_CAPITAL_IDR = float(os.getenv("MAX_BOT_CAPITAL_IDR", "100000"))
MIN_LIMIT_ORDER_INDODAX_IDR = 25000.0  # Syarat minimum nilai Limit Order Indodax
MIN_SAFE_SL_BUFFER_IDR = 28500.0       # Nilai bersih koin wajib >= Rp28.500 agar saat SL tetap > Rp25.000
MIN_NEW_BUY_ALLOCATION_IDR = 32000.0   # Minimal alokasi beli baru per koin agar 100% aman saat eksekusi SL
FEE_ROUNDTRIP_MAKER_PCT = 0.0055       # Estimasi total biaya beli+jual+PPN+CFX Indodax ~0.55%
FEE_ONEWAY_MAKER_PCT = 0.00275         # ~0.275% per sisi (Maker / MOC + PPN + CFX)
FEE_ONEWAY_TAKER_PCT = 0.00400         # ~0.400% per sisi (Taker / fallback GTC + PPN + CFX)
MAX_SPREAD_INDODAX_PCT = 0.0035        # Maksimal toleransi Bid-Ask Spread Indodax (0.35%)

# ==============================================================================
# KONFIGURASI METODE GRID 3-LAPIS (SELESAI PER LAPIS DI TP b1 MASING-MASING)
# ==============================================================================
GRID_MODE_ENABLED = True               # True = aktifkan Grid 3-Lapis; False = mode scalping cadangan
GRID_CAPITAL_PER_LAYER_IDR = float(os.getenv("GRID_CAPITAL_PER_LAYER_IDR", "33000"))
GRID_STEP_PCT = 0.0150                 # Default fallback jarak antar grid 1.50%
GRID_STEP_GREEN_PCT = 0.0150           # Fallback aman (jangan dihapus, dipakai fungsi migrasi)
GRID_STEP_MIN_PCT = 0.0150             # Batas minimum mutlak jarak grid & TP (1.50% agar aman potong fee)
GRID_STEP_MAX_GREEN_PCT = 0.0300       # Batas maksimum jarak grid saat 4H Hijau (3.00% agar TP tetap realistis)
GRID_STEP_MAX_YELLOW_PCT = 0.0350      # Batas maksimum jarak grid saat 4H Kuning (3.50% saat downtrend volatil)
GRID_ATR_MULT_GREEN = 1.8              # Pengali ATR 1H saat 4H Hijau
GRID_ATR_MULT_YELLOW = 2.2             # Pengali ATR 1H saat 4H Kuning (lebih lebar/defensif)
GRID_MAX_TIERS = 0                     # 0 = Tanpa batas maksimal lapis (hanya dibatasi saldo IDR)
GRID_NEXT_TIER_DROP_GREEN_PCT = 0.0300 # Pemicu buka lapis berikutnya: turun >= 3.00% di bawah b3 lapis terbawah (Hijau)
GRID_NEXT_TIER_DROP_YELLOW_PCT = 0.0400# Pemicu buka lapis berikutnya: turun >= 4.00% di bawah b3 lapis terbawah (Kuning)

# Filter 4H Anti-Crash & Anti-Slow-Bleed
GRID_4H_CRASH_RSI = 30.0               # Batas RSI 4H (Wilder) untuk veto Lampu Merah
GRID_4H_CRASH_VOL_RATIO = 1.60         # Lonjakan volume jual 4H (closed / proyeksi waktu) untuk deteksi crash
GRID_4H_FLASH_CRASH_PCT = -0.045       # Veto instan jika 1 candle 4H berjalan anjlok >= -4.50%
GRID_4H_SLOW_BLEED_EMA50_PCT = 0.040   # Veto slow-bleed jika downtrend 3 candle merah & >4% di bawah EMA50 4H

# Filter Anti-Pucuk Entry Grid
GRID_MAX_RSI_M5_ENTRY = 58.0           # Batas atas RSI 5M (Wilder) saat 4H Hijau (anti beli pucuk)
GRID_MAX_RSI_M5_YELLOW = 52.0          # Batas atas RSI 5M (Wilder) saat 4H Kuning
GRID_MAX_DIST_EMA20_15M_PCT = 0.0080   # Harga maksimal +0.80% di atas EMA20 15M agar entry dekat area value
GRID_MIN_ATR_15M_PCT = 0.0035          # Syarat volatilitas minimal 15M agar rentang cukup melibas fee 0.55%
GRID_WAIT_B1_TIMEOUT_MIN = 45.0        # Batas tunggu antrean awal b1 sebelum dibatalkan jika belum terjemput
GRID_MEMORY_RETENTION_HOURS = 168.0    # Memori pengalaman siklus Grid disimpan 1 minggu (168 jam)
MAX_GRID_MEMORY_ITEMS = 60             # Maksimal menyimpan 60 riwayat siklus Grid dalam 1 minggu
GRID_ALLOWED_COINS = {"BTC"}
GRID_LIMIT_TIF = "MOC"                 # Prioritas Maker-Only Cancel dengan fallback aman ke GTC bila ditolak

# Validasi Gemini AI & Proteksi Invalidation Grid
GRID_MIN_SCORE_ENTRY = 65.0            # Syarat skor efektif minimal (setelah penyesuaian memori 7H) untuk buka Lapis 1
GRID_INVALIDATION_ENABLED = False      # Nonaktif: Murni Grid/DCA BTC tanpa Stop Loss / Cut Loss
GRID_INVALIDATION_DD_PCT = -0.12       # Tidak dipakai selama GRID_INVALIDATION_ENABLED = False
GRID_INVALIDATION_AUTO_CUT = False     # Nonaktif permanen (tidak akan pernah cut loss)

# ==============================================================================
# KONFIGURASI PEMBAGIAN DANA (BUDGET VAULT: GRID BTC vs MINI SWING NON-BTC)
# ==============================================================================
GRID_BUDGET_PER_TIER_IDR = float(os.getenv("GRID_BUDGET_PER_TIER_IDR", "100000"))
SWING_MODE_ENABLED = os.getenv("SWING_MODE_ENABLED", "true").lower() == "true"
MAX_SWING_CAPITAL_IDR = float(os.getenv("MAX_SWING_CAPITAL_IDR", "100000"))

# ==============================================================================
# KONFIGURASI SISTEM MINI SWING DETERMINISTIK INDODAX (BLUEPRINT PMK 50/2025 + CFX)
# ==============================================================================
SWING_ALLOWED_COINS = {"ETH", "SOL", "XRP", "DOGE", "PEPE"}

SWING_FEE_BUY_MAKER = 0.001111
SWING_FEE_SELL_MAKER = 0.003211
SWING_FEE_SELL_TAKER = 0.004211
SWING_SLIPPAGE_SL_PCT = 0.0015
SWING_BE_PLUS_MULT = 1.0075

SWING_ATR_MIN_PCT = 0.0130
SWING_ATR_FLOOR_MAX_PCT = 0.0150
SWING_ATR_SWEET_MAX_PCT = 0.0300
SWING_ATR_CAP_MAX_PCT = 0.0450
SWING_SL_FLOOR_PCT = 0.0220
SWING_SL_CAP_PCT = 0.0450
SWING_MAX_POS_LOSS_CAP = 0.0500
SWING_MIN_NET_RRR = 1.75
SWING_MAX_SINGLE_CONCENTRATION = 0.50
SWING_MIN_PARTIAL_SPLIT_IDR = 56000.0

SWING_RISK_BULLISH = 0.0150
SWING_RISK_SIDEWAYS = 0.0125
SWING_RISK_BEARISH = 0.0075
SWING_MAX_SLOTS_BULLISH = 2
SWING_MAX_SLOTS_SIDEWAYS = 2
SWING_MAX_SLOTS_BEARISH = 1

SWING_MAX_SPREAD_PCT = 0.0015
SWING_MIN_OBP = 0.52
SWING_MIN_DEPTH_2PCT_IDR = 800000000.0
SWING_MAX_INACTIVE_SEC = 900.0

SWING_MOC_TIMEOUT_MIN = 25.0
SWING_MOC_MAX_DRIFT_PCT = 0.0060
SWING_STALE_HOURS = 48.0
SWING_STALE_MIN_PNL_PCT = 0.0100
SWING_STALE_MAKER_WAIT_MIN = 15.0
SWING_CB_HALF_LOSSES = 2
SWING_CB_PAUSE_LOSSES = 3
SWING_CB_WEEKLY_DD_PAUSE = -0.0450
SWING_CB_COOLING_HOURS = 24.0
SL_MEMORY_RETENTION_HOURS = 168.0

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
    "DOGE": {"v2_symbol": "DOGEIDR", "indodax_key": "doge_idr", "kraken_pair": "XDGUSD",   "step_decimals": 0, "price_step": 1},
    "PEPE": {"v2_symbol": "PEPEIDR", "indodax_key": "pepe_idr", "kraken_pair": "PEPEUSD",  "step_decimals": 0, "price_step": 0.001}
}

STATE_FILE = "bot_state_tokocrypto.json"

INDODAX_API_KEY = os.getenv("INDODAX_API_KEY", os.getenv("TOKOCRYPTO_API_KEY", "")).strip()
INDODAX_SECRET_KEY = os.getenv("INDODAX_SECRET_KEY", os.getenv("TOKOCRYPTO_SECRET_KEY", "")).strip()
GOOGLE_SHEETS_WEBHOOK_URL = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"

# ==============================================================================
# BAGIAN 2: MANAJEMEN MEMORI POSISI, TRACKER RECOVERY & COOLDOWN SL
# ==============================================================================
def tanggal_wib_hari_ini():
    tz_wib = timezone(timedelta(hours=7))
    return datetime.now(tz_wib).strftime("%Y-%m-%d")

def minggu_iso_wib():
    tz_wib = timezone(timedelta(hours=7))
    now_wib = datetime.now(tz_wib)
    y, w, _ = now_wib.isocalendar()
    return f"{y}-W{w:02d}"

def muat_state_bot():
    tgl_skrg = tanggal_wib_hari_ini()
    minggu_skrg = minggu_iso_wib()
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            if state.get("last_reset_date") != tgl_skrg:
                state["realized_profit_today_idr"] = 0.0
                state["completed_trades_today"] = 0
                state["last_reset_date"] = tgl_skrg
            state.setdefault("loss_to_recover_idr", 0.0)
            state.setdefault("grid_cycle", None)
            state.setdefault("grid_experience_memory", [])
            state.setdefault("swing_positions", [])
            state.setdefault("swing_pending_entries", [])
            state.setdefault("swing_trade_history", [])
            state.setdefault("swing_circuit_breaker", {
                "consecutive_losses": 0,
                "half_size_active": False,
                "cooling_off_until": 0.0,
                "week_id": minggu_skrg,
                "weekly_pnl_idr": 0.0,
                "week_start_equity_idr": MAX_SWING_CAPITAL_IDR
            })
            if state["swing_circuit_breaker"].get("week_id") != minggu_skrg:
                state["swing_circuit_breaker"]["week_id"] = minggu_skrg
                state["swing_circuit_breaker"]["weekly_pnl_idr"] = 0.0
                state["swing_circuit_breaker"]["week_start_equity_idr"] = float(
                    state.get("budget_ledger", {}).get("swing_equity_idr", MAX_SWING_CAPITAL_IDR)
                )
            state.setdefault("budget_ledger", None)
            return state
        except Exception:
            pass
    return {
        "realized_profit_today_idr": 0.0,
        "completed_trades_today": 0,
        "loss_to_recover_idr": 0.0,
        "grid_cycle": None,
        "grid_experience_memory": [],
        "swing_positions": [],
        "swing_pending_entries": [],
        "swing_trade_history": [],
        "swing_circuit_breaker": {
            "consecutive_losses": 0,
            "half_size_active": False,
            "cooling_off_until": 0.0,
            "week_id": minggu_skrg,
            "weekly_pnl_idr": 0.0,
            "week_start_equity_idr": MAX_SWING_CAPITAL_IDR
        },
        "budget_ledger": None,
        "last_reset_date": tgl_skrg
    }

def simpan_state_bot(state):
    """Menyimpan state secara atomik (tulis ke .tmp lalu os.replace) agar memori Grid bebas korup."""
    state["last_reset_date"] = tanggal_wib_hari_ini()
    tmp_file = f"{STATE_FILE}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_file, STATE_FILE)

def catat_hasil_transaksi_ke_recovery(state, pnl_bersih_idr, coin=None, slot=None, pnl_exit_pct=None):
    state["realized_profit_today_idr"] = round(float(state.get("realized_profit_today_idr", 0.0)) + pnl_bersih_idr, 0)
    state["completed_trades_today"] = int(state.get("completed_trades_today", 0)) + 1
    defisit_lama = float(state.get("loss_to_recover_idr", 0.0))
    if pnl_bersih_idr < 0:
        state["loss_to_recover_idr"] = round(defisit_lama + abs(pnl_bersih_idr), 0)
    else:
        state["loss_to_recover_idr"] = round(max(0.0, defisit_lama - pnl_bersih_idr), 0)

def rekam_memori_siklus_grid(state, cycle, alasan_tutup, total_pnl_idr):
    if not cycle:
        return
    now_ts = time.time()
    batas_kadaluarsa = now_ts - (GRID_MEMORY_RETENTION_HOURS * 3600.0)
    tz_wib = timezone(timedelta(hours=7))
    waktu_str = datetime.now(tz_wib).strftime("%d/%m %H:%M")

    durasi_jam = round((now_ts - float(cycle.get("created_ts", now_ts))) / 3600.0, 2)
    memori_aktif = [
        m for m in state.get("grid_experience_memory", [])
        if float(m.get("ts", now_ts)) >= batas_kadaluarsa
    ]
    memori_aktif.append({
        "ts": now_ts,
        "waktu": waktu_str,
        "coin": cycle.get("coin", "?"),
        "alasan_tutup": alasan_tutup,
        "bounce_count": int(cycle.get("bounce_count", 0)),
        "completed_tiers_count": int(cycle.get("completed_tiers_count", 0)),
        "b3_ever_touched": bool(cycle.get("b3_ever_touched", False)),
        "durasi_jam": durasi_jam,
        "total_pnl_idr": round(float(total_pnl_idr), 0),
        "berhasil": float(total_pnl_idr) >= 0.0
    })
    state["grid_experience_memory"] = memori_aktif[-MAX_GRID_MEMORY_ITEMS:]

def hitung_penyesuaian_skor_memori_grid(state, coin):
    """
    Penilaian historis 7 hari yang anti-recency bias:
    - Bonus dibatasi (+4.0 maks) agar koin yang terlalu lama sideways tidak diprioritaskan
      menjelang fase breakout/ekspansi volatilitas.
    - Penalti fokus pada rugi aktual, invalidation cut, atau siklus yang nyangkut lama di b3.
    """
    now_ts = time.time()
    batas_kadaluarsa = now_ts - (GRID_MEMORY_RETENTION_HOURS * 3600.0)
    riwayat_koin = [
        m for m in state.get("grid_experience_memory", [])
        if float(m.get("ts", 0.0)) >= batas_kadaluarsa and m.get("coin") == coin
    ]
    if not riwayat_koin:
        return 0.0, "Belum ada riwayat 7H"

    delta_skor = 0.0
    jml_lancar = 0
    jml_berat = 0
    total_panen_7h = sum(int(m.get("bounce_count", 0)) for m in riwayat_koin)

    for m in riwayat_koin:
        pnl = float(m.get("total_pnl_idr", 0.0))
        sentuh_b3 = bool(m.get("b3_ever_touched", False))
        durasi_j = float(m.get("durasi_jam", 0.0))
        alasan = str(m.get("alasan_tutup", ""))

        if pnl < 0 or "INVALIDATION" in alasan:
            jml_berat += 1
            delta_skor -= 7.0
        elif sentuh_b3 and durasi_j >= 24.0:
            jml_berat += 1
            delta_skor -= 4.0
        elif pnl > 0:
            jml_lancar += 1
            delta_skor += 1.5

    # Redam bias recency: jika sudah terlalu banyak pantulan dalam 7 hari (>= 12x),
    # hindari mengejar range yang berpotensi segera jebol (volatility expansion)
    if total_panen_7h >= 12 and delta_skor > 0:
        delta_skor = min(delta_skor, 1.0)

    terakhir = riwayat_koin[-1]
    umur_terakhir = now_ts - float(terakhir.get("ts", 0.0))
    if "INVALIDATION" in str(terakhir.get("alasan_tutup", "")) and umur_terakhir < 14400.0:
        delta_skor -= 8.0
    elif terakhir.get("b3_ever_touched") and umur_terakhir < 7200.0:
        delta_skor -= 3.5

    delta_skor = round(max(-15.0, min(4.0, delta_skor)), 1)
    catatan = f"7H:{len(riwayat_koin)}x ({jml_lancar} lancar/{jml_berat} berat, Panen:{total_panen_7h}x, Adj:{delta_skor:+.1f})"
    return delta_skor, catatan

# ==============================================================================
# MODUL BUDGET VAULT: ISOLASI KEUANGAN GRID (100RB/LAPIS) vs MINI SWING vs SURPLUS
# ==============================================================================
def hitung_modal_terpakai_grid(state):
    """Menghitung total Rupiah yang sedang terikat di posisi/order Grid BTC."""
    cycle = state.get("grid_cycle")
    if not cycle:
        return 0.0, 0
    tiers = [t for t in cycle.get("tiers", []) if t.get("status") != "DONE"]
    used = 0.0
    for t in tiers:
        for lp in t.get("layers", {}).values():
            if lp.get("status") in ("WAIT_BUY", "HOLDING"):
                used += float(lp.get("capital_idr", 0.0))
    return round(used, 0), len(tiers)

def hitung_modal_terpakai_swing(state):
    """Menghitung total Rupiah yang sedang terikat di order/posisi Mini Swing Non-BTC."""
    used = 0.0
    for p in state.get("swing_pending_entries", []):
        used += float(p.get("capital_idr", 0.0))
    for pos in state.get("swing_positions", []):
        used += float(pos.get("remaining_capital_idr", pos.get("capital_idr", 0.0)))
    return round(used, 0)

def sinkronkan_dan_hitung_budget_vault(state, dompet_asli):
    """
    Pembukuan ketat 3 kantong:
    1. Jatah Grid: max(1, lapis_aktif) * Rp100rb.
    2. Jatah Mini Swing: max MAX_SWING_CAPITAL_IDR (berkurang saat kena SL, tidak ambil dana Grid).
    3. Surplus Cadangan: menampung kelebihan profit/deposit; HANYA dipakai saat:
       - buka lapis Grid baru (total dompet >= jatah Grid + jatah Swing + Rp100rb & surplus >= Rp100rb),
       - ATAU saat batas MAX_SWING_CAPITAL_IDR dinaikkan.
    """
    grid_used, grid_tiers_aktif = hitung_modal_terpakai_grid(state)
    swing_used = hitung_modal_terpakai_swing(state)
    grid_cap_aktif = max(1, grid_tiers_aktif) * GRID_BUDGET_PER_TIER_IDR

    idr_free_wallet = float(dompet_asli.get("idr_free", 0.0))
    total_ekuitas_dompet = round(idr_free_wallet + grid_used + swing_used, 0)

    ledger = state.get("budget_ledger")
    if not isinstance(ledger, dict):
        grid_eq = min(total_ekuitas_dompet, grid_cap_aktif)
        sisa_setelah_grid = max(0.0, total_ekuitas_dompet - grid_eq)
        swing_eq = min(sisa_setelah_grid, MAX_SWING_CAPITAL_IDR) if SWING_MODE_ENABLED else 0.0
        surplus = max(0.0, total_ekuitas_dompet - grid_eq - swing_eq)
        ledger = {
            "grid_equity_idr": round(grid_eq, 0),
            "swing_equity_idr": round(swing_eq, 0),
            "reserve_surplus_idr": round(surplus, 0),
            "last_swing_cap_setting": MAX_SWING_CAPITAL_IDR,
            "last_grid_tiers_count": grid_tiers_aktif,
            "last_wallet_idr_free": round(idr_free_wallet, 0),
            "last_sync_ts": time.time()
        }
        state["budget_ledger"] = ledger
    else:
        prev_swing_cap = float(ledger.get("last_swing_cap_setting", MAX_SWING_CAPITAL_IDR))
        if MAX_SWING_CAPITAL_IDR > prev_swing_cap:
            kebutuhan_naik = MAX_SWING_CAPITAL_IDR - prev_swing_cap
            tarik_surplus = min(float(ledger.get("reserve_surplus_idr", 0.0)), kebutuhan_naik)
            if tarik_surplus > 0:
                ledger["swing_equity_idr"] = round(float(ledger.get("swing_equity_idr", 0.0)) + tarik_surplus, 0)
                ledger["reserve_surplus_idr"] = round(float(ledger.get("reserve_surplus_idr", 0.0)) - tarik_surplus, 0)
        elif MAX_SWING_CAPITAL_IDR < prev_swing_cap:
            kelebihan_cap = max(0.0, float(ledger.get("swing_equity_idr", 0.0)) - MAX_SWING_CAPITAL_IDR)
            if kelebihan_cap > 0:
                swing_bebas_skrg = max(0.0, float(ledger.get("swing_equity_idr", 0.0)) - swing_used)
                kembalikan = min(kelebihan_cap, swing_bebas_skrg)
                ledger["swing_equity_idr"] = round(float(ledger.get("swing_equity_idr", 0.0)) - kembalikan, 0)
                ledger["reserve_surplus_idr"] = round(float(ledger.get("reserve_surplus_idr", 0.0)) + kembalikan, 0)
        ledger["last_swing_cap_setting"] = MAX_SWING_CAPITAL_IDR

        if float(ledger.get("grid_equity_idr", 0.0)) > grid_cap_aktif:
            lebih_g = float(ledger["grid_equity_idr"]) - grid_cap_aktif
            ledger["grid_equity_idr"] = round(grid_cap_aktif, 0)
            ledger["reserve_surplus_idr"] = round(float(ledger.get("reserve_surplus_idr", 0.0)) + lebih_g, 0)
        if float(ledger.get("swing_equity_idr", 0.0)) > MAX_SWING_CAPITAL_IDR:
            lebih_s = float(ledger["swing_equity_idr"]) - MAX_SWING_CAPITAL_IDR
            ledger["swing_equity_idr"] = round(MAX_SWING_CAPITAL_IDR, 0)
            ledger["reserve_surplus_idr"] = round(float(ledger.get("reserve_surplus_idr", 0.0)) + lebih_s, 0)

        grid_free_buku = max(0.0, float(ledger["grid_equity_idr"]) - grid_used)
        swing_free_buku = max(0.0, float(ledger["swing_equity_idr"]) - swing_used)
        surplus_buku = max(0.0, float(ledger["reserve_surplus_idr"]))
        total_free_buku = grid_free_buku + swing_free_buku + surplus_buku
        selisih_kas = round(idr_free_wallet - total_free_buku, 0)

        if selisih_kas > 100.0:
            sisa_tambahan = selisih_kas
            if float(ledger["grid_equity_idr"]) < grid_cap_aktif and ledger.get("last_grid_tiers_count", 0) == 0:
                isi_g = min(sisa_tambahan, grid_cap_aktif - float(ledger["grid_equity_idr"]))
                ledger["grid_equity_idr"] = round(float(ledger["grid_equity_idr"]) + isi_g, 0)
                sisa_tambahan -= isi_g
            ledger["reserve_surplus_idr"] = round(surplus_buku + sisa_tambahan, 0)
        elif selisih_kas < -100.0:
            kurang = abs(selisih_kas)
            pot_surplus = min(surplus_buku, kurang)
            ledger["reserve_surplus_idr"] = round(surplus_buku - pot_surplus, 0)
            kurang -= pot_surplus
            if kurang > 0:
                pot_g = min(grid_free_buku, kurang * 0.5)
                pot_s = min(swing_free_buku, kurang - pot_g)
                sisa_k = kurang - pot_g - pot_s
                if sisa_k > 0 and (grid_free_buku - pot_g) > 0:
                    extra_g = min(grid_free_buku - pot_g, sisa_k)
                    pot_g += extra_g
                    sisa_k -= extra_g
                if sisa_k > 0 and (swing_free_buku - pot_s) > 0:
                    pot_s += min(swing_free_buku - pot_s, sisa_k)
                ledger["grid_equity_idr"] = round(max(grid_used, float(ledger["grid_equity_idr"]) - pot_g), 0)
                ledger["swing_equity_idr"] = round(max(swing_used, float(ledger["swing_equity_idr"]) - pot_s), 0)

    grid_eq_final = float(ledger["grid_equity_idr"])
    swing_eq_final = float(ledger["swing_equity_idr"])
    surplus_final = max(0.0, float(ledger["reserve_surplus_idr"]))

    grid_free_final = round(max(0.0, min(idr_free_wallet, grid_eq_final - grid_used)), 0)
    swing_free_final = round(max(0.0, min(idr_free_wallet - grid_free_final, swing_eq_final - swing_used)), 0)

    ambang_total_lapis_baru = grid_cap_aktif + max(swing_eq_final, MAX_SWING_CAPITAL_IDR if SWING_MODE_ENABLED else 0.0) + GRID_BUDGET_PER_TIER_IDR
    boleh_buka_lapis_baru = bool(
        grid_tiers_aktif >= 1
        and total_ekuitas_dompet >= (ambang_total_lapis_baru * 0.98)
        and surplus_final >= (GRID_BUDGET_PER_TIER_IDR * 0.95)
        and idr_free_wallet >= (swing_free_final + grid_free_final + (GRID_BUDGET_PER_TIER_IDR * 0.95))
    )

    ledger["last_grid_tiers_count"] = grid_tiers_aktif
    ledger["last_wallet_idr_free"] = round(idr_free_wallet, 0)
    ledger["last_sync_ts"] = time.time()

    return {
        "total_ekuitas_dompet": total_ekuitas_dompet,
        "idr_free_wallet": round(idr_free_wallet, 0),
        "grid_tiers_aktif": grid_tiers_aktif,
        "grid_cap_aktif": grid_cap_aktif,
        "grid_equity_idr": grid_eq_final,
        "grid_used_idr": grid_used,
        "grid_free_idr": grid_free_final,
        "swing_cap_max": MAX_SWING_CAPITAL_IDR,
        "swing_equity_idr": swing_eq_final,
        "swing_used_idr": swing_used,
        "swing_free_idr": swing_free_final,
        "reserve_surplus_idr": surplus_final,
        "boleh_buka_lapis_baru": boleh_buka_lapis_baru,
        "ambang_total_lapis_baru": ambang_total_lapis_baru
    }

def catat_perubahan_ledger_grid(state, tiers_sebelum, profit_realized_sebelum):
    ledger = state.get("budget_ledger")
    if not isinstance(ledger, dict):
        return
    _, tiers_sesudah = hitung_modal_terpakai_grid(state)
    cycle = state.get("grid_cycle")
    profit_sesudah = float(cycle.get("realized_grid_profit_idr", 0.0)) if cycle else profit_realized_sebelum
    delta_profit = max(0.0, profit_sesudah - profit_realized_sebelum)

    if tiers_sesudah > tiers_sebelum and tiers_sebelum >= 1:
        tambah_lapis = (tiers_sesudah - tiers_sebelum) * GRID_BUDGET_PER_TIER_IDR
        ambil_surplus = min(float(ledger.get("reserve_surplus_idr", 0.0)), tambah_lapis)
        ledger["reserve_surplus_idr"] = round(float(ledger.get("reserve_surplus_idr", 0.0)) - ambil_surplus, 0)
        ledger["grid_equity_idr"] = round(float(ledger.get("grid_equity_idr", 0.0)) + ambil_surplus, 0)
    elif tiers_sesudah < tiers_sebelum:
        cap_baru = max(1, tiers_sesudah) * GRID_BUDGET_PER_TIER_IDR
        if float(ledger.get("grid_equity_idr", 0.0)) > cap_baru:
            kembalikan = float(ledger["grid_equity_idr"]) - cap_baru
            ledger["grid_equity_idr"] = round(cap_baru, 0)
            ledger["reserve_surplus_idr"] = round(float(ledger.get("reserve_surplus_idr", 0.0)) + kembalikan, 0)

    if delta_profit > 0:
        cap_skrg = max(1, tiers_sesudah) * GRID_BUDGET_PER_TIER_IDR
        eq_baru = float(ledger.get("grid_equity_idr", 0.0)) + delta_profit
        if eq_baru > cap_skrg:
            ledger["reserve_surplus_idr"] = round(float(ledger.get("reserve_surplus_idr", 0.0)) + (eq_baru - cap_skrg), 0)
            ledger["grid_equity_idr"] = round(cap_skrg, 0)
        else:
            ledger["grid_equity_idr"] = round(eq_baru, 0)

    ledger["last_grid_tiers_count"] = tiers_sesudah

def catat_pnl_ledger_swing(state, pnl_bersih_idr):
    ledger = state.get("budget_ledger")
    if isinstance(ledger, dict):
        eq_baru = max(0.0, float(ledger.get("swing_equity_idr", MAX_SWING_CAPITAL_IDR)) + float(pnl_bersih_idr))
        if eq_baru > MAX_SWING_CAPITAL_IDR:
            surplus_tambah = eq_baru - MAX_SWING_CAPITAL_IDR
            ledger["swing_equity_idr"] = round(MAX_SWING_CAPITAL_IDR, 0)
            ledger["reserve_surplus_idr"] = round(float(ledger.get("reserve_surplus_idr", 0.0)) + surplus_tambah, 0)
        else:
            ledger["swing_equity_idr"] = round(eq_baru, 0)

    cb = state.setdefault("swing_circuit_breaker", {})
    cb["weekly_pnl_idr"] = round(float(cb.get("weekly_pnl_idr", 0.0)) + float(pnl_bersih_idr), 0)
    if pnl_bersih_idr < 0:
        cb["consecutive_losses"] = int(cb.get("consecutive_losses", 0)) + 1
        if cb["consecutive_losses"] >= SWING_CB_HALF_LOSSES:
            cb["half_size_active"] = True
        if cb["consecutive_losses"] >= SWING_CB_PAUSE_LOSSES:
            cb["cooling_off_until"] = time.time() + (SWING_CB_COOLING_HOURS * 3600.0)
    else:
        cb["consecutive_losses"] = 0
        cb["half_size_active"] = False

    base_week_eq = max(1.0, float(cb.get("week_start_equity_idr", MAX_SWING_CAPITAL_IDR)))
    if (cb["weekly_pnl_idr"] / base_week_eq) <= SWING_CB_WEEKLY_DD_PAUSE:
        cb["cooling_off_until"] = max(float(cb.get("cooling_off_until", 0.0)), time.time() + (SWING_CB_COOLING_HOURS * 3600.0))

# ==============================================================================
# BAGIAN 3: KONEKSI RESMI INDODAX TRADE API V2 & EKSEKUSI ORDER AMAN
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

_ACTIVE_GRID_IDR_FREE_CAP = None  # Pengaman virtual saat mesin Grid berjalan (0 perubahan di kode Grid)

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
        kapasitas_lapis = int(dompet["idr_free"] // (GRID_CAPITAL_PER_LAYER_IDR * 3.0 * 0.95))
        print(
            f"✅ [AKUN INDODAX UID:{res.get('uid')} TERHUBUNG] Saldo IDR Bebas: Rp{dompet['idr_free']:,.0f} "
            f"(Cukup utk ~{kapasitas_lapis} Lapis baru) | IDR Antre Order: Rp{dompet['idr_locked']:,.0f}"
        )
    else:
        print(f"⚠️ [PERINGATAN CEK SALDO V2]: {res}")
    if _ACTIVE_GRID_IDR_FREE_CAP is not None:
        dompet["idr_free"] = min(dompet["idr_free"], float(_ACTIVE_GRID_IDR_FREE_CAP))
    return dompet

def bulatkan_harga_indodax(coin, harga_idr):
    step = WATCHLIST_COINS[coin].get("price_step", 1)
    return int(round(harga_idr / step) * step)

def format_qty_koin(coin, raw_qty):
    decimals = WATCHLIST_COINS[coin]["step_decimals"]
    factor = 10 ** decimals
    qty = math.floor(max(0.0, raw_qty) * factor) / factor
    return int(qty) if decimals == 0 else round(qty, decimals)

def hitung_kuantitas_koin(coin, nominal_idr, harga_idr):
    if harga_idr <= 0:
        return 0
    return format_qty_koin(coin, nominal_idr / harga_idr)

def eksekusi_order_indodax(coin, side_str, harga_idr, nominal_idr=0.0, qty_koin=0.0, order_type="LIMIT", time_in_force="GTC"):
    harga_bulat = bulatkan_harga_indodax(coin, harga_idr)
    qty = format_qty_koin(coin, qty_koin) if qty_koin > 0 else hitung_kuantitas_koin(coin, nominal_idr, harga_bulat)
    if qty <= 0:
        return {"code": -1, "msg": "Kuantitas order <= 0"}
    if not LIVE_TRADING_ENABLED:
        return {"simulasi": True, "orderId": f"SIM-{int(time.time() * 1000)}", "qty": qty, "price": harga_bulat}

    symbol = WATCHLIST_COINS[coin]["v2_symbol"]
    params = {
        "symbol": symbol,
        "side": side_str.upper(),
        "type": order_type.upper(),
        "quantity": str(qty)
    }
    if order_type.upper() == "LIMIT":
        params["timeInForce"] = str(time_in_force).upper()
        params["price"] = str(harga_bulat)

    res = panggil_indodax_v2("/api/v2/order", method="POST", params=params)
    print(f"👉 [INDODAX V2 {side_str.upper()} {order_type.upper()} {params.get('timeInForce', '')}] {symbol} | Qty={qty} @ Rp{harga_bulat:,.0f} -> {res}")
    if isinstance(res, dict):
        res["qty"] = qty
    return res

def apakah_order_sukses(res):
    return isinstance(res, dict) and ("orderId" in res or res.get("simulasi") is True)

def pasang_order_grid_aman(coin, side_str, target_price_idr, qty_koin, info_pasar=None, paksa_gtc_fallback=True):
    """
    Eksekutor Limit Order Grid anti-gagal MOC:
    1. Untuk SELL: jika harga Ask/Bid pasar sudah >= target TP, coba MOC di harga Ask agar tetap Maker
       & mendapat harga lebih tinggi; jika MOC tetap ditolak, fallback ke LIMIT GTC (tidak pernah yatim).
    2. Untuk BUY: jika target beli >= harga Ask pasar, turunkan ke Bid agar tetap Maker (harga lebih murah);
       jika MOC tetap ditolak dan paksa_gtc_fallback=True, fallback ke LIMIT GTC.
    Return: (sukses, res_dict, harga_terpasang, tif_dipakai)
    """
    side_u = side_str.upper()
    harga_target = bulatkan_harga_indodax(coin, target_price_idr)
    harga_bid = float(info_pasar.get("harga_bid", 0.0)) if info_pasar else 0.0
    harga_ask = float(info_pasar.get("harga_ask", 0.0)) if info_pasar else 0.0
    step = WATCHLIST_COINS[coin].get("price_step", 1)

    harga_coba_moc = harga_target
    if side_u == "SELL" and harga_bid > 0 and harga_target <= harga_bid:
        # Harga sudah melesat melewati target TP -> antre di Ask (atau Bid+1 step) agar tetap Maker & untung lebih besar
        harga_coba_moc = bulatkan_harga_indodax(coin, max(harga_target, harga_ask if harga_ask > harga_bid else harga_bid + step))
    elif side_u == "BUY" and harga_ask > 0 and harga_target >= harga_ask:
        # Harga sudah turun melewati target beli -> antre di Bid (atau Ask-1 step) agar tetap Maker & lebih murah
        harga_coba_moc = bulatkan_harga_indodax(coin, min(harga_target, harga_bid if harga_bid < harga_ask else harga_ask - step))

    tif_utama = str(GRID_LIMIT_TIF).upper()
    res_utama = eksekusi_order_indodax(
        coin, side_u, harga_coba_moc, qty_koin=qty_koin, order_type="LIMIT", time_in_force=tif_utama
    )
    if apakah_order_sukses(res_utama):
        return True, res_utama, harga_coba_moc, tif_utama

    if paksa_gtc_fallback and tif_utama != "GTC":
        # Untuk SELL yang sudah melewati target TP, fallback GTC di max(target, Bid) agar langsung terisi profit
        harga_gtc = bulatkan_harga_indodax(coin, max(harga_target, harga_bid)) if (side_u == "SELL" and harga_bid > 0) else harga_coba_moc
        print(f"⚠️ [FALLBACK MOC->GTC] {side_u} {coin} MOC gagal, dialihkan ke LIMIT GTC @ Rp{harga_gtc:,.0f}...")
        res_gtc = eksekusi_order_indodax(
            coin, side_u, harga_gtc, qty_koin=qty_koin, order_type="LIMIT", time_in_force="GTC"
        )
        if apakah_order_sukses(res_gtc):
            return True, res_gtc, harga_gtc, "GTC"
        return False, res_gtc, harga_gtc, "GTC"

    return False, res_utama, harga_coba_moc, tif_utama

def batalkan_order_indodax(coin, order_id):
    if not LIVE_TRADING_ENABLED or not order_id or str(order_id).startswith(("SIM-", "ERR-", "HOLD-")):
        return True, {"simulasi": True}
    symbol = WATCHLIST_COINS[coin]["v2_symbol"]
    params = {"symbol": symbol, "orderId": str(order_id)}
    res = panggil_indodax_v2("/api/v2/order", method="DELETE", params=params)
    print(f"🗑️ [INDODAX V2 CANCEL] {symbol} OrderID={order_id} -> {res}")
    sukses = isinstance(res, dict) and ("orderId" in res or str(res.get("status", "")).upper() == "CANCELED")
    return sukses, res

def cek_status_order_indodax(coin, order_id):
    """Mengecek status asli order di Indodax: NEW, PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED, REJECTED, NOT_FOUND, UNKNOWN."""
    if not LIVE_TRADING_ENABLED or not order_id or str(order_id).startswith(("SIM-", "ERR-", "HOLD-")):
        return "UNKNOWN", {}
    symbol = WATCHLIST_COINS[coin]["v2_symbol"]
    res = panggil_indodax_v2("/api/v2/order", method="GET", params={"symbol": symbol, "orderId": str(order_id)})
    if isinstance(res, dict):
        if "status" in res:
            return str(res["status"]).upper(), res
        msg_err = str(res.get("msg", "")).lower()
        code_err = int(res.get("code", 0) or 0)
        if code_err in (-2013, 404) or "not found" in msg_err or "does not exist" in msg_err:
            return "NOT_FOUND", res
    return "UNKNOWN", res if isinstance(res, dict) else {}

def ekstrak_eksekusi_order(detail_ord, fallback_price=0.0):
    """Membaca kuantitas terisi aktual (executedQty) dan harga rata-rata eksekusi dari respons order Indodax V2."""
    if not isinstance(detail_ord, dict):
        return 0.0, fallback_price
    exec_qty = float(detail_ord.get("executedQty", detail_ord.get("filledQty", 0)) or 0)
    cum_quote = float(detail_ord.get("cummulativeQuoteQty", detail_ord.get("executedQuoteQty", 0)) or 0)
    ord_price = float(detail_ord.get("price", 0) or 0)
    if exec_qty > 0 and cum_quote > 0:
        avg_price = cum_quote / exec_qty
    elif ord_price > 0:
        avg_price = ord_price
    else:
        avg_price = fallback_price
    return exec_qty, avg_price

def ambil_open_orders_indodax(coin):
    if not LIVE_TRADING_ENABLED or coin not in WATCHLIST_COINS:
        return False, []
    symbol = WATCHLIST_COINS[coin]["v2_symbol"]
    res = panggil_indodax_v2("/api/v2/openOrders", method="GET", params={"symbol": symbol})
    if isinstance(res, list):
        return True, res
    if isinstance(res, dict) and isinstance(res.get("data"), list):
        return True, res["data"]
    return False, []

def ambil_trade_terakhir_indodax(coin, side_filter=None, limit=10):
    if not LIVE_TRADING_ENABLED or coin not in WATCHLIST_COINS:
        return []
    symbol = WATCHLIST_COINS[coin]["v2_symbol"]
    res = panggil_indodax_v2("/api/v2/myTrades", method="GET", params={"symbol": symbol, "limit": limit})
    daftar = res if isinstance(res, list) else (res.get("data", []) if isinstance(res, dict) and isinstance(res.get("data"), list) else [])
    hasil = []
    for t in daftar:
        if not isinstance(t, dict):
            continue
        is_buyer = t.get("isBuyer")
        side_raw = str(t.get("side", "")).upper()
        side_trade = "BUY" if (is_buyer is True or side_raw == "BUY") else ("SELL" if (is_buyer is False or side_raw == "SELL") else "")
        if side_filter and side_trade != side_filter.upper():
            continue
        ts_raw = float(t.get("time", t.get("timestamp", 0)) or 0)
        ts_sec = ts_raw / 1000.0 if ts_raw > 1e12 else ts_raw
        harga_t = float(t.get("price", 0) or 0)
        qty_t = float(t.get("qty", t.get("quantity", 0)) or 0)
        if harga_t > 0:
            hasil.append({"side": side_trade, "price": harga_t, "qty": qty_t, "ts": ts_sec})
    hasil.sort(key=lambda x: x["ts"], reverse=True)
    return hasil

def eksekusi_jual_terverifikasi(coin, harga_limit_idr, qty_dimiliki, prioritas_market=False):
    if prioritas_market:
        res_m = eksekusi_order_indodax(coin, "SELL", harga_limit_idr, qty_koin=qty_dimiliki, order_type="MARKET")
        if apakah_order_sukses(res_m):
            return True, harga_limit_idr, res_m

    res_l = eksekusi_order_indodax(coin, "SELL", harga_limit_idr, qty_koin=qty_dimiliki, order_type="LIMIT")
    if not apakah_order_sukses(res_l):
        return False, harga_limit_idr, res_l

    if not LIVE_TRADING_ENABLED:
        return True, harga_limit_idr, res_l

    oid = str(res_l.get("orderId", ""))
    time.sleep(2.0)
    status_ord, detail_ord = cek_status_order_indodax(coin, oid)
    if status_ord == "FILLED":
        _, harga_aktual = ekstrak_eksekusi_order(detail_ord, fallback_price=harga_limit_idr)
        return True, harga_aktual, res_l

    if status_ord in ("NEW", "PARTIALLY_FILLED"):
        print(f"⚠️ [ANTI-NYANGKUT] Limit Sell {coin} #{oid} masih {status_ord}, dialihkan ke MARKET SELL...")
        batalkan_order_indodax(coin, oid)
        time.sleep(1.0)
        dompet_cek = ambil_saldo_lengkap_indodax()
        sisa_qty = format_qty_koin(coin, dompet_cek["coins_free"].get(coin, 0.0))
        if sisa_qty <= 0:
            return True, harga_limit_idr, res_l
        res_m2 = eksekusi_order_indodax(coin, "SELL", harga_limit_idr, qty_koin=sisa_qty, order_type="MARKET")
        if apakah_order_sukses(res_m2):
            return True, harga_limit_idr, res_m2
        return False, harga_limit_idr, res_m2

    return True, harga_limit_idr, res_l

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

# ==============================================================================
# HELPER EKSEKUSI & MIKROSTRUKTUR INDODAX KHUSUS MINI SWING
# ==============================================================================
_CACHE_PAIRS_INDODAX = {"ts": 0.0, "data": {}}

def ambil_metadata_pairs_indodax():
    """Membaca /api/pairs & /api/price_increments (cache 1 jam) untuk tick/lot & flag maintenance."""
    now_ts = time.time()
    if _CACHE_PAIRS_INDODAX["data"] and (now_ts - _CACHE_PAIRS_INDODAX["ts"]) < 3600.0:
        return _CACHE_PAIRS_INDODAX["data"]

    meta = {}
    try:
        req1 = urllib.request.Request("https://indodax.com/api/pairs", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req1, timeout=10) as r1:
            daftar = json.loads(r1.read().decode())
        req2 = urllib.request.Request("https://indodax.com/api/price_increments", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req2, timeout=10) as r2:
            inc_map = json.loads(r2.read().decode()).get("increments", {})

        for item in daftar if isinstance(daftar, list) else []:
            ticker_id = str(item.get("ticker_id", "")).lower()
            sym_v2 = str(item.get("id", "")).upper()
            p_inc = float(inc_map.get(ticker_id, item.get("price_increment", 0)) or 0)
            q_inc = float(item.get("quantity_increment", 0) or 0)
            meta[sym_v2] = {
                "ticker_id": ticker_id,
                "price_increment": p_inc,
                "quantity_increment": q_inc,
                "trade_min_base_currency": float(item.get("trade_min_base_currency", MIN_LIMIT_ORDER_INDODAX_IDR) or MIN_LIMIT_ORDER_INDODAX_IDR),
                "is_maintenance": int(item.get("is_maintenance", 0) or 0),
                "is_market_suspended": int(item.get("is_market_suspended", 0) or 0),
            }
        _CACHE_PAIRS_INDODAX["ts"] = now_ts
        _CACHE_PAIRS_INDODAX["data"] = meta
    except Exception as e:
        print(f"⚠️ [SWING META PAIRS] Fallback ke config lokal: {e}")
    return meta

def bulatkan_harga_swing(coin, harga_idr, pairs_meta=None):
    """Floor pembulatan harga mengikuti price_increment resmi Indodax (aman utk harga < Rp1 seperti PEPE)."""
    sym = WATCHLIST_COINS[coin]["v2_symbol"]
    inc = 0.0
    if pairs_meta and sym in pairs_meta:
        inc = float(pairs_meta[sym].get("price_increment", 0.0))
    if inc <= 0:
        inc = float(WATCHLIST_COINS[coin].get("price_step", 1))
    val = math.floor(harga_idr / inc) * inc
    if inc >= 1:
        return int(round(val))
    dec = max(0, int(round(-math.log10(inc))))
    return round(val, dec)

def format_qty_swing(coin, raw_qty, pairs_meta=None):
    """Floor kuantitas koin mengikuti quantity_increment resmi Indodax."""
    sym = WATCHLIST_COINS[coin]["v2_symbol"]
    q_inc = 0.0
    if pairs_meta and sym in pairs_meta:
        q_inc = float(pairs_meta[sym].get("quantity_increment", 0.0))
    if q_inc > 0:
        val = math.floor(max(0.0, raw_qty) / q_inc) * q_inc
        if q_inc >= 1:
            return int(round(val))
        dec = max(0, int(round(-math.log10(q_inc))))
        return round(val, dec)
    return format_qty_koin(coin, raw_qty)

def cek_mikrostruktur_orderbook_indodax(coin, order_size_idr=50000.0):
    """
    Mengambil order book (/api/depth) & trade terakhir (/api/trades) langsung dari Indodax:
    - Spread% <= 0.15%
    - OBP (±0.5% dari mid-price) > 0.52
    - Kedalaman ±2% >= Rp800jt ATAU top-5 bid/ask >= 10x ukuran order bot
    - Aktivitas transaksi terbaru <= 15 menit (anti koin tidur)
    """
    pair_key = WATCHLIST_COINS[coin]["indodax_key"].replace("_", "")
    hasil = {
        "ok": False, "best_bid": 0.0, "best_ask": 0.0, "spread_pct": 1.0,
        "obp": 0.5, "depth_2pct_idr": 0.0, "top5_idr": 0.0, "last_trade_age_sec": 99999.0, "alasan": ""
    }
    try:
        url_d = f"https://indodax.com/api/depth/{pair_key}"
        req_d = urllib.request.Request(url_d, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_d, timeout=10) as rd:
            depth = json.loads(rd.read().decode())
        buys = depth.get("buy", [])
        sells = depth.get("sell", [])
        if not buys or not sells:
            hasil["alasan"] = "Order book kosong"
            return hasil

        best_bid = float(buys[0][0])
        best_ask = float(sells[0][0])
        mid = (best_bid + best_ask) / 2.0
        spread_pct = (best_ask - best_bid) / mid if mid > 0 else 1.0

        bid_05, ask_05 = 0.0, 0.0
        depth_2pct = 0.0
        top5_bid = sum(float(p) * float(q) for p, q in buys[:5])
        top5_ask = sum(float(p) * float(q) for p, q in sells[:5])

        for p_s, q_s in buys:
            p, q = float(p_s), float(q_s)
            val = p * q
            if p >= mid * 0.995:
                bid_05 += val
            if p >= mid * 0.980:
                depth_2pct += val
        for p_s, q_s in sells:
            p, q = float(p_s), float(q_s)
            val = p * q
            if p <= mid * 1.005:
                ask_05 += val
            if p <= mid * 1.020:
                depth_2pct += val

        obp = bid_05 / max(1e-9, bid_05 + ask_05)

        # Cek aktivitas transaksi terakhir (anti-inactive 15 menit)
        url_t = f"https://indodax.com/api/trades/{pair_key}"
        req_t = urllib.request.Request(url_t, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_t, timeout=10) as rt:
            trades = json.loads(rt.read().decode())
        age_sec = 99999.0
        if isinstance(trades, list) and trades:
            ts_last = float(trades[0].get("date", 0) or 0)
            age_sec = max(0.0, time.time() - ts_last)

        depth_ok = (depth_2pct >= SWING_MIN_DEPTH_2PCT_IDR) or (min(top5_bid, top5_ask) >= (order_size_idr * 10.0))
        spread_ok = spread_pct <= SWING_MAX_SPREAD_PCT
        active_ok = age_sec <= SWING_MAX_INACTIVE_SEC
        obp_ok = obp > SWING_MIN_OBP

        hasil.update({
            "ok": bool(depth_ok and spread_ok and active_ok and obp_ok),
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": round(spread_pct, 5),
            "obp": round(obp, 4),
            "depth_2pct_idr": round(depth_2pct, 0),
            "top5_idr": round(min(top5_bid, top5_ask), 0),
            "last_trade_age_sec": round(age_sec, 1),
            "alasan": (
                "OK" if (depth_ok and spread_ok and active_ok and obp_ok) else
                f"Spread:{spread_pct*100:.2f}% OBP:{obp:.2f} Depth2%:Rp{depth_2pct:,.0f} Idle:{age_sec:.0f}s"
            )
        })
    except Exception as e:
        hasil["alasan"] = f"Err OB: {str(e)[:40]}"
    return hasil

def eksekusi_order_swing_moc(coin, side_str, harga_idr, qty_koin, pairs_meta=None, order_type="LIMIT", tif="MOC"):
    """Kirim order Trade API 2.0 dengan Maker-Or-Cancel (MOC), STP=TAKER, dan newClientOrderId unik."""
    harga_bulat = bulatkan_harga_swing(coin, harga_idr, pairs_meta)
    qty = format_qty_swing(coin, qty_koin, pairs_meta)
    if qty <= 0:
        return {"code": -1, "msg": "Kuantitas swing <= 0"}
    cid = f"msw-{coin.lower()}-{int(time.time() * 1000)}"
    if not LIVE_TRADING_ENABLED:
        return {"simulasi": True, "orderId": f"SIM-MSW-{int(time.time() * 1000)}", "qty": qty, "price": harga_bulat, "clientOrderId": cid}

    symbol = WATCHLIST_COINS[coin]["v2_symbol"]
    params = {
        "symbol": symbol,
        "side": side_str.upper(),
        "type": order_type.upper(),
        "quantity": str(qty),
        "newClientOrderId": cid,
        "selfTradePreventionMode": "TAKER"
    }
    if order_type.upper() == "LIMIT":
        params["timeInForce"] = str(tif).upper()
        params["price"] = str(harga_bulat)

    res = panggil_indodax_v2("/api/v2/order", method="POST", params=params)
    print(f"🎯 [SWING {side_str.upper()} {order_type.upper()} {tif}] {symbol} | Qty={qty} @ Rp{harga_bulat:,} -> {res}")
    if isinstance(res, dict):
        res["qty"] = qty
    return res

def eksekusi_jual_darurat_swing(coin, best_bid, qty_jual, pairs_meta=None):
    """
    Protokol Virtual SL Guardian + Anti-Dust:
    1. Aggressive Limit Sell (GTC) di Best_Bid * 0.9985 selama 3 detik.
    2. Jika belum terisi penuh, batalkan sisa lalu sapu SELURUH coins_free aktual lewat MARKET sell.
    Return: (sukses, qty_terjual_aktual, avg_price_aktual, res_dict)
    """
    harga_agresif = bulatkan_harga_swing(coin, best_bid * 0.9985, pairs_meta)
    qty_fmt = format_qty_swing(coin, qty_jual, pairs_meta)
    if qty_fmt <= 0:
        return False, 0.0, best_bid, {"msg": "Qty 0"}

    res_lim = eksekusi_order_swing_moc(coin, "SELL", harga_agresif, qty_fmt, pairs_meta=pairs_meta, order_type="LIMIT", tif="GTC")
    if not LIVE_TRADING_ENABLED:
        return True, qty_fmt, harga_agresif, res_lim

    qty_terjual_total = 0.0
    nilai_terjual_total = 0.0

    if apakah_order_sukses(res_lim):
        oid = str(res_lim.get("orderId"))
        time.sleep(3.0)
        st, det = cek_status_order_indodax(coin, oid)
        ex_q1, avg_p1 = ekstrak_eksekusi_order(det, fallback_price=harga_agresif)
        if st == "FILLED":
            q_done = ex_q1 if ex_q1 > 0 else qty_fmt
            return True, q_done, avg_p1, res_lim

        batalkan_order_indodax(coin, oid)
        time.sleep(1.0)
        _, det_after = cek_status_order_indodax(coin, oid)
        ex_q1, avg_p1 = ekstrak_eksekusi_order(det_after, fallback_price=harga_agresif)
        if ex_q1 > 0:
            qty_terjual_total += ex_q1
            nilai_terjual_total += (ex_q1 * avg_p1)

        # Baca seluruh saldo bebas aktual (termasuk dust) untuk disapu habis
        dompet_cek = ambil_saldo_lengkap_indodax()
        sisa_free = float(dompet_cek["coins_free"].get(coin, 0.0))
        sisa_q = format_qty_swing(coin, sisa_free, pairs_meta)
        if sisa_q <= 0 or (sisa_q * best_bid) < MIN_LIMIT_ORDER_INDODAX_IDR:
            if qty_terjual_total > 0:
                return True, qty_terjual_total, (nilai_terjual_total / qty_terjual_total), res_lim
            return False, 0.0, best_bid, det_after

        res_mkt = eksekusi_order_swing_moc(coin, "SELL", best_bid, sisa_q, pairs_meta=pairs_meta, order_type="MARKET", tif="")
        if apakah_order_sukses(res_mkt):
            time.sleep(1.5)
            _, det_m = cek_status_order_indodax(coin, str(res_mkt.get("orderId", "")))
            ex_q2, avg_p2 = ekstrak_eksekusi_order(det_m, fallback_price=best_bid)
            q_m = ex_q2 if ex_q2 > 0 else sisa_q
            qty_terjual_total += q_m
            nilai_terjual_total += (q_m * avg_p2)
            return True, qty_terjual_total, (nilai_terjual_total / max(1e-12, qty_terjual_total)), res_mkt
        if qty_terjual_total > 0:
            return True, qty_terjual_total, (nilai_terjual_total / qty_terjual_total), res_mkt
        return False, 0.0, best_bid, res_mkt

    res_mkt = eksekusi_order_swing_moc(coin, "SELL", best_bid, qty_fmt, pairs_meta=pairs_meta, order_type="MARKET", tif="")
    if apakah_order_sukses(res_mkt):
        time.sleep(1.5)
        _, det_m = cek_status_order_indodax(coin, str(res_mkt.get("orderId", "")))
        ex_q, avg_p = ekstrak_eksekusi_order(det_m, fallback_price=best_bid)
        return True, (ex_q if ex_q > 0 else qty_fmt), avg_p, res_mkt
    return False, 0.0, best_bid, res_mkt

# ==============================================================================
# BAGIAN 4: REKONSILIASI DOMPET INDODAX (MODE SCALPING & MODE GRID)
# ==============================================================================
def rekonsiliasi_grid_dengan_indodax(state, dompet, harga_idr_map):
    """
    Rekonsiliasi 2-arah khusus Mode Grid (Single Source of Truth = Indodax):
    1. Memastikan tidak ada posisi HOLDING hantu jika koin sudah habis terjual manual di aplikasi.
    2. Mengaitkan ulang Open Order SELL yang masih hidup jika sell_oid di memori kosong.
    3. Memberi peringatan jika ada koin yatim di dompet saat tidak ada siklus Grid aktif.
    """
    log_sync = []
    if not dompet.get("terhubung"):
        return state, log_sync

    cycle = state.get("grid_cycle")
    if not cycle:
        for c_cek in GRID_ALLOWED_COINS:
            qty_tot = format_qty_koin(c_cek, dompet["coins_free"].get(c_cek, 0.0) + dompet["coins_locked"].get(c_cek, 0.0))
            harga_c = harga_idr_map.get(c_cek, {}).get("last", 0.0)
            if qty_tot * harga_c >= MIN_LIMIT_ORDER_INDODAX_IDR:
                log_sync.append(
                    f"⚠️ [SYNC GRID PERINGATAN] Terdeteksi koin {c_cek} (Qty:{qty_tot} ~Rp{qty_tot*harga_c:,.0f}) "
                    f"di dompet Indodax tanpa siklus Grid aktif. Cek aplikasi Indodax agar tidak bentrok modal."
                )
        return state, log_sync

    # Pastikan format multi-tier sebelum rekonsiliasi
    if "tiers" not in cycle and "layers" in cycle:
        cycle["tiers"] = [{
            "tier_no": 1,
            "mode_4h": "HIJAU",
            "step_pct": GRID_STEP_GREEN_PCT,
            "created_ts": cycle.get("created_ts", time.time()),
            "status": "ACTIVE",
            "layers": cycle.pop("layers")
        }]
    cycle.setdefault("completed_tiers", [])
    cycle.setdefault("completed_tiers_count", 0)

    coin = cycle["coin"]
    harga_skrg = harga_idr_map.get(coin, {}).get("last", 0.0)
    k_free = dompet["coins_free"].get(coin, 0.0)
    k_locked = dompet["coins_locked"].get(coin, 0.0)
    total_qty_dompet = format_qty_koin(coin, k_free + k_locked)
    nilai_dompet_idr = total_qty_dompet * harga_skrg

    ok_oo, daftar_oo = ambil_open_orders_indodax(coin)
    open_sell_orders = [o for o in daftar_oo if str(o.get("side", "")).upper() == "SELL"] if ok_oo else []
    terpakai_sell_oids = {
        str(lp.get("sell_oid"))
        for t in cycle.get("tiers", [])
        for lp in t["layers"].values()
        if lp.get("sell_oid")
    }

    # 1. Kaitkan Open Order SELL yang belum tercatat di state (anti-duplikat TP)
    for t in cycle.get("tiers", []):
        for nama_lp, lp in t["layers"].items():
            if lp["status"] == "HOLDING" and not lp.get("sell_oid") and open_sell_orders:
                for oo in open_sell_orders:
                    oid_oo = str(oo.get("orderId", ""))
                    if oid_oo and oid_oo not in terpakai_sell_oids:
                        harga_oo = float(oo.get("price", 0) or 0)
                        if harga_oo > 0 and abs(harga_oo - float(lp["tp_price"])) / max(1.0, float(lp["tp_price"])) <= 0.015:
                            lp["sell_oid"] = oid_oo
                            lp["tp_price"] = bulatkan_harga_indodax(coin, harga_oo)
                            terpakai_sell_oids.add(oid_oo)
                            log_sync.append(
                                f"🔗 [SYNC GRID KAITKAN TP] L{t['tier_no']} {nama_lp.upper()} {coin} dikaitkan ke Open Order SELL #{oid_oo} @ Rp{lp['tp_price']:,.0f}."
                            )
                            break

    # 2. Deteksi jika seluruh koin di dompet sudah habis (< Rp5.000) sementara ada lapisan HOLDING tanpa sell_oid
    ada_holding = any(lp["status"] == "HOLDING" for t in cycle.get("tiers", []) for lp in t["layers"].values())
    if ada_holding and nilai_dompet_idr < 5000.0 and (not open_sell_orders):
        # Biarkan lapisan yang punya sell_oid dicek dulu di kelola_siklus_grid_3_lapis (siapa tahu baru FILLED TP).
        # Hanya bersihkan lapisan HOLDING yang tidak punya sell_oid sama sekali & saldonya 0 di dompet.
        for t in cycle.get("tiers", []):
            for nama_lp, lp in t["layers"].items():
                if lp["status"] == "HOLDING" and not lp.get("sell_oid"):
                    trades_jual = [
                        tr for tr in ambil_trade_terakhir_indodax(coin, side_filter="SELL", limit=5)
                        if tr["ts"] >= float(t.get("created_ts", 0)) - 120.0
                    ]
                    if trades_jual:
                        harga_laku = trades_jual[0]["price"]
                        net_pct = ((harga_laku - float(lp["buy_price"])) / max(1.0, float(lp["buy_price"]))) - FEE_ROUNDTRIP_MAKER_PCT
                        pnl_idr = round(float(lp["capital_idr"]) * net_pct, 0)
                        cycle["realized_grid_profit_idr"] = round(float(cycle.get("realized_grid_profit_idr", 0.0)) + pnl_idr, 0)
                        catat_hasil_transaksi_ke_recovery(state, pnl_idr, coin, slot={"coin": coin, "style": f"GRID_L{t['tier_no']}_{nama_lp.upper()}", "capital_idr": lp["capital_idr"]}, pnl_exit_pct=net_pct)
                        log_sync.append(
                            f"🔄 [SYNC GRID JUAL MANUAL] L{t['tier_no']} {nama_lp.upper()} {coin} terjual di luar bot @ Rp{harga_laku:,.0f} (PnL: Rp{pnl_idr:+,.0f})."
                        )
                    else:
                        log_sync.append(
                            f"🧹 [SYNC GRID BERSIHKAN HANTU] L{t['tier_no']} {nama_lp.upper()} {coin} tidak ada di dompet (Saldo: 0), status ditutup."
                        )
                    lp["status"] = "DONE"
                    lp["qty"] = 0.0

    return state, log_sync

def rekonsiliasi_swing_dengan_indodax(state, dompet, harga_idr_map):
    """Rekonsiliasi 2-arah khusus Mini Swing (Non-BTC) terhadap dompet & open orders Indodax."""
    log_sync = []
    if not dompet.get("terhubung") or not SWING_MODE_ENABLED:
        return state, log_sync

    # 1. Bersihkan pending entry yang sudah tidak ada di Indodax & koin tidak masuk dompet
    pending_valid = []
    for p in state.get("swing_pending_entries", []):
        coin = p["coin"]
        oid = p.get("buy_oid")
        st, det = cek_status_order_indodax(coin, oid)
        k_tot = dompet["coins_free"].get(coin, 0.0) + dompet["coins_locked"].get(coin, 0.0)
        harga = harga_idr_map.get(coin, {}).get("last", p["entry_price_idr"])
        if st in ("CANCELED", "EXPIRED", "REJECTED", "NOT_FOUND") and (k_tot * harga) < 5000.0:
            log_sync.append(f"🧹 [SYNC SWING] Pending MOC {coin} #{oid} berstatus {st}, dibersihkan.")
            continue
        pending_valid.append(p)
    state["swing_pending_entries"] = pending_valid

    # 2. Pastikan posisi aktif Mini Swing sinkron dengan saldo koin nyata di dompet
    pos_valid = []
    for pos in state.get("swing_positions", []):
        coin = pos["coin"]
        harga = harga_idr_map.get(coin, {}).get("last", pos["entry_price_idr"])
        k_free = dompet["coins_free"].get(coin, 0.0)
        k_locked = dompet["coins_locked"].get(coin, 0.0)
        k_tot = format_qty_koin(coin, k_free + k_locked)
        nilai_idr = k_tot * harga

        if nilai_idr < 5000.0 and not pos.get("tp1_oid") and not pos.get("tp2_oid"):
            trades_jual = [
                t for t in ambil_trade_terakhir_indodax(coin, side_filter="SELL", limit=5)
                if t["ts"] >= float(pos.get("filled_ts", 0.0)) - 120.0
            ]
            if trades_jual:
                p_laku = trades_jual[0]["price"]
                pnl_pct = ((1.0 - SWING_FEE_BUY_MAKER) * (p_laku / pos["entry_price_idr"]) * (1.0 - SWING_FEE_SELL_MAKER)) - 1.0
                pnl_idr = round(float(pos.get("remaining_capital_idr", pos["capital_idr"])) * pnl_pct, 0)
                catat_pnl_ledger_swing(state, pnl_idr)
                catat_hasil_transaksi_ke_recovery(state, pnl_idr, coin)
                log_sync.append(f"🔄 [SYNC SWING JUAL MANUAL] {coin} terjual @ Rp{p_laku:,} (PnL: Rp{pnl_idr:+,.0f}).")
            else:
                log_sync.append(f"🧹 [SYNC SWING] Posisi hantu {coin} dihapus (Saldo: 0).")
            continue
        pos_valid.append(pos)
    state["swing_positions"] = pos_valid
    return state, log_sync

# ==============================================================================
# BAGIAN 5: NATIVE INDODAX OHLC (RSI WILDER + ANTI-INCOMPLETE CANDLE) & GEMINI
# ==============================================================================
def hitung_rsi(closes_list, periode=14):
    """Menghitung RSI standar Wilder's Smoothing (RMA) sesuai TradingView/Indodax."""
    if len(closes_list) <= periode:
        return 50.0
    deltas = [closes_list[i] - closes_list[i - 1] for i in range(1, len(closes_list))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_gain = sum(gains[:periode]) / float(periode)
    avg_loss = sum(losses[:periode]) / float(periode)

    for i in range(periode, len(deltas)):
        avg_gain = ((avg_gain * (periode - 1)) + gains[i]) / float(periode)
        avg_loss = ((avg_loss * (periode - 1)) + losses[i]) / float(periode)

    if avg_loss <= 1e-12:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def hitung_ema_series(closes_list, periode):
    if not closes_list:
        return []
    if len(closes_list) < periode:
        return [sum(closes_list) / float(len(closes_list))] * len(closes_list)
    k = 2.0 / (periode + 1.0)
    ema_vals = [sum(closes_list[:periode]) / float(periode)]
    for harga in closes_list[periode:]:
        ema_vals.append((harga * k) + (ema_vals[-1] * (1.0 - k)))
    return ema_vals

def hitung_atr_pct(closes, highs, lows, periode=14):
    """Menghitung ATR(14)% standar profesional menggunakan Wilder's Smoothing (RMA, alpha=1/N)."""
    if len(closes) <= periode or closes[-1] <= 0:
        return 0.003
    tr_list = []
    for i in range(1, len(closes)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr_list.append(max(hl, hc, lc))
    if len(tr_list) < periode:
        return (sum(tr_list) / float(max(1, len(tr_list)))) / closes[-1]
    atr_rma = sum(tr_list[:periode]) / float(periode)
    for tr in tr_list[periode:]:
        atr_rma = ((atr_rma * (periode - 1)) + tr) / float(periode)
    return atr_rma / closes[-1]

def ambil_data_ohlc_indodax(coin, info, tf="15", jumlah_candle=100):
    """
    Mengambil data candlestick LANGSUNG dari Indodax:
    tf="5" (M5), tf="15" (M15), tf="60" (H1), tf="240" (H4).
    Mengembalikan tuple: (closes, highs, lows, vols, times).
    """
    peta_menit = {"5": 5, "15": 15, "30": 30, "60": 60, "240": 240}
    menit_per_candle = peta_menit.get(str(tf), 15)
    now_ts = int(time.time())
    from_ts = now_ts - ((jumlah_candle + 15) * menit_per_candle * 60)
    symbol = info["v2_symbol"]
    url = f"https://indodax.com/tradingview/history_v2?symbol={symbol}&tf={tf}&from={from_ts}&to={now_ts}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        if isinstance(data, list) and len(data) >= 35:
            raw = data[-jumlah_candle:]
            closes = [float(r.get("Close", r.get("close", 0))) for r in raw]
            highs = [float(r.get("High", r.get("high", 0))) for r in raw]
            lows = [float(r.get("Low", r.get("low", 0))) for r in raw]
            vols = [float(r.get("Volume", r.get("volume", 0)) or 0) for r in raw]
            times = [float(r.get("Time", r.get("time", 0)) or 0) for r in raw]
            if closes and closes[-1] > 0:
                return closes, highs, lows, vols, times

        if isinstance(data, dict) and "c" in data and len(data["c"]) >= 35:
            closes = [float(x) for x in data["c"][-jumlah_candle:]]
            highs = [float(x) for x in data["h"][-jumlah_candle:]]
            lows = [float(x) for x in data["l"][-jumlah_candle:]]
            vols = [float(x) for x in data.get("v", [1.0] * len(closes))[-jumlah_candle:]]
            times = [float(x) for x in data.get("t", [0.0] * len(closes))[-jumlah_candle:]]
            if closes and closes[-1] > 0:
                return closes, highs, lows, vols, times
    except Exception as e:
        print(f"⚠️ [INDODAX OHLC {coin} TF:{tf}] Gagal ambil chart: {e}")
    return None

def deteksi_rezim_pasar(closes, highs, lows):
    """
    Klasifikasi 4 rezim pasar berbasis CANDLE YANG SUDAH TUTUP (anti-repainting):
    - UPTREND, SIDEWAYS_UP, SIDEWAYS_DOWN, DOWNTREND
    """
    ema20_s = hitung_ema_series(closes, 20)
    ema50_s = hitung_ema_series(closes, 50)
    ema20_skrg = ema20_s[-1]
    ema20_lalu = ema20_s[-4] if len(ema20_s) >= 4 else ema20_s[0]
    ema50_skrg = ema50_s[-1]
    harga_skrg = closes[-1]

    slope_ema20_pct = ((ema20_skrg - ema20_lalu) / ema20_lalu) if ema20_lalu > 0 else 0.0
    jarak_ema_pct = ((ema20_skrg - ema50_skrg) / ema50_skrg) if ema50_skrg > 0 else 0.0

    low_terbaru = min(lows[-10:])
    low_sebelumnya = min(lows[-20:-10]) if len(lows) >= 20 else low_terbaru
    higher_low = low_terbaru >= (low_sebelumnya * 0.9985)

    if ema20_skrg > ema50_skrg and harga_skrg >= ema50_skrg and slope_ema20_pct >= 0.0005 and higher_low:
        rezim = "UPTREND"
    elif ema20_skrg < ema50_skrg and harga_skrg < ema20_skrg and slope_ema20_pct <= -0.0008 and not higher_low:
        rezim = "DOWNTREND"
    elif slope_ema20_pct >= -0.0003 and higher_low and jarak_ema_pct >= -0.0040:
        rezim = "SIDEWAYS_UP"
    else:
        rezim = "SIDEWAYS_DOWN"

    return {
        "rezim": rezim,
        "ema20": ema20_skrg,
        "ema50": ema50_skrg,
        "slope_ema20_pct": round(slope_ema20_pct * 100.0, 3),
        "higher_low": higher_low,
        "rsi": round(hitung_rsi(closes, 14), 1),
        "atr_pct": round(hitung_atr_pct(closes, highs, lows, 14), 5)
    }

def evaluasi_lampu_4h(c4h, h4h, l4h, v4h, t4h, h4_info):
    """
    Pengatur mode 3 lampu 4H bebas bias incomplete candle:
    - Membandingkan volume candle tutup terakhir (v4h[-2]) terhadap rata-rata 19 candle tutup sebelumnya.
    - Memproyeksikan volume candle berjalan (v4h[-1]) secara proporsional terhadap waktu berjalan 4H
      agar crash tajam di 1-2 jam pertama langsung terdeteksi.
    - Menambahkan deteksi slow-bleed (3 candle tutup merah beruntun & jauh di bawah EMA50 4H)
      dan flash crash (-4.5% pada candle berjalan).
    """
    rezim_4h = h4_info["rezim"]
    rsi_4h = h4_info["rsi"]
    ema50_4h = float(h4_info.get("ema50", c4h[-1]))

    # Rata-rata volume dari 19 candle 4H yang SUDAH TUTUP
    hist_vol = v4h[-21:-2] if len(v4h) >= 21 else v4h[:-2]
    vol_rata_closed = (sum(hist_vol) / float(len(hist_vol))) if hist_vol else (v4h[-2] or 1.0)
    vol_rata_closed = max(vol_rata_closed, 1e-9)

    # 1. Analisa candle 4H tutup terakhir (indeks -2)
    rasio_vol_closed = v4h[-2] / vol_rata_closed
    closed_merah = len(c4h) >= 3 and (c4h[-2] < c4h[-3])
    drop_closed_pct = ((c4h[-2] - c4h[-3]) / c4h[-3]) if (len(c4h) >= 3 and c4h[-3] > 0) else 0.0
    dua_merah_closed = len(c4h) >= 4 and (c4h[-2] < c4h[-3] < c4h[-4])
    tiga_merah_closed = len(c4h) >= 5 and (c4h[-2] < c4h[-3] < c4h[-4] < c4h[-5])

    # 2. Analisa candle 4H berjalan (indeks -1) dengan proyeksi volume berbasis waktu berjalan
    now_ts = time.time()
    ts_live = float(t4h[-1]) if (t4h and t4h[-1] > 0) else 0.0
    if ts_live > 0:
        ts_live_sec = ts_live / 1000.0 if ts_live > 1e12 else ts_live
        elapsed_4h = max(300.0, now_ts - ts_live_sec)
        progress_4h = min(1.0, max(0.15, elapsed_4h / 14400.0))
    else:
        progress_4h = min(1.0, max(0.15, (now_ts % 14400.0) / 14400.0))

    vol_live_proj = v4h[-1] / progress_4h
    rasio_vol_live_proj = vol_live_proj / vol_rata_closed
    live_merah = c4h[-1] < c4h[-2]
    drop_live_pct = ((c4h[-1] - c4h[-2]) / c4h[-2]) if c4h[-2] > 0 else 0.0
    rasio_vol_efektif = max(rasio_vol_closed, rasio_vol_live_proj)

    # 3. Deteksi Slow Bleed & Flash Crash
    slow_bleed_4h = (
        rezim_4h == "DOWNTREND"
        and tiga_merah_closed
        and c4h[-1] <= (ema50_4h * (1.0 - GRID_4H_SLOW_BLEED_EMA50_PCT))
    )
    flash_crash_live = drop_live_pct <= GRID_4H_FLASH_CRASH_PCT

    crash_ekstrem = (
        flash_crash_live
        or slow_bleed_4h
        or (
            rezim_4h == "DOWNTREND"
            and (
                rsi_4h < GRID_4H_CRASH_RSI
                or (closed_merah and rasio_vol_closed >= GRID_4H_CRASH_VOL_RATIO and (drop_closed_pct <= -0.025 or dua_merah_closed))
                or (live_merah and (drop_live_pct <= -0.025 or (drop_live_pct <= -0.015 and rasio_vol_live_proj >= GRID_4H_CRASH_VOL_RATIO)))
            )
        )
    )

    if crash_ekstrem:
        return "MERAH", round(rasio_vol_efektif, 2)
    if rezim_4h == "DOWNTREND":
        return "KUNING", round(rasio_vol_efektif, 2)
    return "HIJAU", round(rasio_vol_efektif, 2)

def analisa_teknikal_lengkap_pasar(harga_idr_map):
    """Analisa multi-timeframe 100% Native Indodax (5M+15M+1H+4H) bebas bias incomplete candle."""
    peta_analisa = {}
    for coin, info in WATCHLIST_COINS.items():
        if GRID_MODE_ENABLED and coin not in GRID_ALLOWED_COINS:
            continue

        data_ticker = harga_idr_map.get(coin)
        if not data_ticker or data_ticker["last"] <= 0:
            continue

        harga_idr = data_ticker["last"]
        harga_bid = data_ticker.get("buy", harga_idr)
        harga_ask = data_ticker.get("sell", harga_idr)
        spread_pct = data_ticker.get("spread_pct", 0.0)

        ohlc_5m = ambil_data_ohlc_indodax(coin, info, tf="5", jumlah_candle=150)
        ohlc_15m = ambil_data_ohlc_indodax(coin, info, tf="15", jumlah_candle=150)
        ohlc_1h = ambil_data_ohlc_indodax(coin, info, tf="60", jumlah_candle=150)
        ohlc_4h = ambil_data_ohlc_indodax(coin, info, tf="240", jumlah_candle=150)
        time.sleep(0.15)

        if not ohlc_5m or not ohlc_15m or not ohlc_1h or not ohlc_4h:
            continue

        c5, h5, l5, v5, t5 = ohlc_5m
        c15, h15, l15, v15, t15 = ohlc_15m
        c1h, h1h, l1h, v1h, t1h = ohlc_1h
        c4h, h4h, l4h, v4h, t4h = ohlc_4h

        # Gunakan candle yang SUDAH TUTUP ([:-1]) untuk kalkulasi struktur EMA/RSI/ATR agar anti-repainting
        m5 = deteksi_rezim_pasar(c5[:-1], h5[:-1], l5[:-1])
        m15 = deteksi_rezim_pasar(c15[:-1], h15[:-1], l15[:-1])
        h1 = deteksi_rezim_pasar(c1h[:-1], h1h[:-1], l1h[:-1])
        h4 = deteksi_rezim_pasar(c4h[:-1], h4h[:-1], l4h[:-1])
        lampu_4h, vol_4h_ratio = evaluasi_lampu_4h(c4h, h4h, l4h, v4h, t4h, h4)

        spread_aman = spread_pct <= MAX_SPREAD_INDODAX_PCT

        # Volume 5M pakai candle tutup terakhir (v5[-2]) vs 19 candle tutup sebelumnya
        hist_v5 = v5[-21:-2] if len(v5) >= 21 else v5[:-2]
        vol_rata_5m = (sum(hist_v5) / float(len(hist_v5))) if hist_v5 else (v5[-2] or 1.0)
        rasio_vol = v5[-2] / max(vol_rata_5m, 1e-9)

        # Konfirmasi candle 5M tutup terakhir & candle berjalan tidak sedang jatuh beruntun
        candle_5m_hijau = c5[-2] >= c5[-3]
        candle_jatuh_beruntun = (c5[-2] < c5[-3] < c5[-4]) or (c5[-1] < c5[-2] < c5[-3])

        # Anti-pucuk: pastikan harga tidak terlalu jauh di atas EMA20 15M
        ema20_15m = float(m15["ema20"])
        jarak_dari_ema20_15m_pct = ((harga_idr - ema20_15m) / ema20_15m) if ema20_15m > 0 else 0.0
        tidak_pucuk = jarak_dari_ema20_15m_pct <= GRID_MAX_DIST_EMA20_15M_PCT

        rezim_boleh = ("UPTREND", "SIDEWAYS_UP")
        h4_tidak_crash = (lampu_4h != "MERAH")
        h1_aman = h1["rezim"] in rezim_boleh
        m15_aman = m15["rezim"] in rezim_boleh
        volatilitas_cukup = m15["atr_pct"] >= GRID_MIN_ATR_15M_PCT
        koin_diizinkan = (coin in GRID_ALLOWED_COINS)

        atr_1h_pct = float(h1["atr_pct"])
        if lampu_4h == "HIJAU":
            step_atr = atr_1h_pct * GRID_ATR_MULT_GREEN
            grid_step_aktif = round(max(GRID_STEP_MIN_PCT, min(GRID_STEP_MAX_GREEN_PCT, step_atr)), 4)
            trigger_5m_ok = (
                m5["rsi"] <= GRID_MAX_RSI_M5_ENTRY
                and m15["rsi"] <= 64.0
                and tidak_pucuk
                and (not candle_jatuh_beruntun)
            )
            struktur_ok = m15_aman and h1_aman
        elif lampu_4h == "KUNING":
            step_atr = atr_1h_pct * GRID_ATR_MULT_YELLOW
            grid_step_aktif = round(max(GRID_STEP_MIN_PCT, min(GRID_STEP_MAX_YELLOW_PCT, step_atr)), 4)
            trigger_5m_ok = (
                candle_5m_hijau
                and m5["rsi"] <= GRID_MAX_RSI_M5_YELLOW
                and tidak_pucuk
                and (not candle_jatuh_beruntun)
            )
            struktur_ok = m15_aman and (h1_aman or m15["rezim"] == "UPTREND")
        else:
            step_atr = atr_1h_pct * GRID_ATR_MULT_YELLOW
            grid_step_aktif = round(max(GRID_STEP_MIN_PCT, min(GRID_STEP_MAX_YELLOW_PCT, step_atr)), 4)
            trigger_5m_ok = False
            struktur_ok = False

        layak_grid = bool(
            koin_diizinkan
            and h4_tidak_crash
            and struktur_ok
            and trigger_5m_ok
            and volatilitas_cukup
            and spread_aman
        )

        # Syarat buka Lapis 2 / Lapis 3 (momen sideways-up / uptrend baru di area value)
        layak_lapis_baru = bool(
            koin_diizinkan
            and h4_tidak_crash
            and m15_aman
            and candle_5m_hijau
            and tidak_pucuk
            and (not candle_jatuh_beruntun)
            and (m5["rsi"] <= GRID_MAX_RSI_M5_ENTRY)
            and spread_aman
        )

        skor_grid = 50.0
        if lampu_4h == "HIJAU":
            skor_grid += 10.0 if h4["rezim"] == "UPTREND" else 6.0
        elif lampu_4h == "KUNING":
            skor_grid += 2.0
        if h1["rezim"] == "UPTREND":
            skor_grid += 12.0
        elif h1["rezim"] == "SIDEWAYS_UP":
            skor_grid += 10.0
        if m15["rezim"] == "SIDEWAYS_UP":
            skor_grid += 15.0
        elif m15["rezim"] == "UPTREND":
            skor_grid += 10.0
        # Bonus area value / pullback sehat
        if 35.0 <= m5["rsi"] <= 52.0:
            skor_grid += 10.0
        if -0.004 <= jarak_dari_ema20_15m_pct <= 0.003:
            skor_grid += 4.0
        if not layak_grid:
            skor_grid = min(skor_grid, 45.0)

        if layak_grid:
            ikon_lampu = "🟢" if lampu_4h == "HIJAU" else "🟡"
            prediksi = (
                f"{ikon_lampu} LAYAK GRID [{lampu_4h} Step:{grid_step_aktif*100:.1f}%] "
                f"({m15['rezim']} 15M | {h1['rezim']} 1H | {h4['rezim']} 4H | DistEMA20:{jarak_dari_ema20_15m_pct*100:+.2f}%)"
            )
        elif lampu_4h == "MERAH":
            prediksi = f"🔴 VETO CRASH/BLEED 4H (RSI4H:{h4['rsi']}, Vol4H:{vol_4h_ratio}x - Stop Entry)"
        elif not struktur_ok:
            prediksi = f"🔴 BLOKIR GRID ({m15['rezim']} 15M / {h1['rezim']} 1H | 4H:{lampu_4h})"
        elif not tidak_pucuk:
            prediksi = f"🟡 ANTI-PUCUK (Harga +{jarak_dari_ema20_15m_pct*100:.2f}% di atas EMA20 15M, tunggu pullback)"
        elif not trigger_5m_ok:
            prediksi = f"🟡 TUNGGU TRIGGER 5M (RSI5M:{m5['rsi']} | 4H:{lampu_4h})"
        elif not volatilitas_cukup:
            prediksi = f"🟡 PASAR SEPI (ATR15M:{m15['atr_pct']*100:.2f}% < {GRID_MIN_ATR_15M_PCT*100:.2f}%)"
        else:
            prediksi = f"⚠️ SPREAD LEBAR ({spread_pct*100:.2f}%)"

        entry_ideal_idr = bulatkan_harga_indodax(coin, harga_bid)
        tp_ideal_idr = bulatkan_harga_indodax(coin, entry_ideal_idr * (1.0 + grid_step_aktif))
        sl_ideal_idr = bulatkan_harga_indodax(coin, entry_ideal_idr * (1.0 - (grid_step_aktif * 2.0)))

        peta_analisa[coin] = {
            "coin": coin,
            "sumber_ohlc": "INDODAX-NATIVE-MTF-CLOSED",
            "harga_idr": harga_idr,
            "harga_bid": harga_bid,
            "harga_ask": harga_ask,
            "spread_pct": spread_pct,
            "high_2jam_idr": round(max(h5[-24:]), 0),
            "tren": "UPTREND" if (h1_aman and h4_tidak_crash) else "SIDEWAYS/DOWN",
            "tren_5m_naik": m5["rezim"] in rezim_boleh,
            "tren_15m_naik": m15_aman,
            "candle_5m_hijau": candle_5m_hijau,
            "candle_jatuh_beruntun": candle_jatuh_beruntun,
            "tren_detail": f"5M:{m5['rezim']}|15M:{m15['rezim']}|1H:{h1['rezim']}|4H:{h4['rezim']}[{lampu_4h}]",
            "rezim_5m": m5["rezim"],
            "rezim_15m": m15["rezim"],
            "rezim_1h": h1["rezim"],
            "rezim_4h": h4["rezim"],
            "lampu_4h": lampu_4h,
            "vol_4h_ratio": vol_4h_ratio,
            "grid_step_aktif": grid_step_aktif,
            "jarak_ema20_15m_pct": round(jarak_dari_ema20_15m_pct * 100.0, 2),
            "rsi": m5["rsi"],
            "rsi_15m": m15["rsi"],
            "rsi_1h": h1["rsi"],
            "rsi_4h": h4["rsi"],
            "atr_pct": m5["atr_pct"],
            "atr_15m_pct": m15["atr_pct"],
            "atr_1h_pct": h1["atr_pct"],
            "atr_4h_pct": h4["atr_pct"],
            "rasio_vol": round(rasio_vol, 2),
            "entry_ideal_idr": entry_ideal_idr,
            "tp_ideal_idr": tp_ideal_idr,
            "sl_ideal_idr": sl_ideal_idr,
            "tp_target_pct": round(grid_step_aktif * 100.0, 2),
            "gaya": "GRID_3L" if layak_grid else "WAIT",
            "skor": round(skor_grid, 1),
            "prediksi": prediksi,
            "siap_entry": layak_grid,
            "layak_grid": layak_grid,
            "layak_lapis_baru": layak_lapis_baru,
            "bobot_alokasi": round(skor_grid, 2)
        }
    return peta_analisa

# ==============================================================================
# MESIN DATA & INDIKATOR KUANTITATIF MINI SWING (100% NATIVE INDODAX 1D-4H-1H)
# ==============================================================================
def ambil_ohlcv_swing_indodax(coin, tf="240", jumlah_candle=260):
    """
    Mengambil OHLCV lengkap (Open, High, Low, Close, Volume, Time) LANGSUNG dari chart Indodax
    sesuai timeframe aslinya: tf="1D" (Daily), tf="240" (4H), tf="60" (1H).
    """
    info = WATCHLIST_COINS[coin]
    tf_str = str(tf)
    peta_menit = {"15": 15, "60": 60, "240": 240, "1D": 1440, "D": 1440}
    menit_bar = peta_menit.get(tf_str, 240)
    now_ts = int(time.time())
    from_ts = now_ts - ((jumlah_candle + 25) * menit_bar * 60)
    symbol = info["v2_symbol"]

    daftar_tf_coba = [tf_str, "D"] if tf_str == "1D" else [tf_str]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}

    for tf_uji in daftar_tf_coba:
        url = f"https://indodax.com/tradingview/history_v2?symbol={symbol}&tf={tf_uji}&from={from_ts}&to={now_ts}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode())

            if isinstance(data, list) and len(data) >= 60:
                raw = data[-jumlah_candle:]
                opens = [float(r.get("Open", r.get("open", 0))) for r in raw]
                highs = [float(r.get("High", r.get("high", 0))) for r in raw]
                lows = [float(r.get("Low", r.get("low", 0))) for r in raw]
                closes = [float(r.get("Close", r.get("close", 0))) for r in raw]
                vols = [float(r.get("Volume", r.get("volume", 0)) or 0) for r in raw]
                times = [float(r.get("Time", r.get("time", 0)) or 0) for r in raw]
                if closes and closes[-1] > 0:
                    return {"o": opens, "h": highs, "l": lows, "c": closes, "v": vols, "t": times}

            if isinstance(data, dict) and "c" in data and len(data["c"]) >= 60:
                return {
                    "o": [float(x) for x in data["o"][-jumlah_candle:]],
                    "h": [float(x) for x in data["h"][-jumlah_candle:]],
                    "l": [float(x) for x in data["l"][-jumlah_candle:]],
                    "c": [float(x) for x in data["c"][-jumlah_candle:]],
                    "v": [float(x) for x in data.get("v", [0.0] * len(data["c"]))[-jumlah_candle:]],
                    "t": [float(x) for x in data.get("t", [0.0] * len(data["c"]))[-jumlah_candle:]]
                }
        except Exception as e:
            print(f"⚠️ [SWING OHLCV {coin} TF:{tf_uji}] Gagal: {e}")
    return None

def swing_ema_series(values, periode):
    """Exponential Moving Average (EMA) sejati: k = 2/(N+1), seed SMA awal, sejajar 1:1 dgn indeks candle."""
    n = len(values)
    if n < periode:
        return [None] * n
    k = 2.0 / (periode + 1.0)
    out = [None] * (periode - 1)
    ema = sum(values[:periode]) / float(periode)
    out.append(ema)
    for v in values[periode:]:
        ema = (v * k) + (ema * (1.0 - k))
        out.append(ema)
    return out

def swing_wilder_rma_series(values, periode):
    """Wilder's Smoothing (RMA, alpha = 1/N) standar profesional utk ATR, RSI, dan ADX."""
    n = len(values)
    if n < periode:
        return [None] * n
    out = [None] * (periode - 1)
    rma = sum(values[:periode]) / float(periode)
    out.append(rma)
    for v in values[periode:]:
        rma = ((rma * (periode - 1)) + v) / float(periode)
        out.append(rma)
    return out

def swing_true_range_series(highs, lows, closes):
    tr = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    return tr

def swing_atr_series(highs, lows, closes, periode=14):
    tr = swing_true_range_series(highs, lows, closes)
    return swing_wilder_rma_series(tr, periode)

def swing_rsi_series(closes, periode=14):
    """Wilder's RSI(14) seri lengkap (sejajar indeks closes) untuk deteksi divergensi & momentum."""
    n = len(closes)
    if n <= periode:
        return [None] * n
    gains, losses = [], []
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = swing_wilder_rma_series(gains, periode)
    avg_l = swing_wilder_rma_series(losses, periode)
    out = [None]
    for g, l in zip(avg_g, avg_l):
        if g is None or l is None:
            out.append(None)
        elif l <= 1e-12:
            out.append(100.0 if g > 0 else 50.0)
        else:
            out.append(100.0 - (100.0 / (1.0 + (g / l))))
    return out

def swing_adx_di(highs, lows, closes, periode=14):
    """Wilder's ADX(14), +DI(14), dan -DI(14)."""
    n = len(closes)
    if n < (periode * 2 + 2):
        return 0.0, 0.0, 0.0
    tr_s, pdm_s, mdm_s = [], [], []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pdm_s.append(up if (up > dn and up > 0.0) else 0.0)
        mdm_s.append(dn if (dn > up and dn > 0.0) else 0.0)
        tr_s.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))

    sm_tr = swing_wilder_rma_series(tr_s, periode)
    sm_pdm = swing_wilder_rma_series(pdm_s, periode)
    sm_mdm = swing_wilder_rma_series(mdm_s, periode)

    dx_vals = []
    last_pdi, last_mdi = 0.0, 0.0
    for t_v, p_v, m_v in zip(sm_tr, sm_pdm, sm_mdm):
        if t_v is None or t_v <= 1e-12:
            continue
        pdi = 100.0 * (p_v / t_v)
        mdi = 100.0 * (m_v / t_v)
        denom = pdi + mdi
        dx_vals.append(100.0 * abs(pdi - mdi) / denom if denom > 1e-12 else 0.0)
        last_pdi, last_mdi = pdi, mdi

    adx_s = swing_wilder_rma_series(dx_vals, periode)
    adx_val = adx_s[-1] if (adx_s and adx_s[-1] is not None) else 0.0
    return round(adx_val, 2), round(last_pdi, 2), round(last_mdi, 2)

def swing_choppiness_index(highs, lows, closes, periode=14):
    """Choppiness Index Bill Dreiss CHOP(14): <45 tren bersih, >50 sideways/choppy."""
    if len(closes) < periode + 1:
        return 50.0
    tr = swing_true_range_series(highs, lows, closes)[-periode:]
    hi = max(highs[-periode:])
    lo = min(lows[-periode:])
    if (hi - lo) <= 1e-12:
        return 100.0
    ratio = sum(tr) / (hi - lo)
    if ratio <= 0:
        return 50.0
    return round(100.0 * (math.log10(ratio) / math.log10(float(periode))), 2)

def swing_efficiency_ratio(closes, periode=10):
    """Kaufman Efficiency Ratio ER(10): >0.35 tren efisien, <0.30 sideways."""
    if len(closes) <= periode:
        return 0.0
    direction = abs(closes[-1] - closes[-(periode + 1)])
    volatility = sum(abs(closes[i] - closes[i - 1]) for i in range(len(closes) - periode, len(closes)))
    return round(direction / volatility, 4) if volatility > 1e-12 else 0.0

def swing_bollinger_bands(closes, periode=20, num_std=2.0):
    if len(closes) < periode:
        return 0.0, 0.0, 0.0
    window = closes[-periode:]
    mid = sum(window) / float(periode)
    var = sum((x - mid) ** 2 for x in window) / float(periode)
    std = math.sqrt(max(0.0, var))
    return mid + (num_std * std), mid, mid - (num_std * std)

def swing_donchian_channel(highs, lows, periode=20):
    if len(highs) < periode:
        return max(highs), min(lows)
    return max(highs[-periode:]), min(lows[-periode:])

def swing_relative_strength_vs_btc(t_alt, c_alt, t_btc, c_btc):
    """Menghitung RS = Close_Alt / Close_BTC sejajar timestamp, EMA20(RS), RS_ROC_20, & rekor 20-bar."""
    peta_btc = {int(t): c for t, c in zip(t_btc, c_btc) if c > 0}
    rs_list = []
    for t_a, c_a in zip(t_alt, c_alt):
        cb = peta_btc.get(int(t_a))
        if cb and cb > 0:
            rs_list.append(c_a / cb)
    if len(rs_list) < 25:
        n_min = min(len(c_alt), len(c_btc))
        rs_list = [c_alt[-n_min + i] / max(1e-9, c_btc[-n_min + i]) for i in range(n_min)]

    if len(rs_list) < 22:
        return {"rs": 0.0, "above_ema20": False, "roc_20": 0.0, "break_20_high": False}

    ema20_rs = swing_ema_series(rs_list, 20)
    rs_now = rs_list[-1]
    rs_ema = ema20_rs[-1] if ema20_rs[-1] is not None else rs_now
    rs_roc_20 = ((rs_now - rs_list[-21]) / rs_list[-21]) if rs_list[-21] > 0 else 0.0
    break_20_high = rs_now >= max(rs_list[-21:-1])
    return {
        "rs": rs_now,
        "above_ema20": rs_now > rs_ema,
        "roc_20": round(rs_roc_20, 5),
        "break_20_high": break_20_high
    }

def swing_deteksi_bullish_divergence_4h(lows, rsi_series, lookback=24):
    """Regular Bullish Divergence 4H: Harga mencetak Lower Low sementara RSI(14) Higher Low (titik 1 RSI < 32)."""
    if len(lows) < lookback + 4:
        return False
    l_win = lows[-lookback:]
    r_win = rsi_series[-lookback:]
    pivots = []
    for i in range(2, len(l_win) - 1):
        if r_win[i] is None:
            continue
        if l_win[i] <= l_win[i - 1] and l_win[i] <= l_win[i - 2] and l_win[i] <= l_win[i + 1]:
            pivots.append((i, l_win[i], r_win[i]))
    if len(pivots) < 2:
        return False
    p1_idx, p1_low, p1_rsi = pivots[-2]
    p2_idx, p2_low, p2_rsi = pivots[-1]
    return bool(
        (p2_idx - p1_idx) >= 3
        and p2_idx >= (len(l_win) - 5)
        and p2_low < p1_low
        and p2_rsi > p1_rsi
        and p1_rsi < 32.0
    )

def analisa_teknikal_mini_swing(harga_idr_map, pairs_meta, order_size_ref_idr=50000.0):
    """
    Mesin Analisa Multi-Timeframe 100% Deterministik (1D -> 4H -> 1H + Order Book) langsung dari Indodax.
    - Semua indikator dihitung pada candle yang SUDAH TUTUP ([:-1]) -> zero repainting.
    - BTC/IDR hanya dibaca sebagai Kompas Rezim Makro & Gerbang Stabilisasi (tidak pernah ditransaksikan Swing).
    """
    hasil = {"rezim": "SIDEWAYS", "btc_info": {}, "kandidat": {}, "semua_koin": {}}

    # 1. Lapisan 1: Kompas Makro BTC/IDR (1D, 4H, 1H)
    btc_1d = ambil_ohlcv_swing_indodax("BTC", tf="1D", jumlah_candle=260)
    btc_4h = ambil_ohlcv_swing_indodax("BTC", tf="240", jumlah_candle=160)
    btc_1h = ambil_ohlcv_swing_indodax("BTC", tf="60", jumlah_candle=120)
    if not btc_1d or not btc_4h or not btc_1h:
        hasil["btc_info"] = {"error": "Gagal ambil OHLCV 1D/4H/1H BTC Indodax"}
        return hasil

    # Slice [:-1] = HANYA candle yang sudah tertutup sempurna
    c1d_b, h1d_b, l1d_b = btc_1d["c"][:-1], btc_1d["h"][:-1], btc_1d["l"][:-1]
    c4h_b, h4h_b, l4h_b, t4h_b = btc_4h["c"][:-1], btc_4h["h"][:-1], btc_4h["l"][:-1], btc_4h["t"][:-1]
    o1h_b, c1h_b = btc_1h["o"][:-1], btc_1h["c"][:-1]

    ema50_1d_b = swing_ema_series(c1d_b, 50)[-1]
    ema200_1d_b = swing_ema_series(c1d_b, 200)[-1] or ema50_1d_b
    ema20_4h_b = swing_ema_series(c4h_b, 20)[-1]
    ema50_4h_b = swing_ema_series(c4h_b, 50)[-1]
    adx_4h_b, pdi_4h_b, mdi_4h_b = swing_adx_di(h4h_b, l4h_b, c4h_b, 14)
    chop_4h_b = swing_choppiness_index(h4h_b, l4h_b, c4h_b, 14)
    er_4h_b = swing_efficiency_ratio(c4h_b, 10)
    rsi_1h_b = swing_rsi_series(c1h_b, 14)

    # Klasifikasi 3-Rezim sesuai Tabel Blueprint Bagian 5
    is_bullish = (
        c1d_b[-1] > ema50_1d_b
        and (
            ema50_1d_b > ema200_1d_b
            or (c4h_b[-1] > ema50_4h_b and adx_4h_b > 22.0 and pdi_4h_b > mdi_4h_b and chop_4h_b < 45.0)
        )
    )
    is_bearish = (
        c1d_b[-1] < ema50_1d_b
        and ema20_4h_b < ema50_4h_b
        and mdi_4h_b > pdi_4h_b
        and adx_4h_b >= 20.0
    )
    is_sideways = (adx_4h_b < 22.0 and chop_4h_b > 50.0) or (er_4h_b < 0.30)

    if is_bearish:
        rezim = "BEARISH_DOWN"
    elif is_bullish and not is_sideways:
        rezim = "BULLISH"
    else:
        rezim = "SIDEWAYS"

    # Gerbang 1 Bearish: Stabilisasi BTC (4H change > -2.0% & 1H hijau atau RSI 1H memantul naik)
    btc_4h_chg = ((c4h_b[-1] - c4h_b[-2]) / c4h_b[-2]) if c4h_b[-2] > 0 else 0.0
    btc_1h_hijau = c1h_b[-1] > o1h_b[-1]
    btc_1h_rsi_naik = (rsi_1h_b[-1] is not None and rsi_1h_b[-2] is not None and rsi_1h_b[-1] > rsi_1h_b[-2])
    btc_stabil_gate = (btc_4h_chg > -0.020) and (btc_1h_hijau or btc_1h_rsi_naik)

    hasil["rezim"] = rezim
    hasil["btc_info"] = {
        "rezim": rezim,
        "close_1d": c1d_b[-1], "ema50_1d": round(ema50_1d_b, 0), "ema200_1d": round(ema200_1d_b, 0),
        "adx_4h": adx_4h_b, "pdi_4h": pdi_4h_b, "mdi_4h": mdi_4h_b,
        "chop_4h": chop_4h_b, "er_4h": er_4h_b,
        "btc_4h_chg_pct": round(btc_4h_chg * 100.0, 2),
        "btc_stabil_gate": btc_stabil_gate
    }

    # 2. Lapisan 2 (4H Struktur) & Lapisan 3 (1H Presisi + Order Book) untuk Core Pool Non-BTC
    for coin in sorted(SWING_ALLOWED_COINS):
        if coin == "BTC" or coin not in WATCHLIST_COINS:
            continue
        sym_v2 = WATCHLIST_COINS[coin]["v2_symbol"]
        meta_c = pairs_meta.get(sym_v2, {})
        if meta_c.get("is_maintenance", 0) != 0 or meta_c.get("is_market_suspended", 0) != 0:
            hasil["semua_koin"][coin] = {"coin": coin, "status": "SKIP_MAINTENANCE", "siap_entry": False}
            continue

        d_4h = ambil_ohlcv_swing_indodax(coin, tf="240", jumlah_candle=160)
        d_1h = ambil_ohlcv_swing_indodax(coin, tf="60", jumlah_candle=120)
        time.sleep(0.15)
        if not d_4h or not d_1h:
            continue

        # Closed bars ([:-1]) untuk seluruh sinyal anti-repainting
        o4, h4, l4, c4, v4, t4 = d_4h["o"][:-1], d_4h["h"][:-1], d_4h["l"][:-1], d_4h["c"][:-1], d_4h["v"][:-1], d_4h["t"][:-1]
        o1, h1, l1, c1, v1 = d_1h["o"][:-1], d_1h["h"][:-1], d_1h["l"][:-1], d_1h["c"][:-1], d_1h["v"][:-1]
        harga_live = harga_idr_map.get(coin, {}).get("last", c1[-1])
        harga_bid = harga_idr_map.get(coin, {}).get("buy", harga_live)
        harga_ask = harga_idr_map.get(coin, {}).get("sell", harga_live)

        # Indikator 4H (EMA sejati & Wilder RMA)
        ema20_4h = swing_ema_series(c4, 20)[-1]
        ema50_4h = swing_ema_series(c4, 50)[-1]
        atr_4h_s = swing_atr_series(h4, l4, c4, 14)
        atr_4h = atr_4h_s[-1] or 0.0
        atr_4h_pct = (atr_4h / c4[-1]) if c4[-1] > 0 else 0.0
        rsi_4h_s = swing_rsi_series(c4, 14)
        rsi_4h = rsi_4h_s[-1] or 50.0
        bb_up_4h, bb_mid_4h, bb_lo_4h = swing_bollinger_bands(c4, 20, 2.0)
        dc_hi_4h, dc_lo_4h = swing_donchian_channel(h4, l4, 20)
        swing_low_4h = min(l4[-8:])
        swing_high_4h = max(h4[-12:])
        sma_vol_4h = sum(v4[-21:-1]) / 20.0 if len(v4) >= 21 else max(1e-9, sum(v4) / max(1, len(v4)))
        vol_ratio_4h = v4[-1] / max(1e-9, sma_vol_4h)
        rs_info = swing_relative_strength_vs_btc(t4, c4, t4h_b, c4h_b)

        # Indikator 1H (Konfirmasi Timing)
        ema9_1h = swing_ema_series(c1, 9)[-1]
        ema20_1h = swing_ema_series(c1, 20)[-1]
        rsi_1h_s = swing_rsi_series(c1, 14)
        rsi_1h_now = rsi_1h_s[-1] or 50.0
        rsi_1h_prev = rsi_1h_s[-2] or 50.0
        sma_vol_1h = sum(v1[-21:-1]) / 20.0 if len(v1) >= 21 else max(1e-9, sum(v1) / max(1, len(v1)))
        vol_ratio_1h = v1[-1] / max(1e-9, sma_vol_1h)

        range_1h = max(1e-12, h1[-1] - l1[-1])
        lower_wick_1h = min(o1[-1], c1[-1]) - l1[-1]
        wick_rejection_1h = (lower_wick_1h / range_1h) >= 0.50
        bullish_engulf_1h = (c1[-1] > o1[-1]) and (c1[-2] < o1[-2]) and (c1[-1] >= o1[-2]) and (o1[-1] <= c1[-2])
        reclaim_ema_1h = (c1[-1] > ema9_1h) or (c1[-1] > ema20_1h)
        trigger_1h_ok = bool(
            (reclaim_ema_1h or wick_rejection_1h or bullish_engulf_1h)
            and (vol_ratio_1h >= 1.20)
            and (rsi_1h_now > rsi_1h_prev)
        )

        # Matriks Batasan Volatilitas 4H ATR%
        atr_ok = False
        atr_risk_mult = 0.0
        if SWING_ATR_MIN_PCT <= atr_4h_pct <= SWING_ATR_FLOOR_MAX_PCT:
            atr_ok, atr_risk_mult = True, 1.00
        elif SWING_ATR_FLOOR_MAX_PCT < atr_4h_pct <= SWING_ATR_SWEET_MAX_PCT:
            atr_ok, atr_risk_mult = True, 1.00
        elif SWING_ATR_SWEET_MAX_PCT < atr_4h_pct <= SWING_ATR_CAP_MAX_PCT:
            atr_ok, atr_risk_mult = True, 0.75

        # Evaluasi Syarat Setup 4H Sesuai Rezim Aktif
        setup_4h_ok = False
        setup_label = "WAIT"
        if atr_ok:
            if rezim == "BULLISH":
                pullback_zona = (l4[-1] <= ema20_4h * 1.006) and (c4[-1] >= ema50_4h * 0.995)
                if (c4[-1] > ema50_4h) and rs_info["above_ema20"] and pullback_zona and (40.0 <= rsi_4h <= 55.0):
                    setup_4h_ok = True
                    setup_label = "BULL_PULLBACK"
            elif rezim == "SIDEWAYS":
                sentuh_support = (l4[-1] <= bb_lo_4h * 1.005) or (l4[-1] <= dc_lo_4h * 1.005)
                tidak_breakdown_besar = not (c4[-1] < o4[-1] and vol_ratio_4h >= 1.80)
                if sentuh_support and (rsi_4h < 35.0) and tidak_breakdown_besar:
                    setup_4h_ok = True
                    setup_label = "SIDEWAYS_MEAN_REV"
            elif rezim == "BEARISH_DOWN":
                # Protokol 5-Gerbang Anti-Pisau Jatuh (Gerbang 1: BTC stabil, Gerbang 2: Decoupled / Div+Cap)
                jalur_decoupled = (c4[-1] > ema50_4h) and rs_info["break_20_high"]
                range_4h = max(1e-12, h4[-1] - l4[-1])
                wick_4h_ok = ((min(o4[-1], c4[-1]) - l4[-1]) / range_4h) >= 0.50
                div_4h = swing_deteksi_bullish_divergence_4h(l4, rsi_4h_s)
                jalur_div_cap = div_4h and (vol_ratio_4h >= 2.0) and wick_4h_ok and (l4[-1] <= dc_lo_4h * 1.015)
                if btc_stabil_gate and (jalur_decoupled or jalur_div_cap):
                    setup_4h_ok = True
                    setup_label = "BEAR_DECOUPLED" if jalur_decoupled else "BEAR_DIV_CAP"

        # Cek Order Book hanya jika 4H & 1H lolos (hemat rate-limit API Indodax)
        ob_info = {"ok": False, "spread_pct": 0.0, "obp": 0.5, "alasan": "Belum lolos 4H/1H"}
        if setup_4h_ok and trigger_1h_ok:
            ob_info = cek_mikrostruktur_orderbook_indodax(coin, order_size_idr=order_size_ref_idr)
            if ob_info["best_bid"] > 0:
                harga_bid = ob_info["best_bid"]
                harga_ask = ob_info["best_ask"]

        info_koin = {
            "coin": coin,
            "rezim": rezim,
            "setup_label": setup_label,
            "harga_live": harga_live,
            "harga_bid": harga_bid,
            "harga_ask": harga_ask,
            "ema20_4h": ema20_4h,
            "ema50_4h": ema50_4h,
            "atr_4h": atr_4h,
            "atr_4h_pct": round(atr_4h_pct, 5),
            "atr_ok": atr_ok,
            "atr_risk_mult": atr_risk_mult,
            "rsi_4h": round(rsi_4h, 1),
            "rsi_1h": round(rsi_1h_now, 1),
            "bb_up_4h": bb_up_4h,
            "bb_mid_4h": bb_mid_4h,
            "bb_lo_4h": bb_lo_4h,
            "dc_hi_4h": dc_hi_4h,
            "dc_lo_4h": dc_lo_4h,
            "swing_low_4h": swing_low_4h,
            "swing_high_4h": swing_high_4h,
            "rs_info": rs_info,
            "vol_ratio_1h": round(vol_ratio_1h, 2),
            "setup_4h_ok": setup_4h_ok,
            "trigger_1h_ok": trigger_1h_ok,
            "ob_info": ob_info,
            "siap_entry": bool(setup_4h_ok and trigger_1h_ok and ob_info["ok"])
        }
        hasil["semua_koin"][coin] = info_koin
        if info_koin["siap_entry"]:
            hasil["kandidat"][coin] = info_koin

    return hasil

# ==============================================================================
# BAGIAN 6 & 7: MESIN MINI SWING DETERMINISTIK (DUAL-CAP + VIRTUAL OCO GUARDIAN)
# ==============================================================================
def hitung_parameter_entry_dan_sizing_swing(info_k, swing_equity_idr, swing_free_idr, cb_half_size, pairs_meta):
    """
    Formulasi Matematis Eksak (Blueprint Bagian 4):
    - Dual-Cap SL inklusif fee+slippage Indodax (d_SL_max dari SWING_MAX_POS_LOSS_CAP)
    - Lantai SL 2.20% (ATR 1.3%-1.5%) & Plafon SL 4.50% (ATR 3.1%-4.5%)
    - Bounce Headroom Gate (>= 1.8x d_SL)
    - Net RRR >= 1.75:1
    - Fee-Inclusive Position Sizing C_pos & Q_coin
    """
    coin = info_k["coin"]
    rezim = info_k["rezim"]
    entry_p = bulatkan_harga_swing(coin, info_k["harga_bid"], pairs_meta)
    atr_4h = float(info_k["atr_4h"])
    atr_pct = float(info_k["atr_4h_pct"])
    if entry_p <= 0 or atr_4h <= 0:
        return None, "Harga/ATR tidak valid"

    # 1. Hitung jarak SL struktur (max dari 1.5x ATR atau di bawah SwingLow - 0.25 ATR)
    sl_atr_p = entry_p - (1.5 * atr_4h)
    sl_struct_p = float(info_k["swing_low_4h"]) - (0.25 * atr_4h)
    raw_sl_p = min(sl_atr_p, sl_struct_p)
    d_sl = (entry_p - raw_sl_p) / entry_p

    # Terapkan Lantai & Plafon Volatilitas ATR%
    if atr_pct <= SWING_ATR_FLOOR_MAX_PCT:
        d_sl = max(d_sl, SWING_SL_FLOOR_PCT)
    if atr_pct > SWING_ATR_SWEET_MAX_PCT:
        d_sl = min(d_sl, SWING_SL_CAP_PCT)

    # Dual-Cap 1: Fee-Inclusive Price SL Cap (overhead ~0.67% -> cap 5.0% menyisakan d_SL_max 4.34%)
    d_sl_max = 1.0 - SWING_SLIPPAGE_SL_PCT - (
        (1.0 - SWING_MAX_POS_LOSS_CAP) / ((1.0 - SWING_FEE_BUY_MAKER) * (1.0 - SWING_FEE_SELL_TAKER))
    )
    if d_sl > d_sl_max:
        return None, f"SL struktur terlalu dalam ({d_sl*100:.2f}% > cap {d_sl_max*100:.2f}%)"

    sl_p = bulatkan_harga_swing(coin, entry_p * (1.0 - d_sl), pairs_meta)
    d_sl = (entry_p - sl_p) / entry_p

    # 2. Target TP1 & TP2 sesuai Rezim (dan Gerbang Ruang Pantulan / Headroom >= 1.8x d_SL)
    if rezim == "BULLISH":
        tp1_p = bulatkan_harga_swing(coin, entry_p * (1.0 + (1.5 * d_sl)), pairs_meta)
        tp2_p = bulatkan_harga_swing(coin, entry_p * (1.0 + (3.0 * d_sl)), pairs_meta)
        tp1_ratio = 0.50
        res_terdekat = max(float(info_k["swing_high_4h"]), float(info_k["dc_hi_4h"]))
        r_acct = SWING_RISK_BULLISH
    elif rezim == "SIDEWAYS":
        tp1_raw = max(float(info_k["bb_mid_4h"]), float(info_k["ema20_4h"]), entry_p * (1.0 + (1.35 * d_sl)))
        tp2_raw = max(float(info_k["bb_up_4h"]), entry_p * (1.0 + (2.5 * d_sl)))
        tp1_p = bulatkan_harga_swing(coin, tp1_raw, pairs_meta)
        tp2_p = bulatkan_harga_swing(coin, tp2_raw, pairs_meta)
        tp1_ratio = 0.60
        res_terdekat = float(info_k["bb_up_4h"])
        r_acct = SWING_RISK_SIDEWAYS
    else:  # BEARISH_DOWN (Gerbang 3 & 4)
        tp1_raw = min(float(info_k["ema20_4h"]) * 0.997, entry_p * (1.0 + (1.8 * d_sl)))
        tp2_raw = max(float(info_k["ema50_4h"]), entry_p * (1.0 + (2.6 * d_sl)))
        tp1_p = bulatkan_harga_swing(coin, max(tp1_raw, entry_p * (1.0 + (1.5 * d_sl))), pairs_meta)
        tp2_p = bulatkan_harga_swing(coin, tp2_raw, pairs_meta)
        tp1_ratio = 0.65
        res_terdekat = max(float(info_k["ema20_4h"]), float(info_k["swing_high_4h"]))
        r_acct = SWING_RISK_BEARISH

    headroom_pct = (res_terdekat - entry_p) / entry_p
    if rezim == "BEARISH_DOWN" and headroom_pct < (1.8 * d_sl):
        return None, f"Gagal Headroom Gate Bearish ({headroom_pct*100:.2f}% < {1.8*d_sl*100:.2f}%)"

    # 3. Validasi Net RRR Eksak (berbasis blended TP1 + TP2)
    d_tp_blended = (tp1_ratio * ((tp1_p - entry_p) / entry_p)) + ((1.0 - tp1_ratio) * ((tp2_p - entry_p) / entry_p))
    w_net = ((1.0 - SWING_FEE_BUY_MAKER) * (1.0 + d_tp_blended) * (1.0 - SWING_FEE_SELL_MAKER)) - 1.0
    l_net = 1.0 - ((1.0 - SWING_FEE_BUY_MAKER) * (1.0 - d_sl - SWING_SLIPPAGE_SL_PCT) * (1.0 - SWING_FEE_SELL_TAKER))
    net_rrr = (w_net / l_net) if l_net > 0 else 0.0
    if net_rrr < SWING_MIN_NET_RRR:
        return None, f"Net RRR terlalu tipis ({net_rrr:.2f} < {SWING_MIN_NET_RRR:.2f})"

    # 4. Dual-Cap 2: Fee-Inclusive Position Sizing + Circuit Breaker + ATR Risk Multiplier
    r_eff = r_acct * float(info_k["atr_risk_mult"]) * (0.50 if cb_half_size else 1.0)
    c_pos_ideal = (swing_equity_idr * r_eff) / max(1e-6, l_net)
    c_pos_max_conc = swing_equity_idr * SWING_MAX_SINGLE_CONCENTRATION
    c_pos = min(c_pos_ideal, c_pos_max_conc, swing_free_idr)

    # Jika modal Mini Swing kecil sehingga sizing risiko di bawah minimal order Indodax, pastikan minimal aman SL terpenuhi
    min_order_base = float(pairs_meta.get(WATCHLIST_COINS[coin]["v2_symbol"], {}).get("trade_min_base_currency", MIN_LIMIT_ORDER_INDODAX_IDR))
    min_aman = max(MIN_NEW_BUY_ALLOCATION_IDR, min_order_base * 1.15)
    if c_pos < min_aman:
        if min(c_pos_max_conc, swing_free_idr) >= min_aman:
            c_pos = min_aman
        else:
            return None, f"Dana Swing bebas Rp{swing_free_idr:,.0f} < minimal aman Rp{min_aman:,.0f}"

    qty_coin = format_qty_swing(coin, (c_pos * (1.0 - SWING_FEE_BUY_MAKER)) / entry_p, pairs_meta)
    if qty_coin <= 0 or (qty_coin * entry_p) < min_order_base:
        return None, "Kuantitas koin di bawah minimum Indodax"

    return {
        "entry_price_idr": entry_p,
        "sl_price_idr": sl_p,
        "tp1_price_idr": tp1_p,
        "tp2_price_idr": tp2_p,
        "tp1_ratio": tp1_ratio,
        "d_sl": round(d_sl, 5),
        "l_net": round(l_net, 5),
        "w_net": round(w_net, 5),
        "net_rrr": round(net_rrr, 2),
        "capital_idr": round(qty_coin * entry_p, 0),
        "qty": qty_coin,
        "atr_4h_entry": atr_4h,
        "partial_enabled": (qty_coin * entry_p) >= SWING_MIN_PARTIAL_SPLIT_IDR
    }, "OK"

def _catat_riwayat_swing(state, pos, alasan_exit, pnl_idr, pnl_pct, qty_sold=0.0, harga_jual=0.0, capital_sold_idr=0.0, dust_qty=0.0):
    """Mencatat riwayat penjualan ke JSON HANYA berdasarkan kuantitas yang benar-benar terjual (tanpa mencampur sisa dust)."""
    tz_wib = timezone(timedelta(hours=7))
    hist = state.setdefault("swing_trade_history", [])
    hist.append({
        "ts": time.time(),
        "waktu": datetime.now(tz_wib).strftime("%d/%m %H:%M"),
        "coin": pos["coin"],
        "rezim": pos.get("rezim", "-"),
        "setup": pos.get("setup_label", "-"),
        "alasan": alasan_exit,
        "entry_price_idr": pos.get("entry_price_idr", 0.0),
        "sell_price_idr": harga_jual,
        "qty_sold": qty_sold,
        "capital_sold_idr": round(capital_sold_idr, 0),
        "dust_qty": dust_qty,
        "pnl_idr": round(pnl_idr, 0),
        "pnl_pct": round(pnl_pct * 100.0, 2)
    })
    state["swing_trade_history"] = hist[-80:]

def _cek_sisa_dust_dompet(coin, qty_target_awal, qty_terjual_aktual, dompet_setelah=None):
    """Mengukur sisa dust aktual pasca jual agar JSON & Spreadsheet mencatat bersih hanya porsi yang laku."""
    if dompet_setelah is not None and LIVE_TRADING_ENABLED:
        return round(max(0.0, float(dompet_setelah["coins_free"].get(coin, 0.0))), 8)
    return round(max(0.0, float(qty_target_awal) - float(qty_terjual_aktual)), 8)

def kelola_siklus_mini_swing(state, analisa_swing, vault_info, dompet_asli, harga_live_map, pairs_meta):
    """
    Mesin Operasional Mini Swing 8-Tahap + Anti-Dust:
    1. Saat terbeli MOC: otomatis mengakumulasi dust lama koin tsb di dompet ke dalam posisi aktif agar nanti terjual semua.
    2. Saat jual (TP1/TP2/SL/Stale): menyapu seluruh saldo bebas (zero-dust); bila tetap ada sisa dust, JSON & Sheets
       hanya mencatat kuantitas, modal, dan PnL dari porsi yang benar-benar terjual.
    3. log_tx HANYA diisi saat koin benar-benar TERBELI atau benar-benar TERJUAL.
    """
    log_sw = []
    log_tx = []
    ada_aksi = False
    now_ts = time.time()
    rezim = analisa_swing.get("rezim", "SIDEWAYS")
    semua_koin = analisa_swing.get("semua_koin", {})

    # ==========================================================================
    # TAHAP 1: KAWAL ANTREAN ENTRY MOC (AKUMULASI DUST LAMA SAAT TERBELI)
    # ==========================================================================
    pending_sisa = []
    for p in state.get("swing_pending_entries", []):
        coin = p["coin"]
        harga_skrg = harga_live_map.get(coin, {}).get("last", p["entry_price_idr"])
        st_ord, det_ord = cek_status_order_indodax(coin, p.get("buy_oid"))
        terisi_sim = (not LIVE_TRADING_ENABLED) and (harga_skrg <= p["entry_price_idr"])

        if st_ord == "FILLED" or terisi_sim:
            exec_q, exec_p = ekstrak_eksekusi_order(det_ord, fallback_price=p["entry_price_idr"])
            entry_asli = bulatkan_harga_swing(coin, exec_p if exec_p > 0 else p["entry_price_idr"], pairs_meta)
            qty_order_filled = exec_q if exec_q > 0 else float(p["qty"])

            # AKUMULASI DUST: baca seluruh saldo bebas aktual koin tsb di Indodax (koin baru + dust lama)
            dust_ikut_akumulasi = 0.0
            if LIVE_TRADING_ENABLED:
                dompet_fill = ambil_saldo_lengkap_indodax()
                saldo_free_aktual = float(dompet_fill["coins_free"].get(coin, 0.0))
                if saldo_free_aktual > 0:
                    dust_ikut_akumulasi = round(max(0.0, saldo_free_aktual - qty_order_filled), 8)
                    qty_asli = format_qty_swing(coin, saldo_free_aktual, pairs_meta)
                else:
                    qty_asli = format_qty_swing(coin, qty_order_filled, pairs_meta)
            else:
                qty_asli = format_qty_swing(coin, qty_order_filled, pairs_meta)

            # Evaluasi ulang apakah total posisi (termasuk dust) cukup untuk split partial TP1/TP2 tanpa sisa dust
            nilai_total_pos = round(qty_asli * entry_asli, 0)
            partial_ok = nilai_total_pos >= SWING_MIN_PARTIAL_SPLIT_IDR

            pos_baru = {
                "coin": coin,
                "rezim": p["rezim"],
                "setup_label": p["setup_label"],
                "entry_price_idr": entry_asli,
                "virtual_sl_idr": p["sl_price_idr"],
                "initial_sl_idr": p["sl_price_idr"],
                "tp1_price_idr": p["tp1_price_idr"],
                "tp2_price_idr": p["tp2_price_idr"],
                "tp1_ratio": p["tp1_ratio"],
                "tp1_filled": False,
                "partial_enabled": partial_ok,
                "capital_idr": nilai_total_pos,
                "remaining_capital_idr": nilai_total_pos,
                "qty_total": qty_asli,
                "qty_remaining": qty_asli,
                "dust_accumulated_in": dust_ikut_akumulasi,
                "tp1_oid": None,
                "tp2_oid": None,
                "stale_oid": None,
                "stale_started_ts": 0.0,
                "highest_post_tp1": entry_asli,
                "atr_4h_ref": p["atr_4h_entry"],
                "filled_ts": now_ts
            }

            if pos_baru["partial_enabled"]:
                qty_tp1 = format_qty_swing(coin, qty_asli * pos_baru["tp1_ratio"], pairs_meta)
                sisa_estimasi = qty_asli - qty_tp1
                # Anti-dust split: pastikan sisa untuk TP2 tetap >= minimum order Indodax, jika tidak jual 100% di TP2
                if (sisa_estimasi * pos_baru["tp2_price_idr"]) < (MIN_LIMIT_ORDER_INDODAX_IDR * 1.05):
                    pos_baru["partial_enabled"] = False
                else:
                    res_tp1 = eksekusi_order_swing_moc(coin, "SELL", pos_baru["tp1_price_idr"], qty_tp1, pairs_meta=pairs_meta)
                    if apakah_order_sukses(res_tp1):
                        pos_baru["tp1_oid"] = str(res_tp1.get("orderId"))
                        pos_baru["qty_tp1"] = qty_tp1

            if not pos_baru["partial_enabled"]:
                res_tp2 = eksekusi_order_swing_moc(coin, "SELL", pos_baru["tp2_price_idr"], qty_asli, pairs_meta=pairs_meta)
                if apakah_order_sukses(res_tp2):
                    pos_baru["tp2_oid"] = str(res_tp2.get("orderId"))

            state["swing_positions"].append(pos_baru)
            ada_aksi = True
            mode_tp = f"Partial TP1({int(pos_baru['tp1_ratio']*100)}%):Rp{pos_baru['tp1_price_idr']:,}" if pos_baru["partial_enabled"] else f"All-In TP2:Rp{pos_baru['tp2_price_idr']:,}"
            info_dust_in = f" (+AkumDust:{dust_ikut_akumulasi:g})" if dust_ikut_akumulasi > 0 else ""
            pesan = (
                f"✅ [SWING TERBELI MOC] {coin} ({p['setup_label']}) Qty:{qty_asli:g}{info_dust_in} @ Rp{entry_asli:,} "
                f"(Modal:Rp{nilai_total_pos:,.0f}) | SL:Rp{pos_baru['virtual_sl_idr']:,} | {mode_tp}"
            )
            log_sw.append(pesan)
            log_tx.append(pesan)
            continue

        if st_ord in ("CANCELED", "EXPIRED", "REJECTED", "NOT_FOUND"):
            ada_aksi = True
            log_sw.append(f"🧹 [SWING MOC {st_ord}] Antrean beli {coin} #{p.get('buy_oid')} ditutup.")
            continue

        umur_menit = (now_ts - float(p.get("created_ts", now_ts))) / 60.0
        drift_pct = (harga_skrg - p["entry_price_idr"]) / max(1e-9, p["entry_price_idr"])
        if umur_menit >= SWING_MOC_TIMEOUT_MIN or drift_pct > SWING_MOC_MAX_DRIFT_PCT:
            batalkan_order_indodax(coin, p.get("buy_oid"))
            ada_aksi = True
            log_sw.append(f"🔄 [SWING BATAL MOC] {coin} dibatalkan (Umur:{umur_menit:.0f}m, Drift:{drift_pct*100:+.2f}%) - Anti kejar Market.")
            continue

        pending_sisa.append(p)
        log_sw.append(f"⏳ [SWING ANTRE MOC {umur_menit:.0f}m] {coin} @ Rp{p['entry_price_idr']:,} (Skrg: Rp{harga_skrg:,})")
    state["swing_pending_entries"] = pending_sisa

    # ==========================================================================
    # TAHAP 2: VIRTUAL OCO GUARDIAN (ANTI-DUST + CATAT MURNI PORSI TERJUAL)
    # ==========================================================================
    pos_tetap = []
    for pos in state.get("swing_positions", []):
        coin = pos["coin"]
        t_live = harga_live_map.get(coin, {})
        harga_skrg = float(t_live.get("last", pos["entry_price_idr"]))
        harga_bid = float(t_live.get("buy", harga_skrg))
        harga_ask = float(t_live.get("sell", harga_skrg))
        info_c = semua_koin.get(coin, {})
        atr_4h_skrg = float(info_c.get("atr_4h", pos.get("atr_4h_ref", 0.0))) or float(pos.get("atr_4h_ref", 0.0))
        entry_p = float(pos["entry_price_idr"])

        # A. Cek Stale Time-Stop Limit Order
        if pos.get("stale_oid"):
            st_st, det_st = cek_status_order_indodax(coin, pos["stale_oid"])
            if st_st == "FILLED" or (not LIVE_TRADING_ENABLED and harga_skrg >= harga_ask):
                ex_q, p_laku = ekstrak_eksekusi_order(det_st, fallback_price=harga_ask)
                q_sold = ex_q if ex_q > 0 else float(pos["qty_remaining"])
                cap_sold = round(q_sold * entry_p, 0)
                pnl_pct = ((1.0 - SWING_FEE_BUY_MAKER) * (p_laku / entry_p) * (1.0 - SWING_FEE_SELL_MAKER)) - 1.0
                pnl_idr = round(cap_sold * pnl_pct, 0)
                d_post = ambil_saldo_lengkap_indodax() if LIVE_TRADING_ENABLED else None
                dust_sisa = _cek_sisa_dust_dompet(coin, pos["qty_remaining"], q_sold, d_post)

                catat_pnl_ledger_swing(state, pnl_idr)
                catat_hasil_transaksi_ke_recovery(state, pnl_idr, coin)
                _catat_riwayat_swing(state, pos, "STALE_TIMESTOP_MAKER", pnl_idr, pnl_pct, q_sold, p_laku, cap_sold, dust_sisa)
                ada_aksi = True
                tag_dust = f" | SisaDust:{dust_sisa:g}" if dust_sisa > 0 else ""
                pesan = f"⌛ [SWING STALE EXIT MAKER] {coin} terjual {q_sold:g} @ Rp{p_laku:,} (Net:Rp{pnl_idr:+,.0f}{tag_dust})."
                log_sw.append(pesan)
                log_tx.append(pesan)
                continue
            elif (now_ts - float(pos.get("stale_started_ts", now_ts))) >= (SWING_STALE_MAKER_WAIT_MIN * 60.0):
                batalkan_order_indodax(coin, pos["stale_oid"])
                pos["stale_oid"] = None
                time.sleep(1.0)
                q_sapu = pos["qty_remaining"]
                if LIVE_TRADING_ENABLED:
                    d_sapu = ambil_saldo_lengkap_indodax()
                    q_sapu = format_qty_swing(coin, float(d_sapu["coins_free"].get(coin, pos["qty_remaining"])), pairs_meta)
                ok_sl, q_sold, p_mkt, _ = eksekusi_jual_darurat_swing(coin, harga_bid, q_sapu, pairs_meta=pairs_meta)
                if ok_sl and q_sold > 0:
                    cap_sold = round(q_sold * entry_p, 0)
                    pnl_pct = ((1.0 - SWING_FEE_BUY_MAKER) * (p_mkt / entry_p) * (1.0 - SWING_FEE_SELL_TAKER)) - 1.0
                    pnl_idr = round(cap_sold * pnl_pct, 0)
                    d_post = ambil_saldo_lengkap_indodax() if LIVE_TRADING_ENABLED else None
                    dust_sisa = _cek_sisa_dust_dompet(coin, q_sapu, q_sold, d_post)

                    catat_pnl_ledger_swing(state, pnl_idr)
                    catat_hasil_transaksi_ke_recovery(state, pnl_idr, coin)
                    _catat_riwayat_swing(state, pos, "STALE_TIMESTOP_MARKET", pnl_idr, pnl_pct, q_sold, p_mkt, cap_sold, dust_sisa)
                    ada_aksi = True
                    tag_dust = f" | SisaDust:{dust_sisa:g}" if dust_sisa > 0 else ""
                    pesan = f"⌛ [SWING STALE EXIT MARKET] {coin} terjual {q_sold:g} @ Rp{p_mkt:,} (Net:Rp{pnl_idr:+,.0f}{tag_dust})."
                    log_sw.append(pesan)
                    log_tx.append(pesan)
                    continue

        # B. Cek TP1 Terisi (Partial Mode) -> Geser Virtual SL ke BE+ & Pasang TP2 dengan SELURUH coins_free aktual (Anti-Dust)
        if pos.get("partial_enabled") and not pos.get("tp1_filled") and pos.get("tp1_oid"):
            st_tp1, det_tp1 = cek_status_order_indodax(coin, pos["tp1_oid"])
            laku_sim = (not LIVE_TRADING_ENABLED) and (harga_skrg >= pos["tp1_price_idr"])
            if st_tp1 == "FILLED" or laku_sim:
                ex_q, ex_p = ekstrak_eksekusi_order(det_tp1, fallback_price=pos["tp1_price_idr"])
                q_tp1 = ex_q if ex_q > 0 else float(pos.get("qty_tp1", pos["qty_total"] * pos["tp1_ratio"]))
                cap_tp1 = round(q_tp1 * entry_p, 0)
                pnl_pct_1 = ((1.0 - SWING_FEE_BUY_MAKER) * (ex_p / entry_p) * (1.0 - SWING_FEE_SELL_MAKER)) - 1.0
                pnl_idr_1 = round(cap_tp1 * pnl_pct_1, 0)

                catat_pnl_ledger_swing(state, pnl_idr_1)
                catat_hasil_transaksi_ke_recovery(state, pnl_idr_1, coin)
                _catat_riwayat_swing(state, pos, "TP1_SCALE_OUT", pnl_idr_1, pnl_pct_1, q_tp1, ex_p, cap_tp1, 0.0)

                pos["tp1_filled"] = True
                pos["tp1_oid"] = None
                # ANTI-DUST: baca seluruh sisa coins_free aktual di dompet untuk dipasang ke TP2
                if LIVE_TRADING_ENABLED:
                    d_sisa = ambil_saldo_lengkap_indodax()
                    sisa_aktual = format_qty_swing(coin, float(d_sisa["coins_free"].get(coin, 0.0)), pairs_meta)
                else:
                    sisa_aktual = format_qty_swing(coin, max(0.0, float(pos["qty_remaining"]) - q_tp1), pairs_meta)

                pos["qty_remaining"] = sisa_aktual
                pos["remaining_capital_idr"] = round(sisa_aktual * entry_p, 0)
                pos["highest_post_tp1"] = max(harga_skrg, ex_p)
                pos["virtual_sl_idr"] = max(
                    float(pos["virtual_sl_idr"]),
                    bulatkan_harga_swing(coin, entry_p * SWING_BE_PLUS_MULT, pairs_meta)
                )

                if pos["qty_remaining"] > 0 and (pos["qty_remaining"] * pos["tp2_price_idr"]) >= MIN_LIMIT_ORDER_INDODAX_IDR:
                    res_tp2 = eksekusi_order_swing_moc(coin, "SELL", pos["tp2_price_idr"], pos["qty_remaining"], pairs_meta=pairs_meta)
                    if apakah_order_sukses(res_tp2):
                        pos["tp2_oid"] = str(res_tp2.get("orderId"))

                ada_aksi = True
                pesan = (
                    f"🎯 [SWING TP1 TERCAPAI!] {coin} terjual {q_tp1:g} @ Rp{ex_p:,} (+Rp{pnl_idr_1:,.0f}). "
                    f"BE+ Rp{pos['virtual_sl_idr']:,} & TP2 sapu sisa {sisa_aktual:g} @ Rp{pos['tp2_price_idr']:,}!"
                )
                log_sw.append(pesan)
                log_tx.append(pesan)

        # B2. Mode Single-Tranche: tembus level TP1 -> aktifkan BE+ & Monotonic Trailing (tidak kirim Sheets)
        if (not pos.get("partial_enabled")) and (not pos.get("tp1_filled")) and harga_bid >= float(pos["tp1_price_idr"]):
            pos["tp1_filled"] = True
            pos["highest_post_tp1"] = harga_skrg
            pos["virtual_sl_idr"] = max(
                float(pos["virtual_sl_idr"]),
                bulatkan_harga_swing(coin, entry_p * SWING_BE_PLUS_MULT, pairs_meta)
            )
            ada_aksi = True
            log_sw.append(f"🛡️ [SWING BE+ AKTIF] {coin} melewati TP1 Rp{pos['tp1_price_idr']:,} -> V-SL dikunci di BE+ Rp{pos['virtual_sl_idr']:,}.")

        # C. Cek TP2 Terisi -> Catat murni porsi terjual & cek apakah ada sisa dust
        if pos.get("tp2_oid"):
            st_tp2, det_tp2 = cek_status_order_indodax(coin, pos["tp2_oid"])
            laku_sim2 = (not LIVE_TRADING_ENABLED) and (harga_skrg >= pos["tp2_price_idr"])
            if st_tp2 == "FILLED" or laku_sim2:
                ex_q2, ex_p2 = ekstrak_eksekusi_order(det_tp2, fallback_price=pos["tp2_price_idr"])
                q_sold2 = ex_q2 if ex_q2 > 0 else float(pos["qty_remaining"])
                cap_sold2 = round(q_sold2 * entry_p, 0)
                pnl_pct_2 = ((1.0 - SWING_FEE_BUY_MAKER) * (ex_p2 / entry_p) * (1.0 - SWING_FEE_SELL_MAKER)) - 1.0
                pnl_idr_2 = round(cap_sold2 * pnl_pct_2, 0)
                d_post2 = ambil_saldo_lengkap_indodax() if LIVE_TRADING_ENABLED else None
                dust_sisa2 = _cek_sisa_dust_dompet(coin, pos["qty_remaining"], q_sold2, d_post2)

                catat_pnl_ledger_swing(state, pnl_idr_2)
                catat_hasil_transaksi_ke_recovery(state, pnl_idr_2, coin)
                _catat_riwayat_swing(state, pos, "TP2_FULL_TARGET", pnl_idr_2, pnl_pct_2, q_sold2, ex_p2, cap_sold2, dust_sisa2)
                ada_aksi = True
                tag_dust = f" | SisaDust:{dust_sisa2:g}" if dust_sisa2 > 0 else ""
                pesan = f"🏆 [SWING TP2 PENUH!] {coin} terjual {q_sold2:g} @ Rp{ex_p2:,} (Net:+Rp{pnl_idr_2:,.0f} | +{pnl_pct_2*100:.2f}%{tag_dust})."
                log_sw.append(pesan)
                log_tx.append(pesan)
                continue

        # D. Update Monotonic ATR Trailing Stop pasca TP1
        if pos.get("tp1_filled") and atr_4h_skrg > 0:
            pos["highest_post_tp1"] = max(float(pos.get("highest_post_tp1", harga_skrg)), harga_skrg)
            kandidat_trail = bulatkan_harga_swing(coin, pos["highest_post_tp1"] - (1.5 * atr_4h_skrg), pairs_meta)
            if kandidat_trail > float(pos["virtual_sl_idr"]):
                pos["virtual_sl_idr"] = kandidat_trail
                log_sw.append(f"📈 [SWING TRAIL NAIK] {coin} Virtual SL naik monoton ke Rp{kandidat_trail:,}.")

        # E. Cek Pemicu Virtual SL / BE+ / Trailing Stop -> Sapu SELURUH saldo bebas (Anti-Dust)
        if harga_bid <= float(pos["virtual_sl_idr"]):
            for k_oid in ("tp1_oid", "tp2_oid", "stale_oid"):
                if pos.get(k_oid):
                    batalkan_order_indodax(coin, pos[k_oid])
                    pos[k_oid] = None
            if LIVE_TRADING_ENABLED:
                time.sleep(1.0)
                d_cek = ambil_saldo_lengkap_indodax()
                # Sapu seluruh coins_free aktual (termasuk dust) agar tidak ada sisa di dompet
                q_jual_sl = format_qty_swing(coin, float(d_cek["coins_free"].get(coin, pos["qty_remaining"])), pairs_meta)
            else:
                q_jual_sl = pos["qty_remaining"]

            ok_sl, q_sold_sl, p_eksekusi, _ = eksekusi_jual_darurat_swing(coin, harga_bid, q_jual_sl, pairs_meta=pairs_meta)
            if ok_sl and q_sold_sl > 0:
                cap_sold_sl = round(q_sold_sl * entry_p, 0)
                pnl_pct_sl = ((1.0 - SWING_FEE_BUY_MAKER) * (p_eksekusi / entry_p) * (1.0 - SWING_FEE_SELL_TAKER)) - 1.0
                pnl_idr_sl = round(cap_sold_sl * pnl_pct_sl, 0)
                d_post_sl = ambil_saldo_lengkap_indodax() if LIVE_TRADING_ENABLED else None
                dust_sisa_sl = _cek_sisa_dust_dompet(coin, q_jual_sl, q_sold_sl, d_post_sl)

                catat_pnl_ledger_swing(state, pnl_idr_sl)
                catat_hasil_transaksi_ke_recovery(state, pnl_idr_sl, coin)
                label_exit = "BE_PLUS_TRAIL_EXIT" if pos.get("tp1_filled") else "VIRTUAL_STOP_LOSS"
                _catat_riwayat_swing(state, pos, label_exit, pnl_idr_sl, pnl_pct_sl, q_sold_sl, p_eksekusi, cap_sold_sl, dust_sisa_sl)
                ada_aksi = True
                ikon = "🛡️" if pnl_idr_sl >= 0 else "🚨"
                tag_dust = f" | SisaDust:{dust_sisa_sl:g}" if dust_sisa_sl > 0 else ""
                pesan = f"{ikon} [SWING {label_exit}] {coin} terjual {q_sold_sl:g} @ Rp{p_eksekusi:,} (Net:Rp{pnl_idr_sl:+,.0f} | {pnl_pct_sl*100:+.2f}%{tag_dust})."
                log_sw.append(pesan)
                log_tx.append(pesan)
                continue

        # F. Cek Stale Time-Stop (48 Jam) -> Pasang Limit Maker sapu seluruh coins_free aktual
        umur_jam = (now_ts - float(pos.get("filled_ts", now_ts))) / 3600.0
        pnl_float_pct = (harga_bid - entry_p) / max(1e-9, entry_p)
        if (not pos.get("tp1_filled")) and (not pos.get("stale_oid")) and umur_jam >= SWING_STALE_HOURS and pnl_float_pct < SWING_STALE_MIN_PNL_PCT:
            for k_oid in ("tp1_oid", "tp2_oid"):
                if pos.get(k_oid):
                    batalkan_order_indodax(coin, pos[k_oid])
                    pos[k_oid] = None
            time.sleep(0.8)
            q_stale = pos["qty_remaining"]
            if LIVE_TRADING_ENABLED:
                d_st = ambil_saldo_lengkap_indodax()
                q_stale = format_qty_swing(coin, float(d_st["coins_free"].get(coin, pos["qty_remaining"])), pairs_meta)
            res_st = eksekusi_order_swing_moc(coin, "SELL", harga_ask, q_stale, pairs_meta=pairs_meta, order_type="LIMIT", tif="MOC")
            if apakah_order_sukses(res_st):
                pos["stale_oid"] = str(res_st.get("orderId"))
                pos["stale_started_ts"] = now_ts
                pos["qty_remaining"] = q_stale
                ada_aksi = True
                log_sw.append(f"⌛ [SWING STALE 48H] {coin} pasang Limit Maker jual {q_stale:g} @ Best Ask Rp{harga_ask:,}.")

        pos_tetap.append(pos)
        tp1_txt = "DONE" if pos["tp1_filled"] else f"Rp{pos['tp1_price_idr']:,}"
        log_sw.append(
            f"📌 [SWING HOLD {coin} | {pos['setup_label']}] Entry:Rp{entry_p:,} Skrg:Rp{harga_skrg:,} ({pnl_float_pct*100:+.2f}%) | "
            f"V-SL:Rp{pos['virtual_sl_idr']:,} | TP1:{tp1_txt} | TP2:Rp{pos['tp2_price_idr']:,}"
        )
    state["swing_positions"] = pos_tetap

    # ==========================================================================
    # TAHAP 3: PEMINDAIAN ENTRY BARU (HANYA ANTRE MOC -> BELUM KIRIM SHEETS)
    # ==========================================================================
    cb = state.get("swing_circuit_breaker", {})
    if now_ts < float(cb.get("cooling_off_until", 0.0)):
        sisa_jam = (float(cb["cooling_off_until"]) - now_ts) / 3600.0
        log_sw.append(f"🧊 [SWING CIRCUIT BREAKER AKTIF] Mode jeda wajib tersisa {sisa_jam:.1f} jam (ConsecSL:{cb.get('consecutive_losses', 0)}).")
        return state, log_sw, log_tx, ada_aksi

    max_slots = SWING_MAX_SLOTS_BULLISH if rezim == "BULLISH" else (SWING_MAX_SLOTS_SIDEWAYS if rezim == "SIDEWAYS" else SWING_MAX_SLOTS_BEARISH)
    total_terisi = len(state["swing_positions"]) + len(state["swing_pending_entries"])
    koin_aktif = {x["coin"] for x in state["swing_positions"]} | {x["coin"] for x in state["swing_pending_entries"]}

    if total_terisi >= max_slots:
        log_sw.append(f"⏸️ [SWING SLOT PENUH] {total_terisi}/{max_slots} slot aktif pada rezim {rezim}.")
        return state, log_sw, log_tx, ada_aksi

    kandidat_list = [v for c, v in analisa_swing.get("kandidat", {}).items() if c not in koin_aktif]
    kandidat_list.sort(key=lambda x: x["rs_info"]["roc_20"], reverse=True)

    if not kandidat_list:
        log_sw.append(f"⏸️ [SWING MENUNGGU SETUP | Rezim:{rezim}] Belum ada koin non-BTC lolos 1D-4H-1H & Order Book.")
        return state, log_sw, log_tx, ada_aksi

    swing_free_tersisa = float(vault_info["swing_free_idr"])
    swing_eq_aktif = float(vault_info["swing_equity_idr"])

    for kand in kandidat_list:
        if total_terisi >= max_slots:
            break
        plan, alasan = hitung_parameter_entry_dan_sizing_swing(
            kand, swing_eq_aktif, swing_free_tersisa, bool(cb.get("half_size_active", False)), pairs_meta
        )
        if not plan:
            log_sw.append(f"🚫 [SWING TOLAK {kand['coin']}] {alasan}")
            continue

        res_buy = eksekusi_order_swing_moc(
            kand["coin"], "BUY", plan["entry_price_idr"], plan["qty"], pairs_meta=pairs_meta, order_type="LIMIT", tif="MOC"
        )
        if apakah_order_sukses(res_buy):
            oid_b = str(res_buy.get("orderId"))
            state["swing_pending_entries"].append({
                "coin": kand["coin"],
                "rezim": rezim,
                "setup_label": kand["setup_label"],
                "buy_oid": oid_b,
                "entry_price_idr": plan["entry_price_idr"],
                "sl_price_idr": plan["sl_price_idr"],
                "tp1_price_idr": plan["tp1_price_idr"],
                "tp2_price_idr": plan["tp2_price_idr"],
                "tp1_ratio": plan["tp1_ratio"],
                "capital_idr": plan["capital_idr"],
                "qty": plan["qty"],
                "atr_4h_entry": plan["atr_4h_entry"],
                "partial_enabled": plan["partial_enabled"],
                "net_rrr": plan["net_rrr"],
                "created_ts": now_ts
            })
            swing_free_tersisa = max(0.0, swing_free_tersisa - plan["capital_idr"])
            total_terisi += 1
            ada_aksi = True
            # Catatan: baru antre beli (belum terbeli), jadi HANYA masuk log_sw (konsol), TIDAK masuk log_tx (Sheets)
            log_sw.append(
                f"🚀 [SWING ANTRE MOC BELI | {rezim} - {kand['setup_label']}] {kand['coin']} @ Rp{plan['entry_price_idr']:,} "
                f"(Modal:Rp{plan['capital_idr']:,.0f} | SL:Rp{plan['sl_price_idr']:,} | TP1:Rp{plan['tp1_price_idr']:,} | "
                f"TP2:Rp{plan['tp2_price_idr']:,} | NetRRR:{plan['net_rrr']}:1 | RS20:{kand['rs_info']['roc_20']*100:+.2f}%)"
            )
        else:
            log_sw.append(f"⚠️ [SWING MOC DITOLAK {kand['coin']}] {res_buy} (Tidak pernah kejar Market Buy).")

    return state, log_sw, log_tx, ada_aksi

def cek_apakah_butuh_pengawasan_intensif(state, analisa_swing=None):
    alasan = []
    if FORCE_CONTINUOUS_WATCH:
        alasan.append("FORCE_CONTINUOUS_WATCH aktif")
    if state.get("swing_pending_entries"):
        alasan.append(f"{len(state['swing_pending_entries'])} order MOC Mini Swing menunggu terisi")
    if state.get("swing_positions"):
        alasan.append(f"{len(state['swing_positions'])} posisi Mini Swing aktif dikawal Virtual OCO")
    return bool(alasan), alasan

# ==============================================================================
# BAGIAN 8: RINGKASAN PATROLI & DIAGNOSA PER-LAPIS
# ==============================================================================
def format_durasi_siklus(detik_total):
    detik = max(0, int(detik_total))
    hari = detik // 86400
    sisa = detik % 86400
    jam = sisa // 3600
    menit = (sisa % 3600) // 60
    return f"{hari} hari, {jam} jam, {menit} menit"

def hitung_ringkasan_keuangan_grid(cycle, harga_idr_map):
    """Menghitung modal terpakai, modal holding, dan floating PnL real-time (berbasis harga Bid)."""
    if not cycle:
        return 0.0, 0.0, 0.0, 0.0
    coin = cycle["coin"]
    harga_bid = harga_idr_map.get(coin, {}).get("buy", harga_idr_map.get(coin, {}).get("last", 0.0))
    modal_aktif_total = 0.0
    modal_holding = 0.0
    floating_pnl_idr = 0.0

    for t in cycle.get("tiers", []):
        for lp in t["layers"].values():
            st = lp.get("status", "")
            cap = float(lp.get("capital_idr", 0.0))
            bp = float(lp.get("buy_price", 0.0))
            qty = float(lp.get("qty", 0.0))
            if st in ("WAIT_BUY", "HOLDING"):
                modal_aktif_total += cap
            if st == "HOLDING" and bp > 0 and harga_bid > 0:
                modal_holding += (bp * qty) if qty > 0 else cap
                floating_pnl_idr += (harga_bid - bp) * qty

    dd_pct = (floating_pnl_idr / modal_holding) if modal_holding > 0 else 0.0
    return round(modal_aktif_total, 0), round(modal_holding, 0), round(floating_pnl_idr, 0), dd_pct

def buat_kesimpulan_patroli_dinamis(state, peta_analisa, harga_idr_map=None, analisa_swing=None, vault_info=None):
    total_koin_pasar = len(peta_analisa)
    koin_uptrend = [k for k, v in peta_analisa.items() if v.get("tren") == "UPTREND"]
    koin_siap_beli = [f"{k}({v['gaya']}:Skor {v['skor']}|Step+{v['tp_target_pct']}%)" for k, v in peta_analisa.items() if v.get("siap_entry")]
    rata_rsi_5m = (sum(v.get("rsi", 50.0) for v in peta_analisa.values()) / total_koin_pasar) if total_koin_pasar > 0 else 50.0
    kandidat_terkuat = max(peta_analisa.values(), key=lambda x: x.get("skor", 0.0)) if peta_analisa else None
    info_skor_tertinggi = f"{kandidat_terkuat['coin']} (Skor:{kandidat_terkuat['skor']})" if kandidat_terkuat else "-"
    sumber_grafik = kandidat_terkuat.get("sumber_ohlc", "INDODAX-IDR") if kandidat_terkuat else "INDODAX-IDR"
    info_btc = peta_analisa.get("BTC", {})
    kompas_btc_str = f"BTCIDR {info_btc.get('tren_detail', '-')} (RSI 5M:{info_btc.get('rsi', '-')})"
    defisit_rec = float(state.get("loss_to_recover_idr", 0.0))
    status_rec_str = f"AKTIF (Target Pulihkan Rp{defisit_rec:,.0f})" if defisit_rec > 0 else "Aman (0 Defisit)"

    batas_7h = time.time() - (SL_MEMORY_RETENTION_HOURS * 3600.0)
    outcome_7h = [m for m in state.get("sl_trade_outcome_memory", []) if float(m.get("ts", 0.0)) >= batas_7h]

    if outcome_7h:
        all_w = [m for m in outcome_7h if m.get("hasil") == "MENANG"]
        all_l = [m for m in outcome_7h if m.get("hasil") == "KALAH"]
        tot_w, tot_l = len(all_w), len(all_l)
        wr_tot = (tot_w / float(tot_w + tot_l)) * 100.0
        avg_w_tot = (sum(float(m.get("pnl_pct", 0.0)) for m in all_w) / tot_w) if tot_w else 0.0
        avg_l_tot = (sum(float(m.get("pnl_pct", 0.0)) for m in all_l) / tot_l) if tot_l else 0.0
        rekap_wr_total = f"{tot_w}W/{tot_l}L (WR {wr_tot:.0f}% | Avg Win:+{avg_w_tot:.2f}% | Avg Loss:{avg_l_tot:.2f}%)"

        koin_unik = sorted({m.get("coin", "?") for m in outcome_7h})
        daftar_wr_koin = []
        for ck in koin_unik:
            mk = [m for m in outcome_7h if m.get("coin") == ck]
            kw = [m for m in mk if m.get("hasil") == "MENANG"]
            kl = [m for m in mk if m.get("hasil") == "KALAH"]
            wrk = (len(kw) / float(len(mk))) * 100.0
            aw = (sum(float(m.get("pnl_pct", 0.0)) for m in kw) / len(kw)) if kw else 0.0
            al = (sum(float(m.get("pnl_pct", 0.0)) for m in kl) / len(kl)) if kl else 0.0
            daftar_wr_koin.append(f"{ck}: {len(kw)}W/{len(kl)}L (WR {wrk:.0f}%, +{aw:.2f}%/{al:.2f}%)")
        rekap_wr_koin = " | ".join(daftar_wr_koin)
    else:
        rekap_wr_total = "Belum ada transaksi selesai dlm 7 hari terakhir"
        rekap_wr_koin = "-"

    batas_grid_7h = time.time() - (GRID_MEMORY_RETENTION_HOURS * 3600.0)
    mem_grid_7h = [m for m in state.get("grid_experience_memory", []) if float(m.get("ts", 0.0)) >= batas_grid_7h]
    if mem_grid_7h:
        tot_siklus = len(mem_grid_7h)
        tot_panen_7h = sum(int(m.get("bounce_count", 0)) for m in mem_grid_7h)
        tot_pnl_7h = sum(float(m.get("total_pnl_idr", 0.0)) for m in mem_grid_7h)
        jml_sentuh_b3 = sum(1 for m in mem_grid_7h if m.get("b3_ever_touched"))
        rekap_grid_7h = f"{tot_siklus} Siklus ({tot_panen_7h}x Panen | Net: Rp{tot_pnl_7h:+,.0f} | Sentuh b3: {jml_sentuh_b3}x)"
    else:
        rekap_grid_7h = "Belum ada siklus Grid selesai dlm 7 hari terakhir"

    ringkasan_pasar = (
        f"Pasar [{sumber_grafik} 5M+15M+1H+4H]: {len(koin_uptrend)}/{total_koin_pasar} koin UPTREND | "
        f"Rata-rata RSI 5M (Wilder): {rata_rsi_5m:.1f} | Kompas: {kompas_btc_str} | Sinyal Tertinggi: {info_skor_tertinggi}\n"
        f"   -> Mode Recovery Balik Modal: {status_rec_str}\n"
        f"   -> Statistik Memori 7H (Total Bot): {rekap_wr_total}\n"
        f"   -> Win Rate 7H Per Koin: {rekap_wr_koin}\n"
        f"   -> Memori Siklus Grid 7H: {rekap_grid_7h}\n"
        f"   -> Koin SIAP ENTRY Grid ({len(koin_siap_beli)} koin): {', '.join(koin_siap_beli) or 'Belum ada (tunggu struktur & area value)'}"
    )

    detail_diagnosa_koin = []
    info_grid_md = "-"

    if GRID_MODE_ENABLED:
        cycle = state.get("grid_cycle")
        if cycle:
            coin = cycle["coin"]
            info = peta_analisa.get(coin, {})
            tiers = cycle.get("tiers", [])
            skrg = info.get("harga_idr", tiers[0]["layers"]["b1"]["buy_price"] if tiers else 0.0)
            harga_bid = info.get("harga_bid", skrg)
            tren_k = info.get("tren_detail", "-")
            prediksi_k = info.get("prediksi", "-")
            lampu_4h = info.get("lampu_4h", "-")
            bounces = int(cycle.get("bounce_count", 0))
            done_tiers = int(cycle.get("completed_tiers_count", 0))
            realized_grid = float(cycle.get("realized_grid_profit_idr", 0.0))
            durasi_str = format_durasi_siklus(time.time() - float(cycle.get("created_ts", time.time())))

            harga_ref = harga_idr_map or {coin: {"last": skrg, "buy": harga_bid}}
            modal_aktif, _, floating_grid_idr, dd_pct = hitung_ringkasan_keuangan_grid(cycle, harga_ref)

            baris_tiap_lapis = []
            for t in tiers:
                rincian_b = []
                tp_finis_lapis = float(t["layers"]["b1"]["tp_price"])
                for nama_lp in ("b1", "b2", "b3"):
                    lp = t["layers"].get(nama_lp, {})
                    st_lp = lp.get("status", "-")
                    bp = float(lp.get("buy_price", 0.0))
                    tp = float(lp.get("tp_price", 0.0))
                    if st_lp == "HOLDING" and bp > 0:
                        pnl_lp_pct = ((harga_bid - bp) / bp) * 100.0
                        tag_oid = f"TP#{lp.get('sell_oid')}" if lp.get("sell_oid") else "TP:REARM"
                        rincian_b.append(f"{nama_lp.upper()}:HOLD({pnl_lp_pct:+.2f}%|{tag_oid}@Rp{tp:,.0f})")
                    else:
                        rincian_b.append(f"{nama_lp.upper()}:{st_lp}(@Rp{bp:,.0f})")
                baris_tiap_lapis.append(
                    f"     Lapis {t['tier_no']} [{t.get('mode_4h', '-')}|Step {t.get('step_pct', 0.015)*100:.1f}%|Finis TP b1:Rp{tp_finis_lapis:,.0f}]: {' | '.join(rincian_b)}"
                )

            info_grid_md = (
                f"{coin} | Lapis Aktif: {len(tiers)}/{GRID_MAX_TIERS} (Selesai: {done_tiers}) | Durasi: {durasi_str} | "
                f"Modal Aktif: Rp{modal_aktif:,.0f} | Panen: {bounces}x (+Rp{realized_grid:,.0f}) | "
                f"Floating: Rp{floating_grid_idr:+,.0f} ({dd_pct*100:+.2f}%)"
            )
            detail_diagnosa_koin.append(
                f"   * [GRID PER-LAPIS | Aktif {len(tiers)}/{GRID_MAX_TIERS} | Selesai {done_tiers} | {durasi_str}] {coin} @ Rp{skrg:,.0f} (4H:{lampu_4h}) -> {prediksi_k}\n"
                f"     Tren: [{tren_k}] | Modal Aktif: Rp{modal_aktif:,.0f}\n"
                f"     Panen Siklus: {bounces}x (+Rp{realized_grid:,.0f}) | Floating: Rp{floating_grid_idr:+,.0f} ({dd_pct*100:+.2f}%)\n"
                + "\n".join(baris_tiap_lapis)
            )
        else:
            info_grid_md = "Cash is King (Menunggu syarat Grid Lapis 1)"
            detail_diagnosa_koin.append(
                f"   * Belum ada siklus Grid aktif (100% Cash is King - Menunggu 4H != MERAH, M15/H1/5M valid & Skor >= {GRID_MIN_SCORE_ENTRY})."
            )
    if SWING_MODE_ENABLED:
        rezim_sw = (analisa_swing or {}).get("rezim", "-")
        btc_sw = (analisa_swing or {}).get("btc_info", {})
        detail_diagnosa_koin.append(
            f"   * [MINI SWING NON-BTC | Rezim:{rezim_sw} | BTC 4H ADX:{btc_sw.get('adx_4h', '-')} CHOP:{btc_sw.get('chop_4h', '-')}] "
            f"Aktif:{len(state.get('swing_positions', []))} | Pending MOC:{len(state.get('swing_pending_entries', []))}"
        )
        for pos in state.get("swing_positions", []):
            skrg_s = (harga_idr_map or {}).get(pos["coin"], {}).get("last", pos["entry_price_idr"])
            pnl_s = ((skrg_s - pos["entry_price_idr"]) / max(1e-9, pos["entry_price_idr"])) * 100.0
            tp1_txt = "DONE" if pos["tp1_filled"] else f"Rp{pos['tp1_price_idr']:,}"
            detail_diagnosa_koin.append(
                f"     - SWING {pos['coin']} ({pos['setup_label']}): Entry Rp{pos['entry_price_idr']:,} -> Skrg Rp{skrg_s:,} ({pnl_s:+.2f}%) "
                f"| V-SL:Rp{pos['virtual_sl_idr']:,} | TP1:{tp1_txt} | TP2:Rp{pos['tp2_price_idr']:,}"
            )
    if vault_info:
        detail_diagnosa_koin.append(
            f"   * [LEDGER DOMPET] IDR Bebas: Rp{vault_info['idr_free_wallet']:,.0f} | "
            f"Grid (Cap Rp{vault_info['grid_cap_aktif']:,.0f}): Eq Rp{vault_info['grid_equity_idr']:,.0f} (Bebas Rp{vault_info['grid_free_idr']:,.0f}) | "
            f"Mini Swing (Cap Rp{vault_info['swing_cap_max']:,.0f}): Eq Rp{vault_info['swing_equity_idr']:,.0f} (Bebas Rp{vault_info['swing_free_idr']:,.0f}) | "
            f"Surplus Cadangan: Rp{vault_info['reserve_surplus_idr']:,.0f} (Izin Lapis Baru Grid: {'YA' if vault_info['boleh_buka_lapis_baru'] else 'BELUM'})"
        )

    teks_diagnosa = "\n".join(detail_diagnosa_koin) if detail_diagnosa_koin else "   * Belum ada posisi aktif (100% Cash is King)."
    judul_mode = "PATROLI DUAL-ENGINE (GRID BTC + MINI SWING NON-BTC) SELESAI"

    teks_final = (
        f"🟢 [{judul_mode} | Profit Hari Ini: Rp{state.get('realized_profit_today_idr', 0):,.0f} ({state.get('completed_trades_today', 0)} Trade)]\n"
        f"📊 DIAGNOSA PORTOFOLIO & PREDIKSI CANDLESTICK RUPIAH INDODAX (5M + 15M + 1H + 4H):\n"
        f"{teks_diagnosa}\n"
        f"   -> {ringkasan_pasar}"
    )

    summary_file = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if summary_file:
        try:
            tz_wib = timezone(timedelta(hours=7))
            waktu_run = datetime.now(tz_wib).strftime("%Y-%m-%d %H:%M:%S WIB")
            baris_grid_md = f"- **Status Grid Per-Lapis:** {info_grid_md}\n" if GRID_MODE_ENABLED else ""
            md_summary = (
                f"### 📊 Ringkasan Patroli & Win Rate 7 Hari ({waktu_run})\n"
                f"- **Profit Hari Ini:** Rp{state.get('realized_profit_today_idr', 0):,.0f} ({state.get('completed_trades_today', 0)} Trade)\n"
                f"{baris_grid_md}"
                f"- **Memori Siklus Grid 7H:** {rekap_grid_7h}\n"
                f"- **Win Rate 7H (Total Bot):** {rekap_wr_total}\n"
                f"- **Win Rate 7H (Per Koin):** {rekap_wr_koin}\n"
                f"- **Mode Recovery:** {status_rec_str}\n\n"
                f"```text\n{teks_final}\n```\n"
            )
            with open(summary_file, "a", encoding="utf-8") as sf:
                sf.write(md_summary)
        except Exception:
            pass

    return teks_final

# ==============================================================================
# BAGIAN 9: LAPORAN KE GOOGLE SHEETS (AKURAT UNTUK MODE GRID & MODE SCALPING)
# ==============================================================================
def lapor_ke_google_sheets(state, log_khusus_transaksi, dompet, harga_live_map=None):
    tz_wib = timezone(timedelta(hours=7))
    waktu_lokal = datetime.now(tz_wib).strftime("%Y-%m-%d %H:%M:%S")
    catatan_transaksi = " | ".join(log_khusus_transaksi)[:490]

    modal_aktif = 0.0
    floating_pnl = 0.0
    ringkasan_lapis = "Grid OFF"
    pasangan_str = "Grid OFF"
    info_rsi_str = f"Rec:Rp{state.get('loss_to_recover_idr', 0):,.0f}"

    if GRID_MODE_ENABLED:
        cycle = state.get("grid_cycle")
        if cycle:
            coin = cycle["coin"]
            tiers = cycle.get("tiers", [])
            modal_aktif, _, floating_pnl, dd_pct = hitung_ringkasan_keuangan_grid(cycle, harga_live_map or {})
            ringkasan_lapis = " || ".join(
                [
                    f"L{t['tier_no']}(TPb1:Rp{t['layers']['b1']['tp_price']:,.0f})["
                    + " ".join(f"{k}:{v['status']}" for k, v in t["layers"].items())
                    + "]"
                    for t in tiers
                ]
            )
            pasangan_str = f"INDODAX GRID ({coin} | {len(tiers)}/{GRID_MAX_TIERS} Lapis)"
            info_rsi_str = (
                f"Panen:{cycle.get('bounce_count', 0)}x | LapisDone:{cycle.get('completed_tiers_count', 0)} "
                f"| DD:{dd_pct*100:+.2f}%"
            )
        else:
            ringkasan_lapis = "Siklus selesai / Cash is King"
            pasangan_str = "INDODAX GRID (Cash is King)"

    modal_swing_aktif = hitung_modal_terpakai_swing(state) if SWING_MODE_ENABLED else 0.0
    floating_swing = 0.0
    if SWING_MODE_ENABLED and harga_live_map:
        for sp in state.get("swing_positions", []):
            hb = harga_live_map.get(sp["coin"], {}).get("buy", sp["entry_price_idr"])
            floating_swing += (hb - float(sp["entry_price_idr"])) * float(sp.get("qty_remaining", 0.0))
    ringkasan_swing_str = ", ".join(
        [f"{sp['coin']}[{sp['setup_label']}:VSL {sp['virtual_sl_idr']:,}]" for sp in state.get("swing_positions", [])]
    ) or "Swing Cash"
    pasangan_str = f"DUAL (GRID:{pasangan_str} | SWING:{len(state.get('swing_positions', []))} Pos)"
    modal_aktif = round(modal_aktif + modal_swing_aktif, 0)
    floating_pnl = round(floating_pnl + floating_swing, 0)
    ringkasan_lapis = f"{ringkasan_lapis} || SWING: {ringkasan_swing_str}"

    payload = {
        "tanggal": waktu_lokal,
        "pasangan": pasangan_str,
        "modal_aktif_idr": modal_aktif,
        "harga_acuan_idr": round(dompet.get("idr_free", 0.0), 0),
        "jumlah_grid_tereksekusi": state["completed_trades_today"],
        "profit_terealisasi_idr": state["realized_profit_today_idr"],
        "floating_pnl_idr": floating_pnl,
        "tren_1h": ringkasan_lapis[:490],
        "rsi_14": info_rsi_str,
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
# MESIN GRID 3-LAPIS MANDIRI (TIAP LAPIS SELESAI DI TP b1 + SELF-HEALING + AI)
# ==============================================================================
def _hitung_fee_roundtrip_grid(lp):
    """Menghitung total fee beli+jual berdasarkan tipe eksekusi aktual (MOC vs GTC)."""
    fee_beli = FEE_ONEWAY_MAKER_PCT if str(lp.get("buy_tif", "MOC")).upper() == "MOC" else FEE_ONEWAY_TAKER_PCT
    fee_jual = FEE_ONEWAY_MAKER_PCT if str(lp.get("sell_tif", "MOC")).upper() == "MOC" else FEE_ONEWAY_TAKER_PCT
    return fee_beli + fee_jual

def _hitung_qty_grid_akumulasi_dust(cycle, coin, qty_order_filled, harga_acuan, dompet_baru, exclude_lp=None):
    """
    Akumulasi dust aman khusus Grid BTC (mendukung banyak jaring HOLDING bersamaan):
    1. Mengurangi coins_free dengan qty jaring lain yang HOLDING tapi belum terkunci di order jual (sell_oid=None).
    2. Jika ada sisa dust (< Rp25.000) di coins_free, otomatis digabung ke jaring yang baru terbeli agar terjual habis di TP.
    3. Jika ada saldo BTC besar hasil beli manual (>= Rp25.000), tidak disentuh/dicuri.
    Return: (qty_final, dust_terakumulasi)
    """
    if not LIVE_TRADING_ENABLED or not dompet_baru:
        return format_qty_koin(coin, qty_order_filled), 0.0

    qty_holding_bebas_lain = 0.0
    if cycle:
        for t in cycle.get("tiers", []):
            for lp_cek in t.get("layers", {}).values():
                if lp_cek is exclude_lp:
                    continue
                if lp_cek.get("status") == "HOLDING" and not lp_cek.get("sell_oid"):
                    qty_holding_bebas_lain += float(lp_cek.get("qty", 0.0))

    free_tersedia = max(0.0, float(dompet_baru["coins_free"].get(coin, 0.0)) - qty_holding_bebas_lain)
    if free_tersedia <= 0:
        return format_qty_koin(coin, qty_order_filled), 0.0

    if free_tersedia <= qty_order_filled:
        return format_qty_koin(coin, free_tersedia), 0.0

    kelebihan = free_tersedia - qty_order_filled
    if harga_acuan > 0 and (kelebihan * harga_acuan) < MIN_LIMIT_ORDER_INDODAX_IDR:
        qty_final = format_qty_koin(coin, free_tersedia)
        dust_in = round(max(0.0, qty_final - qty_order_filled), 8)
        return qty_final, dust_in

    return format_qty_koin(coin, qty_order_filled), 0.0

def _catat_riwayat_jual_grid(state, coin, tier_no, nama_lp, buy_price, sell_price, qty_sold, capital_sold_idr, pnl_idr, net_pct, dust_qty=0.0):
    """Mencatat penjualan Grid ke JSON murni berdasarkan kuantitas yang benar-benar terjual (tanpa sisa dust)."""
    tz_wib = timezone(timedelta(hours=7))
    hist = state.setdefault("grid_trade_history", [])
    hist.append({
        "ts": time.time(),
        "waktu": datetime.now(tz_wib).strftime("%d/%m %H:%M"),
        "coin": coin,
        "tier": f"L{tier_no}_{nama_lp.upper()}",
        "buy_price_idr": buy_price,
        "sell_price_idr": sell_price,
        "qty_sold": qty_sold,
        "capital_sold_idr": round(capital_sold_idr, 0),
        "dust_qty": dust_qty,
        "pnl_idr": round(pnl_idr, 0),
        "pnl_pct": round(net_pct * 100.0, 2)
    })
    state["grid_trade_history"] = hist[-80:]

def _buat_struktur_tier_baru(coin, tier_no, p1, step_pct, mode_4h, oid_b1, qty_b1, now_ts, buy_tif_b1="MOC"):
    """Setiap lapis (L1, L2, L3) memiliki target TP b1 lokal sendiri (p1 * (1 + step_pct))."""
    tp1 = bulatkan_harga_indodax(coin, p1 * (1.0 + step_pct))
    p2 = bulatkan_harga_indodax(coin, p1 * (1.0 - step_pct))
    p3 = bulatkan_harga_indodax(coin, p1 * (1.0 - (step_pct * 2.0)))
    return {
        "tier_no": tier_no,
        "mode_4h": mode_4h,
        "step_pct": step_pct,
        "created_ts": now_ts,
        "status": "ACTIVE",
        "realized_tier_profit_idr": 0.0,
        "layers": {
            "b1": {"buy_price": p1, "tp_price": tp1, "base_tp_price": tp1, "status": "WAIT_BUY", "buy_oid": oid_b1, "sell_oid": None, "buy_tif": buy_tif_b1, "sell_tif": "MOC", "qty": qty_b1, "capital_idr": round(qty_b1 * p1, 0)},
            "b2": {"buy_price": p2, "tp_price": p1,  "base_tp_price": p1,  "status": "ARMED",    "buy_oid": None,   "sell_oid": None, "buy_tif": "MOC",      "sell_tif": "MOC", "qty": 0.0,    "capital_idr": GRID_CAPITAL_PER_LAYER_IDR},
            "b3": {"buy_price": p3, "tp_price": p2,  "base_tp_price": p2,  "status": "ARMED",    "buy_oid": None,   "sell_oid": None, "buy_tif": "MOC",      "sell_tif": "MOC", "qty": 0.0,    "capital_idr": GRID_CAPITAL_PER_LAYER_IDR},
        }
    }

def _promosikan_b1_dan_pasang_jaring(coin, tier, qty_aktual, harga_eksekusi, info_pasar):
    """Mempromosikan b1 ke HOLDING, memasang TP b1 aman, serta memasang jaring b2 & b3."""
    layers = tier["layers"]
    step_pct = float(tier.get("step_pct", GRID_STEP_GREEN_PCT))

    if harga_eksekusi > 0:
        p1_aktual = bulatkan_harga_indodax(coin, harga_eksekusi)
        tp1_baru = bulatkan_harga_indodax(coin, p1_aktual * (1.0 + step_pct))
        p2_baru = bulatkan_harga_indodax(coin, p1_aktual * (1.0 - step_pct))
        p3_baru = bulatkan_harga_indodax(coin, p1_aktual * (1.0 - (step_pct * 2.0)))

        layers["b1"]["buy_price"] = p1_aktual
        layers["b1"]["tp_price"] = tp1_baru
        layers["b1"]["base_tp_price"] = tp1_baru

        layers["b2"]["buy_price"] = p2_baru
        layers["b2"]["tp_price"] = p1_aktual
        layers["b2"]["base_tp_price"] = p1_aktual

        layers["b3"]["buy_price"] = p3_baru
        layers["b3"]["tp_price"] = p2_baru
        layers["b3"]["base_tp_price"] = p2_baru

    layers["b1"]["qty"] = qty_aktual
    layers["b1"]["capital_idr"] = round(qty_aktual * float(layers["b1"]["buy_price"]), 0)
    layers["b1"]["status"] = "HOLDING"
    layers["b1"]["buy_oid"] = None

    # 1. Pasang TP b1 secara aman (MOC -> fallback GTC)
    ok_tp1, res_tp1, harga_tp1, tif_tp1 = pasang_order_grid_aman(
        coin, "SELL", layers["b1"]["base_tp_price"], qty_aktual, info_pasar=info_pasar, paksa_gtc_fallback=True
    )
    if ok_tp1:
        layers["b1"]["sell_oid"] = str(res_tp1.get("orderId"))
        layers["b1"]["tp_price"] = harga_tp1
        layers["b1"]["sell_tif"] = tif_tp1

    # 2. Pasang jaring b2 dan b3 secara aman
    for nama_lp in ("b2", "b3"):
        lp = layers[nama_lp]
        q_lp = hitung_kuantitas_koin(coin, lp["capital_idr"], lp["buy_price"])
        ok_lp, res_lp, harga_lp, tif_lp = pasang_order_grid_aman(
            coin, "BUY", lp["buy_price"], q_lp, info_pasar=info_pasar, paksa_gtc_fallback=True
        )
        if ok_lp:
            lp["status"] = "WAIT_BUY"
            lp["buy_oid"] = str(res_lp.get("orderId"))
            lp["buy_price"] = harga_lp
            lp["buy_tif"] = tif_lp
            lp["qty"] = q_lp
            lp["capital_idr"] = round(q_lp * harga_lp, 0)
        else:
            lp["status"] = "ARMED"
            lp["buy_oid"] = None

def kelola_siklus_grid_3_lapis(state, peta_analisa, dompet, harga_live_map=None):
    """
    Mesin Grid 3-Lapis Per-Tier:
    - Tiap lapis (L1, L2, L3) memiliki target finis sendiri di TP b1-nya.
    - Begitu b1 sebuah lapis TP dan b2/b3 tidak holding -> lapis selesai, cancel sisa buy, arsipkan & cairkan kas!
    - Lapis yang selesai dihapus dari daftar tiers aktif sehingga pemicu Lapis 2/3 selalu bekerja pada lapis aktif terbawah.
    - Dilengkapi Self-Healing (anti-yatim MOC), handler PARTIALLY_FILLED, validasi Gemini AI, & Invalidation Guard.
    """
    log_grid = []
    log_tx = []
    ada_aksi = False
    now_ts = time.time()
    cycle = state.get("grid_cycle")

    # Migrasi otomatis jika ada state grid lama
    if cycle and "tiers" not in cycle and "layers" in cycle:
        cycle["tiers"] = [{
            "tier_no": 1,
            "mode_4h": "HIJAU",
            "step_pct": GRID_STEP_GREEN_PCT,
            "created_ts": cycle.get("created_ts", now_ts),
            "status": "ACTIVE",
            "realized_tier_profit_idr": 0.0,
            "layers": cycle.pop("layers")
        }]
    if cycle:
        cycle.setdefault("completed_tiers", [])
        cycle.setdefault("completed_tiers_count", 0)
        # Pastikan tidak ada tier lama berstatus DONE yang masih nyangkut di daftar aktif
        tiers_aktif_saja = [t for t in cycle.get("tiers", []) if t.get("status") != "DONE"]
        if len(tiers_aktif_saja) != len(cycle.get("tiers", [])):
            cycle["tiers"] = tiers_aktif_saja

    # ==========================================================================
    # TAHAP A: BELUM ADA SIKLUS -> BUKA LAPIS 1 (4H 3-MODE + ANTI-PUCUK + GEMINI)
    # ==========================================================================
    if not cycle or not cycle.get("tiers"):
        if cycle and not cycle.get("tiers"):
            state["grid_cycle"] = None
            cycle = None

        info_btc = peta_analisa.get("BTC", {})
        if info_btc.get("lampu_4h") == "MERAH":
            log_grid.append(
                f"🔴 [VETO CRASH/BLEED BTC 4H] Kompas BTC Lampu MERAH (RSI4H:{info_btc.get('rsi_4h')} | "
                f"Vol4H:{info_btc.get('vol_4h_ratio')}x | {info_btc.get('tren_detail')}), tahan 100% di Rupiah."
            )
            return state, log_grid, log_tx, False

        modal_dibutuhkan = GRID_CAPITAL_PER_LAYER_IDR * 3.0
        if dompet.get("terhubung") and dompet.get("idr_free", 0.0) < (modal_dibutuhkan * 0.95):
            log_grid.append(
                f"⏸️ [GRID MODAL KURANG] Saldo IDR bebas Rp{dompet.get('idr_free', 0):,.0f} < Rp{modal_dibutuhkan:,.0f} (1 lapis)."
            )
            return state, log_grid, log_tx, False

        kandidat_raw = []
        for v in peta_analisa.values():
            if v.get("layak_grid") is True:
                adj_mem, note_mem = hitung_penyesuaian_skor_memori_grid(state, v["coin"])
                item_k = dict(v)
                item_k["skor_efektif"] = round(v["skor"] + adj_mem, 1)
                item_k["catatan_memori_grid"] = note_mem
                kandidat_raw.append(item_k)

        kandidat = sorted(
            [k for k in kandidat_raw if k["skor_efektif"] >= GRID_MIN_SCORE_ENTRY],
            key=lambda x: x["skor_efektif"],
            reverse=True
        )
        if not kandidat:
            log_grid.append(
                f"⏸️ [GRID CASH IS KING] Belum ada koin memenuhi syarat Lapis 1 "
                f"(4H!=MERAH, M15/H1/5M valid, anti-pucuk & Skor >= {GRID_MIN_SCORE_ENTRY})."
            )
            return state, log_grid, log_tx, False

        pilih = kandidat[0]
        coin = pilih["coin"]
        step_l1 = pilih["grid_step_aktif"]
        mode_4h = pilih["lampu_4h"]
        p1 = bulatkan_harga_indodax(coin, pilih["harga_bid"])
        qty_b1 = hitung_kuantitas_koin(coin, GRID_CAPITAL_PER_LAYER_IDR, p1)

        ok_b1, res_b1, harga_b1_pasang, tif_b1 = pasang_order_grid_aman(
            coin, "BUY", p1, qty_b1, info_pasar=pilih, paksa_gtc_fallback=True
        )
        if ok_b1:
            oid_b1 = str(res_b1.get("orderId"))
            qty_b1_ok = hitung_kuantitas_koin(coin, GRID_CAPITAL_PER_LAYER_IDR, harga_b1_pasang) if harga_b1_pasang != p1 else qty_b1
            tier_1 = _buat_struktur_tier_baru(coin, 1, harga_b1_pasang, step_l1, mode_4h, oid_b1, qty_b1_ok, now_ts, buy_tif_b1=tif_b1)
            l1 = tier_1["layers"]
            state["grid_cycle"] = {
                "coin": coin,
                "created_ts": now_ts,
                "b3_ever_touched": False,
                "bounce_count": 0,
                "completed_tiers_count": 0,
                "realized_grid_profit_idr": 0.0,
                "tiers": [tier_1],
                "completed_tiers": []
            }
            ada_aksi = True
            pesan = (
                f"🕸️ [BUKA LAPIS 1 ({tif_b1}) | 4H:{mode_4h} Step:{step_l1*100:.1f}%] {coin} "
                f"(Skor:{pilih['skor_efektif']} [{pilih['catatan_memori_grid']}]) | "
                f"b1:Rp{l1['b1']['buy_price']:,.0f}->FINIS TP L1:Rp{l1['b1']['tp_price']:,.0f} | "
                f"b2:Rp{l1['b2']['buy_price']:,.0f} | b3:Rp{l1['b3']['buy_price']:,.0f} (Order:#{oid_b1})"
            )
            log_grid.append(pesan)
            log_tx.append(pesan)
        return state, log_grid, log_tx, ada_aksi

    # ==========================================================================
    # TAHAP B: KAWAL SEMUA LAPIS AKTIF (PENYELESAIAN PER LAPIS + SELF-HEALING)
    # ==========================================================================
    coin = cycle["coin"]
    info = peta_analisa.get(coin, {})
    tiers = cycle["tiers"]
    harga_skrg = info.get("harga_idr", tiers[0]["layers"]["b1"]["buy_price"])
    harga_bid = info.get("harga_bid", harga_skrg)
    lampu_4h = info.get("lampu_4h", "HIJAU")

    tier_dihapus_idx = []
    for idx_t, tier in enumerate(tiers):
        t_no = tier["tier_no"]
        layers = tier["layers"]
        tier.setdefault("realized_tier_profit_idr", 0.0)

        # ----------------------------------------------------------------------
        # 1. KAWAL ANTREAN AWAL b1 (AKUMULASI DUST + PARTIALLY_FILLED & CANCELED)
        # ----------------------------------------------------------------------
        if layers["b1"]["status"] == "WAIT_BUY":
            st_b1, detail_b1 = cek_status_order_indodax(coin, layers["b1"]["buy_oid"])
            terisi_sim = (not LIVE_TRADING_ENABLED) and (harga_skrg <= layers["b1"]["buy_price"])

            if st_b1 == "FILLED" or terisi_sim:
                dompet_baru = ambil_saldo_lengkap_indodax() if LIVE_TRADING_ENABLED else dompet
                exec_qty, exec_price = ekstrak_eksekusi_order(detail_b1, fallback_price=layers["b1"]["buy_price"])
                qty_dasar = exec_qty if exec_qty > 0 else layers["b1"]["qty"]
                qty_b1_aktual, dust_in = _hitung_qty_grid_akumulasi_dust(
                    cycle, coin, qty_dasar, exec_price, dompet_baru, exclude_lp=layers["b1"]
                )
                _promosikan_b1_dan_pasang_jaring(coin, tier, qty_b1_aktual, exec_price, info)
                ada_aksi = True
                tag_dust_in = f" (+AkumDust:{dust_in:g})" if dust_in > 0 else ""
                pesan = (
                    f"✅ [LAPIS {t_no} b1 TERBELI] {coin} Qty:{qty_b1_aktual:g}{tag_dust_in} aktif @ Rp{layers['b1']['buy_price']:,.0f}! "
                    f"TP Finis L{t_no} @ Rp{layers['b1']['tp_price']:,.0f}, jaring b2 & b3 dipasang."
                )
                log_grid.append(pesan)
                log_tx.append(pesan)
                continue

            if st_b1 in ("CANCELED", "EXPIRED", "REJECTED", "NOT_FOUND"):
                exec_qty, exec_price = ekstrak_eksekusi_order(detail_b1, fallback_price=layers["b1"]["buy_price"])
                if exec_qty > 0 and (exec_qty * exec_price) >= MIN_LIMIT_ORDER_INDODAX_IDR:
                    dompet_baru = ambil_saldo_lengkap_indodax() if LIVE_TRADING_ENABLED else dompet
                    qty_b1_aktual, dust_in = _hitung_qty_grid_akumulasi_dust(
                        cycle, coin, exec_qty, exec_price, dompet_baru, exclude_lp=layers["b1"]
                    )
                    _promosikan_b1_dan_pasang_jaring(coin, tier, qty_b1_aktual, exec_price, info)
                    ada_aksi = True
                    tag_dust_in = f" (+AkumDust:{dust_in:g})" if dust_in > 0 else ""
                    pesan = (
                        f"⚠️ [LAPIS {t_no} b1 PARTIAL FILL] Order {st_b1} tapi terisi {qty_b1_aktual:g}{tag_dust_in} {coin}. "
                        f"Tetap dikawal dgn TP Finis L{t_no} @ Rp{layers['b1']['tp_price']:,.0f}."
                    )
                    log_grid.append(pesan)
                    log_tx.append(pesan)
                else:
                    tier_dihapus_idx.append(idx_t)
                    ada_aksi = True
                    pesan = f"🧹 [HAPUS ANTREAN b1 LAPIS {t_no}] Order #{layers['b1']['buy_oid']} berstatus {st_b1} di Indodax."
                    log_grid.append(pesan)
                    log_tx.append(pesan)
                continue

            umur_m = (now_ts - float(tier.get("created_ts", now_ts))) / 60.0
            syarat_masih_ok = info.get("layak_grid", False) if t_no == 1 else info.get("layak_lapis_baru", False)
            if umur_m >= GRID_WAIT_B1_TIMEOUT_MIN or not syarat_masih_ok:
                batalkan_order_indodax(coin, layers["b1"]["buy_oid"])
                if LIVE_TRADING_ENABLED:
                    time.sleep(1.0)
                    st_after, detail_after = cek_status_order_indodax(coin, layers["b1"]["buy_oid"])
                    exec_qty, exec_price = ekstrak_eksekusi_order(detail_after, fallback_price=layers["b1"]["buy_price"])
                    if st_after == "FILLED" or (exec_qty > 0 and (exec_qty * exec_price) >= MIN_LIMIT_ORDER_INDODAX_IDR):
                        dompet_baru = ambil_saldo_lengkap_indodax()
                        qty_dasar = exec_qty if exec_qty > 0 else layers["b1"]["qty"]
                        qty_b1_aktual, dust_in = _hitung_qty_grid_akumulasi_dust(
                            cycle, coin, qty_dasar, exec_price, dompet_baru, exclude_lp=layers["b1"]
                        )
                        _promosikan_b1_dan_pasang_jaring(coin, tier, qty_b1_aktual, exec_price, info)
                        ada_aksi = True
                        tag_dust_in = f" (+AkumDust:{dust_in:g})" if dust_in > 0 else ""
                        pesan = (
                            f"✅ [BATAL b1 LAPIS {t_no} DIGAGALKAN - SUDAH TERISI] {coin} Qty:{qty_b1_aktual:g}{tag_dust_in} "
                            f"dikawal ke TP Finis L{t_no} @ Rp{layers['b1']['tp_price']:,.0f}."
                        )
                        log_grid.append(pesan)
                        log_tx.append(pesan)
                        continue

                tier_dihapus_idx.append(idx_t)
                ada_aksi = True
                pesan = f"🔄 [BATAL ANTREAN b1 LAPIS {t_no}] {coin} belum terjemput ({umur_m:.0f}m) / rezim berubah."
                log_grid.append(pesan)
                log_tx.append(pesan)
                continue

            tag_pf = " [PARTIALLY_FILLED]" if st_b1 == "PARTIALLY_FILLED" else ""
            log_grid.append(f"⏳ [ANTRE b1 LAPIS {t_no} {umur_m:.0f}m{tag_pf}] {coin} @ Rp{layers['b1']['buy_price']:,.0f} (Skrg: Rp{harga_skrg:,.0f})")
            continue

        # ----------------------------------------------------------------------
        # 2. CEK STATUS TERBELI (WAIT_BUY -> HOLDING + AKUMULASI DUST) b2 & b3
        # ----------------------------------------------------------------------
        for nama_lp in ("b2", "b3"):
            lp = layers[nama_lp]
            if lp["status"] == "WAIT_BUY" and lp.get("buy_oid"):
                st_buy, detail_buy = cek_status_order_indodax(coin, lp["buy_oid"])
                terisi_sim = (not LIVE_TRADING_ENABLED) and (harga_skrg <= lp["buy_price"])

                if st_buy == "FILLED" or terisi_sim:
                    dompet_baru = ambil_saldo_lengkap_indodax() if LIVE_TRADING_ENABLED else dompet
                    exec_qty, exec_price = ekstrak_eksekusi_order(detail_buy, fallback_price=lp["buy_price"])
                    qty_dasar = exec_qty if exec_qty > 0 else lp["qty"]
                    qty_aktual, dust_in = _hitung_qty_grid_akumulasi_dust(
                        cycle, coin, qty_dasar, exec_price, dompet_baru, exclude_lp=lp
                    )
                    if exec_price > 0:
                        lp["buy_price"] = bulatkan_harga_indodax(coin, exec_price)
                    lp["qty"] = qty_aktual
                    lp["capital_idr"] = round(qty_aktual * float(lp["buy_price"]), 0)
                    lp["status"] = "HOLDING"
                    lp["buy_oid"] = None
                    if t_no == 1 and nama_lp == "b3":
                        cycle["b3_ever_touched"] = True

                    target_tp_acuan = float(lp.get("base_tp_price", lp["tp_price"]))
                    ok_sell, res_sell, harga_sell_pasang, tif_s = pasang_order_grid_aman(
                        coin, "SELL", target_tp_acuan, qty_aktual, info_pasar=info, paksa_gtc_fallback=True
                    )
                    if ok_sell:
                        lp["sell_oid"] = str(res_sell.get("orderId"))
                        lp["tp_price"] = harga_sell_pasang
                        lp["sell_tif"] = tif_s
                    ada_aksi = True
                    tag_dust_in = f" (+AkumDust:{dust_in:g})" if dust_in > 0 else ""
                    pesan = (
                        f"🟢 [LAPIS {t_no} {nama_lp.upper()} TERBELI] {coin} Qty:{qty_aktual:g}{tag_dust_in} @ Rp{lp['buy_price']:,.0f} -> "
                        f"Pasang TP ({tif_s}) @ Rp{lp['tp_price']:,.0f}."
                    )
                    log_grid.append(pesan)
                    log_tx.append(pesan)

                elif st_buy in ("CANCELED", "EXPIRED", "REJECTED", "NOT_FOUND"):
                    exec_qty, exec_price = ekstrak_eksekusi_order(detail_buy, fallback_price=lp["buy_price"])
                    lp["buy_oid"] = None
                    if exec_qty > 0 and (exec_qty * exec_price) >= MIN_LIMIT_ORDER_INDODAX_IDR:
                        dompet_baru = ambil_saldo_lengkap_indodax() if LIVE_TRADING_ENABLED else dompet
                        qty_aktual, dust_in = _hitung_qty_grid_akumulasi_dust(
                            cycle, coin, exec_qty, exec_price, dompet_baru, exclude_lp=lp
                        )
                        lp["qty"] = qty_aktual
                        lp["buy_price"] = bulatkan_harga_indodax(coin, exec_price)
                        lp["capital_idr"] = round(qty_aktual * lp["buy_price"], 0)
                        lp["status"] = "HOLDING"
                        target_tp_acuan = float(lp.get("base_tp_price", lp["tp_price"]))
                        ok_sell, res_sell, harga_sell_pasang, tif_s = pasang_order_grid_aman(
                            coin, "SELL", target_tp_acuan, qty_aktual, info_pasar=info, paksa_gtc_fallback=True
                        )
                        if ok_sell:
                            lp["sell_oid"] = str(res_sell.get("orderId"))
                            lp["tp_price"] = harga_sell_pasang
                            lp["sell_tif"] = tif_s
                        ada_aksi = True
                        tag_dust_in = f" (+AkumDust:{dust_in:g})" if dust_in > 0 else ""
                        pesan_p = f"⚠️ [LAPIS {t_no} {nama_lp.upper()} PARTIAL FILL] Status {st_buy}, terisi {qty_aktual:g}{tag_dust_in} dipasang TP."
                        log_grid.append(pesan_p)
                        log_tx.append(pesan_p)
                    else:
                        lp["status"] = "ARMED"
                        log_grid.append(f"🔄 [LAPIS {t_no} {nama_lp.upper()} RE-ARM] Order beli {st_buy}, dijadwalkan pasang ulang.")

        # ----------------------------------------------------------------------
        # 3. CEK STATUS TERJUAL PROFIT (HITUNG MURNI QTY TERJUAL + CATAT DUST)
        # ----------------------------------------------------------------------
        for nama_lp in ("b1", "b2", "b3"):
            lp = layers[nama_lp]
            if lp["status"] == "HOLDING" and lp.get("sell_oid"):
                st_sell, detail_sell = cek_status_order_indodax(coin, lp["sell_oid"])
                terjual_sim = (not LIVE_TRADING_ENABLED) and (harga_skrg >= lp["tp_price"])

                if st_sell == "FILLED" or terjual_sim:
                    exec_qty_sell, harga_laku = ekstrak_eksekusi_order(detail_sell, fallback_price=lp["tp_price"])
                    qty_terjual = exec_qty_sell if exec_qty_sell > 0 else float(lp.get("qty", 0.0))
                    dust_sisa = round(max(0.0, float(lp.get("qty", 0.0)) - qty_terjual), 8)
                    capital_terjual = round(qty_terjual * float(lp["buy_price"]), 0)

                    gross_pct = (harga_laku - float(lp["buy_price"])) / max(1.0, float(lp["buy_price"]))
                    net_pct = gross_pct - _hitung_fee_roundtrip_grid(lp)
                    profit_idr = round(capital_terjual * net_pct, 0)

                    cycle["bounce_count"] = int(cycle.get("bounce_count", 0)) + 1
                    cycle["realized_grid_profit_idr"] = round(float(cycle.get("realized_grid_profit_idr", 0.0)) + profit_idr, 0)
                    tier["realized_tier_profit_idr"] = round(float(tier.get("realized_tier_profit_idr", 0.0)) + profit_idr, 0)
                    slot_mem = {"coin": coin, "style": f"GRID_L{t_no}_{nama_lp.upper()}", "capital_idr": capital_terjual}
                    catat_hasil_transaksi_ke_recovery(state, profit_idr, coin, slot=slot_mem, pnl_exit_pct=net_pct)
                    _catat_riwayat_jual_grid(
                        state, coin, t_no, nama_lp, float(lp["buy_price"]), harga_laku,
                        qty_terjual, capital_terjual, profit_idr, net_pct, dust_qty=dust_sisa
                    )
                    lp["sell_oid"] = None
                    ada_aksi = True
                    tag_dust = f" | SisaDust:{dust_sisa:g}" if dust_sisa > 0 else ""

                    if nama_lp == "b1":
                        lp["status"] = "DONE"
                        lp["qty"] = 0.0
                        pesan = (
                            f"🎉 [LAPIS {t_no} TP b1 TERCAPAI!] {coin} terjual {qty_terjual:g} @ Rp{harga_laku:,.0f} "
                            f"(Net:+Rp{profit_idr:,.0f} | Total Pantul:{cycle['bounce_count']}x{tag_dust})."
                        )
                    elif layers["b1"]["status"] == "DONE":
                        lp["status"] = "DONE"
                        lp["qty"] = 0.0
                        pesan = (
                            f"💰 [PANEN PENUTUP LAPIS {t_no} {nama_lp.upper()}] {coin} terjual {qty_terjual:g} "
                            f"@ Rp{harga_laku:,.0f} (+Rp{profit_idr:,.0f}{tag_dust})."
                        )
                    else:
                        lp["tp_price"] = float(lp.get("base_tp_price", lp["tp_price"]))
                        q_ulang = hitung_kuantitas_koin(coin, GRID_CAPITAL_PER_LAYER_IDR, lp["buy_price"])
                        ok_re, res_re, harga_re, tif_re = pasang_order_grid_aman(
                            coin, "BUY", lp["buy_price"], q_ulang, info_pasar=info, paksa_gtc_fallback=True
                        )
                        if ok_re:
                            lp["status"] = "WAIT_BUY"
                            lp["buy_oid"] = str(res_re.get("orderId"))
                            lp["buy_price"] = harga_re
                            lp["buy_tif"] = tif_re
                            lp["qty"] = q_ulang
                            lp["capital_idr"] = round(q_ulang * harga_re, 0)
                        else:
                            lp["status"] = "ARMED"
                            lp["buy_oid"] = None
                            lp["qty"] = 0.0
                        pesan = (
                            f"💰 [PANEN LAPIS {t_no} {nama_lp.upper()}!] {coin} terjual {qty_terjual:g} @ Rp{harga_laku:,.0f} "
                            f"(+Rp{profit_idr:,.0f} | Pantul #{cycle['bounce_count']}{tag_dust}). Jaring dipasang ulang ({tif_re})."
                        )
                    log_grid.append(pesan)
                    log_tx.append(pesan)

                elif st_sell in ("CANCELED", "EXPIRED", "REJECTED", "NOT_FOUND"):
                    exec_qty, harga_laku = ekstrak_eksekusi_order(detail_sell, fallback_price=lp["tp_price"])
                    lp["sell_oid"] = None
                    if exec_qty > 0:
                        sisa_qty = format_qty_koin(coin, max(0.0, float(lp["qty"]) - exec_qty))
                        modal_terjual = round(exec_qty * float(lp["buy_price"]), 0)
                        net_pct = ((harga_laku - float(lp["buy_price"])) / max(1.0, float(lp["buy_price"]))) - _hitung_fee_roundtrip_grid(lp)
                        profit_parsial = round(modal_terjual * net_pct, 0)
                        cycle["realized_grid_profit_idr"] = round(float(cycle.get("realized_grid_profit_idr", 0.0)) + profit_parsial, 0)
                        tier["realized_tier_profit_idr"] = round(float(tier.get("realized_tier_profit_idr", 0.0)) + profit_parsial, 0)
                        lp["qty"] = sisa_qty
                        lp["capital_idr"] = round(sisa_qty * float(lp["buy_price"]), 0)
                        if (sisa_qty * harga_skrg) < MIN_LIMIT_ORDER_INDODAX_IDR:
                            lp["status"] = "DONE"
                            catat_hasil_transaksi_ke_recovery(state, profit_parsial, coin)
                            _catat_riwayat_jual_grid(
                                state, coin, t_no, nama_lp, float(lp["buy_price"]), harga_laku,
                                exec_qty, modal_terjual, profit_parsial, net_pct, dust_qty=sisa_qty
                            )
                            tag_d = f" | SisaDust:{sisa_qty:g}" if sisa_qty > 0 else ""
                            pesan_ps = f"💰 [TP PARSIAL SELESAI L{t_no} {nama_lp.upper()}] Terjual {exec_qty:g} @ Rp{harga_laku:,.0f} (+Rp{profit_parsial:,.0f}{tag_d})."
                            log_grid.append(pesan_ps)
                            log_tx.append(pesan_ps)
                            continue
                    log_grid.append(f"⚠️ [TP LAPIS {t_no} {nama_lp.upper()} {st_sell}] Dijadwalkan pasang ulang otomatis oleh Self-Healing.")

        # ----------------------------------------------------------------------
        # 4. SELF-HEALING: PERBAIKI TP YATIM (sell_oid=None) & JARING MACET (ARMED)
        # ----------------------------------------------------------------------
        dompet_heal = None
        for nama_lp in ("b1", "b2", "b3"):
            lp = layers[nama_lp]
            if lp["status"] == "HOLDING" and not lp.get("sell_oid"):
                if dompet_heal is None:
                    dompet_heal = ambil_saldo_lengkap_indodax() if LIVE_TRADING_ENABLED else dompet
                k_free_h = dompet_heal["coins_free"].get(coin, float(lp["qty"])) if LIVE_TRADING_ENABLED else float(lp["qty"])
                qty_jual_h = format_qty_koin(coin, min(float(lp["qty"]), k_free_h))
                if qty_jual_h > 0 and (qty_jual_h * harga_skrg) >= MIN_LIMIT_ORDER_INDODAX_IDR:
                    target_tp_h = float(lp.get("base_tp_price", lp["tp_price"]))
                    ok_h, res_h, harga_h, tif_h = pasang_order_grid_aman(
                        coin, "SELL", target_tp_h, qty_jual_h, info_pasar=info, paksa_gtc_fallback=True
                    )
                    if ok_h:
                        lp["sell_oid"] = str(res_h.get("orderId"))
                        lp["tp_price"] = harga_h
                        lp["sell_tif"] = tif_h
                        lp["qty"] = qty_jual_h
                        ada_aksi = True
                        pesan = f"🩹 [SELF-HEAL TP L{t_no} {nama_lp.upper()}] Order jual ({tif_h}) dipulihkan @ Rp{harga_h:,.0f} (Order:#{lp['sell_oid']})."
                        log_grid.append(pesan)
                        log_tx.append(pesan)

        if layers["b1"]["status"] == "HOLDING":
            for nama_lp in ("b2", "b3"):
                lp = layers[nama_lp]
                if lp["status"] == "ARMED" and not lp.get("buy_oid"):
                    if dompet_heal is None:
                        dompet_heal = ambil_saldo_lengkap_indodax() if LIVE_TRADING_ENABLED else dompet
                    if (not LIVE_TRADING_ENABLED) or dompet_heal.get("idr_free", 0.0) >= (float(lp["capital_idr"]) * 0.95):
                        q_rearm = hitung_kuantitas_koin(coin, lp["capital_idr"], lp["buy_price"])
                        ok_ra, res_ra, harga_ra, tif_ra = pasang_order_grid_aman(
                            coin, "BUY", lp["buy_price"], q_rearm, info_pasar=info, paksa_gtc_fallback=True
                        )
                        if ok_ra:
                            lp["status"] = "WAIT_BUY"
                            lp["buy_oid"] = str(res_ra.get("orderId"))
                            lp["buy_price"] = harga_ra
                            lp["buy_tif"] = tif_ra
                            lp["qty"] = q_rearm
                            lp["capital_idr"] = round(q_rearm * harga_ra, 0)
                            if LIVE_TRADING_ENABLED:
                                dompet_heal["idr_free"] = max(0.0, dompet_heal.get("idr_free", 0.0) - lp["capital_idr"])
                            ada_aksi = True
                            log_grid.append(f"🩹 [SELF-HEAL JARING L{t_no} {nama_lp.upper()}] Jaring beli ({tif_ra}) dipasang ulang @ Rp{harga_ra:,.0f}.")

        # ----------------------------------------------------------------------
        # 5. PENYELESAIAN MANDIRI PER LAPIS (L1, L2, L3 SELESAI DI TP b1-NYA!)
        # ----------------------------------------------------------------------
        if (
            layers["b1"]["status"] == "DONE"
            and layers["b2"]["status"] != "HOLDING"
            and layers["b3"]["status"] != "HOLDING"
        ):
            ada_terisi_mendadak = False
            for nama_lp in ("b2", "b3"):
                lp = layers[nama_lp]
                if lp.get("buy_oid"):
                    batalkan_order_indodax(coin, lp["buy_oid"])
                    if LIVE_TRADING_ENABLED:
                        time.sleep(0.6)
                        st_c, det_c = cek_status_order_indodax(coin, lp["buy_oid"])
                        ex_q, ex_p = ekstrak_eksekusi_order(det_c, fallback_price=lp["buy_price"])
                        if st_c == "FILLED" or (ex_q > 0 and (ex_q * ex_p) >= MIN_LIMIT_ORDER_INDODAX_IDR):
                            lp["status"] = "HOLDING"
                            lp["buy_oid"] = None
                            lp["qty"] = format_qty_koin(coin, ex_q if ex_q > 0 else lp["qty"])
                            ada_terisi_mendadak = True
                            continue
                    lp["buy_oid"] = None
                    lp["status"] = "DONE"
                else:
                    lp["status"] = "DONE"

            if not ada_terisi_mendadak:
                tier["status"] = "DONE"
                tier["closed_ts"] = now_ts
                cycle["completed_tiers_count"] = int(cycle.get("completed_tiers_count", 0)) + 1
                cycle["completed_tiers"].append({
                    "tier_no": t_no,
                    "created_ts": tier.get("created_ts", now_ts),
                    "closed_ts": now_ts,
                    "tp_b1_idr": layers["b1"]["tp_price"],
                    "realized_tier_profit_idr": tier.get("realized_tier_profit_idr", 0.0)
                })
                tier_dihapus_idx.append(idx_t)
                ada_aksi = True
                durasi_lapis = format_durasi_siklus(now_ts - float(tier.get("created_ts", now_ts)))
                pesan = (
                    f"🏁 [LAPIS {t_no} SELESAI DI TP b1!] {coin} tuntas @ Rp{layers['b1']['tp_price']:,.0f} "
                    f"(Durasi Lapis: {durasi_lapis} | Profit Lapis: +Rp{tier.get('realized_tier_profit_idr', 0):,.0f}). "
                    f"Seluruh modal Lapis {t_no} cair 100% ke Rupiah!"
                )
                log_grid.append(pesan)
                log_tx.append(pesan)

    # Hapus lapis yang sudah selesai/dibatalkan dari daftar aktif (cegah bug tiers[-1] berstatus DONE!)
    for idx_del in sorted(tier_dihapus_idx, reverse=True):
        tiers.pop(idx_del)

    # ==========================================================================
    # TAHAP C: CEK PENUTUPAN SIKLUS PENUH (SEMUA LAPIS AKTIF SUDAH SELESAI)
    # ==========================================================================
    if not tiers:
        if int(cycle.get("completed_tiers_count", 0)) > 0:
            durasi_str = format_durasi_siklus(now_ts - float(cycle.get("created_ts", now_ts)))
            pesan = (
                f"🏆 [SELURUH SIKLUS GRID TUNTAS!] {coin} menyelesaikan {cycle['completed_tiers_count']} Lapis "
                f"| Durasi: {durasi_str} | Total Pantulan: {cycle['bounce_count']}x | "
                f"Total Profit Bersih: +Rp{cycle['realized_grid_profit_idr']:,.0f}."
            )
            log_grid.append(pesan)
            log_tx.append(pesan)
            rekam_memori_siklus_grid(state, cycle, "SEMUA_LAPIS_TP_B1", cycle["realized_grid_profit_idr"])
        state["grid_cycle"] = None
        return state, log_grid, log_tx, True

    # ==========================================================================
    # TAHAP C2: INVALIDATION / DRAWDOWN GUARD (ANTI-BAGHOLDING CRASH EKSTREM)
    # ==========================================================================
    harga_ref_dd = harga_live_map or {coin: {"last": harga_skrg, "buy": harga_bid}}
    _, modal_holding, floating_pnl_idr, dd_pct = hitung_ringkasan_keuangan_grid(cycle, harga_ref_dd)

    if (
        GRID_INVALIDATION_ENABLED
        and modal_holding > 0
        and dd_pct <= GRID_INVALIDATION_DD_PCT
        and lampu_4h == "MERAH"
        and len(tiers) >= GRID_MAX_TIERS
    ):
        if GRID_INVALIDATION_AUTO_CUT:
            for t in tiers:
                for lp in t["layers"].values():
                    if lp.get("buy_oid"):
                        batalkan_order_indodax(coin, lp["buy_oid"])
                    if lp.get("sell_oid"):
                        batalkan_order_indodax(coin, lp["sell_oid"])
            if LIVE_TRADING_ENABLED:
                time.sleep(1.5)
                dompet_cut = ambil_saldo_lengkap_indodax()
                qty_cut = format_qty_koin(coin, dompet_cut["coins_free"].get(coin, 0.0))
            else:
                qty_cut = format_qty_koin(
                    coin,
                    sum(float(lp.get("qty", 0.0)) for t in tiers for lp in t["layers"].values() if lp["status"] == "HOLDING")
                )
            if qty_cut > 0:
                berhasil_cut, harga_cut, _ = eksekusi_jual_terverifikasi(coin, harga_bid, qty_cut, prioritas_market=True)
                if berhasil_cut:
                    total_pnl_cut = round(float(cycle.get("realized_grid_profit_idr", 0.0)) + floating_pnl_idr - (modal_holding * FEE_ROUNDTRIP_MAKER_PCT), 0)
                    catat_hasil_transaksi_ke_recovery(state, floating_pnl_idr, coin, slot={"coin": coin, "style": "GRID_INVALIDATION", "capital_idr": modal_holding}, pnl_exit_pct=dd_pct)
                    rekam_memori_siklus_grid(state, cycle, "INVALIDATION_CUT_4H_MERAH", total_pnl_cut)
                    state["grid_cycle"] = None
                    pesan = (
                        f"🚨 [GRID INVALIDATION CUT] {coin} memotong posisi @ Rp{harga_cut:,.0f} "
                        f"(DD:{dd_pct*100:.2f}% <= {GRID_INVALIDATION_DD_PCT*100:.0f}% & 4H MERAH saat {len(tiers)} lapis penuh). "
                        f"Modal diselamatkan dari bagholding."
                    )
                    log_grid.append(pesan)
                    log_tx.append(pesan)
                    return state, log_grid, log_tx, True
        else:
            log_grid.append(
                f"🚨 [PERINGATAN INVALIDATION] {coin} DD:{dd_pct*100:.2f}% & 4H MERAH (Auto-Cut OFF, mode Swing Hold aktif)."
            )

    # ==========================================================================
    # TAHAP D: PEMICU BUKA LAPIS BARU (HANYA DARI LAPIS AKTIF TERBAWAH!)
    # ==========================================================================
    tiers.sort(key=lambda x: x["tier_no"])
    tier_terbawah = tiers[-1]
    lapis_berikutnya = tier_terbawah["tier_no"] + 1
    b3_terbawah = tier_terbawah["layers"]["b3"]
    step_dinamis_skrg = float(info.get("grid_step_aktif", GRID_STEP_MIN_PCT))
    drop_trigger_pct = round(max(GRID_STEP_MIN_PCT * 2.0, step_dinamis_skrg * 2.0), 4)
    harga_pemicu_lapis_baru = b3_terbawah["buy_price"] * (1.0 - drop_trigger_pct)

    batas_lapis_ok = (GRID_MAX_TIERS <= 0) or (len(tiers) < GRID_MAX_TIERS and lapis_berikutnya <= GRID_MAX_TIERS)
    if (
        batas_lapis_ok
        and b3_terbawah["status"] == "HOLDING"
        and harga_skrg <= harga_pemicu_lapis_baru
    ):
        modal_lapis_baru = GRID_CAPITAL_PER_LAYER_IDR * 3.0
        dompet_skrg = ambil_saldo_lengkap_indodax() if LIVE_TRADING_ENABLED else dompet
        saldo_cukup = (not LIVE_TRADING_ENABLED) or (dompet_skrg.get("idr_free", 0.0) >= modal_lapis_baru * 0.95)

        if not saldo_cukup:
            log_grid.append(
                f"💎 [SWING HOLD | SALDO IDR KURANG UNTUK LAPIS {lapis_berikutnya}] {coin} Rp{harga_skrg:,.0f} "
                f"(Butuh Rp{modal_lapis_baru:,.0f}, Tersedia Rp{dompet_skrg.get('idr_free', 0):,.0f})."
            )
        elif info.get("layak_lapis_baru"):
            step_baru = info.get("grid_step_aktif", GRID_STEP_GREEN_PCT)
            p1_baru = bulatkan_harga_indodax(coin, harga_bid)
            qty_b1_baru = hitung_kuantitas_koin(coin, GRID_CAPITAL_PER_LAYER_IDR, p1_baru)
            ok_nb, res_nb, harga_nb_pasang, tif_nb = pasang_order_grid_aman(
                coin, "BUY", p1_baru, qty_b1_baru, info_pasar=info, paksa_gtc_fallback=True
            )
            if ok_nb:
                oid_nb = str(res_nb.get("orderId"))
                qty_nb_ok = hitung_kuantitas_koin(coin, GRID_CAPITAL_PER_LAYER_IDR, harga_nb_pasang) if harga_nb_pasang != p1_baru else qty_b1_baru
                tier_baru = _buat_struktur_tier_baru(coin, lapis_berikutnya, harga_nb_pasang, step_baru, lampu_4h, oid_nb, qty_nb_ok, now_ts, buy_tif_b1=tif_nb)
                tiers.append(tier_baru)
                ada_aksi = True
                lb = tier_baru["layers"]
                pesan = (
                    f"🧱 [BUKA LAPIS {lapis_berikutnya} ({tif_nb}) | 4H:{lampu_4h} Step:{step_baru*100:.1f}%] {coin} "
                    f"b1:Rp{lb['b1']['buy_price']:,.0f}->FINIS TP L{lapis_berikutnya}:Rp{lb['b1']['tp_price']:,.0f} | "
                    f"b2:Rp{lb['b2']['buy_price']:,.0f} | b3:Rp{lb['b3']['buy_price']:,.0f} (Order:#{oid_nb})"
                )
                log_grid.append(pesan)
                log_tx.append(pesan)
        else:
            log_grid.append(
                f"⏳ [SIAGA LAPIS {lapis_berikutnya}] {coin} Rp{harga_skrg:,.0f} <= pemicu Rp{harga_pemicu_lapis_baru:,.0f} "
                f"(-{drop_trigger_pct*100:.0f}% dr b3 L{tier_terbawah['tier_no']}). Menunggu SIDEWAYS_UP/UPTREND M15, anti-pucuk & 4H!=MERAH."
            )
    else:
        durasi_jalan = format_durasi_siklus(now_ts - float(cycle.get("created_ts", now_ts)))
        ringkas_lapis = " || ".join(
            [
                f"L{t['tier_no']}(TPb1:Rp{t['layers']['b1']['tp_price']:,.0f})["
                + " ".join(k + ":" + v["status"] for k, v in t["layers"].items())
                + "]"
                for t in tiers
            ]
        )
        log_grid.append(
            f"🕸️ [KAWAL GRID {coin} | Aktif {len(tiers)}/{GRID_MAX_TIERS} | Selesai {cycle.get('completed_tiers_count', 0)} | {durasi_jalan}] "
            f"Skrg:Rp{harga_skrg:,.0f} | Panen:{cycle['bounce_count']}x (+Rp{cycle['realized_grid_profit_idr']:,.0f}) | "
            f"DD:{dd_pct*100:+.2f}% | {ringkas_lapis}"
        )

    return state, log_grid, log_tx, ada_aksi

# ==============================================================================
# BAGIAN 10: PROGRAM UTAMA (DUAL STRATEGY: GRID BTC + MINI SWING NON-BTC)
# ==============================================================================
def saring_log_eksekusi_terbeli_terjual(daftar_log):
    """
    Menyaring ketat agar Google Sheets HANYA menerima laporan saat koin
    benar-benar TERBELI (FILLED) atau benar-benar TERJUAL (TP/SL/Panen/Manual).
    Antrean baru, pembatalan, self-heal, & peringatan sync tidak dikirim ke Sheets.
    """
    kata_kunci_eksekusi_nyata = (
        # Benar-benar TERBELI (Grid & Mini Swing)
        "TERBELI]",
        "TERBELI MOC]",
        "PARTIAL FILL]",
        "SUDAH TERISI]",
        # Benar-benar TERJUAL (Grid & Mini Swing)
        "TP b1 TERCAPAI",
        "[PANEN ",
        "TP PARSIAL SELESAI",
        "JUAL MANUAL]",
        "INVALIDATION CUT]",
        "TP1 TERCAPAI!]",
        "TP2 PENUH!]",
        "VIRTUAL_STOP_LOSS]",
        "BE_PLUS_TRAIL_EXIT]",
        "STALE EXIT MAKER]",
        "STALE EXIT MARKET]",
    )
    return [baris for baris in daftar_log if any(k in str(baris) for k in kata_kunci_eksekusi_nyata)]

def jalankan_satu_siklus_penuh(state, paksa_kirim_sheets=False):
    global _ACTIVE_GRID_IDR_FREE_CAP
    dompet_asli = ambil_saldo_lengkap_indodax()
    if LIVE_TRADING_ENABLED and not dompet_asli.get("terhubung"):
        print("⚠️ Gagal terhubung ke API Indodax. Siklus dilewati agar state tidak rusak.")
        return state, False, [], False, {}, {}, {}, {}

    harga_live_map = ambil_harga_idr_semua_koin()
    pairs_meta = ambil_metadata_pairs_indodax() if SWING_MODE_ENABLED else {}

    # 1. Rekonsiliasi 2-Arah Dompet (Grid BTC & Mini Swing Non-BTC terpisah penuh)
    log_recovery_grid = []
    log_recovery_swing = []
    if GRID_MODE_ENABLED:
        state, log_recovery_grid = rekonsiliasi_grid_dengan_indodax(state, dompet_asli, harga_live_map)
    if SWING_MODE_ENABLED:
        state, log_recovery_swing = rekonsiliasi_swing_dengan_indodax(state, dompet_asli, harga_live_map)
    log_recovery = log_recovery_grid + log_recovery_swing

    # 2. Sinkronisasi Pembagian Keuangan (Budget Vault: Grid vs Mini Swing vs Surplus)
    vault_info = sinkronkan_dan_hitung_budget_vault(state, dompet_asli)
    print(
        f"💰 [BUDGET VAULT] Dompet Free:Rp{vault_info['idr_free_wallet']:,.0f} | "
        f"Grid(L{max(1, vault_info['grid_tiers_aktif'])}):Eq Rp{vault_info['grid_equity_idr']:,.0f} Free Rp{vault_info['grid_free_idr']:,.0f} | "
        f"Swing(Cap Rp{vault_info['swing_cap_max']:,.0f}):Eq Rp{vault_info['swing_equity_idr']:,.0f} Free Rp{vault_info['swing_free_idr']:,.0f} | "
        f"Surplus:Rp{vault_info['reserve_surplus_idr']:,.0f} | Lapis Baru Grid:{'IZIN' if vault_info['boleh_buka_lapis_baru'] else 'BLOKIR'}"
    )

    # 3. STRATEGI A: MESIN GRID BTC (100% UTUH, DIBATASI VIRTUAL CAP AGAR TIDAK SENTUH DANA SWING)
    peta_analisa_pasar = {}
    log_grid, log_tx_grid, ada_aksi_grid = [], [], False
    if GRID_MODE_ENABLED:
        peta_analisa_pasar = analisa_teknikal_lengkap_pasar(harga_live_map)
        _, tiers_sblm = hitung_modal_terpakai_grid(state)
        prof_sblm = float(state["grid_cycle"].get("realized_grid_profit_idr", 0.0)) if state.get("grid_cycle") else 0.0

        # Tentukan plafon IDR bebas yang boleh dilihat mesin Grid:
        # - Jika belum ada siklus: hanya jatah bebas Grid (maks 100rb), TIDAK termasuk jatah Mini Swing.
        # - Jika sudah ada lapis aktif: jika izin lapis baru=YA beri jatah bebas Grid + 100rb;
        #   jika TIDAK, batasi maksimal 2.1x modal jaring (~69rb) agar self-healing b2/b3 jalan namun Tahap D buka lapis baru terblokir.
        if tiers_sblm == 0:
            cap_free_grid = vault_info["grid_free_idr"]
        elif vault_info["boleh_buka_lapis_baru"]:
            cap_free_grid = vault_info["grid_free_idr"] + GRID_BUDGET_PER_TIER_IDR
        else:
            cap_free_grid = min(vault_info["grid_free_idr"], GRID_CAPITAL_PER_LAYER_IDR * 2.1)

        dompet_grid = dict(dompet_asli)
        dompet_grid["idr_free"] = min(float(dompet_asli.get("idr_free", 0.0)), cap_free_grid)
        try:
            _ACTIVE_GRID_IDR_FREE_CAP = cap_free_grid
            state, log_grid, log_tx_grid, ada_aksi_grid = kelola_siklus_grid_3_lapis(
                state, peta_analisa_pasar, dompet_grid, harga_live_map=harga_live_map
            )
        finally:
            _ACTIVE_GRID_IDR_FREE_CAP = None

        catat_perubahan_ledger_grid(state, tiers_sblm, prof_sblm)
        if ada_aksi_grid and LIVE_TRADING_ENABLED:
            dompet_asli = ambil_saldo_lengkap_indodax()
        vault_info = sinkronkan_dan_hitung_budget_vault(state, dompet_asli)

    # 4. STRATEGI B: MESIN MINI SWING NON-BTC (1D - 4H - 1H + ORDER BOOK + VIRTUAL OCO)
    analisa_swing = {}
    log_swing, log_tx_swing, ada_aksi_swing = [], [], False
    if SWING_MODE_ENABLED:
        order_ref = max(MIN_NEW_BUY_ALLOCATION_IDR, vault_info["swing_equity_idr"] * 0.40)
        analisa_swing = analisa_teknikal_mini_swing(harga_live_map, pairs_meta, order_size_ref_idr=order_ref)
        state, log_swing, log_tx_swing, ada_aksi_swing = kelola_siklus_mini_swing(
            state, analisa_swing, vault_info, dompet_asli, harga_live_map, pairs_meta
        )
        if ada_aksi_swing and LIVE_TRADING_ENABLED:
            dompet_asli = ambil_saldo_lengkap_indodax()
        vault_info = sinkronkan_dan_hitung_budget_vault(state, dompet_asli)

    # 5. Simpan State Atomik & Laporan
    simpan_state_bot(state)
    semua_log = log_recovery + log_grid + log_swing
    for baris in semua_log:
        print("  ", baris)

    log_tx_terverifikasi = saring_log_eksekusi_terbeli_terjual(log_recovery + log_tx_grid + log_tx_swing)
    ada_transaksi_nyata = bool(log_tx_terverifikasi)
    if ada_transaksi_nyata or paksa_kirim_sheets:
        lapor_ke_google_sheets(state, log_tx_terverifikasi or semua_log, dompet_asli, harga_live_map)
    else:
        print("ℹ️ [SHEETS SKIP] Belum ada koin yang benar-benar terbeli atau terjual.")

    butuh_siaga, alasan_siaga = cek_apakah_butuh_pengawasan_intensif(state, analisa_swing)
    return state, butuh_siaga, alasan_siaga, ada_transaksi_nyata, peta_analisa_pasar, harga_live_map, analisa_swing, vault_info

def cetak_status_awal_quant():
    mode_str = "LIVE TRADING" if LIVE_TRADING_ENABLED else "SIMULASI"
    print(
        f"⚙️ [DUAL QUANT BOT INDODAX | Mode: {mode_str} | 100% Deterministik Tanpa LLM]\n"
        f"   1. GRID BTC     : {'AKTIF' if GRID_MODE_ENABLED else 'OFF'} | Koin: {','.join(sorted(GRID_ALLOWED_COINS))} | Cap: Rp{GRID_BUDGET_PER_TIER_IDR:,.0f}/Lapis\n"
        f"   2. MINI SWING   : {'AKTIF' if SWING_MODE_ENABLED else 'OFF'} | Pool: {','.join(sorted(SWING_ALLOWED_COINS))} (Non-BTC) | Maks Dana: Rp{MAX_SWING_CAPITAL_IDR:,.0f}"
    )

if __name__ == "__main__":
    waktu_mulai = time.time()
    batas_waktu_siaga = waktu_mulai + (ACTIVE_WATCH_MINUTES * 60)

    cetak_status_awal_quant()
    state = muat_state_bot()
    state, butuh_siaga, alasan_siaga, _, peta_analisa_terakhir, harga_live_terakhir, analisa_swing_terakhir, vault_terakhir = jalankan_satu_siklus_penuh(
        state, paksa_kirim_sheets=False
    )

    if butuh_siaga and ACTIVE_WATCH_MINUTES > 0:
        print(f"\n🔥 [PENGAWASAN INTENSIF AKTIF] Selama {ACTIVE_WATCH_MINUTES} menit:")
        for alasan in alasan_siaga:
            print(f"   -> {alasan}")

        putaran = 1
        kesimpulan_sudah_cetak = False
        while time.time() + WATCH_INTERVAL_SECONDS < batas_waktu_siaga:
            sisa_menit = (batas_waktu_siaga - time.time()) / 60.0
            print(f"\n⏱️ [SIAGA PUTARAN #{putaran} | Sisa: {sisa_menit:.1f}m] Menunggu {WATCH_INTERVAL_SECONDS} detik...")
            time.sleep(WATCH_INTERVAL_SECONDS)
            putaran += 1

            state, masih_butuh_siaga, _, ada_eksekusi, peta_analisa_terakhir, harga_live_terakhir, analisa_swing_terakhir, vault_terakhir = jalankan_satu_siklus_penuh(
                state, paksa_kirim_sheets=False
            )
            if ada_eksekusi:
                print("✅ [EKSEKUSI REAL-TIME BERHASIL] State & Google Sheets diperbarui!")
            if not masih_butuh_siaga:
                print("\n" + buat_kesimpulan_patroli_dinamis(state, peta_analisa_terakhir, harga_live_terakhir, analisa_swing_terakhir, vault_terakhir))
                kesimpulan_sudah_cetak = True
                break
        if not kesimpulan_sudah_cetak:
            print("\n" + buat_kesimpulan_patroli_dinamis(state, peta_analisa_terakhir, harga_live_terakhir, analisa_swing_terakhir, vault_terakhir))
    else:
        print("\n" + buat_kesimpulan_patroli_dinamis(state, peta_analisa_terakhir, harga_live_terakhir, analisa_swing_terakhir, vault_terakhir))
