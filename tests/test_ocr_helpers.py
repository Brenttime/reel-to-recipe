"""Tests for OCR cleanup helpers used by reel conversion."""

import os
import sys

# Add project root to path so we can import mcp_server functions directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server import (  # noqa: E402
    _ocr_available_engines,
    _caption_has_recipe_signals,
    _clean_ocr_line,
    _extract_measured_ingredient_evidence,
    _extract_ocr_recipe_fragment,
    _extract_unmeasured_ingredient_evidence,
    _ocr_image_variants,
    _ocr_line_has_recipe_signal,
    _ocr_text_looks_like_book_page,
    _preserve_ingredient_evidence,
    _should_use_slideshow_ocr,
    _slideshow_ocr_has_recipe_signal,
    _preserve_measured_ingredient_evidence,
    _select_ocr_video_frames,
)


def normalize(raw: str) -> str:
    """Apply the same cleanup/fragment extraction used by video OCR."""
    return _extract_ocr_recipe_fragment(_clean_ocr_line(raw))


def compact(text: str) -> str:
    return " ".join(text.lower().split())


def test_ocr_extracts_generic_quantity_ingredient_fragments():
    samples = {
        "i @@800g chicken'breast Aa \\": "800 g chicken breast",
        "@l20g 0%'Greek- yoghurt": "120 g 0% Greek yoghurt",
        "rq fan i.5 tsp garam mast Ly? \\": "1.5 tsp garam",
        "tsp cumin": "1 tsp cumin",
        "5 tsp garam masaia": "1.5 tsp garam",
        "2 tsp turmeric": "1/2 tsp turmeric",
        "aN fe ee. 1/2 tsp turmeric Baa J": "1/2 tsp turmeric",
        "az ang 15 tsp salt.“ aus an": "15 tsp salt",
        "\\, ie @ 5 tsp salt re “a": "1.5 tsp salt",
        "¢ -LStsp salt” Ps": "1.5 tsp salt",
        "@if2 tsp garlic & Ginger ae": "2 tsp garlic & Ginger",
        "400g choppped tomatoes": "400 g chopped tomatoes",
        "60g light creum cheese": "60 g light cream cheese",
        "i 1/5 cup water G5": "1/3 cup water",
        "+) 830g tomato pastes 120’": "30 g tomato paste",
        "4 830g tomato pastes. sie": "30 g tomato paste",
        "759 cooked rice ea’": "75 g cooked rice",
        "ies 40g low fut cheese gare": "40 g low fat cheese",
    }

    for raw, expected in samples.items():
        cleaned = normalize(raw)
        assert compact(expected) in compact(cleaned)
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


def test_ingredient_dense_caption_can_skip_ocr():
    caption = """📊 Macros (per burrito)
585 Calories
57g Protein
55g Carbs
13g Fat
High Protein Butter Chicken Burritos
Packed with flavor and loaded with protein.
Ingredients: 800 g chicken breast, diced 120 g 0% Greek yoghurt 1 tsp paprika 1 tsp cumin 1.5 tsp garam masala 0.5 tsp turmeric 1.5 tsp salt 2 tsp garlic & ginger paste lemon juice cooking spray 20 g light butter 1 medium onion, sliced tomato paste 400 g chopped tomatoes 60 g light cream cheese 1/3 cup water 6 tortillas, warm 75 g cooked rice 40 g low fat cheese
"""
    assert _caption_has_recipe_signals(caption)


def test_ocr_available_engines_always_includes_tesseract():
    engines = _ocr_available_engines()
    assert engines[0] == "tesseract"
    assert "tesseract" in engines


def test_ocr_image_variants_are_bounded_for_runtime(monkeypatch):
    from PIL import Image
    import mcp_server

    monkeypatch.setattr(mcp_server, "OCR_MAX_VARIANTS_PER_IMAGE", 2)
    img = Image.new("RGB", (320, 568), "white")

    assert len(list(_ocr_image_variants(img))) == 2


def test_default_ocr_video_frame_cap_balances_recall_and_runtime():
    import mcp_server

    assert mcp_server.OCR_MAX_VIDEO_FRAMES == 52


