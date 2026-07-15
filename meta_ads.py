"""
Meta Ads (Facebook/Instagram) — кунлик рақамларни автомат ўқиш.
Ҳар кабинет учун: харажат (spend), кўрсатиш (impressions), клик (clicks),
лид (leads — actions ичидан), шундан CPL/CTR/CPM/CR ҳисобланади.

Фойдаланиш:
    python3 meta_ads.py            # бугунги рақам, барча кабинет
    python3 meta_ads.py --date 2026-07-10
"""

import os, sys, json, argparse, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=5))
META_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
API_VER = "v21.0"

# ── Кабинетлар: ID -> (Таргетолог, Кампания/бренд номи) ────────────────────
AD_ACCOUNTS = {
    "act_1383613729264521": {"targetolog": "Eldor",   "brand": "Collagen marine"},
    "act_440073592484616":  {"targetolog": "Umar",    "brand": "Zextra"},
    "act_1702549647737942": {"targetolog": "Sobirjon","brand": "Zextra.new"},
    "act_714191238260025":  {"targetolog": "Eldor",   "brand": "Sinolife family"},
    "act_440763388459898":  {"targetolog": "Eldor",   "brand": "Zextra"},
    "act_1920554638484437": {"targetolog": "Kamron",  "brand": "Zextra"},
}

def _get(url, params):
    qs = urllib.parse.urlencode(params)
    full = url + "?" + qs
    req = urllib.request.Request(full, headers={"User-Agent": "AI-Marketolog/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code}: {body}") from e

USD_TO_UZS = float(os.environ.get("USD_TO_UZS", "12650"))
CONVERT_TO_UZS = os.environ.get("MK_CONVERT_UZS", "0") == "1"  # 0 = $ da qoladi (default)

def fetch_account_insights(act_id, date_str):
    """Возвращает дневную статистику по одному рекламному кабинету."""
    url = f"https://graph.facebook.com/{API_VER}/{act_id}/insights"
    params = {
        "access_token": META_TOKEN,
        "time_range": json.dumps({"since": date_str, "until": date_str}),
        "fields": "spend,impressions,clicks,ctr,cpm,actions,account_name,account_currency",
        "level": "account",
    }
    data = _get(url, params)
    rows = data.get("data", [])
    if not rows:
        return {"spend": 0, "spend_raw": 0, "currency": "USD", "impressions": 0, "clicks": 0, "leads": 0,
                "ctr": 0, "cpm": 0, "account_name": ""}
    r = rows[0]
    leads = 0
    for a in r.get("actions", []):
        # ФАҚАТ асл "lead" event — бошқа "*_add_meta_leads" / "*_grouped" турлари ДУБЛИКАТ,
        # уларни қўшмаймиз (акс ҳолда лид сони бир неча марта ошиб кетади)
        if a.get("action_type") == "lead":
            leads += int(float(a.get("value", 0)))
    currency = r.get("account_currency", "USD")
    spend = float(r.get("spend", 0))
    impressions = int(r.get("impressions", 0))
    # агар кабинет USD'да юритилса — сўмга ўтказамиз (харажат ва CPL сўмда чиқиши учун)
    spend_uzs = spend * USD_TO_UZS if (currency == "USD" and CONVERT_TO_UZS) else spend
    return {
        "spend": spend_uzs,
        "spend_raw": spend,
        "currency": currency,
        "impressions": impressions,
        "clicks": int(r.get("clicks", 0)),
        "leads": leads,
        "ctr": float(r.get("ctr", 0)),
        "cpm": float(r.get("cpm", 0)) * (USD_TO_UZS if (currency == "USD" and CONVERT_TO_UZS) else 1),
        "account_name": r.get("account_name", ""),
    }

def calc_metrics(spend, impressions, clicks, leads):
    cpl = spend / leads if leads else 0
    ctr = clicks / impressions * 100 if impressions else 0
    cpm = spend / impressions * 1000 if impressions else 0
    cr = leads / clicks * 100 if clicks else 0
    return {"cpl": cpl, "ctr": ctr, "cpm": cpm, "cr": cr}

def fetch_all(date_str):
    """Читает ВСЕ кабинеты за дату, возвращает список записей."""
    if not META_TOKEN:
        raise RuntimeError("META_ACCESS_TOKEN o'rnatilmagan")
    out = []
    for act_id, info in AD_ACCOUNTS.items():
        try:
            raw = fetch_account_insights(act_id, date_str)
        except Exception as e:
            out.append({"act_id": act_id, "error": str(e), **info})
            continue
        m = calc_metrics(raw["spend"], raw["impressions"], raw["clicks"], raw["leads"])
        out.append({
            "act_id": act_id, "targetolog": info["targetolog"], "brand": info["brand"],
            "sana": date_str,
            "spend": raw["spend"], "spend_raw": raw["spend_raw"], "currency": raw["currency"],
            "impressions": raw["impressions"],
            "clicks": raw["clicks"], "leads": raw["leads"],
            "cpl": m["cpl"], "ctr": m["ctr"], "cpm": m["cpm"], "cr": m["cr"],
        })
    return out

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD, default = bugun")
    ap.add_argument("--debug", action="store_true", help="bitta kabinet uchun xom javobni ko'rsat")
    args = ap.parse_args()
    date_str = args.date or datetime.now(TZ).strftime("%Y-%m-%d")

    if args.debug:
        first_act = list(AD_ACCOUNTS.keys())[0]
        url = f"https://graph.facebook.com/{API_VER}/{first_act}/insights"
        params = {
            "access_token": META_TOKEN,
            "time_range": json.dumps({"since": date_str, "until": date_str}),
            "fields": "spend,impressions,clicks,ctr,cpm,actions,account_name,account_currency",
            "level": "account",
        }
        data = _get(url, params)
        print(json.dumps(data, indent=2, ensure_ascii=False))
        sys.exit(0)

    results = fetch_all(date_str)
    unit = "so'm" if CONVERT_TO_UZS else "$"
    print(f"\n📊 Meta Ads — {date_str} (barcha summalar {unit} da)\n" + "=" * 66)
    for r in results:
        if "error" in r:
            print(f"❌ {r['targetolog']} ({r['brand']}) — XATO: {r['error'][:120]}")
            continue
        spend_str = f"{r['spend']:,.0f} so'm" if CONVERT_TO_UZS else f"${r['spend']:,.2f}"
        cpl_str = f"{r['cpl']:,.0f} so'm" if CONVERT_TO_UZS else f"${r['cpl']:,.2f}"
        print(f"👤 {r['targetolog']:10s} | {r['brand']:16s} | "
              f"Xarajat: {spend_str:>14s} | Lid: {r['leads']:>3d} | "
              f"CPL: {cpl_str:>12s} | CTR: {r['ctr']:.2f}%")
    print("=" * 66)