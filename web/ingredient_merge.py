"""
Ingredient aggregation — merge duplicate grocery items by parsing
quantity + unit + name and summing compatible quantities.

Rules:
- "1 tsp garlic powder" + "1 tsp garlic powder" → "2 tsp garlic powder"
- "1 lb chicken" + "3 lbs chicken" → "4 lb chicken"
- "2 tbsp olive oil" + "2 tablespoons olive oil" → "4 tbsp olive oil"
- Items with no quantity or incompatible units stay separate
- Parenthetical modifiers are stripped for matching but preserved in output

No LLM calls — pure regex + lookup table.
"""

import re
from fractions import Fraction
from collections import defaultdict


# ─── Unit normalization ───────────────────────────────────────────────────────

UNIT_ALIASES = {
    # Volume
    'tsp': 'tsp', 'teaspoon': 'tsp', 'teaspoons': 'tsp',
    'tbsp': 'tbsp', 'tablespoon': 'tbsp', 'tablespoons': 'tbsp',
    'cup': 'cup', 'cups': 'cup', 'c': 'cup',
    'ml': 'ml', 'milliliter': 'ml', 'milliliters': 'ml', 'millilitre': 'ml', 'millilitres': 'ml',
    'l': 'l', 'liter': 'l', 'liters': 'l', 'litre': 'l', 'litres': 'l',
    'fl oz': 'fl oz', 'fluid ounce': 'fl oz', 'fluid ounces': 'fl oz',
    'gallon': 'gallon', 'gallons': 'gallon', 'gal': 'gallon',
    'quart': 'quart', 'quarts': 'quart', 'qt': 'quart',
    'pint': 'pint', 'pints': 'pint', 'pt': 'pint',
    # Weight
    'g': 'g', 'gram': 'g', 'grams': 'g', 'gm': 'g',
    'kg': 'kg', 'kilogram': 'kg', 'kilograms': 'kg', 'kilo': 'kg', 'kilos': 'kg',
    'oz': 'oz', 'ounce': 'oz', 'ounces': 'oz',
    'lb': 'lb', 'lbs': 'lb', 'pound': 'lb', 'pounds': 'lb',
    # Count
    'can': 'can', 'cans': 'can',
    'clove': 'clove', 'cloves': 'clove',
    'slice': 'slice', 'slices': 'slice',
    'piece': 'piece', 'pieces': 'piece',
    'bunch': 'bunch', 'bunches': 'bunch',
    'sprig': 'sprig', 'sprigs': 'sprig',
    'head': 'head', 'heads': 'head',
    'stalk': 'stalk', 'stalks': 'stalk',
    'stick': 'stick', 'sticks': 'stick',
    'packet': 'packet', 'packets': 'packet', 'pack': 'packet', 'packs': 'packet',
    'bag': 'bag', 'bags': 'bag',
    'jar': 'jar', 'jars': 'jar',
    'bottle': 'bottle', 'bottles': 'bottle',
    'pinch': 'pinch', 'pinches': 'pinch',
    'dash': 'dash', 'dashes': 'dash',
    'handful': 'handful', 'handfuls': 'handful',
    'large': 'large', 'medium': 'medium', 'small': 'small',
}

# Units that can be displayed as plural
UNIT_PLURALS = {
    'tsp': 'tsp', 'tbsp': 'tbsp', 'cup': 'cups', 'ml': 'ml', 'l': 'l',
    'fl oz': 'fl oz', 'gallon': 'gallons', 'quart': 'quarts', 'pint': 'pints',
    'g': 'g', 'kg': 'kg', 'oz': 'oz', 'lb': 'lbs',
    'can': 'cans', 'clove': 'cloves', 'slice': 'slices', 'piece': 'pieces',
    'bunch': 'bunches', 'sprig': 'sprigs', 'head': 'heads', 'stalk': 'stalks',
    'stick': 'sticks', 'packet': 'packets', 'bag': 'bags', 'jar': 'jars',
    'bottle': 'bottles', 'pinch': 'pinches', 'dash': 'dashes',
    'handful': 'handfuls', 'large': 'large', 'medium': 'medium', 'small': 'small',
}


# ─── Number parsing ──────────────────────────────────────────────────────────

