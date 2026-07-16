"""
Bitrix24 -> сделкалар (Deals) орқали таргетолог бўйича лид ва сотув маълумоти.
Майдон: UF_CRM_1772197583641 = "Таргетолог" (enumeration, ID->номи пастда).

Фойдаланиш:
    python3 bitrix.py                       # bugungi kun
    python3 bitrix.py --date 2026-07-15
    python3 bitrix.py --from 2026-07-01 --to 2026-07-16   # oraliq (strategik tahlil uchun)
"""

import os, sys, json, argparse, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=5))
WEBHOOK = os.environ.get("BITRIX_WEBHOOK", "").rstrip("/") + "/"

FIELD_TARGETOLOG = "UF_CRM_1772197583641"
DELIVERY_CATEGORY_ID = "6"  # "Доставка" воронкаси — фақат шу ерда реал сотув суммаси бор

# ID -> targetolog nomi (Bitrix24'dan olingan ro'yxat)
TARGETOLOG_MAP = {
    "700": "Eldor",     # Bitrix'da "Элдор"
    "702": "Umar",
    "704": "Abbos",     # Bitrix'da "Аббос"
    "708": "Timur",
    "724": "Sobirjon",
}

def _post(method, params):
    url = WEBHOOK + method + ".json"
    data = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code}: {body}") from e

def fetch_deals(date_from, date_to):
    """Сделкалар: date_from/date_to = 'YYYY-MM-DD'. Постранично читает всё."""
    all_deals = []
    start = 0
    while True:
        params = {
            "filter": {
                ">=DATE_CREATE": date_from + "T00:00:00",
                "<=DATE_CREATE": date_to + "T23:59:59",
            },
            "select": ["ID", "TITLE", "OPPORTUNITY", "CURRENCY_ID",
                      "CATEGORY_ID", "STAGE_ID", "STAGE_SEMANTIC_ID", "DATE_CREATE",
                      FIELD_TARGETOLOG],
            "start": start,
        }
        resp = _post("crm.deal.list", params)
        if "error" in resp:
            raise RuntimeError(resp.get("error_description", resp["error"]))
        batch = resp.get("result", [])
        all_deals.extend(batch)
        nxt = resp.get("next")
        if not nxt:
            break
        start = nxt
    return all_deals

def summarize(deals):
    """Группировка по таргетологу: жами лид, сотилган (ФАҚАТ Доставка+won), сотув суммаси.
    'Белгиланмаган' (таргетологсиз — директ/TikTok/YouTube/кирувчи қўнғироқ) алоҳида ҳисобланади,
    таргетолог статистикасига аралаштирилмайди."""
    stats = {}
    for d in deals:
        tid = str(d.get(FIELD_TARGETOLOG) or "")
        name = TARGETOLOG_MAP.get(tid, "Noma'lum(" + tid + ")") if tid else "Belgilanmagan (boshqa kanal)"
        s = stats.setdefault(name, {"jami": 0, "sotildi": 0, "sotuv_summa": 0.0,
                                    "jarayonda": 0, "yoqotildi": 0})
        s["jami"] += 1
        category = str(d.get("CATEGORY_ID", ""))
        semantic = d.get("STAGE_SEMANTIC_ID", "")
        # реал сотув — ФАҚАТ Доставка воронкасида (боshqa voronkada "won" bo'lsa ham,
        # bu faqat keyingi bosqichga o'tgani, real sotuv emas)
        if category == DELIVERY_CATEGORY_ID and semantic == "S":
            s["sotildi"] += 1
            s["sotuv_summa"] += float(d.get("OPPORTUNITY") or 0)
        elif semantic == "F":
            s["yoqotildi"] += 1
        else:
            s["jarayonda"] += 1
    return stats

if __name__ == "__main__":
    if not os.environ.get("BITRIX_WEBHOOK"):
        sys.exit("❌ BITRIX_WEBHOOK o'rnatilmagan")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--from", dest="date_from", default=None)
    ap.add_argument("--to", dest="date_to", default=None)
    args = ap.parse_args()

    if args.date_from and args.date_to:
        d_from, d_to = args.date_from, args.date_to
    else:
        d = args.date or datetime.now(TZ).strftime("%Y-%m-%d")
        d_from = d_to = d

    print(f"📥 Bitrix24: {d_from} — {d_to} oralig'idagi sdelkalar o'qilmoqda...")
    deals = fetch_deals(d_from, d_to)
    print(f"Jami topildi: {len(deals)} ta sdelka\n")

    stats = summarize(deals)
    print(f"{'Targetolog':12s} | {'Jami':>5s} | {'Sotildi':>8s} | {'Jarayon':>8s} | "
          f"{'Yo\'qotildi':>10s} | {'Sotuv summa':>14s}")
    print("-" * 75)
    named = {k: v for k, v in stats.items() if not k.startswith("Belgilanmagan")}
    other = {k: v for k, v in stats.items() if k.startswith("Belgilanmagan")}
    for name, s in sorted(named.items(), key=lambda x: -x[1]["sotuv_summa"]):
        print(f"{name:12s} | {s['jami']:>5d} | {s['sotildi']:>8d} | "
              f"{s['jarayonda']:>8d} | {s['yoqotildi']:>10d} | {s['sotuv_summa']:>14,.0f}")
    if other:
        print("-" * 75)
        for name, s in other.items():
            print(f"{name:12s} | {s['jami']:>5d} | {s['sotildi']:>8d} | "
                  f"{s['jarayonda']:>8d} | {s['yoqotildi']:>10d} | {s['sotuv_summa']:>14,.0f}")
    print("\nEslatma: 'Sotildi' va 'Sotuv summa' FAQAT 'Доставка' voronkasidagi "
          "yakunlangan sdelkalardan olinadi.\nLid DATE_CREATE sanasi bilan olinadi, "
          "lekin sotuv (Doставка) bir necha kun kechikishi mumkin —\nshuning uchun "
          "bugungi lidlarning sotuvi hali ko'rinmasligi mumkin (normal holat).")