# ==============================================================================
# SMART DYNAMIC HYBRID AI TRADING BOT 24/7 (LIVE ORDER TOKOCRYPTO + SHEETS)
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
SLOT_SIZE_IDR = float(os.getenv("SLOT_SIZE_IDR", "25000"))

FEE_ROUNDTRIP_MAKER_PCT = 0.004544
FEE_ROUNDTRIP_TAKER_PCT = 0.005544

TP_GRID_BASE_PCT = 0.018
SL_GRID_BASE_PCT = 0.020
TP_SNIPER_BASE_PCT = 0.035
SL_SNIPER_BASE_PCT = 0.018

REVIEW_ENTRY_HOURS = 6.0
PRE_TIMESTOP_HOURS = 40.0
FINAL_TIMESTOP_HOURS = 48.0

WATCHLIST_COINS = {
    "SOL": {
        "toko_symbol": "SOL_IDR",
        "kraken_pair": "SOLUSD",
        "indodax_key": "sol_idr",
        "step_decimals": 2,
    },
    "BTC": {
        "toko_symbol": "BTC_IDR",
        "kraken_pair": "XXBTZUSD",
        "indodax_key": "btc_idr",
        "step_decimals": 5,
    },
    "ETH": {
        "toko_symbol": "ETH_IDR",
        "kraken_pair": "XETHZUSD",
        "indodax_key": "eth_idr",
        "step_decimals": 4,
    },
    "XRP": {
        "toko_symbol": "XRP_IDR",
        "kraken_pair": "XXRPZUSD",
        "indodax_key": "xrp_idr",
        "step_decimals": 0,
    },
    "ADA": {
        "toko_symbol": "ADA_IDR",
        "kraken_pair": "ADAUSD",
        "indodax_key": "ada_idr",
        "step_decimals": 1,
    },
    "SUI": {
        "toko_symbol": "SUI_IDR",
        "kraken_pair": "SUIUSD",
        "indodax_key": "sui_idr",
        "step_decimals": 1,
    },
    "DOGE": {
        "toko_symbol": "DOGE_IDR",
        "kraken_pair": "XDGUSD",
        "indodax_key": "doge_idr",
        "step_decimals": 0,
    },
}

STATE_FILE = "bot_state_tokocrypto.json"

TOKOCRYPTO_API_KEY = os.getenv("TOKOCRYPTO_API_KEY", "").strip()
TOKOCRYPTO_SECRET_KEY = os.getenv("TOKOCRYPTO_SECRET_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GOOGLE_SHEETS_WEBHOOK_URL = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
LIVE_TRADING_ENABLED = bool(TOKOCRYPTO_API_KEY and TOKOCRYPTO_SECRET_KEY)


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
      "completed_trades_today": 0,
  }


def simpan_state_bot(state):
  with open(STATE_FILE, "w") as f:
    json.dump(state, f, indent=2)


def tanda_tangan_hmac(query_string, secret_key):
  return hmac.new(
      secret_key.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256
  ).hexdigest()


def panggil_api_tokocrypto(endpoint, method="GET", params=None, signed=False):
  if params is None:
    params = {}
  base_url = "https://www.tokocrypto.com"
  if signed:
    if not TOKOCRYPTO_API_KEY or not TOKOCRYPTO_SECRET_KEY:
      return {"code": -1, "msg": "TOKOCRYPTO_API_KEY kosong di Secrets"}
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 10000
    query_str = urllib.parse.urlencode(params)
    signature = tanda_tangan_hmac(query_str, TOKOCRYPTO_SECRET_KEY)
    full_query = f"{query_str}&signature={signature}"
  else:
    full_query = urllib.parse.urlencode(params)

  target_url = (
      f"{base_url}{endpoint}?{full_query}"
      if full_query
      else f"{base_url}{endpoint}"
  )
  headers = {"User-Agent": "Mozilla/5.0"}
  if signed:
    headers["X-MBX-APIKEY"] = TOKOCRYPTO_API_KEY

  # Daftar jalur pengiriman: Jalur 1 (Langsung), Jalur 2 & 3 (Relay Server Non-AS untuk tembus HTTP 451)
  jalur_urls = [
      target_url,
      f"https://corsproxy.io/?{urllib.parse.quote(target_url, safe='')}",
      f"https://api.codetabs.com/v1/proxy?quest={urllib.parse.quote(target_url, safe='')}",
  ]

  last_err = {}
  for idx, url_coba in enumerate(jalur_urls):
    req = urllib.request.Request(url_coba, headers=headers, method=method)
    try:
      with urllib.request.urlopen(req, timeout=15) as resp:
        raw_text = resp.read().decode("utf-8", errors="ignore")
        if "/not-support" in raw_text:
          last_err = {
              "code": 451,
              "msg": f"Jalur {idx+1} masih terblokir 451 AS",
          }
          continue
        return json.loads(raw_text)
    except urllib.error.HTTPError as he:
      err_body = he.read().decode("utf-8", errors="ignore")
      last_err = {
          "code": he.code,
          "msg": f"Jalur {idx+1} HTTP {he.code}: {err_body[:100]}",
      }
      if he.code in (451, 403):
        continue
      return last_err
    except Exception as e:
      last_err = {"code": -1, "msg": f"Jalur {idx+1} Err: {str(e)}"}
      continue
  return last_err


