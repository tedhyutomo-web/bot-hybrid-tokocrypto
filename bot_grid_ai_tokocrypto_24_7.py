# ==============================================================================
# SMART DYNAMIC HYBRID AI BOT 24/7 (INDODAX QUAD-ENGINE V2 SHA256/512 + V1)
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
IDEAL_SLOT_SIZE_IDR = float(os.getenv("SLOT_SIZE_IDR", "25000"))
MIN_ORDER_IDR_INDODAX = 11000.0

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
LIVE_TRADING_ENABLED = bool(INDODAX_API_KEY and INDODAX_SECRET_KEY)

# Menyimpan mode mesin yang terbukti berhasil saat cek saldo
ACTIVE_ENGINE = None  # tuple: (version, base_url, hash_algo)


def muat_state_bot():
  if os.path.exists(STATE_FILE):
    try:
      with open(STATE_FILE, "r") as f:
        data = json.load(f)
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


def hitung_qty_koin(coin, nominal_idr, price_idr):
  dec = WATCHLIST_COINS[coin]["decimals"]
  factor = 10**dec
  qty = math.floor((nominal_idr / price_idr) * factor) / factor
  return str(int(qty)) if dec == 0 else f"{qty:.{dec}f}"


# ==============================================================================
# QUAD-ENGINE INDODAX (OTOMATIS DETEKSI V2 SHA256, V2 SHA512, ATAU V1 TAPI)
# ==============================================================================
def kirim_request_v2(base_url, path, http_method, params, hash_algo):
  p = dict(params or {})
  p["timestamp"] = int(time.time() * 1000)
  p["recvWindow"] = 15000
  encoded = urllib.parse.urlencode(p)
  digest_mod = hashlib.sha256 if hash_algo == "SHA256" else hashlib.sha512
  sign = hmac.new(
      INDODAX_SECRET_KEY.encode("utf-8"), encoded.encode("utf-8"), digest_mod
  ).hexdigest()

  headers = {
      "X-APIKEY": INDODAX_API_KEY,
      "Sign": sign,
      "User-Agent": "Mozilla/5.0",
  }

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


def kirim_request_v1(method_name, extra_params=None):
  p = {
      "method": method_name,
      "timestamp": int(time.time() * 1000),
      "recvWindow": 15000,
  }
  if extra_params:
    p.update(extra_params)
  encoded = urllib.parse.urlencode(p).encode("utf-8")
  sign = hmac.new(
      INDODAX_SECRET_KEY.encode("utf-8"), encoded, hashlib.sha512
  ).hexdigest()
  headers = {
      "Key": INDODAX_API_KEY,
      "Sign": sign,
      "Content-Type": "application/x-www-form-urlencoded",
      "User-Agent": "Mozilla/5.0",
  }
  req = urllib.request.Request(
      "https://indodax.com/tapi", data=encoded, headers=headers, method="POST"
  )
  try:
    with urllib.request.urlopen(req, timeout=12) as resp:
      return json.loads(resp.read().decode("utf-8", errors="ignore"))
  except Exception as e:
    return {"success": 0, "error": str(e)}


def deteksi_dan_cek_saldo_indodax():
  global ACTIVE_ENGINE
  prefix = INDODAX_API_KEY[:5] if INDODAX_API_KEY else "KOSONG"
  print(
      f"🔑 [DIAGNOSTIK KUNCI] API Key yang terbaca berawalan: '{prefix}...'"
      f" (Panjang: {len(INDODAX_API_KEY)} karakter)"
  )

  # Daftar 5 Kombinasi Pintu Resmi Indodax (V2 api.indodax.com SHA256/512, V2 tapi.indodax.com SHA256/512, dan V1 /tapi)
  kandidat_mesin = [
      ("V2", "https://api.indodax.com", "SHA256"),
      ("V2", "https://api.indodax.com", "SHA512"),
      ("V2", "https://tapi.indodax.com", "SHA256"),
      ("V2", "https://tapi.indodax.com", "SHA512"),
      ("V1", "https://indodax.com/tapi", "SHA512"),
  ]

  for ver, host, algo in kandidat_mesin:
    if ver == "V2":
      res = kirim_request_v2(host, "/api/v2/account", "GET", {}, algo)
      balances_list = res.get("balances") or (res.get("data") or {}).get(
          "balances"
      )
      if isinstance(balances_list, list):
        ACTIVE_ENGINE = (ver, host, algo)
        saldo_koin = {
            str(b.get("asset", "")).lower(): float(b.get("free", 0))
            for b in balances_list
        }
        saldo_idr = saldo_koin.get("idr", 0.0)
        print(
            f"✅ [TEMBUS via {ver} {host} ({algo})] Saldo IDR Bebas:"
            f" Rp{saldo_idr:,.0f}"
        )
        return saldo_idr, saldo_koin
      else:
        print(f"   -> Uji {ver} {host} ({algo}): {res}")
    else:
      res = kirim_request_v1("getInfo")
      if res.get("success") == 1:
        ACTIVE_ENGINE = ("V1", host, "SHA512")
        bal = res.get("return", {}).get("balance", {})
        saldo_koin = {k.lower(): float(v) for k, v in bal.items()}
        saldo_idr = saldo_koin.get("idr", 0.0)
        print(
            f"✅ [TEMBUS via V1 /tapi (SHA512)] Saldo IDR Bebas:"
            f" Rp{saldo_idr:,.0f}"
        )
        return saldo_idr, saldo_koin
      else:
        print(f"   -> Uji V1 /tapi: {res}")

  return None, {}


