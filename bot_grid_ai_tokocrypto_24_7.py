#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# INDODAX PRO MULTI-REGIME SWING & WIDE-GRID BOT (EDISI BLUEPRINT 2026)
# ==============================================================================
# Dibangun 100% berlandaskan Analisis Trading Profesional Kripto Indodax 2026:
#   1. Ekonomi Friksi PMK 50/2025 + CFX 2026:
#      - Maker Beli 0.1111% | Maker Jual 0.3211% (RT Maker-Maker 0.4322%)
#      - Taker Beli 0.2111% | Taker Jual 0.4211% (RT Taker-Taker 0.6322%)
#      - Eksak Net Win, Net Loss, Net RRR (>= 1:2.00 wajib), Friction-Adjusted Sizing
#   2. Seleksi Likuiditas Puncak Indodax Pro IDR (Core-Satellite):
#      - Core (60-80%): BTC/IDR, ETH/IDR | Satellite (15-30%): XRP/IDR, SOL/IDR
#      - Parkir Kas & Hedge Kurs (Plan B): USDT/IDR | Nol Koin Micin!
#   3. Dual-Chart Analysis (Grafik Global H4 & Daily -> Eksekusi Indodax Pro IDR):
#      - Struktur tren, EMA 50/100/200, RSI + Divergence, MACD, ATR(14) dari Global USD
#      - Validasi DOM Indodax Pro (Spread, Order Book Imbalance, Anti-Spoofing 15-30m)
#      - Filter Kurs USD/IDR & Deteksi Anomali Konversi USDT/IDR
#      - Filter Jendela Likuiditas Puncak (20:00-00:00 WIB, Selasa-Kamis)
#   4. Regime Gate & PLAN B Komprehensif (4 Rezim Pasar):
#      - BULL               -> Core Swing H4-Daily (Staged Partial TP 40/30/30 + BE +0.60%)
#      - SIDEWAYS           -> Wide Grid >= 2.0% (Maks 30% Modal, BTC/ETH, Maker-Only MOC)
#      - SIDEWAYS_DOWNTREND -> Plan B Tahap 1: Parkir Kas/USDT + Counter-Trend Relief Bounce
#                              Ultra-Selektif (Maks 15% Modal BTC/IDR, RSI Oversold + Div + DOM)
#                              atau Defensive Wide Grid 3.0% (+2.55% net)
#      - BEAR / CRASH       -> Plan B Tahap 2: Mode Risk-Off 80-90% Kas/USDT Parkir +
#                              Auto-Hedge Calculator & Alert CFX/OJK Derivatives (Reku/Pintu Pro)
#   5. Arsitektur 5 Lapisan Anti-Bug Produksi:
#      - Virtual OCO State Machine (Bebas Balance Lock Indodax + Buffer Stop-Limit Protektif)
#      - Dual-Key Gateway: Trade API v2 (MOC + STP EXPIRE_TAKER) + Legacy Deadman Switch 15m
#      - Hard Risk Layer Deterministik (Max Daily Loss, Max Drawdown 10% Kill Switch, Cooldown)
#      - Booting Aman (load_state() SEBELUM audit dompet), Rate Throttler (< 20 req/s)
#      - Persistensi Atomik state.json (tmp + os.replace) + SQLite WAL + Telegram & Sheets
# ==============================================================================

import os
import sys
import time
import math
import hmac
import hashlib
import sqlite3
import tempfile
import threading
import urllib.parse
import urllib.request
import urllib.error
import json
from datetime import datetime, timedelta, timezone

# ==============================================================================
# BAGIAN 1: KONFIGURASI EKONOMI INDODAX 2026, PORTOFOLIO & HARD RISK LAYER
# ==============================================================================

# --- Mode Operasional ---
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
RUN_MODE = os.getenv("RUN_MODE", "cycle").strip().lower()  # "cycle" (GitHub Actions) | "daemon" (VPS 24/7)
CYCLE_WATCH_MINUTES = int(os.getenv("CYCLE_WATCH_MINUTES", "4"))
OCO_POLL_SECONDS = int(os.getenv("OCO_POLL_SECONDS", "15"))
DAEMON_ANALYSIS_INTERVAL_SEC = int(os.getenv("DAEMON_ANALYSIS_INTERVAL_SEC", "900"))  # 15 menit cek H4/DOM

# --- Modal Kerja & Aturan Minimum Indodax Pro ---
MAX_BOT_CAPITAL_IDR = float(os.getenv("MAX_BOT_CAPITAL_IDR", "100000000"))  # Default 100jt (ubah via ENV sesuai modal)
MIN_INDODAX_PRO_ORDER_IDR = 25000.0        # Batas bawah Limit Order Indodax Pro (di bawah ini jatuh ke Lite Market)
MIN_SAFE_POSITION_IDR = 30000.0            # Buffer aman agar setelah SL -5% nilai jual tetap > Rp25.000
SPOT_CORE_HOLDING_IDR = float(os.getenv("SPOT_CORE_HOLDING_IDR", "0"))  # Nilai spot cold-wallet/jangka panjang untuk hitung saran Hedge CFX

# --- Struktur Biaya & Pajak Aktual Indodax Pro IDR 2026 (PMK 50/2025 + CFX Maret 2026) ---
FEE_MAKER_BUY = float(os.getenv("FEE_MAKER_BUY", "0.001111"))     # 0.10% fee + 0.0111% CFX + 0% PPh
FEE_MAKER_SELL = float(os.getenv("FEE_MAKER_SELL", "0.003211"))   # 0.10% fee + 0.0111% CFX + 0.21% PPh 22 Final
FEE_TAKER_BUY = float(os.getenv("FEE_TAKER_BUY", "0.002111"))     # 0.20% fee + 0.0111% CFX + 0% PPh
FEE_TAKER_SELL = float(os.getenv("FEE_TAKER_SELL", "0.004211"))   # 0.20% fee + 0.0111% CFX + 0.21% PPh 22 Final
EST_SL_SLIPPAGE_CORE = 0.0015                                     # 0.15% estimasi slippage darurat BTC/ETH
EST_SL_SLIPPAGE_ALT = 0.0030                                      # 0.30% estimasi slippage darurat XRP/SOL

# --- Parameter Matematika RRR & Hard Risk Layer (100% Deterministik dalam Kode) ---
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "0.01"))        # 1.0% risiko modal per transaksi
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.015"))       # 1.5% batas rugi harian -> Circuit Breaker 24 jam
MAX_TOTAL_DRAWDOWN_PCT = float(os.getenv("MAX_TOTAL_DRAWDOWN_PCT", "0.10"))# 10.0% Max Drawdown -> Hard Kill Switch
MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_CONCURRENT_POSITIONS", "3")) # Maksimal 3 posisi terbuka simultan
MIN_NET_RRR_REQUIRED = float(os.getenv("MIN_NET_RRR_REQUIRED", "2.00"))    # Wajib Net RRR >= 1:2.00 pascafriksi
MIN_STRUCTURAL_SL_PCT = 0.035                                              # Minimal jarak SL 3.5% (friksi < 17% SL)
DEFAULT_SWING_SL_PCT = 0.040                                               # Standar Core Swing SL 4.0%
MAX_STRUCTURAL_SL_PCT = 0.060                                              # Maksimal jarak SL swing 6.0%
FEE_ADJUSTED_BE_PCT = 0.0060                                               # +0.60% (rentang +0.55% s.d. +0.65% breakeven sejati)
SL_COOLDOWN_HOURS = float(os.getenv("SL_COOLDOWN_HOURS", "12.0"))          # Masa tenang pasca-SL (skala swing H4)

# --- Staged Partial Take Profit (Core Swing: 40% TP1 / 30% TP2 / 30% TP3 Runner) ---
SWING_TP1_PCT = 0.080   # +8.0% -> Jual 40% + geser SL sisa 60% ke Fee-Adjusted BE (+0.60%)
SWING_TP2_PCT = 0.140   # +14.0% -> Jual 30%
SWING_TP3_PCT = 0.220   # +22.0% -> Jual 30% (atau lebih awal jika sinyal pembalikan RSI>70 div / MACD cross down)
SINGLE_TRANCHE_TP_PCT = 0.120  # +12.0% (Net RRR 1:2.47) jika modal terlalu kecil untuk dipecah 3 tranche

# --- Plan B: Sideways Wide Grid & Bearish / Sideways Downtrend ---
SIDEWAYS_GRID_MAX_ALLOC_PCT = 0.30    # Maksimal 30% modal kerja aktif saat Wide Grid Sideways
SIDEWAYS_GRID_SPACING_PCT = 0.020     # Minimal jarak grid 2.0% (+1.56% bersih per siklus Maker-Maker)
SIDEWAYS_GRID_LEVELS = 3              # 3 lapis grid beli di bawah harga saat ini
SIDEWAYS_GRID_HARD_STOP_PCT = 0.075   # Jika harga jebol > 7.5% di bawah rata-rata grid -> stop & lindungi modal

PLAN_B_ENABLE_RELIEF_BOUNCE = os.getenv("PLAN_B_ENABLE_RELIEF_BOUNCE", "true").lower() == "true"
PLAN_B_RELIEF_MAX_ALLOC_PCT = 0.15    # Maksimal 15% modal untuk Counter-Trend Relief Bounce / Defensive Grid di Sideways Downtrend
PLAN_B_DEFENSIVE_GRID_SPACING_PCT = 0.030  # Jarak 3.0% (+2.555% bersih) khusus Sideways Downtrend pada BTC/IDR
PLAN_B_AUTO_USDT_PARKING = os.getenv("PLAN_B_AUTO_USDT_PARKING", "false").lower() == "true"  # Parkir 80% kas IDR ke USDT/IDR saat BEAR
PLAN_B_USDT_PARKING_RATIO = 0.80      # 80% kas menganggur diparkir ke USDT/IDR saat rezim BEAR
PLAN_B_USDT_MAX_PREMIUM_PCT = 0.025   # Blokir beli USDT jika kurs USDT/IDR lonjak > 2.5% di atas EMA20 (anti-anomali kurs)
PLAN_B_HEDGE_LEVERAGE = 2.0           # Rekomendasi leverage konservatif 2x (rentang 2x-3x) untuk short hedge CFX (Reku/Pintu Pro)

# --- Filter Mikrostruktur DOM, Anti-Spoofing & Jendela Likuiditas ---
DOM_SPOOF_MIN_PERSIST_MINUTES = float(os.getenv("DOM_SPOOF_MIN_PERSIST_MINUTES", "15.0"))  # Uji ketahanan dinding bid 15-30m
ENFORCE_PEAK_LIQUIDITY_WINDOW = os.getenv("ENFORCE_PEAK_LIQUIDITY_WINDOW", "false").lower() == "true"
ALLOW_WEEKEND_NEW_ENTRIES = os.getenv("ALLOW_WEEKEND_NEW_ENTRIES", "false").lower() == "true"
PROFIT_SKIMMING_QUARTERLY_PCT = 0.30  # Rekomendasi tarik 30% profit kuartalan ke cold wallet

# --- Daftar Pasangan Aset Berlikuiditas Puncak Indodax Pro IDR (Core-Satellite) ---
# Core Blue-Chip: 60-80% | Large-Cap Accelerator: 15-30% | Parkir Kas: USDT
UNIVERSE = {
    "BTC": {
        "tier": "CORE",
        "max_portfolio_weight": 0.45,
        "v2_symbol": "BTCIDR",
        "indodax_pair": "btc_idr",
        "binance_symbol": "BTCUSDT",
        "kraken_pair": "XXBTZUSD",
        "price_step": 1000.0,
        "qty_decimals": 6,
        "max_spread_pct": 0.0035,        # Spread tipikal 0.05%-0.30%
        "sl_buffer_pct": 0.008,          # Buffer Stop-Limit protektif 0.5%-1.0%
        "sl_slippage_est": EST_SL_SLIPPAGE_CORE,
        "min_depth_idr": 500_000_000.0,  # Validasi minimal kedalaman order book
        "grid_eligible": True,
    },
    "ETH": {
        "tier": "CORE",
        "max_portfolio_weight": 0.35,
        "v2_symbol": "ETHIDR",
        "indodax_pair": "eth_idr",
        "binance_symbol": "ETHUSDT",
        "kraken_pair": "XETHZUSD",
        "price_step": 1000.0,
        "qty_decimals": 5,
        "max_spread_pct": 0.0040,
        "sl_buffer_pct": 0.010,          # Buffer Stop-Limit protektif 1.0%
        "sl_slippage_est": EST_SL_SLIPPAGE_CORE,
        "min_depth_idr": 200_000_000.0,
        "grid_eligible": True,
    },
    "XRP": {
        "tier": "SATELLITE",
        "max_portfolio_weight": 0.15,
        "v2_symbol": "XRPIDR",
        "indodax_pair": "xrp_idr",
        "binance_symbol": "XRPUSDT",
        "kraken_pair": "XXRPZUSD",
        "price_step": 1.0,
        "qty_decimals": 2,
        "max_spread_pct": 0.0045,
        "sl_buffer_pct": 0.022,          # Buffer Stop-Limit protektif 2%-3% altcoin
        "sl_slippage_est": EST_SL_SLIPPAGE_ALT,
        "min_depth_idr": 150_000_000.0,
        "grid_eligible": False,
    },
    "SOL": {
        "tier": "SATELLITE",
        "max_portfolio_weight": 0.15,
        "v2_symbol": "SOLIDR",
        "indodax_pair": "sol_idr",
        "binance_symbol": "SOLUSDT",
        "kraken_pair": "SOLUSD",
        "price_step": 100.0,
        "qty_decimals": 4,
        "max_spread_pct": 0.0045,
        "sl_buffer_pct": 0.025,          # Buffer Stop-Limit protektif 2%-3% altcoin (bid depth < 1M)
        "sl_slippage_est": EST_SL_SLIPPAGE_ALT,
        "min_depth_idr": 100_000_000.0,
        "grid_eligible": False,
    },
}

USDT_PARK_SPEC = {
    "v2_symbol": "USDTIDR",
    "indodax_pair": "usdt_idr",
    "price_step": 1.0,
    "qty_decimals": 2,
}

# --- Kredensial & Integrasi (Dual-Key + Opsional Gemini Advisory + Telegram + Sheets) ---
INDODAX_API_KEY = os.getenv("INDODAX_API_KEY", "").strip()
INDODAX_SECRET_KEY = os.getenv("INDODAX_SECRET_KEY", "").strip()
# Legacy Key v1 (khusus Deadman Switch countdownCancelAll 15 menit saat mode VPS 24/7)
INDODAX_LEGACY_KEY = os.getenv("INDODAX_LEGACY_KEY", "").strip()
INDODAX_LEGACY_SECRET = os.getenv("INDODAX_LEGACY_SECRET", "").strip()
DEADMAN_SWITCH_SECONDS = int(os.getenv("DEADMAN_SWITCH_SECONDS", "900"))  # 15 menit

# Opsional AI Advisory Filter (shadow-only atau entry-confirmation; TIDAK BOLEH sentuh SL/Hard Risk)
GEMINI_ADVISORY_MODE = os.getenv("GEMINI_ADVISORY_MODE", "off").strip().lower()  # "off" | "shadow" | "entry_filter"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
GOOGLE_SHEETS_WEBHOOK_URL = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()

STATE_FILE = os.getenv("STATE_FILE", "indodax_pro_state.json")
SQLITE_DB_FILE = os.getenv("SQLITE_DB_FILE", "indodax_pro_audit.db")

# ==============================================================================
# BAGIAN 2: UTILITAS WAKTU WIB, RATE THROTTLER & PERSISTENSI ATOMIK + SQLITE WAL
# ==============================================================================
TZ_WIB = timezone(timedelta(hours=7))
_STATE_LOCK = threading.RLock()


class RateThrottler:
    """Membatasi permintaan API ketat di bawah kuota Indodax 20 req/detik agar bebas HTTP 429."""
    def __init__(self, max_per_sec=6.0):
        self.min_interval = 1.0 / max(1.0, float(max_per_sec))
        self._lock = threading.Lock()
        self._last_ts = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            delta = now - self._last_ts
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
            self._last_ts = time.monotonic()


API_THROTTLER = RateThrottler(max_per_sec=6.0)


def now_wib():
    return datetime.now(TZ_WIB)


def tanggal_wib_str():
    return now_wib().strftime("%Y-%m-%d")


