"""
AI Маркетолог Таҳлил — Meta Ads (харажат/лид) ва Bitrix24 (сотув) маълумотини
бирлаштиради, CPO/ROAS ҳисоблайди, Claude орқали чуқур таҳлил ва аниқ
тавсия беради. Telegram'га юборади (раҳбар ва/ёки таргетолог гуруҳларига).

Фойдаланиш:
    python3 claude_analysis.py --days 1        # kunlik (kecha)
    python3 claude_analysis.py --days 7        # haftalik strategik
    python3 claude_analysis.py --days 30       # oylik strategik
"""

import os, sys, json, argparse
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import gspread
from google.oauth2.service_account import Credentials

TZ = timezone(timedelta(hours=5))
SHEET_ID = os.environ.get("MK_SHEET_ID", "")
SA_JSON = os.environ.get("MK_SA_JSON", "/root/marketing_bot/service_account.json")
ANTHROPIC_KEY = os.environ.get("MK_ANTHROPIC_KEY", "")
TELEGRAM_TOKEN = os.environ.get("MK_TELEGRAM_TOKEN", "")
ADMIN_IDS = [x.strip() for x in os.environ.get("MK_ADMIN_IDS", "").split(",") if x.strip()]

try:
    import anthropic
    _claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY) if ANTHROPIC_KEY else None
except Exception:
    _claude = None

def _book():
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(SA_JSON, scopes=scopes)
    return gspread.authorize(creds).open_by_key(SHEET_ID)

def _num(v):
    try:
        s = str(v).replace("$", "").replace(",", ".").replace(" ", "").strip()
        return float(s or 0)
    except ValueError:
        return 0.0

# ── Маълумотни йиғиш ──────────────────────────────────────────────────────
def load_meta(book, date_from, date_to):
    """Meta_Kunlik -> {targetolog: {spend, impressions, clicks, leads}}"""
    try:
        ws = book.worksheet("Meta_Kunlik")
    except Exception:
        return {}
    rows = ws.get_all_values()[1:]
    agg = defaultdict(lambda: {"spend": 0.0, "impressions": 0, "clicks": 0, "leads": 0})
    for r in rows:
        if len(r) < 8:
            continue
        sana = r[0]
        if not (date_from <= sana <= date_to):
            continue
        name = r[1]
        agg[name]["spend"] += _num(r[4])
        agg[name]["impressions"] += int(_num(r[5]))
        agg[name]["clicks"] += int(_num(r[6]))
        agg[name]["leads"] += int(_num(r[7]))
    return agg

def load_bitrix(book, date_from, date_to):
    """Bitrix_Kunlik -> {targetolog: {jami, sotildi, sotuv_summa}}"""
    try:
        ws = book.worksheet("Bitrix_Kunlik")
    except Exception:
        return {}
    rows = ws.get_all_values()[1:]
    agg = defaultdict(lambda: {"jami": 0, "sotildi": 0, "sotuv_summa": 0.0})
    for r in rows:
        if len(r) < 7:
            continue
        sana = r[0]
        if not (date_from <= sana <= date_to):
            continue
        name = r[1]
        agg[name]["jami"] += int(_num(r[2]))
        agg[name]["sotildi"] += int(_num(r[3]))
        agg[name]["sotuv_summa"] += _num(r[6])
    return agg

USD_TO_UZS = float(os.environ.get("USD_TO_UZS", "12650"))

def combine(meta, bitrix):
    """Meta va Bitrix'ni targetolog nomi bo'yicha birlashtiradi, CPO/ROAS hisoblaydi.
    МУҲИМ: Meta spend — доллар ($), Bitrix sotuv_summa — сўм. CPO/ROAS учун
    ҳисоблашда spend'ни сўмга ўтказамиз (акс ҳолда рақамлар мантиқсиз чиқади)."""
    names = set(meta.keys()) | set(bitrix.keys())
    combined = {}
    for name in names:
        if name.startswith("Belgilanmagan") or name.startswith("Noma'lum"):
            continue  # таргетологга боғланмаган — маркетолог таҳлилига қўшмаймиз
        m = meta.get(name, {"spend": 0, "impressions": 0, "clicks": 0, "leads": 0})
        b = bitrix.get(name, {"jami": 0, "sotildi": 0, "sotuv_summa": 0.0})
        spend_usd = m["spend"]
        spend_uzs = spend_usd * USD_TO_UZS
        leads = m["leads"]
        sotildi = b["sotildi"]
        sotuv = b["sotuv_summa"]
        cpl_usd = spend_usd / leads if leads else 0
        cpo_uzs = spend_uzs / sotildi if sotildi else 0   # сотув нархи, сўмда
        roas = sotuv / spend_uzs if spend_uzs else 0       # иккиси ҳам сўмда — тўғри нисбат
        ctr = m["clicks"] / m["impressions"] * 100 if m["impressions"] else 0
        combined[name] = {
            "spend_usd": round(spend_usd, 2), "leads": leads, "ctr": round(ctr, 2),
            "bitrix_jami": b["jami"], "sotildi": sotildi, "sotuv_summa_som": round(sotuv, 2),
            "cpl_usd": round(cpl_usd, 2), "cpo_som": round(cpo_uzs, 2), "roas": round(roas, 2),
        }
    return combined

