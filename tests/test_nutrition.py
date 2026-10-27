"""Tests for nutrition.py - protein estimates come from a fixed table, never guessed."""
import pytest

import nutrition as nu


def test_grams_and_units() -> None:
    e = nu.estimate_protein("chicken breast 200g, rice 150g + 2 eggs")
    assert (e.protein_g, e.estimated, e.unknown) == (78.0, True, [])      # 62 + 4 + 12 (4.05 -> 4.0)
    assert [i["food"] for i in e.items] == ["chicken breast", "rice", "egg"]


@pytest.mark.parametrize("text, grams", [
    ("200g paneer", 36.0),
    ("milk 250ml", 8.5),
    ("1 scoop whey", 24.0),
    ("2 scoops of whey", 48.0),
    ("3 rotis and dal 200 grams", 27.0),
    ("egg", 6.0),
])
def test_formats(text: str, grams: float) -> None:
    assert nu.estimate_protein(text).protein_g == grams


def test_explicit_number_is_stored_as_exact() -> None:
    for text in ["burrito bowl 45g protein", "burrito bowl p45"]:
        e = nu.estimate_protein(text)
        assert (e.protein_g, e.estimated) == (45.0, False)


@pytest.mark.parametrize("text", ["pizza", "chicken", "chicken a lot", "rice 1 cup", "2 samosas, dal 200g"])
def test_unknown_food_or_amount_is_not_guessed(text: str) -> None:
    e = nu.estimate_protein(text)
    assert e.protein_g is None and e.unknown
