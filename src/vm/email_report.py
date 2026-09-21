"""Daily summary report email.

The web app posts each user's session data at end-of-session. This
module aggregates the payload, asks the coach LLM for a free-form
clinical opinion, wraps it into a simple HTML email, and sends it
through Gmail SMTP.

Rate-limited to one email per user per day; the SQLite ledger under
`/var/lib/physiolive/reports.db` tracks who has already received a
report today.

Environment
    EMAIL_SMTP_HOST         default: smtp.gmail.com
    EMAIL_SMTP_PORT         default: 587 (STARTTLS)
    EMAIL_ADDRESS           the Gmail address that sends and receives
    EMAIL_APP_PASSWORD      Gmail app password for that account
    REPORT_RECIPIENT        recipient; defaults to EMAIL_ADDRESS
"""
from __future__ import annotations

import datetime as _dt
import html
import os
import smtplib
import sqlite3
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, List, Optional

import httpx


_STATE_DIR = Path(os.environ.get("PHYSIOLIVE_STATE_DIR", "/var/lib/physiolive"))
_REPORTS_DB = _STATE_DIR / "reports.db"


# ------------------------------------------------------------------ ledger

def _connect() -> sqlite3.Connection:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_REPORTS_DB))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sent_reports ("
        "  user_sub TEXT NOT NULL,"
        "  ymd TEXT NOT NULL,"
        "  sent_at INTEGER NOT NULL,"
        "  PRIMARY KEY(user_sub, ymd)"
        ")"
    )
    return conn


def already_sent_today(user_sub: str, today_ymd: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM sent_reports WHERE user_sub=? AND ymd=?",
            (user_sub, today_ymd),
        ).fetchone()
    return row is not None


def _mark_sent(user_sub: str, today_ymd: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sent_reports(user_sub, ymd, sent_at) "
            "VALUES (?, ?, strftime('%s','now'))",
            (user_sub, today_ymd),
        )


# ------------------------------------------------------------------ aggregation

def _aggregate(sessions: List[Dict]) -> Dict:
    """Turn the client-side session list into a structured summary."""
    out: Dict = {
        "total_sessions": 0,
        "total_reps": 0,
        "exercises": {},   # exercise_id -> {name, reps, good, warn, bad, angles_min, cues}
    }
    for s in sessions or []:
        ex_id = s.get("exercise") or "unknown"
        ex_name = s.get("exercise_name") or ex_id
        block = out["exercises"].setdefault(ex_id, {
            "name": ex_name, "reps": 0, "good": 0, "warn": 0, "bad": 0,
            "angles_min": [], "cues": {},
        })
        out["total_sessions"] += 1
        for r in s.get("reps") or []:
            block["reps"] += 1
            out["total_reps"] += 1
            level = (r.get("level") or "warn").lower()
            block[level if level in ("good", "warn", "bad") else "warn"] += 1
            if r.get("primary_min") is not None:
                block["angles_min"].append(r["primary_min"])
            cue = (r.get("text") or "").strip()
            if cue and level != "good":
                block["cues"][cue] = block["cues"].get(cue, 0) + 1

    for block in out["exercises"].values():
        angs = block["angles_min"]
        block["avg_angle_min"] = round(sum(angs) / len(angs), 1) if angs else None
        del block["angles_min"]
        # Sort cues by count descending, keep top 5.
        block["cues"] = sorted(
            block["cues"].items(), key=lambda kv: -kv[1])[:5]
        good_pct = (100.0 * block["good"] / block["reps"]) if block["reps"] else 0
        block["good_pct"] = round(good_pct, 1)
    return out


# ------------------------------------------------------------------ LLM opinion

_OPINION_PROMPT = (
    "You are a physiotherapist reviewing a patient's daily home "
    "rehabilitation log. Write a warm, specific opinion in 4-6 "
    "sentences, addressed directly to the patient. Cover:\n"
    "  - What went well today.\n"
    "  - One or two form issues that showed up most often.\n"
    "  - A concrete home-exercise suggestion for tomorrow (name a "
    "    specific move plus sets/reps).\n"
    "  - A safety note if the log shows repeated 'bad' verdicts.\n"
    "Do not invent measurements. Base the opinion on the numbers in "
    "the log. Do not repeat the raw numbers verbatim; interpret them."
)


def _clinical_opinion(summary: Dict) -> Optional[str]:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    lines = [f"Total sessions: {summary['total_sessions']}, "
             f"total reps: {summary['total_reps']}."]
    for ex_id, b in summary["exercises"].items():
        line = (f"- {b['name']}: {b['reps']} reps, "
                f"good {b['good']} / warn {b['warn']} / bad {b['bad']}, "
                f"good-form {b['good_pct']}%")
        if b["avg_angle_min"] is not None:
            line += f", avg primary-angle min {b['avg_angle_min']} deg"
        lines.append(line)
        for cue, n in b["cues"]:
            lines.append(f"    cue x{n}: {cue}")
    user_prompt = "\n".join(lines)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _OPINION_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 500,
        "temperature": 0.5,
    }
    if model.startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = "low"
    try:
        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload, timeout=20.0,
        )
        r.raise_for_status()
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = (msg.get("content") or "").strip()
        if content:
            return content
        # gpt-oss reasoning fallback.
        reasoning = (msg.get("reasoning") or "").strip()
        if reasoning:
            return reasoning
    except Exception as e:
        print(f"email_report: LLM opinion failed: "
              f"{type(e).__name__}: {e}")
    return None


# ------------------------------------------------------------------ email