def eksekusi_beli_limit_indodax(coin, nominal_idr, price_idr):
  symbol_v2 = WATCHLIST_COINS[coin]["symbol_v2"]
  pair_v1 = WATCHLIST_COINS[coin]["pair"]
  coin_key = WATCHLIST_COINS[coin]["coin_key"]
  qty_str = hitung_qty_koin(coin, nominal_idr, price_idr)
  harga_str = str(int(round(price_idr)))

  ver, host, algo = ACTIVE_ENGINE or ("V2", "https://api.indodax.com", "SHA256")

  if ver == "V1":
    # Di Indodax V1, Limit Buy menggunakan jumlah koin (misal sol=0.0161) agar tidak ditolak aturan STP Limit
    params_v1 = {
        "pair": pair_v1,
        "type": "buy",
        "price": harga_str,
        coin_key: qty_str,
    }
    res = kirim_request_v1("trade", params_v1)
    print(
        f"👉 [INDODAX V1 BUY] {pair_v1.upper()} | Qty={qty_str}"
        f" (~Rp{nominal_idr:,.0f}) @ Rp{harga_str} -> {res}"
    )
    return res, float(qty_str)

  # Mode V2: Coba dengan parameter quantity, dan fallback ke amount jika diperlukan
  params_v2 = {
      "symbol": symbol_v2,
      "side": "BUY",
      "type": "LIMIT",
      "timeInForce": "GTC",
      "price": harga_str,
      "quantity": qty_str,
  }
  res = kirim_request_v2(host, "/api/v2/order", "POST", params_v2, algo)
  if "code" in res and res.get("code") != 0 and "orderId" not in res:
    params_v2_alt = {
        "symbol": symbol_v2,
        "side": "BUY",
        "type": "LIMIT",
        "timeInForce": "GTC",
        "price": harga_str,
        "amount": qty_str,
    }
    res_alt = kirim_request_v2(
        host, "/api/v2/order", "POST", params_v2_alt, algo
    )
    if "orderId" in res_alt or (res_alt.get("data") or {}).get("orderId"):
      res = res_alt

  print(
      f"👉 [INDODAX V2 BUY ({host}/{algo})] {symbol_v2} | Qty={qty_str}"
      f" (~Rp{nominal_idr:,.0f}) @ Rp{harga_str} -> {res}"
  )
  return res, float(qty_str)


def eksekusi_jual_limit_indodax(coin, qty_koin, price_idr):
  symbol_v2 = WATCHLIST_COINS[coin]["symbol_v2"]
  pair_v1 = WATCHLIST_COINS[coin]["pair"]
  coin_key = WATCHLIST_COINS[coin]["coin_key"]
  dec = WATCHLIST_COINS[coin]["decimals"]
  qty_str = str(int(qty_koin)) if dec == 0 else f"{qty_koin:.{dec}f}"
  harga_str = str(int(round(price_idr)))

  ver, host, algo = ACTIVE_ENGINE or ("V2", "https://api.indodax.com", "SHA256")
  if ver == "V1":
    return kirim_request_v1(
        "trade",
        {
            "pair": pair_v1,
            "type": "sell",
            "price": harga_str,
            coin_key: qty_str,
        },
    )

  params_v2 = {
      "symbol": symbol_v2,
      "side": "SELL",
      "type": "LIMIT",
      "timeInForce": "GTC",
      "price": harga_str,
      "quantity": qty_str,
  }
  return kirim_request_v2(host, "/api/v2/order", "POST", params_v2, algo)


