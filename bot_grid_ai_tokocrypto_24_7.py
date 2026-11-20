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

# ==============================================================================
# KONFIGURASI METODE GRID 3-LAPIS (FOKUS RECOVERY MODAL & SWING HOLD)
# ==============================================================================
GRID_MODE_ENABLED = True               # True = aktifkan Grid 3-Lapis; False = mode scalping lama
GRID_CAPITAL_PER_LAYER_IDR = 33000.0   # Modal Rp100.000 dibagi 3 lapis rata (~Rp33.000/lapis)
GRID_STEP_PCT = 0.0150                 # Jarak antar grid 1.50% (Net profit ~0.95% per pantulan, b3 di -3.00%)
GRID_MAX_RSI_M5_ENTRY = 65.0           # Anti beli di pucuk (overbought) saat buka b1
GRID_MIN_ATR_15M_PCT = 0.0035          # Syarat volatilitas minimal 15M agar rentang cukup melibas fee 0.55%
GRID_RESET_BOUNCE_COUNT = 3            # Jika b3 pernah tersentuh & pantulan >= 3x -> siap reset siklus saat net untung
GRID_WAIT_B1_TIMEOUT_MIN = 45.0        # Batas tunggu antrean awal b1 sebelum dibatalkan jika belum terjemput
GRID_MEMORY_RETENTION_HOURS = 168.0    # Memori pengalaman siklus Grid disimpan 1 minggu (7 hari = 168 jam)
MAX_GRID_MEMORY_ITEMS = 60             # Maksimal menyimpan 60 riwayat siklus Grid dalam 1 minggu
GRID_ALLOWED_COINS = {"BTC", "ETH", "XRP"}  # Khusus 3 aset likuiditas teratas Indodax (anti-slippage & aman Swing Hold)
GRID_LIMIT_TIF = "MOC"                             # Maker-Only Cancel (otomatis tolak jika terancam jadi Taker; ubah ke "GTC" jika perlu)

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
SL_MEMORY_RETENTION_HOURS = 168.0      # Memori pengalaman & Win Rate disimpan 1 minggu (168 jam)
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
            state.setdefault("grid_cycle", None)
            state.setdefault("grid_experience_memory", [])
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
        "grid_cycle": None,
        "grid_experience_memory": [],
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

def rekam_memori_siklus_grid(state, cycle, alasan_tutup, total_pnl_idr):
    """Merekam riwayat siklus Grid selesai selama 1 minggu (168 jam) sebagai bahan pertimbangan koin berikutnya."""
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
        "alasan_tutup": alasan_tutup,  # "TP_PENUH" atau "AUTO_RESET_B3"
        "bounce_count": int(cycle.get("bounce_count", 0)),
        "b3_ever_touched": bool(cycle.get("b3_ever_touched", False)),
        "durasi_jam": durasi_jam,
        "total_pnl_idr": round(float(total_pnl_idr), 0),
        "berhasil": float(total_pnl_idr) >= 0.0
    })
    state["grid_experience_memory"] = memori_aktif[-MAX_GRID_MEMORY_ITEMS:]

