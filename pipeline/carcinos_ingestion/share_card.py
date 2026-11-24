"""
Share preview images ("share cards").

When a reader texts a paper to a colleague, the text holds one short link:
    https://carcino-s.com/s/?c=<alert id>
iMessage (and most chat apps) turn that link into a picture card. The picture
is this module's output: a 1200x630 PNG in CarcinoS style (dark green, CS logo,
tier pill, disease site, paper title), stored in the public Supabase Storage
bucket "share-cards" as <alert id>.png.

Called from deliver.py once per alert per delivery run. Entirely non-fatal:
if Pillow, the fonts or the upload fail, the email still goes out and the
share page falls back to a generic CarcinoS preview image.

One-time setup (Supabase SQL editor):
    insert into storage.buckets (id, name, public)
    values ('share-cards', 'share-cards', true)
    on conflict (id) do nothing;
"""

from __future__ import annotations

import html
import io
import os
import re
import sys
from typing import Any, Iterable

BUCKET = "share-cards"
W, H = 1200, 630

_FONT_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")
_SERIF = os.path.join(_FONT_DIR, "LibreBaskerville.ttf")
_SANS = os.path.join(_FONT_DIR, "Inter.ttf")

# CarcinoS invite-page palette
BG = (11, 18, 14)          # #0b120e
STRIPE = (121, 173, 134)   # #79ad86
GREEN = (114, 176, 127)    # #72b07f
PILL_BG = (159, 199, 166)  # #9fc7a6
PILL_DIM = (61, 107, 74)   # #3d6b4a
TEXT = (255, 255, 255)
MUTED = (114, 128, 117)    # #728075
LOGO_BG = (17, 17, 17)
LOGO_BORDER = (46, 56, 48)
RULE = (33, 51, 41)        # #213329

TIER_TEXT = {"A": "PRACTICE IMPACTING", "B": "INCREMENTAL", "C": "HORIZON"}
TIER_SQ = {"A": 3, "B": 2, "C": 1}

_TAGS = re.compile(r"<[^>]+>")


def _plain(s: str) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", s or "")).split())


