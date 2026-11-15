"""
Sagrada Familia ticket watcher.

Loads the official public booking page in a headless browser (like a normal
visitor), reads which calendar days are bookable, and sends a Telegram message
when one of the target dates opens up. Notify-only: it never books or pays.

Env vars:
  TELEGRAM_BOT_TOKEN   token from @BotFather
  TELEGRAM_CHAT_ID     your chat id with the bot
  LOOP_MINUTES         how long to keep checking in one run (default 0 = single check)
  INTERVAL_SECONDS     pause between checks inside a run (default 75)
  TEST_ALERT=1         send a test message and exit
"""

import datetime as dt
import json
import os
import random
import sys
import time
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PRODUCT_URL = "https://tickets.sagradafamilia.org/en/1-individual/4375-sagrada-familia"
PAGE_URL = os.environ.get("SF_TEST_URL", PRODUCT_URL)  # override only for local tests

# date -> who is going (used in the alert text)
TARGETS = {
    "2026-11-16": "2 adults + baby",
    "2026-11-17": "2 adults + baby",
    "2026-11-18": "2 adults + baby",
    "2026-11-19": "2 adults + baby",
    "2026-11-20": "2 adults + baby",
    "2026-11-21": "3 adults + baby",
    "2026-11-22": "3 adults + baby",
    "2026-11-23": "2 adults + baby",
}

MADRID = dt.timezone(dt.timedelta(hours=1))  # CET (no DST in late November)


def log(*a):
    print(dt.datetime.now(MADRID).strftime("%H:%M:%S"), *a, flush=True)


def telegram(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        log("Telegram not configured; would send:\n" + text)
        return
    data = urllib.parse.urlencode(
        {"chat_id": chat, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


def open_dates_and_slots(page) -> dict:
    """Return {iso_date: [time slots]} for target dates that are bookable now."""
    page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_selector("td.CalendarDay", timeout=45_000)
    page.wait_for_timeout(2500)  # let the availability request repaint the calendar

    # The widget also renders hidden neighbouring months, so only look inside
    # the month block captioned "November 2026". Each day cell carries an
    # aria-label like "Tuesday, 24 November 2026" (or "Not available. ...").
    month_sel = "xpath=//div[contains(@class,'CalendarMonth ')][.//div[contains(@class,'CalendarMonth_caption')][normalize-space()='November 2026']]"
    month = page.locator(month_sel).first
    if month.count() == 0:
        raise RuntimeError("November 2026 calendar not found on page")
    if month.locator("td.CalendarDay").count() < 28:
        raise RuntimeError("Calendar day cells not rendered")

    found = {}
    open_cells = month.locator("td.CalendarDay[aria-disabled='false']")
    for i in range(open_cells.count()):
        label = (open_cells.nth(i).get_attribute("aria-label") or "").split(". ")[-1]
        try:
            iso = dt.datetime.strptime(label.strip(), "%A, %d %B %Y").date().isoformat()
        except ValueError:
            continue
        if iso in TARGETS:
            found[iso] = []

    # Best effort: click each open date and read the offered times.
    for iso in found:
        try:
            d = dt.date.fromisoformat(iso)
            month.locator(
                f"td.CalendarDay[aria-disabled='false'][aria-label$='{d:%A}, {d.day} {d:%B %Y}']"
            ).first.click()
            page.wait_for_timeout(3500)
            text = page.locator("main").inner_text()
            after = text.split("AT WHAT TIME?", 1)[-1].split("HOW MANY PEOPLE", 1)[0]
            slots = sorted(
                {t for t in after.split() if len(t) == 5 and t[2] == ":" and t.replace(":", "").isdigit()}
            )
            found[iso] = slots
        except Exception as e:  # times are a bonus; the day alert is what matters
            log(f"could not read times for {iso}: {e}")
    return found


def format_alert(found: dict) -> str:
    lines = ["🎟 Sagrada Família tickets just opened!"]
    for iso, slots in sorted(found.items()):
        d = dt.date.fromisoformat(iso)
        times = ", ".join(slots[:12]) if slots else "open the page to see times"
        lines.append(f"• {d:%a %d %b} ({TARGETS[iso]}): {times}")
    lines.append("")
    lines.append("Book now (slots go fast): " + PRODUCT_URL)
    lines.append("Tip: the baby needs a free 'Under 11s' ticket in the same booking.")
    return "\n".join(lines)


def main() -> int:
    if os.environ.get("TEST_ALERT") == "1":
        telegram("✅ Sagrada Família watcher is connected. You'll only hear from me when Nov 16–23 tickets appear.")
        return 0

    today = dt.datetime.now(MADRID).date().isoformat()
    for d in [d for d in TARGETS if d < today]:
        TARGETS.pop(d)
    if not TARGETS:
        log("All target dates are in the past; nothing to watch.")
        return 0

    loop_minutes = float(os.environ.get("LOOP_MINUTES", "0"))
    interval = int(os.environ.get("INTERVAL_SECONDS", "75"))
    deadline = time.time() + loop_minutes * 60

    alerted = set()          # dates already announced in this run
    consecutive_errors = 0
    error_alert_sent = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="en-GB", timezone_id="Europe/Madrid")
        page = ctx.new_page()
        while True:
            try:
                found = open_dates_and_slots(page)
                consecutive_errors = 0
                new = {d: s for d, s in found.items() if d not in alerted}
                log("open target dates:", json.dumps(found) if found else "none")
                if new:
                    telegram(format_alert(new))
                    alerted.update(new)
                # if a date sells out again, allow a fresh alert when it reopens
                alerted &= set(found)
            except (PWTimeout, Exception) as e:
                consecutive_errors += 1
                log(f"check failed ({consecutive_errors}): {e}")
                if consecutive_errors >= 4 and not error_alert_sent:
                    telegram(f"⚠️ Sagrada watcher can't read the ticket page right now ({type(e).__name__}). It keeps trying, but check manually meanwhile: {PRODUCT_URL}")
                    error_alert_sent = True
            if time.time() + interval > deadline:
                break
            time.sleep(interval + random.randint(-15, 15))
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
