# ==============================================================================
# SMART DYNAMIC HYBRID AI BOT 24/7 (MISSED-PEAK TP RANGE + SMART SL RANGE AI)
# ==============================================================================
# Pembaruan Cerdas Sesuai Strategi Anda:
# 1. RESTING TP ORDER DI INDODAX: Order Jual TP (LIMIT SELL) langsung dipasang
#    standby di Order Book Indodax begitu koin terbeli (muncul di Open Orders!).
# 2. MISSED-PEAK / TP RANGE DETECTOR (Anti-Gagal Bungkus Untung):
#    - Bot membaca riwayat harga tertinggi (High candlestick) sejak koin dibeli.
#    - Jika harga sempat naik menyentuh Range Dekat TP (>= 75% dari target TP)
#      namun gagal tembus TP lalu turun kembali, DAN analisis indikator menunjukkan
#      tren mulai berat untuk naik lagi sementara posisi saat ini MASIH UNTUNG
#      BERSIH (>= +1.0% di atas harga beli), bot langsung membatalkan antrean TP
#      atas dan LANGSUNG SELL sekarang juga untuk mengamankan profit!
# 3. SMART SL RANGE ANALYZER (Evaluasi Range SL -1.2% s/d -2.0%):
#    - Saat harga turun masuk ke Range Peringatan SL (-1.2% s/d -2.0%), bot
#      menganalisis apakah penurunan itu hanya koreksi wajar (Oversold di Support -> Tahan)
#      ataukah tren patah parah (Volume jual besar & tren jatuh -> Cut Loss dini
#      sebelum rugi makin dalam!).
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

MAX_BOT_CAPITAL_IDR = float(os.getenv("MAX_BOT_CAPITAL_IDR", "100000"))
MAX_SLOTS_ALLOWED = 4
MIN_ORDER_IDR_INDODAX = 11000.0
MIN_CONVICTION_SCORE = 62.0

FEE_ROUNDTRIP_MAKER_PCT = 0.0055
FEE_ROUNDTRIP_TAKER_PCT = 0.0075

TP_GRID_BASE_PCT = 0.020
SL_GRID_BASE_PCT = 0.020
TP_SNIPER_BASE_PCT = 0.036
SL_SNIPER_BASE_PCT = 0.018

REVIEW_ENTRY_HOURS = 6.0
PRE_TIMESTOP_HOURS = 40.0
FINAL_TIMESTOP_HOURS = 48.0

WATCHLIST_COINS = {
    "SOL": {
        "pair": "sol_idr",
        "symbol_v2": "SOLIDR",
        "coin_key": "sol",
        "kraken_pair": "SOLUSD",
        "decimals": 4,
    },
    "BTC": {
        "pair": "btc_idr",
        "symbol_v2": "BTCIDR",
        "coin_key": "btc",
        "kraken_pair": "XXBTZUSD",
        "decimals": 6,
    },
    "ETH": {
        "pair": "eth_idr",
        "symbol_v2": "ETHIDR",
        "coin_key": "eth",
        "kraken_pair": "XETHZUSD",
        "decimals": 5,
    },
    "XRP": {
        "pair": "xrp_idr",
        "symbol_v2": "XRPIDR",
        "coin_key": "xrp",
        "kraken_pair": "XXRPZUSD",
        "decimals": 2,
    },
    "ADA": {
        "pair": "ada_idr",
        "symbol_v2": "ADAIDR",
        "coin_key": "ada",
        "kraken_pair": "ADAUSD",
        "decimals": 2,
    },
    "SUI": {
        "pair": "sui_idr",
        "symbol_v2": "SUIIDR",
        "coin_key": "sui",
        "kraken_pair": "SUIUSD",
        "decimals": 2,
    },
    "DOGE": {
        "pair": "doge_idr",
        "symbol_v2": "DOGEIDR",
        "coin_key": "doge",
        "kraken_pair": "XDGUSD",
        "decimals": 0,
    },
}

STATE_FILE = "bot_state_tokocrypto.json"

INDODAX_API_KEY = (
    os.getenv("INDODAX_API_KEY") or os.getenv("TOKOCRYPTO_API_KEY") or ""
).strip()
INDODAX_SECRET_KEY = (
    os.getenv("INDODAX_SECRET_KEY") or os.getenv("TOKOCRYPTO_SECRET_KEY") or ""
).strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GOOGLE_SHEETS_WEBHOOK_URL = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()


def muat_state_bot():
  if os.path.exists(STATE_FILE):
    try:
      with open(STATE_FILE, "r") as f:
        data = json.load(f)
        data["active_slots"] = [
            s for s in data.get("active_slots", []) if s.get("venue") == "INDODAX"
        ]
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


