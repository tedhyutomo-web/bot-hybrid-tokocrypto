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
MAX_SINGLE_COIN_CAP_PCT = 0.45         # Maksimal porsi modal pada 1 koin (mode scalping cadangan)
FEE_ROUNDTRIP_MAKER_PCT = 0.0055       # Estimasi total biaya beli+jual+PPN+CFX Indodax ~0.55%

MIN_CONVICTION_SCORE = 64.0            # Skor kelayakan minimal normal (0 - 100)
RECOVERY_SCORE_BOOST = 3.5             # Tambahan syarat skor minimal (+3.5) saat mode balik modal aktif
MAX_CONCURRENT_COINS = 3               # Maksimal 3 koin bersamaan (mode scalping cadangan)
MAX_SPREAD_INDODAX_PCT = 0.0035        # Maksimal toleransi Bid-Ask Spread Indodax (0.35%)
DAILY_LOSS_LIMIT_PCT = -0.025          # Batas rugi harian (-2.5% modal) untuk Circuit Breaker
SL_COOLDOWN_MINUTES = 45               # Masa tenang 45 menit untuk koin yang baru terkena SL

# ==============================================================================
# KONFIGURASI METODE GRID 3-LAPIS (SELESAI PER LAPIS DI TP b1 MASING-MASING)
# ==============================================================================
GRID_MODE_ENABLED = True               # True = aktifkan Grid 3-Lapis; False = mode scalping cadangan
GRID_CAPITAL_PER_LAYER_IDR = float(os.getenv("GRID_CAPITAL_PER_LAYER_IDR", "33000"))
GRID_STEP_PCT = 0.0150                 # Default / Lampu Hijau: jarak antar grid 1.50% (b3 di -3.00%)
GRID_STEP_GREEN_PCT = 0.0150           # Jarak grid saat 4H Lampu Hijau (1.50%)
GRID_STEP_YELLOW_PCT = 0.0200          # Jarak grid diperlebar saat 4H Lampu Kuning (2.00%, b3 di -4.00%)
GRID_MAX_TIERS = 3                     # Maksimal 3 lapis aktif bersamaan (tiap lapis selesai di TP b1-nya)
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
GRID_ALLOWED_COINS = {"BTC", "ETH", "XRP"}
GRID_LIMIT_TIF = "MOC"                 # Prioritas Maker-Only Cancel dengan fallback aman ke GTC bila ditolak

# Validasi Gemini AI & Proteksi Invalidation Grid
GRID_USE_GEMINI_VALIDATION = os.getenv("GRID_USE_GEMINI_VALIDATION", "true").lower() == "true"
GRID_GEMINI_FALLBACK_ALLOW = os.getenv("GRID_GEMINI_FALLBACK_ALLOW", "false").lower() == "true"
GRID_INVALIDATION_ENABLED = True       # Aktifkan penjaga drawdown ekstrem agar modal tidak terkunci selamanya
GRID_INVALIDATION_DD_PCT = -0.12       # Batas floating drawdown ekstrem (-12%) saat semua lapis penuh & 4H MERAH
GRID_INVALIDATION_AUTO_CUT = os.getenv("GRID_INVALIDATION_AUTO_CUT", "true").lower() == "true"

# Parameter Target TP & SL Dinamis (Mode Scalping Cadangan)
TP_GRID_MIN_PCT = 0.0135
TP_GRID_MAX_PCT = 0.0220
SL_GRID_BASE_PCT = 0.0105

TP_SNIPER_MIN_PCT = 0.0180
TP_SNIPER_MAX_PCT = 0.0340
SL_SNIPER_BASE_PCT = 0.0105
SMART_SL_TRIGGER_PCT = -0.0070
SL_WATCH_MIN_PCT = -0.0040
SL_WATCH_MAX_PCT = -0.0045
EMERGENCY_SL_PCT = -0.0145
SL_THROTTLE_SECONDS = 300.0
SL_MEMORY_RETENTION_HOURS = 168.0
MAX_SL_MEMORY_ITEMS = 40

SCRATCH_PROFIT_BID_PCT = 0.0060
TP_RANGE_MIN_PROFIT_PCT = 0.0095
TIME_STOP_HOURS = 2.5
TIME_STOP_MIN_PROFIT_PCT = 0.0100
DYNAMIC_ENTRY_SHIFT_PCT = 0.0035
REVIEW_ENTRY_HOURS = 1.5

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
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            if state.get("last_reset_date") != tgl_skrg:
                state["realized_profit_today_idr"] = 0.0
                state["completed_trades_today"] = 0
                state["last_reset_date"] = tgl_skrg
            state.setdefault("active_slots", [])
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
    now_ts = time.time()
    batas_kadaluarsa = now_ts - (SL_MEMORY_RETENTION_HOURS * 3600.0)
    teks_konteks = ""

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
                f" | ⚠️ MEMORI TAHAN SL (7H: {jml_bangkit}x Bangkit vs {jml_gagal}x Gagal [{wr_bangkit:.0f}%]; "
                f"terakhir {gagal_terbaru['coin']} ditahan di {gagal_terbaru['minus_awal_pct']}% jatuh ke {gagal_terbaru['pnl_akhir_pct']}%): "
                f"Jangan paksakan TAHAN jika tren 5M/15M patah!"
            )
        elif jml_bangkit > jml_gagal and bangkit_terbaru:
            teks_konteks += (
                f" | ✅ MEMORI TAHAN SL (7H: {jml_bangkit}x Bangkit vs {jml_gagal}x Gagal [{wr_bangkit:.0f}%]; "
                f"terakhir {bangkit_terbaru['coin']} dari {bangkit_terbaru['minus_awal_pct']}% berbalik +{bangkit_terbaru['pnl_akhir_pct']}%): "
                f"Pola historis cenderung memantul, layak TAHAN jika oversold & jual mereda."
            )
        elif total_pola > 0:
            info_b = f"{bangkit_terbaru['coin']} {bangkit_terbaru['minus_awal_pct']}%->{bangkit_terbaru['pnl_akhir_pct']:+}%" if bangkit_terbaru else "-"
            info_g = f"{gagal_terbaru['coin']} {gagal_terbaru['minus_awal_pct']}%->{gagal_terbaru['pnl_akhir_pct']}%" if gagal_terbaru else "-"
            teks_konteks += (
                f" | ⚖️ MEMORI TAHAN SL SEIMBANG (7H: {jml_bangkit}x Bangkit vs {jml_gagal}x Gagal [50%]; "
                f"Bangkit:{info_b}, Gagal:{info_g}): Putuskan objektif berdasarkan tren & volume saat ini."
            )

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
                f" | 📊 REKOR 7H {coin}: {len(k_w)}x Menang (avg +{avg_w:.2f}%) vs {len(k_l)}x Kalah (avg {avg_l:.2f}%) "
                f"[WR {wr_k:.0f}%] | Total Bot 7H: {total_w}W (avg +{avg_all_w:.2f}%) vs {total_l}L (avg {avg_all_l:.2f}%) [WR {wr_all:.0f}%]"
            )
        else:
            teks_konteks += (
                f" | 📊 REKOR BOT 7H: {total_w}x Menang (avg +{avg_all_w:.2f}%) vs {total_l}x Kalah (avg {avg_all_l:.2f}%) [WR {wr_all:.0f}%]"
            )

    return teks_konteks