# ── Claude таҳлил ──────────────────────────────────────────────────────────
def build_prompt(combined, date_from, date_to, is_strategic):
    period_label = "ҲАФТАЛИК/ОЙЛИК СТРАТЕГИК" if is_strategic else "КУНЛИК"
    data_json = json.dumps(combined, ensure_ascii=False, indent=2)
    task = (
        "Чуқур стратегик таҳлил бер: тенденция, каналлар бўйича фикр "
        "(Meta'дан ташқари Google/TikTok синаш керакми), узоқ муддатли тавсия."
        if is_strategic else
        "Тезкор диагноз бер: бугун-эртага нима қилиш керак, аниқ ҳаракат таклиф қил."
    )
    return (
        f"Сен — тажрибали маркетинг директори (Facebook/Instagram таргетинг, "
        f"Ўзбекистон бозори, БАД/маҳсулот сотуви). Қуйида {date_from} — {date_to} "
        f"даври учун ҳар таргетолог бўйича маълумот (spend_usd=реклама харажати $, "
        f"leads=лид сони, cpl_usd=лид нархи $, sotildi=реал сотилган (Доставка "
        f"воронкасидан), sotuv_summa_som=сотув summasi сўмда, cpo_som=битта сотув "
        f"нархи сўмда (харажат сўмга ўтказилган/sotildi), roas=фойда коэффициенти "
        f"(sotuv_summa_som / харажат сўмда — 1дан юқори бўлса фойда, паст бўлса зарар)):\n\n"
        f"{data_json}\n\n"
        f"{period_label} ТАҲЛИЛ керак, ЎЗБЕК тилида (кирилл), профессионал ва қисқа:\n"
        f"1) Умумий ҳолат (жами харажат, жами сотув, ўртача ROAS)\n"
        f"2) Ким яхши ишлаяпти (паст CPO, юқори ROAS) — аниқ рақам билан мақта\n"
        f"3) Кимга эътибор керак (юқори CPO, паст ROAS ёки ROAS<1 — зарар) — аниқ айт\n"
        f"4) АНИҚ ТАВСИЯ: кимнинг бюджетини ошириш/камайтириш керак, нега\n"
        f"5) {task}\n\n"
        f"Эслатма: ROAS<1 демак реклама харажати сотувдан кўп — зарар қиляпти (ҳисобда "
        f"валюта аллақачон бир хилга — сўмга — келтирилган, шунинг учун ROAS тўғри "
        f"кўрсаткич). Лид билан сотув орасида кечикиш бор (Регистрациядан Доставкага "
        f"етгунча бир неча кун), шунинг учун sotildi=0 бўлган таргетолог ҳали натижа "
        f"кутаётган бўлиши мумкин — буни ҳам эсла."
    )

async def _dummy():  # placeholder if needed later for async telegram
    pass

def send_telegram(text):
    if not TELEGRAM_TOKEN or not ADMIN_IDS:
        print("⚠️ Telegram sozlanmagan — faqat konsolga chiqaraman")
        return
    import urllib.request, urllib.parse
    for chat_id in ADMIN_IDS:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            data = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:4000]}).encode()
            urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15)
        except Exception as e:
            print(f"⚠️ Telegram yuborishda xato ({chat_id}): {e}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1, help="tahlil oynasi (1=kecha, 7=hafta, 30=oy)")
    args = ap.parse_args()

    if not SHEET_ID:
        sys.exit("❌ MK_SHEET_ID o'rnatilmagan")
    if not _claude:
        sys.exit("❌ MK_ANTHROPIC_KEY o'rnatilmagan yoki anthropic kutubxonasi yo'q")

    today = datetime.now(TZ).date()
    if args.days == 1:
        d_from = d_to = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        d_from = (today - timedelta(days=args.days)).strftime("%Y-%m-%d")
        d_to = today.strftime("%Y-%m-%d")

    print(f"📊 Tahlil oynasi: {d_from} — {d_to}")
    book = _book()
    meta = load_meta(book, d_from, d_to)
    bitrix = load_bitrix(book, d_from, d_to)
    combined = combine(meta, bitrix)

    if not combined:
        print("⚠️ Maʼlumot topilmadi.")
        sys.exit(0)

    print(json.dumps(combined, ensure_ascii=False, indent=2))

    is_strategic = args.days > 1
    prompt = build_prompt(combined, d_from, d_to, is_strategic)
    resp = _claude.messages.create(model="claude-opus-4-5", max_tokens=2000,
                                   messages=[{"role": "user", "content": prompt}])
    analysis = resp.content[0].text.strip()

    title = "🧠 ҲАФТАЛИК/ОЙЛИК СТРАТЕГИК ТАҲЛИЛ" if is_strategic else "🧠 КУНЛИК ТАҲЛИЛ"
    full_text = f"{title}\n📅 {d_from} — {d_to}\n\n{analysis}"
    print("\n" + "=" * 60)
    print(full_text)
    send_telegram(full_text)