def hitung_kuantitas_koin(coin, nominal_idr, harga_idr):
  decimals = WATCHLIST_COINS[coin]["step_decimals"]
  raw_qty = nominal_idr / harga_idr
  factor = 10**decimals
  qty = math.floor(raw_qty * factor) / factor
  return int(qty) if decimals == 0 else round(qty, decimals)


def eksekusi_order_tokocrypto(
    coin, side_str, order_type_str, qty, price_idr=None
):
  if not LIVE_TRADING_ENABLED:
    return {"code": -1, "msg": "Simulasi (API Key kosong)"}

  symbol = WATCHLIST_COINS[coin]["toko_symbol"]
  params = {
      "symbol": symbol,
      "side": 0 if side_str == "BUY" else 1,
      "type": 1 if order_type_str == "LIMIT" else 2,
      "quantity": str(qty),
  }
  if order_type_str == "LIMIT" and price_idr is not None:
    params["price"] = str(int(round(price_idr)))

  res = panggil_api_tokocrypto(
      "/open/v1/orders", method="POST", params=params, signed=True
  )
  print(
      f"👉 [TOKOCRYPTO LIVE ORDER] {side_str} {symbol} | Qty={qty} |"
      f" Harga=Rp{price_idr} -> Respon Server: {res}"
  )
  return res


def batalkan_order_tokocrypto(coin, order_id):
  if not LIVE_TRADING_ENABLED or not order_id or str(order_id).startswith("SIM"):
    return
  symbol = WATCHLIST_COINS[coin]["toko_symbol"]
  params = {"symbol": symbol, "orderId": str(order_id)}
  res = panggil_api_tokocrypto(
      "/open/v1/orders/cancel", method="POST", params=params, signed=True
  )
  print(
      f"👉 [TOKOCRYPTO CANCEL ORDER] {symbol} orderId={order_id} -> Respon:"
      f" {res}"
  )


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