def catat_hasil_transaksi_ke_recovery(state, pnl_bersih_idr, coin=None, slot=None, pnl_exit_pct=None):
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

def sinkronkan_koin_dompet_indodax(state, dompet, harga_idr_map):
    log_sync = []
    if not dompet.get("terhubung"):
        return state, log_sync

    now_ts = time.time()
    slot_valid = []

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

        if status_slot == "WAITING_BUY":
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

        if status_slot == "HOLDING_FOR_TP":
            if nilai_koin_asli < 5000.0:
                tp_oid = slot.get("tp_order_id")
                status_tp, detail_tp = cek_status_order_indodax(coin, tp_oid) if tp_oid else ("NOT_FOUND", {})

                if status_tp == "FILLED":
                    _, harga_laku = ekstrak_eksekusi_order(detail_tp, fallback_price=tp_idr)
                    pnl_pct = ((harga_laku - entry_idr) / entry_idr) - FEE_ROUNDTRIP_MAKER_PCT
                    profit_bersih = round(float(slot.get("capital_idr", 0)) * pnl_pct, 0)
                    catat_hasil_transaksi_ke_recovery(state, profit_bersih, coin, slot=slot, pnl_exit_pct=pnl_pct)
                    log_sync.append(
                        f"🎉 [TP TERVERIFIKASI INDODAX] {coin} laku di Rp{harga_laku:,.0f} "
                        f"(PnL Bersih: Rp{profit_bersih:,.0f} | OrderTP:#{tp_oid})."
                    )
                    continue

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
                    log_sync.append(
                        f"🧹 [SYNC HAPUS SLOT HANTU] {coin} tidak ditemukan di dompet Indodax (Saldo: 0). "
                        f"Slot hantu dihapus tanpa merusak statistik Win Rate/Recovery."
                    )
                continue

            if total_qty_asli > 0:
                slot["qty"] = total_qty_asli

            if slot.get("tp_order_id") and k_locked <= 0:
                status_tp, _ = cek_status_order_indodax(coin, slot["tp_order_id"])
                if status_tp in ("CANCELED", "EXPIRED", "NOT_FOUND"):
                    log_sync.append(
                        f"🔄 [SYNC TP DIBATALKAN MANUAL] OrderTP #{slot['tp_order_id']} {coin} sudah tidak aktif di Indodax. "
                        f"Reset tp_order_id agar bot pasang ulang otomatis."
                    )
                    slot["tp_order_id"] = None

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

        ohlc_5m = ambil_data_ohlc_indodax(coin, info, tf="5", jumlah_candle=100)
        ohlc_15m = ambil_data_ohlc_indodax(coin, info, tf="15", jumlah_candle=100)
        ohlc_1h = ambil_data_ohlc_indodax(coin, info, tf="60", jumlah_candle=100)
        ohlc_4h = ambil_data_ohlc_indodax(coin, info, tf="240", jumlah_candle=100)
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

        if lampu_4h == "HIJAU":
            grid_step_aktif = GRID_STEP_GREEN_PCT
            trigger_5m_ok = (
                m5["rsi"] <= GRID_MAX_RSI_M5_ENTRY
                and m15["rsi"] <= 64.0
                and tidak_pucuk
                and (not candle_jatuh_beruntun)
            )
            struktur_ok = m15_aman and h1_aman
        elif lampu_4h == "KUNING":
            grid_step_aktif = GRID_STEP_YELLOW_PCT
            trigger_5m_ok = (
                candle_5m_hijau
                and m5["rsi"] <= GRID_MAX_RSI_M5_YELLOW
                and tidak_pucuk
                and (not candle_jatuh_beruntun)
            )
            struktur_ok = m15_aman and (h1_aman or m15["rezim"] == "UPTREND")
        else:
            grid_step_aktif = GRID_STEP_YELLOW_PCT
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

_MODEL_GEMINI_HABIS_KUOTA = set()
_MODEL_GEMINI_AKTIF = None
_LEVEL_PENALARAN_AKTIF = "MENENGAH (1024 Token Penalaran)"

def ambil_daftar_kunci_api_gemini():
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
    semua_model = [
        "gemini-3-flash-preview",
        "gemini-2.5-flash"
    ]
    model_tersedia = [m for m in semua_model if m not in _MODEL_GEMINI_HABIS_KUOTA]
    return model_tersedia if model_tersedia else semua_model

