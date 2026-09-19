"""End-of-session summary.

Computes a small set of statistics from the session log and, when the
`reportlab` dependency is available, exports a one-page PDF the user can
share with a physiotherapist.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional


def summarise(session_summary: dict) -> Dict:
    reps = session_summary.get("reps") or []
    if not reps:
        return {
            "rep_count": 0,
            "good_count": 0,
            "avg_primary_min": None,
            "avg_torso_max": None,
        }
    good = sum(1 for r in reps if r.get("level") == "good")
    pmins = [r.get("primary_min") for r in reps
             if r.get("primary_min") is not None]
    tmax = [r.get("torso_max_deg") for r in reps
            if r.get("torso_max_deg") is not None]
    return {
        "rep_count": len(reps),
        "good_count": good,
        "avg_primary_min": (sum(pmins) / len(pmins)) if pmins else None,
        "avg_torso_max": (sum(tmax) / len(tmax)) if tmax else None,
    }


def export_pdf(session_summary: dict, out_path: Path) -> Optional[Path]:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import cm
    except Exception as e:
        print(f"progress: reportlab unavailable ({e}); PDF skipped")
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stats = summarise(session_summary)
    reps = session_summary.get("reps") or []
    c = canvas.Canvas(str(out_path), pagesize=A4)
    w, h = A4
    y = h - 2 * cm
    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, y, "PhysioLive session summary")
    y -= 0.9 * cm
    c.setFont("Helvetica", 11)
    c.drawString(2 * cm, y, f"Exercise: {session_summary.get('exercise', '-')}")
    y -= 0.6 * cm
    c.drawString(2 * cm, y,
                 f"Started at: {session_summary.get('started_at', '-')}")
    y -= 0.6 * cm
    c.drawString(2 * cm, y,
                 f"Reps: {stats['rep_count']}   Good: {stats['good_count']}")
    y -= 0.6 * cm
    if stats["avg_primary_min"] is not None:
        c.drawString(2 * cm, y,
                     f"Avg primary min angle: "
                     f"{stats['avg_primary_min']:.1f} degrees")
        y -= 0.6 * cm
    if stats["avg_torso_max"] is not None:
        c.drawString(2 * cm, y,
                     f"Avg peak torso lean: "
                     f"{stats['avg_torso_max']:.1f} degrees")
        y -= 0.6 * cm

    y -= 0.4 * cm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2 * cm, y, "Rep detail")
    y -= 0.5 * cm
    c.setFont("Helvetica", 10)
    for r in reps:
        if y < 3 * cm:
            c.showPage()
            y = h - 2 * cm
            c.setFont("Helvetica", 10)
        line = (f"#{r.get('rep_index', '?')}  "
                f"{r.get('level', '-'):>5}  "
                f"primary min "
                f"{_num(r.get('primary_min'))}  "
                f"torso peak {_num(r.get('torso_max_deg'))}  "
                f"{r.get('text', '')[:70]}")
        c.drawString(2 * cm, y, line)
        y -= 0.42 * cm
    c.showPage()
    c.save()
    return out_path


def _num(v) -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v):.0f}"
    except Exception:
        return "-"
