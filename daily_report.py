#!/usr/bin/env python3
"""
Daily Executive Report Generator
Businesses: Castient | Ten Four Pictures | Video Production Directory
"""

import os
import json
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def hr(char="─", width=62):
    return char * width

def section(title, char="─"):
    print(f"\n{hr(char)}")
    print(f"  {title}")
    print(hr(char))

def ask(label: str, default: str = "") -> str:
    """Prompt the user for input with an optional default."""
    if default:
        val = input(f"  {label} [{default}]: ").strip()
        return val if val else default
    val = input(f"  {label}: ").strip()
    return val if val else "—"

def ask_optional(label: str) -> str:
    val = input(f"  {label} (or Enter to skip): ").strip()
    return val if val else "none"

# ─────────────────────────────────────────────────────────────
# Data Gathering
# ─────────────────────────────────────────────────────────────

def gather_castient() -> dict:
    section("CASTIENT  ·  B2B Content & Podcast Production  ·  castient.com")
    print()
    return {
        "active_retainer_clients":   ask("Active retainer clients", "0"),
        "mrr_month_to_date":         ask("MRR / revenue this month ($)", "0"),
        "leads_in_pipeline":         ask("Leads currently in pipeline", "0"),
        "new_leads_since_yesterday": ask_optional("New leads / inquiries since yesterday"),
        "deliverables_due_today":    ask_optional("Content deliverables due today"),
        "client_calls_today":        ask_optional("Client calls or meetings today"),
        "completed_yesterday":       ask_optional("Key task completed yesterday"),
        "main_focus_today":          ask_optional("Main focus for Castient today"),
        "blockers":                  ask_optional("Blockers or risks"),
    }


def gather_tenfour() -> dict:
    section("TEN FOUR PICTURES  ·  Video Production  ·  tenfour.pictures")
    print()
    return {
        "active_productions":        ask("Active productions / projects", "0"),
        "revenue_month_to_date":     ask("Revenue this month to date ($)", "0"),
        "new_inquiries_this_week":   ask("New project inquiries this week", "0"),
        "proposals_outstanding":     ask("Proposals / quotes outstanding", "0"),
        "shoots_or_milestones_today":ask_optional("Shoots, deliveries, or client milestones today"),
        "client_calls_today":        ask_optional("Client calls or meetings today"),
        "completed_yesterday":       ask_optional("Key task completed yesterday"),
        "main_focus_today":          ask_optional("Main focus for Ten Four today"),
        "blockers":                  ask_optional("Blockers or risks"),
    }


def gather_directory() -> dict:
    section("VIDEO PRODUCTION DIRECTORY  ·  New Digital Product  ·  In Development")
    print()
    return {
        "current_stage":             ask("Current stage (e.g. design / dev / beta)", "development"),
        "target_launch_date":        ask("Target launch date", "TBD"),
        "listings_loaded":           ask("Directory listings loaded so far", "0"),
        "features_shipped":          ask_optional("Features completed so far"),
        "worked_on_yesterday":       ask_optional("What did you work on yesterday"),
        "focus_today":               ask_optional("Dev / build focus today"),
        "blockers":                  ask_optional("Blockers or risks"),
    }


def gather_priorities() -> list:
    section("TOP 3 PRIORITIES  ·  Across all businesses")
    print("  What are the 3 most important outcomes for today?\n")
    priorities = []
    for i in range(1, 4):
        p = ask(f"Priority #{i}")
        if p and p != "—":
            priorities.append(p)
    return priorities if priorities else ["Not specified"]


def gather_context() -> dict:
    section("WINS & MARKET SIGNALS  ·  Optional but valuable")
    print()
    return {
        "wins_from_yesterday":  ask_optional("Any wins or momentum from yesterday"),
        "concerns":             ask_optional("Anything keeping you up at night"),
        "market_news":          ask_optional("Any market news or signals you've seen"),
    }


# ─────────────────────────────────────────────────────────────
# Report Generation
# ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior strategic advisor writing a daily executive briefing for a
multi-business founder. Your tone is direct, intelligent, and concise — like a trusted COO
who has read everything and distills it to signal. No filler, no padding, no corporate speak."""

def build_user_prompt(date: str, castient: dict, tenfour: dict, directory: dict,
                      priorities: list, context: dict) -> str:
    return f"""Write a daily executive report for this founder's three businesses.

TODAY: {date}

━━━ BUSINESS CONTEXT ━━━

CASTIENT (castient.com)
- Model: B2B content & podcast production, retainer-based
- What they do: Turn internal business insights into podcast-style narrative content used for
  demand generation and sales enablement. "Narrative formats drive 22x more recall than data alone."
- Target clients: Enterprise SaaS companies, CPG brands, C-suite executives
- Deliverable: Full episode production + 8 content cutdowns per episode (Slack, Teams, decks, etc.)

TEN FOUR PICTURES (tenfour.pictures)
- Model: Boutique video production, Toronto, project-based ($5k–$25k+ per project)
- What they do: Handcrafted branded content, commercials, music videos, documentaries, live events,
  animation, post-production. Founded 2020. "Handcrafted Moving Images."
- Clients: CPG brands, NGOs, music industry, B2C companies, healthcare

VIDEO PRODUCTION DIRECTORY
- What: New digital product being built — a directory website for the video production industry
- Status: In development