def format_qty_koin(coin, qty_float):
  dec = WATCHLIST_COINS[coin]["decimals"]
  factor = 10**dec
  qty = math.floor(qty_float * factor) / factor
  return str(int(qty)) if dec == 0 else f"{qty:.{dec}f}"


def hitung_qty_koin(coin, nominal_idr, price_idr):
  return format_qty_koin(coin, nominal_idr / price_idr)


def kirim_request_v2(path, http_method="GET", params=None):
  p = dict(params or {})
  p["timestamp"] = int(time.time() * 1000)
  p["recvWindow"] = 15000
  encoded = urllib.parse.urlencode(p)
  sign = hmac.new(
      INDODAX_SECRET_KEY.encode("utf-8"),
      encoded.encode("utf-8"),
      hashlib.sha256,
  ).hexdigest()

  headers = {
      "X-APIKEY": INDODAX_API_KEY,
      "Sign": sign,
      "User-Agent": "Mozilla/5.0",
  }

  base_url = "https://api.indodax.com"
  if http_method in ("GET", "DELETE"):
    url = f"{base_url}{path}?{encoded}"
    body = None
  else:
    url = f"{base_url}{path}"
    body = encoded.encode("utf-8")
    headers["Content-Type"] = "application/x-www-form-urlencoded"

  req = urllib.request.Request(
      url, data=body, headers=headers, method=http_method
  )
  try:
    with urllib.request.urlopen(req, timeout=12) as resp:
      return json.loads(resp.read().decode("utf-8", errors="ignore"))
  except urllib.error.HTTPError as he:
    err_text = he.read().decode("utf-8", errors="ignore")
    try:
      return json.loads(err_text)
    except Exception:
      return {"code": he.code, "msg": f"HTTP {he.code}: {err_text[:120]}"}
  except Exception as e:
    return {"code": -1, "msg": str(e)}


def cek_saldo_indodax_v2():
  res = kirim_request_v2("/api/v2/account", "GET", {})
  if "balances" in res or "canTrade" in res:
    balances_list = res.get("balances", [])
    saldo_free = {
        str(b.get("asset", "")).lower(): float(b.get("free", 0))
        for b in balances_list
    }
    saldo_locked = {
        str(b.get("asset", "")).lower(): float(b.get("locked", 0))
        for b in balances_list
    }
    saldo_idr = saldo_free.get("idr", 0.0)
    idr_locked = saldo_locked.get("idr", 0.0)
    print(
        f"✅ [AKUN INDODAX UID:{res.get('uid')}] Saldo IDR Bebas:"
        f" Rp{saldo_idr:,.0f} | IDR Antre Beli: Rp{idr_locked:,.0f}"
    )
    return saldo_idr, saldo_free, saldo_locked
  print(f"⚠️ [GAGAL CEK SALDO]: {res}")
  return 0.0, {}, {}


def cek_status_order_v2(coin, order_id):
  if not order_id:
    return None
  symbol_v2 = WATCHLIST_COINS[coin]["symbol_v2"]
  res = kirim_request_v2(
      "/api/v2/order",
      "GET",
      {"symbol": symbol_v2, "orderId": str(order_id)},
  )
  status_str = str(
      res.get("status") or (res.get("data") or {}).get("status") or ""
  ).upper()
  return status_str


def eksekusi_beli_limit_indodax(coin, nominal_idr, price_idr):
  symbol_v2 = WATCHLIST_COINS[coin]["symbol_v2"]
  qty_str = hitung_qty_koin(coin, nominal_idr, price_idr)
  harga_str = str(int(round(price_idr)))

  params_v2 = {
      "symbol": symbol_v2,
      "side": "BUY",
      "type": "LIMIT",
      "timeInForce": "GTC",
      "price": harga_str,
      "quantity": qty_str,
  }
  res = kirim_request_v2("/api/v2/order", "POST", params_v2)
  print(
      f"👉 [INDODAX V2 BUY] {symbol_v2} | Qty={qty_str} (~Rp{nominal_idr:,.0f})"
      f" @ Rp{harga_str} -> {res}"
  )
  return res, float(qty_str)


def eksekusi_jual_limit_indodax(coin, qty_koin, price_idr, label="SELL"):
  symbol_v2 = WATCHLIST_COINS[coin]["symbol_v2"]
  qty_str = format_qty_koin(coin, qty_koin)
  harga_str = str(int(round(price_idr)))

  params_v2 = {
      "symbol": symbol_v2,
      "side": "SELL",
      "type": "LIMIT",
      "timeInForce": "GTC",
      "price": harga_str,
      "quantity": qty_str,
  }
  res = kirim_request_v2("/api/v2/order", "POST", params_v2)
  print(
      f"👉 [INDODAX V2 {label}] {symbol_v2} | Qty={qty_str} @ Rp{harga_str} ->"
      f" {res}"
  )
  return res


