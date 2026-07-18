"""
AI Практик Маркетолог — Telegram бот.
- Ҳар куни 00:20 да автомат КУНЛИК таҳлил юборади
- Ҳар душанба 9:00 да автомат ҲАФТАЛИК стратегик таҳлил юборади
- Исталган пайт эркин савол ёзсанг — Meta+Bitrix маълумотига қараб жавоб беради
  (масалан: "Umar яхши ишляптими?", "бу ҳафта нима қилиш керак?", "Eldor'га нима дейсан?")

Команды:
  /start
  /bugun — кунлик таҳлилни дарров олиш
  /hafta — ҳафталик стратегик таҳлилни дарров олиш
  Оддий хабар — эркин савол сифатида Claude'га боради
"""

import os, sys, json, logging, fcntl
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from claude_analysis import (
    _book, load_meta, load_bitrix, combine, build_prompt, _claude,
)

_lock = open("/tmp/mkbot.lock", "w")
try:
    fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.stderr.write("Бот уже запущен.\n"); sys.exit(1)

TELEGRAM_TOKEN = os.environ.get("MK_TELEGRAM_TOKEN", "")
ADMIN_IDS = set()
for x in os.environ.get("MK_ADMIN_IDS", "").split(","):
    x = x.strip()
    if x.isdigit():
        ADMIN_IDS.add(int(x))

TZ = timezone(timedelta(hours=5))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

def is_admin(uid):
    return uid in ADMIN_IDS

# ── Таҳлил ясаш (кунлик/ҳафталик) ──────────────────────────────────────────
def get_analysis(days):
    today = datetime.now(TZ).date()
    if days == 1:
        d_from = d_to = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        d_from = (today - timedelta(days=days)).strftime("%Y-%m-%d")
        d_to = today.strftime("%Y-%m-%d")
    book = _book()
    meta = load_meta(book, d_from, d_to)
    bitrix = load_bitrix(book, d_from, d_to)
    combined = combine(meta, bitrix)
    if not combined:
        return None, d_from, d_to
    prompt = build_prompt(combined, d_from, d_to, is_strategic=(days > 1))
    resp = _claude.messages.create(model="claude-opus-4-5", max_tokens=2000,
                                   messages=[{"role": "user", "content": prompt}])
    return resp.content[0].text.strip(), d_from, d_to

# ── Автомат жоблар ─────────────────────────────────────────────────────────
async def daily_job(context):
    try:
        analysis, d_from, d_to = get_analysis(1)
        if not analysis:
            log.info("Kunlik: maʼlumot yoʻq (%s)", d_from)
            return
        text = f"🧠 КУНЛИК ТАҲЛИЛ\n📅 {d_from}\n\n{analysis}"
        for aid in ADMIN_IDS:
            await context.bot.send_message(chat_id=aid, text=text[:4000])
    except Exception as e:
        log.error("daily_job: %s", e)

async def weekly_job(context):
    try:
        analysis, d_from, d_to = get_analysis(7)
        if not analysis:
            log.info("Haftalik: maʼlumot yoʻq")
            return
        text = f"🧠 ҲАФТАЛИК СТРАТЕГИК ТАҲЛИЛ\n📅 {d_from} — {d_to}\n\n{analysis}"
        for aid in ADMIN_IDS:
            await context.bot.send_message(chat_id=aid, text=text[:4000])
    except Exception as e:
        log.error("weekly_job: %s", e)

# ── Командалар ──────────────────────────────────────────────────────────────
async def cmd_start(update, context):
    u = update.effective_user
    if not is_admin(u.id):
        await update.message.reply_text("⛔ Бу бот фақат маркетинг раҳбарига."); return
    await update.message.reply_text(
        "👋 AI Практик Маркетолог\n\n"
        "🔹 /bugun — кунлик таҳлил (дарров)\n"
        "🔹 /hafta — ҳафталик стратегик таҳлил (дарров)\n\n"
        "Исталган саволингизни оддий хабар сифатида ёзинг — "
        "мен Meta ва Bitrix маълумотига қараб жавоб бераман.\n"
        "Мисол: «Umar яхши ишляптими?», «бу ҳафта кимга эътибор керак?»\n\n"
        "Автомат хабарлар:\n"
        "• Ҳар куни 00:20 — кунлик таҳлил\n"
        "• Ҳар душанба 9:00 — ҳафталик стратегик таҳлил")