━━━ TODAY'S DATA ━━━

FOUNDER'S TOP 3 PRIORITIES:
{json.dumps(priorities, indent=2)}

CASTIENT METRICS & STATUS:
{json.dumps(castient, indent=2)}

TEN FOUR PICTURES METRICS & STATUS:
{json.dumps(tenfour, indent=2)}

VIDEO PRODUCTION DIRECTORY STATUS:
{json.dumps(directory, indent=2)}

WINS & MARKET SIGNALS:
{json.dumps(context, indent=2)}

━━━ FORMAT ━━━

Produce the report EXACTLY in this structure (use these exact headers):

═══════════════════════════════════════════════════════════════
DAILY EXECUTIVE REPORT  ·  {date}
═══════════════════════════════════════════════════════════════

[One sharp sentence: the headline state of the business portfolio today]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯  TOP PRIORITIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Numbered list. For each priority add 1 sentence explaining why it matters strategically.]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊  BUSINESS SNAPSHOT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  CASTIENT
  [4–6 bullet KPI lines + 1 line on today's focus]

  TEN FOUR PICTURES
  [4–6 bullet KPI lines + 1 line on today's focus]

  VIDEO PRODUCTION DIRECTORY
  [Stage, progress, today's focus, target launch]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌍  EXTERNAL FORCES & MARKET SIGNALS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[4–5 bullet points. Cover: B2B content marketing trends, video production industry,
 podcast/audio content demand, directory/marketplace businesses, AI impact on content production.
 Use any market news the founder provided. Be specific and actionable, not generic.]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚧  BLOCKERS & RISKS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Synthesize all blockers from today's data. Flag any strategic or operational risks you see
 that the founder may not have mentioned. Be direct — no softening.]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡  EXECUTIVE BRIEF
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[3–4 strategic recommendations. Be direct. What should he stop, start, accelerate, or watch?
 Think across all 3 businesses — where is leverage? where is the bottleneck?]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡  QUICK WINS FOR TODAY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[2–3 specific actions that can be done today and will compound. Make them concrete.]

═══════════════════════════════════════════════════════════════
End of Report  ·  {date}
═══════════════════════════════════════════════════════════════
"""


def generate_report(date: str, castient: dict, tenfour: dict, directory: dict,
                    priorities: list, context: dict) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\n  ERROR: ANTHROPIC_API_KEY not set in .env file.")
        print("  Get your key at https://console.anthropic.com/ then add it to .env")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print("\n  Calling Claude API  ·  generating report...")

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": build_user_prompt(date, castient, tenfour, directory, priorities, context)
        }]
    )

    return message.content[0].text


# ─────────────────────────────────────────────────────────────
# Save & Email
# ─────────────────────────────────────────────────────────────

def save_report(report: str, date_slug: str) -> str:
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    filepath = reports_dir / f"{date_slug}.md"
    with open(filepath, "w") as f:
        f.write(f"# Daily Executive Report\n\n```\n{report}\n```\n")
    return str(filepath)


def send_email(report: str, subject: str, config: dict) -> bool:
    """Send report via Gmail SMTP (free). Requires GMAIL_APP_PASSWORD in .env"""
    email_cfg = config.get("email", {})
    sender    = email_cfg.get("sender_email", "")
    recipient = email_cfg.get("recipient_email", "")
    password  = os.environ.get("GMAIL_APP_PASSWORD", "")

    if not all([sender, recipient, password]):
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = sender
        msg["To"]      = recipient

        # Plain text
        msg.attach(MIMEText(report, "plain"))

        # Dark-themed HTML
        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0f0f0f;">
  <div style="font-family:'Courier New',Courier,monospace;font-size:13px;
              line-height:1.7;color:#d4d4d4;max-width:680px;margin:0 auto;
              padding:32px 24px;background:#0f0f0f;">
    <pre style="white-space:pre-wrap;word-break:break-word;margin:0;">{report}</pre>
  </div>
</body>
</html>"""
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())

        return True
    except Exception as e:
        print(f"\n  ⚠  Email failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def main():
    config = load_config()
    now    = datetime.now()
    date   = now.strftime("%A, %B %d, %Y")
    slug   = now.strftime("%Y-%m-%d")

    print("\n" + hr("═"))
    print(f"  DAILY EXECUTIVE REPORT  ·  {date}")
    print(f"  Castient  |  Ten Four Pictures  |  Directory")
    print(hr("═"))
    print("\n  Answer each prompt. Press Enter to use the default or skip.\n")

    castient   = gather_castient()
    tenfour    = gather_tenfour()
    directory  = gather_directory()
    priorities = gather_priorities()
    context    = gather_context()

    section("GENERATING YOUR REPORT", "═")
    report = generate_report(date, castient, tenfour, directory, priorities, context)

    # Print to terminal
    print("\n\n" + report + "\n")

    # Save to file
    saved = save_report(report, slug)
    print(f"\n  Saved  →  {saved}")

    # Email
    subject = f"Executive Report — {date}"
    if send_email(report, subject, config):
        recipient = config.get("email", {}).get("recipient_email", "")
        print(f"  Emailed →  {recipient}")
    else:
        print("  Email  →  not configured (see .env and config.yaml)")

    print(f"\n{hr('═')}\n")


if __name__ == "__main__":
    main()