def batalkan_order_indodax(coin, order_id):
  if not order_id or str(order_id).startswith("SIM"):
    return
  symbol_v2 = WATCHLIST_COINS[coin]["symbol_v2"]
  res = kirim_request_v2(
      "/api/v2/order",
      "DELETE",
      {"symbol": symbol_v2, "orderId": str(order_id)},
  )
  print(f"👉 [INDODAX V2 CANCEL] {symbol_v2} ID={order_id} -> {res}")


def pasang_antrean_tp_di_indodax(slot, saldo_free_map):
  coin = slot["coin"]
  coin_key = WATCHLIST_COINS[coin]["coin_key"]
  koin_bebas = float(saldo_free_map.get(coin_key, 0.0))
  qty_jual = koin_bebas if koin_bebas > 0 else float(slot.get("qty", 0.0))
  if qty_jual <= 0:
    return None

  res_tp = eksekusi_jual_limit_indodax(
      coin, qty_jual, slot["tp_price_idr"], label="PASANG ANTREAN TP"
  )
  tp_order_id = res_tp.get("orderId") or (res_tp.get("data") or {}).get(
      "orderId"
  )
  if tp_order_id:
    slot["tp_order_id"] = tp_order_id
    slot["qty"] = float(format_qty_koin(coin, qty_jual))
  return tp_order_id


def ambil_info_pasar_indodax_lengkap():
  """Mengambil harga terakhir (last) DAN harga tertinggi 24 jam/sesi dari Indodax tickers."""
  harga_map = {}
  high_24h_map = {}
  try:
    url = "https://indodax.com/api/tickers"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
      tickers = json.loads(resp.read().decode()).get("tickers", {})
    for coin, info in WATCHLIST_COINS.items():
      t = tickers.get(info["pair"], {})
      if "last" in t:
        harga_map[coin] = float(t["last"])
        high_24h_map[coin] = float(t.get("high", t["last"]))
  except Exception as e:
    print("Gagal ambil harga publik Indodax:", e)
  return harga_map, high_24h_map


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
      volumes = [float(r[6]) for r in raw]

      ema20 = sum(closes[-20:]) / 20.0
      ema50 = sum(closes[-50:]) / 50.0
      gains, losses = [], []
      for i in range(-14, 0):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
      rsi = 100 - (
          100 / (1 + (sum(gains) / 14.0) / ((sum(losses) / 14.0) or 0.0001))
      )
      tr_list = [highs[i] - lows[i] for i in range(-14, 0)]
      atr_pct = (sum(tr_list) / 14.0) / closes[-1]

      # Hitung rasio puncak 2 jam terakhir dibanding harga penutupan saat ini (untuk deteksi Missed Peak)
      high_2jam_rasio = max(highs[-2:]) / closes[-1]
      estimasi_high_2jam_idr = round(harga_idr * high_2jam_rasio, 0)

      # Cek apakah candle terakhir sedang merah menekan ke bawah (bearish momentum)
      candle_terakhir_merah = closes[-1] < float(raw[-1][1])
      vol_rata = sum(volumes[-20:]) / 20.0
      vol_rasio = volumes[-1] / (vol_rata or 1.0)
      bonus_vol = min(max((vol_rasio - 0.8) * 8.0, 0.0), 10.0)

      potensi_naik_pct = round(max(atr_pct * 2.2, 0.008), 4)
      diskon_entry_ideal_pct = min(max(atr_pct * 0.4, 0.004), 0.018)
      entry_ideal_idr = round(harga_idr * (1.0 - diskon_entry_ideal_pct), 0)

      if ema20 > ema50 and 38 <= rsi <= 56:
        gaya = "SNIPER"
        skor = 82.0 + (10.0 - abs(46 - rsi) * 0.8) + bonus_vol
      elif rsi < 32:
        gaya = "SNIPER"
        skor = 78.0 + min((32 - rsi) * 1.2, 12.0) + bonus_vol
      elif 32 <= rsi <= 58:
        gaya = "GRID"
        skor = (
            64.0
            + (8.0 - abs(45 - rsi) * 0.5)
            + (4.0 if ema20 >= ema50 * 0.995 else -4.0)
        )
      else:
        gaya = "SKIP_RISKY"
        skor = 35.0

      peta_analisa[coin] = {
          "coin": coin,
          "harga_idr": harga_idr,
          "high_2jam_idr": estimasi_high_2jam_idr,
          "tren": "UPTREND" if ema20 > ema50 else "SIDEWAYS/DOWN",
          "candle_merah": candle_terakhir_merah,
          "vol_rasio": round(vol_rasio, 2),
          "rsi": round(rsi, 1),
          "atr_pct": round(atr_pct, 4),
          "potensi_naik_pct": potensi_naik_pct,
          "entry_ideal_idr": entry_ideal_idr,
          "gaya": gaya,
          "skor": round(min(skor, 99.0), 1),
      }
    except Exception:
      continue
  return peta_analisa


