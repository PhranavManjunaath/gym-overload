"""
Parser - turns a workout message like "bench 60x10,10,9 @8" into structured data.

Plain Python with regexes, no LLM: what you typed is exactly what gets logged.
Anything it can't read raises ParseError instead of guessing.

Formats (one exercise per line, or separate with ";"):
    bench 60x10,10,9            one weight, reps per set
    bench 60kg x 10, 10, 9      spaces and "kg" are fine
    bench 60x10 62.5x8,7        different weights: WEIGHTxREPS groups
    bench 60x10@8,10@8.5,9@9    RPE per set (no space before @)
    bench 60x10,10,9 @8         RPE for every set on the line (space before @)
    squat 100x5,5,5 deload      mark a deload session
    squat 100x5,5,5 yesterday   date: today (default), yesterday, or 2026-10-26
Weights are kg only; use a dot for decimals (62.5, not 62,5).
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import List, Optional

import progression_engine as pe

HELP = (
    "Log one exercise per line, like:\n"
    "  bench 60x10,10,9\n"
    "  bench 60x10,10,9 @8   (RPE for all sets)\n"
    "  bench 60x10 62.5x8,7  (different weights)\n"
    "  squat 100x5,5,5 deload yesterday\n"
    "Weights in kg, decimals with a dot (62.5)."
)

_NUM = r"\d+(?:\.\d+)?"
_REP = rf"\d+(?:@{_NUM})?"
_GROUP_RE = re.compile(rf"^({_NUM})x({_REP}(?:,{_REP})*)$")   # 60x10,10@8,9
_LINE_RPE_RE = re.compile(rf"^@({_NUM})$")                       # @8
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")                     # 2026-10-26
_LBS_RE = re.compile(r"\d\s*(?:lb|lbs|pounds?)\b", re.IGNORECASE)


class ParseError(ValueError):
    """The message couldn't be read. The text says what was wrong."""


@dataclass
class ParsedEntry:
    exercise: str               # lowercased, single spaces - db.py matches it to an exercise
    date: dt.date
    sets: List[pe.SetLog]
    is_deload: bool = False


def parse_message(text: str, today: Optional[dt.date] = None) -> List[ParsedEntry]:
    """Parse a whole message: one entry per non-empty line (or ';'-separated part)."""
    today = today or dt.date.today()
    entries = [parse_line(part.strip(), today) for part in re.split(r"[\n;]", text) if part.strip()]
    if not entries:
        raise ParseError("Empty message.\n" + HELP)
    return entries


def _normalize(line: str) -> str:
    s = line.lower()
    s = re.sub(r"(\d)\s*kgs?\b", r"\1", s)              # 60kg / 60 kg -> 60
    s = re.sub(r"(\d)\s*[x×*]\s*(?=\d)", r"\1x", s)     # 60 x 10 / 60×10 / 60*10 -> 60x10
    s = re.sub(r"(?<=\d)\s*,\s*(?=\d)", ",", s)          # 10, 10, 9 -> 10,10,9
    s = re.sub(r"@\s+(?=\d)", "@", s)                    # @ 8 -> @8 (keeps the space before @)
    return s


def parse_line(line: str, today: dt.date) -> ParsedEntry:
    """Parse one exercise, e.g. 'bench 60x10,10,9 @8'."""
    if _LBS_RE.search(line):
        raise ParseError(f"'{line}': please log weights in kg.")

    name_parts: List[str] = []
    groups: List[re.Match[str]] = []
    line_rpe: Optional[float] = None
    date: Optional[dt.date] = None
    is_deload = False

    for tok in _normalize(line).split():
        if tok == "deload":
            is_deload = True
        elif tok in ("today", "yesterday") or _DATE_RE.match(tok):
            if date is not None:
                raise ParseError(f"'{line}': more than one date.")
            date = _parse_date(tok, today, line)
        elif m := _GROUP_RE.match(tok):
            groups.append(m)
        elif m := _LINE_RPE_RE.match(tok):
            if line_rpe is not None:
                raise ParseError(f"'{line}': more than one line RPE (@...).")
            line_rpe = float(m.group(1))
        elif not groups and not tok[0].isdigit() and not tok.startswith("@"):
            name_parts.append(tok.strip(":-"))
        else:
            raise ParseError(f"'{line}': couldn't read '{tok}'.\n" + HELP)

    name = " ".join(p for p in name_parts if p)
    if not re.search(r"[a-z]", name):
        raise ParseError(f"'{line}': missing exercise name.\n" + HELP)
    if not groups:
        raise ParseError(f"'{line}': no sets found.\n" + HELP)

    sets: List[pe.SetLog] = []
    for g in groups:
        weight = float(g.group(1))
        for rep in g.group(2).split(","):
            reps_str, _, rpe_str = rep.partition("@")
            rpe = float(rpe_str) if rpe_str else line_rpe
            sets.append(pe.SetLog(weight, int(reps_str), rpe))

    return ParsedEntry(name, date or today, sets, is_deload)


def _parse_date(tok: str, today: dt.date, line: str) -> dt.date:
    if tok == "today":
        return today
    if tok == "yesterday":
        return today - dt.timedelta(days=1)
    try:
        d = dt.date.fromisoformat(tok)
    except ValueError:
        raise ParseError(f"'{line}': '{tok}' isn't a real date.") from None
    if d > today:
        raise ParseError(f"'{line}': {tok} is in the future.")
    return d