def evaluasi_dan_kawal_posisi_dinamis(state, peta_analisa):
  slot_tetap_aktif = []
  log_aksi = []
  now_ts = time.time()

  semua_kandidat = sorted(
      peta_analisa.values(), key=lambda x: x["skor"], reverse=True
  )
  koin_terbaik_pasar = semua_kandidat[0] if semua_kandidat else None

  for slot in state["active_slots"]:
    if LIVE_TRADING_ENABLED and (
        not slot.get("buy_order_id")
        or str(slot.get("buy_order_id")).startswith("SIM")
    ):
      log_aksi.append(
          f"[RESET SIMULASI] Menghapus slot simulasi lama {slot['coin']}."
      )
      continue

    coin = slot["coin"]
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
    qty_koin = slot.get(
        "qty",
        hitung_kuantitas_koin(
            coin, slot["capital_idr"], slot["entry_price_idr"]
        ),
    )

    if slot["status"] == "WAITING_BUY":
      if harga_sekarang <= slot["entry_price_idr"]:
        slot["status"] = "HOLDING_FOR_TP"
        slot["filled_timestamp"] = now_ts
        slot["highest_price_idr"] = harga_sekarang
        log_aksi.append(
            f"✅ [ENTRY TERBELI] {coin} ({mode_slot}) di"
            f" Rp{slot['entry_price_idr']:,.0f}."
        )
        slot_tetap_aktif.append(slot)
        continue

      if umur_antre_jam <= REVIEW_ENTRY_HOURS:
        log_aksi.append(
            f"⏳ [ANTRE BELI {umur_antre_jam:.1f}j] {coin}"
            f" (ID:{slot.get('buy_order_id')}) di"
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
        batalkan_order_tokocrypto(coin, slot.get("buy_order_id"))
        entry_baru_idr = info_pasar["entry_ideal_idr"]
        tp_pct = (
            TP_SNIPER_BASE_PCT if mode_slot == "SNIPER" else TP_GRID_BASE_PCT
        )
        sl_pct = (
            SL_SNIPER_BASE_PCT if mode_slot == "SNIPER" else SL_GRID_BASE_PCT
        )
        qty_baru = hitung_kuantitas_koin(
            coin, slot["capital_idr"], entry_baru_idr
        )
        respon_baru = eksekusi_order_tokocrypto(
            coin, "BUY", "LIMIT", qty_baru, entry_baru_idr
        )
        if respon_baru.get("code") == 0:
          slot["entry_price_idr"] = entry_baru_idr
          slot["qty"] = qty_baru
          slot["tp_price_idr"] = round(entry_baru_idr * (1.0 + tp_pct), 0)
          slot["sl_price_idr"] = round(entry_baru_idr * (1.0 - sl_pct), 0)
          slot["buy_order_id"] = respon_baru.get("data", {}).get("orderId")
          slot["timestamp"] = now_ts
          log_aksi.append(
              f"📈 [NAIKKAN ENTRY >6J] {coin} digeser ke"
              f" Rp{entry_baru_idr:,.0f}!"
          )
          slot_tetap_aktif.append(slot)
      else:
        batalkan_order_tokocrypto(coin, slot.get("buy_order_id"))
        log_aksi.append(
            f"🔄 [GANTI KOIN >6J] Antrean {coin} dibatalkan, anggaran"
            " dialihkan."
        )

    elif slot["status"] == "HOLDING_FOR_TP":
      umur_hold_jam = (now_ts - slot.get("filled_timestamp", now_ts)) / 3600.0
      kenaikan_skrg_pct = (harga_sekarang - slot["entry_price_idr"]) / slot[
          "entry_price_idr"
      ]

      if harga_sekarang >= slot["tp_price_idr"]:
        eksekusi_order_tokocrypto(coin, "SELL", "LIMIT", qty_koin, harga_sekarang)
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
        eksekusi_order_tokocrypto(coin, "SELL", "LIMIT", qty_koin, harga_sekarang)
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
            slot["entry_price_idr"] * (1.0 + FEE_ROUNDTRIP_TAKER_PCT + 0.0175),
            0,
        )
        slot["sl_price_idr"] = max(slot["sl_price_idr"], sl_target)
      elif kenaikan_skrg_pct >= 0.022:
        if rsi_sekarang >= 68.0 or tren_sekarang != "UPTREND":
          eksekusi_order_tokocrypto(
              coin, "SELL", "LIMIT", qty_koin, harga_sekarang
          )
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
              * (1.0 + FEE_ROUNDTRIP_TAKER_PCT + 0.0105),
              0,
          )
          slot["sl_price_idr"] = max(slot["sl_price_idr"], sl_target)
      elif kenaikan_skrg_pct >= 0.015:
        sl_target = round(
            slot["entry_price_idr"] * (1.0 + FEE_ROUNDTRIP_TAKER_PCT + 0.0040),
            0,
        )
        slot["sl_price_idr"] = max(slot["sl_price_idr"], sl_target)

      if umur_hold_jam >= PRE_TIMESTOP_HOURS:
        tp_dinamis_40h_pct = min(max(potensi_naik_pct, 0.010), 0.022)
        if umur_hold_jam < FINAL_TIMESTOP_HOURS:
          if tren_sekarang == "UPTREND" and rsi_sekarang < 65:
            slot["tp_price_idr"] = min(
                slot["tp_price_idr"],
                round(slot["entry_price_idr"] * (1.0 + tp_dinamis_40h_pct), 0),
            )
          elif kenaikan_skrg_pct >= 0.0085:
            eksekusi_order_tokocrypto(
                coin, "SELL", "LIMIT", qty_koin, harga_sekarang
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
        elif kenaikan_skrg_pct >= 0.0080:
          eksekusi_order_tokocrypto(
              coin, "SELL", "LIMIT", qty_koin, harga_sekarang
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

      log_aksi.append(
          f"🎯 [KAWAL TP] {coin} ({mode_slot}) | Skrg: Rp{harga_sekarang:,.0f}"
          f" ({kenaikan_skrg_pct*100:+.2f}%) -> TP:"
          f" Rp{slot['tp_price_idr']:,.0f}"
      )
      slot_tetap_aktif.append(slot)

  state["active_slots"] = slot_tetap_aktif
  return state, log_aksi


def kelola_anggaran_kosong_dengan_analisa(state, peta_analisa):
  modal_sedang_terpakai = sum(
      slot["capital_idr"] for slot in state["active_slots"]
  )
  sisa_jatah_modal_bot = max(0.0, MAX_BOT_CAPITAL_IDR - modal_sedang_terpakai)
  jumlah_slot_kosong = int(sisa_jatah_modal_bot // SLOT_SIZE_IDR)

  if jumlah_slot_kosong <= 0:
    return state, [
        f"[MODAL PENUH] Rp{modal_sedang_terpakai:,.0f} sedang aktif bekerja."
    ]

  kandidat_urut = sorted(
      [v for v in peta_analisa.values() if v["gaya"] != "WAIT_OVERBOUGHT"],
      key=lambda x: x["skor"],
      reverse=True,
  )

  log_alokasi = []
  slot_terpasang = 0

  for kandidat in kandidat_urut:
    if slot_terpasang >= jumlah_slot_kosong:
      break
    coin = kandidat["coin"]
    if sum(1 for s in state["active_slots"] if s["coin"] == coin) >= 2:
      continue

    gaya = kandidat["gaya"]
    entry_idr = int(round(kandidat["entry_ideal_idr"]))
    tp_pct = TP_SNIPER_BASE_PCT if gaya == "SNIPER" else TP_GRID_BASE_PCT
    sl_pct = SL_SNIPER_BASE_PCT if gaya == "SNIPER" else SL_GRID_BASE_PCT
    tp_idr = int(round(entry_idr * (1.0 + tp_pct)))
    sl_idr = int(round(entry_idr * (1.0 - sl_pct)))
    qty_koin = hitung_kuantitas_koin(coin, SLOT_SIZE_IDR, entry_idr)

    respon_order = eksekusi_order_tokocrypto(
        coin, "BUY", "LIMIT", qty_koin, entry_idr
    )

    if respon_order.get("code") == 0:
      order_id = respon_order.get("data", {}).get("orderId")
      slot_baru = {
          "coin": coin,
          "style": gaya,
          "status": "WAITING_BUY",
          "capital_idr": SLOT_SIZE_IDR,
          "qty": qty_koin,
          "entry_price_idr": entry_idr,
          "tp_price_idr": tp_idr,
          "sl_price_idr": sl_idr,
          "rsi_at_entry": kandidat["rsi"],
          "buy_order_id": order_id,
          "timestamp": time.time(),
      }
      state["active_slots"].append(slot_baru)
      slot_terpasang += 1
      log_alokasi.append(
          f"🚀 [LIVE ORDER SUKSES #{order_id} - {gaya}] {coin} | Limit Buy:"
          f" Rp{entry_idr:,.0f} (Qty: {qty_koin}) -> TP: Rp{tp_idr:,.0f}"
      )
    else:
      pesan_gagal = respon_order.get("msg", str(respon_order))
      log_alokasi.append(
          f"⚠️ [ORDER DITOLAK TOKOCRYPTO] {coin} (Qty:{qty_koin} @"
          f" Rp{entry_idr:,.0f}) -> Alasan: {pesan_gagal}"
      )

  return state, log_alokasi


def lapor_ke_google_sheets(state, semua_log):
  ringkasan_slot = (
      ", ".join([
          f"{s['coin']}[{s['style']}:{s['status']}@Rp{s['entry_price_idr']:,.0f}]"
          for s in state["active_slots"]
      ])
      or "Belum ada order aktif"
  )
  catatan_lengkap = " | ".join(semua_log)[:480]

  payload = {
      "tanggal": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
      "pasangan": f"HYBRID LIVE ({len(state['active_slots'])} Slot)",
      "modal_aktif_idr": sum(s["capital_idr"] for s in state["active_slots"]),
      "harga_acuan_idr": MAX_BOT_CAPITAL_IDR,
      "jumlah_grid_tereksekusi": state["completed_trades_today"],
      "profit_terealisasi_idr": state["realized_profit_today_idr"],
      "floating_pnl_idr": 0,
      "tren_1h": ringkasan_slot,
      "rsi_14": "Live-Sync",
      "analisis_ai_gemini": catatan_lengkap,
  }

  print("=== RINGKASAN EKSEKUSI SMART DYNAMIC HYBRID BOT ===")
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
  harga_live = ambil_harga_idr_semua_koin()
  peta_analisa_pasar = analisa_teknikal_lengkap_pasar(harga_live)
  state, log_kawal = evaluasi_dan_kawal_posisi_dinamis(
      state, peta_analisa_pasar
  )
  state, log_alokasi = kelola_anggaran_kosong_dengan_analisa(
      state, peta_analisa_pasar
  )
  simpan_state_bot(state)
  lapor_ke_google_sheets(state, log_kawal + log_alokasi)
