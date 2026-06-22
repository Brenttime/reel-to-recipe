"""Tests for OCR cleanup helpers used by reel conversion."""

import os
import sys

# Add project root to path so we can import mcp_server functions directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server import (  # noqa: E402
    _caption_has_recipe_signals,
    _clean_ocr_line,
    _extract_ocr_recipe_fragment,
    _ocr_line_has_recipe_signal,
)


def normalize(raw: str) -> str:
    """Apply the same cleanup/fragment extraction used by video OCR."""
    return _extract_ocr_recipe_fragment(_clean_ocr_line(raw))


def test_instagram_overlay_quantity_cleanup_for_butter_chicken_burritos():
    """Noisy OCR from the DWC6zVtDwH4 reel should preserve key quantities."""
    samples = {
        "i @@800g chicken'breast Aa \\": "800g chicken'breast",
        "@l20g 0%'Greek- yoghurt": "120g 0% Greek yoghurt",
        "rq fan i.5 tsp garam mast Ly? \\": "1.5 tsp garam mas",
        "aN fe ee. 1/2 tsp turmeric Baa J": "1/2 tsp turmeric",
        "az ang 15 tsp salt.“ aus an": "1.5 tsp salt",
        "@if2 tsp garlic & Ginger ae": "2 tsp garlic & Ginger",
        "400g choppped tomatoes": "400g chopped tomatoes",
        "i 1/5 cup water G5": "1/3 cup water",
        "759 cooked rice ea’": "75g cooked rice",
        "ies 40g low fat cheese gare": "40g low fat cheese",
    }

    for raw, expected in samples.items():
        cleaned = normalize(raw)
        assert expected.lower() in cleaned.lower()
        assert _ocr_line_has_recipe_signal(cleaned)


def test_rejects_background_noise_without_recipe_signal():
    cleaned = normalize("ae7, random medium contrast table glare")
    assert not _ocr_line_has_recipe_signal(cleaned)


def test_macro_only_caption_does_not_skip_ocr():
    caption = """📊 Macros (per burrito)
585 Calories
57g Protein
55g Carbs
13g Fat
High Protein Butter Chicken Burritos
Packed with flavor and loaded with protein."""
    assert not _caption_has_recipe_signals(caption)
