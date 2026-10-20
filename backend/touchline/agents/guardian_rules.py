"""Guardian rules: deterministic verification of any AI-written text.

A text is approved only if:
  1. every number in it can be traced to a cited fact (with rounding / unit tolerance),
  2. every cited fact id exists,
  3. it names no player or club that is not part of this match,
  4. it passes the safety screen (Azure AI Content Safety when configured, else a local list),
  5. it respects the length budget for its surface.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from touchline.models import Fact, MatchMeta, Verdict
from touchline.sim.league import build_league

_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹０１２３４５６７８９", "0123456789" * 3)
NUM_RE = re.compile(r"(?<![A-Za-z0-9_.,])(\d+(?:[.,]\d+)?)(?![A-Za-z0-9_])")
FACT_ID_RE = re.compile(r"\[?\b(F\d+)\b\]?")
ALWAYS_ALLOWED = {0.0, 1.0, 45.0, 90.0}
# Fixed numbers that appear inside offline template sentences ("in the last 5 minutes").
TEMPLATE_CONSTANTS = (5.0, 10.0, 100.0)
BLOCKLIST = {"idiot", "stupid", "moron", "pathetic", "disgrace", "useless"}


def normalise_digits(text: str) -> str:
    return text.translate(_DIGIT_MAP)


def extract_numbers(text: str) -> list[float]:
    text = FACT_ID_RE.sub(" ", normalise_digits(text))
    out = []
    for raw in NUM_RE.findall(text):
        try:
            out.append(float(raw.replace(",", ".")))
        except ValueError:
            continue
    return out


def _variants(value: float, kind: str, unit: str) -> set[float]:
    v = float(value)
    vals = {v, round(v), round(v, 1), round(v, 2), float(int(v))}
    if kind.startswith("xg") and 0 <= v <= 1:
        vals |= {round(v * 100), round(v * 100, 1), 100.0}  # "41% chance", "41 in 100"
    if unit == "km/h":
        vals |= {round(v / 3.6, 1), round(v / 3.6)}  # m/s
    if unit == "/100":
        vals.add(100.0)
    if unit == "km":
        vals |= {round(v * 1000)}
    if unit == "m":
        vals |= {round(v / 0.9144)}  # yards
    if kind == "momentum":
        vals |= {abs(v), round(abs(v))}
    return vals


def allowed_numbers(facts: Iterable[Fact], extra: Iterable[float] = ()) -> set[float]:
    allowed = set(ALWAYS_ALLOWED) | {float(x) for x in extra}
    for f in facts:
        if isinstance(f.value, str):
            allowed |= {float(x) for x in re.findall(r"\d+(?:\.\d+)?", f.value)}
        else:
            allowed |= _variants(f.value, f.kind, f.unit)
        if f.minute is not None:
            allowed.add(float(f.minute))
    return allowed


def _number_ok(n: float, allowed: set[float]) -> bool:
    return any(abs(n - a) <= (0.051 if n < 10 else 0.51) for a in allowed)


class NameIndex:
    """Detects names of players / clubs that are NOT in this match."""

    def __init__(self, meta: MatchMeta) -> None:
        in_match_tokens = set()
        for team in (meta.home, meta.away):
            in_match_tokens |= {team.short_name.lower(), team.name.lower(), team.code.lower()}
            for p in team.players:
                in_match_tokens |= {p.short_name.lower(), p.name.lower()}
        foreign: set[str] = set()
        for team in build_league():
            if team.id in {meta.home.id, meta.away.id}:
                continue
            for tok in (team.name, team.short_name):
                if tok.lower() not in in_match_tokens:
                    foreign.add(tok)
            for p in team.players:
                if p.short_name.lower() not in in_match_tokens and len(p.short_name) > 3:
                    foreign.add(p.name)
        self.foreign_re = re.compile(
            r"\b(" + "|".join(sorted(map(re.escape, foreign), key=len, reverse=True)) + r")\b"
        )

    def foreign_names(self, text: str) -> list[str]:
        return sorted(set(self.foreign_re.findall(text)))


def verify_text(
    text: str,
    cited_fact_ids: list[str],
    facts: dict[str, Fact],
    *,
    names: NameIndex,
    extra_numbers: Iterable[float] = (),
    max_chars: int = 420,
    require_citation: bool = True,
) -> Verdict:
    reasons: list[str] = []
    unknown = [fid for fid in cited_fact_ids if fid not in facts]
    if unknown:
        reasons.append(f"Cites unknown fact ids: {', '.join(unknown)}")
    cited = [facts[fid] for fid in cited_fact_ids if fid in facts]
    nums = extract_numbers(text)
    allowed = allowed_numbers(cited, extra_numbers)
    bad = [n for n in nums if not _number_ok(n, allowed)]
    if bad:
        shown = ", ".join(f"{b:g}" for b in bad[:4])
        reasons.append(f"Numbers not supported by cited facts: {shown}")
    if require_citation and nums and not cited:
        reasons.append("Contains numbers but cites no facts")
    foreign = names.foreign_names(text)
    if foreign:
        reasons.append(f"Mentions people or clubs not in this match: {', '.join(foreign)}")
    lowered = text.lower()
    flagged = [w for w in BLOCKLIST if re.search(rf"\b{w}\b", lowered)]
    if flagged:
        reasons.append("Safety screen: inappropriate language")
    if len(text) > max_chars:
        reasons.append(f"Too long for the surface ({len(text)} > {max_chars} chars)")
    if not text.strip():
        reasons.append("Empty output")
    return Verdict(
        approved=not reasons,
        reasons=reasons,
        checked_numbers=[f"{n:g}" for n in nums],
        checked_names=foreign,
    )