def _font(path: str, size: int, weight: str = "Regular"):
    from PIL import ImageFont
    f = ImageFont.truetype(path, size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit_title(draw, title: str, max_w: int, max_h: int):
    """Largest serif size (54 → 36) whose wrapped title fits; else truncate."""
    for size in (54, 50, 46, 42, 38, 36):
        f = _font(_SERIF, size)
        lh = int(size * 1.36)
        lines = _wrap(draw, title, f, max_w)
        if len(lines) * lh <= max_h:
            return f, lines, lh
    f = _font(_SERIF, 36)
    lh = int(36 * 1.36)
    lines = _wrap(draw, title, f, max_w)
    keep = max(1, max_h // lh)
    lines = lines[:keep]
    last = lines[-1]
    while last and draw.textlength(last + "…", font=f) > max_w:
        last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
    lines[-1] = last.rstrip(",;:—- ") + "…"
    return f, lines, lh


def _pill(draw, x: int, y: int, text: str, filled: bool, squares: int = 0) -> int:
    f = _font(_SANS, 21, "ExtraBold" if filled else "Bold")
    pad_x, h = 16, 40
    sq, gap = 13, 5
    sq_w = (squares * sq + (squares - 1) * gap + 10) if squares else 0
    # letter-spaced caps
    spacing = 2
    tw = sum(draw.textlength(ch, font=f) for ch in text) + spacing * (len(text) - 1)
    w = int(pad_x * 2 + sq_w + tw)
    if filled:
        draw.rounded_rectangle((x, y, x + w, y + h), radius=6, fill=PILL_BG)
        fg = BG
    else:
        draw.rounded_rectangle((x, y, x + w, y + h), radius=6, outline=PILL_DIM, width=2)
        fg = PILL_BG
    cx = x + pad_x
    for _ in range(squares):
        draw.rectangle((cx, y + (h - sq) // 2, cx + sq, y + (h + sq) // 2), fill=fg)
        cx += sq + gap
    if squares:
        cx += 10 - gap
    for ch in text:
        draw.text((cx, y + h / 2), ch, font=f, fill=fg, anchor="lm")
        cx += draw.textlength(ch, font=f) + spacing
    return x + w


def render_share_card(title: str, tier: str = "A", site_label: str = "",
                      conference: str = "", pills: bool = True) -> bytes:
    """Return a 1200x630 PNG (bytes) for one paper."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 10), fill=STRIPE)

    L = 72
    # Logo mark
    top = 62
    d.rounded_rectangle((L, top, L + 84, top + 84), radius=16, fill=LOGO_BG, outline=LOGO_BORDER, width=2)
    lf = _font(_SERIF, 32, "Bold")
    cw = d.textlength("C", font=lf)
    sw = d.textlength("S", font=lf)
    lx = L + 42 - (cw + sw) / 2
    d.text((lx, top + 43), "C", font=lf, fill=(224, 224, 224), anchor="lm")
    d.text((lx + cw, top + 43), "S", font=lf, fill=GREEN, anchor="lm")
    # Wordmark
    wf = _font(_SERIF, 42, "Bold")
    wx = L + 84 + 26
    d.text((wx, top + 30), "Carcino", font=wf, fill=TEXT, anchor="lm")
    d.text((wx + d.textlength("Carcino", font=wf), top + 30), "S", font=wf, fill=GREEN, anchor="lm")
    sf = _font(_SANS, 20, "SemiBold")
    sub = "SHARED WITH YOU"
    sx = wx
    for ch in sub:
        d.text((sx, top + 70), ch, font=sf, fill=MUTED, anchor="lm")
        sx += d.textlength(ch, font=sf) + 2.4

    # Pills
    py = 196
    if not pills:
        pass
    elif conference:
        nx = _pill(d, L, py, "POTENTIALLY PRACTICE IMPACTING", True, 3)
    else:
        nx = _pill(d, L, py, TIER_TEXT.get(tier, "PRACTICE IMPACTING"), True, TIER_SQ.get(tier, 3))
    if pills and site_label:
        _pill(d, nx + 12, py, site_label.upper(), False)

    # Title
    ty = 270
    max_h = H - ty - 96
    f, lines, lh = _fit_title(d, title or "An oncology paper", W - L * 2, max_h)
    for i, line in enumerate(lines):
        d.text((L, ty + i * lh), line, font=f, fill=TEXT)

    # Footer
    d.line((L, H - 70, W - L, H - 70), fill=RULE, width=2)
    ff = _font(_SANS, 22, "SemiBold")
    d.text((L, H - 38), "carcino-s.com", font=ff, fill=GREEN, anchor="lm")
    tag = "Physician-reviewed oncology updates"
    d.text((W - L, H - 38), tag, font=_font(_SANS, 22), fill=MUTED, anchor="rm")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def ensure_share_cards(sb: Any, alerts: Iterable[Any], done: set, site_labels: dict,
                       dry_run: bool = False) -> None:
    """Render + upload a share card for each alert not yet handled this run.

    `done` is a set shared across the whole delivery run so each card is
    rendered once even though many subscribers get the same alert.
    Never raises.
    """
    for a in alerts:
        aid = str(getattr(a, "id", "") or "")
        if not aid or aid in done:
            continue
        done.add(aid)
        try:
            png = render_share_card(
                _plain(getattr(a, "title", "")),
                getattr(a, "tier", "A") or "A",
                site_labels.get(getattr(a, "disease_site_code", "") or "", ""),
                getattr(a, "conference_source", "") or "",
            )
            if dry_run:
                continue
            sb.storage.from_(BUCKET).upload(
                f"{aid}.png", png,
                {"content-type": "image/png", "upsert": "true", "cache-control": "86400"},
            )
        except Exception as e:  # never block delivery
            print(f"    [WARN] share card for {aid} failed: {e}", file=sys.stderr)
