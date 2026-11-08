# ==============================================================================
# SMART DYNAMIC HYBRID AI TRADING BOT 24/7 (TOKOCRYPTO API + GEMINI AI + SHEETS)
# ==============================================================================
# Arsitektur "Analyze-Before-Act" (Selalu Analisis Pasar Sebelum Mengambil Keputusan):
# 1. CAPITAL CAP (Batas Maksimal Modal Bot): Bot hanya mengelola maksimal sebesar
#    MAX_BOT_CAPITAL_IDR (misal Rp100.000 / Rp150.000) dari saldo Tokocrypto Anda.
# 2. HYBRID CAMPURAN DINAMIS (Grid + Sniper Berjalan Bersamaan): Tiap slot Rp25.000
#    dapat memilih gaya GRID atau SNIPER secara mandiri sesuai kondisi pasar koin.
# 3. ANALISIS CERDAS ANTREAN ENTRY (> 6 Jam / Harga Lari):
#    - Tidak asal patok batalkan di 3.5%. Jika antrean sudah > 6 jam (atau harga
#      mulai menjauh), bot MENGANALISIS ULANG chart koin tersebut + seluruh pasar:
#      * Opsi A (PERTAHANKAN): Jika harga sedang turun mendekati titik Limit Buy dan
#        indikator bagus, antrean dipertahankan.
#      * Opsi B (SESUAIKAN/NAIKKAN ENTRY): Jika koin ini masih kandidat terbaik di
#        pasar dan trennya kuat naik, bot menggeser naik Limit Buy ke area support
#        terbaru agar terbeli tanpa mengejar pucuk.
#      * Opsi C (GANTI KOIN LEBIH BAIK): Jika koin lain di pasar punya skor peluang
#        jauh lebih tinggi, barulah antrean dibatalkan dan anggaran langsung dipindah
#        ke koin terbaik tersebut pada siklus yang sama!
# 4. DYNAMIC STEP-UP TRAILING PROFIT LOCK & SMART EARLY TP (Sudah Hitung Fee+Pajak):
#    - Menghitung otomatis biaya beli+jual+pajak Tokocrypto (0.4544% Maker / 0.5544% Taker).
#    - Saat naik >= +1.5%: Kunci SL di +0.95% (Untung bersih +0.40% di atas fee/pajak).
#    - Saat naik >= +2.2%: Jika RSI >= 68 (jenuh beli), langsung Take Profit di +2.2%!
#      Jika tren masih kuat (RSI < 68), kunci SL di +1.60% (Untung bersih > +1.05%)
#      sambil lanjut mengejar +3.5%.
#    - Saat naik >= +2.8%: Kunci SL di +2.30% (Untung bersih > +1.75%).
# 5. ANALISIS BERTAHAP TIME-STOP (40 JAM -> 48 JAM):
#    - Pada umur >= 40 Jam (Mendekati 48 Jam): Bot menganalisis ulang kekuatan tren,
#      RSI, dan volatilitas (ATR) koin tersebut:
#      * Jika momentum masih mampu mendorong harga naik, bot menyesuaikan target TP
#        secara realistis ke +1.2% s/d +2.0% sesuai proyeksi ATR.
#      * Jika hasil analisis di 40 jam menunjukkan tren sudah habis/lemah dan posisi
#        sudah untung >= +0.85% (menutup fee+pajak + untung bersih), langsung bungkus!
#    - Pada umur >= 48 Jam: Evaluasi akhir untuk keluar di >= +0.80% agar modal kembali
#      segar dan langsung dianalisis untuk peluang koin baru.
# ==============================================================================

import os
import time
import hmac
import hashlib
import urllib.parse
import urllib.request
import json
from datetime import datetime

# ==============================================================================
# BAGIAN 1: KONFIGURASI MODAL & BIAYA RESMI TOKOCRYPTO
# ==============================================================================
MAX_BOT_CAPITAL_IDR = float(os.getenv("MAX_BOT_CAPITAL_IDR", "100000"))
SLOT_SIZE_IDR = float(os.getenv("SLOT_SIZE_IDR", "25000"))  # Min order Tokocrypto Rp20.000 (https://www.tokocrypto.com/en/trade-rule)

