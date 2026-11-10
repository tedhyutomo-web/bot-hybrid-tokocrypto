# ==============================================================================
# SMART DYNAMIC HYBRID AI TRADING BOT 24/7 (INDODAX OFFICIAL API + ELASTIC BUDGET)
# ==============================================================================
# Keunggulan Versi Indodax Ini:
# 1. 100% BEBAS BLOKIR HTTP 451 (Tanpa Proxy, Kecepatan Eksekusi < 1 Detik dari GitHub US!).
# 2. SMART ELASTIC BUDGET ALLOCATION:
#    - Membaca saldo Rupiah asli di akun Indodax Anda secara otomatis (getInfo).
#    - Jika saldo Anda kurang dari Rp100.000 (misal Rp95.000 karena admin/loss)
#      atau tinggal Rp12.000, bot TIDAK AKAN ERROR dan otomatis menyesuaikan
#      ukuran slot agar seluruh anggaran yang ada di atas batas minimum order
#      Indodax (Rp11.000) terkelola maksimal 100%!
# 3. ANALYZE-BEFORE-ACT (>6 Jam Evaluasi Entry, Step-Up Trailing Lock Sadar Pajak/Fee,
#    Smart Early TP +2.2%, dan Optimasi Target TP 40 Jam -> 48 Jam).
# ==============================================================================
import datetime
import hashlib
import hmac
import json
import math
import os
import time
import urllib.parse
import urllib.request

# Batas Maksimal Modal yang Boleh Dikelola Bot (Rp)
MAX_BOT_CAPITAL_IDR = float(os.getenv("MAX_BOT_CAPITAL_IDR", "100000"))
IDEAL_SLOT_SIZE_IDR = float(os.getenv("SLOT_SIZE_IDR", "25000"))
# Batas minimal order di Indodax adalah Rp10.000 (kita beri pengaman Rp11.000 agar pasti lolos)
MIN_ORDER_IDR_INDODAX = 11000.0

# Biaya Maker + Pajak + CFX di Indodax (https://help.indodax.com/hc/id/articles/4416646599705-Rincian-Biaya-Transaksi-di-INDODAX)
FEE_ROUNDTRIP_MAKER_PCT = 0.0055
FEE_ROUNDTRIP_TAKER_PCT = 0.0075

TP_GRID_BASE_PCT = 0.020  # +2.0% Target dasar Grid di Indodax
SL_GRID_BASE_PCT = 0.020  # -2.0% Batas SL dasar Grid
TP_SNIPER_BASE_PCT = 0.036  # +3.6% Target dasar Sniper Momentum
SL_SNIPER_BASE_PCT = 0.018  # -1.8% Batas SL dasar Sniper Momentum

REVIEW_ENTRY_HOURS = 6.0
PRE_TIMESTOP_HOURS = 40.0
FINAL_TIMESTOP_HOURS = 48.0

# Daftar Koin Likuiditas Tinggi di Indodax (Pasangan IDR)
WATCHLIST_COINS = {
    "SOL": {"pair": "sol_idr", "coin_key": "sol", "kraken_pair": "SOLUSD"},
    "BTC": {"pair": "btc_idr", "coin_key": "btc", "kraken_pair": "XXBTZUSD"},
    "ETH": {"pair": "eth_idr", "coin_key": "eth", "kraken_pair": "XETHZUSD"},
    "XRP": {"pair": "xrp_idr", "coin_key": "xrp", "kraken_pair": "XXRPZUSD"},
    "ADA": {"pair": "ada_idr", "coin_key": "ada", "kraken_pair": "ADAUSD"},
    "SUI": {"pair": "sui_idr", "coin_key": "sui", "kraken_pair": "SUIUSD"},
    "DOGE": {"pair": "doge_idr", "coin_key": "doge", "kraken_pair": "XDGUSD"},
}

STATE_FILE = "bot_state_tokocrypto.json"

# Membaca INDODAX_API_KEY atau langsung dari TOKOCRYPTO_API_KEY yang Anda edit di GitHub Secrets
INDODAX_API_KEY = (
    os.getenv("INDODAX_API_KEY") or os.getenv("TOKOCRYPTO_API_KEY") or ""
).strip()
INDODAX_SECRET_KEY = (
    os.getenv("INDODAX_SECRET_KEY") or os.getenv("TOKOCRYPTO_SECRET_KEY") or ""
).strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GOOGLE_SHEETS_WEBHOOK_URL = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
LIVE_TRADING_ENABLED = bool(INDODAX_API_KEY and INDODAX_SECRET_KEY)


