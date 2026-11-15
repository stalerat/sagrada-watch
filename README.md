# Sagrada Família ticket watch

Checks the official booking page for the basic ticket (entry + audio guide in the app)
roughly every 75 seconds (each run lasts ~45 min and starts the next one itself) and sends a Telegram message when any day from
Mon 16 to Mon 23 Nov 2026 becomes bookable. Notify-only: it never books or pays.

- Weekdays: 2 adults + baby. Sat 21 / Sun 22: 3 adults + baby.
- The baby still needs a free "Under 11s" ticket in the same booking.
- It stops by itself once all the dates have passed (or delete the repo / disable the workflow).

## Setup
1. Repo secrets (Settings → Secrets and variables → Actions):
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
2. Actions tab → "Sagrada Familia ticket watch" → Run workflow → tick "test alert"
   to confirm you get the Telegram message.
3. Keep the repo **public**: public repos get free unlimited Actions minutes.
   No secrets live in the code.

Local run: `pip install -r requirements.txt && playwright install chromium && python checker.py`