def kuartal_wib_str():
    d = now_wib()
    q = ((d.month - 1) // 3) + 1
    return f"{d.year}-Q{q}"


def cek_jendela_likuiditas_wib(dt_wib=None):
    """
    Mengecek sesi likuiditas puncak Indonesia:
    - Puncak: 20:00-00:00 WIB (sesi gabungan Eropa-AS), Selasa-Kamis (weekday 1,2,3).
    - Akhir pekan (Sabtu=5, Minggu=6): likuiditas tipis & rawan false move.
    """
    dt = dt_wib or now_wib()
    wd = dt.weekday()  # 0=Senin .. 6=Minggu
    jam = dt.hour
    is_weekend = wd in (5, 6)
    is_prime_day = wd in (1, 2, 3)  # Selasa, Rabu, Kamis
    is_peak_hour = (20 <= jam <= 23) or (jam == 0)
    if is_weekend:
        label = "WEEKEND_TIPIS"
    elif is_prime_day and is_peak_hour:
        label = "PEAK_PRIME_WIB"
    elif is_peak_hour:
        label = "PEAK_WIB"
    else:
        label = "OFF_PEAK_WIB"
    return {
        "label": label,
        "is_weekend": is_weekend,
        "is_peak_hour": is_peak_hour,
        "is_prime_day": is_prime_day,
        "entry_allowed": (not is_weekend or ALLOW_WEEKEND_NEW_ENTRIES) and (
            not ENFORCE_PEAK_LIQUIDITY_WINDOW or is_peak_hour
        ),
    }


def init_sqlite_wal():
    """Inisialisasi SQLite dalam mode WAL untuk audit trail transaksi & kejadian risiko."""
    try:
        conn = sqlite3.connect(SQLITE_DB_FILE, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_wib TEXT NOT NULL,
                regime TEXT,
                coin TEXT,
                strategy TEXT,
                action TEXT,
                price_idr REAL,
                qty REAL,
                notional_idr REAL,
                net_pnl_idr REAL,
                net_rrr_est REAL,
                note TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS regime_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_wib TEXT NOT NULL,
                regime TEXT NOT NULL,
                btc_usd REAL,
                btc_ema50_d REAL,
                btc_ema100_d REAL,
                btc_rsi_h4 REAL,
                usdt_idr REAL,
                note TEXT
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ [SQLITE WAL INIT]: {e}")


def log_audit_db(regime, coin, strategy, action, price_idr=0.0, qty=0.0,
                 notional_idr=0.0, net_pnl_idr=0.0, net_rrr_est=0.0, note=""):
    try:
        conn = sqlite3.connect(SQLITE_DB_FILE, timeout=10)
        conn.execute(
            """INSERT INTO trade_audit
               (ts_wib, regime, coin, strategy, action, price_idr, qty, notional_idr, net_pnl_idr, net_rrr_est, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now_wib().strftime("%Y-%m-%d %H:%M:%S"),
                regime, coin, strategy, action,
                float(price_idr or 0.0), float(qty or 0.0), float(notional_idr or 0.0),
                float(net_pnl_idr or 0.0), float(net_rrr_est or 0.0), str(note)[:500],
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def log_regime_db(regime_info):
    try:
        conn = sqlite3.connect(SQLITE_DB_FILE, timeout=10)
        conn.execute(
            """INSERT INTO regime_history
               (ts_wib, regime, btc_usd, btc_ema50_d, btc_ema100_d, btc_rsi_h4, usdt_idr, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now_wib().strftime("%Y-%m-%d %H:%M:%S"),
                regime_info.get("regime", "UNKNOWN"),
                float(regime_info.get("btc_usd", 0.0)),
                float(regime_info.get("btc_ema50_d", 0.0)),
                float(regime_info.get("btc_ema100_d", 0.0)),
                float(regime_info.get("btc_rsi_h4", 50.0)),
                float(regime_info.get("usdt_idr", 0.0)),
                str(regime_info.get("reason", ""))[:400],
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def default_state():
    return {
        "schema_version": 3,
        "configured_capital_idr": MAX_BOT_CAPITAL_IDR,
        "last_reset_date": tanggal_wib_str(),
        "current_quarter": kuartal_wib_str(),
        "peak_equity_idr": MAX_BOT_CAPITAL_IDR,
        "current_equity_idr": MAX_BOT_CAPITAL_IDR,
        "realized_pnl_today_idr": 0.0,
        "realized_pnl_quarter_idr": 0.0,
        "skimmed_cold_wallet_total_idr": 0.0,
        "completed_trades_total": 0,
        "wins_total": 0,
        "losses_total": 0,
        "circuit_breaker_until_ts": 0.0,
        "kill_switch_active": False,
        "kill_switch_reason": "",
        "sl_cooldown_until": {},
        "last_regime": "UNKNOWN",
        "last_hedge_alert_ts": 0.0,
        "dom_wall_tracker": {},      # Persistensi uji ketahanan dinding bid 15-30m (anti-spoofing)
        "usdt_idr_history": [],      # Riwayat kurs USDT/IDR untuk deteksi anomali kurs
        "usdt_parked_qty": 0.0,
        "usdt_parked_avg_idr": 0.0,
        "swing_positions": [],       # Posisi Core Swing & Relief Bounce (Virtual OCO)
        "grid_orders": [],           # Order Wide Grid (Sideways 2.0% / Defensive 3.0%)
    }


def load_state():
    """
    WAJIB dipanggil PALING AWAL saat booting (sebelum audit order/dompet)
    agar order Grid/Swing aktif & status circuit breaker tidak pernah terhapus pasca-restart.
    """
    with _STATE_LOCK:
        tgl = tanggal_wib_str()
        qtr = kuartal_wib_str()
        st = default_state()
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    st.update(loaded)
            except Exception as e:
                print(f"⚠️ [LOAD STATE GAGAL - PAKAI DEFAULT AMAN]: {e}")

        if st.get("last_reset_date") != tgl:
            st["realized_pnl_today_idr"] = 0.0
            st["last_reset_date"] = tgl
        if st.get("current_quarter") != qtr:
            st["realized_pnl_quarter_idr"] = 0.0
            st["current_quarter"] = qtr
        # Jika user mengubah MAX_BOT_CAPITAL_IDR di Secrets/ENV (misal dari default ke 100rb),
        # selaraskan ekuitas kerja agar plafon baru langsung berlaku secara presisi.
        prev_cfg = float(st.get("configured_capital_idr", 0.0) or 0.0)
        if abs(prev_cfg - MAX_BOT_CAPITAL_IDR) >= 1.0:
            st["configured_capital_idr"] = MAX_BOT_CAPITAL_IDR
            st["current_equity_idr"] = MAX_BOT_CAPITAL_IDR
            st["peak_equity_idr"] = MAX_BOT_CAPITAL_IDR
            st["kill_switch_active"] = False
            st["kill_switch_reason"] = ""
        return st


def save_state_atomic(state):
    """Penulisan atomik (tmp + os.replace) agar state.json kebal mati listrik / redeploy."""
    with _STATE_LOCK:
        state["last_saved_wib"] = now_wib().strftime("%Y-%m-%d %H:%M:%S")
        dir_name = os.path.dirname(os.path.abspath(STATE_FILE)) or "."
        fd, tmp_path = tempfile.mkstemp(prefix=".state_tmp_", suffix=".json", dir=dir_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                json.dump(state, tmp_file, indent=2, ensure_ascii=False)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, STATE_FILE)
        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            print(f"⚠️ [SAVE STATE ATOMIC GAGAL]: {e}")


# ==============================================================================
# BAGIAN 3: MATEMATIKA EKSAK RRR & FRICTION-ADJUSTED POSITION SIZING
# ==============================================================================
def hitung_matematika_rrr_eksak(
    tp_gross,
    sl_gross,
    f_buy=FEE_MAKER_BUY,
    f_tp=FEE_MAKER_SELL,
    f_sl=FEE_TAKER_SELL,
    s_buy=0.0,
    s_tp=0.0,
    s_sl=EST_SL_SLIPPAGE_CORE,
):
    """
    Rumus eksak multiplikatif pascafriksi (Bagian 5 File Analisis):
      Net Win  = ((1 - f_buy) * (1 + tp_gross - s_tp) * (1 - f_tp)) / (1 + s_buy) - 1
      Net Loss = 1 - ((1 - f_buy) * (1 - sl_gross - s_sl) * (1 - f_sl)) / (1 + s_buy)
      Net RRR  = Net Win / Net Loss
      BE WR    = 1 / (1 + Net RRR)
    """
    net_win = ((1.0 - f_buy) * (1.0 + tp_gross - s_tp) * (1.0 - f_tp)) / (1.0 + s_buy) - 1.0
    net_loss = 1.0 - ((1.0 - f_buy) * (1.0 - sl_gross - s_sl) * (1.0 - f_sl)) / (1.0 + s_buy)
    if net_loss <= 0:
        return {"net_win": net_win, "net_loss": 0.0, "net_rrr": 0.0, "breakeven_wr": 1.0}
    net_rrr = net_win / net_loss
    be_wr = (1.0 / (1.0 + net_rrr)) if net_rrr > 0 else 1.0
    friction_load_over_sl = ((net_loss - sl_gross) / sl_gross) if sl_gross > 0 else 0.0
    return {
        "net_win": net_win,
        "net_loss": net_loss,
        "net_rrr": net_rrr,
        "breakeven_wr": be_wr,
        "friction_load_over_sl": friction_load_over_sl,
    }


def hitung_blended_net_rrr_staged_tp(sl_gross, s_sl=EST_SL_SLIPPAGE_CORE,
                                     tranches=((0.40, SWING_TP1_PCT), (0.30, SWING_TP2_PCT), (0.30, SWING_TP3_PCT))):
    """Menghitung Blended Net Win & Blended Net RRR untuk Staged Partial TP (40%/30%/30%)."""
    blended_net_win = 0.0
    net_loss_ref = 0.0
    for weight, tp_g in tranches:
        m = hitung_matematika_rrr_eksak(tp_g, sl_gross, s_sl=s_sl)
        blended_net_win += weight * m["net_win"]
        net_loss_ref = m["net_loss"]
    net_rrr = (blended_net_win / net_loss_ref) if net_loss_ref > 0 else 0.0
    be_wr = (1.0 / (1.0 + net_rrr)) if net_rrr > 0 else 1.0
    return {
        "blended_net_win": blended_net_win,
        "net_loss": net_loss_ref,
        "net_rrr": net_rrr,
        "breakeven_wr": be_wr,
    }


def hitung_friction_adjusted_position_size(equity_idr, risk_pct, net_loss_pct, max_cap_idr):
    """
    Ukuran Posisi = (Modal * Risiko%) / SL Bersih
    Mengunci kerugian aktual pascabiaya & slippage presisi di batas risiko Rupiah.
    """
    if net_loss_pct <= 0 or equity_idr <= 0:
        return 0.0
    risk_idr = equity_idr * risk_pct
    raw_size = risk_idr / net_loss_pct
    return round(min(raw_size, max_cap_idr), 0)


def hitung_profit_bersih_grid_maker(spacing_pct):
    """Profit bersih per siklus Grid Maker-Maker (0.1111% beli + 0.3211% jual)."""
    return ((1.0 - FEE_MAKER_BUY) * (1.0 + spacing_pct) * (1.0 - FEE_MAKER_SELL)) - 1.0


# ==============================================================================
# BAGIAN 4: GATEWAY DUAL-KEY INDODAX (TRADE API V2 + LEGACY DEADMAN SWITCH)
# ==============================================================================
def http_get_json(url, headers=None, timeout=12):
    API_THROTTLER.wait()
    hdrs = {"User-Agent": "Mozilla/5.0 (IndodaxProQuant/2026)", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def muat_metadata_pairs_indodax():
    """
    Memuat price_increment & minimum order otomatis dari https://indodax.com/api/pairs
    sesuai keputusan rekayasa ke-5 File Analisis.
    """
    try:
        pairs = http_get_json("https://indodax.com/api/pairs", timeout=12)
        if not isinstance(pairs, list):
            return False
        by_id = {str(p.get("id", "")).lower(): p for p in pairs if isinstance(p, dict)}
        for coin, spec in UNIVERSE.items():
            pid = spec["indodax_pair"].replace("_", "")
            p = by_id.get(pid) or by_id.get(spec["indodax_pair"])
            if not p:
                continue
            prec = float(p.get("price_precision", 0) or 0)
            if prec > 0:
                spec["price_step"] = prec
            min_idr = float(p.get("trade_min_base_currency", 0) or 0)
            if min_idr > 0:
                spec["min_order_idr"] = max(MIN_INDODAX_PRO_ORDER_IDR, min_idr)
        return True
    except Exception as e:
        print(f"⚠️ [AUTO-LOAD /api/pairs FALLBACK DEFAULT]: {e}")
        return False


def bulatkan_harga(coin_or_spec, harga_idr, mode="nearest"):
    spec = UNIVERSE.get(coin_or_spec, USDT_PARK_SPEC) if isinstance(coin_or_spec, str) else coin_or_spec
    step = float(spec.get("price_step", 1.0) or 1.0)
    if mode == "floor":
        val = math.floor(harga_idr / step) * step
    elif mode == "ceil":
        val = math.ceil(harga_idr / step) * step
    else:
        val = round(harga_idr / step) * step
    return int(val) if step >= 1.0 else round(val, 4)


def format_qty(coin_or_spec, raw_qty):
    spec = UNIVERSE.get(coin_or_spec, USDT_PARK_SPEC) if isinstance(coin_or_spec, str) else coin_or_spec
    dec = int(spec.get("qty_decimals", 4))
    factor = 10 ** dec
    qty = math.floor(max(0.0, float(raw_qty)) * factor) / factor
    return int(qty) if dec == 0 else round(qty, dec)


def call_indodax_v2(endpoint, method="GET", params=None):
    """Konektor Resmi Indodax Trade API v2 (X-APIKEY + HMAC-SHA256)."""
    if params is None:
        params = {}
    if not INDODAX_API_KEY or not INDODAX_SECRET_KEY:
        return {"code": -1, "msg": "INDODAX_API_KEY / INDODAX_SECRET_KEY kosong"}

    API_THROTTLER.wait()
    p = dict(params)
    p["timestamp"] = int(time.time() * 1000)
    p["recvWindow"] = 15000
    query_str = urllib.parse.urlencode(p)
    sign = hmac.new(
        INDODAX_SECRET_KEY.encode("utf-8"),
        query_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    base_url = "https://api.indodax.com"
    url = f"{base_url}{endpoint}?{query_str}" if method in ("GET", "DELETE") else f"{base_url}{endpoint}"
    headers = {
        "X-APIKEY": INDODAX_API_KEY,
        "Sign": sign,
        "User-Agent": "Mozilla/5.0 (IndodaxProQuant/2026)",
    }
    body = None
    if method == "POST":
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = query_str.encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"code": e.code, "msg": str(e)}
    except Exception as e:
        return {"code": -1, "msg": str(e)}


def ping_legacy_deadman_switch(countdown_sec=DEADMAN_SWITCH_SECONDS):
    """
    Dual-Key Gateway: Memperbarui heartbeat countdownCancelAll via Legacy Trade API v1
    sehingga jika VPS mati/terputus > 15 menit, Indodax otomatis membatalkan semua open order.
    """
    if not LIVE_TRADING_ENABLED or not INDODAX_LEGACY_KEY or not INDODAX_LEGACY_SECRET:
        return False, "Deadman Switch nonaktif (simulasi / Legacy Key belum diisi)"
    API_THROTTLER.wait()
    payload = {
        "method": "cancelAllAfter",
        "nonce": int(time.time() * 1000),
        "countdown": int(countdown_sec),
    }
    encoded = urllib.parse.urlencode(payload).encode("utf-8")
    sign = hmac.new(INDODAX_LEGACY_SECRET.encode("utf-8"), encoded, hashlib.sha512).hexdigest()
    headers = {
        "Key": INDODAX_LEGACY_KEY,
        "Sign": sign,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 (IndodaxProQuant/2026)",
    }
    req = urllib.request.Request("https://indodax.com/tapi", data=encoded, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            return bool(res.get("success") == 1), str(res)
    except Exception as e:
        return False, str(e)


def hitung_modal_terpakai_bot(state):
    """Total Rupiah yang sedang digunakan oleh posisi Swing, Wide Grid, dan Parkir USDT bot."""
    used_swing = sum(float(p.get("remaining_capital_idr", 0.0)) for p in state.get("swing_positions", []))
    used_grid = sum(float(g.get("capital_idr", 0.0)) for g in state.get("grid_orders", []))
    used_usdt = float(state.get("usdt_parked_qty", 0.0)) * float(state.get("usdt_parked_avg_idr", 0.0))
    return used_swing + used_grid + used_usdt


def hitung_plafon_sisa_bot(state):
    """
    HARD CAP PLAFON MUTLAK MAX_BOT_CAPITAL_IDR:
    Mengunci agar bot TIDAK PERNAH menyentuh dana di luar MAX_BOT_CAPITAL_IDR
    meskipun saldo Rupiah asli di dompet Indodax Anda jauh lebih besar.
    """
    plafon_efektif = min(MAX_BOT_CAPITAL_IDR, float(state.get("current_equity_idr", MAX_BOT_CAPITAL_IDR)))
    return max(0.0, plafon_efektif - hitung_modal_terpakai_bot(state))


def ambil_dompet_indodax(state):
    dompet = {
        "connected": False,
        "wallet_idr_free_raw": 0.0,
        "idr_free": 0.0,   # Saldo IDR yang BOLEH dipakai bot (selalu dikunci <= sisa plafon MAX_BOT_CAPITAL_IDR)
        "idr_locked": 0.0,
        "coins_free": {},
        "coins_locked": {},
    }
    sisa_plafon = hitung_plafon_sisa_bot(state)
    if not LIVE_TRADING_ENABLED or not INDODAX_API_KEY:
        dompet["wallet_idr_free_raw"] = sisa_plafon
        dompet["idr_free"] = sisa_plafon
        dompet["coins_free"]["USDT"] = float(state.get("usdt_parked_qty", 0.0))
        return dompet

    res = call_indodax_v2("/api/v2/account", method="GET")
    if isinstance(res, dict) and "balances" in res:
        dompet["connected"] = True
        for b in res.get("balances", []):
            asset = str(b.get("asset", "")).upper()
            f_val = float(b.get("free", 0) or 0)
            l_val = float(b.get("locked", 0) or 0)
            if asset == "IDR":
                dompet["wallet_idr_free_raw"] = f_val
                dompet["idr_free"] = min(f_val, sisa_plafon)
                dompet["idr_locked"] = l_val
            else:
                dompet["coins_free"][asset] = f_val
                dompet["coins_locked"][asset] = l_val
    else:
        print(f"⚠️ [GAGAL CEK SALDO INDODAX V2]: {res}")
    return dompet


def is_order_ok(res):
    return isinstance(res, dict) and ("orderId" in res or res.get("simulasi") is True)


def kirim_order_indodax_pro(
    coin,
    side,
    qty,
    price_idr=0.0,
    order_type="LIMIT",
    maker_only=True,
):
    """
    Eksekusi order pada Indodax Pro Trade API v2:
    - Maker-First: timeInForce=MOC (Maker-Only Cancel) + selfTradePreventionMode=EXPIRE_TAKER.
      Jika MOC ditolak server (kode tertentu) atau order bersifat protektif buffer,
      menangani secara transparan tanpa diam-diam terkena Taker fee saat entry!
    """
    spec = UNIVERSE.get(coin, USDT_PARK_SPEC)
    qty_fmt = format_qty(spec, qty)
    if qty_fmt <= 0:
        return {"code": -2, "msg": "Quantity 0"}

    harga_bulat = bulatkan_harga(spec, price_idr) if price_idr > 0 else 0
    if not LIVE_TRADING_ENABLED:
        return {
            "simulasi": True,
            "orderId": f"SIM-{coin}-{int(time.time() * 1000) % 1000000}",
            "symbol": spec["v2_symbol"],
            "side": side.upper(),
            "type": order_type.upper(),
            "price": harga_bulat,
            "qty": qty_fmt,
            "timeInForce": "MOC" if (order_type.upper() == "LIMIT" and maker_only) else "GTC",
        }

    params = {
        "symbol": spec["v2_symbol"],
        "side": side.upper(),
        "type": order_type.upper(),
        "quantity": str(qty_fmt),
        "selfTradePreventionMode": "EXPIRE_TAKER",
    }
    if order_type.upper() == "LIMIT":
        params["price"] = str(harga_bulat)
        params["timeInForce"] = "MOC" if maker_only else "GTC"

    res = call_indodax_v2("/api/v2/order", method="POST", params=params)
    # Jika endpoint akun belum mengaktifkan parameter STP/MOC spesifik, fallback terkontrol
    msg_low = str(res.get("msg", "")).lower() if isinstance(res, dict) else ""
    if not is_order_ok(res) and ("selftradeprevention" in msg_low or "stp" in msg_low):
        params.pop("selfTradePreventionMode", None)
        res = call_indodax_v2("/api/v2/order", method="POST", params=params)
    if not is_order_ok(res) and maker_only and "timeinforce" in msg_low:
        params["timeInForce"] = "GTC"
        res = call_indodax_v2("/api/v2/order", method="POST", params=params)

    if isinstance(res, dict):
        res["qty"] = qty_fmt
    print(f"👉 [INDODAX V2 {side.upper()} {order_type.upper()} {'MOC' if maker_only else 'BUF'}] {spec['v2_symbol']} Qty={qty_fmt} @ Rp{harga_bulat:,.0f} -> {res}")
    return res


def cancel_order_indodax(coin, order_id):
    if not LIVE_TRADING_ENABLED or not order_id or str(order_id).startswith("SIM-"):
        return True, {"simulasi": True}
    spec = UNIVERSE.get(coin, USDT_PARK_SPEC)
    res = call_indodax_v2("/api/v2/order", method="DELETE", params={"symbol": spec["v2_symbol"], "orderId": str(order_id)})
    ok = isinstance(res, dict) and ("orderId" in res or str(res.get("status", "")).upper() == "CANCELED")
    return ok, res


def cek_status_order(coin, order_id):
    if not LIVE_TRADING_ENABLED or not order_id or str(order_id).startswith("SIM-"):
        return "SIM", {}
    spec = UNIVERSE.get(coin, USDT_PARK_SPEC)
    res = call_indodax_v2("/api/v2/order", method="GET", params={"symbol": spec["v2_symbol"], "orderId": str(order_id)})
    if isinstance(res, dict) and "status" in res:
        return str(res["status"]).upper(), res
    msg = str(res.get("msg", "")).lower() if isinstance(res, dict) else ""
    if "not found" in msg or int(res.get("code", 0) or 0) in (-2013, 404):
        return "NOT_FOUND", res
    return "UNKNOWN", res if isinstance(res, dict) else {}


def ambil_open_orders(coin):
    if not LIVE_TRADING_ENABLED:
        return True, []
    spec = UNIVERSE.get(coin, USDT_PARK_SPEC)
    res = call_indodax_v2("/api/v2/openOrders", method="GET", params={"symbol": spec["v2_symbol"]})
    if isinstance(res, list):
        return True, res
    if isinstance(res, dict) and isinstance(res.get("data"), list):
        return True, res["data"]
    return False, []


def eksekusi_sl_protektif_berbuffer(coin, qty, bid_price_idr):
    """
    Menangani ketiadaan Stop-Market di Indodax (Bagian 3 File Analisis):
    1. Mengirim Limit Sell dengan buffer agresif (-0.8%/-1.0% BTC/ETH, -2.2%/-2.5% XRP/SOL)
       agar terisi cepat layaknya Stop-Market namun terkendali dari slippage ekstrem.
    2. Jika dalam 3 detik belum FILLED (indikasi flash crash menembus buffer),
       batalkan & kirim MARKET SELL darurat agar kerugian tidak membengkak tak terbatas.
    """
    spec = UNIVERSE[coin]
    buffer_pct = spec["sl_buffer_pct"]
    limit_price = bulatkan_harga(spec, bid_price_idr * (1.0 - buffer_pct), mode="floor")

    res_lim = kirim_order_indodax_pro(coin, "SELL", qty, price_idr=limit_price, order_type="LIMIT", maker_only=False)
    if not is_order_ok(res_lim):
        res_mkt = kirim_order_indodax_pro(coin, "SELL", qty, price_idr=bid_price_idr, order_type="MARKET", maker_only=False)
        return is_order_ok(res_mkt), bid_price_idr * (1.0 - spec["sl_slippage_est"]), "MARKET_FALLBACK"

    if not LIVE_TRADING_ENABLED:
        est_fill = bid_price_idr * (1.0 - spec["sl_slippage_est"])
        return True, est_fill, f"BUFFERED_SL_SIM(-{buffer_pct*100:.1f}%)"

    oid = str(res_lim.get("orderId", ""))
    time.sleep(3.0)
    st, det = cek_status_order(coin, oid)
    if st == "FILLED":
        fill_p = float(det.get("price", 0) or 0) or bid_price_idr
        return True, fill_p, f"BUFFERED_LIMIT_FILLED(-{buffer_pct*100:.1f}%)"

    # Flash crash menembus buffer -> batalkan & paksa Market Sell sisa qty
    cancel_order_indodax(coin, oid)
    time.sleep(1.0)
    res_acc = call_indodax_v2("/api/v2/account", method="GET")
    sisa_free = qty
    if isinstance(res_acc, dict) and "balances" in res_acc:
        for b in res_acc["balances"]:
            if str(b.get("asset", "")).upper() == coin:
                sisa_free = format_qty(spec, float(b.get("free", 0) or 0))
                break
    if sisa_free <= 0:
        return True, bid_price_idr, "FILLED_ON_CANCEL_CHECK"

    res_mkt = kirim_order_indodax_pro(coin, "SELL", sisa_free, price_idr=bid_price_idr, order_type="MARKET", maker_only=False)
    return is_order_ok(res_mkt), bid_price_idr * (1.0 - buffer_pct), "EMERGENCY_MARKET_FALLBACK"


# ==============================================================================
# BAGIAN 5: DUAL-CHART DATA ENGINE (GLOBAL H4/DAILY + INDODAX DOM & ANTI-SPOOF)
# ==============================================================================
def ambil_tickers_indodax():
    """Mengambil harga Last, Best Bid (buy), Best Ask (sell), dan Spread Indodax Pro IDR."""
    out = {}
    data = http_get_json("https://indodax.com/api/tickers", timeout=12)
    tickers = data.get("tickers", {})
    all_keys = [(c, s["indodax_pair"]) for c, s in UNIVERSE.items()] + [("USDT", USDT_PARK_SPEC["indodax_pair"])]
    for coin, pair_key in all_keys:
        t = tickers.get(pair_key, {})
        if not t or "last" not in t:
            continue
        last_p = float(t["last"])
        bid_p = float(t.get("buy", last_p) or last_p)
        ask_p = float(t.get("sell", last_p) or last_p)
        spread = ((ask_p - bid_p) / bid_p) if bid_p > 0 else 0.0
        out[coin] = {
            "last": last_p,
            "bid": bid_p,
            "ask": ask_p,
            "spread_pct": max(0.0, spread),
            "vol_idr": float(t.get("vol_idr", 0) or 0),
            "high_24h": float(t.get("high", last_p) or last_p),
            "low_24h": float(t.get("low", last_p) or last_p),
        }
    return out


def validasi_dom_dan_antispoofing(coin, state, ticker_info):
    """
    Validasi Depth of Market (DOM) Indodax Pro (5-10 level teratas):
    - Menghitung Order Book Imbalance (rasio bid vs ask) dan total kedalaman IDR.
    - Uji ketahanan dinding bid 15-30 menit (anti-spoofing Kriptova):
      Dinding likuiditas asli bertahan >= 15 menit; dinding palsu lenyap dalam detik.
    """
    spec = UNIVERSE[coin]
    pair_clean = spec["indodax_pair"].replace("_", "")
    now_ts = time.time()
    result = {
        "ok": False,
        "spread_pct": ticker_info.get("spread_pct", 1.0),
        "bid_top10_idr": 0.0,
        "ask_top10_idr": 0.0,
        "imbalance": 1.0,
        "best_bid": ticker_info.get("bid", 0.0),
        "best_ask": ticker_info.get("ask", 0.0),
        "bid_wall_price": 0.0,
        "bid_wall_idr": 0.0,
        "wall_age_minutes": 0.0,
        "wall_verified": False,
        "reason": "",
    }
    try:
        depth = http_get_json(f"https://indodax.com/api/depth/{pair_clean}", timeout=10)
        buys = depth.get("buy", [])[:15]
        sells = depth.get("sell", [])[:15]
        if not buys or not sells:
            result["reason"] = "Order book kosong"
            return result

        best_bid = float(buys[0][0])
        best_ask = float(sells[0][0])
        spread = (best_ask - best_bid) / best_bid if best_bid > 0 else 1.0
        result["best_bid"] = best_bid
        result["best_ask"] = best_ask
        result["spread_pct"] = spread

        bid_top10 = [(float(p), float(q), float(p) * float(q)) for p, q in buys[:10]]
        ask_top10 = [(float(p), float(q), float(p) * float(q)) for p, q in sells[:10]]
        bid_sum = sum(x[2] for x in bid_top10)
        ask_sum = sum(x[2] for x in ask_top10)
        result["bid_top10_idr"] = bid_sum
        result["ask_top10_idr"] = ask_sum
        result["imbalance"] = round(bid_sum / max(1.0, ask_sum), 2)

        # Cari dinding bid terbesar di top-10
        wall_p, _, wall_idr = max(bid_top10, key=lambda x: x[2])
        result["bid_wall_price"] = wall_p
        result["bid_wall_idr"] = wall_idr

        # Uji ketahanan dinding bid lintas siklus (Anti-Spoofing 15-30 menit)
        tracker = state.setdefault("dom_wall_tracker", {})
        prev = tracker.get(coin)
        if prev and abs(wall_p - float(prev.get("price", 0))) / max(1.0, wall_p) <= 0.005:
            # Dinding bertahan di level yang sama (dalam toleransi 0.5%) dan volumenya masih >= 60%
            if wall_idr >= float(prev.get("idr", 0)) * 0.60:
                age_min = (now_ts - float(prev.get("first_seen_ts", now_ts))) / 60.0
                prev["last_seen_ts"] = now_ts
                prev["idr"] = max(wall_idr, float(prev.get("idr", 0)) * 0.8)
            else:
                # Dinding menyusut drastis -> potensi spoofing! Reset timer.
                age_min = 0.0
                tracker[coin] = {"price": wall_p, "idr": wall_idr, "first_seen_ts": now_ts, "last_seen_ts": now_ts}
        else:
            age_min = 0.0
            tracker[coin] = {"price": wall_p, "idr": wall_idr, "first_seen_ts": now_ts, "last_seen_ts": now_ts}

        result["wall_age_minutes"] = round(age_min, 1)
        result["wall_verified"] = (age_min >= DOM_SPOOF_MIN_PERSIST_MINUTES) or (bid_sum >= spec["min_depth_idr"])

        if spread > spec["max_spread_pct"]:
            result["reason"] = f"Spread {spread*100:.2f}% > maks {spec['max_spread_pct']*100:.2f}%"
            return result

        result["ok"] = True
        result["reason"] = (
            f"DOM OK | Spread:{spread*100:.2f}% | Imb:{result['imbalance']}x | "
            f"Bid10:Rp{bid_sum/1e6:.0f}jt | WallAge:{age_min:.0f}m"
        )
        return result
    except Exception as e:
        result["reason"] = f"DOM Error: {e}"
        return result


def ambil_ohlc_global(coin, interval="4h", limit=220):
    """
    Mengambil candlestick Global USD/USDT (H4 atau Daily) agar analisis struktur harga
    bebas distorsi kurs Rupiah dan wick palsu buku tipis Indodax.
    Urutan sumber: Binance Global -> Binance.US -> Kraken -> Fallback Indodax IDR.
    """
    spec = UNIVERSE[coin]
    # 1. Binance Global / Binance Data Vision (bebas geo-block untuk market data publik!)
    bn_interval = "4h" if interval == "4h" else "1d"
    for base in ("https://data-api.binance.vision", "https://api.binance.com"):
        try:
            url = f"{base}/api/v3/klines?symbol={spec['binance_symbol']}&interval={bn_interval}&limit={limit}"
            raw = http_get_json(url, timeout=10)
            if isinstance(raw, list) and len(raw) >= 60:
                return {
                    "source": "GLOBAL_BINANCE_USDT",
                    "opens": [float(r[1]) for r in raw],
                    "highs": [float(r[2]) for r in raw],
                    "lows": [float(r[3]) for r in raw],
                    "closes": [float(r[4]) for r in raw],
                    "vols": [float(r[5]) for r in raw],
                }
        except Exception:
            continue

    # 2. Kraken Public OHLC (interval dalam menit: 240 = 4H, 1440 = Daily)
    try:
        kr_int = 240 if interval == "4h" else 1440
        url = f"https://api.kraken.com/0/public/OHLC?pair={spec['kraken_pair']}&interval={kr_int}"
        res = http_get_json(url, timeout=10)
        res_obj = res.get("result", {})
        key = next((k for k in res_obj.keys() if k != "last"), None)
        if key and len(res_obj[key]) >= 60:
            rows = res_obj[key][-limit:]
            return {
                "source": "GLOBAL_KRAKEN_USD",
                "opens": [float(r[1]) for r in rows],
                "highs": [float(r[2]) for r in rows],
                "lows": [float(r[3]) for r in rows],
                "closes": [float(r[4]) for r in rows],
                "vols": [float(r[6]) for r in rows],
            }
    except Exception:
        pass

    # 3. Fallback darurat ke Indodax TradingView History v2 (tetap H4 / Daily)
    try:
        tf = "240" if interval == "4h" else "1D"
        now_ts = int(time.time())
        sec_per_bar = (4 * 3600) if interval == "4h" else 86400
        from_ts = now_ts - (limit * sec_per_bar)
        url = f"https://indodax.com/tradingview/history_v2?symbol={spec['v2_symbol']}&tf={tf}&from={from_ts}&to={now_ts}"
        raw = http_get_json(url, timeout=12)
        if isinstance(raw, list) and len(raw) >= 60:
            rows = raw[-limit:]
            return {
                "source": "INDODAX_FALLBACK",
                "opens": [float(r.get("Open", r.get("open", 0))) for r in rows],
                "highs": [float(r.get("High", r.get("high", 0))) for r in rows],
                "lows": [float(r.get("Low", r.get("low", 0))) for r in rows],
                "closes": [float(r.get("Close", r.get("close", 0))) for r in rows],
                "vols": [float(r.get("Volume", r.get("volume", 0)) or 0) for r in rows],
            }
    except Exception:
        pass
    return None


# ==============================================================================
# BAGIAN 6: INDIKATOR TEKNIKAL H4-DAILY (EMA, RSI+DIVERGENCE, MACD, ATR, STRUKTUR)
# ==============================================================================
def hitung_ema_series(values, period):
    if not values:
        return []
    k = 2.0 / (period + 1.0)
    ema = [float(values[0])]
    for v in values[1:]:
        ema.append((float(v) * k) + (ema[-1] * (1.0 - k)))
    return ema


def hitung_rsi_series(closes, period=14):
    n = len(closes)
    if n <= period:
        return [50.0] * n
    rsi = [50.0] * period
    gains, losses = [], []
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period
    rs = (avg_g / avg_l) if avg_l > 1e-12 else 999.0
    rsi.append(100.0 - (100.0 / (1.0 + rs)))
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        g = max(d, 0.0)
        l = max(-d, 0.0)
        avg_g = ((avg_g * (period - 1)) + g) / period
        avg_l = ((avg_l * (period - 1)) + l) / period
        rs = (avg_g / avg_l) if avg_l > 1e-12 else 999.0
        rsi.append(100.0 - (100.0 / (1.0 + rs)))
    return rsi


def hitung_macd(closes):
    ema12 = hitung_ema_series(closes, 12)
    ema26 = hitung_ema_series(closes, 26)
    macd_line = [a - b for a, b in zip(ema12, ema26)]
    signal_line = hitung_ema_series(macd_line, 9)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist


def hitung_atr_pct(highs, lows, closes, period=14):
    if len(closes) <= period + 1:
        return 0.025
    trs = []
    for i in range(-period, 0):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr = sum(trs) / float(period)
    return (atr / closes[-1]) if closes[-1] > 0 else 0.025


def deteksi_bullish_divergence(lows, rsi_series, lookback=18):
    """Mendeteksi Bullish Divergence (Price Lower Low, RSI Higher Low) pada H4."""
    if len(lows) < lookback + 5 or len(rsi_series) < lookback + 5:
        return False
    mid = lookback // 2
    seg_lama_l = lows[-lookback:-mid]
    seg_baru_l = lows[-mid:]
    seg_lama_r = rsi_series[-lookback:-mid]
    seg_baru_r = rsi_series[-mid:]
    return (min(seg_baru_l) < min(seg_lama_l) * 0.997) and (min(seg_baru_r) > min(seg_lama_r) + 2.0)


def deteksi_bearish_divergence(highs, rsi_series, lookback=18):
    """Mendeteksi Bearish Divergence (Price Higher High, RSI Lower High di area > 65-70)."""
    if len(highs) < lookback + 5 or len(rsi_series) < lookback + 5:
        return False
    mid = lookback // 2
    seg_lama_h = highs[-lookback:-mid]
    seg_baru_h = highs[-mid:]
    seg_lama_r = rsi_series[-lookback:-mid]
    seg_baru_r = rsi_series[-mid:]
    return (
        max(seg_baru_h) > max(seg_lama_h) * 1.003
        and max(seg_baru_r) < max(seg_lama_r) - 2.5
        and max(seg_lama_r) >= 65.0
    )


def cek_struktur_higher_low(lows, window=6):
    """Cek apakah struktur swing low terakhir membentuk Higher Low (HL utuh)."""
    if len(lows) < window * 3:
        return False
    low_sebelumnya = min(lows[-window * 3:-window * 2])
    low_terbaru = min(lows[-window * 2:-1])
    return low_terbaru > low_sebelumnya * 0.998


def deteksi_anomali_kurs_usdt(state, usdt_idr_price):
    """
    Memantau kurs USDT/IDR Indodax: mendeteksi lonjakan anomali kurs lokal
    (seperti kasus USDT/IDR melonjak tak wajar) agar tidak mendistorsi sinyal & parkir USDT.
    """
    hist = state.setdefault("usdt_idr_history", [])
    if usdt_idr_price > 0:
        hist.append(float(usdt_idr_price))
        state["usdt_idr_history"] = hist[-48:]
    if len(state["usdt_idr_history"]) < 5:
        return False, 0.0
    ema20_fx = hitung_ema_series(state["usdt_idr_history"], min(20, len(state["usdt_idr_history"])))[-1]
    dev_pct = (usdt_idr_price - ema20_fx) / ema20_fx if ema20_fx > 0 else 0.0
    is_anomaly = dev_pct > PLAN_B_USDT_MAX_PREMIUM_PCT
    return is_anomaly, dev_pct


# ==============================================================================
# BAGIAN 7: REGIME GATE (SAKELAR INDUK 4 REZIM: BULL / SIDEWAYS / SW-DOWN / BEAR)
# ==============================================================================
def evaluasi_rezim_pasar(btc_d, btc_h4, usdt_idr, fx_anomaly):
    """
    Sakelar Induk Anti-Overtrading (Lapisan 2 File Analisis):
    Mengklasifikasikan kondisi makro pasar dari grafik Global BTC Daily & H4:
      1. BULL               : BTC Daily > EMA50 & EMA100 (atau EMA50 > EMA100 & struktur HL utuh).
      2. SIDEWAYS           : Jarak EMA50-EMA100 sempit (< 2.5%), harga berkonsolidasi di pita EMA, tidak crash.
      3. SIDEWAYS_DOWNTREND : Harga di bawah EMA50 Daily namun masih tertahan di atas -10% dari EMA100
                              tanpa capitulation crash (Plan B Tahap 1 aktif).
      4. BEAR               : BTC di bawah EMA50 & EMA100 Daily, EMA50 < EMA100, momentum turun tajam
                              atau drawdown H4 dalam (Plan B Tahap 2 Risk-Off 80-90% Kas/USDT + Hedge Alert).
    """
    if not btc_d or not btc_h4:
        return {
            "regime": "BEAR",
            "reason": "Data Global BTC tidak tersedia -> Fail-Safe Mode BEAR Defensif",
            "btc_usd": 0.0,
            "btc_ema50_d": 0.0,
            "btc_ema100_d": 0.0,
            "btc_rsi_h4": 50.0,
            "usdt_idr": usdt_idr,
            "fx_anomaly": fx_anomaly,
        }

    c_d = btc_d["closes"]
    l_d = btc_d["lows"]
    c_h4 = btc_h4["closes"]
    h_h4 = btc_h4["highs"]
    l_h4 = btc_h4["lows"]

    price = c_d[-1]
    ema50_d = hitung_ema_series(c_d, min(50, len(c_d)))[-1]
    ema100_d = hitung_ema_series(c_d, min(100, len(c_d)))[-1]
    ema50_h4 = hitung_ema_series(c_h4, min(50, len(c_h4)))[-1]
    ema100_h4 = hitung_ema_series(c_h4, min(100, len(c_h4)))[-1]
    rsi_d = hitung_rsi_series(c_d, 14)[-1]
    rsi_h4 = hitung_rsi_series(c_h4, 14)[-1]
    atr_h4 = hitung_atr_pct(h_h4, l_h4, c_h4, 14)
    hl_daily = cek_struktur_higher_low(l_d, window=5)
    hl_h4 = cek_struktur_higher_low(l_h4, window=6)

    # Perubahan 24 jam (6 candle H4) untuk deteksi flash crash
    chg_24h = ((c_h4[-1] - c_h4[-7]) / c_h4[-7]) if len(c_h4) >= 7 else 0.0
    gap_ema_d = abs(ema50_d - ema100_d) / max(1e-9, ema100_d)
    dist_ema100_d = (price - ema100_d) / max(1e-9, ema100_d)

    # 1. Crash / Strong Bear Veto -> BEAR
    if chg_24h <= -0.065 or (price < ema50_d and price < ema100_d and ema50_d < ema100_d and (rsi_d < 42.0 or dist_ema100_d < -0.05)):
        regime = "BEAR"
        reason = (
            f"BTC Global (${price:,.0f}) di bawah EMA50(${ema50_d:,.0f}) & EMA100(${ema100_d:,.0f}) "
            f"| RSI D:{rsi_d:.1f} H4:{rsi_h4:.1f} | 24h:{chg_24h*100:+.1f}% -> PLAN B RISK-OFF 80-90% KAS/USDT"
        )
    # 2. Bullish Regime -> CORE SWING
    elif (price > ema50_d and price > ema100_d) or (ema50_d > ema100_d and price > ema100_d and (hl_daily or hl_h4) and rsi_h4 >= 45.0):
        # Cek apakah sebenarnya mendatar sempit di atas EMA
        if gap_ema_d < 0.015 and abs(price - ema50_h4) / max(1e-9, ema50_h4) < 0.015 and 42.0 <= rsi_h4 <= 58.0 and atr_h4 < 0.018:
            regime = "SIDEWAYS"
            reason = (
                f"BTC Global (${price:,.0f}) konsolidasi ketat di sekitar EMA50/100 (Gap:{gap_ema_d*100:.2f}%, ATR H4:{atr_h4*100:.2f}%) "
                f"-> WIDE GRID >= 2.0% (Maks 30% Modal)"
            )
        else:
            regime = "BULL"
            reason = (
                f"BTC Global (${price:,.0f}) > EMA50/100 Daily & Struktur Tren Naik (RSI H4:{rsi_h4:.1f}) "
                f"-> CORE SWING H4-DAILY (Partial TP 40/30/30)"
            )
    # 3. Sideways Downtrend -> PLAN B TAHAP 1
    elif price < ema50_d and (price < ema50_h4 or ema50_h4 < ema100_h4):
        regime = "SIDEWAYS_DOWNTREND"
        reason = (
            f"BTC Global (${price:,.0f}) melemah bertahap di bawah EMA50 (${ema50_d:,.0f}) tanpa crash tajam (RSI H4:{rsi_h4:.1f}) "
            f"-> PLAN B SIDEWAYS DOWNTREND (Defensif + Relief Bounce/Grid 3% <=15% Modal)"
        )
    # 4. Sideways Netral -> WIDE GRID 2.0%
    else:
        regime = "SIDEWAYS"
        reason = (
            f"BTC Global (${price:,.0f}) bergerak mendatar di antara EMA50/100 (RSI H4:{rsi_h4:.1f}, ATR H4:{atr_h4*100:.2f}%) "
            f"-> WIDE GRID >= 2.0% (Maks 30% Modal BTC/ETH)"
        )

    return {
        "regime": regime,
        "reason": reason,
        "btc_usd": price,
        "btc_ema50_d": ema50_d,
        "btc_ema100_d": ema100_d,
        "btc_ema50_h4": ema50_h4,
        "btc_rsi_d": round(rsi_d, 1),
        "btc_rsi_h4": round(rsi_h4, 1),
        "btc_atr_h4": round(atr_h4, 4),
        "btc_chg_24h": round(chg_24h, 4),
        "usdt_idr": usdt_idr,
        "fx_anomaly": fx_anomaly,
    }


# ==============================================================================
# BAGIAN 8: ANALISA SETUP SWING & PLAN B PER KOIN (DUAL-CHART + DOM)
# ==============================================================================
def analisa_setup_koin(coin, tickers, state, regime_info):
    """
    Menghasilkan sinyal trading deterministik berbasis analisis Dual-Chart H4-Daily
    dan validasi DOM Indodax Pro untuk 1 pasangan aset.
    """
    spec = UNIVERSE[coin]
    tk = tickers.get(coin)
    if not tk or tk["last"] <= 0:
        return None

    ohlc_h4 = ambil_ohlc_global(coin, "4h", limit=180)
    ohlc_d = ambil_ohlc_global(coin, "1d", limit=130)
    if not ohlc_h4 or not ohlc_d:
        return None

    dom = validasi_dom_dan_antispoofing(coin, state, tk)

    c_h4, h_h4, l_h4, v_h4 = ohlc_h4["closes"], ohlc_h4["highs"], ohlc_h4["lows"], ohlc_h4["vols"]
    c_d = ohlc_d["closes"]

    ema20_h4 = hitung_ema_series(c_h4, 20)[-1]
    ema50_h4 = hitung_ema_series(c_h4, 50)[-1]
    ema100_h4 = hitung_ema_series(c_h4, min(100, len(c_h4)))[-1]
    ema50_d = hitung_ema_series(c_d, min(50, len(c_d)))[-1]
    ema100_d = hitung_ema_series(c_d, min(100, len(c_d)))[-1]

    rsi_h4_s = hitung_rsi_series(c_h4, 14)
    rsi_h4 = rsi_h4_s[-1]
    rsi_d = hitung_rsi_series(c_d, 14)[-1]
    macd_l, macd_s, macd_h = hitung_macd(c_h4)
    atr_h4 = hitung_atr_pct(h_h4, l_h4, c_h4, 14)

    bull_div_h4 = deteksi_bullish_divergence(l_h4, rsi_h4_s)
    bear_div_h4 = deteksi_bearish_divergence(h_h4, rsi_h4_s)
    hl_h4 = cek_struktur_higher_low(l_h4, window=6)
    macd_bull_cross = (len(macd_h) >= 2) and (macd_h[-1] > 0) and (macd_h[-1] > macd_h[-2])
    macd_bear_cross = (len(macd_h) >= 2) and (macd_l[-1] < macd_s[-1]) and (macd_l[-2] >= macd_s[-2])

    # Konversi level support struktural H4 dari Global ke Indodax IDR secara proporsional
    # (menghindari distorsi kurs dengan memakai rasio jarak terhadap harga penutupan global)
    swing_low_recent = min(l_h4[-12:])
    dist_to_support = max(0.0, (c_h4[-1] - swing_low_recent) / max(1e-9, c_h4[-1]))
    # SL struktural minimal 3.5% - maksimal 6.0% (default 4.0% atau 1.6x ATR H4)
    sl_gross = min(MAX_STRUCTURAL_SL_PCT, max(MIN_STRUCTURAL_SL_PCT, max(dist_to_support + 0.008, atr_h4 * 1.6)))

    # Penentuan harga Limit Buy Maker-First: sedikit di atas support & WAJIB di bawah best_ask
    # serta menghindari angka bulat persis & zona abu-abu spread kosong.
    best_bid = dom["best_bid"] or tk["bid"]
    best_ask = dom["best_ask"] or tk["ask"]
    diskon_limit = min(0.006, max(0.0015, atr_h4 * 0.20))
    raw_entry_idr = min(best_bid, best_ask * 0.9985) * (1.0 - diskon_limit)
    # Hindari tepat angka bulat ratusan ribu pada BTC/ETH (taruh +1 atau +2 tick di atas)
    entry_idr = bulatkan_harga(spec, raw_entry_idr, mode="floor")
    if entry_idr >= best_ask:
        entry_idr = bulatkan_harga(spec, best_ask - spec["price_step"], mode="floor")

    # Kalkulasi Eksak Blended Net RRR (Staged Partial TP 40/30/30) dan Single Tranche (TP 12%)
    rrr_staged = hitung_blended_net_rrr_staged_tp(sl_gross, s_sl=spec["sl_slippage_est"])
    rrr_single = hitung_matematika_rrr_eksak(SINGLE_TRANCHE_TP_PCT, sl_gross, s_sl=spec["sl_slippage_est"])

    # Evaluasi Sinyal berdasarkan Rezim Pasar
    regime = regime_info["regime"]
    signal_type = "NONE"
    score = 0.0
    alasan = "Belum ada konfluensi H4-Daily"

    if regime == "BULL":
        # Core Swing Pullback / Trend Continuation (H4-Daily)
        tren_d_ok = (c_d[-1] > ema50_d) or (ema50_d > ema100_d)
        pullback_zone = (c_h4[-1] >= ema50_h4 * 0.985) and (c_h4[-1] <= ema20_h4 * 1.03)
        momentum_ok = (38.0 <= rsi_h4 <= 62.0) and (macd_bull_cross or c_h4[-1] > c_h4[-2])
        if tren_d_ok and (hl_h4 or pullback_zone) and momentum_ok and dom["ok"] and rrr_staged["net_rrr"] >= MIN_NET_RRR_REQUIRED:
            signal_type = "CORE_SWING"
            score = 70.0
            if hl_h4:
                score += 8.0
            if macd_bull_cross:
                score += 7.0
            if dom["imbalance"] >= 1.10:
                score += 6.0
            if dom["wall_verified"]:
                score += 5.0
            if spec["tier"] == "CORE":
                score += 4.0
            alasan = (
                f"CORE SWING H4-Daily | Net RRR Staged 1:{rrr_staged['net_rrr']:.2f} "
                f"| SL:{sl_gross*100:.1f}% | RSI H4:{rsi_h4:.1f} | {dom['reason']}"
            )
    elif regime == "SIDEWAYS_DOWNTREND" and PLAN_B_ENABLE_RELIEF_BOUNCE and coin == "BTC":
        # PLAN B TAHAP 1: Relief Bounce Counter-Trend ultra-selektif khusus BTC/IDR
        oversold_ekstrem = (rsi_h4 <= 30.0) or (rsi_d <= 33.0)
        reversal_confirm = bull_div_h4 or (c_h4[-1] > c_h4[-2] and macd_h[-1] > macd_h[-2])
        # Pada relief bounce, target konservatif TP +9% / SL -3.8% (cek Net RRR >= 2.00)
        sl_rb = MIN_STRUCTURAL_SL_PCT
        rrr_rb = hitung_matematika_rrr_eksak(0.095, sl_rb, s_sl=spec["sl_slippage_est"])
        if oversold_ekstrem and reversal_confirm and dom["ok"] and dom["wall_verified"] and dom["imbalance"] >= 1.25 and rrr_rb["net_rrr"] >= MIN_NET_RRR_REQUIRED:
            signal_type = "PLAN_B_RELIEF_BOUNCE"
            sl_gross = sl_rb
            rrr_single = rrr_rb
            score = 82.0 + (5.0 if bull_div_h4 else 0.0)
            alasan = (
                f"PLAN B RELIEF BOUNCE BTC | RSI H4:{rsi_h4:.1f} BullDiv:{bull_div_h4} "
                f"| Net RRR 1:{rrr_rb['net_rrr']:.2f} | WallTerverifikasi ({dom['wall_age_minutes']}m)"
            )

    return {
        "coin": coin,
        "tier": spec["tier"],
        "ohlc_source": ohlc_h4["source"],
        "last_idr": tk["last"],
        "bid_idr": best_bid,
        "ask_idr": best_ask,
        "dom": dom,
        "rsi_h4": round(rsi_h4, 1),
        "rsi_d": round(rsi_d, 1),
        "atr_h4": round(atr_h4, 4),
        "ema50_h4_usd": ema50_h4,
        "ema100_h4_usd": ema100_h4,
        "hl_h4": hl_h4,
        "bull_div_h4": bull_div_h4,
        "bear_div_h4": bear_div_h4,
        "macd_bear_cross": macd_bear_cross,
        "entry_idr": entry_idr,
        "sl_gross": sl_gross,
        "rrr_staged": rrr_staged,
        "rrr_single": rrr_single,
        "signal_type": signal_type,
        "score": round(score, 1),
        "reason": alasan,
    }


# ==============================================================================
# BAGIAN 9: OPSIONAL GEMINI AI ADVISORY (SHADOW / ENTRY FILTER ONLY - BUKAN SL!)
# ==============================================================================
def ambil_gemini_keys():
    keys = []
    raw = os.getenv("GEMINI_API_KEY", "").strip()
    for k in raw.replace(";", ",").split(","):
        if k.strip() and k.strip() not in keys:
            keys.append(k.strip())
    for i in (2, 3, 4, 5):
        kx = os.getenv(f"GEMINI_API_KEY_{i}", "").strip()
        if kx and kx not in keys:
            keys.append(kx)
    return keys


def konsultasi_gemini_entry_advisory(kandidat_list, regime_info):
    """
    Opsional filter konfirmasi entry ala tickernelz (shadow-only atau entry_filter).
    PENTING: Sesuai Analisis, AI TIDAK PERNAH boleh menonaktifkan Hard Risk Layer atau SL!
    """
    if GEMINI_ADVISORY_MODE == "off" or not kandidat_list:
        return {k["coin"]: (True, "Deterministik (Tanpa AI)") for k in kandidat_list}

    keys = ambil_gemini_keys()
    if not keys:
        return {k["coin"]: (True, "API Key Gemini kosong -> lanjut deterministik") for k in kandidat_list}

    lines = [
        f"[{k['coin']}] Tipe:{k['signal_type']} Skor:{k['score']} RSI_H4:{k['rsi_h4']} RSI_D:{k['rsi_d']} "
        f"NetRRR:1:{k['rrr_staged']['net_rrr']:.2f} ImbDOM:{k['dom']['imbalance']}x WallAge:{k['dom']['wall_age_minutes']}m"
        for k in kandidat_list
    ]
    prompt = (
        f"Anda adalah Senior Quant Risk Reviewer untuk Swing Trading H4-Daily di Indodax Pro IDR.\n"
        f"Rezim Makro: {regime_info['regime']} ({regime_info['reason']}).\n"
        f"Evaluasi kandidat entry berikut. Jawab 1 baris per koin: [KOIN]: YA atau TUNDA - alasan maks 10 kata.\n"
        + "\n".join(lines)
    )

    teks = None
    for model in ("gemini-3-flash-preview", "gemini-2.5-flash"):
        for api_key in keys:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1, "maxOutputTokens": 512}}
            try:
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=18) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                parts = res.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                teks = "\n".join(str(p.get("text", "")).strip() for p in parts if "text" in p and not p.get("thought"))
                if teks:
                    break
            except Exception:
                continue
        if teks:
            break

    out = {}
    for k in kandidat_list:
        c = k["coin"]
        approved = True
        note = "AI Fallback -> Deterministik"
        if teks:
            for ln in teks.splitlines():
                if f"[{c}]" in ln or ln.upper().startswith(c):
                    kanan = ln.split(":", 1)[-1].strip()
                    ai_ya = kanan.upper().startswith("YA") and "TUNDA" not in kanan.upper()[:18]
                    if GEMINI_ADVISORY_MODE == "shadow":
                        approved = True
                        note = f"[SHADOW AI: {'YA' if ai_ya else 'TUNDA'}] {kanan[:70]}"
                    else:
                        approved = ai_ya
                        note = f"[AI FILTER] {kanan[:70]}"
                    break
        out[c] = (approved, note)
    return out


# ==============================================================================
# BAGIAN 10: HARD RISK LAYER, RECORD PNL & PROFIT SKIMMING TRACKER
# ==============================================================================
def cek_hard_risk_gate(state):
    """
    Lapisan Proteksi Deterministik (tidak dapat dilewati oleh sinyal/AI mana pun):
    1. Max Total Drawdown 10% -> Hard Kill Switch.
    2. Max Daily Loss 1.5% -> Circuit Breaker 24 jam (persisten pasca-restart!).
    """
    now_ts = time.time()
    equity = float(state.get("current_equity_idr", MAX_BOT_CAPITAL_IDR))
    peak = max(float(state.get("peak_equity_idr", MAX_BOT_CAPITAL_IDR)), equity)
    state["peak_equity_idr"] = peak

    dd_pct = (peak - equity) / max(1.0, peak)
    if state.get("kill_switch_active") or dd_pct >= MAX_TOTAL_DRAWDOWN_PCT:
        state["kill_switch_active"] = True
        state["kill_switch_reason"] = f"Max Drawdown {dd_pct*100:.2f}% >= {MAX_TOTAL_DRAWDOWN_PCT*100:.1f}%"
        return False, f"🛑 [HARD KILL SWITCH AKTIF] {state['kill_switch_reason']} — Semua entry baru dimatikan!"

    if float(state.get("circuit_breaker_until_ts", 0.0)) > now_ts:
        sisa_jam = (float(state["circuit_breaker_until_ts"]) - now_ts) / 3600.0
        return False, f"⏸️ [CIRCUIT BREAKER PERSISTEN] Aktif sisa {sisa_jam:.1f} jam (rugi harian tercapai)."

    daily_loss_limit = -peak * MAX_DAILY_LOSS_PCT
    if float(state.get("realized_pnl_today_idr", 0.0)) <= daily_loss_limit:
        state["circuit_breaker_until_ts"] = now_ts + (24.0 * 3600.0)
        return False, (
            f"🚨 [CIRCUIT BREAKER TERPICU] Rugi hari ini Rp{state['realized_pnl_today_idr']:,.0f} "
            f"melewati batas Rp{daily_loss_limit:,.0f}. Entry dikunci 24 jam!"
        )
    return True, "HARD_RISK_OK"


def catat_realized_pnl(state, coin, pnl_idr, is_sl=False):
    state["realized_pnl_today_idr"] = round(float(state.get("realized_pnl_today_idr", 0.0)) + pnl_idr, 0)
    state["realized_pnl_quarter_idr"] = round(float(state.get("realized_pnl_quarter_idr", 0.0)) + pnl_idr, 0)
    state["current_equity_idr"] = round(max(0.0, float(state.get("current_equity_idr", MAX_BOT_CAPITAL_IDR)) + pnl_idr), 0)
    if state["current_equity_idr"] > float(state.get("peak_equity_idr", 0.0)):
        state["peak_equity_idr"] = state["current_equity_idr"]
    state["completed_trades_total"] = int(state.get("completed_trades_total", 0)) + 1
    if pnl_idr >= 0:
        state["wins_total"] = int(state.get("wins_total", 0)) + 1
    else:
        state["losses_total"] = int(state.get("losses_total", 0)) + 1
        if is_sl and coin:
            state.setdefault("sl_cooldown_until", {})[coin] = time.time() + (SL_COOLDOWN_HOURS * 3600.0)


def cek_rekomendasi_profit_skimming(state):
    """Mengecek apakah profit kuartalan layak dilakukan skimming 30% ke hardware cold wallet."""
    q_pnl = float(state.get("realized_pnl_quarter_idr", 0.0))
    ambang = MAX_BOT_CAPITAL_IDR * 0.05  # minimal +5% profit kuartalan
    if q_pnl >= ambang:
        saran_tarik = round(q_pnl * PROFIT_SKIMMING_QUARTERLY_PCT, 0)
        return (
            f"💰 [REKOMENDASI PROFIT SKIMMING KUARTALAN {state.get('current_quarter')}] "
            f"Profit kuartal Rp{q_pnl:,.0f} -> Tarik {PROFIT_SKIMMING_QUARTERLY_PCT*100:.0f}% "
            f"(Rp{saran_tarik:,.0f}) ke Hardware Cold Wallet (Ledger/Trezor)."
        )
    return None


# ==============================================================================
# BAGIAN 11: VIRTUAL OCO STATE MACHINE (SWING PARTIAL TP + FEE-ADJUSTED BE + SL)
# ==============================================================================
def _selesaikan_tp_terisi(state, pos, coin, spec, stage, sell_p, qty_sold, cap_sold, fee_exit, regime_info, tag_custom=""):
    """Mencatat PnL & memperbarui status posisi hanya SETELAH order TP benar-benar FILLED."""
    entry_p = float(pos["entry_price_idr"])
    net_ret = ((1.0 - FEE_MAKER_BUY) * (sell_p / entry_p) * (1.0 - fee_exit)) - 1.0
    pnl_idr = round(cap_sold * net_ret, 0)
    catat_realized_pnl(state, coin, pnl_idr, is_sl=False)

    pos["remaining_qty"] = format_qty(spec, max(0.0, float(pos["remaining_qty"]) - qty_sold))
    pos["remaining_capital_idr"] = round(max(0.0, float(pos["remaining_capital_idr"]) - cap_sold), 0)
    pos.pop("pending_tp_order", None)

    closed = False
    if stage == "SINGLE":
        closed = True
        msg = f"🎉 [CORE SWING TP TERISI] {coin} terjual Maker @ Rp{sell_p:,.0f} (Net:+{net_ret*100:.2f}% | +Rp{pnl_idr:,.0f})"
        action_db = "TP_FULL"
    elif stage == "TP1":
        pos["tp1_done"] = True
        be_price = bulatkan_harga(spec, entry_p * (1.0 + FEE_ADJUSTED_BE_PCT), mode="ceil")
        pos["sl_price_idr"] = max(float(pos["sl_price_idr"]), be_price)
        pos["be_armed"] = True
        msg = (
            f"🎯 [PARTIAL TP1 40% TERISI] {coin} terjual @ Rp{sell_p:,.0f} (+Rp{pnl_idr:,.0f}) | "
            f"SL sisa 60% digeser ke Fee-Adjusted BE Rp{pos['sl_price_idr']:,.0f} (+0.60%)!"
        )
        action_db = "PARTIAL_TP1"
    elif stage == "TP2":
        pos["tp2_done"] = True
        pos["sl_price_idr"] = max(float(pos["sl_price_idr"]), float(pos["tp1_price_idr"]))
        msg = (
            f"🎯 [PARTIAL TP2 30% TERISI] {coin} terjual @ Rp{sell_p:,.0f} (+Rp{pnl_idr:,.0f}) | "
            f"Trailing Floor Runner 30% naik ke TP1 Rp{pos['sl_price_idr']:,.0f}!"
        )
        action_db = "PARTIAL_TP2"
    else:
        closed = True
        tag = tag_custom or "PARTIAL TP3 30% PENUH"
        msg = f"🏆 [{tag} TERISI] {coin} tutup sisa 30% @ Rp{sell_p:,.0f} (+Rp{pnl_idr:,.0f})!"
        action_db = tag

    if pos["remaining_qty"] <= 0:
        closed = True

    log_audit_db(
        regime_info["regime"], coin, pos["strategy"], action_db,
        sell_p, qty_sold, cap_sold, pnl_idr, pos.get("est_net_rrr", 0.0), msg,
    )
    return closed, msg


def kelola_virtual_oco_swing(state, analisa_map, tickers, dompet, regime_info):
    """
    Virtual OCO State Machine v2 (Anti-Balance Lock & Verifikasi Fill LIVE Presisi):
    - WAITING_BUY: di mode LIVE hanya promosi ke ACTIVE_OCO berdasarkan status asli order
      (FILLED / PARTIALLY_FILLED terverifikasi) — tidak pernah salah baca saldo pribadi di dompet!
    - ACTIVE_OCO:
      * Memantau pending_tp_order (order Limit Sell TP yang sedang antre) hingga benar-benar FILLED
        sebelum mencatat PnL & menutup slot.
      * Jika harga berbalik menyentuh SL saat Limit Sell TP masih antre, langsung cancel TP dulu
        agar koin bebas, lalu eksekusi Stop-Limit Ber-Buffer Protektif (fallback Market).
      * Jika harga mundur > 1.5% di bawah antrean TP > 10 menit, otomatis cancel TP agar koin
        tidak terkunci (bebas balance lock) dan kembali dikawal Virtual OCO.
    """
    logs, tx_logs = [], []
    remaining = []
    now_ts = time.time()

    for pos in state.get("swing_positions", []):
        coin = pos["coin"]
        spec = UNIVERSE[coin]
        tk = tickers.get(coin)
        info = analisa_map.get(coin)
        if not tk:
            remaining.append(pos)
            continue

        last_p = tk["last"]
        bid_p = tk["bid"]
        ask_p = tk["ask"]
        entry_p = float(pos["entry_price_idr"])

        # --- FASE 1: WAITING_BUY (Antrean Limit Maker MOC) ---
        if pos["status"] == "WAITING_BUY":
            umur_jam = (now_ts - float(pos.get("created_ts", now_ts))) / 3600.0
            terisi = False
            if LIVE_TRADING_ENABLED and dompet["connected"]:
                st_ord, det = cek_status_order(coin, pos.get("buy_order_id"))
                exec_qty = float(det.get("executedQty", det.get("executed_qty", 0)) or 0)
                if st_ord == "FILLED":
                    terisi = True
                    if float(det.get("price", 0) or 0) > 0:
                        pos["entry_price_idr"] = float(det["price"])
                        entry_p = pos["entry_price_idr"]
                    if exec_qty > 0:
                        pos["initial_qty"] = format_qty(spec, exec_qty)
                        pos["remaining_qty"] = pos["initial_qty"]
                        pos["initial_capital_idr"] = round(pos["initial_qty"] * entry_p, 0)
                        pos["remaining_capital_idr"] = pos["initial_capital_idr"]
                elif st_ord in ("CANCELED", "EXPIRED", "REJECTED", "NOT_FOUND"):
                    # Jika sempat terisi sebagian sebelum cancel/expire, promosikan porsi yang terisi
                    if exec_qty > 0 and (exec_qty * last_p >= MIN_INDODAX_PRO_ORDER_IDR):
                        terisi = True
                        pos["initial_qty"] = format_qty(spec, exec_qty)
                        pos["remaining_qty"] = pos["initial_qty"]
                        pos["initial_capital_idr"] = round(pos["initial_qty"] * entry_p, 0)
                        pos["remaining_capital_idr"] = pos["initial_capital_idr"]
                    else:
                        logs.append(f"🧹 [MOC ORDER {st_ord}] Order beli {coin} #{pos.get('buy_order_id')} tidak lagi aktif.")
                        continue
            else:
                if last_p <= entry_p:
                    terisi = True

            if terisi:
                pos["status"] = "ACTIVE_OCO"
                pos["filled_ts"] = now_ts
                pos["highest_idr"] = max(entry_p, last_p)
                msg = (
                    f"✅ [SWING TERISI - VIRTUAL OCO AKTIF] {coin} ({pos['strategy']}) @ Rp{entry_p:,.0f} "
                    f"Qty:{pos['remaining_qty']} | SL:Rp{pos['sl_price_idr']:,.0f} | TP1:Rp{pos['tp1_price_idr']:,.0f}"
                )
                logs.append(msg)
                tx_logs.append(msg)
                log_audit_db(
                    regime_info["regime"], coin, pos["strategy"], "BUY_FILLED",
                    entry_p, pos["remaining_qty"], pos["remaining_capital_idr"], 0.0, pos.get("est_net_rrr", 0.0), msg,
                )
                remaining.append(pos)
                continue

            # Batalkan antrean beli jika rezim berubah menjadi BEAR atau kadaluarsa > 12 jam (3 candle H4)
            if regime_info["regime"] == "BEAR" or umur_jam >= 12.0:
                cancel_order_indodax(coin, pos.get("buy_order_id"))
                # Cek terakhir di mode LIVE apakah sempat terisi sebagian sebelum dibatalkan
                if LIVE_TRADING_ENABLED and dompet["connected"]:
                    st_chk, det_chk = cek_status_order(coin, pos.get("buy_order_id"))
                    eq_chk = float(det_chk.get("executedQty", det_chk.get("executed_qty", 0)) or 0)
                    if eq_chk * last_p >= MIN_INDODAX_PRO_ORDER_IDR:
                        pos["status"] = "ACTIVE_OCO"
                        pos["filled_ts"] = now_ts
                        pos["initial_qty"] = format_qty(spec, eq_chk)
                        pos["remaining_qty"] = pos["initial_qty"]
                        pos["initial_capital_idr"] = round(pos["initial_qty"] * entry_p, 0)
                        pos["remaining_capital_idr"] = pos["initial_capital_idr"]
                        msg = f"✅ [PARTIAL BUY TERISI SEBELUM BATAL] {coin} Qty:{pos['remaining_qty']} -> lanjut Virtual OCO."
                        logs.append(msg)
                        tx_logs.append(msg)
                        remaining.append(pos)
                        continue
                msg = f"🔄 [BATAL ANTREAN BELI] {coin} dibatalkan (Rezim:{regime_info['regime']}, Umur:{umur_jam:.1f}j)."
                logs.append(msg)
                tx_logs.append(msg)
                continue

            logs.append(f"⏳ [ANTRE MAKER MOC {umur_jam:.1f}j] {coin} Limit Buy @ Rp{entry_p:,.0f} (Skrg: Rp{last_p:,.0f})")
            remaining.append(pos)
            continue

        # --- FASE 2: ACTIVE_OCO (Pemantauan Pending TP, SL Protektif, Staged Partial TP & Runner) ---
        if pos["status"] == "ACTIVE_OCO":
            pos["highest_idr"] = max(float(pos.get("highest_idr", entry_p)), last_p)
            qty_avail = float(pos["remaining_qty"])
            sl_p = float(pos["sl_price_idr"])
            pnl_pct_now = (bid_p - entry_p) / entry_p

            # 0. VERIFIKASI ANTREAN LIMIT SELL TP YANG SEDANG AKTIF (KHUSUS MODE LIVE)
            pto = pos.get("pending_tp_order")
            if pto and LIVE_TRADING_ENABLED and dompet["connected"]:
                st_tp, det_tp = cek_status_order(coin, pto.get("order_id"))
                if st_tp == "FILLED":
                    fill_p = float(det_tp.get("price", 0) or 0) or float(pto["price_idr"])
                    fee_ex = FEE_MAKER_SELL if pto.get("maker", True) else FEE_TAKER_SELL
                    closed, msg = _selesaikan_tp_terisi(
                        state, pos, coin, spec, pto["stage"], fill_p,
                        float(pto["qty"]), float(pto["capital_idr"]), fee_ex, regime_info, pto.get("tag", ""),
                    )
                    logs.append(msg)
                    tx_logs.append(msg)
                    if closed:
                        continue
                    qty_avail = float(pos["remaining_qty"])
                    pto = None
                elif st_tp in ("CANCELED", "EXPIRED", "REJECTED", "NOT_FOUND"):
                    logs.append(f"🔄 [ANTREAN TP {st_tp}] Order TP #{pto.get('order_id')} {coin} tidak aktif lagi, kembali kawal Virtual OCO.")
                    pos.pop("pending_tp_order", None)
                    pto = None
                else:
                    # Order TP masih NEW / PARTIALLY_FILLED:
                    # Prioritas 1: Jika harga berbalik menyentuh SL -> BATALKAN TP dulu agar koin terbuka untuk SL!
                    umur_tp_menit = (now_ts - float(pto.get("placed_ts", now_ts))) / 60.0
                    harga_mundur_jauh = last_p < float(pto["price_idr"]) * 0.985 and umur_tp_menit >= 10.0
                    if bid_p <= sl_p or last_p <= sl_p or harga_mundur_jauh:
                        cancel_order_indodax(coin, pto.get("order_id"))
                        time.sleep(1.0)
                        alasan_c = "SL TERSENTUH" if (bid_p <= sl_p or last_p <= sl_p) else "HARGA MUNDUR >1.5% (ANTI-LOCK)"
                        logs.append(f"🔓 [BATAL ANTREAN TP - {alasan_c}] Order TP #{pto.get('order_id')} {coin} dilepas.")
                        pos.pop("pending_tp_order", None)
                        pto = None
                    else:
                        logs.append(
                            f"⏳ [MENUNGGU TP {pto['stage']} TERISI #{pto.get('order_id')}] {coin} "
                            f"Limit Sell Qty:{pto['qty']} @ Rp{pto['price_idr']:,.0f} (Skrg: Rp{last_p:,.0f})"
                        )
                        remaining.append(pos)
                        continue

            # Sinkronisasi ketersediaan saldo koin di dompet (cek free + locked agar tidak salah anggap kosong)
            if LIVE_TRADING_ENABLED and dompet["connected"]:
                k_free = dompet["coins_free"].get(coin, 0.0)
                k_locked = dompet["coins_locked"].get(coin, 0.0)
                if (k_free + k_locked) * last_p < 5000.0:
                    logs.append(f"🧹 [SYNC POSISI KOSONG] {coin} saldo 0 di dompet, menutup slot Virtual OCO.")
                    continue
                if k_free > 0:
                    qty_avail = format_qty(spec, min(qty_avail, k_free))
                    pos["remaining_qty"] = qty_avail

            # A. CEK STOP LOSS (PRIORITAS TERTINGGI - 100% DETERMINISTIK)
            if bid_p <= sl_p or last_p <= sl_p:
                ok_sl, fill_sl, mode_sl = eksekusi_sl_protektif_berbuffer(coin, qty_avail, bid_p)
                if ok_sl:
                    gross_ret = (fill_sl - entry_p) / entry_p
                    net_ret = ((1.0 - FEE_MAKER_BUY) * (1.0 + gross_ret) * (1.0 - FEE_TAKER_SELL)) - 1.0
                    pnl_idr = round(float(pos["remaining_capital_idr"]) * net_ret, 0)
                    is_true_loss = pnl_idr < 0
                    catat_realized_pnl(state, coin, pnl_idr, is_sl=is_true_loss)
                    label = "FEE-ADJUSTED BE STOP" if pos.get("tp1_done") and not is_true_loss else "STOP LOSS PROTEKTIF"
                    msg = (
                        f"🛡️ [{label} | {mode_sl}] {coin} keluar @ Rp{fill_sl:,.0f} "
                        f"(Net:{net_ret*100:+.2f}% | PnL:Rp{pnl_idr:,.0f})"
                    )
                    logs.append(msg)
                    tx_logs.append(msg)
                    log_audit_db(
                        regime_info["regime"], coin, pos["strategy"], label,
                        fill_sl, qty_avail, pos["remaining_capital_idr"], pnl_idr, pos.get("est_net_rrr", 0.0), msg,
                    )
                    continue

            # Helper kirim TP: di Simulasi langsung selesai; di LIVE masuk status pending_tp_order sampai FILLED!
            def _proses_kirim_tp(stage, qty_sell, cap_sell, sell_p, maker_only=True, tag_custom=""):
                res_tp = kirim_order_indodax_pro(coin, "SELL", qty_sell, price_idr=sell_p, order_type="LIMIT", maker_only=maker_only)
                if not is_order_ok(res_tp):
                    return False, False, f"⚠️ [GAGAL PASANG TP {stage}] {coin}: {res_tp}"
                if not LIVE_TRADING_ENABLED:
                    fee_ex = FEE_MAKER_SELL if maker_only else FEE_TAKER_SELL
                    closed_f, msg_f = _selesaikan_tp_terisi(
                        state, pos, coin, spec, stage, sell_p, qty_sell, cap_sell, fee_ex, regime_info, tag_custom,
                    )
                    return True, closed_f, msg_f
                # Mode LIVE: simpan sebagai pending_tp_order (JANGAN catat PnL sebelum FILLED!)
                oid_tp = str(res_tp.get("orderId"))
                pos["pending_tp_order"] = {
                    "order_id": oid_tp,
                    "stage": stage,
                    "qty": qty_sell,
                    "price_idr": sell_p,
                    "capital_idr": cap_sell,
                    "maker": maker_only,
                    "tag": tag_custom,
                    "placed_ts": now_ts,
                }
                msg_wait = (
                    f"📌 [ANTREAN TP {stage} DIPASANG #{oid_tp}] {coin} Limit Sell Qty:{qty_sell} @ Rp{sell_p:,.0f} "
                    f"(Menunggu konfirmasi FILLED dari Indodax)"
                )
                return True, False, msg_wait

            # B. CEK STAGED PARTIAL TAKE PROFIT (MAKER-FIRST)
            use_staged = bool(pos.get("use_staged_tp", True))

            if not use_staged:
                # Mode Single-Tranche (untuk modal kecil agar tiap jual >= Rp25.000 Indodax Pro)
                if not pos.get("be_armed") and pnl_pct_now >= 0.065:
                    be_price = bulatkan_harga(spec, entry_p * (1.0 + FEE_ADJUSTED_BE_PCT), mode="ceil")
                    if be_price > pos["sl_price_idr"]:
                        pos["sl_price_idr"] = be_price
                        pos["be_armed"] = True
                        logs.append(f"🔒 [FEE-ADJUSTED BE +0.60%] {coin} SL digeser ke Rp{be_price:,.0f} (bebas rugi biaya+pajak).")

                if ask_p >= float(pos["tp1_price_idr"]) or last_p >= float(pos["tp1_price_idr"]):
                    sell_p = bulatkan_harga(spec, max(ask_p, float(pos["tp1_price_idr"])), mode="ceil")
                    ok_tp, closed_tp, msg_tp = _proses_kirim_tp(
                        "SINGLE", qty_avail, float(pos["remaining_capital_idr"]), sell_p, maker_only=True,
                    )
                    logs.append(msg_tp)
                    if ok_tp:
                        tx_logs.append(msg_tp)
                    if closed_tp:
                        continue
            else:
                # Mode Staged Partial TP: 40% TP1 (+8%) -> 30% TP2 (+14%) -> 30% TP3 (+22% / Reversal)
                if not pos.get("tp1_done") and last_p >= float(pos["tp1_price_idr"]):
                    qty_tp1 = min(format_qty(spec, float(pos["initial_qty"]) * 0.40), qty_avail)
                    sell_p = bulatkan_harga(spec, max(ask_p, float(pos["tp1_price_idr"])), mode="ceil")
                    if qty_tp1 * sell_p >= MIN_INDODAX_PRO_ORDER_IDR:
                        cap_tp1 = round(float(pos["initial_capital_idr"]) * (qty_tp1 / max(1e-9, float(pos["initial_qty"]))), 0)
                        ok_tp, closed_tp, msg_tp = _proses_kirim_tp("TP1", qty_tp1, cap_tp1, sell_p, maker_only=True)
                        logs.append(msg_tp)
                        if ok_tp:
                            tx_logs.append(msg_tp)
                        if closed_tp:
                            continue
                        qty_avail = float(pos["remaining_qty"])

                if pos.get("tp1_done") and not pos.get("tp2_done") and not pos.get("pending_tp_order") and last_p >= float(pos["tp2_price_idr"]) and qty_avail > 0:
                    qty_tp2 = min(format_qty(spec, float(pos["initial_qty"]) * 0.30), qty_avail)
                    sell_p = bulatkan_harga(spec, max(ask_p, float(pos["tp2_price_idr"])), mode="ceil")
                    if qty_tp2 * sell_p >= MIN_INDODAX_PRO_ORDER_IDR:
                        cap_tp2 = round(float(pos["initial_capital_idr"]) * (qty_tp2 / max(1e-9, float(pos["initial_qty"]))), 0)
                        ok_tp, closed_tp, msg_tp = _proses_kirim_tp("TP2", qty_tp2, cap_tp2, sell_p, maker_only=True)
                        logs.append(msg_tp)
                        if ok_tp:
                            tx_logs.append(msg_tp)
                        if closed_tp:
                            continue
                        qty_avail = float(pos["remaining_qty"])

                reversal_exit = bool(
                    pos.get("tp2_done")
                    and info
                    and ((info["rsi_h4"] >= 70.0 and info["bear_div_h4"]) or (info["macd_bear_cross"] and pnl_pct_now >= 0.12))
                )
                if pos.get("tp2_done") and not pos.get("pending_tp_order") and qty_avail > 0 and (last_p >= float(pos["tp3_price_idr"]) or reversal_exit):
                    sell_p = bulatkan_harga(spec, max(bid_p, last_p), mode="floor")
                    tag = "RUNNER REVERSAL EXIT (RSI/MACD)" if reversal_exit else "PARTIAL TP3 30% PENUH"
                    ok_tp, closed_tp, msg_tp = _proses_kirim_tp(
                        "TP3", qty_avail, float(pos["remaining_capital_idr"]), sell_p,
                        maker_only=not reversal_exit, tag_custom=tag,
                    )
                    logs.append(msg_tp)
                    if ok_tp:
                        tx_logs.append(msg_tp)
                    if closed_tp:
                        continue

            if pos["remaining_qty"] <= 0:
                continue

            tp1_label = "✅" if pos.get("tp1_done") else f"Rp{pos['tp1_price_idr']:,.0f}"
            logs.append(
                f"📈 [KAWAL OCO {pos['strategy']}] {coin} | Entry:Rp{entry_p:,.0f} | Bid:Rp{bid_p:,.0f} ({pnl_pct_now*100:+.2f}%) "
                f"| SL:Rp{pos['sl_price_idr']:,.0f} | TP1:{tp1_label}"
            )
            remaining.append(pos)

    state["swing_positions"] = remaining
    return logs, tx_logs


# ==============================================================================
# BAGIAN 12: WIDE GRID ENGINE (SIDEWAYS >= 2.0% & PLAN B DEFENSIVE GRID 3.0%)
# ==============================================================================
def kelola_wide_grid_engine(state, tickers, dompet, regime_info, hard_risk_ok):
    """
    Wide Grid Maker-Only (Lapisan 2 & 4 File Analisis):
    - Rezim SIDEWAYS: Maksimal 30% modal di BTC/IDR & ETH/IDR, jarak grid >= 2.0% (+1.56% bersih/siklus).
    - Rezim SIDEWAYS_DOWNTREND (Plan B): Maksimal 15% modal khusus BTC/IDR, jarak grid 3.0% (+2.55% bersih/siklus).
    - Rezim BEAR: Bekukan pembelian grid baru; jaga hard stop floor agar tidak terseret crash.
    """
    logs, tx_logs = [], []
    regime = regime_info["regime"]
    active_grids = []

    # 1. Kawal order Grid yang sedang berjalan (baik BUY maupun SELL TP)
    for g in state.get("grid_orders", []):
        coin = g["coin"]
        spec = UNIVERSE[coin]
        tk = tickers.get(coin)
        if not tk:
            active_grids.append(g)
            continue
        last_p, bid_p = tk["last"], tk["bid"]

        if g["status"] == "WAITING_BUY":
            # Jika rezim berubah ke BEAR, batalkan antrean BUY grid yang belum terisi!
            if regime == "BEAR":
                cancel_order_indodax(coin, g.get("buy_order_id"))
                msg = f"🛑 [GRID PAUSE - BEAR REGIME] Batalkan antrean Grid Buy {coin} @ Rp{g['buy_price_idr']:,.0f}."
                logs.append(msg)
                tx_logs.append(msg)
                continue

            filled = False
            if LIVE_TRADING_ENABLED and dompet["connected"]:
                st_o, _ = cek_status_order(coin, g.get("buy_order_id"))
                if st_o == "FILLED":
                    filled = True
                elif st_o in ("CANCELED", "EXPIRED", "NOT_FOUND"):
                    continue
            else:
                if last_p <= float(g["buy_price_idr"]):
                    filled = True

            if filled:
                sell_p = bulatkan_harga(spec, float(g["buy_price_idr"]) * (1.0 + float(g["spacing_pct"])), mode="ceil")
                res_s = kirim_order_indodax_pro(coin, "SELL", g["qty"], price_idr=sell_p, order_type="LIMIT", maker_only=True)
                if is_order_ok(res_s):
                    g["status"] = "WAITING_SELL"
                    g["sell_price_idr"] = sell_p
                    g["sell_order_id"] = str(res_s.get("orderId"))
                    msg = f"🟩 [GRID BUY TERISI -> PASANG TP +{g['spacing_pct']*100:.1f}%] {coin} Beli Rp{g['buy_price_idr']:,.0f} -> Jual Rp{sell_p:,.0f}"
                    logs.append(msg)
                    tx_logs.append(msg)
                active_grids.append(g)
                continue

            active_grids.append(g)
            continue

        if g["status"] == "WAITING_SELL":
            # Cek Hard Floor Grid (-7.5% dari harga beli) untuk mencegah kerugian ekstrem saat breakdown
            dd_grid = (bid_p - float(g["buy_price_idr"])) / float(g["buy_price_idr"])
            if dd_grid <= -SIDEWAYS_GRID_HARD_STOP_PCT and regime == "BEAR":
                cancel_order_indodax(coin, g.get("sell_order_id"))
                ok_sl, fill_sl, mode_sl = eksekusi_sl_protektif_berbuffer(coin, g["qty"], bid_p)
                if ok_sl:
                    net_ret = ((1.0 - FEE_MAKER_BUY) * (fill_sl / float(g["buy_price_idr"])) * (1.0 - FEE_TAKER_SELL)) - 1.0
                    pnl_idr = round(float(g["capital_idr"]) * net_ret, 0)
                    catat_realized_pnl(state, coin, pnl_idr, is_sl=True)
                    msg = f"🛡️ [GRID BREAKDOWN STOP | {mode_sl}] {coin} keluar @ Rp{fill_sl:,.0f} (PnL: Rp{pnl_idr:,.0f})"
                    logs.append(msg)
                    tx_logs.append(msg)
                    log_audit_db(regime, coin, "WIDE_GRID", "GRID_STOP", fill_sl, g["qty"], g["capital_idr"], pnl_idr, 0.0, msg)
                    continue

            sold = False
            if LIVE_TRADING_ENABLED and dompet["connected"]:
                st_o, _ = cek_status_order(coin, g.get("sell_order_id"))
                if st_o == "FILLED":
                    sold = True
            else:
                if last_p >= float(g["sell_price_idr"]):
                    sold = True

            if sold:
                net_pct = hitung_profit_bersih_grid_maker(float(g["spacing_pct"]))
                pnl_idr = round(float(g["capital_idr"]) * net_pct, 0)
                catat_realized_pnl(state, coin, pnl_idr, is_sl=False)
                msg = (
                    f"🎉 [WIDE GRID SIKLUS SELESAI] {coin} (+{g['spacing_pct']*100:.1f}% gross -> +{net_pct*100:.2f}% bersih) "
                    f"| Profit: +Rp{pnl_idr:,.0f}"
                )
                logs.append(msg)
                tx_logs.append(msg)
                log_audit_db(regime, coin, "WIDE_GRID", "GRID_TP", g["sell_price_idr"], g["qty"], g["capital_idr"], pnl_idr, 0.0, msg)
                continue

            active_grids.append(g)

    state["grid_orders"] = active_grids

    # 2. Pasang Grid Baru hanya saat SIDEWAYS (2.0%, maks 30% modal, BTC/ETH) atau SIDEWAYS_DOWNTREND (3.0%, maks 15% modal, BTC)
    if not hard_risk_ok or regime not in ("SIDEWAYS", "SIDEWAYS_DOWNTREND"):
        return logs, tx_logs

    if regime == "SIDEWAYS":
        target_coins = [c for c, s in UNIVERSE.items() if s.get("grid_eligible")]
        max_grid_budget = float(state.get("current_equity_idr", MAX_BOT_CAPITAL_IDR)) * SIDEWAYS_GRID_MAX_ALLOC_PCT
        spacing = SIDEWAYS_GRID_SPACING_PCT
        grid_label = "WIDE_GRID_2PCT"
    else:
        # Plan B Sideways Downtrend: Defensive Wide Grid 3.0% (+2.55% net) khusus BTC/IDR, maks 15% modal
        target_coins = ["BTC"]
        max_grid_budget = float(state.get("current_equity_idr", MAX_BOT_CAPITAL_IDR)) * PLAN_B_RELIEF_MAX_ALLOC_PCT
        spacing = PLAN_B_DEFENSIVE_GRID_SPACING_PCT
        grid_label = "PLAN_B_DEFENSIVE_GRID_3PCT"

    used_grid = sum(float(g.get("capital_idr", 0.0)) for g in state["grid_orders"])
    sisa_budget = min(max(0.0, max_grid_budget - used_grid), dompet["idr_free"], hitung_plafon_sisa_bot(state))
    if sisa_budget < MIN_SAFE_POSITION_IDR:
        return logs, tx_logs

    # Jika anggaran 30% (misal Rp30rb pada modal Rp100rb) tidak cukup dibagi 2 koin (>= Rp30rb/koin),
    # pusatkan seluruh anggaran 30% tersebut ke koin paling likuid (BTC/IDR) agar tetap patuh batas 30% analisis.
    if len(target_coins) > 1 and (sisa_budget / len(target_coins)) < MIN_SAFE_POSITION_IDR:
        target_coins = [target_coins[0]]  # Fokus 100% ke BTC/IDR

    per_coin_budget = sisa_budget / max(1, len(target_coins))
    for coin in target_coins:
        tk = tickers.get(coin)
        if not tk or tk["bid"] <= 0:
            continue
        existing_for_coin = [g for g in state["grid_orders"] if g["coin"] == coin]
        slots_needed = SIDEWAYS_GRID_LEVELS - len(existing_for_coin)
        if slots_needed <= 0:
            continue

        cap_per_level = math.floor(per_coin_budget / max(1, slots_needed))
        if cap_per_level < MIN_SAFE_POSITION_IDR:
            slots_needed = int(per_coin_budget // MIN_SAFE_POSITION_IDR)
            if slots_needed <= 0:
                continue
            cap_per_level = math.floor(per_coin_budget / slots_needed)

        spec = UNIVERSE[coin]
        for lvl in range(1, slots_needed + 1):
            buy_p = bulatkan_harga(spec, tk["bid"] * (1.0 - (spacing * lvl)), mode="floor")
            # Hindari duplikasi level harga yang sudah ada
            if any(abs(float(g["buy_price_idr"]) - buy_p) / max(1.0, buy_p) < (spacing * 0.5) for g in state["grid_orders"] if g["coin"] == coin):
                continue
            qty = format_qty(spec, cap_per_level / buy_p)
            notional = round(qty * buy_p, 0)
            if notional < (MIN_INDODAX_PRO_ORDER_IDR + 2500.0):
                continue
            res_b = kirim_order_indodax_pro(coin, "BUY", qty, price_idr=buy_p, order_type="LIMIT", maker_only=True)
            if is_order_ok(res_b):
                state["grid_orders"].append({
                    "coin": coin,
                    "strategy": grid_label,
                    "status": "WAITING_BUY",
                    "level": lvl,
                    "spacing_pct": spacing,
                    "buy_price_idr": buy_p,
                    "sell_price_idr": bulatkan_harga(spec, buy_p * (1.0 + spacing), mode="ceil"),
                    "qty": qty,
                    "capital_idr": notional,
                    "buy_order_id": str(res_b.get("orderId")),
                    "created_ts": time.time(),
                })
                dompet["idr_free"] = max(0.0, dompet["idr_free"] - notional)
                net_est = hitung_profit_bersih_grid_maker(spacing) * 100.0
                msg = (
                    f"🧱 [{grid_label} L{lvl}] {coin} Limit Maker Buy @ Rp{buy_p:,.0f} "
                    f"(Modal Rp{notional:,.0f} | Target +{spacing*100:.1f}% / Net +{net_est:.2f}%)"
                )
                logs.append(msg)
                tx_logs.append(msg)
                log_audit_db(regime, coin, grid_label, "GRID_BUY_PLACED", buy_p, qty, notional, 0.0, 0.0, msg)

    return logs, tx_logs


# ==============================================================================
# BAGIAN 13: PLAN B KHUSUS BEAR MARKET (PARKIR KAS USDT + ALERT HEDGE CFX/OJK)
# ==============================================================================
def jalankan_plan_b_bear_market(state, tickers, dompet, regime_info):
    """
    Plan B Rezim BEAR (Bagian 2 & 6 File Analisis):
    1. Preservasi Modal 80%-90% Kas/USDT:
       - Mematikan seluruh entry agresif.
       - Opsional parkir 80% kas IDR bebas ke USDT/IDR (Limit Maker) sebagai lindung nilai
         depresiasi Rupiah, dengan syarat tidak ada anomali lonjakan kurs USDT/IDR.
       - Saat rezim kembali ke BULL, otomatis melepas kembali parkir USDT ke IDR agar siap Swing!
    2. Kalkulator & Peringatan Short Hedge Derivatif Legal OJK/CFX (Reku Futures / Pintu Pro Futures):
       - Menghitung margin & ukuran short hedge konservatif 2x-3x untuk melindungi nilai spot holding.
    """
    logs, tx_logs = [], []
    regime = regime_info["regime"]
    tk_usdt = tickers.get("USDT")
    if not tk_usdt or tk_usdt["last"] <= 0:
        return logs, tx_logs

    usdt_bid = tk_usdt["bid"]
    usdt_ask = tk_usdt["ask"]

    # A. PARKIR KAS USDT SAAT BEAR (OPSIONAL VIA ENV PLAN_B_AUTO_USDT_PARKING=true)
    if PLAN_B_AUTO_USDT_PARKING:
        if regime == "BEAR" and not regime_info.get("fx_anomaly", False):
            target_park_idr = min(dompet["idr_free"], hitung_plafon_sisa_bot(state)) * PLAN_B_USDT_PARKING_RATIO
            if target_park_idr >= MIN_SAFE_POSITION_IDR:
                buy_p = bulatkan_harga(USDT_PARK_SPEC, usdt_bid, mode="floor")
                qty_u = format_qty(USDT_PARK_SPEC, target_park_idr / buy_p)
                if qty_u * buy_p >= MIN_INDODAX_PRO_ORDER_IDR:
                    res = kirim_order_indodax_pro("USDT", "BUY", qty_u, price_idr=buy_p, order_type="LIMIT", maker_only=True)
                    if is_order_ok(res):
                        old_q = float(state.get("usdt_parked_qty", 0.0))
                        old_avg = float(state.get("usdt_parked_avg_idr", buy_p))
                        new_q = old_q + qty_u
                        state["usdt_parked_avg_idr"] = ((old_q * old_avg) + (qty_u * buy_p)) / max(1e-9, new_q)
                        state["usdt_parked_qty"] = new_q
                        dompet["idr_free"] = max(0.0, dompet["idr_free"] - (qty_u * buy_p))
                        msg = (
                            f"🛡️ [PLAN B PARKIR USDT] Rezim BEAR -> Parkir {qty_u:.2f} USDT @ Rp{buy_p:,.0f} "
                            f"(Rp{qty_u*buy_p:,.0f}) sebagai lindung nilai kurs Rupiah."
                        )
                        logs.append(msg)
                        tx_logs.append(msg)
                        log_audit_db(regime, "USDT", "PLAN_B_PARK", "USDT_PARK_BUY", buy_p, qty_u, qty_u * buy_p, 0.0, 0.0, msg)
        elif regime == "BULL":
            # Rezim kembali BULL -> cairkan parkir USDT ke IDR agar siap eksekusi Core Swing IDR
            parked_q = float(state.get("usdt_parked_qty", 0.0))
            if LIVE_TRADING_ENABLED and dompet["connected"]:
                parked_q = min(parked_q, float(dompet["coins_free"].get("USDT", 0.0)))
            if parked_q * usdt_ask >= MIN_INDODAX_PRO_ORDER_IDR:
                sell_p = bulatkan_harga(USDT_PARK_SPEC, usdt_ask, mode="ceil")
                res = kirim_order_indodax_pro("USDT", "SELL", parked_q, price_idr=sell_p, order_type="LIMIT", maker_only=True)
                if is_order_ok(res):
                    state["usdt_parked_qty"] = 0.0
                    msg = f"🔄 [PLAN B UNPARK USDT -> IDR] Rezim BULL aktif, mencairkan {parked_q:.2f} USDT @ Rp{sell_p:,.0f} ke IDR."
                    logs.append(msg)
                    tx_logs.append(msg)
                    log_audit_db(regime, "USDT", "PLAN_B_UNPARK", "USDT_PARK_SELL", sell_p, parked_q, parked_q * sell_p, 0.0, 0.0, msg)

    # B. KALKULATOR & PERINGATAN SHORT HEDGE DERIVATIF CFX/OJK (REKU FUTURES / PINTU PRO FUTURES)
    if regime == "BEAR":
        now_ts = time.time()
        if (now_ts - float(state.get("last_hedge_alert_ts", 0.0))) >= (12.0 * 3600.0):
            active_spot_idr = SPOT_CORE_HOLDING_IDR + sum(
                float(p.get("remaining_capital_idr", 0.0)) for p in state.get("swing_positions", [])
            )
            if active_spot_idr > 0:
                hedge_notional = active_spot_idr * 0.50  # Lindungi 50% eksposur spot
                margin_needed = hedge_notional / PLAN_B_HEDGE_LEVERAGE
                alert_msg = (
                    f"⚠️ [PLAN B SARAN HEDGE CFX/OJK] Rezim BEAR terkonfirmasi ({regime_info['reason']}). "
                    f"Indodax murni Spot 1:1. Untuk eksposur spot Rp{active_spot_idr:,.0f}, pertimbangkan "
                    f"Short Hedge BTC Perpetual di Reku Futures (RT 0.331%) / Pintu Pro Futures "
                    f"senilai Rp{hedge_notional:,.0f} (Margin ~Rp{margin_needed:,.0f} @ Leverage {PLAN_B_HEDGE_LEVERAGE:.0f}x)."
                )
            else:
                alert_msg = (
                    f"🛡️ [PLAN B MODE RISK-OFF BEAR] 100% modal kerja aman di Kas/USDT "
                    f"(Rp{dompet['idr_free']:,.0f} IDR bebas | {state.get('usdt_parked_qty', 0):.2f} USDT). "
                    f"Entri agresif dimatikan sampai BTC Global kembali di atas EMA50/100."
                )
            state["last_hedge_alert_ts"] = now_ts
            logs.append(alert_msg)
            kirim_telegram(alert_msg)

    return logs, tx_logs


# ==============================================================================
# BAGIAN 14: EKSEKUTOR ENTRY BARU (CORE SWING & PLAN B RELIEF BOUNCE)
# ==============================================================================
def jalankan_entry_baru(state, analisa_map, dompet, regime_info, hard_risk_ok):
    logs, tx_logs = [], []
    if not hard_risk_ok:
        return logs, tx_logs

    regime = regime_info["regime"]
    if regime not in ("BULL", "SIDEWAYS_DOWNTREND"):
        return logs, tx_logs

    sesi = cek_jendela_likuiditas_wib()
    if not sesi["entry_allowed"]:
        logs.append(f"⏸️ [FILTER SESI LIKUIDITAS] Saat ini {sesi['label']} — Entry baru ditunda menunggu sesi likuiditas puncak.")
        return logs, tx_logs

    sisa_slot = MAX_CONCURRENT_POSITIONS - len(state.get("swing_positions", []))
    if sisa_slot <= 0 or dompet["idr_free"] < MIN_SAFE_POSITION_IDR:
        return logs, tx_logs

    now_ts = time.time()
    cooldowns = {k: v for k, v in state.get("sl_cooldown_until", {}).items() if float(v) > now_ts}
    state["sl_cooldown_until"] = cooldowns

    open_coins = {p["coin"] for p in state.get("swing_positions", [])}
    kandidat = [
        a for a in analisa_map.values()
        if a
        and a["signal_type"] in ("CORE_SWING", "PLAN_B_RELIEF_BOUNCE")
        and a["coin"] not in open_coins
        and a["coin"] not in cooldowns
    ]
    kandidat.sort(key=lambda x: x["score"], reverse=True)
    kandidat = kandidat[:sisa_slot]
    if not kandidat:
        return logs, tx_logs

    # Opsional Gemini Advisory (Shadow atau Entry Filter)
    ai_votes = konsultasi_gemini_entry_advisory(kandidat, regime_info)
    equity = float(state.get("current_equity_idr", MAX_BOT_CAPITAL_IDR))

    for k in kandidat:
        coin = k["coin"]
        spec = UNIVERSE[coin]
        approved, ai_note = ai_votes.get(coin, (True, "Deterministik"))
        if not approved:
            logs.append(f"⏸️ [AI FILTER TUNDA ENTRY] {coin}: {ai_note}")
            continue

        # Anti-Duplikat di Indodax Live
        if LIVE_TRADING_ENABLED and dompet["connected"]:
            ok_oo, oo_list = ambil_open_orders(coin)
            if ok_oo and len(oo_list) > 0:
                logs.append(f"🛡️ [ANTI-DUPLIKAT] {coin} sudah punya {len(oo_list)} Open Order aktif di Indodax.")
                continue

        # Hitung Ukuran Posisi Presisi (Friction-Adjusted Position Sizing)
        sl_gross = k["sl_gross"]
        net_loss_pct = k["rrr_staged"]["net_loss"]
        max_weight_cap = equity * (
            PLAN_B_RELIEF_MAX_ALLOC_PCT if k["signal_type"] == "PLAN_B_RELIEF_BOUNCE" else spec["max_portfolio_weight"]
        )
        max_avail_cap = min(max_weight_cap, dompet["idr_free"], hitung_plafon_sisa_bot(state))
        risk_pct = (RISK_PER_TRADE_PCT * 0.5) if k["signal_type"] == "PLAN_B_RELIEF_BOUNCE" else RISK_PER_TRADE_PCT
        pos_size_idr = hitung_friction_adjusted_position_size(equity, risk_pct, net_loss_pct, max_avail_cap)

        # Penyesuaian ramah modal kecil: jika modal kerja kecil sehingga 1% risk menghasilkan size < Rp30rb,
        # gunakan alokasi proporsional aman minimal Rp30.000 selama tidak melebihi batas bobot koin
        if pos_size_idr < MIN_SAFE_POSITION_IDR and max_avail_cap >= MIN_SAFE_POSITION_IDR:
            pos_size_idr = min(max_avail_cap, max(MIN_SAFE_POSITION_IDR, round(equity * 0.30, 0)))

        if pos_size_idr < MIN_SAFE_POSITION_IDR:
            logs.append(f"⚠️ [SKIP {coin}] Ukuran posisi Rp{pos_size_idr:,.0f} di bawah batas aman Indodax Pro Rp{MIN_SAFE_POSITION_IDR:,.0f}.")
            continue

        # Cek apakah modal posisi cukup untuk dipecah Staged Partial TP 40/30/30 (tiap tranche >= Rp25.000)
        can_stage = (pos_size_idr * 0.30 >= MIN_INDODAX_PRO_ORDER_IDR) and (k["signal_type"] == "CORE_SWING")
        est_rrr = k["rrr_staged"]["net_rrr"] if can_stage else k["rrr_single"]["net_rrr"]
        if est_rrr < MIN_NET_RRR_REQUIRED:
            logs.append(f"🚫 [TOLAK RRR < 1:2.00] {coin} Net RRR hanya 1:{est_rrr:.2f} (di bawah ambang 1:{MIN_NET_RRR_REQUIRED:.2f}).")
            continue

        entry_p = k["entry_idr"]
        qty = format_qty(spec, pos_size_idr / entry_p)
        notional = round(qty * entry_p, 0)
        if notional < (MIN_INDODAX_PRO_ORDER_IDR + 2500.0):
            continue

        res_buy = kirim_order_indodax_pro(coin, "BUY", qty, price_idr=entry_p, order_type="LIMIT", maker_only=True)
        if not is_order_ok(res_buy):
            logs.append(f"⚠️ [GAGAL ENTRY {coin}] {res_buy}")
            continue

        sl_p = bulatkan_harga(spec, entry_p * (1.0 - sl_gross), mode="floor")
        if can_stage:
            tp1_p = bulatkan_harga(spec, entry_p * (1.0 + SWING_TP1_PCT), mode="ceil")
            tp2_p = bulatkan_harga(spec, entry_p * (1.0 + SWING_TP2_PCT), mode="ceil")
            tp3_p = bulatkan_harga(spec, entry_p * (1.0 + SWING_TP3_PCT), mode="ceil")
        else:
            tp_target = 0.095 if k["signal_type"] == "PLAN_B_RELIEF_BOUNCE" else SINGLE_TRANCHE_TP_PCT
            tp1_p = bulatkan_harga(spec, entry_p * (1.0 + tp_target), mode="ceil")
            tp2_p = tp1_p
            tp3_p = tp1_p

        state["swing_positions"].append({
            "coin": coin,
            "strategy": k["signal_type"],
            "status": "WAITING_BUY",
            "buy_order_id": str(res_buy.get("orderId")),
            "entry_price_idr": entry_p,
            "sl_price_idr": sl_p,
            "tp1_price_idr": tp1_p,
            "tp2_price_idr": tp2_p,
            "tp3_price_idr": tp3_p,
            "use_staged_tp": can_stage,
            "tp1_done": False,
            "tp2_done": False,
            "be_armed": False,
            "initial_qty": qty,
            "remaining_qty": qty,
            "initial_capital_idr": notional,
            "remaining_capital_idr": notional,
            "highest_idr": entry_p,
            "est_net_rrr": round(est_rrr, 2),
            "created_ts": now_ts,
        })
        dompet["idr_free"] = max(0.0, dompet["idr_free"] - notional)

        mode_tp_txt = f"Staged 40/30/30 (TP1:Rp{tp1_p:,.0f}/TP2:Rp{tp2_p:,.0f}/TP3:Rp{tp3_p:,.0f})" if can_stage else f"Single TP:Rp{tp1_p:,.0f}"
        msg = (
            f"🚀 [ENTRY MAKER MOC - {k['signal_type']}] {coin} | Modal:Rp{notional:,.0f} @ Rp{entry_p:,.0f} "
            f"| SL:Rp{sl_p:,.0f} (-{sl_gross*100:.1f}%) | {mode_tp_txt} | Net RRR 1:{est_rrr:.2f} | {ai_note}"
        )
        logs.append(msg)
        tx_logs.append(msg)
        log_audit_db(regime, coin, k["signal_type"], "BUY_PLACED", entry_p, qty, notional, 0.0, est_rrr, msg)

    return logs, tx_logs


# ==============================================================================
# BAGIAN 15: TELEMETRI (TELEGRAM EVENT-BASED, GOOGLE SHEETS, GITHUB SUMMARY)
# ==============================================================================
def kirim_telegram(pesan):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": pesan[:3900]}).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as e:
        print(f"⚠️ [TELEGRAM GAGAL]: {e}")


def kirim_google_sheets(state, tx_logs, dompet, regime_info):
    if not GOOGLE_SHEETS_WEBHOOK_URL or not tx_logs:
        return
    payload = {
        "tanggal": now_wib().strftime("%Y-%m-%d %H:%M:%S"),
        "pasangan": f"INDODAX PRO ({regime_info['regime']})",
        "modal_aktif_idr": round(
            sum(float(p.get("remaining_capital_idr", 0)) for p in state["swing_positions"])
            + sum(float(g.get("capital_idr", 0)) for g in state["grid_orders"]),
            0,
        ),
        "harga_acuan_idr": round(dompet.get("idr_free", 0.0), 0),
        "jumlah_grid_tereksekusi": state.get("completed_trades_total", 0),
        "profit_terealisasi_idr": state.get("realized_pnl_today_idr", 0.0),
        "floating_pnl_idr": 0.0,
        "tren_1h": f"{regime_info['regime']} | BTC:${regime_info.get('btc_usd', 0):,.0f}",
        "rsi_14": f"H4:{regime_info.get('btc_rsi_h4', '-')}",
        "analisis_ai_gemini": " | ".join(tx_logs)[:490],
    }
    try:
        req = urllib.request.Request(
            GOOGLE_SHEETS_WEBHOOK_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"✅ [GOOGLE SHEETS TERKIRIM]: {resp.read().decode('utf-8')[:120]}")
    except Exception as e:
        print(f"⚠️ [GOOGLE SHEETS GAGAL]: {e}")


def tulis_ringkasan_siklus(state, regime_info, analisa_map, dompet, logs):
    tot = int(state.get("completed_trades_total", 0))
    wr = (int(state.get("wins_total", 0)) / tot * 100.0) if tot > 0 else 0.0
    sesi = cek_jendela_likuiditas_wib()
    skim_msg = cek_rekomendasi_profit_skimming(state)

    baris = [
        "=" * 78,
        f"📊 INDODAX PRO MULTI-REGIME BOT | {now_wib().strftime('%Y-%m-%d %H:%M:%S WIB')} | Mode: {'LIVE' if LIVE_TRADING_ENABLED else 'SIMULASI'}",
        f"🧭 REZIM PASAR : {regime_info['regime']} ({regime_info['reason']})",
        f"🕒 SESI PASAR  : {sesi['label']} | Kurs USDT/IDR: Rp{regime_info.get('usdt_idr', 0):,.0f} (Anomali: {regime_info.get('fx_anomaly')})",
        f"💼 PLAFON BOT  : Rp{MAX_BOT_CAPITAL_IDR:,.0f} (Ekuitas: Rp{state.get('current_equity_idr', 0):,.0f} | Sisa Plafon Bebas: Rp{dompet.get('idr_free', 0):,.0f} | Dompet Asli: Rp{dompet.get('wallet_idr_free_raw', dompet.get('idr_free', 0)):,.0f})",
        f"📈 KINERJA     : PnL Hari Ini Rp{state.get('realized_pnl_today_idr', 0):,.0f} | Kuartal Rp{state.get('realized_pnl_quarter_idr', 0):,.0f} | WR: {wr:.1f}% ({state.get('wins_total', 0)}W/{state.get('losses_total', 0)}L)",
        f"📌 POSISI AKTIF: {len(state.get('swing_positions', []))} Swing OCO | {len(state.get('grid_orders', []))} Wide Grid",
        "-" * 78,
    ]
    for coin, a in analisa_map.items():
        if not a:
            continue
        baris.append(
            f"   * {coin:<4} [{a['tier']:<9}] Rp{a['last_idr']:>14,.0f} | RSI H4:{a['rsi_h4']:>4.1f} D:{a['rsi_d']:>4.1f} "
            f"| NetRRR 1:{a['rrr_staged']['net_rrr']:.2f} | Sinyal:{a['signal_type']}"
        )
    if skim_msg:
        baris.append(skim_msg)
    baris.append("=" * 78)
    teks = "\n".join(baris)
    print(teks)

    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(f"### 📊 Indodax Pro Multi-Regime Report ({regime_info['regime']})\n```text\n{teks}\n```\n")
        except Exception:
            pass


# ==============================================================================
# BAGIAN 16: ORKESTRATOR UTAMA (URUTAN BOOTING AMAN + MODE CYCLE / DAEMON)
# ==============================================================================
def jalankan_satu_siklus(state, refresh_analisa=True, cached_bundle=None):
    # 1. Heartbeat Deadman Switch (Dual-Key Legacy v1) bila dikonfigurasi
    if LIVE_TRADING_ENABLED and INDODAX_LEGACY_KEY:
        ping_legacy_deadman_switch(DEADMAN_SWITCH_SECONDS)

    # 2. Cek Saldo & Tickers Aktual Indodax
    dompet = ambil_dompet_indodax(state)
    if LIVE_TRADING_ENABLED and not dompet["connected"]:
        print("⚠️ Gagal terhubung ke Trade API v2 Indodax. Siklus dilewati demi keamanan state.")
        return state, cached_bundle

    tickers = ambil_tickers_indodax()
    usdt_idr = tickers.get("USDT", {}).get("last", 0.0)
    fx_anomaly, _ = deteksi_anomali_kurs_usdt(state, usdt_idr)

    # 3. Analisa Dual-Chart Global H4-Daily & Regime Gate
    if refresh_analisa or not cached_bundle:
        btc_d = ambil_ohlc_global("BTC", "1d", limit=130)
        btc_h4 = ambil_ohlc_global("BTC", "4h", limit=180)
        regime_info = evaluasi_rezim_pasar(btc_d, btc_h4, usdt_idr, fx_anomaly)
        if regime_info["regime"] != state.get("last_regime"):
            state["last_regime"] = regime_info["regime"]
            log_regime_db(regime_info)
            kirim_telegram(f"🧭 [PERUBAHAN REZIM PASAR] -> {regime_info['regime']}\n{regime_info['reason']}")

        analisa_map = {}
        for coin in UNIVERSE.keys():
            analisa_map[coin] = analisa_setup_koin(coin, tickers, state, regime_info)
        cached_bundle = (regime_info, analisa_map)
    else:
        regime_info, analisa_map = cached_bundle

    # 4. Hard Risk Gate (Deterministik)
    hard_risk_ok, risk_msg = cek_hard_risk_gate(state)
    all_logs, all_tx = [], []
    if not hard_risk_ok:
        all_logs.append(risk_msg)

    # 5. Kawal Virtual OCO Swing (PRIORITAS TERTINGGI - selalu jalan tiap tick!)
    l_oco, tx_oco = kelola_virtual_oco_swing(state, analisa_map, tickers, dompet, regime_info)
    all_logs.extend(l_oco)
    all_tx.extend(tx_oco)

    # 6. Jalankan Wide Grid (Sideways 2% / Plan B Sideways Downtrend 3%)
    l_grid, tx_grid = kelola_wide_grid_engine(state, tickers, dompet, regime_info, hard_risk_ok)
    all_logs.extend(l_grid)
    all_tx.extend(tx_grid)

    # 7. Jalankan Plan B Bear Market (Parkir USDT & Saran Hedge CFX/OJK)
    l_pb, tx_pb = jalankan_plan_b_bear_market(state, tickers, dompet, regime_info)
    all_logs.extend(l_pb)
    all_tx.extend(tx_pb)

    # 8. Eksekusi Entry Baru (Core Swing saat BULL / Relief Bounce saat SIDEWAYS_DOWNTREND)
    l_en, tx_en = jalankan_entry_baru(state, analisa_map, dompet, regime_info, hard_risk_ok)
    all_logs.extend(l_en)
    all_tx.extend(tx_en)

    # 9. Simpan State secara Atomik (tmp + os.replace)
    save_state_atomic(state)

    for ln in all_logs:
        print("  ", ln)

    if all_tx:
        kirim_telegram("🔔 [INDODAX PRO BOT TRANSAKSI]\n" + "\n".join(all_tx))
        kirim_google_sheets(state, all_tx, dompet, regime_info)

    if refresh_analisa:
        tulis_ringkasan_siklus(state, regime_info, analisa_map, dompet, all_logs)

    return state, cached_bundle


def main():
    # URUTAN BOOTING KRITIS (Menambal bug FMA KNOWN_ISSUES.md):
    # 1. Init SQLite WAL -> 2. Load state.json SEBELUM sentuh API order -> 3. Muat metadata /api/pairs
    init_sqlite_wal()
    state = load_state()
    muat_metadata_pairs_indodax()

    if RUN_MODE == "daemon":
        print(f"🚀 [VPS 24/7 DAEMON MODE] OCO Poll: {OCO_POLL_SECONDS}d | Refresh H4/DOM: {DAEMON_ANALYSIS_INTERVAL_SEC}d")
        last_analysis_ts = 0.0
        cached = None
        while True:
            try:
                now_ts = time.time()
                need_refresh = (now_ts - last_analysis_ts) >= DAEMON_ANALYSIS_INTERVAL_SEC
                state, cached = jalankan_satu_siklus(state, refresh_analisa=need_refresh, cached_bundle=cached)
                if need_refresh:
                    last_analysis_ts = now_ts
            except KeyboardInterrupt:
                print("\n🛑 Bot dihentikan dengan aman oleh pengguna.")
                save_state_atomic(state)
                break
            except Exception as e:
                print(f"⚠️ [ERROR SIKLUS DAEMON]: {e}")
            time.sleep(OCO_POLL_SECONDS)
    else:
        # Mode Cycle (Ramah GitHub Actions Cron + Kawal Virtual OCO selama CYCLE_WATCH_MINUTES)
        start_ts = time.time()
        end_ts = start_ts + (CYCLE_WATCH_MINUTES * 60)
        state, cached = jalankan_satu_siklus(state, refresh_analisa=True, cached_bundle=None)
        while (state.get("swing_positions") or state.get("grid_orders")) and (time.time() + OCO_POLL_SECONDS < end_ts):
            time.sleep(OCO_POLL_SECONDS)
            state, cached = jalankan_satu_siklus(state, refresh_analisa=False, cached_bundle=cached)


if __name__ == "__main__":
    main()