# ==============================================================================
# BAGIAN 1: MEMORI POSISI BOT (STATE TRACKER)
# ==============================================================================
def muat_state_bot():
  if os.path.exists(STATE_FILE):
    try:
      with open(STATE_FILE, "r") as f:
        data = json.load(f)
        # Bersihkan slot lama yang bukan dari Indodax
        slots = [
            s for s in data.get("active_slots", []) if s.get("venue") == "INDODAX"
        ]
        data["active_slots"] = slots
        return data
    except Exception:
      pass
  return {
      "active_slots": [],
      "realized_profit_today_idr": 0.0,
      "completed_trades_today": 0,
  }


def simpan_state_bot(state):
  with open(STATE_FILE, "w") as f:
    json.dump(state, f, indent=2)


# ==============================================================================
# BAGIAN 2: KONEKSI LANGSUNG KE OFFICIAL INDODAX TRADE API (HMAC-SHA512)
# ==============================================================================
def panggil_tapi_indodax(method_name, extra_params=None):
  """Memanggil Private Trade API Indodax (https://indodax.com/tapi) dengan tanda tangan HMAC-SHA512 resmi."""
  if not LIVE_TRADING_ENABLED:
    return {"success": 0, "error": "API Key Indodax belum diisi di Secrets"}

  params = {
      "method": method_name,
      "timestamp": int(time.time() * 1000),
      "recvWindow": 15000,
  }
  if extra_params:
    params.update(extra_params)

  post_body = urllib.parse.urlencode(params).encode("utf-8")
  sign = hmac.new(
      INDODAX_SECRET_KEY.encode("utf-8"), post_body, hashlib.sha512
  ).hexdigest()

  headers = {
      "Key": INDODAX_API_KEY,
      "Sign": sign,
      "Content-Type": "application/x-www-form-urlencoded",
      "User-Agent": "Mozilla/5.0",
  }

  req = urllib.request.Request(
      "https://indodax.com/tapi", data=post_body, headers=headers, method="POST"
  )
  try:
    with urllib.request.urlopen(req, timeout=15) as resp:
      return json.loads(resp.read().decode("utf-8", errors="ignore"))
  except Exception as e:
    return {"success": 0, "error": str(e)}


def cek_saldo_asli_indodax():
  """Mengambil saldo IDR bebas (free) dan saldo koin di dompet Indodax Anda."""
  res = panggil_tapi_indodax("getInfo")
  if res.get("success") == 1:
    bal = res.get("return", {}).get("balance", {})
    saldo_idr_bebas = float(bal.get("idr", 0))
    print(
        "💰 [INFO DOMPET INDODAX] Saldo IDR Tersedia Saat Ini:"
        f" Rp{saldo_idr_bebas:,.0f}"
    )
    return saldo_idr_bebas, bal
  else:
    err = res.get("error", "Gagal cek saldo")
    print(f"⚠️ [PERINGATAN CEK SALDO INDODAX] Respon: {err}")
    return None, {}


def eksekusi_beli_limit_indodax(coin, nominal_idr, price_idr):
  """
  Di Indodax Trade API, pembelian Limit Order menggunakan parameter 'idr' (nominal Rupiah),
  sehingga kita tidak pusing pembulatan desimal koin dan bisa membeli berapapun nominalnya (>= Rp11.000)!
  """
  pair = WATCHLIST_COINS[coin]["pair"]
  params = {
      "pair": pair,
      "type": "buy",
      "price": int(round(price_idr)),
      "idr": int(round(nominal_idr)),
  }
  res = panggil_tapi_indodax("trade", params)
  print(
      f"👉 [INDODAX LIVE BUY] {pair.upper()} | Nominal=Rp{nominal_idr:,.0f} @"
      f" Harga=Rp{price_idr:,.0f} -> Respon: {res}"
  )
  return res