def panggil_teks_gemini_ai(prompt, timeout_detik=20, mode_penalaran="MENENGAH"):
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
    peran_ai = (
        "Chief Quant Grid & Risk Manager Indodax (Strategi Grid 3-Lapis Per-Tier, selesai di TP b1 tiap lapis)"
        if GRID_MODE_ENABLED else
        "Chief Quant Scalper & Risk Manager 5M Indodax"
    )
    baris_tugas = [f"[{t['id']}] {t['deskripsi']}" for t in daftar_tugas_ai]
    prompt_batch = (
        f"Anda adalah {peran_ai} ({konteks_mode}). Evaluasi seluruh paket data berikut sekaligus.\n"
        f"Konteks Pasar: Kompas BTCIDR={status_kompas_btc}.\n"
        f"Aturan Keputusan:\n"
        f"- TIPE BELI_BARU / GRID_ENTRY: Jawab YA (layak buka lapis/beli) atau TUNDA (jangan masuk dulu, hindari beli pucuk/freefall).\n"
        f"- TIPE EXIT_PROFIT: Jawab YA (jual sekarang amankan profit) atau TAHAN (kawal ke TP penuh).\n"
        f"- TIPE EVALUASI_SL: Jawab YA (cut loss sekarang) atau TAHAN (tunggu pantulan).\n"
        f"Daftar Tugas ({len(daftar_tugas_ai)} item):\n"
        + "\n".join(baris_tugas) + "\n\n"
        f"INSTRUKSI JAWABAN:\n"
        f"Jawab WAJIB 1 baris per ID dengan format persis:\n"
        f"[ID]: KEPUTUSAN - alasan singkat maksimal 12 kata"
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
            if jenis in ("BELI_BARU", "GRID_ENTRY"):
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
# BAGIAN 6 & 7: MODE SCALPING CADANGAN (TIDAK BERJALAN SAAT GRID_MODE_ENABLED=True)
# ==============================================================================
def evaluasi_dan_kawal_posisi_dinamis(state, peta_analisa, dompet):
    slot_tetap_aktif = []
    log_aksi = []
    log_transaksi = []
    ada_eksekusi_penting = False
    now_ts = time.time()
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

        if slot["status"] == "WAITING_BUY":
            if (dompet["terhubung"] and nilai_koin_idr >= 5000) or (not dompet["terhubung"] and harga_sekarang <= entry_idr):
                slot["status"] = "HOLDING_FOR_TP"
                slot["filled_timestamp"] = now_ts
                slot["highest_price_idr"] = max(harga_sekarang, high_2jam_idr)
                pasang_antrean_tp_di_indodax(slot, koin_free)
                ada_eksekusi_penting = True
                pesan = f"✅ [TERBELI & PASANG TP] {coin} ({mode_slot}) aktif di Rp{entry_idr:,.0f}! Antrean Jual TP di Rp{slot['tp_price_idr']:,.0f}."
                log_aksi.append(pesan)
                log_transaksi.append(pesan)
                slot_tetap_aktif.append(slot)
                continue

            umur_antre_menit = (now_ts - float(slot.get("timestamp", now_ts))) / 60.0
            umur_antre_jam = umur_antre_menit / 60.0

            masih_layak_entry = bool(info_pasar and info_pasar.get("siap_entry") is True and info_pasar.get("skor", 0) >= MIN_CONVICTION_SCORE)
            if not masih_layak_entry or umur_antre_jam >= REVIEW_ENTRY_HOURS:
                sukses_batal, _ = batalkan_order_indodax(coin, slot.get("buy_order_id"))
                if dompet["terhubung"] and not sukses_batal:
                    st_cek, _ = cek_status_order_indodax(coin, slot.get("buy_order_id"))
                    if st_cek == "FILLED":
                        slot_tetap_aktif.append(slot)
                        continue
                dompet["idr_free"] = float(dompet.get("idr_free", 0.0)) + float(slot.get("capital_idr", 0.0))
                ada_eksekusi_penting = True
                pesan = f"🔄 [BATAL ANTREAN] Order beli {coin} dibatalkan ({prediksi_koin})."
                log_aksi.append(pesan)
                log_transaksi.append(pesan)
                continue

            slot_tetap_aktif.append(slot)
            continue

        if slot["status"] == "HOLDING_FOR_TP":
            if dompet["terhubung"] and nilai_koin_idr < 5000 and slot.get("tp_order_id"):
                kenaikan_tp_pct = (tp_idr - entry_idr) / entry_idr
                profit_bersih = round(slot["capital_idr"] * (kenaikan_tp_pct - FEE_ROUNDTRIP_MAKER_PCT), 0)
                catat_hasil_transaksi_ke_recovery(state, profit_bersih, coin, slot=slot, pnl_exit_pct=(kenaikan_tp_pct - FEE_ROUNDTRIP_MAKER_PCT))
                ada_eksekusi_penting = True
                pesan = f"🎉 [TP TERJUAL OTOMATIS!] {coin} laku di Rp{tp_idr:,.0f}. Profit Bersih: Rp{profit_bersih:,.0f}."
                log_aksi.append(pesan)
                log_transaksi.append(pesan)
                continue

            if dompet["terhubung"] and nilai_koin_idr < 5000:
                continue

            puncak_tercatat = max(float(slot.get("highest_price_idr", harga_sekarang)), harga_sekarang)
            slot["highest_price_idr"] = puncak_tercatat
            harga_eksekusi_jual = bulatkan_harga_indodax(coin, harga_bid_asli)
            kenaikan_skrg_pct = (harga_sekarang - entry_idr) / entry_idr
            kenaikan_bid_pct = (harga_eksekusi_jual - entry_idr) / entry_idr
            qty_dimiliki = format_qty_koin(coin, total_koin_dimiliki if dompet["terhubung"] else slot.get("qty", 0))
            estimasi_nilai_jual_skrg = qty_dimiliki * harga_eksekusi_jual

            if min(kenaikan_skrg_pct, kenaikan_bid_pct) <= EMERGENCY_SL_PCT and qty_dimiliki > 0 and estimasi_nilai_jual_skrg >= 10000.0:
                if slot.get("tp_order_id"):
                    batalkan_order_indodax(coin, slot["tp_order_id"])
                    slot["tp_order_id"] = None
                    time.sleep(1.0)
                res_emg = eksekusi_order_indodax(coin, "SELL", harga_eksekusi_jual, qty_koin=qty_dimiliki, order_type="MARKET")
                if apakah_order_sukses(res_emg):
                    pnl_exit_pct = kenaikan_bid_pct - FEE_ROUNDTRIP_MAKER_PCT
                    pnl_bersih = round(slot["capital_idr"] * pnl_exit_pct, 0)
                    catat_hasil_transaksi_ke_recovery(state, pnl_bersih, coin, slot=slot, pnl_exit_pct=pnl_exit_pct)
                    ada_eksekusi_penting = True
                    pesan = f"🚨 [EMERGENCY SL MARKET] {coin} dipotong @ Rp{harga_eksekusi_jual:,.0f} (PnL: Rp{pnl_bersih:,.0f})."
                    log_aksi.append(pesan)
                    log_transaksi.append(pesan)
                    continue

            if not slot.get("tp_order_id") and (not dompet["terhubung"] or koin_free > 0):
                pasang_antrean_tp_di_indodax(slot, koin_free)
                ada_eksekusi_penting = True

            slot_tetap_aktif.append(slot)

    state["active_slots"] = slot_tetap_aktif
    return state, log_aksi, log_transaksi, ada_eksekusi_penting, antrean_batch_exit, antrean_batch_sl

def kelola_anggaran_kosong_dengan_analisa(state, peta_analisa, dompet, pending_slots=None):
    return state, ["[MODE SCALPING CADANGAN] Gunakan GRID_MODE_ENABLED=True untuk mesin Grid 3-Lapis."], [], False, []

def eksekusi_hasil_batch_terpadu(state, peta_analisa, dompet, antrean_batch_exit, antrean_batch_sl, antrean_batch_entry):
    return state, [], [], False

def cek_apakah_butuh_pengawasan_intensif(state, peta_analisa):
    return FORCE_CONTINUOUS_WATCH, (["FORCE_CONTINUOUS_WATCH aktif"] if FORCE_CONTINUOUS_WATCH else [])

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

def buat_kesimpulan_patroli_dinamis(state, peta_analisa, harga_idr_map=None):
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
                "   * Belum ada siklus Grid aktif (100% Cash is King - Menunggu syarat 4H != MERAH, M15/H1/5M valid & persetujuan Gemini AI)."
            )
    else:
        for slot in state.get("active_slots", []):
            coin = slot["coin"]
            info = peta_analisa.get(coin, {})
            skrg = info.get("harga_idr", float(slot["entry_price_idr"]))
            detail_diagnosa_koin.append(
                f"   * {coin} [{slot.get('status')}] @ Rp{slot['entry_price_idr']:,.0f} (Skrg: Rp{skrg:,.0f})"
            )

    teks_diagnosa = "\n".join(detail_diagnosa_koin) if detail_diagnosa_koin else "   * Belum ada posisi aktif (100% Cash is King)."
    judul_mode = "PATROLI GRID 3-LAPIS (PER-LAPIS) SELESAI" if GRID_MODE_ENABLED else "PATROLI PRO SCALPER 5M SELESAI"

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
            modal_aktif = 0.0
            floating_pnl = 0.0
            ringkasan_lapis = "Siklus selesai / Cash is King"
            pasangan_str = "INDODAX GRID (Cash is King)"
            info_rsi_str = f"Rec:Rp{state.get('loss_to_recover_idr', 0):,.0f}"

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
    else:
        floating_pnl = 0.0
        if harga_live_map:
            for s in state["active_slots"]:
                if s.get("status") == "HOLDING_FOR_TP":
                    harga_skrg = harga_live_map.get(s["coin"], {}).get("buy", harga_live_map.get(s["coin"], {}).get("last", s["entry_price_idr"]))
                    floating_pnl += (harga_skrg - float(s["entry_price_idr"])) * float(s.get("qty", 0.0))

        ringkasan_slot = ", ".join(
            [f"{s['coin']}[{s['style']}:{s['status']}:Rp{s['capital_idr']:,.0f}@Rp{s['entry_price_idr']:,.0f}->TP:Rp{s['tp_price_idr']:,.0f}]" for s in state["active_slots"]]
        ) or "Semua slot kosong"

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
# MESIN GRID 3-LAPIS MANDIRI (TIAP LAPIS SELESAI DI TP b1 + SELF-HEALING + AI)
# ==============================================================================
def _buat_struktur_tier_baru(coin, tier_no, p1, step_pct, mode_4h, oid_b1, qty_b1, now_ts):
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
            "b1": {"buy_price": p1, "tp_price": tp1, "status": "WAIT_BUY", "buy_oid": oid_b1, "sell_oid": None, "qty": qty_b1, "capital_idr": round(qty_b1 * p1, 0)},
            "b2": {"buy_price": p2, "tp_price": p1,  "status": "ARMED",    "buy_oid": None,   "sell_oid": None, "qty": 0.0,    "capital_idr": GRID_CAPITAL_PER_LAYER_IDR},
            "b3": {"buy_price": p3, "tp_price": p2,  "status": "ARMED",    "buy_oid": None,   "sell_oid": None, "qty": 0.0,    "capital_idr": GRID_CAPITAL_PER_LAYER_IDR},
        }
    }

