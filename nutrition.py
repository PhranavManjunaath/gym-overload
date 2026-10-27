"""
Nutrition - estimates protein from a meal description with a fixed food table.

Plain Python, never the LLM. Results are labelled "estimated" and the user can
correct them. If any food or amount isn't recognised, the estimate is None and
the user is asked for the number - no guessing. Tracking only: no calorie advice.

Formats (items separated by "," "+" or " and "):
    chicken breast 200g, rice 150g     grams for per-100 g foods
    2 eggs + 1 scoop whey               counts for per-unit foods
    milk 250ml                          ml for drinks
    "... 35g protein" or "p35"          your own number - stored as exact, not estimated
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Approximate protein, grams. Rounded reference values (cooked unless noted).
PER_100G: Dict[str, float] = {
    "chicken breast": 31, "chicken": 27, "fish": 22, "tuna": 26, "salmon": 22, "prawns": 24,
    "mutton": 25, "beef": 26, "paneer": 18, "tofu": 8, "soya chunks": 52,        # soya: dry weight
    "dal": 9, "rajma": 8.7, "chana": 8.9, "chickpeas": 8.9, "rice": 2.7, "oats": 13,  # oats: dry
    "curd": 3.5, "yogurt": 3.5, "greek yogurt": 10, "peanut butter": 25, "peanuts": 26,
    "almonds": 21, "potato": 2, "pasta": 5.8, "cheese": 25,
}
PER_100ML: Dict[str, float] = {"milk": 3.4, "soy milk": 3.3}
PER_UNIT: Dict[str, float] = {
    "egg": 6, "egg white": 3.6, "scoop whey": 24, "whey": 24, "roti": 3, "chapati": 3,
    "bread": 3, "banana": 1.3,
}
_PLURALS = {"eggs": "egg", "egg whites": "egg white", "rotis": "roti", "chapatis": "chapati",
            "bananas": "banana", "scoops whey": "scoop whey", "scoop of whey": "scoop whey",
            "scoops of whey": "scoop whey", "slices bread": "bread", "bread slices": "bread",
            "slice bread": "bread", "bread slice": "bread"}

_EXPLICIT = re.compile(r"(?:\b(\d+(?:\.\d+)?)\s*g\s*protein\b|\bp\s*(\d+(?:\.\d+)?)\b)", re.I)
_GRAMS = re.compile(r"(\d+(?:\.\d+)?)\s*(g|gm|gms|grams?)\b", re.I)
_ML = re.compile(r"(\d+(?:\.\d+)?)\s*(ml)\b", re.I)
_COUNT = re.compile(r"^(\d+(?:\.\d+)?)\s+(.+)$")


@dataclass
class ProteinEstimate:
    protein_g: Optional[float]                 # None = couldn't estimate; ask the user
    estimated: bool                            # False when the user wrote the number
    items: List[Dict[str, object]] = field(default_factory=list)   # what each food contributed
    unknown: List[str] = field(default_factory=list)               # items we couldn't read


def _food(name: str) -> str:
    name = " ".join(name.lower().replace("-", " ").split())
    return _PLURALS.get(name, name)


def _item(text: str) -> Tuple[Optional[Dict[str, object]], Optional[str]]:
    """One item -> ({food, amount, protein_g}, None) or (None, the item as unreadable)."""
    raw = text.strip()
    if m := _GRAMS.search(raw):
        food = _food(_GRAMS.sub("", raw))
        if food in PER_100G:
            g = float(m.group(1))
            return {"food": food, "amount": f"{g:g} g", "protein_g": round(PER_100G[food] * g / 100, 1)}, None
    elif m := _ML.search(raw):
        food = _food(_ML.sub("", raw))
        if food in PER_100ML:
            ml = float(m.group(1))
            return {"food": food, "amount": f"{ml:g} ml", "protein_g": round(PER_100ML[food] * ml / 100, 1)}, None
    else:
        m = _COUNT.match(raw)
        count, food = (float(m.group(1)), _food(m.group(2))) if m else (1.0, _food(raw))
        if food in PER_UNIT:
            return {"food": food, "amount": f"{count:g}", "protein_g": round(PER_UNIT[food] * count, 1)}, None
    return None, raw


def estimate_protein(text: str) -> ProteinEstimate:
    if m := _EXPLICIT.search(text):
        return ProteinEstimate(float(m.group(1) or m.group(2)), estimated=False)
    parts = [p for p in re.split(r",|\+|\band\b|\bwith\b", text, flags=re.I) if p.strip()]
    items, unknown = [], []
    for p in parts:
        item, bad = _item(p)
        if item:
            items.append(item)
        else:
            unknown.append(bad)
    if unknown or not items:
        return ProteinEstimate(None, estimated=True, items=items, unknown=unknown or [text.strip()])
    return ProteinEstimate(round(sum(float(i["protein_g"]) for i in items), 1), estimated=True, items=items)
