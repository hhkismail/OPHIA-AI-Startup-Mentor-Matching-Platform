# ui.py
# Small HTML building blocks for the dashboard (avatars, chips, score badges,
# grade meters, mentor cards). Two rules:
#   1. Every value is escaped here, so callers can pass raw or API text.
#   2. Every element sets BOTH its text and background colour, so nothing can
#      become invisible if the theme flips to dark.

import hashlib
import html

ACCENT = "#0F766E"

CSS = """
<style>
  .block-container { padding-top: 1.2rem; max-width: 1200px; }
  .o-bar { display:flex; align-items:center; gap:.7rem; padding:.2rem 0 .6rem; }
  .o-logo { width:34px; height:34px; border-radius:9px; background:#0F766E; color:#FFFFFF;
            display:flex; align-items:center; justify-content:center; font-weight:700; font-size:1.05rem; }
  .o-name { font-weight:700; font-size:1.25rem; color:#1F2328; letter-spacing:.02em; }
  .o-tag  { color:#57606A; font-size:.85rem; }

  .o-avatar { width:42px; height:42px; border-radius:50%; flex:0 0 42px; display:flex;
              align-items:center; justify-content:center; font-weight:600; font-size:.95rem; }
  .o-person { display:flex; gap:.7rem; align-items:center; min-width:0; }
  .o-person .t { min-width:0; }
  .o-person .n { font-weight:600; color:#1F2328; line-height:1.25; }
  .o-person .s { color:#57606A; font-size:.82rem; line-height:1.3; }

  .o-chips { display:flex; flex-wrap:wrap; gap:.3rem; margin:.45rem 0 .1rem; }
  .o-chip { background:#EEF2F1; color:#24453F; border-radius:999px; padding:.12rem .55rem;
            font-size:.75rem; white-space:nowrap; }

  .o-score { border-radius:10px; padding:.35rem .6rem; text-align:center; min-width:64px; }
  .o-score .v { font-size:1.45rem; font-weight:700; line-height:1.1; font-variant-numeric:tabular-nums; }
  .o-score .l { font-size:.68rem; text-transform:uppercase; letter-spacing:.06em; }
  .o-strong   { background:#E6F4F1; color:#0B5C55; }
  .o-possible { background:#FDF3E1; color:#8A5A00; }
  .o-weak     { background:#F1F2F4; color:#57606A; }

  .o-grades { display:flex; gap:1.1rem; flex-wrap:wrap; color:#57606A; font-size:.8rem; margin-top:.25rem; }
  .o-dots { letter-spacing:.08em; color:#0F766E; }
  .o-dots .off { color:#C9D1D9; }

  .o-card { background:#FFFFFF; color:#1F2328; border:1px solid #E1E4E8; border-radius:12px;
            padding:.9rem 1rem; height:100%; }
  .o-card .bio { color:#424A53; font-size:.85rem; line-height:1.45; margin:.55rem 0 .2rem;
                 display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }
  .o-foot { display:flex; justify-content:space-between; align-items:center; margin-top:.6rem;
            color:#57606A; font-size:.78rem; }
  .o-status { border-radius:999px; padding:.1rem .5rem; font-size:.72rem; font-weight:600; }
  .o-available { background:#E6F4F1; color:#0B5C55; }
  .o-busy      { background:#F1F2F4; color:#57606A; }
</style>
"""

# Muted avatar colours (background, text), picked by name so they're stable
_AVATAR_COLOURS = [("#E6F4F1", "#0B5C55"), ("#E8EEF9", "#2B4C8C"), ("#FDF3E1", "#8A5A00"),
                   ("#F3ECF8", "#6B3E8E"), ("#FBEAEA", "#9A2E2E"), ("#EEF2F1", "#24453F")]


def esc(text) -> str:
    """Escape for HTML. API text arrives already escaped, so unescape first to avoid '&amp;amp;'."""
    return html.escape(html.unescape(str(text or "")))


def initials(name: str) -> str:
    words = [w for w in html.unescape(name).replace(".", " ").split() if w[:1].isalpha()]
    skip = {"dr", "mr", "mrs", "ms", "prof"}
    words = [w for w in words if w.lower() not in skip] or words
    return "".join(w[0].upper() for w in words[:2]) or "?"


def avatar(name: str) -> str:
    bg, fg = _AVATAR_COLOURS[int(hashlib.md5(name.encode()).hexdigest(), 16) % len(_AVATAR_COLOURS)]
    return f'<div class="o-avatar" style="background:{bg};color:{fg}">{esc(initials(name))}</div>'


def person(name: str, subtitle: str = "") -> str:
    return (f'<div class="o-person">{avatar(name)}<div class="t"><div class="n">{esc(name)}</div>'
            f'<div class="s">{esc(subtitle)}</div></div></div>')


def chips(items) -> str:
    return '<div class="o-chips">' + "".join(f'<span class="o-chip">{esc(i)}</span>' for i in items if i) + "</div>"


def score_band(score: int) -> tuple[str, str]:
    """Same thresholds as the human-agreement evaluation: <50 weak, 50-79 possible, 80+ strong."""
    if score >= 80:
        return "o-strong", "Strong"
    return ("o-possible", "Possible") if score >= 50 else ("o-weak", "Weak")


def score_badge(score: int) -> str:
    cls, label = score_band(score)
    return f'<div class="o-score {cls}"><div class="v">{int(score)}</div><div class="l">{label}</div></div>'


def dots(value: int, out_of: int = 5) -> str:
    value = max(0, min(out_of, int(value)))
    return f'<span class="o-dots">{"●" * value}<span class="off">{"●" * (out_of - value)}</span></span>'


def grade_meters(grades: dict | None) -> str:
    if not grades:
        return '<div class="o-grades">AI review unavailable: score from similarity only</div>'
    parts = [(label, grades[key]) for label, key in
             (("Domain", "domain_fit"), ("Need", "need_fit"), ("Market", "market_fit"))]
    return '<div class="o-grades">' + "".join(f"<span>{label} {dots(v)}</span>" for label, v in parts) + "</div>"


def mentor_card(m: dict) -> str:
    available = m.get("status", "Available") == "Available"
    status = (f'<span class="o-status {"o-available" if available else "o-busy"}">'
              f'{"Available" if available else esc(m.get("status"))}</span>')
    where = " · ".join(filter(None, [esc(m.get("country")), f'{int(m.get("availability_hours", 0))} h / month']))
    return (f'<div class="o-card">{person(m["name"], m.get("title", ""))}'
            f'<div class="bio">{esc(m.get("bio"))}</div>{chips(m.get("expertise", [])[:5])}'
            f'<div class="o-foot"><span>{where}</span>{status}</div></div>')