def _promosikan_b1_dan_pasang_jaring(coin, tier, qty_aktual, harga_eksekusi, info_pasar):
    """Mempromosikan b1 ke HOLDING, memasang TP b1 aman, serta memasang jaring b2 & b3."""
    layers = tier["layers"]
    step_pct = float(tier.get("step_pct", GRID_STEP_GREEN_PCT))

    if harga_eksekusi > 0:
        p1_aktual = bulatkan_harga_indodax(coin, harga_eksekusi)
        layers["b1"]["buy_price"] = p1_aktual
        layers["b1"]["tp_price"] = bulatkan_harga_indodax(coin, p1_aktual * (1.0 + step_pct))
        layers["b2"]["buy_price"] = bulatkan_harga_indodax(coin, p1_aktual * (1.0 - step_pct))
        layers["b2"]["tp_price"] = p1_aktual
        layers["b3"]["buy_price"] = bulatkan_harga_indodax(coin, p1_aktual * (1.0 - (step_pct * 2.0)))
        layers["b3"]["tp_price"] = layers["b2"]["buy_price"]

    layers["b1"]["qty"] = qty_aktual
    layers["b1"]["capital_idr"] = round(qty_aktual * float(layers["b1"]["buy_price"]), 0)
    layers["b1"]["status"] = "HOLDING"
    layers["b1"]["buy_oid"] = None

    # 1. Pasang TP b1 secara aman (MOC -> fallback GTC)
    ok_tp1, res_tp1, harga_tp1, _ = pasang_order_grid_aman(
        coin, "SELL", layers["b1"]["tp_price"], qty_aktual, info_pasar=info_pasar, paksa_gtc_fallback=True
    )
    if ok_tp1:
        layers["b1"]["sell_oid"] = str(res_tp1.get("orderId"))
        layers["b1"]["tp_price"] = harga_tp1

    # 2. Pasang jaring b2 dan b3 secara aman
    for nama_lp in ("b2", "b3"):
        lp = layers[nama_lp]
        q_lp = hitung_kuantitas_koin(coin, lp["capital_idr"], lp["buy_price"])
        ok_lp, res_lp, harga_lp, _ = pasang_order_grid_aman(
            coin, "BUY", lp["buy_price"], q_lp, info_pasar=info_pasar, paksa_gtc_fallback=True
        )
        if ok_lp:
            lp["status"] = "WAIT_BUY"
            lp["buy_oid"] = str(res_lp.get("orderId"))
            lp["buy_price"] = harga_lp
            lp["qty"] = q_lp
            lp["capital_idr"] = round(q_lp * harga_lp, 0)
        else:
            lp["status"] = "ARMED"
            lp["buy_oid"] = None