def hitung_penyesuaian_skor_memori_grid(state, coin):
    """
    Menilai performa historis Grid 1 minggu terakhir untuk 1 koin:
    - Bonus skor jika koin terbukti lancar panen & cepat selesai.
    - Penalti skor jika koin baru saja nyangkut lama di bawah b3 atau rugi.
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

    for m in riwayat_koin:
        pnl = float(m.get("total_pnl_idr", 0.0))
        bounces = int(m.get("bounce_count", 0))
        sentuh_b3 = bool(m.get("b3_ever_touched", False))
        durasi_j = float(m.get("durasi_jam", 0.0))

        if pnl > 0 and (not sentuh_b3 or durasi_j <= 24.0):
            jml_lancar += 1
            delta_skor += 3.0 + (2.0 if bounces >= 3 else 0.0)
        elif pnl < 0 or (sentuh_b3 and durasi_j >= 24.0):
            jml_berat += 1
            delta_skor -= 5.0

    # Jeda penalti ringan (-4.0) jika siklus terakhir koin ini sempat menyentuh b3 dan baru selesai < 2 jam lalu
    terakhir = riwayat_koin[-1]
    if terakhir.get("b3_ever_touched") and (now_ts - float(terakhir.get("ts", 0.0))) < 7200.0:
        delta_skor -= 4.0

    delta_skor = round(max(-15.0, min(12.0, delta_skor)), 1)
    catatan = f"7H:{len(riwayat_koin)}x ({jml_lancar} lancar/{jml_berat} berat, Adj:{delta_skor:+.1f})"
    return delta_skor, catatan

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

def eksekusi_order_indodax(coin, side_str, harga_idr, nominal_idr=0.0, qty_koin=0.0, order_type="LIMIT", time_in_force="GTC"):
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
        params["timeInForce"] = str(time_in_force).upper()
        params["price"] = str(harga_bulat)

    res = panggil_indodax_v2("/api/v2/order", method="POST", params=params)
    print(f"👉 [INDODAX V2 {side_str.upper()} {order_type.upper()} {params.get('timeInForce', '')}] {symbol} | Qty={qty} @ Rp{harga_bulat:,.0f} -> {res}")
    if isinstance(res, dict):
        res["qty"] = qty
    return res

def apakah_order_sukses(res):
    return isinstance(res, dict) and ("orderId" in res or res.get("simulasi") is True)

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
    """Mengecek status asli order di Indodax: NEW, PARTIALLY_FILLED, FILLED, CANCELED, NOT_FOUND, atau UNKNOWN."""
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

def ambil_open_orders_indodax(coin):
    """Mengambil daftar Open Orders aktif untuk 1 koin dari Indodax V2."""
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
    """Mengambil riwayat trade aktual dari Indodax untuk mengetahui harga beli/jual sebenarnya."""
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
    """
    Menjamin order jual benar-benar LAKU (tidak nyangkut di Open Orders).
    Jika Limit Sell belum langsung terisi dalam 2 detik -> cancel & tembak Market Order.
    """
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
        harga_aktual = float(detail_ord.get("price", 0) or 0) or harga_limit_idr
        return True, harga_aktual, res_l

    # Order Limit ternyata nyangkut (harga Bid keburu turun) -> batalkan & paksa Market agar bersih
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
    """
    REKONSILIASI 2-ARAH (SINGLE SOURCE OF TRUTH = INDODAX):
    1. Audit seluruh active_slots terhadap saldo dompet & Open Orders asli Indodax.
    2. Pulihkan koin yatim di dompet dengan harga beli asli dari riwayat myTrades Indodax.
    """
    log_sync = []
    if not dompet.get("terhubung"):
        return state, log_sync

    now_ts = time.time()
    slot_valid = []

    # ==========================================================================
    # TAHAP 1: AUDIT SLOT DI MEMORI BOT VS REALITA DOMPET & OPEN ORDERS INDODAX
    # ==========================================================================
    for slot in state.get("active_slots", []):
        coin = slot["coin"]
        status_slot = slot.get("status", "")
        harga_skrg = harga_idr_map.get(coin, {}).get("last", float(slot.get("entry_price_idr", 0)))
        k_free = dompet["coins_free"].get(coin, 0.0)
        k_locked = dompet["coins_locked"].get(coin, 0.0)
        total_qty_asli = format_qty_koin(coin, k_free + k_locked)
        nilai_koin_asli = total_qty_asli * harga_skrg
        entry_idr = float(slot.get("entry_price_idr", harga_skrg))
        tp_idr = float(slot.get("tp_price_idr", entry_idr * 1.015))
        umur_slot_detik = now_ts - float(slot.get("timestamp", now_ts))

        # --- A. AUDIT WAITING_BUY ---
        if status_slot == "WAITING_BUY":
            # Jika koin sudah masuk dompet, biarkan Bagian 6 mempromosikannya ke HOLDING_FOR_TP
            if nilai_koin_asli >= 5000.0:
                slot_valid.append(slot)
                continue

            buy_oid = slot.get("buy_order_id")
            status_ord, _ = cek_status_order_indodax(coin, buy_oid) if buy_oid else ("NOT_FOUND", {})
            ok_oo, daftar_oo = ambil_open_orders_indodax(coin)
            ada_di_open_orders = any(str(o.get("orderId", "")) == str(buy_oid) for o in daftar_oo) if ok_oo else True
            idr_locked_kosong = float(dompet.get("idr_locked", 0.0)) < 1000.0

            if umur_slot_detik > 15.0 and (
                idr_locked_kosong
                or status_ord in ("CANCELED", "EXPIRED", "REJECTED", "NOT_FOUND")
                or (ok_oo and not ada_di_open_orders)
            ):
                log_sync.append(
                    f"🧹 [SYNC HAPUS ANTREAN HANTU] Order beli {coin} (#{buy_oid}) sudah tidak ada di Indodax "
                    f"(Status:{status_ord}, IDR Locked:Rp{dompet.get('idr_locked', 0):,.0f}). Slot dihapus & plafon pulih."
                )
                continue

            slot_valid.append(slot)
            continue

        # --- B. AUDIT HOLDING_FOR_TP ---
        if status_slot == "HOLDING_FOR_TP":
            # 1. KOIN TIDAK ADA DI DOMPET (< Rp5.000) -> WAJIB DIBERSIHKAN (BAIK tp_order_id ADA MAUPUN KOSONG!)
            if nilai_koin_asli < 5000.0:
                tp_oid = slot.get("tp_order_id")
                status_tp, detail_tp = cek_status_order_indodax(coin, tp_oid) if tp_oid else ("NOT_FOUND", {})

                # Cek apakah benar-benar laku lewat order TP
                if status_tp == "FILLED":
                    harga_laku = float(detail_tp.get("price", 0) or 0) or tp_idr
                    pnl_pct = ((harga_laku - entry_idr) / entry_idr) - FEE_ROUNDTRIP_MAKER_PCT
                    profit_bersih = round(float(slot.get("capital_idr", 0)) * pnl_pct, 0)
                    catat_hasil_transaksi_ke_recovery(state, profit_bersih, coin, slot=slot, pnl_exit_pct=pnl_pct)
                    log_sync.append(
                        f"🎉 [TP TERVERIFIKASI INDODAX] {coin} laku di Rp{harga_laku:,.0f} "
                        f"(PnL Bersih: Rp{profit_bersih:,.0f} | OrderTP:#{tp_oid})."
                    )
                    continue

                # Jika bukan dari TP (misal dijual manual di app atau sell sebelumnya laku), cek myTrades aktual
                waktu_acuan = float(slot.get("filled_timestamp", slot.get("timestamp", 0))) - 120.0
                trades_jual = [
                    t for t in ambil_trade_terakhir_indodax(coin, side_filter="SELL", limit=8)
                    if t["ts"] >= waktu_acuan
                ]
                if trades_jual:
                    harga_laku_manual = trades_jual[0]["price"]
                    pnl_pct = ((harga_laku_manual - entry_idr) / entry_idr) - FEE_ROUNDTRIP_MAKER_PCT
                    pnl_bersih = round(float(slot.get("capital_idr", 0)) * pnl_pct, 0)
                    catat_hasil_transaksi_ke_recovery(state, pnl_bersih, coin, slot=slot, pnl_exit_pct=pnl_pct)
                    log_sync.append(
                        f"🔄 [SYNC JUAL AKTUAL INDODAX] {coin} sudah terjual di luar bot @ Rp{harga_laku_manual:,.0f} "
                        f"(PnL Bersih: Rp{pnl_bersih:,.0f}). Slot ditutup & disinkronkan."
                    )
                else:
                    # Koin benar-benar tidak ada & tidak ada trade baru -> murni slot hantu (seperti kasus ETH)
                    log_sync.append(
                        f"🧹 [SYNC HAPUS SLOT HANTU] {coin} tidak ditemukan di dompet Indodax (Saldo: 0). "
                        f"Slot hantu dihapus tanpa merusak statistik Win Rate/Recovery."
                    )
                continue

            # 2. KOIN ADA DI DOMPET -> SINKRONKAN QTY & STATUS ORDER TP
            if total_qty_asli > 0:
                slot["qty"] = total_qty_asli

            # Jika di memori tercatat punya tp_order_id tapi koin_locked == 0 -> berarti TP dicancel manual di aplikasi!
            if slot.get("tp_order_id") and k_locked <= 0:
                status_tp, _ = cek_status_order_indodax(coin, slot["tp_order_id"])
                if status_tp in ("CANCELED", "EXPIRED", "NOT_FOUND"):
                    log_sync.append(
                        f"🔄 [SYNC TP DIBATALKAN MANUAL] OrderTP #{slot['tp_order_id']} {coin} sudah tidak aktif di Indodax. "
                        f"Reset tp_order_id agar bot pasang ulang otomatis."
                    )
                    slot["tp_order_id"] = None

            # Jika tp_order_id kosong tapi di dompet ada koin_locked -> sambungkan dengan Open Order SELL yang sudah ada
            if not slot.get("tp_order_id") and k_locked > 0:
                ok_oo, daftar_oo = ambil_open_orders_indodax(coin)
                if ok_oo:
                    sell_orders = [o for o in daftar_oo if str(o.get("side", "")).upper() == "SELL"]
                    if sell_orders:
                        slot["tp_order_id"] = str(sell_orders[0].get("orderId"))
                        harga_oo = float(sell_orders[0].get("price", 0) or 0)
                        if harga_oo > 0:
                            slot["tp_price_idr"] = harga_oo
                        log_sync.append(
                            f"🔗 [SYNC KAITKAN ORDER TP] {coin} dikaitkan ke Open Order SELL #{slot['tp_order_id']} @ Rp{slot['tp_price_idr']:,.0f}."
                        )

            slot_valid.append(slot)

    state["active_slots"] = slot_valid

    # ==========================================================================
    # TAHAP 2: AUTO-RECOVERY KOIN YATIM DI DOMPET (GUNAKAN HARGA BELI ASLI!)
    # ==========================================================================
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
            # Cari harga beli asli dari riwayat myTrades Indodax agar tidak asal pakai harga sekarang
            trades_beli = ambil_trade_terakhir_indodax(coin, side_filter="BUY", limit=5)
            harga_beli_asli = trades_beli[0]["price"] if trades_beli else harga_skrg
            entry_idr = ref.get("entry_price_idr", bulatkan_harga_indodax(coin, harga_beli_asli))
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
                "filled_timestamp": trades_beli[0]["ts"] if trades_beli else now_ts,
                "timestamp": now_ts
            }

            # Cek apakah sudah ada Open Order SELL di Indodax sebelum memasang TP baru
            tp_terkait = None
            if k_locked > 0:
                ok_oo, daftar_oo = ambil_open_orders_indodax(coin)
                if ok_oo:
                    sell_oo = [o for o in daftar_oo if str(o.get("side", "")).upper() == "SELL"]
                    if sell_oo:
                        tp_terkait = str(sell_oo[0].get("orderId"))
                        slot_pulih["tp_order_id"] = tp_terkait
                        if float(sell_oo[0].get("price", 0) or 0) > 0:
                            slot_pulih["tp_price_idr"] = float(sell_oo[0]["price"])

            if not tp_terkait and k_free > 0:
                pasang_antrean_tp_di_indodax(slot_pulih, k_free)

            state["active_slots"].append(slot_pulih)
            sumber_acuan = "myTrades Indodax" if trades_beli else "Harga Pasar"
            log_sync.append(
                f"♻️ [AUTO-RECOVERY DOMPET] {coin} (Qty:{total_qty}) ditemukan di Indodax! "
                f"Dipulihkan (Entry {sumber_acuan}: Rp{entry_idr:,.0f} -> TP: Rp{slot_pulih['tp_price_idr']:,.0f})."
            )
    return state, log_sync

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

def hitung_ema_series(closes_list, periode):
    """Menghitung deret EMA (Exponential Moving Average) asli, bukan SMA."""
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
    """Menghitung ATR asli (True Range) dalam persentase terhadap harga terakhir."""
    if len(closes) <= periode or closes[-1] <= 0:
        return 0.003
    tr_list = []
    for i in range(-periode, 0):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr_list.append(max(hl, hc, lc))
    return (sum(tr_list) / float(periode)) / closes[-1]

def ambil_data_ohlc_indodax(coin, info, tf="15", jumlah_candle=100):
    """
    Mengambil data candlestick LANGSUNG dari Indodax sesuai timeframe-nya:
    tf="5" (M5), tf="15" (M15), tf="60" (H1), tf="240" (H4).
    100% native Indodax tanpa fallback bursa lain.
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

        if isinstance(data, list) and len(data) >= 30:
            raw = data[-jumlah_candle:]
            closes = [float(r.get("Close", r.get("close", 0))) for r in raw]
            highs = [float(r.get("High", r.get("high", 0))) for r in raw]
            lows = [float(r.get("Low", r.get("low", 0))) for r in raw]
            vols = [float(r.get("Volume", r.get("volume", 0)) or 0) for r in raw]
            if closes and closes[-1] > 0:
                return closes, highs, lows, vols

        if isinstance(data, dict) and "c" in data and len(data["c"]) >= 30:
            closes = [float(x) for x in data["c"][-jumlah_candle:]]
            highs = [float(x) for x in data["h"][-jumlah_candle:]]
            lows = [float(x) for x in data["l"][-jumlah_candle:]]
            vols = [float(x) for x in data.get("v", [1.0] * len(closes))[-jumlah_candle:]]
            if closes and closes[-1] > 0:
                return closes, highs, lows, vols
    except Exception as e:
        print(f"⚠️ [INDODAX OHLC {coin} TF:{tf}] Gagal ambil chart: {e}")
    return None

def deteksi_rezim_pasar(closes, highs, lows):
    """
    Klasifikasi objektif 4 rezim pasar menggunakan EMA20/EMA50 asli & struktur Higher Low:
    - UPTREND
    - SIDEWAYS_UP   (Sideways cenderung uptrend -> BOLEH GRID)
    - SIDEWAYS_DOWN (Sideways cenderung downtrend -> DILARANG GRID)
    - DOWNTREND     (Downtrend -> DILARANG GRID)
    """
    ema20_s = hitung_ema_series(closes, 20)
    ema50_s = hitung_ema_series(closes, 50)
    ema20_skrg = ema20_s[-1]
    ema20_lalu = ema20_s[-4] if len(ema20_s) >= 4 else ema20_s[0]
    ema50_skrg = ema50_s[-1]
    harga_skrg = closes[-1]

    slope_ema20_pct = ((ema20_skrg - ema20_lalu) / ema20_lalu) if ema20_lalu > 0 else 0.0
    jarak_ema_pct = ((ema20_skrg - ema50_skrg) / ema50_skrg) if ema50_skrg > 0 else 0.0

    # Struktur Swing Low (10 candle terbaru vs 10 candle sebelumnya)
    low_terbaru = min(lows[-10:])
    low_sebelumnya = min(lows[-20:-10]) if len(lows) >= 20 else low_terbaru
    higher_low = low_terbaru >= (low_sebelumnya * 0.9985)  # Toleransi noise 0.15%

    # 1. UPTREND jelas: EMA20 > EMA50, harga di atas EMA50, slope EMA20 naik
    if ema20_skrg > ema50_skrg and harga_skrg >= ema50_skrg and slope_ema20_pct >= 0.0005 and higher_low:
        rezim = "UPTREND"
    # 2. DOWNTREND jelas: EMA20 < EMA50, harga di bawah EMA20, slope menukik turun
    elif ema20_skrg < ema50_skrg and harga_skrg < ema20_skrg and slope_ema20_pct <= -0.0008 and not higher_low:
        rezim = "DOWNTREND"
    # 3. SIDEWAYS CENDERUNG UPTREND: EMA20 datar/naik & membentuk Higher Low (tidak jebol support)
    elif slope_ema20_pct >= -0.0003 and higher_low and jarak_ema_pct >= -0.0040:
        rezim = "SIDEWAYS_UP"
    # 4. Sisanya dianggap SIDEWAYS CENDERUNG DOWNTREND (aman/konservatif -> blokir entry)
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