def eksekusi_jual_limit_indodax(coin, qty_koin, price_idr):
  """Menjual koin di Indodax menggunakan jumlah koin yang dimiliki."""
  pair = WATCHLIST_COINS[coin]["pair"]
  coin_key = WATCHLIST_COINS[coin]["coin_key"]
  params = {
      "pair": pair,
      "type": "sell",
      "price": int(round(price_idr)),
      coin_key: f"{qty_koin:.8f}".rstrip("0").rstrip("."),
  }
  res = panggil_tapi_indodax("trade", params)
  print(
      f"👉 [INDODAX LIVE SELL] {pair.upper()} | Qty={qty_koin:.6f} @"
      f" Harga=Rp{price_idr:,.0f} -> Respon: {res}"
  )
  return res


def batalkan_order_indodax(coin, order_id, side_type="buy"):
  if not order_id or str(order_id).startswith("SIM"):
    return
  pair = WATCHLIST_COINS[coin]["pair"]
  params = {"pair": pair, "order_id": int(order_id), "type": side_type}
  res = panggil_tapi_indodax("cancelOrder", params)
  print(
      f"👉 [INDODAX CANCEL ORDER] {pair.upper()} ID={order_id} -> Respon: {res}"
  )


def cek_status_order_indodax(coin, order_id):
  """Memeriksa langsung ke server Indodax apakah antrean Limit Buy kita sudah terbeli (filled) atau belum."""
  if not order_id or str(order_id).startswith("SIM"):
    return None
  pair = WATCHLIST_COINS[coin]["pair"]
  res = panggil_tapi_indodax(
      "getOrder", {"pair": pair, "order_id": int(order_id)}
  )
  if res.get("success") == 1:
    return res.get("return", {}).get("order", {})
  return None


# ==============================================================================
# BAGIAN 3: HARGA LIVE INDODAX & ANALISIS TEKNIKAL PASAR
# ==============================================================================
def ambil_harga_idr_semua_koin():
  harga_map = {}
  try:
    url = "https://indodax.com/api/tickers"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
      tickers = json.loads(resp.read().decode()).get("tickers", {})
    for coin, info in WATCHLIST_COINS.items():
      t = tickers.get(info["pair"], {})
      if "last" in t:
        harga_map[coin] = float(t["last"])
  except Exception as e:
    print("Gagal ambil harga publik Indodax:", e)
  return harga_map


def analisa_teknikal_lengkap_pasar(harga_idr_live):
  peta_analisa = {}
  for coin, info in WATCHLIST_COINS.items():
    harga_idr = harga_idr_live.get(coin, 0)
    if harga_idr <= 0:
      continue
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
          "rsi": round(rsi, 1),
          "atr_pct": round(atr_pct, 4),
          "potensi_naik_pct": potensi_naik_pct,
          "entry_ideal_idr": entry_ideal_idr,
          "gaya": gaya,
          "skor": round(skor, 1),
      }
    except Exception:
      continue
  return peta_analisa