def konsultasi_alokasi_gemini_ai(
    kandidat_layak, anggaran_bebas_idr, slot_kosong
):
  if (
      not kandidat_layak
      or slot_kosong <= 0
      or anggaran_bebas_idr < MIN_ORDER_IDR_INDODAX
  ):
    return (
        [],
        (
            "Tidak ada koin dengan skor >=62 atau slot penuh. Menahan Cash"
            " Reserve."
        ),
    )

  terpilih = kandidat_layak[:slot_kosong]
  skor_rata = sum(k["skor"] for k in terpilih) / len(terpilih)
  if len(terpilih) == 1 and skor_rata < 75.0 and anggaran_bebas_idr >= 35000:
    dana_dipakai = max(
        MIN_ORDER_IDR_INDODAX, round(anggaran_bebas_idr * 0.55, 0)
    )
    alasan_sizing = (
        f"1 koin layak ({terpilih[0]['coin']} Skor {terpilih[0]['skor']})."
        f" Alokasi 55% (Rp{dana_dipakai:,.0f}) & 45% Cash Reserve."
    )
  else:
    dana_dipakai = math.floor(anggaran_bebas_idr)
    alasan_sizing = (
        f"{len(terpilih)} koin layak (Rata-rata Skor {skor_rata:.1f}). Alokasi"
        f" proporsional Rp{dana_dipakai:,.0f}."
    )

  bobot_list = [max(k["skor"] - 50.0, 10.0) for k in terpilih]
  total_bobot = sum(bobot_list)
  rencana_alokasi = []
  sisa_dana = int(dana_dipakai)

  for idx, k in enumerate(terpilih):
    if idx == len(terpilih) - 1:
      nominal = sisa_dana
    else:
      nominal = int(round(dana_dipakai * (bobot_list[idx] / total_bobot)))
      if nominal < MIN_ORDER_IDR_INDODAX:
        nominal = int(MIN_ORDER_IDR_INDODAX)
      if (sisa_dana - nominal) < MIN_ORDER_IDR_INDODAX and idx < len(
          terpilih
      ) - 1:
        nominal = sisa_dana
    if nominal >= MIN_ORDER_IDR_INDODAX and nominal <= sisa_dana:
      rencana_alokasi.append((k, nominal))
      sisa_dana -= nominal

  return rencana_alokasi, alasan_sizing