def analisa_teknikal_lengkap_pasar(harga_idr_map):
    """Analisa multi-timeframe 100% Native Indodax (M5 + M15 + H1 + Rem Makro H4)."""
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

        # Ambil langsung chart masing-masing timeframe dari Indodax (5M, 15M, 1H, 4H)
        ohlc_5m = ambil_data_ohlc_indodax(coin, info, tf="5", jumlah_candle=80)
        ohlc_15m = ambil_data_ohlc_indodax(coin, info, tf="15", jumlah_candle=80)
        ohlc_1h = ambil_data_ohlc_indodax(coin, info, tf="60", jumlah_candle=80)
        ohlc_4h = ambil_data_ohlc_indodax(coin, info, tf="240", jumlah_candle=80)
        time.sleep(0.15)  # Jeda sopan anti rate-limit Indodax

        if not ohlc_5m or not ohlc_15m or not ohlc_1h or not ohlc_4h:
            continue

        c5, h5, l5, v5 = ohlc_5m
        c15, h15, l15, v15 = ohlc_15m
        c1h, h1h, l1h, v1h = ohlc_1h
        c4h, h4h, l4h, v4h = ohlc_4h

        m5 = deteksi_rezim_pasar(c5, h5, l5)
        m15 = deteksi_rezim_pasar(c15, h15, l15)
        h1 = deteksi_rezim_pasar(c1h, h1h, l1h)
        h4 = deteksi_rezim_pasar(c4h, h4h, l4h)

        spread_aman = spread_pct <= MAX_SPREAD_INDODAX_PCT
        vol_rata_5m = sum(v5[-20:-1]) / 19.0 if len(v5) >= 20 else (v5[-1] or 1.0)
        rasio_vol = v5[-1] / (vol_rata_5m or 1.0)
        candle_5m_hijau = c5[-1] >= c5[-2]
        candle_jatuh_beruntun = (c5[-1] < c5[-2] < c5[-3])

        # SYARAT ENTRY GRID (4 rezim di M15 & H1 + Rem Makro H4 tidak DOWNTREND + Anti-Pucuk + Volatilitas)
        rezim_boleh = ("UPTREND", "SIDEWAYS_UP")
        h4_aman = h4["rezim"] != "DOWNTREND"
        h1_aman = h1["rezim"] in rezim_boleh
        m15_aman = m15["rezim"] in rezim_boleh
        tidak_pucuk = m5["rsi"] <= GRID_MAX_RSI_M5_ENTRY and m15["rsi"] <= 68.0
        volatilitas_cukup = m15["atr_pct"] >= GRID_MIN_ATR_15M_PCT
        koin_diizinkan = (coin in GRID_ALLOWED_COINS)

        layak_grid = bool(
            koin_diizinkan
            and h4_aman
            and h1_aman
            and m15_aman
            and tidak_pucuk
            and volatilitas_cukup
            and spread_aman
            and not candle_jatuh_beruntun
        )

        # Skor prioritas pemilihan koin terbaik untuk Grid
        skor_grid = 50.0
        if h4["rezim"] == "UPTREND":
            skor_grid += 8.0
        elif h4["rezim"] == "SIDEWAYS_UP":
            skor_grid += 5.0
        if h1["rezim"] == "UPTREND":
            skor_grid += 12.0
        elif h1["rezim"] == "SIDEWAYS_UP":
            skor_grid += 10.0
        if m15["rezim"] == "SIDEWAYS_UP":
            skor_grid += 15.0  # Sideways cenderung naik adalah kondisi favorit Grid
        elif m15["rezim"] == "UPTREND":
            skor_grid += 10.0
        if 35.0 <= m5["rsi"] <= 55.0:
            skor_grid += 10.0  # Bonus beli di pullback sehat (bukan pucuk)
        if not layak_grid:
            skor_grid = min(skor_grid, 45.0)

        # Evaluasi peluang swing balik naik (dipakai saat harga sedang di bawah b3)
        peluang_rebound_b3 = bool(
            h1["rsi"] <= 48.0
            or m15["rsi"] <= 38.0
            or h4["rezim"] in ("UPTREND", "SIDEWAYS_UP")
            or h1["rezim"] in ("UPTREND", "SIDEWAYS_UP")
            or candle_5m_hijau
        )

        if layak_grid:
            prediksi = f"🟢 LAYAK GRID ({m15['rezim']} 15M | {h1['rezim']} 1H | {h4['rezim']} 4H | ATR15M:{m15['atr_pct']*100:.2f}%)"
        elif not h4_aman:
            prediksi = f"🔴 REM MAKRO H4 ({h4['rezim']} 4H - Tahan Entry di Bear Market)"
        elif h1["rezim"] in ("DOWNTREND", "SIDEWAYS_DOWN") or m15["rezim"] in ("DOWNTREND", "SIDEWAYS_DOWN"):
            prediksi = f"🔴 BLOKIR GRID ({m15['rezim']} 15M / {h1['rezim']} 1H - Hindari Downtrend)"
        elif not tidak_pucuk:
            prediksi = f"🟡 TUNDA GRID (Overbought RSI 5M:{m5['rsi']} - Tunggu Pullback)"
        elif not volatilitas_cukup:
            prediksi = f"🟡 PASAR TERLALU SEPI (ATR 15M:{m15['atr_pct']*100:.2f}% < {GRID_MIN_ATR_15M_PCT*100:.2f}%)"
        else:
            prediksi = f"⚠️ SPREAD LEBAR ({spread_pct*100:.2f}%)"

        entry_ideal_idr = bulatkan_harga_indodax(coin, harga_bid)  # Pakai harga Bid agar 100% Maker
        tp_ideal_idr = bulatkan_harga_indodax(coin, entry_ideal_idr * (1.0 + GRID_STEP_PCT))
        sl_ideal_idr = bulatkan_harga_indodax(coin, entry_ideal_idr * (1.0 - (GRID_STEP_PCT * 2.0)))

        peta_analisa[coin] = {
            "coin": coin,
            "sumber_ohlc": "INDODAX-NATIVE-MTF",
            "harga_idr": harga_idr,
            "harga_bid": harga_bid,
            "harga_ask": harga_ask,
            "spread_pct": spread_pct,
            "high_2jam_idr": round(max(h5[-24:]), 0),
            "tren": "UPTREND" if (h1_aman and h4_aman) else "SIDEWAYS/DOWN",
            "tren_5m_naik": m5["rezim"] in rezim_boleh,
            "tren_15m_naik": m15_aman,
            "candle_5m_hijau": candle_5m_hijau,
            "candle_jatuh_beruntun": candle_jatuh_beruntun,
            "tren_detail": f"5M:{m5['rezim']}|15M:{m15['rezim']}|1H:{h1['rezim']}|4H:{h4['rezim']}",
            "rezim_5m": m5["rezim"],
            "rezim_15m": m15["rezim"],
            "rezim_1h": h1["rezim"],
            "rezim_4h": h4["rezim"],
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
            "tp_target_pct": round(GRID_STEP_PCT * 100.0, 2),
            "gaya": "GRID_3L" if layak_grid else "WAIT",
            "skor": round(skor_grid, 1),
            "prediksi": prediksi,
            "siap_entry": layak_grid,
            "layak_grid": layak_grid,
            "peluang_rebound_b3": peluang_rebound_b3,
            "bobot_alokasi": round(skor_grid, 2)
        }
    return peta_analisa

_MODEL_GEMINI_HABIS_KUOTA = set()
_MODEL_GEMINI_AKTIF = None
_LEVEL_PENALARAN_AKTIF = "MENENGAH (1024 Token Penalaran)"

def ambil_daftar_kunci_api_gemini():
    """Mendukung multi-API key (dipisah koma di GEMINI_API_KEY atau GEMINI_API_KEY_2..5)."""
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

def dapatkan_daftar_model_gemini():
    """Urutan model: gemini-3-flash-preview (utama) -> fallback gemini-2.5-flash (cadangan)."""
    semua_model = [
        "gemini-3-flash-preview",
        "gemini-2.5-flash"
    ]
    model_tersedia = [m for m in semua_model if m not in _MODEL_GEMINI_HABIS_KUOTA]
    return model_tersedia if model_tersedia else semua_model

def panggil_teks_gemini_ai(prompt, timeout_detik=20, mode_penalaran="MENENGAH"):
    """Panggilan Gemini terpadu dengan Multi-Key Rotation, Model Fallback, & thinkingBudget."""
    global _MODEL_GEMINI_HABIS_KUOTA, _MODEL_GEMINI_AKTIF, _LEVEL_PENALARAN_AKTIF
    daftar_kunci = ambil_daftar_kunci_api_gemini()
    if not daftar_kunci:
        return None, "GEMINI_API_KEY kosong"

    daftar_model = dapatkan_daftar_model_gemini()
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
                            _MODEL_GEMINI_AKTIF = nama_model
                            _LEVEL_PENALARAN_AKTIF = f"{mode_penalaran} ({budget_pikir} Token)" if idx_p == 0 else f"{mode_penalaran} (Default Server)"
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
            _MODEL_GEMINI_HABIS_KUOTA.add(nama_model)

    return None, " | ".join(catatan_err)

