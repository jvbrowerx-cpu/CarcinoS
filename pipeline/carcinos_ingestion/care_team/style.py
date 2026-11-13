"""Code checks that keep each row descriptive and dose-free.

These enforce "report, don't instruct". A row that fails any check is removed
from what readers see and shown to the editor with the reason.
"""

from __future__ import annotations

import re

# Words that turn a fragment into an instruction when they start it.
IMPERATIVE_VERBS = {
    "give", "get", "check", "monitor", "teach", "educate", "counsel", "start", "stop",
    "hold", "avoid", "ensure", "consider", "obtain", "order", "administer", "assess",
    "screen", "watch", "tell", "advise", "instruct", "remind", "use", "plan", "schedule",
    "arrange", "refer", "discontinue", "continue", "reduce", "increase", "prescribe",
    "premedicate", "warn", "track", "follow", "make", "be", "keep", "report", "expect",
    "anticipate", "document", "notify", "call", "contact", "encourage", "recommend",
    "provide", "offer", "draw", "prepare", "verify", "confirm", "review", "note",
    "look", "limit", "minimize", "correct", "replace", "measure", "evaluate", "perform",
}

# Directive phrases anywhere in the row.
DIRECTIVE_PATTERNS = [
    r"\bshould\b", r"\bmust\b", r"\bneed(?:s)? to\b", r"\bbe sure\b", r"\bmake sure\b",
    r"\byou\b", r"\byour\b", r"\bit is (?:important|essential|recommended) to\b",
    r"\bwe recommend\b", r"\bdon't\b", r"\bdo not\b", r"\bnever\b", r"\balways\b",
    r"\bthis patient\b", r"\bwatch for\b", r"\blook out for\b", r"\binstruct\b",
    r"\bpatients? should\b", r"\bcounsel\b",
]

# Any dosing.
DOSE_PATTERNS = [
    r"\d\s*(?:mg|mcg|µg|g|ml|mL|units?|IU)\b", r"mg\s*/\s*(?:m2|m²|kg)", r"\bAUC\s*\d",
    r"\bdos(?:e|ing) (?:reduction|adjustment|modification|interruption|escalation|delay)s?\b",
    r"\b(?:reduce|lower|adjust|modify|hold|interrupt)(?:d|s)? (?:the )?dose", r"\bdosing\b",
    r"\btitrat", r"\bpremedicat", r"\bloading dose\b",
]


def style_issues(text: str) -> list[str]:
    issues: list[str] = []
    t = (text or "").strip()
    low = t.lower()

    for clause in re.split(r"[;.]\s*", t):
        words = clause.split()
        if not words:
            continue
        first = re.sub(r"[^a-z]", "", words[0].lower())
        if first in IMPERATIVE_VERBS:
            issues.append(f"instructional wording (starts with '{first}')")

    for pat in DIRECTIVE_PATTERNS:
        m = re.search(pat, low)
        if m:
            issues.append(f"directive wording: '{m.group(0)}'")

    for pat in DOSE_PATTERNS:
        m = re.search(pat, t, flags=re.IGNORECASE)
        if m:
            issues.append(f"dosing content not allowed: '{m.group(0)}'")
            break

    return issues