def test_select_ocr_video_frames_preserves_full_timeline_when_capping():
    frames = [f"frame_{i:05d}.png" for i in range(120)]
    selected = _select_ocr_video_frames(frames, max_frames=5)

    assert selected[0] == frames[0]
    assert selected[-1] == frames[-1]
    assert len(selected) == 5
    assert selected == sorted(selected)


def test_extract_measured_ingredient_evidence_filters_macros_and_preserves_quantities():
    ocr_text = """
    800g chicken breast
    120g 0% Greek yoghurt
    1 tsp paprika
    1 tsp cumin
    1.5 tsp garam masala
    1/2 tsp turmeric
    1.5 tsp salt
    2 tsp garlic & Ginger
    lemon juice
    cooking spray
    20g light butter
    1 medium sliced onion
    30g tomato paste
    400g choppped tomatoes
    60g light creum cheese
    1/3 cup water
    6 tortillas warm
    75g cooked rice
    40g low fut cheese
    585 Calories
    57g Protein
    """

    evidence = _extract_measured_ingredient_evidence("", "", ocr_text)
    compacted = [compact(item) for item in evidence]

    for expected in [
        "800 g chicken breast",
        "120 g 0% Greek yoghurt",
        "1 tsp paprika",
        "1 tsp cumin",
        "1.5 tsp garam masala",
        "1/2 tsp turmeric",
        "1.5 tsp salt",
        "2 tsp garlic & Ginger",
        "20 g light butter",
        "1 medium sliced onion",
        "30 g tomato paste",
        "400 g chopped tomatoes",
        "60 g light cream cheese",
        "1/3 cup water",
        "6 tortillas",
        "75 g cooked rice",
        "40 g low fat cheese",
    ]:
        assert any(compact(expected) in item for item in compacted)

    assert not any("calories" in item or "protein" in item or "carbs" in item for item in compacted)


def test_measured_ingredient_evidence_ignores_transcript_macro_chatter():
    transcript = "that gives you 57 g rams of protein that you can meal prep"
    ocr_text = "40g low fat cheese"

    evidence = _extract_measured_ingredient_evidence(ocr_text)

    assert "40 g low fat cheese" in evidence
    assert not _extract_measured_ingredient_evidence(transcript)


def test_extract_unmeasured_ingredient_evidence_preserves_generic_mentions():
    ocr_text = """
    1 l emon juice
    cooking spray
    30 g tomato paste
    bacon
    random background text
    """

    evidence = _extract_unmeasured_ingredient_evidence(ocr_text)

    assert "lemon juice" in evidence
    assert "cooking spray" in evidence
    assert "tomato paste" in evidence
    assert "bacon" in evidence
    assert not any("random" in item for item in evidence)


def test_tiktok_short_ocr_garbage_is_not_preserved_as_ingredients():
    """Regression fixture for TikTok 7505186235124665646.

    Busy salmon-bite frames produced short OCR fragments like "7 fon", "2 anh",
    and "5 Bee". They look count-led enough to pass the old generic scoring, then
    the preservation pass force-inserted them into Ingredients ahead of the LLM.
    """
    ocr_text = """
    360 g of salmon
    360 g of salmon into Zsinch cubes
    2 inch cubes
    air fry at 400F for 8 10 minutes
    1 tbsp sriracha
    2 tbsp greek yogurt
    2 tsp rice vineoar
    7 fon
    7 g wee
    2 anh
    2 g Sats se
    5 Bee
    7 aoe args
    """

    measured = _extract_measured_ingredient_evidence(ocr_text)
    unmeasured = _extract_unmeasured_ingredient_evidence(ocr_text)
    combined = "\n".join(measured + unmeasured).lower()

    assert "360 g of salmon" in measured
    assert "1 tbsp sriracha" in measured
    assert "2 tbsp greek yogurt" in measured
    assert not any(item in combined for item in ["7 fon", "7 g wee", "2 anh", "2 g sats", "5 bee", "7 aoe", "wee", "sats"])


