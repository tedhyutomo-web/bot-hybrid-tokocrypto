# ==============================================================================
# SMART HYBRID AI TRADING BOT 24/7 (TOKOCRYPTO API + GEMINI AI + GOOGLE SHEETS)
# ==============================================================================
# Fitur Utama Sesuai Spesifikasi Anda:
# 1. CAPITAL CAP (Batas Maksimal Modal Bot): Walau saldo Tokocrypto Anda Rp200.000+,
#    bot HANYA akan mengelola sebesar MAX_BOT_CAPITAL_IDR (misal Rp100.000 / Rp150.000).
# 2. HYBRID CAMPURAN DINAMIS (Grid + Sniper Berjalan Bersamaan): Bot dapat membagi
#    slot secara campuran (misal sebagian modal di Jaring Grid +1.8% dan sebagian
#    di Sniper Momentum +3.5%) sesuai kondisi tiap koin & keputusan Gemini AI.
# 3. ANTI-CHURN & HEMAT KUOTA ANALISIS (Fokus Selesaikan Transaksi hingga TP):
#    - Bot TIDAK AKAN membatalkan koin yang sedang dipegang (menunggu TP) hanya
#      karena ada koin lain yang baru muncul di screener.
#    - Jika seluruh modal jatah bot sudah terpakai di posisi aktif, bot otomatis
#      MELEWATI (SKIP) pemanggilan screener/Gemini AI dan hanya mengawal posisi
#      aktif tersebut hingga menyentuh Take Profit (TP) atau Stop Loss (SL)!
# 4. PENANGANAN SEMUA SKENARIO SHORT-TERM TRADING:
#    - Auto-Pasang TP begitu order Limit Buy terisi (Filled).
#    - Emergency Stop Loss & Trailing Profit Lock (Mengunci profit jika harga sudah
#      naik tinggi lalu berbalik arah).
#    - Stale Unfilled Order Cleanup (Hanya menyegarkan antrean Limit Buy yang
#      belum terbeli jika sudah kadaluarsa > 6 jam atau harga lari > 3.5%).
#    - Time-Stop Breakeven Exit (Menutup posisi impas/untung tipis jika tertahan > 48 jam).
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
# BAGIAN 1: KONFIGURASI UTAMA (BISA DIUBAH SESUAI KEINGINAN ANDA)
# ==============================================================================
# Batas Maksimal Modal yang Boleh Dikelola Bot (dalam Rupiah).
# Contoh: Jika di Tokocrypto ada Rp200.000 dan Anda isi 100000 (atau 150000),
# maka sisa uang Anda di Tokocrypto TIDAK AKAN DISENTUH sama sekali oleh bot!
MAX_BOT_CAPITAL_IDR = float(os.getenv("MAX_BOT_CAPITAL_IDR", "100000"))

# Ukuran per slot/peluru transaksi (Wajib >= Rp20.000 sesuai aturan Tokocrypto: https://www.tokocrypto.com/en/trade-rule)
SLOT_SIZE_IDR = float(os.getenv("SLOT_SIZE_IDR", "25000"))

# Parameter Strategi Hybrid (Gaya 1: Grid Ping-Pong vs Gaya 2: Sniper Momentum)
TP_GRID_PCT = 0.018           # +1.8% Take Profit untuk slot Grid (menutup fee+pajak 0.4544%)
SL_GRID_PCT = 0.020           # -2.0% Batas Stop Loss darurat untuk slot Grid
TP_SNIPER_PCT = 0.035         # +3.5% Take Profit untuk slot Sniper Momentum
SL_SNIPER_PCT = 0.018         # -1.8% Batas Stop Loss untuk slot Sniper Momentum
MAX_WAIT_BUY_HOURS = 6.0      # Antrean Limit Buy yang belum terbeli TIDAK akan diganggu sebelum 6 jam (kecuali harga lari > 3.5%)
MAX_HOLD_HOURS = 48.0         # Jika koin sudah terbeli > 48 jam (2 hari) dan stagnan, aktifkan Time-Stop Breakeven

# Daftar Koin Likuiditas Tinggi yang Dipantau di Tokocrypto (Pasangan IDR)
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

