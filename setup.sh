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
    echo "  For email delivery (optional — Gmail, free):"
    echo "  1. Enable 2-Step Verification on your Google account"
    echo "  2. Go to: myaccount.google.com → Security → App Passwords"
    echo "  3. Create a password for Mail"
    echo "  4. Add it to .env as GMAIL_APP_PASSWORD"
    echo "  5. Fill in sender_email and recipient_email in config.yaml"
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
echo "  ── TO SCHEDULE DAILY AT 7:00 AM ──────────────────────────"
echo "  Run:  crontab -e"
echo "  Add this line (update the path):"
echo ""
echo "    0 7 * * * cd $(pwd) && source venv/bin/activate && python daily_report.py >> reports/cron.log 2>&1"
echo ""
echo "════════════════════════════════════════════════════════════"
echo ""