def test_preserve_measured_ingredient_evidence_replaces_vague_llm_ingredients():
    recipe_text = """High Protein Butter Chicken Burritos

Source: @themacrobar

Servings: 6
Serving Size: 1 burrito

## Ingredients
- 4 chicken breasts, diced [meat]
- 120g 0% Greek yogurt [dairy]
- seasonings (same as before) [spices]
- tomato paste [pantry]
- water, as needed [beverages]
- cooked rice [pantry]
- 40g low fat cheese [dairy]

## Instructions
1. Mix and cook.
"""
    evidence = [
        "800 g chicken breast",
        "120 g 0% Greek yoghurt",
        "1 tsp paprika",
        "1 tsp cumin",
        "1.5 tsp garam masala",
        "1/2 tsp turmeric",
        "1.5 tsp salt",
        "30 g tomato paste",
        "1/3 cup water",
        "75 g cooked rice",
        "40 g low fat cheese",
    ]

    fixed = _preserve_measured_ingredient_evidence(recipe_text, evidence)
    fixed_compact = compact(fixed)

    for expected in evidence:
        assert compact(expected) in fixed_compact

    assert "4 chicken breasts" not in fixed
    assert "seasonings (same as before)" not in fixed
    assert "water, as needed" not in fixed
    assert "- 1. Step" not in fixed

def test_dwc6zvt_reel_regression_preserves_expected_ingredients():
    """Regression fixture for https://www.instagram.com/reel/DWC6zVtDwH4/.

    The real reel is deliberately not fetched in unit tests. Instead this locks
    in the source evidence observed from that reel: caption/OCR ingredient text,
    noisy OCR fragments, and transcript macro chatter that previously leaked
    into ingredients as "57 g rams of protein that you".
    """
    caption = """
    📊 Macros (per burrito)
    585 Calories
    57g Protein
    55g Carbs
    13g Fat
    High Protein Butter Chicken Burritos
    Ingredients: 800 g chicken breast, diced 120 g 0% Greek yoghurt 1 tsp paprika
    1 tsp cumin 1.5 tsp garam masala 0.5 tsp turmeric 1.5 tsp salt
    2 tsp garlic & ginger paste lemon juice cooking spray 20 g light butter
    1 medium onion, sliced tomato paste 400 g chopped tomatoes
    60 g light cream cheese 1/3 cup water 6 tortillas, warm
    75 g cooked rice 40 g low fat cheese
    """
    noisy_ocr = """
    i @@800g chicken'breast Aa \\
    @l20g 0%'Greek- yoghurt
    1tsp paprika
    tsp cumin
    5 tsp garam masaia
    2 tsp turmeric
    ¢ -LStsp salt” Ps
    @if2 tsp garlic &.ginger ae
    1 l emon juice
    cooking spray
    20g light butter
    1 medium sliced onion
    +) 830g tomato pastes 120’
    400g choppped tomatoes
    60g light creum cheese
    i 1/5 cup water G5
    6 tortillas warm
    759 cooked rice ea’
    ies 40g low fut cheese gare
    """
    transcript_macro_chatter = """
    These burritos have 585 calories, 57 g rams of protein that you can meal prep,
    55 g carbs, and 13 g fat per burrito.
    """
    llm_output_with_known_drift = """High Protein Butter Chicken Burritos

## Macros
Calories: 585 | Protein: 57g | Carbs: 55g | Fat: 13g

## Ingredients
- 4 chicken breasts, diced [meat]
- 120g 0% Greek yogurt [dairy]
- seasonings (same as before) [spices]
- garlic & ginger paste [produce]
- lemon juice [condiments]
- cooking spray [pantry]
- light butter [dairy]
- onion, sliced [produce]
- tomato paste [condiments]
- chopped tomatoes [produce]
- cream cheese [dairy]
- water, as needed [pantry]
- tortillas, warmed [bakery]
- cooked rice [pantry]
- low fat cheese [dairy]
- 57 g rams of protein that you [other]

## Instructions
1. Mix and cook.
"""

    measured = _extract_measured_ingredient_evidence(caption, noisy_ocr)
    unmeasured = _extract_unmeasured_ingredient_evidence(caption, noisy_ocr)
    fixed = _preserve_ingredient_evidence(llm_output_with_known_drift, measured, unmeasured)
    fixed_compact = compact(fixed)
    ingredients_section = fixed.split("## Instructions", 1)[0]
    ingredient_lines = [line for line in ingredients_section.splitlines() if line.strip().startswith("-")]

    expected_ingredients = [
        "800 g chicken breast",
        "120 g 0% Greek yoghurt",
        "1/2 tsp turmeric",
        "1 tsp paprika",
        "1 tsp cumin",
        "1.5 tsp garam masala",
        "1.5 tsp salt",
        "2 tsp garlic & ginger",
        "lemon juice",
        "cooking spray",
        "20 g light butter",
        "1 medium onion",
        "30 g tomato paste",
        "400 g chopped tomatoes",
        "60 g light cream cheese",
        "1/3 cup water",
        "6 tortillas",
        "75 g cooked rice",
        "40 g low fat cheese",
    ]

    assert not _extract_measured_ingredient_evidence(transcript_macro_chatter)
    for expected in expected_ingredients:
        assert compact(expected) in fixed_compact

    assert "4 chicken breasts" not in fixed
    assert "seasonings (same as before)" not in fixed
    assert "water, as needed" not in fixed
    assert all("57 g rams of protein" not in line for line in ingredient_lines[:19])