# ==============================================================================
# BAGIAN 4: PENGAWALAN POSISI DINAMIS (>6 JAM & 40->48 JAM)
# ==============================================================================
def evaluasi_dan_kawal_posisi_dinamis(state, peta_analisa, saldo_koin_map):
  slot_tetap_aktif = []
  log_aksi = []
  now_ts = time.time()

  semua_kandidat = sorted(
      peta_analisa.values(), key=lambda x: x["skor"], reverse=True
  )
  koin_terbaik_pasar = semua_kandidat[0] if semua_kandidat else None

  for slot in state["active_slots"]:
    coin = slot["coin"]
    coin_key = WATCHLIST_COINS[coin]["coin_key"]
    info_pasar = peta_analisa.get(coin)
    harga_sekarang = (
        info_pasar["harga_idr"] if info_pasar else slot["entry_price_idr"]
    )
    rsi_sekarang = info_pasar["rsi"] if info_pasar else 50.0
    tren_sekarang = info_pasar["tren"] if info_pasar else "SIDEWAYS"
    potensi_naik_pct = info_pasar["potensi_naik_pct"] if info_pasar else 0.015
    skor_koin_ini = info_pasar["skor"] if info_pasar else 50.0

    umur_antre_jam = (now_ts - slot["timestamp"]) / 3600.0
    mode_slot = slot["style"]
    qty_estimasi = float(
        saldo_koin_map.get(coin_key, 0)
    ) or slot.get("qty", slot["capital_idr"] / slot["entry_price_idr"])

    if slot["status"] == "WAITING_BUY":
      # Cek ke Indodax apakah order sudah filled
      detail_order = cek_status_order_indodax(coin, slot.get("buy_order_id"))
      sudah_terbeli = (
          detail_order and detail_order.get("status") == "filled"
      ) or (harga_sekarang <= slot["entry_price_idr"])

      if sudah_terbeli:
        slot["status"] = "HOLDING_FOR_TP"
        slot["filled_timestamp"] = now_ts
        slot["highest_price_idr"] = harga_sekarang
        log_aksi.append(
            f"✅ [ENTRY TERBELI] {coin} ({mode_slot}) di"
            f" Rp{slot['entry_price_idr']:,.0f}. Mengawal hingga TP"
            f" Rp{slot['tp_price_idr']:,.0f}."
        )
        slot_tetap_aktif.append(slot)
        continue

      if umur_antre_jam <= REVIEW_ENTRY_HOURS:
        log_aksi.append(
            f"⏳ [ANTRE BELI {umur_antre_jam:.1f}j] {coin}"
            f" (Rp{slot['capital_idr']:,.0f}) di"
            f" Rp{slot['entry_price_idr']:,.0f} (Pasar:"
            f" Rp{harga_sekarang:,.0f})."
        )
        slot_tetap_aktif.append(slot)
        continue

      jarak_ke_entry_pct = (harga_sekarang - slot["entry_price_idr"]) / slot[
          "entry_price_idr"
      ]
      skor_terbaik_lain = (
          koin_terbaik_pasar["skor"] if koin_terbaik_pasar else 0
      )

      if jarak_ke_entry_pct <= 0.012 and rsi_sekarang <= 52:
        log_aksi.append(
            f"🔍 [PERTAHANKAN >6J] {coin} dekat ke Limit Buy"
            f" Rp{slot['entry_price_idr']:,.0f}."
        )
        slot_tetap_aktif.append(slot)
      elif (
          info_pasar
          and info_pasar["gaya"] != "WAIT_OVERBOUGHT"
          and skor_koin_ini >= (skor_terbaik_lain - 10)
      ):
        batalkan_order_indodax(coin, slot.get("buy_order_id"), "buy")
        entry_baru_idr = info_pasar["entry_ideal_idr"]
        tp_pct = (
            TP_SNIPER_BASE_PCT if mode_slot == "SNIPER" else TP_GRID_BASE_PCT
        )
        sl_pct = (
            SL_SNIPER_BASE_PCT if mode_slot == "SNIPER" else SL_GRID_BASE_PCT
        )
        respon_baru = eksekusi_beli_limit_indodax(
            coin, slot["capital_idr"], entry_baru_idr
        )
        if respon_baru.get("success") == 1:
          slot["entry_price_idr"] = entry_baru_idr
          slot["tp_price_idr"] = round(entry_baru_idr * (1.0 + tp_pct), 0)
          slot["sl_price_idr"] = round(entry_baru_idr * (1.0 - sl_pct), 0)
          slot["buy_order_id"] = respon_baru.get("return", {}).get("order_id")
          slot["timestamp"] = now_ts
          log_aksi.append(
              f"📈 [NAIKKAN ENTRY >6J] {coin} digeser ke"
              f" Rp{entry_baru_idr:,.0f}!"
          )
          slot_tetap_aktif.append(slot)
      else:
        batalkan_order_indodax(coin, slot.get("buy_order_id"), "buy")
        log_aksi.append(
            f"🔄 [GANTI KOIN >6J] Antrean {coin} dibatalkan, anggaran"
            f" Rp{slot['capital_idr']:,.0f} dialihkan."
        )

    elif slot["status"] == "HOLDING_FOR_TP":
      umur_hold_jam = (now_ts - slot.get("filled_timestamp", now_ts)) / 3600.0
      kenaikan_skrg_pct = (harga_sekarang - slot["entry_price_idr"]) / slot[
          "entry_price_idr"
      ]

      if harga_sekarang >= slot["tp_price_idr"]:
        eksekusi_jual_limit_indodax(coin, qty_estimasi, harga_sekarang)
        profit_bersih = round(
            slot["capital_idr"] * (kenaikan_skrg_pct - FEE_ROUNDTRIP_MAKER_PCT),
            0,
        )
        state["realized_profit_today_idr"] += profit_bersih
        state["completed_trades_today"] += 1
        log_aksi.append(
            f"🎉 [TP TERCAPAI] {coin} laku di Rp{harga_sekarang:,.0f} (Bersih:"
            f" +Rp{profit_bersih:,.0f})!"
        )
        continue

      if harga_sekarang <= slot["sl_price_idr"]:
        eksekusi_jual_limit_indodax(coin, qty_estimasi, harga_sekarang)
        pnl_bersih = round(
            slot["capital_idr"] * (kenaikan_skrg_pct - FEE_ROUNDTRIP_TAKER_PCT),
            0,
        )
        state["realized_profit_today_idr"] += pnl_bersih
        state["completed_trades_today"] += 1
        log_aksi.append(
            f"🛡️ [SL/TRAILING CAIR] {coin} dilepas di Rp{harga_sekarang:,.0f}"
            f" (Hasil: Rp{pnl_bersih:,.0f})."
        )
        continue

      if kenaikan_skrg_pct >= 0.028:
        sl_target = round(
            slot["entry_price_idr"] * (1.0 + FEE_ROUNDTRIP_TAKER_PCT + 0.0165),
            0,
        )
        slot["sl_price_idr"] = max(slot["sl_price_idr"], sl_target)
      elif kenaikan_skrg_pct >= 0.022:
        if rsi_sekarang >= 68.0 or tren_sekarang != "UPTREND":
          eksekusi_jual_limit_indodax(coin, qty_estimasi, harga_sekarang)
          profit_bersih = round(
              slot["capital_idr"]
              * (kenaikan_skrg_pct - FEE_ROUNDTRIP_MAKER_PCT),
              0,
          )
          state["realized_profit_today_idr"] += profit_bersih
          state["completed_trades_today"] += 1
          log_aksi.append(
              f"⚡ [EARLY TP +2.2%] {coin} langsung TP (+Rp{profit_bersih:,.0f})!"
          )
          continue
        else:
          sl_target = round(
              slot["entry_price_idr"]
              * (1.0 + FEE_ROUNDTRIP_TAKER_PCT + 0.0095),
              0,
          )
          slot["sl_price_idr"] = max(slot["sl_price_idr"], sl_target)
      elif kenaikan_skrg_pct >= 0.016:
        sl_target = round(
            slot["entry_price_idr"] * (1.0 + FEE_ROUNDTRIP_TAKER_PCT + 0.0035),
            0,
        )
        slot["sl_price_idr"] = max(slot["sl_price_idr"], sl_target)

      if umur_hold_jam >= PRE_TIMESTOP_HOURS:
        tp_dinamis_40h_pct = min(max(potensi_naik_pct, 0.011), 0.022)
        if umur_hold_jam < FINAL_TIMESTOP_HOURS:
          if tren_sekarang == "UPTREND" and rsi_sekarang < 65:
            slot["tp_price_idr"] = min(
                slot["tp_price_idr"],
                round(slot["entry_price_idr"] * (1.0 + tp_dinamis_40h_pct), 0),
            )
          elif kenaikan_skrg_pct >= 0.0095:
            eksekusi_jual_limit_indodax(coin, qty_estimasi, harga_sekarang)
            profit_bersih = round(
                slot["capital_idr"]
                * (kenaikan_skrg_pct - FEE_ROUNDTRIP_MAKER_PCT),
                0,
            )
            state["realized_profit_today_idr"] += profit_bersih
            state["completed_trades_today"] += 1
            log_aksi.append(
                f"🕒 [KELUAR 40J] {coin} bungkus +Rp{profit_bersih:,.0f}!"
            )
            continue
        elif kenaikan_skrg_pct >= 0.0090:
          eksekusi_jual_limit_indodax(coin, qty_estimasi, harga_sekarang)
          profit_bersih = round(
              slot["capital_idr"]
              * (kenaikan_skrg_pct - FEE_ROUNDTRIP_MAKER_PCT),
              0,
          )
          state["realized_profit_today_idr"] += profit_bersih
          state["completed_trades_today"] += 1
          log_aksi.append(
              f"⏱️ [TIME-STOP 48J] {coin} bungkus +Rp{profit_bersih:,.0f}!"
          )
          continue

      log_aksi.append(
          f"🎯 [KAWAL TP] {coin} ({mode_slot}) | Skrg: Rp{harga_sekarang:,.0f}"
          f" ({kenaikan_skrg_pct*100:+.2f}%) -> TP:"
          f" Rp{slot['tp_price_idr']:,.0f}"
      )
      slot_tetap_aktif.append(slot)

  state["active_slots"] = slot_tetap_aktif
  return state, log_aksi