def evaluasi_dan_kawal_posisi_dinamis(
    state, peta_analisa, saldo_free_map, saldo_locked_map
):
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
    high_2jam_idr = (
        info_pasar["high_2jam_idr"] if info_pasar else harga_sekarang
    )
    rsi_sekarang = info_pasar["rsi"] if info_pasar else 50.0
    tren_sekarang = info_pasar["tren"] if info_pasar else "SIDEWAYS"
    candle_merah = info_pasar["candle_merah"] if info_pasar else False
    vol_rasio = info_pasar["vol_rasio"] if info_pasar else 1.0
    potensi_naik_pct = info_pasar["potensi_naik_pct"] if info_pasar else 0.015
    skor_koin_ini = info_pasar["skor"] if info_pasar else 50.0

    umur_antre_jam = (now_ts - slot["timestamp"]) / 3600.0
    mode_slot = slot["style"]
    koin_free = float(saldo_free_map.get(coin_key, 0.0))
    koin_locked = float(saldo_locked_map.get(coin_key, 0.0))
    total_koin_dimiliki = koin_free + koin_locked
    qty_estimasi = total_koin_dimiliki or float(
        slot.get("qty", slot["capital_idr"] / slot["entry_price_idr"])
    )

    if slot["status"] == "WAITING_BUY":
      status_asli = cek_status_order_v2(coin, slot.get("buy_order_id"))
      koin_sudah_di_dompet = total_koin_dimiliki >= (
          slot.get("qty", 0) * 0.90
      ) and slot.get("qty", 0) > 0

      if status_asli in ("FILLED", "PARTIALLY_FILLED") or koin_sudah_di_dompet:
        slot["status"] = "HOLDING_FOR_TP"
        slot["filled_timestamp"] = now_ts
        slot["highest_price_idr"] = max(harga_sekarang, high_2jam_idr)
        tp_id = pasang_antrean_tp_di_indodax(slot, saldo_free_map)
        log_aksi.append(
            f"✅ [ENTRY TERBELI & TP DIPASANG] {coin} ({mode_slot}) di"
            f" Rp{slot['entry_price_idr']:,.0f}! Order Jual TP"
            f" Rp{slot['tp_price_idr']:,.0f} (ID:{tp_id}) telah dipasang di"
            f" Indodax | SL Range: Rp{slot['sl_price_idr']:,.0f}."
        )
        slot_tetap_aktif.append(slot)
        continue

      if status_asli in ("CANCELED", "CANCELLED", "REJECTED", "EXPIRED"):
        log_aksi.append(
            f"🔄 [ORDER BATAL] {coin} #{slot.get('buy_order_id')}"
            f" ({status_asli}). Anggaran Rp{slot['capital_idr']:,.0f}"
            " dibebaskan."
        )
        continue

      if umur_antre_jam <= REVIEW_ENTRY_HOURS:
        log_aksi.append(
            f"⏳ [ANTRE BELI {umur_antre_jam:.1f}j] {coin} di"
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
          and info_pasar["skor"] >= MIN_CONVICTION_SCORE
          and skor_koin_ini >= (skor_terbaik_lain - 8)
      ):
        batalkan_order_indodax(coin, slot.get("buy_order_id"))
        entry_baru_idr = info_pasar["entry_ideal_idr"]
        tp_pct = (
            TP_SNIPER_BASE_PCT if mode_slot == "SNIPER" else TP_GRID_BASE_PCT
        )
        sl_pct = (
            SL_SNIPER_BASE_PCT if mode_slot == "SNIPER" else SL_GRID_BASE_PCT
        )
        respon_baru, qty_baru = eksekusi_beli_limit_indodax(
            coin, slot["capital_idr"], entry_baru_idr
        )
        order_id_baru = respon_baru.get("orderId") or (
            respon_baru.get("data") or {}
        ).get("orderId")
        if order_id_baru:
          slot["entry_price_idr"] = entry_baru_idr
          slot["qty"] = qty_baru
          slot["tp_price_idr"] = round(entry_baru_idr * (1.0 + tp_pct), 0)
          slot["sl_price_idr"] = round(entry_baru_idr * (1.0 - sl_pct), 0)
          slot["buy_order_id"] = order_id_baru
          slot["timestamp"] = now_ts
          log_aksi.append(
              f"📈 [NAIKKAN ENTRY >6J] {coin} digeser ke"
              f" Rp{entry_baru_idr:,.0f}!"
          )
          slot_tetap_aktif.append(slot)
      else:
        batalkan_order_indodax(coin, slot.get("buy_order_id"))
        log_aksi.append(
            f"🔄 [GANTI KOIN >6J] Antrean {coin} dibatalkan, anggaran"
            " dialihkan."
        )

    elif slot["status"] == "HOLDING_FOR_TP":
      umur_hold_jam = (now_ts - slot.get("filled_timestamp", now_ts)) / 3600.0
      kenaikan_skrg_pct = (harga_sekarang - slot["entry_price_idr"]) / slot[
          "entry_price_idr"
      ]

      # Rekam puncak harga tertinggi yang pernah dicapai sejak koin dipegang (termasuk High 2 jam terakhir)
      puncak_tercatat = max(
          slot.get("highest_price_idr", harga_sekarang),
          harga_sekarang,
          high_2jam_idr if umur_hold_jam >= 0.5 else harga_sekarang,
      )
      slot["highest_price_idr"] = puncak_tercatat
      kenaikan_puncak_pct = (puncak_tercatat - slot["entry_price_idr"]) / slot[
          "entry_price_idr"
      ]
      target_tp_pct = (slot["tp_price_idr"] - slot["entry_price_idr"]) / slot[
          "entry_price_idr"
      ]

      # 1. Pastikan antrean LIMIT SELL (TP) sudah terpasang di Order Book Indodax
      if not slot.get("tp_order_id") and koin_free > 0:
        tp_id = pasang_antrean_tp_di_indodax(slot, saldo_free_map)
        if tp_id:
          log_aksi.append(
              f"📌 [PASANG ANTREAN TP INDODAX] Order Jual TP {coin} di"
              f" Rp{slot['tp_price_idr']:,.0f} berhasil dipasang (OrderID:"
              f" #{tp_id})!"
          )

      # 2. Cek apakah antrean TP di Indodax sudah LAKU TERJUAL (FILLED)
      status_tp = (
          cek_status_order_v2(coin, slot.get("tp_order_id"))
          if slot.get("tp_order_id")
          else None
      )
      if status_tp == "FILLED" or harga_sekarang >= slot["tp_price_idr"]:
        if status_tp != "FILLED":
          batalkan_order_indodax(coin, slot.get("tp_order_id"))
          eksekusi_jual_limit_indodax(
              coin, qty_estimasi, harga_sekarang, label="TP SELL"
          )
        pct_untung = (
            max(harga_sekarang, slot["tp_price_idr"]) - slot["entry_price_idr"]
        ) / slot["entry_price_idr"]
        profit_bersih = round(
            slot["capital_idr"] * (pct_untung - FEE_ROUNDTRIP_MAKER_PCT), 0
        )
        state["realized_profit_today_idr"] += profit_bersih
        state["completed_trades_today"] += 1
        log_aksi.append(
            f"🎉 [TP TERCAPAI!] {coin} laku terjual di"
            f" Rp{slot['tp_price_idr']:,.0f} (Bersih: +Rp{profit_bersih:,.0f})!"
        )
        continue

      # 3. FITUR BARU SESUAI IDE ANDA: "MISSED-PEAK / TP RANGE DETECTOR"
      # Jika riwayat harga tertinggi (puncak_tercatat) sudah sempat masuk ke Range Dekat TP (>= 75% dari target TP),
      # lalu sekarang harga mundur turun dan analisis menunjukkan berat naik lagi (tren bukan UPTREND atau candle merah),
      # sementara posisi sekarang MASIH UNTUNG BERSIH (>= +1.0% di atas harga beli), LANGSUNG SELL SEKARANG!
      if (
          kenaikan_puncak_pct >= (target_tp_pct * 0.75)
          and kenaikan_skrg_pct >= 0.010
      ):
        if (
            tren_sekarang != "UPTREND"
            or candle_merah
            or rsi_sekarang >= 62.0
        ):
          if slot.get("tp_order_id"):
            batalkan_order_indodax(coin, slot.get("tp_order_id"))
          eksekusi_jual_limit_indodax(
              coin, qty_estimasi, harga_sekarang, label="RANGE TP SELL"
          )
          profit_bersih = round(
              slot["capital_idr"]
              * (kenaikan_skrg_pct - FEE_ROUNDTRIP_MAKER_PCT),
              0,
          )
          state["realized_profit_today_idr"] += profit_bersih
          state["completed_trades_today"] += 1
          log_aksi.append(
              f"⚡ [TP RANGE TERDETEKSI!] {coin} sempat menyentuh puncak"
              f" Rp{puncak_tercatat:,.0f} (+{kenaikan_puncak_pct*100:.2f}%)"
              " dekat TP namun tertahan. Langsung bungkus untung sekarang di"
              f" Rp{harga_sekarang:,.0f} (Bersih: +Rp{profit_bersih:,.0f})!"
          )
          continue

      # 4. FITUR BARU SESUAI IDE ANDA: "SMART SL RANGE ANALYZER (-1.2% s/d Batas SL)"
      # Sebelum jatuh ke batas SL mutlak (-2.0%), saat harga masuk Range Peringatan SL (-1.25%),
      # analisis dulu apakah ini cuma jarum Oversold (Tahan) atau tren jatuh deras dengan volume besar (Cut Loss Dini)!
      if (
          harga_sekarang <= slot["sl_price_idr"]
          or (
              kenaikan_skrg_pct <= -0.0135
              and tren_sekarang != "UPTREND"
              and candle_merah
              and vol_rasio >= 1.25
              and rsi_sekarang > 32.0
          )
      ):
        if slot.get("tp_order_id"):
          batalkan_order_indodax(coin, slot.get("tp_order_id"))
        eksekusi_jual_limit_indodax(
            coin, qty_estimasi, harga_sekarang, label="SMART SL SELL"
        )
        pnl_bersih = round(
            slot["capital_idr"] * (kenaikan_skrg_pct - FEE_ROUNDTRIP_TAKER_PCT),
            0,
        )
        state["realized_profit_today_idr"] += pnl_bersih
        state["completed_trades_today"] += 1
        alasan_sl = (
            "Batas SL Tersentuh"
            if harga_sekarang <= slot["sl_price_idr"]
            else "Deteksi Dini Range SL (Tren Patah)"
        )
        log_aksi.append(
            f"🛡️ [SL PROTEKSI: {alasan_sl}] Antrean TP {coin} dibatalkan &"
            f" dilepas di Rp{harga_sekarang:,.0f} (Hasil: Rp{pnl_bersih:,.0f})."
        )
        continue

      # 5. Step-Up Trailing Profit Lock (+1.6% / +2.2% / +2.8%)
      if kenaikan_skrg_pct >= 0.028:
        sl_target = round(
            slot["entry_price_idr"] * (1.0 + FEE_ROUNDTRIP_TAKER_PCT + 0.0165),
            0,
        )
        slot["sl_price_idr"] = max(slot["sl_price_idr"], sl_target)
      elif kenaikan_skrg_pct >= 0.022:
        sl_target = round(
            slot["entry_price_idr"] * (1.0 + FEE_ROUNDTRIP_TAKER_PCT + 0.0095),
            0,
        )
        slot["sl_price_idr"] = max(slot["sl_price_idr"], sl_target)
      elif kenaikan_skrg_pct >= 0.016:
        sl_target = round(
            slot["entry_price_idr"] * (1.0 + FEE_ROUNDTRIP_TAKER_PCT + 0.0035),
            0,
        )
        slot["sl_price_idr"] = max(slot["sl_price_idr"], sl_target)

      # 6. Evaluasi Dinamis 40 Jam -> 48 Jam
      if umur_hold_jam >= PRE_TIMESTOP_HOURS:
        tp_dinamis_40h_pct = min(max(potensi_naik_pct, 0.011), 0.022)
        if umur_hold_jam < FINAL_TIMESTOP_HOURS:
          if tren_sekarang == "UPTREND" and rsi_sekarang < 65:
            tp_baru = round(
                slot["entry_price_idr"] * (1.0 + tp_dinamis_40h_pct), 0
            )
            if tp_baru < slot["tp_price_idr"]:
              if slot.get("tp_order_id"):
                batalkan_order_indodax(coin, slot.get("tp_order_id"))
              slot["tp_price_idr"] = tp_baru
              res_tp = eksekusi_jual_limit_indodax(
                  coin, qty_estimasi, tp_baru, label="REVISI TP 40J"
              )
              slot["tp_order_id"] = res_tp.get("orderId") or (
                  res_tp.get("data") or {}
              ).get("orderId")
          elif kenaikan_skrg_pct >= 0.0095:
            if slot.get("tp_order_id"):
              batalkan_order_indodax(coin, slot.get("tp_order_id"))
            eksekusi_jual_limit_indodax(
                coin, qty_estimasi, harga_sekarang, label="KELUAR 40J"
            )
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
          if slot.get("tp_order_id"):
            batalkan_order_indodax(coin, slot.get("tp_order_id"))
          eksekusi_jual_limit_indodax(
              coin, qty_estimasi, harga_sekarang, label="TIME-STOP 48J"
          )
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

      id_tp_str = (
          f"#{slot.get('tp_order_id')}"
          if slot.get("tp_order_id")
          else "Standby"
      )
      log_aksi.append(
          f"🎯 [KAWAL TP & SL] {coin} ({mode_slot}) | Skrg:"
          f" Rp{harga_sekarang:,.0f} ({kenaikan_skrg_pct*100:+.2f}%, Puncak:"
          f" Rp{puncak_tercatat:,.0f}) | Antre TP({id_tp_str}):"
          f" Rp{slot['tp_price_idr']:,.0f} | Jaga SL:"
          f" Rp{slot['sl_price_idr']:,.0f}"
      )
      slot_tetap_aktif.append(slot)

  state["active_slots"] = slot_tetap_aktif
  return state, log_aksi