def konsultasi_batch_terpadu_gemini(daftar_tugas_ai, status_kompas_btc, defisit_recovery_idr=0.0):
    """
    1x Unified Batch Call per siklus untuk seluruh keputusan:
    BELI_BARU (Entry), EXIT_PROFIT (Scratch/TP Range/Time-Stop), dan EVALUASI_SL (Smart/Hard SL).
    """
    hasil_batch = {}
    if not daftar_tugas_ai:
        return hasil_batch

    if not ambil_daftar_kunci_api_gemini():
        for t in daftar_tugas_ai:
            hasil_batch[t["id"]] = (
                bool(t.get("default_jika_error", False)),
                f"[QUANT-FALLBACK] {t.get('alasan_fallback', 'Tanpa API Key Gemini.')}",
                True
            )
        return hasil_batch

    konteks_mode = (
        f"MODE RECOVERY AKTIF (Target tutup defisit Rp{defisit_recovery_idr:,.0f}, seleksi ketat)"
        if defisit_recovery_idr > 0 else "Mode Normal"
    )
    baris_tugas = [f"[{t['id']}] {t['deskripsi']}" for t in daftar_tugas_ai]
    prompt_batch = (
        f"Anda adalah Chief Quant Scalper & Risk Manager 5M Indodax ({konteks_mode}). Evaluasi seluruh paket data berikut sekaligus.\n"
        f"Konteks Pasar: Kompas BTCIDR={status_kompas_btc}.\n"
        f"Aturan Keputusan:\n"
        f"- TIPE BELI_BARU: Jawab YA (eksekusi beli) atau TUNDA (jangan beli).\n"
        f"- TIPE EXIT_PROFIT (Scratch/TP Range/Time-Stop): Jawab YA (jual sekarang amankan profit) atau TAHAN (kawal ke TP penuh).\n"
        f"- TIPE EVALUASI_SL (Smart SL -0.70% / Hard SL -1.05%, Emergency SL mutlak -1.45%): Jawab YA (cut loss sekarang) atau TAHAN (tunggu pantulan).\n"
        f"Daftar Tugas ({len(daftar_tugas_ai)} item):\n"
        + "\n".join(baris_tugas) + "\n\n"
        f"INSTRUKSI JAWABAN:\n"
        f"Jawab WAJIB 1 baris per ID dengan format persis:\n"
        f"[ID]: KEPUTUSAN - alasan singkat maksimal 10 kata"
    )

    teks_respons, err_info = panggil_teks_gemini_ai(prompt_batch, timeout_detik=20, mode_penalaran="MENENGAH")
    if not teks_respons:
        print(f"⚠️ [GEMINI BATCH LIMIT -> QUANT FALLBACK AKTIF]: {err_info}")
        for t in daftar_tugas_ai:
            hasil_batch[t["id"]] = (
                bool(t.get("default_jika_error", False)),
                f"[QUANT-FALLBACK] {t.get('alasan_fallback', str(err_info)[:45])}",
                True
            )
        return hasil_batch

    model_tag = "[gemini-batch]"
    if teks_respons.startswith("[") and "]" in teks_respons:
        model_tag = teks_respons.split("]", 1)[0] + "]"
        isi_murni = teks_respons.split("]", 1)[1].strip()
    else:
        isi_murni = teks_respons.strip()

    for t in daftar_tugas_ai:
        tid = t["id"]
        jenis = t.get("jenis", "EVALUASI_SL")
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
    antrean_batch_exit = []

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
                sukses_batal, _ = batalkan_order_indodax(coin, slot.get("buy_order_id"))
                if dompet["terhubung"] and not sukses_batal:
                    st_cek, _ = cek_status_order_indodax(coin, slot.get("buy_order_id"))
                    if st_cek == "FILLED":
                        log_aksi.append(f"✅ [BATAL DIGAGALKAN - SUDAH TERBELI] Order beli {coin} ternyata baru saja terisi di Indodax.")
                        slot_tetap_aktif.append(slot)
                        continue
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
                sukses_batal, _ = batalkan_order_indodax(coin, slot.get("buy_order_id"))
                if dompet["terhubung"] and not sukses_batal:
                    st_cek, _ = cek_status_order_indodax(coin, slot.get("buy_order_id"))
                    if st_cek == "FILLED":
                        log_aksi.append(f"✅ [GESER DIGAGALKAN - SUDAH TERBELI] Order beli {coin} ternyata baru saja terisi di Indodax.")
                        slot_tetap_aktif.append(slot)
                        continue
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
                else:
                    # Jika order lama sudah terlanjur dibatalkan tapi pasang order baru gagal, kembalikan dana ke saldo bebas
                    dompet["idr_free"] = float(dompet.get("idr_free", 0.0)) + modal_slot
                    log_aksi.append(f"⚠️ [GESER ENTRY GAGAL] Order lama {coin} dibatalkan, pasang ulang gagal -> dana kembali ke Rupiah.")
                    continue

            # 4. Evaluasi batas waktu antre maksimal (1.5 Jam)
            if umur_antre_jam >= REVIEW_ENTRY_HOURS:
                sukses_batal, _ = batalkan_order_indodax(coin, slot.get("buy_order_id"))
                if dompet["terhubung"] and not sukses_batal:
                    st_cek, _ = cek_status_order_indodax(coin, slot.get("buy_order_id"))
                    if st_cek == "FILLED":
                        log_aksi.append(f"✅ [TIMEOUT DIGAGALKAN - SUDAH TERBELI] Order beli {coin} ternyata baru saja terisi di Indodax.")
                        slot_tetap_aktif.append(slot)
                        continue
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

            # Jika terhubung ke Indodax tapi koin sudah habis di dompet, jangan pernah dikawal lagi!
            if dompet["terhubung"] and nilai_koin_idr < 5000:
                log_aksi.append(f"🧹 [GUARD SALDO 0] {coin} kosong di dompet Indodax, slot dilepas.")
                continue

            qty_dimiliki = format_qty_koin(coin, total_koin_dimiliki if dompet["terhubung"] else slot.get("qty", 0))
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
                berhasil_jual, harga_eksekusi_jual, _ = eksekusi_jual_terverifikasi(coin, harga_eksekusi_jual, qty_dimiliki, prioritas_market=False)
                if berhasil_jual:
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
                antrean_batch_exit.append({
                    "id": f"EXIT_{coin}_{idx_slot}",
                    "jenis": "EXIT_PROFIT",
                    "slot": slot,
                    "coin": coin,
                    "mode_slot": mode_slot,
                    "entry_idr": entry_idr,
                    "tp_idr": tp_idr,
                    "harga_sekarang": harga_sekarang,
                    "harga_eksekusi_jual": harga_eksekusi_jual,
                    "kenaikan_bid_pct": kenaikan_bid_pct,
                    "qty_dimiliki": qty_dimiliki,
                    "koin_free": koin_free,
                    "lama_pegang_jam": lama_pegang_jam,
                    "label_exit": label_exit,
                    "default_jika_error": True,
                    "alasan_fallback": f"YA - Quant Fallback mengamankan profit Bid +{kenaikan_bid_pct*100:.2f}% ({label_exit}).",
                    "deskripsi": (
                        f"TIPE: EXIT_PROFIT | Koin {coin} ({mode_slot}) Beli:Rp{entry_idr:,.0f}, Target TP:Rp{tp_idr:,.0f}, "
                        f"Puncak:Rp{puncak_tercatat:,.0f}, Skrg Bid:Rp{harga_eksekusi_jual:,.0f} (Untung Bersih +{estimasi_untung_bersih_pct:.2f}% setelah fee) "
                        f"[{label_exit}]. Tren:{tren_detail}, RSI 5M:{rsi_sekarang}, Diagnosa:{prediksi_koin}."
                    )
                })
                continue

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

    state["active_slots"] = slot_tetap_aktif
    return state, log_aksi, log_transaksi, ada_eksekusi_penting, antrean_batch_exit, antrean_batch_sl

# ==============================================================================
# BAGIAN 7: ALOKASI MODAL PRO & STRATEGI BALIK MODAL (POIN 4 & POIN 5)
# ==============================================================================
def kelola_anggaran_kosong_dengan_analisa(state, peta_analisa, dompet, pending_slots=None):
    semua_slot_aktif = state["active_slots"] + (pending_slots or [])
    modal_aktif_state = sum(float(s.get("capital_idr", 0)) for s in semua_slot_aktif)
    sisa_plafon_bot = max(0.0, MAX_BOT_CAPITAL_IDR - modal_aktif_state)
    saldo_idr_tersedia = min(dompet["idr_free"], sisa_plafon_bot) if dompet["terhubung"] else sisa_plafon_bot

    slot_terisi = len(semua_slot_aktif)
    sisa_slot_maks = max(0, MAX_CONCURRENT_COINS - slot_terisi)

    if saldo_idr_tersedia < MIN_NEW_BUY_ALLOCATION_IDR or sisa_slot_maks <= 0:
        return state, [
            f"[MODAL AKTIF BEKERJA] Rp{modal_aktif_state:,.0f} di {slot_terisi} posisi (Sisa IDR: Rp{dompet['idr_free']:,.0f})."
        ], [], False, []

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

    koin_sudah_ada = {s["coin"] for s in semua_slot_aktif}
    # Kunci Mutlak Lapis 1: Blokir koin yang saldonya sudah ada di dompet Indodax (>= Rp5.000)
    if dompet.get("terhubung"):
        for c_cek in WATCHLIST_COINS.keys():
            qty_dompet = dompet["coins_free"].get(c_cek, 0.0) + dompet["coins_locked"].get(c_cek, 0.0)
            harga_c = peta_analisa.get(c_cek, {}).get("harga_idr", 0.0)
            if qty_dompet * harga_c >= 5000.0:
                koin_sudah_ada.add(c_cek)
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
        ], [], False, []

    jumlah_siap = len(kandidat_siap_entry)
    total_bobot = sum(k.get("bobot_alokasi", k["skor"]) for k in kandidat_siap_entry)
    log_alokasi = []
    log_transaksi_beli = []
    ada_order_baru = False
    sisa_kas = saldo_idr_tersedia
    antrean_batch_entry = []

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

        antrean_batch_entry.append({
            "id": f"BELI_{coin}",
            "jenis": "BELI_BARU",
            "kandidat": kandidat,
            "qty_rencana": qty_rencana,
            "nilai_efektif_idr": nilai_efektif_idr,
            "default_jika_error": False,  # Wajib menunggu Gemini aktif jika semua API Key limit (429)
            "alasan_fallback": f"TUNDA - Kuota Gemini limit, entry baru {coin} ditahan sampai AI aktif.",
            "deskripsi": (
                f"TIPE: BELI_BARU | Koin {coin} ({gaya}, Skor:{kandidat['skor']}), "
                f"Harga Skrg:Rp{kandidat['harga_idr']:,.0f}, Rencana Beli:Rp{entry_idr:,.0f}, "
                f"Target TP Dinamis:+{kandidat['tp_target_pct']}% (Modal Rp{nilai_efektif_idr:,.0f}). "
                f"Tren:{kandidat['tren_detail']}, RSI 5M:{kandidat['rsi']}, RSI 15M:{kandidat['rsi_15m']}, "
                f"Vol:{kandidat['rasio_vol']}x, Spread:{kandidat['spread_pct']*100:.2f}%."
            )
        })
        sisa_kas -= nilai_efektif_idr
        anggaran_sesi_ini = max(0.0, anggaran_sesi_ini - nilai_efektif_idr)

    return state, log_alokasi, log_transaksi_beli, ada_order_baru, antrean_batch_entry

