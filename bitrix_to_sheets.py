"""
Bitrix24 -> Google Sheets. Сделкаларни лид санаси (DATE_CREATE) бўйича кунларга
бўлиб, ҳар таргетолог учун жами/сотилди/сотув суммасини ҳисоблайди.

МУҲИМ: сделка ҳолати вақт ўтиши билан ўзгаради (Регистрация -> Доставка),
шунинг учун бу скрипт ҳар ишга тушганда сўнгги N кунни ҚАЙТА ҲИСОБЛАБ,
эскисини янгилайди (шунчаки қўшмайди) — токи "сотилди" сони ва сумма
доим ЖОРИЙ ҳолатни кўрсатсин.

Фойдаланиш:
    python3 bitrix_to_sheets.py                 # oxirgi 14 kunni qayta hisoblaydi
    python3 bitrix_to_sheets.py --days 30
"""

import os, sys, argparse
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import gspread
from google.oauth2.service_account import Credentials

from bitrix import fetch_deals, FIELD_TARGETOLOG, TARGETOLOG_MAP, DELIVERY_CATEGORY_ID

TZ = timezone(timedelta(hours=5))
SHEET_ID = os.environ.get("MK_SHEET_ID", "")
SA_JSON = os.environ.get("MK_SA_JSON", "/root/marketing_bot/service_account.json")
WS_NAME = "Bitrix_Kunlik"

HEADERS = ["Sana", "Targetolog", "Jami_lid", "Sotildi", "Jarayonda",
           "Yoqotildi", "Sotuv_summa", "Yangilandi"]

def _book():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(SA_JSON, scopes=scopes)
    return gspread.authorize(creds).open_by_key(SHEET_ID)

def ensure_ws(book):
    try:
        return book.worksheet(WS_NAME)
    except Exception:
        ws = book.add_worksheet(title=WS_NAME, rows=3000, cols=len(HEADERS) + 2)
        ws.append_row(HEADERS)
        return ws

def bucket_deals(deals):
    """Сделкаларни (сана, таргетолог) бўйича гуруҳлайди."""
    buckets = defaultdict(lambda: {"jami": 0, "sotildi": 0, "sotuv_summa": 0.0,
                                   "jarayonda": 0, "yoqotildi": 0})
    for d in deals:
        date_create = (d.get("DATE_CREATE") or "")[:10]  # YYYY-MM-DD
        if not date_create:
            continue
        tid = str(d.get(FIELD_TARGETOLOG) or "")
        name = TARGETOLOG_MAP.get(tid, "Noma'lum(" + tid + ")") if tid else "Belgilanmagan"
        b = buckets[(date_create, name)]
        b["jami"] += 1
        category = str(d.get("CATEGORY_ID", ""))
        semantic = d.get("STAGE_SEMANTIC_ID", "")
        if category == DELIVERY_CATEGORY_ID and semantic == "S":
            b["sotildi"] += 1
            b["sotuv_summa"] += float(d.get("OPPORTUNITY") or 0)
        elif semantic == "F":
            b["yoqotildi"] += 1
        else:
            b["jarayonda"] += 1
    return buckets

if __name__ == "__main__":
    if not SHEET_ID:
        sys.exit("❌ MK_SHEET_ID o'rnatilmagan")
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14,
                    help="oxirgi necha kunni qayta hisoblash (lag uchun, default 14)")
    args = ap.parse_args()

    today = datetime.now(TZ).date()
    window_start = (today - timedelta(days=args.days)).strftime("%Y-%m-%d")
    window_end = today.strftime("%Y-%m-%d")

    print(f"📥 Bitrix24: {window_start} — {window_end} qayta hisoblanmoqda...")
    deals = fetch_deals(window_start, window_end)
    print(f"Jami sdelka: {len(deals)}")

    buckets = bucket_deals(deals)
    now = datetime.now(TZ).strftime("%d.%m.%Y %H:%M")
    new_rows = []
    for (sana, name), b in sorted(buckets.items()):
        new_rows.append([sana, name, b["jami"], b["sotildi"], b["jarayonda"],
                         b["yoqotildi"], round(b["sotuv_summa"], 2), now])

    book = _book()
    ws = ensure_ws(book)
    all_vals = ws.get_all_values()
    header = all_vals[0] if all_vals else HEADERS
    old_rows = all_vals[1:] if len(all_vals) > 1 else []

    # эски қаторлардан ОЙНА ТАШҚАРИСИДАГИЛАРНИ сақлаймиз (масалан 15+ кун олдинги тарих)
    kept = [r for r in old_rows if r and (r[0] < window_start or r[0] > window_end)]

    final_rows = kept + new_rows
    final_rows.sort(key=lambda r: (r[0], r[1]))

    ws.clear()
    ws.append_row(HEADERS)
    if final_rows:
        ws.append_rows(final_rows, value_input_option="USER_ENTERED")

    print(f"✅ Yangilandi: {len(new_rows)} ta (oyna: {window_start}—{window_end}), "
          f"saqlangan eski: {len(kept)}, jami qator: {len(final_rows)}")