def kelola_anggaran_berbasis_conviction_ai(state, peta_analisa, saldo_idr_dompet):
  modal_sedang_terpakai = sum(
      slot["capital_idr"] for slot in state["active_slots"]
  )
  batas_sisa_plafon_bot = max(0.0, MAX_BOT_CAPITAL_IDR - modal_sedang_terpakai)
  anggaran_bisa_dipakai = min(batas_sisa_plafon_bot, saldo_idr_dompet)
  slot_kosong = max(0, MAX_SLOTS_ALLOWED - len(state["active_slots"]))

  if slot_kosong <= 0 or anggaran_bisa_dipakai < MIN_ORDER_IDR_INDODAX:
    return state, [
        f"[MODAL AKTIF BEKERJA] Rp{modal_sedang_terpakai:,.0f} di"
        f" {len(state['active_slots'])} koin berbeda (Sisa IDR bebas:"
        f" Rp{saldo_idr_dompet:,.0f})."
    ]

  koin_sudah_ada = {s["coin"] for s in state["active_slots"]}
  kandidat_layak = sorted(
      [
          v
          for v in peta_analisa.values()
          if v["coin"] not in koin_sudah_ada
          and v["skor"] >= MIN_CONVICTION_SCORE
      ],
      key=lambda x: x["skor"],
      reverse=True,
  )

  rencana_alokasi, alasan_ai = konsultasi_alokasi_gemini_ai(
      kandidat_layak, anggaran_bisa_dipakai, slot_kosong
  )

  if not rencana_alokasi:
    return state, [f"🛡️ [DISIPLIN PRO] {alasan_ai}"]

  log_alokasi = [f"🧠 [KEPUTUSAN SIZING AI] {alasan_ai}"]

  for kandidat, nominal_peluru in rencana_alokasi:
    coin = kandidat["coin"]
    gaya = kandidat["gaya"]
    entry_idr = int(round(kandidat["entry_ideal_idr"]))
    tp_pct = TP_SNIPER_BASE_PCT if gaya == "SNIPER" else TP_GRID_BASE_PCT
    sl_pct = SL_SNIPER_BASE_PCT if gaya == "SNIPER" else SL_GRID_BASE_PCT
    tp_idr = int(round(entry_idr * (1.0 + tp_pct)))
    sl_idr = int(round(entry_idr * (1.0 - sl_pct)))

    respon_order, qty_dikirim = eksekusi_beli_limit_indodax(
        coin, nominal_peluru, entry_idr
    )
    order_id = respon_order.get("orderId") or (
        respon_order.get("data") or {}
    ).get("orderId")

    if order_id:
      slot_baru = {
          "venue": "INDODAX",
          "coin": coin,
          "style": gaya,
          "status": "WAITING_BUY",
          "capital_idr": nominal_peluru,
          "qty": qty_dikirim,
          "entry_price_idr": entry_idr,
          "tp_price_idr": tp_idr,
          "sl_price_idr": sl_idr,
          "rsi_at_entry": kandidat["rsi"],
          "buy_order_id": order_id,
          "tp_order_id": None,
          "timestamp": time.time(),
      }
      state["active_slots"].append(slot_baru)
      log_alokasi.append(
          f"🚀 [ORDER #{order_id} - {gaya}] {coin} (Skor {kandidat['skor']}) |"
          f" Rp{nominal_peluru:,.0f} | Beli: Rp{entry_idr:,.0f} -> TP:"
          f" Rp{tp_idr:,.0f} | SL: Rp{sl_idr:,.0f}"
      )
    else:
      pesan_gagal = (
          respon_order.get("msg")
          or respon_order.get("error")
          or str(respon_order)
      )
      log_alokasi.append(
          f"⚠️ [INFO ORDER] {coin} (Rp{nominal_peluru:,.0f}) -> {pesan_gagal}"
      )

  return state, log_alokasi