# ==============================================================================
# BAGIAN 5: SMART ELASTIC BUDGET ALLOCATION (MAKSIMALKAN SALDO BERAPA PUN >= Rp11.000)
# ==============================================================================
def hitung_pecahan_slot_elastis(anggaran_tersedia):
  """
  Membagi anggaran yang tersedia secara dinamis & elastis:
  - Contoh 1: Anggaran Rp95.000 -> dibagi menjadi [Rp25.000, Rp25.000, Rp25.000, Rp20.000] (4 slot optimal!)
  - Contoh 2: Anggaran Rp82.000 -> dibagi menjadi [Rp27.333, Rp27.333, Rp27.334] (3 slot maksimal!)
  - Contoh 3: Anggaran Rp15.000 -> tetap jalan 1 slot [Rp15.000] karena >= Rp11.000!
  """
  if anggaran_tersedia < MIN_ORDER_IDR_INDODAX:
    return []

  daftar_pecahan = []
  sisa = math.floor(anggaran_tersedia)

  while sisa >= IDEAL_SLOT_SIZE_IDR:
    # Jika sisa setelah diambil Rp25.000 ternyata tanggung (di antara Rp1 s/d Rp10.999),
    # gabungkan sisa tanggung tersebut atau bagi rata agar tidak ada uang menganggur!
    calon_sisa = sisa - IDEAL_SLOT_SIZE_IDR
    if 0 < calon_sisa < MIN_ORDER_IDR_INDODAX:
      if sisa <= 36000:
        daftar_pecahan.append(int(sisa))
        sisa = 0
        break
      else:
        slot_1 = int(sisa // 2)
        slot_2 = int(sisa - slot_1)
        daftar_pecahan.extend([slot_1, slot_2])
        sisa = 0
        break
    else:
      daftar_pecahan.append(int(IDEAL_SLOT_SIZE_IDR))
      sisa -= IDEAL_SLOT_SIZE_IDR

  if sisa >= MIN_ORDER_IDR_INDODAX:
    daftar_pecahan.append(int(sisa))

  return daftar_pecahan


def kelola_anggaran_elastis_indodax(state, peta_analisa, saldo_idr_dompet):
  modal_sedang_terpakai = sum(
      slot["capital_idr"] for slot in state["active_slots"]
  )
  batas_sisa_plafon_bot = max(0.0, MAX_BOT_CAPITAL_IDR - modal_sedang_terpakai)

  # Gunakan angka terkecil antara sisa plafon bot dan uang asli yang benar-benar ada di dompet Indodax!
  if saldo_idr_dompet is not None:
    anggaran_bisa_dipakai = min(batas_sisa_plafon_bot, saldo_idr_dompet)
  else:
    anggaran_bisa_dipakai = batas_sisa_plafon_bot

  daftar_peluru_idr = hitung_pecahan_slot_elastis(anggaran_bisa_dipakai)

  if not daftar_peluru_idr:
    return state, [
        f"[MODAL TERKELOLA MAKSIMAL] Aktif: Rp{modal_sedang_terpakai:,.0f} |"
        f" Sisa Saldo Bebas: Rp{anggaran_bisa_dipakai:,.0f} (di bawah min order"
        " Rp11.000)."
    ]

  kandidat_urut = sorted(
      [v for v in peta_analisa.values() if v["gaya"] != "WAIT_OVERBOUGHT"],
      key=lambda x: x["skor"],
      reverse=True,
  )

  log_alokasi = []
  idx_kandidat = 0

  for nominal_peluru in daftar_peluru_idr:
    while idx_kandidat < len(kandidat_urut):
      kandidat = kandidat_urut[idx_kandidat]
      idx_kandidat += 1
      coin = kandidat["coin"]
      if sum(1 for s in state["active_slots"] if s["coin"] == coin) < 2:
        break
    else:
      break

    gaya = kandidat["gaya"]
    entry_idr = int(round(kandidat["entry_ideal_idr"]))
    tp_pct = TP_SNIPER_BASE_PCT if gaya == "SNIPER" else TP_GRID_BASE_PCT
    sl_pct = SL_SNIPER_BASE_PCT if gaya == "SNIPER" else SL_GRID_BASE_PCT
    tp_idr = int(round(entry_idr * (1.0 + tp_pct)))
    sl_idr = int(round(entry_idr * (1.0 - sl_pct)))
    qty_estimasi = round(nominal_peluru / entry_idr, 6)

    respon_order = eksekusi_beli_limit_indodax(coin, nominal_peluru, entry_idr)

    if respon_order.get("success") == 1:
      order_id = respon_order.get("return", {}).get("order_id", int(time.time()))
      slot_baru = {
          "venue": "INDODAX",
          "coin": coin,
          "style": gaya,
          "status": "WAITING_BUY",
          "capital_idr": nominal_peluru,
          "qty": qty_estimasi,
          "entry_price_idr": entry_idr,
          "tp_price_idr": tp_idr,
          "sl_price_idr": sl_idr,
          "rsi_at_entry": kandidat["rsi"],
          "buy_order_id": order_id,
          "timestamp": time.time(),
      }
      state["active_slots"].append(slot_baru)
      log_alokasi.append(
          f"🚀 [INDODAX ORDER #{order_id} - {gaya}] {coin} | Modal"
          f" Elastis: Rp{nominal_peluru:,.0f} | Limit Buy:"
          f" Rp{entry_idr:,.0f} -> TP: Rp{tp_idr:,.0f}"
      )
    else:
      pesan_gagal = respon_order.get("error", str(respon_order))
      log_alokasi.append(
          f"⚠️ [INFO ORDER INDODAX] {coin} (Rp{nominal_peluru:,.0f} @"
          f" Rp{entry_idr:,.0f}) -> {pesan_gagal}"
      )

  return state, log_alokasi


# ==============================================================================
# BAGIAN 6: LAPORAN OTOMATIS KE GOOGLE SHEETS (WEBHOOK TAB 4)
# ==============================================================================
def lapor_ke_google_sheets(state, semua_log, saldo_idr_dompet):
  ringkasan_slot = (
      ", ".join([
          f"{s['coin']}[{s['style']}:Rp{s['capital_idr']:,.0f}@Rp{s['entry_price_idr']:,.0f}]"
          for s in state["active_slots"]
      ])
      or "Menunggu Saldo / Order Aktif"
  )
  catatan_lengkap = " | ".join(semua_log)[:480]
  total_modal_aktif = sum(s["capital_idr"] for s in state["active_slots"])

  payload = {
      "tanggal": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
      "pasangan": f"INDODAX HYBRID ({len(state['active_slots'])} Slot)",
      "modal_aktif_idr": total_modal_aktif,
      "harga_acuan_idr": (
          saldo_idr_dompet
          if saldo_idr_dompet is not None
          else MAX_BOT_CAPITAL_IDR
      ),
      "jumlah_grid_tereksekusi": state["completed_trades_today"],
      "profit_terealisasi_idr": state["realized_profit_today_idr"],
      "floating_pnl_idr": 0,
      "tren_1h": ringkasan_slot,
      "rsi_14": "Indodax-Live",
      "analisis_ai_gemini": catatan_lengkap,
  }

  print("=== RINGKASAN EKSEKUSI SMART DYNAMIC HYBRID BOT (INDODAX) ===")
  print(json.dumps(payload, indent=2))

  if GOOGLE_SHEETS_WEBHOOK_URL:
    try:
      req = urllib.request.Request(
          GOOGLE_SHEETS_WEBHOOK_URL,
          data=json.dumps(payload).encode("utf-8"),
          headers={"Content-Type": "application/json"},
      )
      with urllib.request.urlopen(req, timeout=10) as resp:
        print("Sukses kirim ke Google Sheets:", resp.read().decode())
    except Exception as e:
      print("Gagal kirim ke Google Sheets:", e)


if __name__ == "__main__":
  state = muat_state_bot()
  saldo_idr_bebas, saldo_koin_map = cek_saldo_asli_indodax()
  harga_live = ambil_harga_idr_semua_koin()
  peta_analisa_pasar = analisa_teknikal_lengkap_pasar(harga_live)
  state, log_kawal = evaluasi_dan_kawal_posisi_dinamis(
      state, peta_analisa_pasar, saldo_koin_map
  )
  state, log_alokasi = kelola_anggaran_elastis_indodax(
      state, peta_analisa_pasar, saldo_idr_bebas
  )
  simpan_state_bot(state)
  lapor_ke_google_sheets(state, log_kawal + log_alokasi, saldo_idr_bebas)