def eksekusi_hasil_batch_terpadu(state, peta_analisa, dompet, antrean_batch_exit, antrean_batch_sl, antrean_batch_entry):
    """Mengirim 1x Batch Call ke Gemini AI untuk Exit + SL + Entry, lalu mengeksekusi hasilnya serentak."""
    log_batch = []
    log_tx_batch = []
    ada_aksi_batch = False
    now_ts = time.time()

    for item_sl in antrean_batch_sl:
        item_sl["jenis"] = "EVALUASI_SL"

    daftar_tugas_ai = antrean_batch_exit + antrean_batch_sl + antrean_batch_entry
    if not daftar_tugas_ai:
        return state, log_batch, log_tx_batch, ada_aksi_batch

    info_btc = peta_analisa.get("BTC", {})
    status_kompas_btc = f"{info_btc.get('tren_detail', 'N/A')} (RSI 5M:{info_btc.get('rsi', '-')})"
    defisit_recovery = float(state.get("loss_to_recover_idr", 0.0))

    hasil_batch = konsultasi_batch_terpadu_gemini(daftar_tugas_ai, status_kompas_btc, defisit_recovery)

    # 1. EKSEKUSI KEPUTUSAN EXIT PROFIT (SCRATCH / TP RANGE / TIME-STOP)
    for item_ex in antrean_batch_exit:
        slot = item_ex["slot"]
        coin = item_ex["coin"]
        mode_slot = item_ex["mode_slot"]
        tp_idr = item_ex["tp_idr"]
        qty_dimiliki = item_ex["qty_dimiliki"]
        label_exit = item_ex["label_exit"]
        kenaikan_bid_pct = item_ex["kenaikan_bid_pct"]

        setuju_jual, alasan_ai, _ = hasil_batch.get(
            item_ex["id"], (item_ex["default_jika_error"], item_ex["alasan_fallback"], True)
        )
        if setuju_jual:
            if slot.get("tp_order_id"):
                batalkan_order_indodax(coin, slot["tp_order_id"])
                slot["tp_order_id"] = None
                time.sleep(2)
            berhasil_jual, harga_eksekusi_jual, _ = eksekusi_jual_terverifikasi(
                coin, item_ex["harga_eksekusi_jual"], qty_dimiliki, prioritas_market=False
            )
            if berhasil_jual:
                profit_bersih = round(slot["capital_idr"] * (kenaikan_bid_pct - FEE_ROUNDTRIP_MAKER_PCT), 0)
                catat_hasil_transaksi_ke_recovery(
                    state, profit_bersih, coin, slot=slot, pnl_exit_pct=(kenaikan_bid_pct - FEE_ROUNDTRIP_MAKER_PCT)
                )
                ada_aksi_batch = True
                pesan = (
                    f"⚡ [{label_exit} DIEKSEKUSI] {coin} dijual di Rp{harga_eksekusi_jual:,.0f} "
                    f"({kenaikan_bid_pct*100:.2f}%, Profit Bersih: Rp{profit_bersih:,.0f}) | AI: {alasan_ai}"
                )
                log_batch.append(pesan)
                log_tx_batch.append(pesan)
                continue
            else:
                pasang_antrean_tp_di_indodax(slot, qty_dimiliki)
        else:
            log_batch.append(
                f"💎 [{label_exit} DITAHAN GEMINI AI] {coin} (Bid:+{kenaikan_bid_pct*100:.2f}%) dikawal menuju TP Rp{tp_idr:,.0f} | AI: {alasan_ai}"
            )

        if not slot.get("tp_order_id") and (not dompet["terhubung"] or item_ex["koin_free"] > 0):
            pasang_antrean_tp_di_indodax(slot, item_ex["koin_free"])
            ada_aksi_batch = True
            pesan = f"📌 [PASANG ULANG TP] Antrean TP {coin} diaktifkan di Rp{slot['tp_price_idr']:,.0f}."
            log_batch.append(pesan)
            log_tx_batch.append(pesan)

        status_tp_order = f"OrderTP:#{slot.get('tp_order_id')}" if slot.get("tp_order_id") else "TP-Aktif"
        log_batch.append(
            f"🎯 [KAWAL {status_tp_order} | {item_ex['lama_pegang_jam']:.1f}j] {coin} ({mode_slot}) | Skrg: Rp{item_ex['harga_sekarang']:,.0f} "
            f"(Bid:{kenaikan_bid_pct*100:+.2f}%) -> TP: Rp{tp_idr:,.0f} | SL: Rp{slot['sl_price_idr']:,.0f}"
        )
        state["active_slots"].append(slot)

    # 2. EKSEKUSI KEPUTUSAN STOP LOSS (SMART SL -0.70% / HARD SL -1.05%)
    for item_sl in antrean_batch_sl:
        slot = item_sl["slot"]
        coin = item_sl["coin"]
        mode_slot = item_sl["mode_slot"]
        entry_idr = item_sl["entry_idr"]
        tp_idr = item_sl["tp_idr"]
        qty_dimiliki = item_sl["qty_dimiliki"]
        label_sl = item_sl["label_sl"]

        setuju_sl_ai, alasan_sl_ai, dari_fallback = hasil_batch.get(
            item_sl["id"], (item_sl["default_jika_error"], item_sl["alasan_fallback"], True)
        )
        if setuju_sl_ai:
            if slot.get("tp_order_id"):
                batalkan_order_indodax(coin, slot["tp_order_id"])
                slot["tp_order_id"] = None
                time.sleep(1.0)
            harga_jual_sl = bulatkan_harga_indodax(coin, min(item_sl["harga_bid_asli"], item_sl["harga_sekarang"] * 0.998))
            berhasil_sl, harga_jual_sl, _ = eksekusi_jual_terverifikasi(coin, harga_jual_sl, qty_dimiliki, prioritas_market=False)
            if berhasil_sl:
                pnl_exit_pct = ((harga_jual_sl - entry_idr) / entry_idr) - FEE_ROUNDTRIP_MAKER_PCT
                pnl_bersih = round(slot["capital_idr"] * pnl_exit_pct, 0)
                catat_hasil_transaksi_ke_recovery(state, pnl_bersih, coin, slot=slot, pnl_exit_pct=pnl_exit_pct)
                ada_aksi_batch = True
                pesan = (
                    f"🛡️ [{label_sl} DIEKSEKUSI] {coin} ({mode_slot}) dijual di Rp{harga_jual_sl:,.0f} "
                    f"(Bid:{item_sl['kenaikan_bid_pct']*100:+.2f}%, PnL: Rp{pnl_bersih:,.0f} | Cooldown {SL_COOLDOWN_MINUTES}m & Mode Recovery Aktif) | AI: {alasan_sl_ai}"
                )
                log_batch.append(pesan)
                log_tx_batch.append(pesan)
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
            log_batch.append(
                f"🛑 [{label_sl} DITAHAN GEMINI AI (Jeda 5m)] {coin} (Bid:{item_sl['kenaikan_bid_pct']*100:+.2f}%) ditahan menunggu pantulan | AI: {alasan_sl_ai}"
            )

        if not slot.get("tp_order_id") and (not dompet["terhubung"] or item_sl["koin_free"] > 0):
            pasang_antrean_tp_di_indodax(slot, item_sl["koin_free"])
            ada_aksi_batch = True
            pesan = f"📌 [PASANG ULANG TP] Antrean TP {coin} diaktifkan di Rp{slot['tp_price_idr']:,.0f}."
            log_batch.append(pesan)
            log_tx_batch.append(pesan)

        status_tp_order = f"OrderTP:#{slot.get('tp_order_id')}" if slot.get("tp_order_id") else "TP-Aktif"
        log_batch.append(
            f"🎯 [KAWAL {status_tp_order} | {item_sl['lama_pegang_jam']:.1f}j] {coin} ({mode_slot}) | Skrg: Rp{item_sl['harga_sekarang']:,.0f} "
            f"(Bid:{item_sl['kenaikan_bid_pct']*100:+.2f}%) -> TP: Rp{tp_idr:,.0f} | SL: Rp{slot['sl_price_idr']:,.0f}"
        )
        state["active_slots"].append(slot)

    # 3. EKSEKUSI KEPUTUSAN BELI BARU (ENTRY)
    for item_en in antrean_batch_entry:
        kandidat = item_en["kandidat"]
        coin = kandidat["coin"]
        gaya = kandidat["gaya"]
        entry_idr = kandidat["entry_ideal_idr"]
        qty_rencana = item_en["qty_rencana"]
        nilai_efektif_idr = item_en["nilai_efektif_idr"]

        setuju_beli, alasan_gemini, _ = hasil_batch.get(
            item_en["id"], (item_en["default_jika_error"], item_en["alasan_fallback"], True)
        )
        if not setuju_beli:
            log_batch.append(f"⏸️ [GEMINI AI HOLD ENTRY {coin}] Setup ditunda AI: {alasan_gemini}")
            continue

        # Kunci Mutlak Lapis 2 & 3: Tolak beli jika koin sudah ada di slot aktif atau punya Open Order di Indodax
        if any(s.get("coin") == coin for s in state["active_slots"]):
            log_batch.append(f"🛡️ [BLOKIR DUPLIKAT {coin}] Sudah ada posisi aktif di state bot, batal beli ulang.")
            continue
        if dompet.get("terhubung"):
            ok_oo, daftar_oo = ambil_open_orders_indodax(coin)
            if ok_oo and len(daftar_oo) > 0:
                log_batch.append(
                    f"🛡️ [BLOKIR DUPLIKAT INDODAX {coin}] Terdeteksi {len(daftar_oo)} Open Order aktif di Indodax, batal beli ulang."
                )
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
            ada_aksi_batch = True
            persen_plafon = (nilai_efektif_idr / MAX_BOT_CAPITAL_IDR) * 100.0
            label_rec = " [RECOVERY SETUP]" if defisit_recovery > 0 else ""
            pesan = (
                f"🚀 [ENTRY ORDER BELI #{order_id} - {gaya}{label_rec}] {coin} (Skor:{kandidat['skor']}) | "
                f"Alokasi: Rp{nilai_efektif_idr:,.0f} ({persen_plafon:.0f}% Modal) | "
                f"Beli: Rp{entry_idr:,.0f} -> TP Dinamis (+{tp_target_pct}%): Rp{tp_idr:,.0f} | AI: {alasan_gemini}"
            )
            log_batch.append(pesan)
            log_tx_batch.append(pesan)

    return state, log_batch, log_tx_batch, ada_aksi_batch

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
        rekap_wr_total = "Belum ada transaksi selesai dlm 7 hari terakhir"
        rekap_wr_koin = "-"

    jml_bangkit_72j = sum(1 for m in tahan_sl_72j if m.get("hasil") == "SUKSES_BANGKIT")
    jml_gagal_72j = sum(1 for m in tahan_sl_72j if m.get("hasil") == "GAGAL_PANTUL")
    rekap_tahan_sl = (
        f"{jml_bangkit_72j}x Bangkit vs {jml_gagal_72j}x Gagal"
        if tahan_sl_72j else "Belum ada riwayat tahan SL"
    )