def lapor_ke_google_sheets(state, semua_log, saldo_idr_dompet):
  ringkasan_slot = (
      ", ".join([
          f"{s['coin']}[{s['style']}:TP@Rp{s['tp_price_idr']:,.0f}/SL@Rp{s['sl_price_idr']:,.0f}]"
          for s in state["active_slots"]
      ])
      or f"Tahan Cash Reserve (Saldo IDR: Rp{saldo_idr_dompet:,.0f})"
  )
  catatan_lengkap = " | ".join(semua_log)[:480]
  total_modal_aktif = sum(s["capital_idr"] for s in state["active_slots"])

  payload = {
      "tanggal": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
      "pasangan": f"PRO KELLY AI ({len(state['active_slots'])} Posisi)",
      "modal_aktif_idr": total_modal_aktif,
      "harga_acuan_idr": saldo_idr_dompet,
      "jumlah_grid_tereksekusi": state["completed_trades_today"],
      "profit_terealisasi_idr": state["realized_profit_today_idr"],
      "floating_pnl_idr": 0,
      "tren_1h": ringkasan_slot,
      "rsi_14": "TP+SL-Range",
      "analisis_ai_gemini": catatan_lengkap,
  }

  print("=== RINGKASAN EKSEKUSI PRO QUANT HYBRID BOT (INDODAX V2) ===")
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
  saldo_idr_bebas, saldo_free_map, saldo_locked_map = cek_saldo_indodax_v2()
  harga_live, high_24h = ambil_info_pasar_indodax_lengkap()
  peta_analisa_pasar = analisa_teknikal_lengkap_pasar(harga_live)
  state, log_kawal = evaluasi_dan_kawal_posisi_dinamis(
      state, peta_analisa_pasar, saldo_free_map, saldo_locked_map
  )
  state, log_alokasi = kelola_anggaran_berbasis_conviction_ai(
      state, peta_analisa_pasar, saldo_idr_bebas
  )
  simpan_state_bot(state)
  lapor_ke_google_sheets(state, log_kawal + log_alokasi, saldo_idr_bebas)