async def cmd_bugun(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Рухсат йўқ."); return
    await update.message.reply_text("🧠 Таҳлил тайёрланмоқда...")
    try:
        analysis, d_from, d_to = get_analysis(1)
        if not analysis:
            await update.message.reply_text("⚠️ " + d_from + " учун маълумот топилмади."); return
        await update.message.reply_text(f"🧠 КУНЛИК ТАҲЛИЛ\n📅 {d_from}\n\n{analysis}"[:4000])
    except Exception as e:
        await update.message.reply_text("❌ Хато: " + str(e))

async def cmd_hafta(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Рухсат йўқ."); return
    await update.message.reply_text("🧠 Ҳафталик таҳлил тайёрланмоқда...")
    try:
        analysis, d_from, d_to = get_analysis(7)
        if not analysis:
            await update.message.reply_text("⚠️ Маълумот топилмади."); return
        await update.message.reply_text(f"🧠 ҲАФТАЛИК ТАҲЛИЛ\n📅 {d_from} — {d_to}\n\n{analysis}"[:4000])
    except Exception as e:
        await update.message.reply_text("❌ Хато: " + str(e))

# ── Эркин суҳбат ─────────────────────────────────────────────────────────────
async def on_text(update, context):
    u = update.effective_user
    msg = update.message
    if not is_admin(u.id) or not msg or not msg.text:
        return
    question = msg.text.strip()
    await context.bot.send_chat_action(chat_id=msg.chat_id, action="typing")
    try:
        # сўнгги 30 кунлик маълумотни контекст сифатида берамиз
        today = datetime.now(TZ).date()
        d_from = (today - timedelta(days=30)).strftime("%Y-%m-%d")
        d_to = today.strftime("%Y-%m-%d")
        book = _book()
        meta = load_meta(book, d_from, d_to)
        bitrix = load_bitrix(book, d_from, d_to)
        combined = combine(meta, bitrix)
        data_json = json.dumps(combined, ensure_ascii=False, indent=2)

        prompt = (
            "Сен — тажрибали маркетинг директори (Facebook/Instagram таргетинг, "
            "Ўзбекистон бозори). Раҳбар сендан савол сўраяпти. Қуйида сўнгги 30 кунлик "
            f"(({d_from} — {d_to}) ҳар таргетолог бўйича маълумот "
            "(spend_usd=харажат $, leads=лид, cpl_usd=лид нархи $, sotildi=реал сотилган, "
            "sotuv_summa_som=сотув сўмда, cpo_som=сотув нархи сўмда, roas=фойда коэффициенти):\n\n"
            f"{data_json}\n\n"
            f"РАҲБАРНИНГ САВОЛИ: {question}\n\n"
            "Шу маълумотга асосланиб, ЎЗБЕК тилида (кирилл), қисқа ва аниқ, "
            "самимий суҳбат услубида жавоб бер. Рақамлар билан исботла."
        )
        resp = _claude.messages.create(model="claude-opus-4-5", max_tokens=1200,
                                       messages=[{"role": "user", "content": prompt}])
        await msg.reply_text(resp.content[0].text.strip()[:4000])
    except Exception as e:
        await msg.reply_text("❌ Хато: " + str(e))

# ── Запуск ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not TELEGRAM_TOKEN:
        sys.exit("❌ MK_TELEGRAM_TOKEN o'rnatilmagan")
    if not _claude:
        sys.exit("❌ MK_ANTHROPIC_KEY o'rnatilmagan")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("bugun", cmd_bugun))
    app.add_handler(CommandHandler("hafta", cmd_hafta))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    from datetime import time as dtime
    app.job_queue.run_daily(daily_job, time=dtime(hour=0, minute=20, tzinfo=TZ))
    app.job_queue.run_daily(weekly_job, time=dtime(hour=9, minute=0, tzinfo=TZ), days=(0,))

    log.info("AI Практик Маркетолог бот запущен.")
    app.run_polling()