def _validasi_grid_dengan_gemini(peta_analisa, state, coin, tier_no, p1, step_pct, note_memori):
    """Validasi 1x panggilan Gemini AI sebelum membuka Lapis Grid baru (L1, L2, atau L3)."""
    if not GRID_USE_GEMINI_VALIDATION:
        return True, "[AI-BYPASS] Validasi Gemini dimatikan di konfigurasi."

    info = peta_analisa.get(coin, {})
    info_btc = peta_analisa.get("BTC", {})
    status_kompas_btc = f"{info_btc.get('tren_detail', 'N/A')} (RSI 5M:{info_btc.get('rsi', '-')}, RSI 4H:{info_btc.get('rsi_4h', '-')})"
    defisit_rec = float(state.get("loss_to_recover_idr", 0.0))

    tp1 = bulatkan_harga_indodax(coin, p1 * (1.0 + step_pct))
    p3 = bulatkan_harga_indodax(coin, p1 * (1.0 - (step_pct * 2.0)))
    tugas = [{
        "id": f"GRID_L{tier_no}_{coin}",
        "jenis": "GRID_ENTRY",
        "default_jika_error": GRID_GEMINI_FALLBACK_ALLOW,
        "alasan_fallback": (
            f"YA - Quant Fallback menyetujui buka Lapis {tier_no} {coin}."
            if GRID_GEMINI_FALLBACK_ALLOW else
            f"TUNDA - Kuota Gemini limit, buka Lapis {tier_no} {coin} ditahan."
        ),
        "deskripsi": (
            f"TIPE: GRID_ENTRY | Buka Lapis {tier_no} {coin} (4H:{info.get('lampu_4h', '-')}, Step:{step_pct*100:.1f}%) | "
            f"b1:Rp{p1:,.0f} -> Finis TP b1:Rp{tp1:,.0f} | b3:Rp{p3:,.0f} | "
            f"Tren:{info.get('tren_detail', '-')} | RSI 5M:{info.get('rsi', '-')}, 15M:{info.get('rsi_15m', '-')}, "
            f"1H:{info.get('rsi_1h', '-')}, 4H:{info.get('rsi_4h', '-')} | "
            f"DistEMA20_15M:{info.get('jarak_ema20_15m_pct', 0):+.2f}% | ATR15M:{info.get('atr_15m_pct', 0)*100:.2f}% | "
            f"Spread:{info.get('spread_pct', 0)*100:.2f}% | Memori:{note_memori}."
        )
    }]
    hasil = konsultasi_batch_terpadu_gemini(tugas, status_kompas_btc, defisit_rec)
    setuju, alasan, _ = hasil.get(tugas[0]["id"], (GRID_GEMINI_FALLBACK_ALLOW, "[QUANT-FALLBACK]", True))
    return setuju, alasan

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

        kandidat = sorted(kandidat_raw, key=lambda x: x["skor_efektif"], reverse=True)
        if not kandidat:
            log_grid.append("⏸️ [GRID CASH IS KING] Belum ada koin memenuhi syarat Lapis 1 (4H!=MERAH, M15/H1/5M valid & anti-pucuk).")
            return state, log_grid, log_tx, False

        pilih = kandidat[0]
        coin = pilih["coin"]
        step_l1 = pilih["grid_step_aktif"]
        mode_4h = pilih["lampu_4h"]
        p1 = bulatkan_harga_indodax(coin, pilih["harga_bid"])
        qty_b1 = hitung_kuantitas_koin(coin, GRID_CAPITAL_PER_LAYER_IDR, p1)

        # Validasi Gemini AI sebelum membuka Lapis 1
        setuju_ai, alasan_ai = _validasi_grid_dengan_gemini(
            peta_analisa, state, coin, 1, p1, step_l1, pilih["catatan_memori_grid"]
        )
        if not setuju_ai:
            log_grid.append(f"⏸️ [GEMINI TUNDA LAPIS 1 {coin}] {alasan_ai}")
            return state, log_grid, log_tx, False

        ok_b1, res_b1, harga_b1_pasang, tif_b1 = pasang_order_grid_aman(
            coin, "BUY", p1, qty_b1, info_pasar=pilih, paksa_gtc_fallback=True
        )
        if ok_b1:
            oid_b1 = str(res_b1.get("orderId"))
            qty_b1_ok = hitung_kuantitas_koin(coin, GRID_CAPITAL_PER_LAYER_IDR, harga_b1_pasang) if harga_b1_pasang != p1 else qty_b1
            tier_1 = _buat_struktur_tier_baru(coin, 1, harga_b1_pasang, step_l1, mode_4h, oid_b1, qty_b1_ok, now_ts)
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
                f"b2:Rp{l1['b2']['buy_price']:,.0f} | b3:Rp{l1['b3']['buy_price']:,.0f} (Order:#{oid_b1}) | AI: {alasan_ai}"
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
        # 1. KAWAL ANTREAN AWAL b1 (TERMASUK HANDLER PARTIALLY_FILLED & CANCELED)
        # ----------------------------------------------------------------------
        if layers["b1"]["status"] == "WAIT_BUY":
            st_b1, detail_b1 = cek_status_order_indodax(coin, layers["b1"]["buy_oid"])
            terisi_sim = (not LIVE_TRADING_ENABLED) and (harga_skrg <= layers["b1"]["buy_price"])

            if st_b1 == "FILLED" or terisi_sim:
                dompet_baru = ambil_saldo_lengkap_indodax()
                exec_qty, exec_price = ekstrak_eksekusi_order(detail_b1, fallback_price=layers["b1"]["buy_price"])
                qty_dasar = exec_qty if exec_qty > 0 else layers["b1"]["qty"]
                qty_b1_aktual = format_qty_koin(
                    coin,
                    min(qty_dasar, dompet_baru["coins_free"].get(coin, qty_dasar))
                    if LIVE_TRADING_ENABLED else qty_dasar
                )
                _promosikan_b1_dan_pasang_jaring(coin, tier, qty_b1_aktual, exec_price, info)
                ada_aksi = True
                pesan = (
                    f"✅ [LAPIS {t_no} b1 TERBELI] {coin} aktif @ Rp{layers['b1']['buy_price']:,.0f}! "
                    f"TP Finis L{t_no} @ Rp{layers['b1']['tp_price']:,.0f}, jaring b2 & b3 dipasang."
                )
                log_grid.append(pesan)
                log_tx.append(pesan)
                continue

            if st_b1 in ("CANCELED", "EXPIRED", "REJECTED", "NOT_FOUND"):
                exec_qty, exec_price = ekstrak_eksekusi_order(detail_b1, fallback_price=layers["b1"]["buy_price"])
                if exec_qty > 0 and (exec_qty * exec_price) >= MIN_LIMIT_ORDER_INDODAX_IDR:
                    dompet_baru = ambil_saldo_lengkap_indodax()
                    qty_b1_aktual = format_qty_koin(coin, min(exec_qty, dompet_baru["coins_free"].get(coin, exec_qty)))
                    _promosikan_b1_dan_pasang_jaring(coin, tier, qty_b1_aktual, exec_price, info)
                    ada_aksi = True
                    pesan = (
                        f"⚠️ [LAPIS {t_no} b1 PARTIAL FILL] Order {st_b1} tapi terisi {qty_b1_aktual} {coin}. "
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
                        qty_b1_aktual = format_qty_koin(coin, min(qty_dasar, dompet_baru["coins_free"].get(coin, qty_dasar)))
                        _promosikan_b1_dan_pasang_jaring(coin, tier, qty_b1_aktual, exec_price, info)
                        ada_aksi = True
                        pesan = (
                            f"✅ [BATAL b1 LAPIS {t_no} DIGAGALKAN - SUDAH TERISI] {coin} Qty:{qty_b1_aktual} "
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
        # 2. CEK STATUS TERBELI (WAIT_BUY -> HOLDING) UNTUK b2 DAN b3
        # ----------------------------------------------------------------------
        for nama_lp in ("b2", "b3"):
            lp = layers[nama_lp]
            if lp["status"] == "WAIT_BUY" and lp.get("buy_oid"):
                st_buy, detail_buy = cek_status_order_indodax(coin, lp["buy_oid"])
                terisi_sim = (not LIVE_TRADING_ENABLED) and (harga_skrg <= lp["buy_price"])

                if st_buy == "FILLED" or terisi_sim:
                    dompet_baru = ambil_saldo_lengkap_indodax()
                    exec_qty, exec_price = ekstrak_eksekusi_order(detail_buy, fallback_price=lp["buy_price"])
                    qty_dasar = exec_qty if exec_qty > 0 else lp["qty"]
                    qty_aktual = format_qty_koin(
                        coin,
                        min(qty_dasar, dompet_baru["coins_free"].get(coin, qty_dasar))
                        if LIVE_TRADING_ENABLED else qty_dasar
                    )
                    if exec_price > 0:
                        lp["buy_price"] = bulatkan_harga_indodax(coin, exec_price)
                    lp["qty"] = qty_aktual
                    lp["capital_idr"] = round(qty_aktual * float(lp["buy_price"]), 0)
                    lp["status"] = "HOLDING"
                    lp["buy_oid"] = None
                    if t_no == 1 and nama_lp == "b3":
                        cycle["b3_ever_touched"] = True

                    ok_sell, res_sell, harga_sell_pasang, tif_s = pasang_order_grid_aman(
                        coin, "SELL", lp["tp_price"], qty_aktual, info_pasar=info, paksa_gtc_fallback=True
                    )
                    if ok_sell:
                        lp["sell_oid"] = str(res_sell.get("orderId"))
                        lp["tp_price"] = harga_sell_pasang
                    ada_aksi = True
                    pesan = (
                        f"🟢 [LAPIS {t_no} {nama_lp.upper()} TERBELI] {coin} @ Rp{lp['buy_price']:,.0f} -> "
                        f"Pasang TP ({tif_s}) @ Rp{lp['tp_price']:,.0f}."
                    )
                    log_grid.append(pesan)
                    log_tx.append(pesan)

                elif st_buy in ("CANCELED", "EXPIRED", "REJECTED", "NOT_FOUND"):
                    exec_qty, exec_price = ekstrak_eksekusi_order(detail_buy, fallback_price=lp["buy_price"])
                    lp["buy_oid"] = None
                    if exec_qty > 0 and (exec_qty * exec_price) >= MIN_LIMIT_ORDER_INDODAX_IDR:
                        dompet_baru = ambil_saldo_lengkap_indodax()
                        qty_aktual = format_qty_koin(coin, min(exec_qty, dompet_baru["coins_free"].get(coin, exec_qty)))
                        lp["qty"] = qty_aktual
                        lp["buy_price"] = bulatkan_harga_indodax(coin, exec_price)
                        lp["capital_idr"] = round(qty_aktual * lp["buy_price"], 0)
                        lp["status"] = "HOLDING"
                        ok_sell, res_sell, harga_sell_pasang, _ = pasang_order_grid_aman(
                            coin, "SELL", lp["tp_price"], qty_aktual, info_pasar=info, paksa_gtc_fallback=True
                        )
                        if ok_sell:
                            lp["sell_oid"] = str(res_sell.get("orderId"))
                            lp["tp_price"] = harga_sell_pasang
                        ada_aksi = True
                        log_grid.append(f"⚠️ [LAPIS {t_no} {nama_lp.upper()} PARTIAL] Status {st_buy}, sisa terisi {qty_aktual} dipasang TP.")
                    else:
                        lp["status"] = "ARMED"
                        log_grid.append(f"🔄 [LAPIS {t_no} {nama_lp.upper()} RE-ARM] Order beli {st_buy}, dijadwalkan pasang ulang.")

        # ----------------------------------------------------------------------
        # 3. CEK STATUS TERJUAL PROFIT (URUTAN b1 -> b2 -> b3 AGAR EFISIEN)
        # ----------------------------------------------------------------------
        for nama_lp in ("b1", "b2", "b3"):
            lp = layers[nama_lp]
            if lp["status"] == "HOLDING" and lp.get("sell_oid"):
                st_sell, detail_sell = cek_status_order_indodax(coin, lp["sell_oid"])
                terjual_sim = (not LIVE_TRADING_ENABLED) and (harga_skrg >= lp["tp_price"])

                if st_sell == "FILLED" or terjual_sim:
                    _, harga_laku = ekstrak_eksekusi_order(detail_sell, fallback_price=lp["tp_price"])
                    gross_pct = (harga_laku - float(lp["buy_price"])) / max(1.0, float(lp["buy_price"]))
                    net_pct = gross_pct - FEE_ROUNDTRIP_MAKER_PCT
                    profit_idr = round(float(lp["capital_idr"]) * net_pct, 0)

                    cycle["bounce_count"] = int(cycle.get("bounce_count", 0)) + 1
                    cycle["realized_grid_profit_idr"] = round(float(cycle.get("realized_grid_profit_idr", 0.0)) + profit_idr, 0)
                    tier["realized_tier_profit_idr"] = round(float(tier.get("realized_tier_profit_idr", 0.0)) + profit_idr, 0)
                    slot_mem = {"coin": coin, "style": f"GRID_L{t_no}_{nama_lp.upper()}", "capital_idr": lp["capital_idr"]}
                    catat_hasil_transaksi_ke_recovery(state, profit_idr, coin, slot=slot_mem, pnl_exit_pct=net_pct)
                    lp["sell_oid"] = None
                    ada_aksi = True

                    if nama_lp == "b1":
                        lp["status"] = "DONE"
                        lp["qty"] = 0.0
                        pesan = (
                            f"🎉 [LAPIS {t_no} TP b1 TERCAPAI!] {coin} laku @ Rp{harga_laku:,.0f} "
                            f"(Net:+Rp{profit_idr:,.0f} | Total Pantul:{cycle['bounce_count']}x)."
                        )
                    elif layers["b1"]["status"] == "DONE":
                        # b1 sudah selesai -> jangan pasang ulang jaring b2/b3 agar lapis langsung tutup bersih
                        lp["status"] = "DONE"
                        lp["qty"] = 0.0
                        pesan = f"💰 [PANEN PENUTUP LAPIS {t_no} {nama_lp.upper()}] {coin} laku @ Rp{harga_laku:,.0f} (+Rp{profit_idr:,.0f})."
                    else:
                        q_ulang = hitung_kuantitas_koin(coin, GRID_CAPITAL_PER_LAYER_IDR, lp["buy_price"])
                        ok_re, res_re, harga_re, tif_re = pasang_order_grid_aman(
                            coin, "BUY", lp["buy_price"], q_ulang, info_pasar=info, paksa_gtc_fallback=True
                        )
                        if ok_re:
                            lp["status"] = "WAIT_BUY"
                            lp["buy_oid"] = str(res_re.get("orderId"))
                            lp["buy_price"] = harga_re
                            lp["qty"] = q_ulang
                            lp["capital_idr"] = round(q_ulang * harga_re, 0)
                        else:
                            lp["status"] = "ARMED"
                            lp["buy_oid"] = None
                            lp["qty"] = 0.0
                        pesan = (
                            f"💰 [PANEN LAPIS {t_no} {nama_lp.upper()}!] {coin} laku @ Rp{harga_laku:,.0f} "
                            f"(+Rp{profit_idr:,.0f} | Pantul #{cycle['bounce_count']}). Jaring dipasang ulang ({tif_re})."
                        )
                    log_grid.append(pesan)
                    log_tx.append(pesan)

                elif st_sell in ("CANCELED", "EXPIRED", "REJECTED", "NOT_FOUND"):
                    # Order TP dibatalkan manual/expired -> reset sell_oid agar Self-Healing langsung pasang ulang
                    exec_qty, harga_laku = ekstrak_eksekusi_order(detail_sell, fallback_price=lp["tp_price"])
                    lp["sell_oid"] = None
                    if exec_qty > 0:
                        sisa_qty = format_qty_koin(coin, max(0.0, float(lp["qty"]) - exec_qty))
                        modal_terjual = exec_qty * float(lp["buy_price"])
                        net_pct = ((harga_laku - float(lp["buy_price"])) / max(1.0, float(lp["buy_price"]))) - FEE_ROUNDTRIP_MAKER_PCT
                        profit_parsial = round(modal_terjual * net_pct, 0)
                        cycle["realized_grid_profit_idr"] = round(float(cycle.get("realized_grid_profit_idr", 0.0)) + profit_parsial, 0)
                        tier["realized_tier_profit_idr"] = round(float(tier.get("realized_tier_profit_idr", 0.0)) + profit_parsial, 0)
                        lp["qty"] = sisa_qty
                        lp["capital_idr"] = round(sisa_qty * float(lp["buy_price"]), 0)
                        if (sisa_qty * harga_skrg) < MIN_LIMIT_ORDER_INDODAX_IDR:
                            lp["status"] = "DONE"
                            log_grid.append(f"💰 [TP PARSIAL SELESAI L{t_no} {nama_lp.upper()}] Terjual {exec_qty} @ Rp{harga_laku:,.0f} (+Rp{profit_parsial:,.0f}).")
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
                    ok_h, res_h, harga_h, tif_h = pasang_order_grid_aman(
                        coin, "SELL", lp["tp_price"], qty_jual_h, info_pasar=info, paksa_gtc_fallback=True
                    )
                    if ok_h:
                        lp["sell_oid"] = str(res_h.get("orderId"))
                        lp["tp_price"] = harga_h
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
    drop_trigger_pct = GRID_NEXT_TIER_DROP_YELLOW_PCT if lampu_4h == "KUNING" else GRID_NEXT_TIER_DROP_GREEN_PCT
    harga_pemicu_lapis_baru = b3_terbawah["buy_price"] * (1.0 - drop_trigger_pct)

    if (
        len(tiers) < GRID_MAX_TIERS
        and lapis_berikutnya <= GRID_MAX_TIERS
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
            _, note_mem = hitung_penyesuaian_skor_memori_grid(state, coin)

            setuju_ai, alasan_ai = _validasi_grid_dengan_gemini(
                peta_analisa, state, coin, lapis_berikutnya, p1_baru, step_baru, note_mem
            )
            if not setuju_ai:
                log_grid.append(f"⏸️ [GEMINI TUNDA LAPIS {lapis_berikutnya} {coin}] {alasan_ai}")
            else:
                qty_b1_baru = hitung_kuantitas_koin(coin, GRID_CAPITAL_PER_LAYER_IDR, p1_baru)
                ok_nb, res_nb, harga_nb_pasang, tif_nb = pasang_order_grid_aman(
                    coin, "BUY", p1_baru, qty_b1_baru, info_pasar=info, paksa_gtc_fallback=True
                )
                if ok_nb:
                    oid_nb = str(res_nb.get("orderId"))
                    qty_nb_ok = hitung_kuantitas_koin(coin, GRID_CAPITAL_PER_LAYER_IDR, harga_nb_pasang) if harga_nb_pasang != p1_baru else qty_b1_baru
                    tier_baru = _buat_struktur_tier_baru(coin, lapis_berikutnya, harga_nb_pasang, step_baru, lampu_4h, oid_nb, qty_nb_ok, now_ts)
                    tiers.append(tier_baru)
                    ada_aksi = True
                    lb = tier_baru["layers"]
                    pesan = (
                        f"🧱 [BUKA LAPIS {lapis_berikutnya} ({tif_nb}) | 4H:{lampu_4h} Step:{step_baru*100:.1f}%] {coin} "
                        f"b1:Rp{lb['b1']['buy_price']:,.0f}->FINIS TP L{lapis_berikutnya}:Rp{lb['b1']['tp_price']:,.0f} | "
                        f"b2:Rp{lb['b2']['buy_price']:,.0f} | b3:Rp{lb['b3']['buy_price']:,.0f} (Order:#{oid_nb}) | AI: {alasan_ai}"
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
# BAGIAN 10: PROGRAM UTAMA
# ==============================================================================
def jalankan_satu_siklus_penuh(state, paksa_kirim_sheets=False):
    dompet = ambil_saldo_lengkap_indodax()
    if LIVE_TRADING_ENABLED and not dompet.get("terhubung"):
        print("⚠️ Gagal terhubung ke API Indodax. Siklus dilewati agar state tidak rusak.")
        return state, False, [], False, {}, {}

    harga_live_map = ambil_harga_idr_semua_koin()

    # Langkah 1: Rekonsiliasi 2-Arah Dompet Indodax (Aktif di Mode Grid maupun Scalping!)
    log_recovery = []
    if GRID_MODE_ENABLED:
        state, log_recovery = rekonsiliasi_grid_dengan_indodax(state, dompet, harga_live_map)
    else:
        state, log_recovery = sinkronkan_koin_dompet_indodax(state, dompet, harga_live_map)
        if log_recovery:
            dompet = ambil_saldo_lengkap_indodax()

    # Langkah 2: Analisa Multi-Timeframe Native Indodax (5M + 15M + 1H + 4H)
    peta_analisa_pasar = analisa_teknikal_lengkap_pasar(harga_live_map)

    if GRID_MODE_ENABLED:
        state, log_grid, log_tx_grid, ada_aksi_grid = kelola_siklus_grid_3_lapis(
            state, peta_analisa_pasar, dompet, harga_live_map=harga_live_map
        )
        simpan_state_bot(state)
        for baris in (log_recovery + log_grid):
            print("  ", baris)
        if ada_aksi_grid or log_recovery or paksa_kirim_sheets:
            lapor_ke_google_sheets(state, log_recovery + (log_tx_grid or log_grid), dompet, harga_live_map)
        else:
            print("ℹ️ [GRID TENANG] Belum ada eksekusi grid baru, Google Sheets tidak ditambah.")
        return state, False, [], ada_aksi_grid, peta_analisa_pasar, harga_live_map

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
        print("ℹ️ [TIDAK ADA TRANSAKSI BARU] Sesi patroli tenang, Google Sheets tidak ditambah.")

    return state, butuh_siaga, alasan_siaga, ada_transaksi_nyata, peta_analisa_pasar, harga_live_map

def cek_status_koneksi_gemini_awal():
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
            f"Penalaran: {_LEVEL_PENALARAN_AKTIF} | Jumlah API Key: {len(daftar_kunci)} | "
            f"Validasi Grid: {'AKTIF' if GRID_USE_GEMINI_VALIDATION else 'OFF'}]"
        )
    else:
        print("❌ [STATUS GEMINI AI GAGAL TERHUBUNG] Tidak dapat memuat daftar model dari Google API.")

if __name__ == "__main__":
    waktu_mulai = time.time()
    batas_waktu_siaga = waktu_mulai + (ACTIVE_WATCH_MINUTES * 60)

    cek_status_koneksi_gemini_awal()
    state = muat_state_bot()
    state, butuh_siaga, alasan_siaga, _, peta_analisa_terakhir, harga_live_terakhir = jalankan_satu_siklus_penuh(
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

            state, masih_butuh_siaga, alasan_baru, ada_eksekusi, peta_analisa_terakhir, harga_live_terakhir = jalankan_satu_siklus_penuh(
                state, paksa_kirim_sheets=False
            )
            if ada_eksekusi:
                print("✅ [TRANSAKSI REAL-TIME BERHASIL] State & Google Sheets telah diperbarui!")
            if not masih_butuh_siaga:
                print("\n" + buat_kesimpulan_patroli_dinamis(state, peta_analisa_terakhir, harga_live_terakhir))
                kesimpulan_sudah_cetak = True
                break
        if not kesimpulan_sudah_cetak:
            print("\n" + buat_kesimpulan_patroli_dinamis(state, peta_analisa_terakhir, harga_live_terakhir))
    else:
        print("\n" + buat_kesimpulan_patroli_dinamis(state, peta_analisa_terakhir, harga_live_terakhir))