# Biaya Resmi Tokocrypto Pasangan IDR (https://support.tokocrypto.com/hc/en-us/articles/360004044591-Tokocrypto-Transaction-Fee-Details)
FEE_ROUNDTRIP_MAKER_PCT = 0.004544  # 0.4544% (Beli Maker 0.1222% + Jual Maker 0.3322% termasuk Pajak PPh 0.21% & ICEx)
FEE_ROUNDTRIP_TAKER_PCT = 0.005544  # 0.5544% (Jika keluar via Stop/Market Order)

# Parameter Target Dasar (Disesuaikan Dinamis oleh Analisis Bot)
TP_GRID_BASE_PCT = 0.018     # +1.8% Target dasar Grid
SL_GRID_BASE_PCT = 0.020     # -2.0% Batas SL dasar Grid
TP_SNIPER_BASE_PCT = 0.035   # +3.5% Target dasar Sniper
SL_SNIPER_BASE_PCT = 0.018   # -1.8% Batas SL dasar Sniper

REVIEW_ENTRY_HOURS = 6.0     # Mulai analisis ulang kelayakan antrean Limit Buy setelah 6 jam
PRE_TIMESTOP_HOURS = 40.0    # Mulai analisis ulang target TP realistis saat posisi mendekati 40 jam
FINAL_TIMESTOP_HOURS = 48.0  # Batas evaluasi perputaran modal 48 jam (2 hari)

WATCHLIST_COINS = {
    "SOL":  {"toko_symbol": "SOL_IDR",  "kraken_pair": "SOLUSD",   "indodax_key": "sol_idr"},
    "BTC":  {"toko_symbol": "BTC_IDR",  "kraken_pair": "XXBTZUSD", "indodax_key": "btc_idr"},
    "ETH":  {"toko_symbol": "ETH_IDR",  "kraken_pair": "XETHZUSD", "indodax_key": "eth_idr"},
    "XRP":  {"toko_symbol": "XRP_IDR",  "kraken_pair": "XXRPZUSD", "indodax_key": "xrp_idr"},
    "ADA":  {"toko_symbol": "ADA_IDR",  "kraken_pair": "ADAUSD",   "indodax_key": "ada_idr"},
    "SUI":  {"toko_symbol": "SUI_IDR",  "kraken_pair": "SUIUSD",   "indodax_key": "sui_idr"},
    "DOGE": {"toko_symbol": "DOGE_IDR", "kraken_pair": "XDGUSD",   "indodax_key": "doge_idr"}
}

STATE_FILE = "bot_state_tokocrypto.json"