def test_dzot65qbrle_reel_regression_preserves_bacon_ocr_label():
    """Regression fixture for https://www.instagram.com/reel/DZOT65QBrlE/.

    This reel's caption does not list ingredients, but OCR sees a brief standalone
    "bacon" overlay around frame 48. The pipeline has no object detection; bacon
    must be preserved from OCR text, not inferred from the video pixels.
    """
    ocr_text = """
    season with bbq seasoning + paprika
    air fry 400° for 5 min each side
    y bacon ae P J
    bacon
    any greenery works,
    I love this salad kit
    MAPLE BACON BBQ CHICKEN BOWL
    drizzle with BBQ sauce and chipotle
    """
    llm_output_missing_bacon = """Maple Bacon BBQ Chicken Bowl

## Ingredients
- 1 salad kit (any mix/greenery) [produce]
- 1 sweet potato [produce]
- 1 chicken breast [meat]
- 1 tbsp Greek yogurt [dairy]
- 1 tbsp Chipotle sauce [condiments]
- 1/2 tsp ranch seasoning [spices]
- squeeze of hot honey [condiments]
- BBQ sauce [condiments]
- paprika [spices]
- salt [spices]
- oil [pantry]
- french fried onions [pantry]

## Instructions
1. Build the bowl.
"""

    measured = _extract_measured_ingredient_evidence(ocr_text)
    unmeasured = _extract_unmeasured_ingredient_evidence(ocr_text)
    fixed = _preserve_ingredient_evidence(llm_output_missing_bacon, measured, unmeasured)

    assert "bacon" in unmeasured
    assert "- bacon [meat]" in fixed

def test_book_page_ocr_block_is_not_preserved_as_ingredient_evidence():
    """Regression fixture for dense cookbook/page OCR in TikTok end cards."""
    useful_overlay = """
    2 low cal tortillas
    1 laughing cow
    1/4 tsp ranch seasoning
    drizzle of Greek yogurt ranch
    tiny bit of cheese
    """
    book_page_ocr = """
    FART Cente
    CHICKEN PIZZA AGAR e 8
    4 X Q flavor FULL
    Air fry 375F for 5 7 min or until crisp cand o
    Add sliced pickles and another drizzle of
    digital cookbooks
    NASHVILLE
    CHICKEN PIZZA
    imgredients
    Makayte Tgong
    directions
    chicken here
    yourpizza sauce
    flavor FULL
    Fat: 9¢ I
    24 g Go HOME
    """
    ocr_text = f"{useful_overlay}\n---\n{book_page_ocr}"

    assert _ocr_text_looks_like_book_page(book_page_ocr)
    assert not _ocr_text_looks_like_book_page(useful_overlay)

    measured = _extract_measured_ingredient_evidence(ocr_text)
    unmeasured = _extract_unmeasured_ingredient_evidence(ocr_text)
    combined = "\n".join(measured + unmeasured).lower()

    assert "1/4 tsp ranch seasoning" in measured
    assert "ranch seasoning" in combined
    assert "chicken pizza agar" not in combined
    assert "chicken pizza" not in combined
    assert "chicken here" not in combined
    assert "yourpizza sauce" not in combined