# Unicode fraction mapping
UNICODE_FRACTIONS = {
    '½': '1/2', '⅓': '1/3', '⅔': '2/3', '¼': '1/4', '¾': '3/4',
    '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5',
    '⅙': '1/6', '⅚': '5/6', '⅛': '1/8', '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
}

# Regex for numbers: "2 1/2", "1/4", "2.5", "2½", plain "3"
NUMBER_RE = re.compile(
    r'(\d+\s+\d+/\d+)'   # mixed: "2 1/2"
    r'|(\d+/\d+)'         # fraction: "1/4"
    r'|(\d+\.?\d*)'       # decimal/integer: "2.5" or "3"
)


def parse_number(s: str) -> float | None:
    """Parse a number string (fraction, mixed, decimal) to float."""
    s = s.strip()
    if not s:
        return None

    # Replace unicode fractions
    for uf, frac in UNICODE_FRACTIONS.items():
        if uf in s:
            # "2½" → "2 1/2"
            s = s.replace(uf, f' {frac}').strip()

    # Mixed number: "2 1/2"
    m = re.match(r'^(\d+)\s+(\d+/\d+)$', s)
    if m:
        return int(m.group(1)) + float(Fraction(m.group(2)))

    # Plain fraction: "1/4"
    m = re.match(r'^(\d+/\d+)$', s)
    if m:
        return float(Fraction(m.group(1)))

    # Decimal or integer
    m = re.match(r'^(\d+\.?\d*)$', s)
    if m:
        return float(m.group(1))

    return None


def format_number(n: float) -> str:
    """Format a float as a clean string (prefer fractions for common values)."""
    if n == int(n):
        return str(int(n))

    # Common fractions
    common = {
        0.25: '1/4', 0.333: '1/3', 0.5: '1/2', 0.667: '2/3', 0.75: '3/4',
        0.125: '1/8', 0.375: '3/8', 0.625: '5/8', 0.875: '7/8',
    }

    # Check if it's a whole + fraction
    whole = int(n)
    frac_part = n - whole

    for val, rep in common.items():
        if abs(frac_part - val) < 0.01:
            if whole:
                return f'{whole} {rep}'
            return rep

    # Fall back to rounded decimal
    if n == round(n, 1):
        return f'{n:.1f}'.rstrip('0').rstrip('.')
    return f'{n:.2f}'.rstrip('0').rstrip('.')


# ─── Ingredient parsing ───────────────────────────────────────────────────────

# Pattern: optional quantity, optional unit, then the ingredient name
# Examples:
#   "2 tbsp olive oil" → qty=2, unit=tbsp, name="olive oil"
#   "1/2 cup shredded mozzarella (optional)" → qty=0.5, unit=cup, name="shredded mozzarella"
#   "Salt and pepper" → qty=None, unit=None, name="salt and pepper"
#   "800g chicken breast" → qty=800, unit=g, name="chicken breast"

# Build unit regex from aliases (sorted longest first to avoid partial matches)
_all_units = sorted(set(UNIT_ALIASES.keys()), key=len, reverse=True)
_unit_pattern = '|'.join(re.escape(u) for u in _all_units)

# Quantity: handles "2 1/2", "1/4", "2.5", "2½", with optional range "1 - 2"
QTY_RE = r'(\d+\s+\d+/\d+|\d+/\d+|\d+\.?\d*)'
RANGE_QTY_RE = rf'{QTY_RE}(?:\s*[-–]\s*{QTY_RE})?'

# Full ingredient line pattern
INGREDIENT_RE = re.compile(
    rf'^\s*{RANGE_QTY_RE}'              # quantity (with optional range)
    rf'\s*({_unit_pattern})?\b\.?'       # optional unit
    rf'\s*(.*)',                         # rest = ingredient name
    re.IGNORECASE
)

# Pattern for "800g chicken" (number glued to unit, no space)
GLUED_UNIT_RE = re.compile(
    rf'^\s*{QTY_RE}\s*({_unit_pattern})\b\.?\s*(.*)',
    re.IGNORECASE
)