TOKOCRYPTO_API_KEY = os.getenv("TOKOCRYPTO_API_KEY", "")
TOKOCRYPTO_SECRET_KEY = os.getenv("TOKOCRYPTO_SECRET_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GOOGLE_SHEETS_WEBHOOK_URL = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "")

# ==============================================================================
# BAGIAN 2: MEMORI POSISI BOT & FUNGSI ANALISIS TEKNIKAL MENDALAM
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
                harga_map[coin] = float(t["last"])
    except Exception as e:
        print("Fallback harga IDR:", e)
    return harga_map

def analisa_teknikal_lengkap_pasar(harga_idr_live):
    """
    Menganalisis seluruh koin di Watchlist terlebih dahulu (EMA20, EMA50, RSI-14,
    Bollinger Bands, ATR, dan Skor Kelayakan) agar setiap keputusan bot (baik
    mengawal TP, mengevaluasi antrean >6 jam, maupun evaluasi 40 jam) selalu
    didasarkan pada data analisis pasar terkini!
    """
    peta_analisa = {}
    for coin, info in WATCHLIST_COINS.items():
        harga_idr = harga_idr_live.get(coin, 0)
        if harga_idr <= 0:
            continue
        try:
            url = f"https://api.kraken.com/0/public/OHLC?pair={info['kraken_pair']}&interval=60"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                res = json.loads(resp.read().decode())
            result_key = [k for k in res["result"].keys() if k != "last"][0]
            raw = res["result"][result_key][-60:]
            closes = [float(r[4]) for r in raw]
            highs = [float(r[2]) for r in raw]
            lows = [float(r[3]) for r in raw]

            ema20 = sum(closes[-20:]) / 20.0
            ema50 = sum(closes[-50:]) / 50.0
            gains, losses = [], []
            for i in range(-14, 0):
                diff = closes[i] - closes[i-1]
                gains.append(max(diff, 0))
                losses.append(max(-diff, 0))
            rsi = 100 - (100 / (1 + (sum(gains)/14.0) / ((sum(losses)/14.0) or 0.0001)))
            tr_list = [highs[i] - lows[i] for i in range(-14, 0)]
            atr_pct = (sum(tr_list) / 14.0) / closes[-1]

            # Proyeksi potensi kenaikan realistis berdasarkan ATR (volatilitas 4-8 jam ke depan)
            potensi_naik_pct = round(max(atr_pct * 2.2, 0.008), 4)
            diskon_entry_ideal_pct = min(max(atr_pct * 0.4, 0.004), 0.018)
            entry_ideal_idr = round(harga_idr * (1.0 - diskon_entry_ideal_pct), 0)

            if (ema20 > ema50 and 36 <= rsi <= 58) or rsi < 33:
                gaya = "SNIPER"
                skor = 100 - abs(44 - rsi)
            elif 33 <= rsi <= 63:
                gaya = "GRID"
                skor = 75 - abs(50 - rsi)
            else:
                gaya = "WAIT_OVERBOUGHT"
                skor = 10.0

            peta_analisa[coin] = {
                "coin": coin,
                "harga_idr": harga_idr,
                "tren": "UPTREND" if ema20 > ema50 else "SIDEWAYS/DOWN",
                "ema_bullish": ema20 > ema50,
                "rsi": round(rsi, 1),
                "atr_pct": round(atr_pct, 4),
                "potensi_naik_pct": potensi_naik_pct,
                "entry_ideal_idr": entry_ideal_idr,
                "gaya": gaya,
                "skor": round(skor, 1)
            }
        except Exception:
            continue
    return peta_analisa

# ==============================================================================
# BAGIAN 3: EVALUASI DINAMIS POSISI AKTIF & ANTREAN ENTRY (ANALYZE-BEFORE-ACT)
# ==============================================================================
def evaluasi_dan_kawal_posisi_dinamis(state, peta_analisa):
    """
    1. Mengawal posisi HOLDING_FOR_TP dengan Dynamic Step-Up Trailing Stop (sudah
       hitung fee+pajak 0.5544%), Smart Early TP di +2.2%, dan Analisis 40 Jam -> 48 Jam.
    2. Mengevaluasi antrean WAITING_BUY setelah > 6 jam dengan menganalisis ulang
       apakah koin akan menjemput entry, perlu dinaikkan entry-nya, atau diganti
       ke koin lain yang skor analisisnya jauh lebih bagus!
    """
    slot_tetap_aktif = []
    log_aksi = []
    now_ts = time.time()
    ada_anggaran_batal_entry = False

    # Cari koin dengan skor tertinggi di pasar saat ini sebagai pembanding
    semua_kandidat = sorted(peta_analisa.values(), key=lambda x: x["skor"], reverse=True)
    koin_terbaik_pasar = semua_kandidat[0] if semua_kandidat else None

    for slot in state["active_slots"]:
        coin = slot["coin"]
        info_pasar = peta_analisa.get(coin)
        harga_sekarang = info_pasar["harga_idr"] if info_pasar else slot["entry_price_idr"]
        rsi_sekarang = info_pasar["rsi"] if info_pasar else 50.0
        tren_sekarang = info_pasar["tren"] if info_pasar else "SIDEWAYS"
        potensi_naik_pct = info_pasar["potensi_naik_pct"] if info_pasar else 0.015
        skor_koin_ini = info_pasar["skor"] if info_pasar else 50.0

        umur_antre_jam = (now_ts - slot["timestamp"]) / 3600.0
        mode_slot = slot["style"]

        # ======================================================================
        # SKENARIO A: SLOT SEDANG ANTRE BELI (WAITING_BUY)
        # ======================================================================
        if slot["status"] == "WAITING_BUY":
            # 1. Jika harga sudah menyentuh Limit Buy -> Status naik menjadi HOLDING_FOR_TP
            if harga_sekarang <= slot["entry_price_idr"]:
                slot["status"] = "HOLDING_FOR_TP"
                slot["filled_timestamp"] = now_ts
                slot["highest_price_idr"] = harga_sekarang
                log_aksi.append(
                    f"✅ [ENTRY TERBELI] {coin} ({mode_slot}) terbeli di Rp{slot['entry_price_idr']:,.0f}. "
                    f"Target TP aktif di Rp{slot['tp_price_idr']:,.0f} & SL di Rp{slot['sl_price_idr']:,.0f}."
                )
                slot_tetap_aktif.append(slot)
                continue

            # 2. Selama <= 6 Jam pertama, sabar pertahankan antrean (Jangan diganggu)
            if umur_antre_jam <= REVIEW_ENTRY_HOURS:
                log_aksi.append(
                    f"⏳ [ANTRE ENTRY AMAN {umur_antre_jam:.1f} Jam] {coin} ({mode_slot}) tetap antre beli di Rp{slot['entry_price_idr']:,.0f} "
                    f"(Harga pasar: Rp{harga_sekarang:,.0f})."
                )
                slot_tetap_aktif.append(slot)
                continue

            # 3. SETELAH > 6 JAM: ANALISIS ULANG PASAR SEBELUM MEMUTUSKAN NASIB ANTREAN!
            jarak_ke_entry_pct = (harga_sekarang - slot["entry_price_idr"]) / slot["entry_price_idr"]
            skor_terbaik_lain = koin_terbaik_pasar["skor"] if koin_terbaik_pasar else 0

            # Keputusan 3A: Jika jarak harga sudah dekat (<= 1.2%) dan RSI sedang turun menuju area beli -> PERTAHANKAN!
            if jarak_ke_entry_pct <= 0.012 and rsi_sekarang <= 52:
                log_aksi.append(
                    f"🔍 [ANALISA >6 JAM: PERTAHANKAN] Harga {coin} (Rp{harga_sekarang:,.0f}) tinggal berjarak {jarak_ke_entry_pct*100:.2f}% "
                    f"dari Limit Buy Rp{slot['entry_price_idr']:,.0f} dengan RSI {rsi_sekarang}. Antrean dipertahankan!"
                )
                slot_tetap_aktif.append(slot)

            # Keputusan 3B: Jika koin ini masih sangat layak (Uptrend & Skor Tinggi >= Skor Terbaik Pasar - 10),
            # NAIKKAN harga Limit Buy ke support terbaru agar terbeli!
            elif info_pasar and info_pasar["gaya"] != "WAIT_OVERBOUGHT" and skor_koin_ini >= (skor_terbaik_lain - 10):
                entry_baru_idr = info_pasar["entry_ideal_idr"]
                tp_pct = TP_SNIPER_BASE_PCT if mode_slot == "SNIPER" else TP_GRID_BASE_PCT
                sl_pct = SL_SNIPER_BASE_PCT if mode_slot == "SNIPER" else SL_GRID_BASE_PCT
                slot["entry_price_idr"] = entry_baru_idr
                slot["tp_price_idr"] = round(entry_baru_idr * (1.0 + tp_pct), 0)
                slot["sl_price_idr"] = round(entry_baru_idr * (1.0 - sl_pct), 0)
                slot["timestamp"] = now_ts  # Reset waktu antrean
                log_aksi.append(
                    f"📈 [ANALISA >6 JAM: NAIKKAN ENTRY] {coin} masih berstatus {tren_sekarang} kuat (RSI {rsi_sekarang}, Skor {skor_koin_ini}). "
                    f"Limit Buy dinaikkan secara dinamis ke Rp{entry_baru_idr:,.0f} (TP baru: Rp{slot['tp_price_idr']:,.0f}) agar tidak ketinggalan!"
                )
                slot_tetap_aktif.append(slot)

            # Keputusan 3C: Jika koin ini sudah tidak layak atau ada koin lain yang jauh lebih bagus -> BATALKAN & REALOKASI!
            else:
                ada_anggaran_batal_entry = True
                nama_pengganti = koin_terbaik_pasar["coin"] if koin_terbaik_pasar else "koin lain"
                log_aksi.append(
                    f"🔄 [ANALISA >6 JAM: GANTI KOIN] Antrean {coin} dibatalkan setelah analisis ulang karena peluangnya melemah "
                    f"(Skor {skor_koin_ini}). Anggaran Rp{slot['capital_idr']:,.0f} langsung dialihkan ke kandidat terbaik ({nama_pengganti})!"
                )

        # ======================================================================
        # SKENARIO B: KOIN SUDAH TERBELI & SEDANG DIKAWAL MENUJU TP (HOLDING_FOR_TP)
        # ======================================================================
        elif slot["status"] == "HOLDING_FOR_TP":
            umur_hold_jam = (now_ts - slot.get("filled_timestamp", now_ts)) / 3600.0
            slot["highest_price_idr"] = max(slot.get("highest_price_idr", harga_sekarang), harga_sekarang)
            kenaikan_skrg_pct = (harga_sekarang - slot["entry_price_idr"]) / slot["entry_price_idr"]

            # 1. Cek apakah sudah menyentuh Target Take Profit (TP)
            if harga_sekarang >= slot["tp_price_idr"]:
                profit_bersih = round(slot["capital_idr"] * (kenaikan_skrg_pct - FEE_ROUNDTRIP_MAKER_PCT), 0)
                state["realized_profit_today_idr"] += profit_bersih
                state["completed_trades_today"] += 1
                log_aksi.append(
                    f"🎉 [TAKE PROFIT TERCAPAI] {coin} ({mode_slot}) terjual di Rp{harga_sekarang:,.0f} "
                    f"(+{kenaikan_skrg_pct*100:.2f}%). Profit Bersih (potong fee+pajak): +Rp{profit_bersih:,.0f}!"
                )
                continue

            # 2. Cek apakah menyentuh Stop Loss (SL) atau Trailing Stop Loss yang sudah dinaikkan
            if harga_sekarang <= slot["sl_price_idr"]:
                hasil_pct = (harga_sekarang - slot["entry_price_idr"]) / slot["entry_price_idr"]
                pnl_bersih = round(slot["capital_idr"] * (hasil_pct - FEE_ROUNDTRIP_TAKER_PCT), 0)
                state["realized_profit_today_idr"] += pnl_bersih
                state["completed_trades_today"] += 1
                label_sl = "TRAILING PROFIT TERKUNCI CAIR" if pnl_bersih > 0 else "STOP LOSS PENYELAMAT"
                log_aksi.append(
                    f"🛡️ [{label_sl}] {coin} ({mode_slot}) dieksekusi di Rp{harga_sekarang:,.0f} "
                    f"(Batas SL: Rp{slot['sl_price_idr']:,.0f}). Hasil Bersih (potong fee+pajak): Rp{pnl_bersih:,.0f}."
                )
                continue

            # 3. FITUR DYNAMIC STEP-UP TRAILING PROFIT LOCK & SMART EARLY TP (SUDAH HITUNG PAJAK & FEE!)
            # Tahap 3A: Harga sudah naik >= +2.8% -> Kunci SL di +2.30% (Profit bersih terkunci ~ +1.75%)
            if kenaikan_skrg_pct >= 0.028:
                sl_target = round(slot["entry_price_idr"] * (1.0 + FEE_ROUNDTRIP_TAKER_PCT + 0.0175), 0)
                if sl_target > slot["sl_price_idr"]:
                    slot["sl_price_idr"] = sl_target
                    log_aksi.append(
                        f"🔒 [TRAILING LOCK LEVEL 3] {coin} naik +{kenaikan_skrg_pct*100:.2f}%! SL dikunci di Rp{sl_target:,.0f} (+2.30%, jaminan untung bersih +1.75% setelah pajak/fee)."
                    )

            # Tahap 3B: Harga sudah naik >= +2.2% -> Cek RSI dulu! Jika RSI jenuh (>=68), langsung TP di +2.2%!
            # Jika RSI masih kuat (<68), kunci SL di +1.60% (Profit bersih terkunci ~ +1.05% setelah pajak/fee)
            elif kenaikan_skrg_pct >= 0.022:
                if rsi_sekarang >= 68.0 or tren_sekarang != "UPTREND":
                    profit_bersih = round(slot["capital_idr"] * (kenaikan_skrg_pct - FEE_ROUNDTRIP_MAKER_PCT), 0)
                    state["realized_profit_today_idr"] += profit_bersih
                    state["completed_trades_today"] += 1
                    log_aksi.append(
                        f"⚡ [SMART EARLY TP +2.2%] {coin} sudah naik +{kenaikan_skrg_pct*100:.2f}% dan analisis mendeteksi RSI mulai jenuh ({rsi_sekarang}). "
                        f"Bot langsung bungkus TP sekarang! Profit Bersih: +Rp{profit_bersih:,.0f}."
                    )
                    continue
                else:
                    sl_target = round(slot["entry_price_idr"] * (1.0 + FEE_ROUNDTRIP_TAKER_PCT + 0.0105), 0)  # ~ +1.60%
                    if sl_target > slot["sl_price_idr"]:
                        slot["sl_price_idr"] = sl_target
                        log_aksi.append(
                            f"🔒 [TRAILING LOCK LEVEL 2 (+1.60%)] {coin} naik +{kenaikan_skrg_pct*100:.2f}% & tren masih kuat (RSI {rsi_sekarang}). "
                            f"SL dinaikkan ke Rp{sl_target:,.0f} (mengunci untung bersih > +1.05% setelah pajak/fee sambil mengejar +3.5%)!"
                        )

            # Tahap 3C: Harga sudah naik >= +1.5% -> Kunci SL di +0.95% (Menutup 0.55% pajak/fee + untung bersih +0.40%)
            elif kenaikan_skrg_pct >= 0.015:
                sl_target = round(slot["entry_price_idr"] * (1.0 + FEE_ROUNDTRIP_TAKER_PCT + 0.0040), 0)  # ~ +0.95%
                if sl_target > slot["sl_price_idr"]:
                    slot["sl_price_idr"] = sl_target
                    log_aksi.append(
                        f"🔒 [TRAILING LOCK LEVEL 1 (+0.95%)] {coin} naik +{kenaikan_skrg_pct*100:.2f}%. "
                        f"SL dinaikkan ke Rp{sl_target:,.0f} (100% menutup pajak/fee + kunci untung bersih +0.40%)."
                    )

            # 4. EVALUASI DINAMIS MENDEKATI 48 JAM (MULAI DI 40 JAM!)
            if umur_hold_jam >= PRE_TIMESTOP_HOURS:
                # Hitung target TP dinamis berdasarkan tenaga ATR pasar saat itu (minimal +1.0% s/d +2.0%)
                tp_dinamis_40h_pct = min(max(potensi_naik_pct, 0.010), 0.022)

                # Jika di 40-48 jam tren masih mendukung & belum sampai target dinamis, sesuaikan TP ke angka realistis tersebut (+1.0% atau lebih)
                if umur_hold_jam < FINAL_TIMESTOP_HOURS:
                    if tren_sekarang == "UPTREND" and rsi_sekarang < 65:
                        tp_baru_realistis = round(slot["entry_price_idr"] * (1.0 + tp_dinamis_40h_pct), 0)
                        if tp_baru_realistis < slot["tp_price_idr"]:
                            slot["tp_price_idr"] = tp_baru_realistis
                        log_aksi.append(
                            f"🕒 [ANALISA 40 JAM - OPTIMASI TP] {coin} sudah ditahan {umur_hold_jam:.1f} jam. Analisis pasar masih {tren_sekarang} (RSI {rsi_sekarang}), "
                            f"target TP disesuaikan secara dinamis ke +{tp_dinamis_40h_pct*100:.2f}% (Rp{slot['tp_price_idr']:,.0f}) agar tercapai sebelum 48 jam!"
                        )
                    elif kenaikan_skrg_pct >= 0.0085:
                        # Jika analisis di 40 jam menunjukkan tren sudah lemah dan tidak mungkin naik ke 1%+, langsung bungkus di >= +0.85%!
                        profit_bersih = round(slot["capital_idr"] * (kenaikan_skrg_pct - FEE_ROUNDTRIP_MAKER_PCT), 0)
                        state["realized_profit_today_idr"] += profit_bersih
                        state["completed_trades_today"] += 1
                        log_aksi.append(
                            f"🕒 [ANALISA 40 JAM - KELUAR CERDAS] {coin} ditahan {umur_hold_jam:.1f} jam & analisis tren melemah ({tren_sekarang}). "
                            f"Langsung bungkus di +{kenaikan_skrg_pct*100:.2f}% (Profit Bersih: +Rp{profit_bersih:,.0f})!"
                        )
                        continue

                # Jika sudah genap >= 48 Jam dan belum tembus 1%+, bungkus di >= +0.80% agar modal berputar
                else:
                    if kenaikan_skrg_pct >= 0.0080:
                        profit_bersih = round(slot["capital_idr"] * (kenaikan_skrg_pct - FEE_ROUNDTRIP_MAKER_PCT), 0)
                        state["realized_profit_today_idr"] += profit_bersih
                        state["completed_trades_today"] += 1
                        log_aksi.append(
                            f"⏱️ [TIME-STOP 48 JAM SELESAI] {coin} mencapai batas 48 jam di +{kenaikan_skrg_pct*100:.2f}%. "
                            f"Ditutup untung bersih +Rp{profit_bersih:,.0f} untuk diputar ke koin baru!"
                        )
                        continue

            log_aksi.append(
                f"🎯 [KAWAL POSISI AKTIF] {coin} ({mode_slot}, {umur_hold_jam:.1f}j) | Beli: Rp{slot['entry_price_idr']:,.0f} | "
                f"Sekarang: Rp{harga_sekarang:,.0f} ({kenaikan_skrg_pct*100:+.2f}%) | TP: Rp{slot['tp_price_idr']:,.0f} | SL: Rp{slot['sl_price_idr']:,.0f}."
            )
            slot_tetap_aktif.append(slot)

    state["active_slots"] = slot_tetap_aktif
    return state, log_aksi, ada_anggaran_batal_entry

# ==============================================================================
# BAGIAN 4: ALOKASI MODAL MENGANGGUR BERDASARKAN HASIL ANALISIS TERBARU
# ==============================================================================
def kelola_anggaran_kosong_dengan_analisa(state, peta_analisa):
    """
    Setiap kali ada anggaran menganggur (baik karena slot awal kosong, habis TP,
    atau baru saja ada koin yang batal entry setelah >6 jam), bot langsung
    menggunakan hasil analisis pasar terbaru untuk membuka posisi terbaik!
    """
    modal_sedang_terpakai = sum(slot["capital_idr"] for slot in state["active_slots"])
    sisa_jatah_modal_bot = max(0.0, MAX_BOT_CAPITAL_IDR - modal_sedang_terpakai)
    jumlah_slot_kosong = int(sisa_jatah_modal_bot // SLOT_SIZE_IDR)

    if jumlah_slot_kosong <= 0:
        return state, [
            f"[MODAL BOT PENUH TERKELOLA] Rp{modal_sedang_terpakai:,.0f} dari batas Rp{MAX_BOT_CAPITAL_IDR:,.0f} sedang aktif bekerja."
        ]

    kandidat_urut = sorted(
        [v for v in peta_analisa.values() if v["gaya"] != "WAIT_OVERBOUGHT"],
        key=lambda x: x["skor"],
        reverse=True
    )

    log_alokasi = []
    slot_terpasang = 0

    for kandidat in kandidat_urut:
        if slot_terpasang >= jumlah_slot_kosong:
            break
        coin = kandidat["coin"]
        # Maksimal 2 slot per koin agar terdiversifikasi
        if sum(1 for s in state["active_slots"] if s["coin"] == coin) >= 2:
            continue

        gaya = kandidat["gaya"]
        entry_idr = kandidat["entry_ideal_idr"]
        tp_pct = TP_SNIPER_BASE_PCT if gaya == "SNIPER" else TP_GRID_BASE_PCT
        sl_pct = SL_SNIPER_BASE_PCT if gaya == "SNIPER" else SL_GRID_BASE_PCT

        slot_baru = {
            "coin": coin,
            "style": gaya,
            "status": "WAITING_BUY",
            "capital_idr": SLOT_SIZE_IDR,
            "entry_price_idr": entry_idr,
            "tp_price_idr": round(entry_idr * (1.0 + tp_pct), 0),
            "sl_price_idr": round(entry_idr * (1.0 - sl_pct), 0),
            "rsi_at_entry": kandidat["rsi"],
            "timestamp": time.time()
        }
        state["active_slots"].append(slot_baru)
        slot_terpasang += 1
        log_alokasi.append(
            f"🚀 [ALOKASI SLOT BARU - {gaya}] {coin} (Skor {kandidat['skor']}, {kandidat['tren']}, RSI {kandidat['rsi']}) | "
            f"Modal: Rp{SLOT_SIZE_IDR:,.0f} | Limit Buy: Rp{entry_idr:,.0f} | TP: Rp{slot_baru['tp_price_idr']:,.0f} | SL: Rp{slot_baru['sl_price_idr']:,.0f}"
        )

    return state, log_alokasi

# ==============================================================================
# BAGIAN 5: LAPORAN OTOMATIS KE GOOGLE SHEETS (WEBHOOK TAB 4)
# ==============================================================================
def lapor_ke_google_sheets(state, semua_log):
    ringkasan_slot = ", ".join(
        [f"{s['coin']}[{s['style']}:{s['status']}@Rp{s['entry_price_idr']:,.0f}->TP:Rp{s['tp_price_idr']:,.0f}]" for s in state["active_slots"]]
    ) or "Semua slot kosong"
    catatan_lengkap = " | ".join(semua_log)[:480]

    payload = {
        "tanggal": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pasangan": f"HYBRID DINAMIS ({len(state['active_slots'])} Slot)",
        "modal_aktif_idr": sum(s["capital_idr"] for s in state["active_slots"]),
        "harga_acuan_idr": MAX_BOT_CAPITAL_IDR,
        "jumlah_grid_tereksekusi": state["completed_trades_today"],
        "profit_terealisasi_idr": state["realized_profit_today_idr"],
        "floating_pnl_idr": 0,
        "tren_1h": ringkasan_slot,
        "rsi_14": "Auto-Analyzed",
        "analisis_ai_gemini": catatan_lengkap
    }

    print("=== RINGKASAN EKSEKUSI SMART DYNAMIC HYBRID BOT ===")
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

if __name__ == "__main__":
    state = muat_state_bot()
    harga_live = ambil_harga_idr_semua_koin()

    # 1. ANALISIS PASAR TERLEBIH DAHULU (Analyze-Before-Act)
    peta_analisa_pasar = analisa_teknikal_lengkap_pasar(harga_live)

    # 2. Evaluasi posisi aktif, Trailing Lock bertahap (+0.95% / +1.60% / +2.30%),
    #    Evaluasi 40 jam -> 48 jam, dan Evaluasi antrean > 6 jam
    state, log_kawal, ada_batal_entry = evaluasi_dan_kawal_posisi_dinamis(state, peta_analisa_pasar)

    # 3. Jika ada anggaran menganggur (termasuk dari antrean yang baru dibatalkan),
    #    langsung kelola ke peluang terbaik hasil analisis pasar!
    state, log_alokasi = kelola_anggaran_kosong_dengan_analisa(state, peta_analisa_pasar)

    simpan_state_bot(state)
    lapor_ke_google_sheets(state, log_kawal + log_alokasi)