def test_tiktok_photo_caption_recipe_ignores_low_signal_decorative_ocr():
    """Regression fixture for TikTok 7477345219885763845.

    The post has a complete recipe in the TikTok caption, but the single photo is
    just a plated-food image. Tesseract read plate/background texture as junk
    like "15 g Ingredients" and "4 cup bell peppers", which contaminated recipe
    186. Caption-rich slideshows should ignore that low-signal decorative OCR.
    """
    caption = """
    Calories: 520   Protein: 45g   Carbs: 50g   Fat: 15g
    Ingredients: For the Turkey Meatballs: 1 lb lean ground turkey
    1/4 cup breadcrumbs 1 egg 2 cloves garlic, minced 1/2 tsp salt
    1/2 tsp black pepper 1/2 tsp dried oregano 1/2 tsp ground cumin
    1 tbsp fresh parsley, chopped 1 tbsp olive oil (for cooking)
    For the Tzatziki Sauce: 1/2 cup Greek yogurt 1/4 cup cucumber, grated and drained
    1 clove garlic, minced 1 tbsp lemon juice 1 tbsp fresh dill, chopped 1/4 tsp salt
    For the Bowl: 1 cup cooked rice 1/2 cup cherry tomatoes, halved
    1/2 cup cucumber, sliced 1/4 cup red onion, diced 1/4 cup bell peppers, diced
    Fresh dill and black pepper for garnish
    Instructions: 1. Prepare the Meatballs. 2. Shape & Cook the Meatballs.
    3. Make the Tzatziki Sauce. 4. Assemble the Bowl. 5. Add the Finishing Touches.
    """
    decorative_photo_ocr = """
    - > .
    — — -_—
    = ”
    ~ . = 7? oe ~ 9
    > os »
    15 g Ingredients For the Turkey Meatballs
    4 cup bell peppers
    1 tbsp olive oil
    . 7 \\ ? G os... ~ ee ?
    Be oe ee ar aig: ver eee ~ (ae Z
    """

    assert _caption_has_recipe_signals(caption)
    assert not _slideshow_ocr_has_recipe_signal(decorative_photo_ocr)
    assert not _should_use_slideshow_ocr(caption, decorative_photo_ocr)

    # The caption itself remains authoritative and still preserves the real bowl
    # quantity. The decorative-photo OCR must not get a chance to override it.
    caption_measured = _extract_measured_ingredient_evidence(caption)
    assert any(item.startswith("1/4 cup bell pepper") for item in caption_measured)
    assert not _should_use_slideshow_ocr(caption, decorative_photo_ocr)


def test_caption_poor_slideshow_still_uses_strong_recipe_ocr():
    caption = "Mediterranean meal prep bowl #FoodTok"
    real_recipe_card_ocr = """
    Ingredients
    1 lb lean ground turkey
    1/4 cup breadcrumbs
    1 egg
    Instructions
    Mix and cook meatballs.
    """

    assert not _caption_has_recipe_signals(caption)
    assert _slideshow_ocr_has_recipe_signal(real_recipe_card_ocr)
    assert _should_use_slideshow_ocr(caption, real_recipe_card_ocr)


def test_book_page_detector_focuses_on_book_structure_not_single_recipe_heading():
    normal_overlay = """
    ingredients
    800 g chicken breast
    120 g greek yogurt
    1 tsp paprika
    """
    chapter_page = """
    Chapter 4
    Weeknight Dinners
    Page 42
    Ingredients
    Directions
    Copyright 2025
    """

    assert not _ocr_text_looks_like_book_page(normal_overlay)
    assert _ocr_text_looks_like_book_page(chapter_page)

