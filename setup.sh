#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Daily Executive Report — One-Command Setup
# ─────────────────────────────────────────────────────────────
set -e

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  Daily Executive Report  ·  Setup"
echo "════════════════════════════════════════════════════════════"
echo ""

# 1. Python check
if ! command -v python3 &> /dev/null; then
    echo "  ERROR: python3 is required. Install from https://python.org"
    exit 1
fi

# 2. Virtual environment
echo "  Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 3. Dependencies
echo "  Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "  Dependencies installed."

# 4. .env file
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "  ─────────────────────────────────────────────────────"
    echo "  ACTION REQUIRED: Add your Anthropic API key to .env"
    echo "  ─────────────────────────────────────────────────────"
    echo "  1. Open .env in any text editor"
    echo "  2. Replace 'your_anthropic_api_key_here' with your key"
    echo "     Get one free at: https://console.anthropic.com/"
    echo ""
    echo "  For Telegram delivery (optional — free, 2 min):"
    echo "  1. Open Telegram → message @BotFather → send /newbot"
    echo "  2. Name your bot, copy the token → add to .env as TELEGRAM_BOT_TOKEN"
    echo "  3. Start a chat with your bot (search it, press Start)"
    echo "  4. Open: https://api.telegram.org/botYOUR_TOKEN/getUpdates"
    echo "     Find your chat ID → add to .env as TELEGRAM_CHAT_ID"
    echo "  ─────────────────────────────────────────────────────"
else
    echo "  .env already exists — skipping."
fi

echo ""
echo "  Setup complete!"
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  NEXT STEPS"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "  1. Add your API key to .env"
echo "  2. Run your first report:"
echo ""
echo "       source venv/bin/activate"
echo "       python daily_report.py"
echo ""
echo "  ── TO SCHEDULE DAILY REPORT AT 7:00 AM ──────────────────"
echo "  Run:  crontab -e"
echo "  Add this line (update the path):"
echo ""
echo "    0 7 * * * cd $(pwd) && source venv/bin/activate && python daily_report.py >> reports/cron.log 2>&1"
echo ""
echo "  ── TO SCHEDULE FILM GIG HUNTER (every 30 min) ────────────"
echo "  Add this line to crontab -e:"
echo ""
echo "    */30 * * * * cd $(pwd) && source venv/bin/activate && python film_gig_hunter.py >> reports/gigs-cron.log 2>&1"
echo ""
echo "  Or quieter (3x daily: 8am, noon, 5pm):"
echo ""
echo "    0 8,12,17 * * * cd $(pwd) && source venv/bin/activate && python film_gig_hunter.py >> reports/gigs-cron.log 2>&1"
echo ""
echo "  Run it once now to test:"
echo ""
echo "       source venv/bin/activate"
echo "       python film_gig_hunter.py"
echo ""
echo "════════════════════════════════════════════════════════════"
echo ""