def _compose_html(summary: Dict, opinion: Optional[str],
                  display_name: str, ymd: str) -> str:
    rows = []
    for ex_id, b in summary["exercises"].items():
        cues_html = ""
        if b["cues"]:
            cues_html = "<ul style='margin:6px 0 0;padding-left:18px'>" + "".join(
                f"<li>x{n}: {html.escape(cue)}</li>" for cue, n in b["cues"]
            ) + "</ul>"
        avg = (f"{b['avg_angle_min']}&deg;" if b["avg_angle_min"] is not None
               else "-")
        rows.append(
            f"<tr>"
            f"<td>{html.escape(b['name'])}</td>"
            f"<td style='text-align:right'>{b['reps']}</td>"
            f"<td style='text-align:right'>{b['good_pct']}%</td>"
            f"<td style='text-align:right'>{avg}</td>"
            f"<td>{cues_html or '-'}</td>"
            f"</tr>"
        )
    table = ("<table style='width:100%;border-collapse:collapse;"
             "font-family:system-ui,sans-serif;font-size:14px'>"
             "<thead><tr style='background:#e5e7eb'>"
             "<th style='text-align:left;padding:6px'>Exercise</th>"
             "<th style='text-align:right;padding:6px'>Reps</th>"
             "<th style='text-align:right;padding:6px'>Good form</th>"
             "<th style='text-align:right;padding:6px'>Avg min angle</th>"
             "<th style='text-align:left;padding:6px'>Top cues</th>"
             "</tr></thead>"
             "<tbody>"
             + ("".join(rows) if rows else
                "<tr><td colspan='5' style='padding:12px;color:#6b7280'>"
                "No reps recorded today.</td></tr>")
             + "</tbody></table>")
    opinion_html = ""
    if opinion:
        opinion_html = ("<h3 style='margin-top:24px'>Clinical opinion</h3>"
                        f"<p style='white-space:pre-wrap;line-height:1.55'>"
                        f"{html.escape(opinion)}</p>")
    else:
        opinion_html = ("<p style='color:#9ca3af;font-size:13px;"
                        "margin-top:24px'>"
                        "(LLM opinion unavailable this time.)</p>")

    return (
        "<html><body style='background:#0a0d14;color:#e5e7eb;"
        "font-family:system-ui,sans-serif;padding:16px'>"
        "<div style='max-width:640px;margin:0 auto;background:#111827;"
        "padding:20px;border-radius:12px'>"
        f"<h2 style='margin:0'>PhysioLive - Daily summary</h2>"
        f"<p style='color:#9ca3af;margin:4px 0 16px'>"
        f"{html.escape(display_name)} &middot; {html.escape(ymd)}"
        f" &middot; sessions {summary['total_sessions']} "
        f" &middot; reps {summary['total_reps']}</p>"
        + table + opinion_html +
        "<p style='margin-top:24px;color:#6b7280;font-size:12px'>"
        "Sent automatically by the PhysioLive VM. Reply to this email "
        "with feedback and it lands in your own inbox."
        "</p></div></body></html>"
    )


def _compose_plain(summary: Dict, opinion: Optional[str],
                   display_name: str, ymd: str) -> str:
    lines = [
        f"PhysioLive - Daily summary",
        f"{display_name} - {ymd}",
        f"Total sessions: {summary['total_sessions']}, "
        f"total reps: {summary['total_reps']}",
        "",
    ]
    for ex_id, b in summary["exercises"].items():
        lines.append(f"{b['name']}: {b['reps']} reps, "
                     f"good form {b['good_pct']}%, "
                     f"avg min angle "
                     f"{b['avg_angle_min']}"
                     f"{' deg' if b['avg_angle_min'] is not None else ''}")
        for cue, n in b["cues"]:
            lines.append(f"    x{n}: {cue}")
    if opinion:
        lines.append("")
        lines.append("Clinical opinion:")
        lines.append(opinion)
    return "\n".join(lines)


class EmailNotConfigured(RuntimeError):
    """Raised when the SMTP credentials are missing."""


def send_daily_report(user_sub: str, display_name: str,
                      sessions: List[Dict]) -> Dict:
    """Aggregate + email the daily report. Returns a status dict."""
    smtp_host = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
    smtp_user = os.environ.get("EMAIL_ADDRESS", "").strip()
    smtp_pass = os.environ.get("EMAIL_APP_PASSWORD", "").strip()
    recipient = (os.environ.get("REPORT_RECIPIENT", "").strip()
                 or smtp_user)
    if not smtp_user or not smtp_pass or not recipient:
        raise EmailNotConfigured(
            "EMAIL_ADDRESS, EMAIL_APP_PASSWORD or REPORT_RECIPIENT is "
            "not set - the email report is disabled.")

    today = _dt.date.today().isoformat()
    if already_sent_today(user_sub, today):
        return {"ok": True, "sent": False, "reason": "already sent today"}

    summary = _aggregate(sessions)
    opinion = _clinical_opinion(summary)

    msg = EmailMessage()
    msg["Subject"] = (f"PhysioLive daily summary "
                      f"({today}) - "
                      f"{summary['total_reps']} reps")
    msg["From"] = smtp_user
    msg["To"] = recipient
    msg.set_content(_compose_plain(summary, opinion, display_name, today))
    msg.add_alternative(_compose_html(summary, opinion, display_name, today),
                        subtype="html")

    ctx = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ctx)
        smtp.ehlo()
        smtp.login(smtp_user, smtp_pass)
        smtp.send_message(msg)

    _mark_sent(user_sub, today)
    return {
        "ok": True, "sent": True, "date": today,
        "total_reps": summary["total_reps"],
        "used_llm": opinion is not None,
    }