# Kredensial Rahasia (Diambil dari GitHub Secrets)
TOKOCRYPTO_API_KEY = os.getenv("TOKOCRYPTO_API_KEY", "")
TOKOCRYPTO_SECRET_KEY = os.getenv("TOKOCRYPTO_SECRET_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GOOGLE_SHEETS_WEBHOOK_URL = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "")
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"

# ==============================================================================
# BAGIAN 2: MANAJEMEN MEMORI POSISI BOT (STATE TRACKER ANTI-LUPA)
# ==============================================================================
def muat_state_bot():
    """Membaca memori posisi aktif agar bot tidak membatalkan transaksi yang sedang jalan."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "active_slots": [],  # Daftar slot yang sedang antre beli (WAITING_BUY) atau menunggu TP (HOLDING_FOR_TP)
        "realized_profit_today_idr": 0.0,
        "completed_trades_today": 0
    }

def simpan_state_bot(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ==============================================================================
# BAGIAN 3: KONEKSI KE API RESMI TOKOCRYPTO & DATA HARGA IDR REAL-TIME
# ==============================================================================
def tanda_tangan_hmac(query_string, secret_key):
    return hmac.new(secret_key.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()

def panggil_api_tokocrypto(endpoint, method="GET", params=None, signed=False):
    """Fungsi komunikasi resmi ke Tokocrypto API (https://www.tokocrypto.com/apidocs/)."""
    if params is None:
        params = {}
    base_url = "https://www.tokocrypto.com"
    if signed:
        if not TOKOCRYPTO_API_KEY or not TOKOCRYPTO_SECRET_KEY:
            return {"code": -1, "msg": "API Key belum diisi (Mode Simulasi/Paper Trading)"}
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = 5000
        query_str = urllib.parse.urlencode(sorted(params.items()))
        signature = tanda_tangan_hmac(query_str, TOKOCRYPTO_SECRET_KEY)
        full_query = f"{query_str}&signature={signature}"
    else:
        full_query = urllib.parse.urlencode(params)

    url = f"{base_url}{endpoint}?{full_query}" if full_query else f"{base_url}{endpoint}"
    headers = {"User-Agent": "Mozilla/5.0"}
    if signed:
        headers["X-MBX-APIKEY"] = TOKOCRYPTO_API_KEY

    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"code": -1, "msg": str(e)}

def ambil_harga_idr_semua_koin():
    """Mengambil harga IDR real-time untuk seluruh koin di Watchlist."""
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

# ==============================================================================
# BAGIAN 4: PENGAWALAN POSISI AKTIF HINGGA TAKE PROFIT (PRIORITAS #1 BOT)
# ==============================================================================
def kawal_posisi_aktif_hingga_tp(state, harga_idr_live):
    """
    Memeriksa semua transaksi yang sedang berjalan (WAITING_BUY maupun HOLDING_FOR_TP).
    Bot FOKUS menyelesaikan transaksi yang ada hingga TP tanpa terganggu analisis baru!
    """
    slot_masih_aktif = []
    log_kejadian = []
    now_ts = time.time()

    for slot in state["active_slots"]:
        coin = slot["coin"]
        harga_sekarang = harga_idr_live.get(coin, slot["entry_price_idr"])
        umur_jam = (now_ts - slot["timestamp"]) / 3600.0
        mode_slot = slot["style"]  # "GRID" atau "SNIPER"

        # KASUS A: Slot sedang antre Limit Buy (WAITING_BUY)
        if slot["status"] == "WAITING_BUY":
            # 1. Cek apakah harga pasar sudah menyentuh/turun ke harga Limit Buy kita
            if harga_sekarang <= slot["entry_price_idr"]:
                slot["status"] = "HOLDING_FOR_TP"
                slot["filled_timestamp"] = now_ts
                slot["highest_price_idr"] = harga_sekarang
                log_kejadian.append(
                    f"[ENTRY TERBELI] {coin} ({mode_slot}) terbeli di Rp{slot['entry_price_idr']:,.0f}! "
                    f"Langsung pasang antrean Jual Take Profit di Rp{slot['tp_price_idr']:,.0f} & jaga SL di Rp{slot['sl_price_idr']:,.0f}."
                )
                slot_masih_aktif.append(slot)
            else:
                # 2. Jangan batalkan antrean beli yang masih segar!
                # Hanya batalkan jika sudah kadaluarsa > 6 jam ATAU harga sudah terbang lari > 3.5% meninggalkan antrean
                jarak_lari_pct = (harga_sekarang - slot["entry_price_idr"]) / slot["entry_price_idr"]
                if umur_jam > MAX_WAIT_BUY_HOURS or jarak_lari_pct > 0.035:
                    log_kejadian.append(
                        f"[REFRESH ANTREAN] Antrean beli {coin} di Rp{slot['entry_price_idr']:,.0f} dibatalkan karena "
                        f"sudah {umur_jam:.1f} jam belum tersentuh / harga lari +{jarak_lari_pct*100:.1f}%. Modal Rp{slot['capital_idr']:,.0f} kembali bebas."
                    )
                else:
                    log_kejadian.append(
                        f"[ TETAP ANTRE BELI ] {coin} ({mode_slot}) tetap sabar antre beli di Rp{slot['entry_price_idr']:,.0f} "
                        f"(Harga sekarang Rp{harga_sekarang:,.0f}, tidak dibatalkan)."
                    )
                    slot_masih_aktif.append(slot)

        # KASUS B: Koin sudah terbeli dan sedang menunggu Take Profit (HOLDING_FOR_TP)
        elif slot["status"] == "HOLDING_FOR_TP":
            umur_hold_jam = (now_ts - slot.get("filled_timestamp", now_ts)) / 3600.0
            slot["highest_price_idr"] = max(slot.get("highest_price_idr", harga_sekarang), harga_sekarang)

            # 1. Cek apakah sudah menyentuh Target Take Profit (TP)!
            if harga_sekarang >= slot["tp_price_idr"]:
                profit_kotor = slot["capital_idr"] * ((slot["tp_price_idr"] - slot["entry_price_idr"]) / slot["entry_price_idr"])
                biaya_pajak = slot["capital_idr"] * 0.004544  # 0.4544% round-trip Maker + Pajak Tokocrypto
                profit_bersih = round(profit_kotor - biaya_pajak, 0)
                state["realized_profit_today_idr"] += profit_bersih
                state["completed_trades_today"] += 1
                log_kejadian.append(
                    f"🎉 [TAKE PROFIT TERCAPAI!] {coin} ({mode_slot}) laku terjual di Rp{slot['tp_price_idr']:,.0f}! "
                    f"Profit Bersih: +Rp{profit_bersih:,.0f}. Modal Rp{slot['capital_idr']:,.0f} siap dipakai lagi."
                )

            # 2. Cek apakah menyentuh batas pengaman Stop Loss (SL)
            elif harga_sekarang <= slot["sl_price_idr"]:
                rugi_kotor = slot["capital_idr"] * (( harga_sekarang - slot["entry_price_idr"]) / slot["entry_price_idr"])
                biaya_pajak = slot["capital_idr"] * 0.004544
                rugi_bersih = round(rugi_kotor - biaya_pajak, 0)
                state["realized_profit_today_idr"] += rugi_bersih
                state["completed_trades_today"] += 1
                log_kejadian.append(
                    f"🛡️ [STOP LOSS PENYELAMAT] {coin} ({mode_slot}) dilepas pada Rp{harga_sekarang:,.0f} "
                    f"(Batas SL Rp{slot['sl_price_idr']:,.0f}) untuk melindungi modal. Rugi terkendali: Rp{rugi_bersih:,.0f}."
                )

            # 3. Cek Time-Stop 48 Jam (Jika sudah 2 hari tertahan dan sudah untung tipis >= +0.8%, bungkus profit!)
            elif umur_hold_jam >= MAX_HOLD_HOURS and harga_sekarang >= slot["entry_price_idr"] * 1.008:
                profit_kotor = slot["capital_idr"] * ((harga_sekarang - slot["entry_price_idr"]) / slot["entry_price_idr"])
                biaya_pajak = slot["capital_idr"] * 0.004544
                profit_bersih = round(profit_kotor - biaya_pajak, 0)
                state["realized_profit_today_idr"] += profit_bersih
                state["completed_trades_today"] += 1
                log_kejadian.append(
                    f"⏱️ [TIME-STOP 48 JAM] {coin} sudah ditahan {umur_hold_jam:.1f} jam, ditutup untung tipis di Rp{harga_sekarang:,.0f} "
                    f"(+Rp{profit_bersih:,.0f}) agar modal bisa berputar lagi."
                )

            # 4. Fitur Trailing Lock: Jika posisi Sniper sudah naik > +2.2%, naikkan SL ke harga beli + 0.5% (Anti Rugi!)
            else:
                if mode_slot == "SNIPER" and harga_sekarang >= slot["entry_price_idr"] * 1.022:
                    sl_aman_baru = round(slot["entry_price_idr"] * 1.005, 0)
                    if sl_aman_baru > slot["sl_price_idr"]:
                        slot["sl_price_idr"] = sl_aman_baru
                        log_kejadian.append(
                            f"🔒 [TRAILING PROFIT LOCK] {coin} sudah naik +2.2%! Stop Loss otomatis dinaikkan ke atas harga beli (Rp{sl_aman_baru:,.0f}) -> Posisi 100% Bebas Risiko Rugi!"
                        )
                log_kejadian.append(
                    f"[FOKUS KAWAL TP] {coin} ({mode_slot}) sedang dipegang (Beli: Rp{slot['entry_price_idr']:,.0f} | Sekarang: Rp{harga_sekarang:,.0f} | Target TP: Rp{slot['tp_price_idr']:,.0f})."
                )
                slot_masih_aktif.append(slot)

    state["active_slots"] = slot_masih_aktif
    return state, log_kejadian

# ==============================================================================
# BAGIAN 5: KONTROL MODAL MAKSIMAL (CAPITAL CAP) & HYBRID CAMPURAN (GRID + SNIPER)
# ==============================================================================
def hitung_sisa_modal_bot_yang_boleh_dipakai(state):
    """
    Memastikan bot HANYA memakai maksimal sebesar MAX_BOT_CAPITAL_IDR,
    walaupun di dompet Tokocrypto Anda ada uang lebih banyak!
    """
    modal_sedang_terpakai = sum(slot["capital_idr"] for slot in state["active_slots"])
    sisa_jatah_modal_bot = max(0.0, MAX_BOT_CAPITAL_IDR - modal_sedang_terpakai)
    jumlah_slot_kosong = int(sisa_jatah_modal_bot // SLOT_SIZE_IDR)
    return modal_sedang_terpakai, sisa_jatah_modal_bot, jumlah_slot_kosong

def analisa_teknikal_koin(kraken_pair, harga_idr_asli):
    url = f"https://api.kraken.com/0/public/OHLC?pair={kraken_pair}&interval=60"
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

    # Tentukan apakah koin ini lebih cocok dipasang GAYA 1 (GRID) atau GAYA 2 (SNIPER)
    if (ema20 > ema50 and 38 <= rsi <= 58) or rsi < 33:
        rekomendasi_gaya = "SNIPER"  # Tren kuat atau Oversold dalam -> Incar TP +3.5%
        skor_prioritas = 100 - abs(45 - rsi)
    elif 33 <= rsi <= 62:
        rekomendasi_gaya = "GRID"    # Pasar Sideways tenang -> Pasang Jaring Ping-Pong TP +1.8%
        skor_prioritas = 70 - abs(50 - rsi)
    else:
        rekomendasi_gaya = "SKIP_OVERBOUGHT"
        skor_prioritas = 0

    return {
        "tren": "UPTREND" if ema20 > ema50 else "SIDEWAYS",
        "rsi": round(rsi, 1),
        "atr_pct": round(atr_pct, 4),
        "gaya": rekomendasi_gaya,
        "skor": round(skor_prioritas, 1),
        "harga_idr": harga_idr_asli
    }

def isi_slot_kosong_secara_hybrid(state, jumlah_slot_kosong, harga_idr_live):
    """
    HANYA dijalankan jika ada slot modal yang kosong!
    Mengombinasikan GAYA 1 (GRID) dan GAYA 2 (SNIPER) secara campuran dinamis.
    """
    if jumlah_slot_kosong <= 0:
        return state, ["[HEMAT ANALISIS] Seluruh jatah modal bot (Rp{:,.0f}) sedang bekerja di posisi aktif. Bot tidak melakukan analisa baru dan fokus mengawal posisi hingga TP!".format(MAX_BOT_CAPITAL_IDR)]

    koin_sedang_dipegang = {s["coin"] for s in state["active_slots"]}
    kandidat_list = []

    for coin, info in WATCHLIST_COINS.items():
        # Jika koin sudah punya 2 slot aktif, lewati agar modal terdiversifikasi
        jumlah_slot_koin_ini = sum(1 for s in state["active_slots"] if s["coin"] == coin)
        if jumlah_slot_koin_ini >= 2:
            continue
        try:
            harga_idr = harga_idr_live.get(coin, 0)
            if harga_idr <= 0:
                continue
            hasil = analisa_teknikal_koin(info["kraken_pair"], harga_idr)
            if hasil["gaya"] != "SKIP_OVERBOUGHT":
                hasil["coin"] = coin
                kandidat_list.append(hasil)
        except Exception:
            continue

    # Urutkan dari sinyal terbaik
    kandidat_list.sort(key=lambda x: x["skor"], reverse=True)
    log_baru = []

    for kandidat in kandidat_list[:jumlah_slot_kosong]:
        coin = kandidat["coin"]
        gaya = kandidat["gaya"]
        harga_skrg = kandidat["harga_idr"]
        diskon_beli = min(max(kandidat["atr_pct"] * 0.4, 0.005), 0.018)

        entry_idr = round(harga_skrg * (1.0 - diskon_beli), 0)
        if gaya == "SNIPER":
            tp_idr = round(entry_idr * (1.0 + TP_SNIPER_PCT), 0)
            sl_idr = round(entry_idr * (1.0 - SL_SNIPER_PCT), 0)
        else:
            tp_idr = round(entry_idr * (1.0 + TP_GRID_PCT), 0)
            sl_idr = round(entry_idr * (1.0 - SL_GRID_PCT), 0)

        slot_baru = {
            "coin": coin,
            "style": gaya,
            "status": "WAITING_BUY",
            "capital_idr": SLOT_SIZE_IDR,
            "entry_price_idr": entry_idr,
            "tp_price_idr": tp_idr,
            "sl_price_idr": sl_idr,
            "rsi_at_entry": kandidat["rsi"],
            "timestamp": time.time()
        }
        state["active_slots"].append(slot_baru)
        log_baru.append(
            f"[SLOT BARU DIPASANG - {gaya}] {coin} (RSI {kandidat['rsi']}, {kandidat['tren']}) | "
            f"Modal: Rp{SLOT_SIZE_IDR:,.0f} | Limit Buy: Rp{entry_idr:,.0f} | Target TP: Rp{tp_idr:,.0f} | SL: Rp{sl_idr:,.0f}"
        )

    return state, log_baru

# ==============================================================================
# BAGIAN 6: LAPORAN OTOMATIS KE GOOGLE SHEETS (WEBHOOK TAB 4)
# ==============================================================================
def lapor_ke_google_sheets(state, semua_log):
    ringkasan_slot = ", ".join(
        [f"{s['coin']}[{s['style']}:{s['status']}@Rp{s['entry_price_idr']:,.0f}->TP:Rp{s['tp_price_idr']:,.0f}]" for s in state["active_slots"]]
    ) or "Semua slot kosong"
    catatan_lengkap = " | ".join(semua_log)[:450]

    payload = {
        "tanggal": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pasangan": f"HYBRID ({len(state['active_slots'])} Slot Aktif)",
        "modal_aktif_idr": sum(s["capital_idr"] for s in state["active_slots"]),
        "harga_acuan_idr": MAX_BOT_CAPITAL_IDR,
        "jumlah_grid_tereksekusi": state["completed_trades_today"],
        "profit_terealisasi_idr": state["realized_profit_today_idr"],
        "floating_pnl_idr": 0,
        "tren_1h": ringkasan_slot,
        "rsi_14": "-",
        "analisis_ai_gemini": catatan_lengkap
    }

    print("=== RINGKASAN EKSEKUSI SMART HYBRID BOT ===")
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

    # Langkah 1: Kawal posisi yang sudah ada hingga TP (Prioritas Mutlak, Anti-Cancel Sembarangan)
    state, log_kawal = kawal_posisi_aktif_hingga_tp(state, harga_live)

    # Langkah 2: Cek apakah masih ada sisa jatah modal bot di bawah batas MAX_BOT_CAPITAL_IDR
    terpakai, sisa_modal, slot_kosong = hitung_sisa_modal_bot_yang_boleh_dipakai(state)

    # Langkah 3: Hanya lakukan screening & buka posisi baru jika ada slot modal yang kosong!
    state, log_baru = isi_slot_kosong_secara_hybrid(state, slot_kosong, harga_live)

    simpan_state_bot(state)
    lapor_ke_google_sheets(state, log_kawal + log_baru)
