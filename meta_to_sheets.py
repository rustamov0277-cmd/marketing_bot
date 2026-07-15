"""
Meta Ads -> Google Sheets. Ҳар куни ишга тушади (cron), Meta'дан кечаги/бугунги
кунлик рақамни ўқийди, "Meta_Kunlik" варағига ёзади (такрор ёзмайди — 
сана+кабинет бўйича текшириб, аввал ёзилган бўлса ўчириб қайта ёзади).

Фойдаланиш:
    python3 meta_to_sheets.py                # bugungi kun
    python3 meta_to_sheets.py --date 2026-07-15
    python3 meta_to_sheets.py --backfill 7   # oxirgi 7 kunni yozadi (birinchi ishga tushirishda)
"""

import os, sys, argparse
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials

from meta_ads import fetch_all, AD_ACCOUNTS

TZ = timezone(timedelta(hours=5))
SHEET_ID = os.environ.get("MK_SHEET_ID", "")
SA_JSON = os.environ.get("MK_SA_JSON", "/root/marketing_bot/service_account.json")
WS_NAME = "Meta_Kunlik"

HEADERS = ["Sana", "Targetolog", "Brend/Kampaniya", "Akkaunt_ID",
           "Xarajat_USD", "Korsatishlar", "Kliklar", "Lidlar",
           "CPL_USD", "CTR", "CPM_USD", "CR", "Yozildi"]

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

def write_day(ws, date_str, existing_keys):
    """Пишет данные за один день. existing_keys — set строк 'sana|act_id' уже записанных."""
    results = fetch_all(date_str)
    now = datetime.now(TZ).strftime("%d.%m.%Y %H:%M")
    new_rows = []
    for r in results:
        if "error" in r:
            print(f"⚠️ {date_str} {r['targetolog']} ({r['brand']}): {r['error'][:100]}")
            continue
        key = date_str + "|" + r["act_id"]
        if key in existing_keys:
            continue  # уже есть — не дублируем
        new_rows.append([
            date_str, r["targetolog"], r["brand"], r["act_id"],
            round(r["spend"], 2), r["impressions"], r["clicks"], r["leads"],
            round(r["cpl"], 2), round(r["ctr"], 2), round(r["cpm"], 2), round(r["cr"], 2),
            now,
        ])
        existing_keys.add(key)
    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
    return len(new_rows)

if __name__ == "__main__":
    if not SHEET_ID:
        sys.exit("❌ MK_SHEET_ID o'rnatilmagan")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--backfill", type=int, default=0, help="oxirgi N kunni yozish")
    args = ap.parse_args()

    book = _book()
    ws = ensure_ws(book)
    existing = set()
    for row in ws.get_all_values()[1:]:
        if len(row) >= 4:
            existing.add(row[0] + "|" + row[3])

    if args.backfill:
        total = 0
        for i in range(args.backfill, -1, -1):
            d = (datetime.now(TZ) - timedelta(days=i)).strftime("%Y-%m-%d")
            n = write_day(ws, d, existing)
            print(f"📅 {d}: {n} ta yangi yozuv")
            total += n
        print(f"✅ Jami yozildi: {total}")
    else:
        date_str = args.date or datetime.now(TZ).strftime("%Y-%m-%d")
        n = write_day(ws, date_str, existing)
        print(f"✅ {date_str}: {n} ta yangi yozuv Sheets'ga yozildi")