def batalkan_order_indodax(coin, order_id):
  if not order_id or str(order_id).startswith("SIM"):
    return
  ver, host, algo = ACTIVE_ENGINE or ("V2", "https://api.indodax.com", "SHA256")
  if ver == "V1":
    pair_v1 = WATCHLIST_COINS[coin]["pair"]
    kirim_request_v1(
        "cancelOrder", {"pair": pair_v1, "order_id": int(order_id), "type": "buy"}
    )
  else:
    symbol_v2 = WATCHLIST_COINS[coin]["symbol_v2"]
    kirim_request_v2(
        host,
        "/api/v2/order",
        "DELETE",
        {"symbol": symbol_v2, "orderId": str(order_id)},
        algo,
    )


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
      if harga_sekarang <= slot["entry_price_idr"]:
        slot["status"] = "HOLDING_FOR_TP"
        slot["filled_timestamp"] = now_ts
        slot["highest_price_idr"] = harga_sekarang
        log_aksi.append(
            f"✅ [ENTRY TERBELI] {coin} ({mode_slot}) di"
            f" Rp{slot['entry_price_idr']:,.0f}. Kawal TP"
            f" Rp{slot['tp_price_idr']:,.0f}."
        )
        slot_tetap_aktif.append(slot)
        continue

      if umur_antre_jam <= REVIEW_ENTRY_HOURS:
        log_aksi.append(
            f"⏳ [ANTRE BELI {umur_antre_jam:.1f}j] {coin}"
            f" (Rp{slot['capital_idr']:,.0f}) di"
            f" Rp{slot['entry_price_idr']:,.0f}."
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
        order_id_baru = (
            respon_baru.get("orderId")
            or (respon_baru.get("data") or {}).get("orderId")
            or (respon_baru.get("return") or {}).get("order_id")
        )
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


def hitung_pecahan_slot_elastis(anggaran_tersedia):
  if anggaran_tersedia < MIN_ORDER_IDR_INDODAX:
    return []

  daftar_pecahan = []
  sisa = math.floor(anggaran_tersedia)

  while sisa >= IDEAL_SLOT_SIZE_IDR:
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

  if saldo_idr_dompet is not None:
    anggaran_bisa_dipakai = min(batas_sisa_plafon_bot, saldo_idr_dompet)
  else:
    anggaran_bisa_dipakai = batas_sisa_plafon_bot

  daftar_peluru_idr = hitung_pecahan_slot_elastis(anggaran_bisa_dipakai)

  if not daftar_peluru_idr:
    return state, [
        f"[MODAL TERKELOLA MAKSIMAL] Aktif: Rp{modal_sedang_terpakai:,.0f} |"
        f" Sisa Saldo Bebas: Rp{anggaran_bisa_dipakai:,.0f}."
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

    respon_order, qty_dikirim = eksekusi_beli_limit_indodax(
        coin, nominal_peluru, entry_idr
    )
    order_id = (
        respon_order.get("orderId")
        or (respon_order.get("data") or {}).get("orderId")
        or (respon_order.get("return") or {}).get("order_id")
    )

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
          "timestamp": time.time(),
      }
      state["active_slots"].append(slot_baru)
      log_alokasi.append(
          f"🚀 [INDODAX ORDER #{order_id} - {gaya}] {coin} | Modal:"
          f" Rp{nominal_peluru:,.0f} (Qty:{qty_dikirim}) | Beli:"
          f" Rp{entry_idr:,.0f} -> TP: Rp{tp_idr:,.0f}"
      )
    else:
      pesan_gagal = (
          respon_order.get("error")
          or respon_order.get("msg")
          or str(respon_order)
      )
      log_alokasi.append(
          f"⚠️ [INFO ORDER INDODAX] {coin} (Rp{nominal_peluru:,.0f} @"
          f" Rp{entry_idr:,.0f}) -> {pesan_gagal}"
      )

  return state, log_alokasi


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
      "pasangan": f"INDODAX QUAD ({len(state['active_slots'])} Slot)",
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
      "rsi_14": "Indodax-Auto",
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
  saldo_idr_bebas, saldo_koin_map = deteksi_dan_cek_saldo_indodax()
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