# Rekap Memori Pengalaman Siklus Grid 1 Minggu (168 Jam)
    batas_grid_7h = time.time() - (GRID_MEMORY_RETENTION_HOURS * 3600.0)
    mem_grid_7h = [
        m for m in state.get("grid_experience_memory", [])
        if float(m.get("ts", 0.0)) >= batas_grid_7h
    ]
    if mem_grid_7h:
        tot_siklus = len(mem_grid_7h)
        tot_panen_7h = sum(int(m.get("bounce_count", 0)) for m in mem_grid_7h)
        tot_pnl_7h = sum(float(m.get("total_pnl_idr", 0.0)) for m in mem_grid_7h)
        jml_sentuh_b3 = sum(1 for m in mem_grid_7h if m.get("b3_ever_touched"))
        rekap_grid_7h = (
            f"{tot_siklus} Siklus ({tot_panen_7h}x Panen | Net: Rp{tot_pnl_7h:+,.0f} | Sentuh b3: {jml_sentuh_b3}x)"
        )
    else:
        rekap_grid_7h = "Belum ada siklus Grid selesai dlm 7 hari terakhir"

    ringkasan_pasar = (
        f"Pasar [{sumber_grafik} 5M+15M+1H]: {len(koin_uptrend)}/{total_koin_pasar} koin UPTREND | "
        f"Rata-rata RSI 5M: {rata_rsi_5m:.1f} | Kompas: {kompas_btc_str} | Sinyal Tertinggi: {info_skor_tertinggi}\n"
        f"   -> Mode Recovery Balik Modal:{status_rec_str}\n"
        f"   -> Statistik Memori 7H (Total Bot): {rekap_wr_total} | Tahan SL: {rekap_tahan_sl}\n"
        f"   -> Win Rate 7H Per Koin: {rekap_wr_koin}\n"
        f"   -> Memori Siklus Grid 7H: {rekap_grid_7h}\n"
        f"   -> Koin Berstatus SIAP ENTRY Saat Ini ({len(koin_siap_beli)} koin): {', '.join(koin_siap_beli) or 'Belum ada (menunggu konfirmasi candle 5M hijau)'}"
    )

    detail_diagnosa_koin = []
    info_grid_md = "-"

    if GRID_MODE_ENABLED:
        cycle = state.get("grid_cycle")
        if cycle:
            coin = cycle["coin"]
            info = peta_analisa.get(coin, {})
            layers = cycle.get("layers", {})
            p1_ref = float(layers.get("b1", {}).get("buy_price", 0.0))
            skrg = info.get("harga_idr", p1_ref)
            harga_bid = info.get("harga_bid", skrg)
            tren_k = info.get("tren_detail", "-")
            prediksi_k = info.get("prediksi", "-")
            rsi_5m = info.get("rsi", "-")
            rsi_15m = info.get("rsi_15m", "-")
            rsi_1h = info.get("rsi_1h", "-")
            bounces = int(cycle.get("bounce_count", 0))
            realized_grid = float(cycle.get("realized_grid_profit_idr", 0.0))
            b3_sentuh = "PERNAH" if cycle.get("b3_ever_touched") else "BELUM"
            lama_jam = (time.time() - float(cycle.get("created_ts", time.time()))) / 3600.0

            floating_grid_idr = 0.0
            rincian_lapis = []
            for nama_lp in ("b1", "b2", "b3"):
                lp = layers.get(nama_lp, {})
                st_lp = lp.get("status", "-")
                bp = float(lp.get("buy_price", 0.0))
                tp = float(lp.get("tp_price", 0.0))
                qty_lp = float(lp.get("qty", 0.0))
                if st_lp == "HOLDING" and bp > 0:
                    pnl_lp_pct = ((harga_bid - bp) / bp) * 100.0
                    floating_grid_idr += (harga_bid - bp) * qty_lp
                    rincian_lapis.append(
                        f"{nama_lp.upper()}:HOLD ({pnl_lp_pct:+.2f}% | Beli Rp{bp:,.0f}->TP Rp{tp:,.0f})"
                    )
                else:
                    rincian_lapis.append(f"{nama_lp.upper()}:{st_lp} (@Rp{bp:,.0f}->TP Rp{tp:,.0f})")

            info_grid_md = (
                f"{coin} | Panen: {bounces}x (+Rp{realized_grid:,.0f}) | "
                f"Floating: Rp{floating_grid_idr:+,.0f} | b3 Tersentuh: {b3_sentuh}"
            )
            detail_diagnosa_koin.append(
                f"   * [GRID 3-LAPIS | {lama_jam:.1f}j] {coin} @ Rp{skrg:,.0f} (Bid: Rp{harga_bid:,.0f}) -> {prediksi_k}\n"
                f"     Tren: [{tren_k}] | RSI 5M:{rsi_5m} / 15M:{rsi_15m} / 1H:{rsi_1h}\n"
                f"     Panen Siklus: {bounces}x (+Rp{realized_grid:,.0f}) | Floating: Rp{floating_grid_idr:+,.0f} | Sentuh b3: {b3_sentuh}\n"
                f"     Lapis: {' | '.join(rincian_lapis)}"
            )
        else:
            info_grid_md = "Cash is King (Menunggu syarat Grid M15 & H1)"
            detail_diagnosa_koin.append(
                "   * Belum ada siklus Grid 3-Lapis aktif (100% Cash is King - Menunggu syarat Sideways-Up / Uptrend M15 & H1)."
            )
    else:
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

    teks_diagnosa = "\n".join(detail_diagnosa_koin) if detail_diagnosa_koin else "   * Belum ada posisi aktif (100% Cash is King)."
    judul_mode = "PATROLI GRID 3-LAPIS SELESAI" if GRID_MODE_ENABLED else "PATROLI PRO SCALPER 5M SELESAI"

    teks_final = (
        f"🟢 [{judul_mode} | Profit Hari Ini: Rp{state.get('realized_profit_today_idr', 0):,.0f} ({state.get('completed_trades_today', 0)} Trade)]\n"
        f"📊 DIAGNOSA PORTOFOLIO & PREDIKSI CANDLESTICK RUPIAH INDODAX (5M + 15M + 1H):\n"
        f"{teks_diagnosa}\n"
        f"   -> {ringkasan_pasar}"
    )

    summary_file = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if summary_file:
        try:
            tz_wib = timezone(timedelta(hours=7))
            waktu_run = datetime.now(tz_wib).strftime("%Y-%m-%d %H:%M:%S WIB")
            baris_grid_md = f"- **Status Grid 3-Lapis:** {info_grid_md}\n" if GRID_MODE_ENABLED else ""
            md_summary = (
                f"### 📊 Ringkasan Patroli & Win Rate 7 Hari ({waktu_run})\n"
                f"- **Profit Hari Ini:** Rp{state.get('realized_profit_today_idr', 0):,.0f} ({state.get('completed_trades_today', 0)} Trade)\n"
                f"{baris_grid_md}"
                f"- **Memori Siklus Grid 7H:** {rekap_grid_7h}\n"
                f"- **Win Rate 7H (Total Bot):** {rekap_wr_total}\n"
                f"- **Win Rate 7H (Per Koin):** {rekap_wr_koin}\n"
                f"- **Rekor Tahan SL 7H:** {rekap_tahan_sl}\n"
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
# MESIN GRID 3-LAPIS PERSISTEN (b1, b2, b3) + AUTO-RESET + SWING HOLD BAWAH b3
# ==============================================================================
def kelola_siklus_grid_3_lapis(state, peta_analisa, dompet):
    """
    Mengelola 1 siklus Grid 3-Lapis (b1, b2, b3 @ ~Rp33.000) secara persisten:
    - b1 terbeli -> pasang Limit Sell b1 (+1.50%) + Limit Buy b2 (-1.50%) + Limit Buy b3 (-3.00%).
    - b2 terbeli -> pasang Limit Sell di b1. Jika laku -> pasang ulang Limit Buy b2.
    - b3 terbeli -> pasang Limit Sell di b2. Jika laku -> pasang ulang Limit Buy b3.
    - Jika harga < b3 & teknikal melihat peluang balik ke b2/b1 -> TAHAN (Swing Hold) tanpa cut loss.
    - Jika b3 pernah tersentuh & pantulan >= 3x lalu harga balik ke >= b2 dengan total siklus untung -> Jual semua & reset.
    """
    log_grid = []
    log_tx = []
    ada_aksi = False
    now_ts = time.time()
    cycle = state.get("grid_cycle")

    # ==========================================================================
    # TAHAP A: BELUM ADA SIKLUS GRID AKTIF -> CARI KOIN TERBAIK SESUAI 4 SYARAT
    # ==========================================================================
    if not cycle:
        info_btc = peta_analisa.get("BTC", {})
        btc_downtrend_keras = (
            info_btc.get("rezim_4h") == "DOWNTREND"
            or (info_btc.get("rezim_1h") == "DOWNTREND" and info_btc.get("rsi_15m", 50.0) < 35.0)
        )
        if btc_downtrend_keras:
            log_grid.append(
                f"⏸️ [GRID WAIT] Kompas BTC sedang DOWNTREND (1H:{info_btc.get('rezim_1h')} / 4H:{info_btc.get('rezim_4h')} | RSI15M:{info_btc.get('rsi_15m')}), tahan di Rupiah."
            )
            return state, log_grid, log_tx, False

        modal_dibutuhkan = GRID_CAPITAL_PER_LAYER_IDR * 3.0
        if dompet.get("terhubung") and dompet.get("idr_free", 0.0) < (modal_dibutuhkan * 0.95):
            log_grid.append(
                f"⏸️ [GRID MODAL KURANG] Saldo IDR bebas Rp{dompet.get('idr_free', 0):,.0f} < Rp{modal_dibutuhkan:,.0f} (3 lapis)."
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

        kandidat = sorted(kandidat_raw, key=lambda x: x["skor_efektif"], reverse=True)
        if not kandidat:
            log_grid.append("⏸️ [GRID CASH IS KING] Belum ada koin memenuhi syarat (Sideways-Up/Uptrend di M15 & H1 + Volatilitas cukup).")
            return state, log_grid, log_tx, False

        pilih = kandidat[0]
        coin = pilih["coin"]
        p1 = bulatkan_harga_indodax(coin, pilih["harga_bid"])
        tp1 = bulatkan_harga_indodax(coin, p1 * (1.0 + GRID_STEP_PCT))
        p2 = bulatkan_harga_indodax(coin, p1 * (1.0 - GRID_STEP_PCT))
        p3 = bulatkan_harga_indodax(coin, p1 * (1.0 - (GRID_STEP_PCT * 2.0)))

        qty_b1 = hitung_kuantitas_koin(coin, GRID_CAPITAL_PER_LAYER_IDR, p1)
        res_b1 = eksekusi_order_indodax(coin, "BUY", p1, qty_koin=qty_b1, order_type="LIMIT", time_in_force=GRID_LIMIT_TIF)
        if apakah_order_sukses(res_b1):
            oid_b1 = str(res_b1.get("orderId"))
            state["grid_cycle"] = {
                "coin": coin,
                "created_ts": now_ts,
                "b3_ever_touched": False,
                "bounce_count": 0,
                "realized_grid_profit_idr": 0.0,
                "layers": {
                    "b1": {"buy_price": p1, "tp_price": tp1, "status": "WAIT_BUY", "buy_oid": oid_b1, "sell_oid": None, "qty": qty_b1, "capital_idr": round(qty_b1 * p1, 0)},
                    "b2": {"buy_price": p2, "tp_price": p1,  "status": "ARMED",    "buy_oid": None,   "sell_oid": None, "qty": 0.0,    "capital_idr": GRID_CAPITAL_PER_LAYER_IDR},
                    "b3": {"buy_price": p3, "tp_price": p2,  "status": "ARMED",    "buy_oid": None,   "sell_oid": None, "qty": 0.0,    "capital_idr": GRID_CAPITAL_PER_LAYER_IDR},
                }
            }
            ada_aksi = True
            pesan = (
                f"🕸️ [BUKA SIKLUS GRID 3-LAPIS] {coin} (Skor:{pilih['skor_efektif']} [{pilih['catatan_memori_grid']}] | {pilih['tren_detail']}) | "
                f"b1:Rp{p1:,.0f}->TP:Rp{tp1:,.0f} | b2:Rp{p2:,.0f} | b3:Rp{p3:,.0f} (Order b1:#{oid_b1})"
            )
            log_grid.append(pesan)
            log_tx.append(pesan)
        return state, log_grid, log_tx, ada_aksi

    # ==========================================================================
    # TAHAP B: KAWAL SIKLUS GRID AKTIF (VERIFIKASI ORDER LANGSUNG KE INDODAX)
    # ==========================================================================
    coin = cycle["coin"]
    info = peta_analisa.get(coin, {})
    harga_skrg = info.get("harga_idr", cycle["layers"]["b1"]["buy_price"])
    harga_bid = info.get("harga_bid", harga_skrg)
    layers = cycle["layers"]

    # 1. Cek jika b1 masih WAIT_BUY (belum terjemput)
    if layers["b1"]["status"] == "WAIT_BUY":
        st_b1, _ = cek_status_order_indodax(coin, layers["b1"]["buy_oid"])
        terisi_sim = (not LIVE_TRADING_ENABLED) and (harga_skrg <= layers["b1"]["buy_price"])
        if st_b1 == "FILLED" or terisi_sim:
            dompet_baru = ambil_saldo_lengkap_indodax()
            qty_b1_aktual = format_qty_koin(
                coin,
                min(layers["b1"]["qty"], dompet_baru["coins_free"].get(coin, layers["b1"]["qty"]))
                if LIVE_TRADING_ENABLED else layers["b1"]["qty"]
            )
            layers["b1"]["qty"] = qty_b1_aktual
            layers["b1"]["status"] = "HOLDING"

            # Pasang Limit Sell TP untuk b1
            res_tp1 = eksekusi_order_indodax(coin, "SELL", layers["b1"]["tp_price"], qty_koin=qty_b1_aktual, order_type="LIMIT", time_in_force=GRID_LIMIT_TIF)
            if apakah_order_sukses(res_tp1):
                layers["b1"]["sell_oid"] = str(res_tp1.get("orderId"))

            # Langsung pasang jaring Limit Buy b2 & b3 di order book Indodax (100% Maker)
            for nama_lapis in ("b2", "b3"):
                lp = layers[nama_lapis]
                q_lp = hitung_kuantitas_koin(coin, lp["capital_idr"], lp["buy_price"])
                res_lp = eksekusi_order_indodax(coin, "BUY", lp["buy_price"], qty_koin=q_lp, order_type="LIMIT", time_in_force=GRID_LIMIT_TIF)
                if apakah_order_sukses(res_lp):
                    lp["status"] = "WAIT_BUY"
                    lp["buy_oid"] = str(res_lp.get("orderId"))
                    lp["qty"] = q_lp
                    lp["capital_idr"] = round(q_lp * lp["buy_price"], 0)

            ada_aksi = True
            pesan = f"✅ [GRID b1 TERBELI] {coin} aktif! TP b1 @ Rp{layers['b1']['tp_price']:,.0f}, jaring Limit Buy b2 & b3 terpasang."
            log_grid.append(pesan)
            log_tx.append(pesan)
            return state, log_grid, log_tx, ada_aksi

        # Jika b1 belum terjemput terlalu lama atau tren sudah rusak -> batal bersih
        umur_m = (now_ts - float(cycle.get("created_ts", now_ts))) / 60.0
        if umur_m >= GRID_WAIT_B1_TIMEOUT_MIN or not info.get("layak_grid", False):
            batalkan_order_indodax(coin, layers["b1"]["buy_oid"])
            state["grid_cycle"] = None
            ada_aksi = True
            pesan = f"🔄 [BATAL ANTREAN b1] {coin} belum terjemput ({umur_m:.0f}m) / rezim berubah. Reset ke Rupiah."
            log_grid.append(pesan)
            log_tx.append(pesan)
            return state, log_grid, log_tx, ada_aksi

        log_grid.append(f"⏳ [GRID ANTRE b1 {umur_m:.0f}m] {coin} @ Rp{layers['b1']['buy_price']:,.0f} (Skrg: Rp{harga_skrg:,.0f})")
        return state, log_grid, log_tx, False

    # 2. Cek status terbeli (WAIT_BUY -> HOLDING) untuk b2 dan b3
    for nama_lapis in ("b2", "b3"):
        lp = layers[nama_lapis]
        if lp["status"] == "WAIT_BUY" and lp.get("buy_oid"):
            st_buy, _ = cek_status_order_indodax(coin, lp["buy_oid"])
            terisi_sim = (not LIVE_TRADING_ENABLED) and (harga_skrg <= lp["buy_price"])
            if st_buy == "FILLED" or terisi_sim:
                dompet_baru = ambil_saldo_lengkap_indodax()
                qty_aktual = format_qty_koin(
                    coin,
                    min(lp["qty"], dompet_baru["coins_free"].get(coin, lp["qty"]))
                    if LIVE_TRADING_ENABLED else lp["qty"]
                )
                lp["qty"] = qty_aktual
                lp["status"] = "HOLDING"
                lp["buy_oid"] = None
                if nama_lapis == "b3":
                    cycle["b3_ever_touched"] = True

                res_sell = eksekusi_order_indodax(coin, "SELL", lp["tp_price"], qty_koin=qty_aktual, order_type="LIMIT", time_in_force=GRID_LIMIT_TIF)
                if apakah_order_sukses(res_sell):
                    lp["sell_oid"] = str(res_sell.get("orderId"))
                ada_aksi = True
                pesan = f"🟢 [GRID {nama_lapis.upper()} TERBELI] {coin} @ Rp{lp['buy_price']:,.0f} -> Pasang TP @ Rp{lp['tp_price']:,.0f}."
                log_grid.append(pesan)
                log_tx.append(pesan)

    # 3. Cek status terjual profit (HOLDING -> TP FILLED) untuk b1, b2, b3
    for nama_lapis in ("b3", "b2", "b1"):
        lp = layers[nama_lapis]
        if lp["status"] == "HOLDING" and lp.get("sell_oid"):
            st_sell, _ = cek_status_order_indodax(coin, lp["sell_oid"])
            terjual_sim = (not LIVE_TRADING_ENABLED) and (harga_skrg >= lp["tp_price"])
            if st_sell == "FILLED" or terjual_sim:
                gross_pct = (lp["tp_price"] - lp["buy_price"]) / lp["buy_price"]
                net_pct = gross_pct - FEE_ROUNDTRIP_MAKER_PCT
                profit_idr = round(lp["capital_idr"] * net_pct, 0)

                cycle["bounce_count"] = int(cycle.get("bounce_count", 0)) + 1
                cycle["realized_grid_profit_idr"] = round(float(cycle.get("realized_grid_profit_idr", 0.0)) + profit_idr, 0)
                slot_mem = {"coin": coin, "style": f"GRID_{nama_lapis.upper()}", "capital_idr": lp["capital_idr"]}
                catat_hasil_transaksi_ke_recovery(state, profit_idr, coin, slot=slot_mem, pnl_exit_pct=net_pct)
                lp["sell_oid"] = None
                ada_aksi = True

                if nama_lapis == "b1":
                    lp["status"] = "DONE"
                    pesan = f"🎉 [GRID b1 TP PENUH!] {coin} laku @ Rp{lp['tp_price']:,.0f} (Net:+Rp{profit_idr:,.0f} | Total Pantul:{cycle['bounce_count']}x)."
                else:
                    # Pasang ulang jaring Limit Buy untuk b2/b3 agar siap tangkap pantulan berikutnya
                    q_ulang = hitung_kuantitas_koin(coin, GRID_CAPITAL_PER_LAYER_IDR, lp["buy_price"])
                    res_re = eksekusi_order_indodax(coin, "BUY", lp["buy_price"], qty_koin=q_ulang, order_type="LIMIT", time_in_force=GRID_LIMIT_TIF)
                    lp["status"] = "WAIT_BUY" if apakah_order_sukses(res_re) else "ARMED"
                    lp["buy_oid"] = str(res_re.get("orderId")) if apakah_order_sukses(res_re) else None
                    lp["qty"] = q_ulang
                    pesan = f"💰 [PANEN GRID {nama_lapis.upper()}!] {coin} laku @ Rp{lp['tp_price']:,.0f} (+Rp{profit_idr:,.0f} | Pantul #{cycle['bounce_count']}). Jaring dipasang ulang."
                log_grid.append(pesan)
                log_tx.append(pesan)

    # 4. Jika b1 sudah TP dan b2/b3 tidak ada yang nyangkut -> TUTUP & RESET SIKLUS BERSIH
    if layers["b1"]["status"] == "DONE" and layers["b2"]["status"] != "HOLDING" and layers["b3"]["status"] != "HOLDING":
        for nama_lapis in ("b2", "b3"):
            if layers[nama_lapis].get("buy_oid"):
                batalkan_order_indodax(coin, layers[nama_lapis]["buy_oid"])
        pesan = f"🏁 [SIKLUS GRID SELESAI!] {coin} total profit terealisasi: +Rp{cycle['realized_grid_profit_idr']:,.0f} ({cycle['bounce_count']}x panen). Reset ke siklus baru."
        log_grid.append(pesan)
        log_tx.append(pesan)
        rekam_memori_siklus_grid(state, cycle, "TP_PENUH", cycle["realized_grid_profit_idr"])
        state["grid_cycle"] = None
        return state, log_grid, log_tx, True

    # 5. ATURAN RESET AMAN: Jika b3 pernah tersentuh & sudah >= 3x panen, lalu harga balik ke >= b2 dengan Net Siklus UNTUNG
    if cycle.get("b3_ever_touched") and cycle.get("bounce_count", 0) >= GRID_RESET_BOUNCE_COUNT and harga_bid >= layers["b2"]["buy_price"]:
        floating_idr = 0.0
        total_qty_tahan = 0.0
        for lp in layers.values():
            if lp["status"] == "HOLDING":
                floating_idr += (harga_bid - lp["buy_price"]) * lp["qty"]
                total_qty_tahan += lp["qty"]
        est_fee_jual = (total_qty_tahan * harga_bid) * (FEE_ROUNDTRIP_MAKER_PCT * 0.6)
        net_siklus_idr = cycle["realized_grid_profit_idr"] + floating_idr - est_fee_jual

        if net_siklus_idr > 0 and total_qty_tahan > 0:
            for lp in layers.values():
                if lp.get("buy_oid"):
                    batalkan_order_indodax(coin, lp["buy_oid"])
                if lp.get("sell_oid"):
                    batalkan_order_indodax(coin, lp["sell_oid"])
            time.sleep(1.0)
            dompet_cek = ambil_saldo_lengkap_indodax()
            qty_jual_semua = format_qty_koin(coin, dompet_cek["coins_free"].get(coin, total_qty_tahan) if LIVE_TRADING_ENABLED else total_qty_tahan)
            sukses_exit, harga_exit, _ = eksekusi_jual_terverifikasi(coin, bulatkan_harga_indodax(coin, harga_bid), qty_jual_semua)
            if sukses_exit:
                pnl_sisa_idr = round(floating_idr - est_fee_jual, 0)
                modal_sisa = sum(lp["capital_idr"] for lp in layers.values() if lp["status"] == "HOLDING") or GRID_CAPITAL_PER_LAYER_IDR
                slot_reset = {"coin": coin, "style": "GRID_RESET", "capital_idr": modal_sisa}
                catat_hasil_transaksi_ke_recovery(state, pnl_sisa_idr, coin, slot=slot_reset, pnl_exit_pct=(pnl_sisa_idr / modal_sisa))
                rekam_memori_siklus_grid(state, cycle, "AUTO_RESET_B3", net_siklus_idr)
                pesan = (
                    f"🏆 [AUTO-RESET SIKLUS UNTUNG] {coin} sudah {cycle['bounce_count']}x panen & pernah sentuh b3. "
                    f"Semua sisa koin ditutup @ Rp{harga_exit:,.0f} (Total Net Siklus: +Rp{net_siklus_idr:,.0f}). Reset!"
                )
                log_grid.append(pesan)
                log_tx.append(pesan)
                state["grid_cycle"] = None
                return state, log_grid, log_tx, True

    # 6. ATURAN SWING HOLD DI BAWAH b3 (TIDAK CUT LOSS PAKSA SAAT MASIH ADA PELUANG REBOUND)
    harga_b3 = layers["b3"]["buy_price"]
    if harga_skrg < harga_b3:
        jarak_bawah_b3_pct = ((harga_skrg - harga_b3) / harga_b3) * 100.0
        peluang_naik = info.get("peluang_rebound_b3", True)
        status_rebound = "ADA PELUANG REBOUND KE b2/b1" if peluang_naik else "TEKANAN JUAL MASIH KUAT (TETAP SWING HOLD)"
        log_grid.append(
            f"💎 [SWING HOLD BAWAH b3] {coin} di Rp{harga_skrg:,.0f} ({jarak_bawah_b3_pct:+.2f}% dari b3) | "
            f"RSI 15M:{info.get('rsi_15m', '-')} / 1H:{info.get('rsi_1h', '-')} | {status_rebound}. "
            f"Antrean TP b3@Rp{layers['b3']['tp_price']:,.0f} & b2@Rp{layers['b2']['tp_price']:,.0f} tetap aktif menunggu swing."
        )
    else:
        ringkas = " | ".join([f"{k}:{v['status']}" for k, v in layers.items()])
        log_grid.append(
            f"🕸️ [KAWAL GRID {coin}] Skrg:Rp{harga_skrg:,.0f} | {ringkas} | "
            f"Panen:{cycle['bounce_count']}x (+Rp{cycle['realized_grid_profit_idr']:,.0f})"
        )

    return state, log_grid, log_tx, ada_aksi

# ==============================================================================
# BAGIAN 10: PROGRAM UTAMA (HANYA KIRIM SHEETS JIKA ADA ENTRY / TP / SL)
# ==============================================================================
def jalankan_satu_siklus_penuh(state, paksa_kirim_sheets=False):
    dompet = ambil_saldo_lengkap_indodax()
    if LIVE_TRADING_ENABLED and not dompet.get("terhubung"):
        print("⚠️ Gagal terhubung ke API Indodax. Siklus dilewati agar state tidak rusak.")
        return state, False, [], False, {}

    harga_live_map = ambil_harga_idr_semua_koin()

    # Langkah 1: Pulihkan otomatis koin di dompet yang belum masuk daftar aktif (hanya untuk mode scalping lama)
    log_recovery = []
    if not GRID_MODE_ENABLED:
        state, log_recovery = sinkronkan_koin_dompet_indodax(state, dompet, harga_live_map)
        if log_recovery:
            dompet = ambil_saldo_lengkap_indodax()

    # Langkah 2: Analisa Native Indodax (5M + 15M + 1H)
    peta_analisa_pasar = analisa_teknikal_lengkap_pasar(harga_live_map)

    if GRID_MODE_ENABLED:
        state, log_grid, log_tx_grid, ada_aksi_grid = kelola_siklus_grid_3_lapis(
            state, peta_analisa_pasar, dompet
        )
        simpan_state_bot(state)
        for baris in log_grid:
            print("  ", baris)
        if ada_aksi_grid or paksa_kirim_sheets:
            lapor_ke_google_sheets(state, log_tx_grid or log_grid, dompet, harga_live_map)
        else:
            print("ℹ️ [GRID TENANG] Belum ada eksekusi grid baru, Google Sheets tidak ditambah.")
        # Saat mode Grid aktif, tidak perlu loop pengawasan intensif 1 menitan karena semua order sudah terpasang GTC di Indodax
        return state, False, [], ada_aksi_grid, peta_analisa_pasar
    state, log_kawal, log_tx_kawal, ada_aksi_kawal, antrean_exit, antrean_sl = evaluasi_dan_kawal_posisi_dinamis(
        state, peta_analisa_pasar, dompet
    )
    pending_slots = [x["slot"] for x in antrean_exit + antrean_sl]
    state, log_alokasi, log_tx_beli, ada_aksi_beli, antrean_entry = kelola_anggaran_kosong_dengan_analisa(
        state, peta_analisa_pasar, dompet, pending_slots=pending_slots
    )
    state, log_batch, log_tx_batch, ada_aksi_batch = eksekusi_hasil_batch_terpadu(
        state, peta_analisa_pasar, dompet, antrean_exit, antrean_sl, antrean_entry
    )
    simpan_state_bot(state)

    butuh_siaga, alasan_siaga = cek_apakah_butuh_pengawasan_intensif(state, peta_analisa_pasar)
    semua_log_konsol = log_recovery + log_kawal + log_alokasi + log_batch
    for baris in semua_log_konsol:
        print("  ", baris)

    log_khusus_transaksi = log_recovery + log_tx_kawal + log_tx_beli + log_tx_batch
    ada_transaksi_nyata = bool(log_khusus_transaksi) or ada_aksi_kawal or ada_aksi_beli or ada_aksi_batch

    if ada_transaksi_nyata or paksa_kirim_sheets:
        lapor_ke_google_sheets(state, log_khusus_transaksi or semua_log_konsol, dompet, harga_live_map)
    else:
        print("ℹ️ [TIDAK ADA TRANSAKSI BARU] Sesi patroli tenang, Google Sheets tidak ditambah baris baru agar jurnal tetap bersih.")

    return state, butuh_siaga, alasan_siaga, ada_transaksi_nyata, peta_analisa_pasar

def cek_status_koneksi_gemini_awal():
    """Memverifikasi API Key & kesiapan model utama tanpa membuang kuota generateContent harian."""
    global _MODEL_GEMINI_AKTIF
    daftar_kunci = ambil_daftar_kunci_api_gemini()
    if not daftar_kunci:
        print("⚠️ [STATUS GEMINI AI]: BELUM TERHUBUNG (GEMINI_API_KEY kosong / belum terbaca dari Secrets)")
        return
    daftar_model = dapatkan_daftar_model_gemini()
    if daftar_model:
        model_utama = daftar_model[0]
        model_cadangan = daftar_model[1] if len(daftar_model) > 1 else "-"
        _MODEL_GEMINI_AKTIF = model_utama
        print(
            f"✅ [STATUS GEMINI AI SIAP | Model Utama: {model_utama} | Cadangan: {model_cadangan} | "
            f"Penalaran: {_LEVEL_PENALARAN_AKTIF} | Jumlah API Key: {len(daftar_kunci)}] "
            f"(100% kuota dihemat khusus untuk 1x Batch Entry, Exit & SL)"
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
