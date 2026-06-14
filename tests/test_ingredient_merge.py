"""
Unit tests for ingredient_merge.py — the pure-logic ingredient aggregation.

Run with:
    .venv/bin/pytest tests/test_ingredient_merge.py -v
"""

import sys
sys.path.insert(0, 'web')

import pytest
from ingredient_merge import parse_ingredient, merge_ingredients, parse_number, format_number


class TestParseNumber:
    """Number parsing edge cases."""

    def test_integer(self):
        assert parse_number("3") == 3.0

    def test_decimal(self):
        assert parse_number("2.5") == 2.5

    def test_fraction(self):
        assert parse_number("1/2") == 0.5

    def test_mixed_number(self):
        assert parse_number("2 1/2") == 2.5

    def test_unicode_half(self):
        assert parse_number("½") == 0.5

    def test_unicode_mixed(self):
        assert parse_number("2½") == 2.5

    def test_empty(self):
        assert parse_number("") is None

    def test_third(self):
        assert abs(parse_number("1/3") - 0.333) < 0.01


class TestFormatNumber:
    """Number formatting."""

    def test_whole(self):
        assert format_number(4.0) == "4"

    def test_half(self):
        assert format_number(0.5) == "1/2"

    def test_mixed(self):
        assert format_number(2.5) == "2 1/2"

    def test_quarter(self):
        assert format_number(0.25) == "1/4"

    def test_three_quarters(self):
        assert format_number(1.75) == "1 3/4"

    def test_odd_decimal(self):
        # Not a common fraction — stays decimal
        result = format_number(1.3)
        assert "1.3" in result


class TestParseIngredient:
    """Ingredient line parsing."""

    def test_standard(self):
        qty, unit, name, _ = parse_ingredient("2 tbsp olive oil")
        assert qty == 2.0
        assert unit == "tbsp"
        assert name == "olive oil"

    def test_glued_unit(self):
        qty, unit, name, _ = parse_ingredient("800g chicken breast")
        assert qty == 800.0
        assert unit == "g"
        assert name == "chicken breast"

    def test_fraction(self):
        qty, unit, name, _ = parse_ingredient("1/2 cup shredded mozzarella")
        assert qty == 0.5
        assert unit == "cup"
        assert "mozzarella" in name

    def test_mixed_number(self):
        qty, unit, name, _ = parse_ingredient("2 1/2 lb Yukon Gold potatoes")
        assert qty == 2.5
        assert unit == "lb"
        assert "Yukon Gold potatoes" in name

    def test_no_quantity(self):
        qty, unit, name, _ = parse_ingredient("Salt and pepper")
        assert qty is None
        assert unit is None
        assert name == "Salt and pepper"

    def test_unit_alias(self):
        qty, unit, name, _ = parse_ingredient("2 tablespoons olive oil")
        assert unit == "tbsp"

    def test_range(self):
        qty, unit, name, _ = parse_ingredient("1 - 2 tablespoons hot honey")
        assert qty == 2.0  # takes the high end
        assert unit == "tbsp"
        assert "hot honey" in name

    def test_plural_unit(self):
        qty, unit, name, _ = parse_ingredient("3 cups flour")
        assert qty == 3.0
        assert unit == "cup"


class TestMergeIngredients:
    """Ingredient merging / aggregation."""

    def test_exact_duplicates(self):
        items = ["1 tsp garlic powder", "1 tsp garlic powder"]
        merged = merge_ingredients(items)
        assert len(merged) == 1
        assert "2 tsp garlic powder" in merged[0]

    def test_unit_alias_merge(self):
        """'tablespoons' and 'tbsp' should merge."""
        items = ["2 tbsp olive oil", "2 tablespoons olive oil"]
        merged = merge_ingredients(items)
        assert len(merged) == 1
        assert "4 tbsp" in merged[0]

    def test_different_units_no_merge(self):
        """'800g chicken' and '1 lb chicken' should NOT merge (incompatible units)."""
        items = ["800g chicken breast", "1 lb chicken breast"]
        merged = merge_ingredients(items)
        assert len(merged) == 2

    def test_different_names_no_merge(self):
        """'chicken breast' and 'chicken thigh' should NOT merge."""
        items = ["1 lb chicken breast", "1 lb chicken thigh"]
        merged = merge_ingredients(items)
        assert len(merged) == 2

    def test_no_quantity_stays_separate(self):
        """Items without quantities stay as-is."""
        items = ["Salt and pepper", "Salt and pepper"]
        merged = merge_ingredients(items)
        # Both kept since qty is None
        assert len(merged) == 2

    def test_parenthetical_stripped_for_match(self):
        """'olive oil (or avocado oil)' matches 'olive oil'."""
        items = ["2 tbsp olive oil", "2 tbsp olive oil (or avocado oil, divided)"]
        merged = merge_ingredients(items)
        assert len(merged) == 1
        assert "4 tbsp" in merged[0]

    def test_fractions_sum_correctly(self):
        """1/2 + 1/2 = 1."""
        items = ["1/2 cup sugar", "1/2 cup sugar"]
        merged = merge_ingredients(items)
        assert len(merged) == 1
        assert "1 cup sugar" in merged[0]

    def test_mixed_sum(self):
        """1/4 + 3/4 = 1."""
        items = ["1/4 tsp salt", "3/4 tsp salt"]
        merged = merge_ingredients(items)
        assert len(merged) == 1
        assert "1 tsp salt" in merged[0]

    def test_grams_sum(self):
        """500g + 300g = 800g."""
        items = ["500g chicken breast", "300g chicken breast"]
        merged = merge_ingredients(items)
        assert len(merged) == 1
        assert "800" in merged[0]
        assert "chicken breast" in merged[0]

    def test_plural_unit_display(self):
        """Merged quantity >1 should use plural unit form."""
        items = ["1 cup flour", "2 cups flour"]
        merged = merge_ingredients(items)
        assert len(merged) == 1
        assert "3 cups flour" in merged[0]

    def test_preserves_order(self):
        """First occurrence determines position in output."""
        items = ["1 tsp salt", "2 cups flour", "1 tsp salt"]
        merged = merge_ingredients(items)
        assert merged[0] == "2 tsp salt"
        assert merged[1] == "2 cups flour"

    def test_empty_list(self):
        assert merge_ingredients([]) == []

    def test_single_item(self):
        items = ["1 cup milk"]
        assert merge_ingredients(items) == ["1 cup milk"]

    def test_real_world_scenario(self):
        """Real OnlyPans data: multiple recipes sharing garlic, olive oil."""
        items = [
            "1 tsp garlic powder",
            "2 tbsp olive oil",
            "1 tsp garlic powder",
            "2 tablespoons olive oil (or avocado oil, divided)",
            "1/2 tsp cayenne",
            "800g chicken breast",
        ]
        merged = merge_ingredients(items)
        assert len(merged) == 4
        # garlic merged
        garlic = [m for m in merged if "garlic" in m][0]
        assert "2 tsp" in garlic
        # olive oil merged
        oil = [m for m in merged if "olive oil" in m][0]
        assert "4 tbsp" in oil