def _strip_parentheticals(name: str) -> str:
    """Remove parenthetical modifiers for matching purposes."""
    # "(optional)", "(about 2 cups)", "(or avocado oil, divided)"
    return re.sub(r'\s*\([^)]*\)\s*', ' ', name).strip()


def _normalize_name(name: str) -> str:
    """Normalize ingredient name for grouping."""
    name = _strip_parentheticals(name)
    # Remove prep instructions after comma: "onion, diced" → "onion"
    name = re.split(r',\s*', name)[0]
    # Lowercase, strip extra spaces
    name = re.sub(r'\s+', ' ', name.lower().strip())
    # Remove trailing period
    name = name.rstrip('.')
    return name


def parse_ingredient(line: str) -> tuple:
    """
    Parse an ingredient line into (quantity: float|None, unit: str|None, name: str, original: str).

    Returns the parsed components and preserves the original line.
    """
    original = line.strip()
    if not original:
        return (None, None, '', original)

    # Replace unicode fractions in the line
    working = original
    for uf, frac in UNICODE_FRACTIONS.items():
        working = working.replace(uf, f' {frac}')

    # Try glued pattern first: "800g chicken breast"
    m = GLUED_UNIT_RE.match(working)
    if m:
        qty_str = m.group(1)
        unit_str = m.group(2)
        name = m.group(3).strip()
        qty = parse_number(qty_str)
        unit = UNIT_ALIASES.get(unit_str.lower().rstrip('.'))
        return (qty, unit, name, original)

    # Try standard pattern
    m = INGREDIENT_RE.match(working)
    if m:
        qty_str = m.group(1) or ''
        range_high = m.group(2)  # if range like "1-2", take the high end
        unit_str = m.group(3) or ''
        name = m.group(4).strip()

        qty = None
        if qty_str:
            if range_high:
                # For ranges like "1 - 2 tablespoons", use the high end
                qty = parse_number(range_high)
            else:
                qty = parse_number(qty_str)

        unit = UNIT_ALIASES.get(unit_str.lower().rstrip('.')) if unit_str else None

        # If we got a quantity but no unit and the name starts with what looks like a unit
        # handle edge case: "1 (1 oz) packet ranch seasoning"
        if qty and not unit and name:
            # Check for "(X unit)" pattern at start
            paren_m = re.match(r'\([\d./\s]+\s*(' + _unit_pattern + r')\)\s*(.*)', name, re.IGNORECASE)
            if paren_m:
                # Use the parenthetical quantity+unit instead
                name = paren_m.group(2).strip()
                # Keep original qty (the outer number is count, e.g., "1 packet")

        return (qty, unit, name if name else original, original)

    # No quantity found — treat entire line as name
    return (None, None, original, original)


def merge_ingredients(ingredients: list[str]) -> list[str]:
    """
    Merge a list of ingredient strings, combining items with the same
    normalized name and compatible units.

    Returns a list of merged ingredient strings.
    """
    # Group by normalized name + unit
    groups = defaultdict(list)  # key: (normalized_name, unit) → list of (qty, original)

    parsed = []
    for line in ingredients:
        qty, unit, name, original = parse_ingredient(line)
        parsed.append((qty, unit, name, original))
        norm_name = _normalize_name(name)
        groups[(norm_name, unit)].append((qty, name, original))

    # Merge groups
    result = []
    seen_keys = set()

    for line_idx, (qty, unit, name, original) in enumerate(parsed):
        norm_name = _normalize_name(name)
        key = (norm_name, unit)

        if key in seen_keys:
            continue
        seen_keys.add(key)

        group = groups[key]

        if len(group) == 1:
            # No duplicates — keep original
            result.append(original)
        elif all(g[0] is not None for g in group):
            # All have quantities — sum them
            total = sum(g[0] for g in group)

            # Use the longest original name as the display name (most descriptive)
            best_name = max((g[1] for g in group), key=len)

            # Format the merged line
            qty_str = format_number(total)
            if unit:
                unit_display = UNIT_PLURALS.get(unit, unit) if total > 1 else unit
                result.append(f'{qty_str} {unit_display} {best_name}')
            else:
                result.append(f'{qty_str} {best_name}')
        else:
            # Mixed (some have quantities, some don't) — keep all originals
            for _, _, orig in group:
                result.append(orig)

    return result
