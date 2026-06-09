/**
 * Reel Cookbook — Frontend Logic
 * Features: Search, Filter, Recipe Modal, Edit, Delete,
 *           Shopping List, Serving Scaler, Cook Mode, Dark Mode
 */

/* ─── Theme System (runs immediately to prevent flash) ─── */
(function() {
    function getEffectiveTheme(preference) {
        if (preference === 'system') {
            return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
        return preference;
    }

    const stored = localStorage.getItem('onlypans-theme') || 'system';
    const effective = getEffectiveTheme(stored);
    if (effective === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    } else {
        document.documentElement.removeAttribute('data-theme');
    }
})();

const searchInput = document.getElementById('searchInput');
const clearBtn = document.getElementById('clearSearch');
const recipeGrid = document.getElementById('recipeGrid');
const emptyState = document.getElementById('emptyState');
const filterChips = document.getElementById('filterChips');
const modalOverlay = document.getElementById('modalOverlay');
const modalContent = document.getElementById('modalContent');
const modalClose = document.getElementById('modalClose');
const shoppingOverlay = document.getElementById('shoppingOverlay');
const shoppingContent = document.getElementById('shoppingContent');
const shoppingClose = document.getElementById('shoppingClose');
const cookModeEl = document.getElementById('cookMode');
const cookModeContent = document.getElementById('cookModeContent');
const cartToggle = document.getElementById('cartToggle');
const cartBadge = document.getElementById('cartBadge');
const addReelBtn = document.getElementById('addReelBtn');
const spotlightOverlay = document.getElementById('spotlightOverlay');

let allRecipes = [];
let currentRecipe = null;
let isEditMode = false;
let editFormSnapshot = null;
let debounceTimer = null;
let currentMultiplier = 1;
let originalServings = 1;
const MULTIPLIER_STEPS = [0.5, 1, 2, 3, 4];
let wakeLockSentinel = null;
let unitSystem = localStorage.getItem('onlypans-units') || 'original'; // 'original' | 'metric' | 'imperial'

// ─── Drink Detection ────────────────────────────
const DRINK_TAGS = new Set([
    'cocktail', 'mocktail', 'spirits', 'smoothie', 'shake',
    'lemonade', 'punch', 'coffee', 'matcha',
]);

const DRINK_EMOJI = {
    'cocktail': '🍸', 'mocktail': '🧃', 'spirits': '🥃',
    'smoothie': '🥤', 'shake': '🥛', 'lemonade': '🍋',
    'punch': '🍹', 'coffee': '☕', 'matcha': '🍵',
};

function isDrinkRecipe(recipe) {
    if (!recipe.tags || !recipe.tags.length) return false;
    return recipe.tags.some(t => DRINK_TAGS.has(t.toLowerCase()));
}

function getDrinkEmoji(recipe) {
    if (!recipe.tags) return '🍹';
    for (const t of recipe.tags) {
        const emoji = DRINK_EMOJI[t.toLowerCase()];
        if (emoji) return emoji;
    }
    return '🍹';
}

// ─── Ingredient Helpers ─────────────────────────
// Ingredients can be strings (old) or {text, section} objects (new)
function ingText(ing) {
    if (typeof ing === 'string') return ing;
    if (ing && typeof ing === 'object') return ing.text || String(ing);
    return String(ing);
}

// ─── Date Helpers ───────────────────────────────
function isNewRecipe(recipe) {
    if (!recipe.created_at) return false;
    const created = new Date(recipe.created_at.replace(' ', 'T') + 'Z');
    const now = new Date();
    return (now - created) < 24 * 60 * 60 * 1000;
}

function formatDateAdded(dateStr) {
    if (!dateStr) return '';
    const created = new Date(dateStr.replace(' ', 'T') + 'Z');
    const now = new Date();
    const diffMs = now - created;
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffHours < 1) return 'Just now';
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays}d ago`;

    return created.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

// ─── Shopping List State ─────────────────────────
const CART_KEY = 'reel-cookbook-cart';
const CHECKED_KEY = 'reel-cookbook-checked';

function getCart() {
    try {
        return JSON.parse(localStorage.getItem(CART_KEY)) || [];
    } catch { return []; }
}

function setCart(ids) {
    localStorage.setItem(CART_KEY, JSON.stringify(ids));
    updateCartBadge();
}

function getChecked() {
    try {
        return JSON.parse(localStorage.getItem(CHECKED_KEY)) || [];
    } catch { return []; }
}

function setChecked(items) {
    localStorage.setItem(CHECKED_KEY, JSON.stringify(items));
}

function addToCart(recipeId) {
    recipeId = Number(recipeId);
    const cart = getCart();
    if (!cart.includes(recipeId)) {
        cart.push(recipeId);
        setCart(cart);
    }
}

function removeFromCart(recipeId) {
    recipeId = Number(recipeId);
    const cart = getCart().filter(id => id !== recipeId);
    setCart(cart);
}

function updateCartBadge() {
    const cart = getCart();
    if (cart.length > 0) {
        cartBadge.textContent = cart.length;
        cartBadge.style.display = 'flex';
    } else {
        cartBadge.style.display = 'none';
    }
}

// ─── Fraction Utilities ──────────────────────────
const DECIMAL_TO_FRACTION = [
    [0.125, '⅛'], [0.25, '¼'], [0.333, '⅓'], [0.375, '⅜'],
    [0.5, '½'], [0.625, '⅝'], [0.667, '⅔'], [0.75, '¾'], [0.875, '⅞']
];

function parseFraction(str) {
    str = str.trim();
    // Handle mixed number like "1 1/2"
    const mixedMatch = str.match(/^(\d+)\s+(\d+)\/(\d+)$/);
    if (mixedMatch) {
        return parseInt(mixedMatch[1]) + parseInt(mixedMatch[2]) / parseInt(mixedMatch[3]);
    }
    // Handle simple fraction like "1/2"
    const fracMatch = str.match(/^(\d+)\/(\d+)$/);
    if (fracMatch) {
        return parseInt(fracMatch[1]) / parseInt(fracMatch[2]);
    }
    // Handle decimal
    const num = parseFloat(str);
    return isNaN(num) ? null : num;
}

function formatNumber(num) {
    if (num === 0) return '0';
    const whole = Math.floor(num);
    const frac = num - whole;

    if (frac < 0.05) return whole.toString();

    // Find closest fraction
    let closestFrac = '';
    let closestDiff = 1;
    for (const [val, symbol] of DECIMAL_TO_FRACTION) {
        const diff = Math.abs(frac - val);
        if (diff < closestDiff) {
            closestDiff = diff;
            closestFrac = symbol;
        }
    }

    if (closestDiff < 0.05) {
        return whole > 0 ? `${whole} ${closestFrac}` : closestFrac;
    }

    // Fall back to decimal with at most 2 places
    const result = Math.round(num * 100) / 100;
    return result % 1 === 0 ? result.toString() : result.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
}

function parseIngredientQuantity(ingredient) {
    // Match leading quantity: digits, fractions, decimals, mixed numbers
    const match = ingredient.match(/^([\d\s\/\.]+)\s*(.*)$/);
    if (!match) return { quantity: null, rest: ingredient };

    const quantityStr = match[1].trim();
    const rest = match[2];
    const quantity = parseFraction(quantityStr);

    if (quantity === null) return { quantity: null, rest: ingredient };
    return { quantity, rest };
}

function scaleIngredient(ingredient, ratio) {
    const { quantity, rest } = parseIngredientQuantity(ingredient);
    if (quantity === null) return ingredient;
    const scaled = quantity * ratio;
    return `${formatNumber(scaled)} ${rest}`;
}

// ─── Unit Conversion Engine ─────────────────────
const UNIT_CONVERSIONS = {
    // Weight: metric → imperial
    'g': { imperial: { factor: 0.03527396, unit: 'oz', threshold: 28 } },
    'grams': { imperial: { factor: 0.03527396, unit: 'oz', threshold: 28 } },
    'gram': { imperial: { factor: 0.03527396, unit: 'oz', threshold: 28 } },
    'kg': { imperial: { factor: 2.20462, unit: 'lb', threshold: 0.1 } },
    'kilogram': { imperial: { factor: 2.20462, unit: 'lb', threshold: 0.1 } },
    'kilograms': { imperial: { factor: 2.20462, unit: 'lb', threshold: 0.1 } },
    // Weight: imperial → metric
    'oz': { metric: { factor: 28.3495, unit: 'g', threshold: 0.5 } },
    'ounce': { metric: { factor: 28.3495, unit: 'g', threshold: 0.5 } },
    'ounces': { metric: { factor: 28.3495, unit: 'g', threshold: 0.5 } },
    'lb': { metric: { factor: 453.592, unit: 'g', threshold: 0.25 } },
    'lbs': { metric: { factor: 453.592, unit: 'g', threshold: 0.25 } },
    'pound': { metric: { factor: 453.592, unit: 'g', threshold: 0.25 } },
    'pounds': { metric: { factor: 453.592, unit: 'g', threshold: 0.25 } },
    // Volume: metric → imperial
    'ml': { imperial: { factor: 0.033814, unit: 'fl oz', threshold: 15 } },
    'milliliter': { imperial: { factor: 0.033814, unit: 'fl oz', threshold: 15 } },
    'milliliters': { imperial: { factor: 0.033814, unit: 'fl oz', threshold: 15 } },
    'l': { imperial: { factor: 4.22675, unit: 'cups', threshold: 0.05 } },
    'liter': { imperial: { factor: 4.22675, unit: 'cups', threshold: 0.05 } },
    'liters': { imperial: { factor: 4.22675, unit: 'cups', threshold: 0.05 } },
    'litre': { imperial: { factor: 4.22675, unit: 'cups', threshold: 0.05 } },
    'litres': { imperial: { factor: 4.22675, unit: 'cups', threshold: 0.05 } },
    // Volume: imperial → metric
    'cup': { metric: { factor: 236.588, unit: 'ml', threshold: 0.125 } },
    'cups': { metric: { factor: 236.588, unit: 'ml', threshold: 0.125 } },
    'tbsp': { metric: { factor: 14.787, unit: 'ml', threshold: 0.5 } },
    'tablespoon': { metric: { factor: 14.787, unit: 'ml', threshold: 0.5 } },
    'tablespoons': { metric: { factor: 14.787, unit: 'ml', threshold: 0.5 } },
    'tsp': { metric: { factor: 4.929, unit: 'ml', threshold: 0.25 } },
    'teaspoon': { metric: { factor: 4.929, unit: 'ml', threshold: 0.25 } },
    'teaspoons': { metric: { factor: 4.929, unit: 'ml', threshold: 0.25 } },
    'fl oz': { metric: { factor: 29.5735, unit: 'ml', threshold: 0.5 } },
    'fluid ounce': { metric: { factor: 29.5735, unit: 'ml', threshold: 0.5 } },
    'fluid ounces': { metric: { factor: 29.5735, unit: 'ml', threshold: 0.5 } },
    'quart': { metric: { factor: 946.353, unit: 'ml', threshold: 0.25 } },
    'quarts': { metric: { factor: 946.353, unit: 'ml', threshold: 0.25 } },
    'pint': { metric: { factor: 473.176, unit: 'ml', threshold: 0.25 } },
    'pints': { metric: { factor: 473.176, unit: 'ml', threshold: 0.25 } },
    'gallon': { metric: { factor: 3785.41, unit: 'ml', threshold: 0.25 } },
    'gallons': { metric: { factor: 3785.41, unit: 'ml', threshold: 0.25 } },
    // Temperature: handled separately
    '°c': { imperial: { convert: (v) => v * 9/5 + 32, unit: '°F' } },
    '°f': { metric: { convert: (v) => (v - 32) * 5/9, unit: '°C' } },
    'c': { _tempOnly: true, imperial: { convert: (v) => v * 9/5 + 32, unit: '°F' } },
    'f': { _tempOnly: true, metric: { convert: (v) => (v - 32) * 5/9, unit: '°C' } },
};

function detectIngredientSystem(ingredients) {
    // Detect whether recipe is predominantly metric or imperial
    let metricCount = 0, imperialCount = 0;
    const metricUnits = new Set(['g', 'grams', 'gram', 'kg', 'kilogram', 'kilograms', 'ml', 'milliliter', 'milliliters', 'l', 'liter', 'liters', 'litre', 'litres', '°c']);
    const imperialUnits = new Set(['oz', 'ounce', 'ounces', 'lb', 'lbs', 'pound', 'pounds', 'cup', 'cups', 'tbsp', 'tablespoon', 'tablespoons', 'tsp', 'teaspoon', 'teaspoons', 'fl oz', 'fluid ounce', 'fluid ounces', 'quart', 'quarts', 'pint', 'pints', 'gallon', 'gallons', '°f']);

    for (const ing of ingredients) {
        const text = ingText(ing).toLowerCase();
        for (const u of metricUnits) {
            if (text.includes(u)) { metricCount++; break; }
        }
        for (const u of imperialUnits) {
            if (text.includes(u)) { imperialCount++; break; }
        }
    }
    if (metricCount > imperialCount) return 'metric';
    if (imperialCount > metricCount) return 'imperial';
    return 'mixed';
}

function getTargetSystem(recipeSystem) {
    // If user selected 'original', show as-is
    if (unitSystem === 'original') return null;
    // Otherwise convert toward the selected system
    return unitSystem;
}

function convertIngredientUnits(ingredientText, targetSystem) {
    if (!targetSystem) return ingredientText;

    // Match: quantity + unit + rest of ingredient
    // e.g. "800g chicken breast" or "2 cups flour" or "1/2 lb ground beef"
    const match = ingredientText.match(/^([\d\s\/\.]+)\s*(°[cfCF]|fl oz|fluid ounces?|[a-zA-Z]+)\.?\s+(.*)$/);
    if (!match) return ingredientText;

    const quantityStr = match[1].trim();
    const unitRaw = match[2];
    const remainder = match[3];

    const quantity = parseFraction(quantityStr);
    if (quantity === null) return ingredientText;

    const unitLower = unitRaw.toLowerCase();
    const conversion = UNIT_CONVERSIONS[unitLower];
    if (!conversion) return ingredientText;
    if (!conversion[targetSystem]) return ingredientText;

    // Skip temp-only markers unless the value looks like a temperature (>100 for C, >200 for F)
    if (conversion._tempOnly) {
        if (unitLower === 'c' && quantity < 100) return ingredientText;
        if (unitLower === 'f' && quantity < 200) return ingredientText;
    }

    const conv = conversion[targetSystem];
    let converted;
    if (conv.convert) {
        converted = conv.convert(quantity);
    } else {
        converted = quantity * conv.factor;
    }

    // Smart rounding: round to reasonable precision
    if (converted >= 100) {
        converted = Math.round(converted);
    } else if (converted >= 10) {
        converted = Math.round(converted * 2) / 2; // nearest 0.5
    } else {
        converted = Math.round(converted * 4) / 4; // nearest 0.25
    }

    return `${formatNumber(converted)} ${conv.unit} ${remainder}`;
}

// Also handle the "800g" no-space pattern
function convertIngredientLine(ingredientText, targetSystem) {
    if (!targetSystem) return ingredientText;

    // First try: "800g chicken" (no space between number and unit)
    const noSpaceMatch = ingredientText.match(/^([\d\s\/\.]+)(g|kg|ml|oz|lb|lbs)\b\s*(.*)$/i);
    if (noSpaceMatch) {
        const quantityStr = noSpaceMatch[1].trim();
        const unitRaw = noSpaceMatch[2];
        const remainder = noSpaceMatch[3];
        const quantity = parseFraction(quantityStr);
        if (quantity !== null) {
            const unitLower = unitRaw.toLowerCase();
            const conversion = UNIT_CONVERSIONS[unitLower];
            if (conversion && conversion[targetSystem]) {
                const conv = conversion[targetSystem];
                let converted = conv.convert ? conv.convert(quantity) : quantity * conv.factor;
                if (converted >= 100) converted = Math.round(converted);
                else if (converted >= 10) converted = Math.round(converted * 2) / 2;
                else converted = Math.round(converted * 4) / 4;
                return `${formatNumber(converted)} ${conv.unit} ${remainder}`;
            }
        }
    }

    // Standard pattern with space
    return convertIngredientUnits(ingredientText, targetSystem);
}

function getConvertedIngredient(ing, multiplier, targetSystem) {
    let text = ingText(ing);
    if (multiplier !== 1) text = scaleIngredient(text, multiplier);
    if (targetSystem) text = convertIngredientLine(text, targetSystem);
    return text;
}

function cycleUnits() {
    // Cycle: original → imperial → metric → original
    const cycle = ['original', 'imperial', 'metric'];
    const idx = cycle.indexOf(unitSystem);
    unitSystem = cycle[(idx + 1) % cycle.length];
    localStorage.setItem('onlypans-units', unitSystem);

    refreshIngredientsDisplay();
    updateUnitToggleLabel();
}

function updateUnitToggleLabel() {
    const btn = document.getElementById('unitToggleBtn');
    if (!btn) return;
    const labels = { original: 'As Written', imperial: 'oz · lb · cups', metric: 'g · ml · °C' };
    btn.setAttribute('data-units', unitSystem);
    btn.querySelector('.unit-toggle-label').textContent = labels[unitSystem];
}

function refreshIngredientsDisplay() {
    const ingredientsList = document.getElementById('ingredientsList');
    if (!ingredientsList || !currentRecipe) return;

    const recipeSystem = detectIngredientSystem(currentRecipe.ingredients);
    const targetSystem = getTargetSystem(recipeSystem);

    ingredientsList.innerHTML = currentRecipe.ingredients.map(ing => {
        const text = getConvertedIngredient(ing, currentMultiplier, targetSystem);
        return `<li>${escapeHtml(text)}</li>`;
    }).join('');
}

function recipeIsScalable(recipe) {
    // Only show scaler if at least 30% of ingredients have numeric quantities
    if (!recipe.ingredients || recipe.ingredients.length === 0) return false;
    const withQuantity = recipe.ingredients.filter(ing => {
        const text = ingText(ing);
        return parseIngredientQuantity(text).quantity !== null;
    }).length;
    return withQuantity / recipe.ingredients.length >= 0.3;
}

function parseServingsNumber(servingsStr) {
    if (!servingsStr) return null;
    // Try to get first number from string like "4", "2-4", "8 tacos", "4 servings"
    const match = servingsStr.match(/(\d+)/);
    return match ? parseInt(match[1]) : null;
}

// ─── Init ───────────────────────────────────────
let hasLoadedOnce = false;

async function init() {
    await loadUserProfile();
    await loadRecipes();
    await loadCategories();
    setupListeners();
    updateCartBadge();
    hasLoadedOnce = true;
    // Deep-link: open recipe if URL is /recipe/<id>/...
    await openRecipeFromUrl();
    // Handle browser back/forward
    window.addEventListener('popstate', async () => {
        if (location.pathname.startsWith('/recipe/')) {
            await openRecipeFromUrl();
        } else {
            closeModal();
        }
    });
    // Poll for new recipes every 60s
    setInterval(pollForNewRecipes, 60000);

    // PWA resume: skip card animations when returning from background
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && hasLoadedOnce) {
            // Mark all existing cards as no-animate so they don't replay entrance
            document.querySelectorAll('.recipe-card').forEach(card => {
                card.classList.add('no-animate');
            });
        }
    });

    // iOS PWA first-tap fix: when the app resumes from background, WebKit
    // sometimes requires a touch to "wake" the compositor before registering clicks.
    // Force a reflow on pageshow to ensure the hit-test tree is ready immediately.
    window.addEventListener('pageshow', (e) => {
        if (e.persisted || hasLoadedOnce) {
            // Force synchronous reflow — makes hit-test regions immediately active
            void document.body.offsetHeight;
            // Also ensure cards are not stuck in animation state
            document.querySelectorAll('.recipe-card').forEach(card => {
                card.classList.add('no-animate');
            });
        }
    });
}

// ─── User Profile ────────────────────────────────
async function loadUserProfile() {
    try {
        const res = await fetch('/auth/me', { credentials: 'same-origin' });
        const data = await res.json();
        if (!data.authenticated) return;

        // Populate shared currentUser for reviews + filters
        currentUser = data;

        const profileEl = document.getElementById('userProfile');
        const avatarEl = document.getElementById('userAvatar');
        const dropdownAvatarEl = document.getElementById('dropdownAvatar');
        const nameEl = document.getElementById('dropdownName');
        const usernameEl = document.getElementById('dropdownUsername');
        const avatarBtn = document.getElementById('userAvatarBtn');
        const dropdown = document.getElementById('userDropdown');

        // Set avatar (fallback to Discord default)
        const avatarUrl = data.avatar_url || `https://cdn.discordapp.com/embed/avatars/${parseInt(data.discord_id) % 5}.png`;
        avatarEl.src = avatarUrl;
        dropdownAvatarEl.src = avatarUrl;
        nameEl.textContent = data.display_name || data.username;
        usernameEl.textContent = `@${data.username}`;
        profileEl.style.display = 'block';

        // Toggle dropdown on click
        avatarBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('open');
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target) && !avatarBtn.contains(e.target)) {
                dropdown.classList.remove('open');
            }
        });

        // Theme toggle
        initThemeToggle();
    } catch (e) {
        console.error('Failed to load user profile:', e);
    }
}

/* ─── Theme Toggle ─── */
function initThemeToggle() {
    const toggleGroup = document.getElementById('themeToggleGroup');
    if (!toggleGroup) return;

    const stored = localStorage.getItem('onlypans-theme') || 'system';

    // Set initial active state
    toggleGroup.querySelectorAll('.theme-toggle-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.theme === stored);
    });

    toggleGroup.addEventListener('click', (e) => {
        const btn = e.target.closest('.theme-toggle-btn');
        if (!btn) return;

        const preference = btn.dataset.theme;
        localStorage.setItem('onlypans-theme', preference);

        // Update active state
        toggleGroup.querySelectorAll('.theme-toggle-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        applyTheme(preference);
    });

    // Listen for system theme changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
        const current = localStorage.getItem('onlypans-theme') || 'system';
        if (current === 'system') {
            applyTheme('system');
        }
    });
}

function applyTheme(preference) {
    const effective = preference === 'system'
        ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
        : preference;

    // Add transition class for smooth change
    document.documentElement.classList.add('theme-transitioning');

    if (effective === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    } else {
        document.documentElement.removeAttribute('data-theme');
    }

    // Remove transition class after animation
    setTimeout(() => {
        document.documentElement.classList.remove('theme-transitioning');
    }, 450);
}

async function openRecipeFromUrl() {
    const match = location.pathname.match(/^\/recipe\/(\d+)/);
    if (!match) return;
    try {
        const res = await fetch(`/api/recipes/${match[1]}`);
        if (!res.ok) return;
        const recipe = await res.json();
        renderModal(recipe);
        modalOverlay.classList.add('active');
        document.body.style.overflow = 'hidden';
    } catch (e) { /* recipe not found — stay on gallery */ }
}

// ─── Data Loading ───────────────────────────────
async function loadRecipes(query = '') {
    const url = query ? `/api/recipes?q=${encodeURIComponent(query)}` : '/api/recipes';
    const res = await fetch(url);
    allRecipes = await res.json();
    // Normalize tags: API returns comma-separated string, UI expects array
    allRecipes.forEach(r => {
        if (typeof r.tags === 'string') {
            r.tags = r.tags ? r.tags.split(',').map(t => t.trim()).filter(Boolean) : [];
        } else if (!Array.isArray(r.tags)) {
            r.tags = [];
        }
    });
    renderGrid(allRecipes);
}

async function pollForNewRecipes() {
    // Silent background poll — reload only if recipe count changed
    try {
        const query = searchInput ? searchInput.value : '';
        const url = query ? `/api/recipes?q=${encodeURIComponent(query)}` : '/api/recipes';
        const res = await fetch(url);
        if (!res.ok) return;
        const recipes = await res.json();
        if (recipes.length !== allRecipes.length) {
            recipes.forEach(r => {
                if (typeof r.tags === 'string') {
                    r.tags = r.tags ? r.tags.split(',').map(t => t.trim()).filter(Boolean) : [];
                } else if (!Array.isArray(r.tags)) {
                    r.tags = [];
                }
            });
            allRecipes = recipes;
            renderGrid(allRecipes);
            loadCategories();
        }
    } catch (e) {
        // Silent — don't disrupt UX on network blips
    }
}
async function loadCategories() {
    const res = await fetch('/api/categories');
    const categories = await res.json();
    renderCategoryChips(categories);
}

// ─── Category Emoji Map ─────────────────────────
const CATEGORY_ICONS = {
    // Proteins
    'chicken': '🍗', 'beef': '🥩', 'pork': '🥓', 'seafood': '🦐',
    'fish': '🐟', 'salmon': '🍣', 'shrimp': '🦐', 'duck': '🦆',
    'lamb': '🐑', 'turkey': '🦃',
    // Cuisines
    'japanese': '🇯🇵', 'korean': '🇰🇷', 'chinese': '🇨🇳', 'mexican': '🇲🇽',
    'italian': '🇮🇹', 'indian': '🇮🇳', 'thai': '🇹🇭', 'vietnamese': '🇻🇳',
    'french': '🇫🇷', 'american': '🇺🇸', 'mediterranean': '🫒',
    'cajun': '🫘', 'middle eastern': '🧆',
    // Meal types
    'breakfast': '🍳', 'lunch': '🥪', 'dinner': '🍽️', 'snack': '🍿',
    'dessert': '🍰', 'appetizer': '🥟', 'brunch': '🧇',
    // Dish types
    'sandwich': '🥪', 'burger': '🍔', 'pizza': '🍕', 'tacos': '🌮',
    'soup': '🍲', 'salad': '🥗', 'bowl': '🥣', 'rice': '🍚',
    'noodles': '🍜', 'curry': '🍛', 'wings': '🍗', 'dumplings': '🥟',
    'pasta': '🍝', 'fries': '🍟', 'wrap': '🌯',
    // Cooking style
    'air fryer': '💨', 'bbq': '🍖', 'fried': '🍳',
    // Dietary
    'spicy': '🌶️', 'vegan': '🌱', 'vegetarian': '🥬',
    // Drinks & Cocktails
    'cocktail': '🍸', 'mocktail': '🧃', 'spirits': '🥃',
    'smoothie': '🥤', 'shake': '🥛', 'lemonade': '🍋',
    'punch': '🍹', 'coffee': '☕', 'matcha': '🍵',
};

function getCategoryIcon(name) {
    const key = name.toLowerCase();
    if (CATEGORY_ICONS[key]) return CATEGORY_ICONS[key];
    // Fuzzy match
    for (const [k, v] of Object.entries(CATEGORY_ICONS)) {
        if (key.includes(k) || k.includes(key)) return v;
    }
    return '🍴';
}

// ─── Rendering ──────────────────────────────────
function renderCategoryChips(categories) {
    let chips = '';

    // "Added by Me" chip (only if logged in)
    if (currentUser && currentUser.authenticated) {
        const avatarUrl = currentUser.avatar_url || `https://cdn.discordapp.com/embed/avatars/${parseInt(currentUser.discord_id) % 5}.png`;
        chips += `
            <button class="chip chip-added-by-me" data-filter="added-by-me">
                <img class="chip-avatar" src="${avatarUrl}" alt="" />
                <span class="chip-label">Added by Me</span>
            </button>
        `;
    }

    // "Top Rated" chip (4+ stars filter)
    chips += `
        <button class="chip chip-top-rated" data-filter="top-rated">
            <span class="chip-icon">⭐</span>
            <span class="chip-label">Top Rated</span>
        </button>
    `;

    chips += categories.map(c => `
        <button class="chip" data-category="${escapeAttr(c.name)}">
            <span class="chip-icon">${getCategoryIcon(c.name)}</span>
            <span class="chip-label">${escapeHtml(c.name)}</span>
        </button>
    `).join('');

    filterChips.innerHTML = chips;
}
function renderGrid(recipes) {
    if (recipes.length === 0) {
        recipeGrid.innerHTML = '';
        emptyState.style.display = 'block';
        return;
    }

    emptyState.style.display = 'none';
    const cart = getCart();
    recipeGrid.innerHTML = recipes.map((r, i) => `
        <article class="recipe-card" data-id="${r.id}">
            ${isNewRecipe(r) ? '<span class="new-badge">NEW</span>' : ''}
            <div class="card-body">
                <div class="card-platform">
                    <span class="dot"></span>
                    ${r.platform || 'recipe'}
                </div>
                <button class="card-cart-btn ${cart.includes(r.id) ? 'in-cart' : ''}" data-add-id="${r.id}" title="${cart.includes(r.id) ? 'In shopping list' : 'Add to shopping list'}">
                    ${cart.includes(r.id) ? '✓' : '+'}
                </button>
                <button class="recipe-card-plan-btn" data-plan-id="${r.id}" data-plan-title="${escapeAttr(r.title)}" title="Add to meal plan">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="14" height="14"><rect x="3" y="4" width="18" height="18" rx="3"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="8" y1="2" x2="8" y2="5"/><line x1="16" y1="2" x2="16" y2="5"/><line x1="12" y1="13" x2="12" y2="17"/><line x1="10" y1="15" x2="14" y2="15"/></svg>
                </button>
            <h3 class="card-title">${escapeHtml(r.title)}${isDrinkRecipe(r) ? ` <span class="drink-badge">${getDrinkEmoji(r)}</span>` : ''}</h3>
            ${r.creator ? `<p class="card-creator">by ${escapeHtml(r.creator)}</p>` : ''}
            ${r.tags.length ? `
                <div class="card-tags">
                    ${r.tags.slice(0, 3).map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}
                </div>
            ` : ''}
            <div class="card-meta">
                ${r.total_time ? `
                    <span class="meta-item">
                        <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clip-rule="evenodd"/></svg>
                        ${escapeHtml(r.total_time)}
                    </span>
                ` : ''}
                ${r.servings ? `
                    <span class="meta-item">
                        <svg viewBox="0 0 20 20" fill="currentColor"><path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z"/></svg>
                        ${r.servings === '1' && r.serving_size ? escapeHtml(r.serving_size) : `Makes ${escapeHtml(r.servings)}${r.serving_size ? ` (${escapeHtml(r.serving_size)} each)` : ''}`}
                    </span>
                ` : ''}
                <span class="meta-item">
                    <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clip-rule="evenodd"/></svg>
                    ${r.ingredients.length} ingredients
                </span>
                ${r.created_at ? `
                    <span class="meta-item meta-date">
                        <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M6 2a1 1 0 00-1 1v1H4a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-1V3a1 1 0 10-2 0v1H7V3a1 1 0 00-1-1zm0 5a1 1 0 000 2h8a1 1 0 100-2H6z" clip-rule="evenodd"/></svg>
                        ${formatDateAdded(r.created_at)}
                    </span>
                ` : ''}
                ${r.rating_avg ? `
                    <span class="meta-item meta-rating">
                        <span class="card-star">&#9733;</span>
                        ${r.rating_avg} <span class="rating-count">(${r.rating_count})</span>
                    </span>
                ` : ''}
            </div>
            </div>
        </article>
    `).join('');
}

function renderModal(recipe) {
    // Normalize tags (API returns comma-separated string)
    if (typeof recipe.tags === 'string') {
        recipe.tags = recipe.tags ? recipe.tags.split(',').map(t => t.trim()).filter(Boolean) : [];
    } else if (!Array.isArray(recipe.tags)) {
        recipe.tags = [];
    }
    currentRecipe = recipe;
    originalServings = parseServingsNumber(recipe.servings) || 1;
    currentMultiplier = 1;

    const cart = getCart();
    const inCart = cart.includes(recipe.id);

    modalContent.innerHTML = `
        <div class="modal-actions">
            <button class="action-btn share-btn" id="shareCardBtn" title="Share recipe">
                <svg viewBox="0 0 20 20" fill="currentColor"><path d="M12.586 4.586a2 2 0 112.828 2.828l-3 3a2 2 0 01-2.828 0 1 1 0 00-1.414 1.414 4 4 0 005.656 0l3-3a4 4 0 00-5.656-5.656l-1.5 1.5a1 1 0 101.414 1.414l1.5-1.5zm-5 5a2 2 0 012.828 0 1 1 0 001.414-1.414 4 4 0 00-5.656 0l-3 3a4 4 0 105.656 5.656l1.5-1.5a1 1 0 10-1.414-1.414l-1.5 1.5a2 2 0 11-2.828-2.828l3-3z"/></svg>
            </button>
            <button class="action-btn edit-btn" id="editRecipeBtn" title="Edit recipe">
                <svg viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
            </button>
            <button class="action-btn delete-btn" id="deleteRecipeBtn" title="Delete recipe">
                <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
            </button>
        </div>
        ${recipe.platform ? `<div class="modal-platform">${escapeHtml(recipe.platform)}</div>` : ''}
        <h2 class="modal-title">${escapeHtml(recipe.title)}</h2>
        <p class="modal-creator">
            ${recipe.creator ? `by <strong>${escapeHtml(recipe.creator)}</strong>` : ''}
            ${recipe.source_url ? ` · <a href="${escapeHtml(recipe.source_url)}" target="_blank" rel="noopener">View original</a>` : ''}
        </p>
        ${recipe.created_at ? `<p class="modal-date-added">${isNewRecipe(recipe) ? '<span class="new-badge-inline">NEW</span> ' : ''}Added ${formatDateAdded(recipe.created_at)}${recipe.added_by ? ` by <strong>${escapeHtml(recipe.added_by)}</strong>` : ''}</p>` : ''}

        <!-- Rating & Reviews Section -->
        <div class="reviews-section" id="reviewsSection">
            <div class="reviews-summary" id="reviewsSummary">
                <div class="reviews-loading">Loading reviews…</div>
            </div>
        </div>

        ${(recipe.servings || recipe.serving_size || recipe.prep_time || recipe.cook_time || recipe.total_time) ? `
            <div class="modal-meta-bar">
                ${recipe.servings ? `
                    <div class="modal-meta-item">
                        <span class="meta-label">Servings</span>
                        <span class="meta-value">
                            ${parseServingsNumber(recipe.servings) && recipeIsScalable(recipe) ? `
                                <span class="scaler-widget">
                                    <button class="scaler-btn" id="scalerMinus">−</button>
                                    <span class="scaler-value" id="scalerValue">${parseServingsNumber(recipe.servings)}</span>
                                    <button class="scaler-btn" id="scalerPlus">+</button>
                                </span>
                            ` : `${escapeHtml(recipe.servings)}`}
                        </span>
                    </div>
                ` : ''}
                ${recipe.serving_size ? `
                    <div class="modal-meta-item">
                        <span class="meta-label">Serving Size</span>
                        <span class="meta-value">${escapeHtml(recipe.serving_size)}</span>
                    </div>
                ` : ''}
                ${recipe.prep_time ? `
                    <div class="modal-meta-item">
                        <span class="meta-label">Prep</span>
                        <span class="meta-value">${escapeHtml(recipe.prep_time)}</span>
                    </div>
                ` : ''}
                ${recipe.cook_time ? `
                    <div class="modal-meta-item">
                        <span class="meta-label">Cook</span>
                        <span class="meta-value">${escapeHtml(recipe.cook_time)}</span>
                    </div>
                ` : ''}
                ${recipe.total_time ? `
                    <div class="modal-meta-item">
                        <span class="meta-label">Total</span>
                        <span class="meta-value">${escapeHtml(recipe.total_time)}</span>
                    </div>
                ` : ''}
            </div>
        ` : ''}

        ${recipe.macros && /\d/.test(recipe.macros) ? `<div class="modal-macros">📊 ${escapeHtml(recipe.macros)}</div>` : ''}

        <div class="section-title-row">
            <h4 class="section-title">Ingredients</h4>
            <button class="unit-toggle-btn" id="unitToggleBtn" data-units="${unitSystem}" onclick="cycleUnits()" title="Convert units">
                <svg class="unit-toggle-scale" viewBox="0 0 24 20" width="18" height="15">
                    <line x1="12" y1="2" x2="12" y2="18" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                    <line x1="6" y1="18" x2="18" y2="18" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                    <g class="scale-beam">
                        <line x1="3" y1="6" x2="21" y2="6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                        <path d="M1 6 L3 12 L5 12 Z" fill="currentColor" opacity="0.6"/>
                        <path d="M19 6 L21 12 L23 12 Z" fill="currentColor" opacity="0.6"/>
                    </g>
                </svg>
                <span class="unit-toggle-label">${unitSystem === 'imperial' ? 'oz · lb · cups' : unitSystem === 'metric' ? 'g · ml · °C' : 'As Written'}</span>
            </button>
        </div>
        <ul class="ingredients-list" id="ingredientsList">
            ${recipe.ingredients.map(ing => {
                const recipeSystem = detectIngredientSystem(recipe.ingredients);
                const targetSystem = getTargetSystem(recipeSystem);
                const text = getConvertedIngredient(ing, 1, targetSystem);
                return `<li>${escapeHtml(text)}</li>`;
            }).join('')}
        </ul>

        <h4 class="section-title">Instructions</h4>
        <ol class="instructions-list">
            ${recipe.instructions.map(step => `<li>${escapeHtml(step)}</li>`).join('')}
        </ol>

        ${recipe.tips ? `<div class="modal-tips">${escapeHtml(recipe.tips)}</div>` : ''}

        <div class="modal-action-bar">
            <button class="btn-add-list ${inCart ? 'in-cart' : ''}" id="addToListBtn">
                ${inCart ? '✓ In Shopping List' : '🛒 Add to Shopping List'}
            </button>
            ${recipe.instructions.length > 0 ? `
                <button class="btn-cook" id="startCookModeBtn">${isDrinkRecipe(recipe) ? '🍸 Start Mixing' : '👨‍🍳 Start Cooking'}</button>
            ` : ''}
        </div>
    `;

    // Bind action buttons
    document.getElementById('deleteRecipeBtn').addEventListener('click', () => deleteRecipe(recipe));
    document.getElementById('editRecipeBtn').addEventListener('click', () => openEditMode(recipe));

    // Bind add to list button
    const addBtn = document.getElementById('addToListBtn');
    addBtn.addEventListener('click', () => {
        const cart = getCart();
        if (cart.includes(recipe.id)) {
            removeFromCart(recipe.id);
            addBtn.textContent = '🛒 Add to Shopping List';
            addBtn.classList.remove('in-cart');
        } else {
            addToCartWithScaledIngredients(recipe);
            addBtn.textContent = '✓ In Shopping List';
            addBtn.classList.add('in-cart');
        }
        renderGrid(allRecipes);
    });

    // Bind scaler buttons
    const scalerMinus = document.getElementById('scalerMinus');
    const scalerPlus = document.getElementById('scalerPlus');
    if (scalerMinus && scalerPlus) {
        scalerMinus.addEventListener('click', () => updateScale(-1));
        scalerPlus.addEventListener('click', () => updateScale(1));
    }

    // Bind cook mode button
    const cookBtn = document.getElementById('startCookModeBtn');
    if (cookBtn) {
        cookBtn.addEventListener('click', () => openCookMode(recipe));
    }

    // Bind share button
    document.getElementById('shareCardBtn').addEventListener('click', () => shareRecipe(recipe));

    // Load reviews
    loadReviews(recipe.id);
}

function addToCartWithScaledIngredients(recipe) {
    addToCart(recipe.id);
    // Store scaled ingredients if multiplier != 1
    if (currentMultiplier !== 1) {
        const scaledKey = `reel-cookbook-scaled-${recipe.id}`;
        const scaledIngredients = recipe.ingredients.map(ing => scaleIngredient(ingText(ing), currentMultiplier));
        localStorage.setItem(scaledKey, JSON.stringify(scaledIngredients));
    } else {
        // Remove any old scaled data
        localStorage.removeItem(`reel-cookbook-scaled-${recipe.id}`);
    }
}

function updateScale(delta) {
    const currentIdx = MULTIPLIER_STEPS.indexOf(currentMultiplier);
    const newIdx = currentIdx + delta;
    if (newIdx < 0 || newIdx >= MULTIPLIER_STEPS.length) return;
    currentMultiplier = MULTIPLIER_STEPS[newIdx];

    const scalerValue = document.getElementById('scalerValue');
    if (scalerValue) {
        const scaled = Math.round(originalServings * currentMultiplier * 10) / 10;
        scalerValue.textContent = String(scaled);
    }

    // Update ingredients display
    const ingredientsList = document.getElementById('ingredientsList');
    if (ingredientsList && currentRecipe) {
        const recipeSystem = detectIngredientSystem(currentRecipe.ingredients);
        const targetSystem = getTargetSystem(recipeSystem);
        ingredientsList.innerHTML = currentRecipe.ingredients.map(ing => {
            const text = getConvertedIngredient(ing, currentMultiplier, targetSystem);
            return `<li>${escapeHtml(text)}</li>`;
        }).join('');
    }
}

function renderEditModal(recipe) {
    modalContent.innerHTML = `
        <h2 class="modal-title" style="margin-bottom: 20px;">Edit Recipe</h2>
        <form id="editForm" class="edit-form">
            <label class="edit-label">Title</label>
            <input type="text" class="edit-input" id="edit-title" value="${escapeAttr(recipe.title)}">

            <div class="edit-row">
                <div class="edit-col">
                    <label class="edit-label">Creator</label>
                    <input type="text" class="edit-input" id="edit-creator" value="${escapeAttr(recipe.creator)}">
                </div>
                <div class="edit-col">
                    <label class="edit-label">Platform</label>
                    <input type="text" class="edit-input" id="edit-platform" value="${escapeAttr(recipe.platform)}">
                </div>
            </div>

            <div class="edit-row">
                <div class="edit-col">
                    <label class="edit-label">Makes (portions)</label>
                    <input type="text" class="edit-input" id="edit-servings" value="${escapeAttr(recipe.servings)}" placeholder="e.g. 4">
                </div>
                <div class="edit-col">
                    <label class="edit-label">Portion Description</label>
                    <input type="text" class="edit-input" id="edit-serving_size" value="${escapeAttr(recipe.serving_size || '')}" placeholder="e.g. 1 bowl, 1 sandwich">
                </div>
            </div>

            <div class="edit-row">
                <div class="edit-col">
                    <label class="edit-label">Prep Time</label>
                    <input type="text" class="edit-input" id="edit-prep_time" value="${escapeAttr(recipe.prep_time)}">
                </div>
                <div class="edit-col">
                    <label class="edit-label">Cook Time</label>
                    <input type="text" class="edit-input" id="edit-cook_time" value="${escapeAttr(recipe.cook_time)}">
                </div>
            </div>

            <label class="edit-label">Source URL</label>
            <input type="text" class="edit-input" id="edit-source_url" value="${escapeAttr(recipe.source_url)}">

            <label class="edit-label">Added by</label>
            <div class="edit-added-by-wrapper" id="editAddedByWrapper">
                <input type="text" class="edit-input" id="edit-added_by" value="${escapeAttr(recipe.added_by || '')}" autocomplete="off" placeholder="Type or select a user…">
                <div class="edit-added-by-dropdown" id="editAddedByDropdown"></div>
            </div>

            <label class="edit-label">Ingredients <span class="edit-hint">(one per line)</span></label>
            <textarea class="edit-textarea" id="edit-ingredients" rows="8">${recipe.ingredients.map(ing => ingText(ing)).join('\n')}</textarea>

            <label class="edit-label">Instructions <span class="edit-hint">(one step per line)</span></label>
            <textarea class="edit-textarea" id="edit-instructions" rows="8">${recipe.instructions.join('\n')}</textarea>

            <label class="edit-label">Tips</label>
            <textarea class="edit-textarea" id="edit-tips" rows="3">${recipe.tips || ''}</textarea>

            <label class="edit-label">Macros</label>
            <input type="text" class="edit-input" id="edit-macros" value="${escapeAttr(recipe.macros)}">

            <label class="edit-label">Tags <span class="edit-hint">(comma-separated)</span></label>
            <input type="text" class="edit-input" id="edit-tags" value="${recipe.tags.join(', ')}">

            <div class="edit-buttons">
                <button type="button" class="btn btn-cancel" id="cancelEditBtn">Cancel</button>
                <button type="submit" class="btn btn-save">Save Changes</button>
            </div>
        </form>
    `;

    document.getElementById('cancelEditBtn').addEventListener('click', () => confirmDiscardEdit(recipe));
    document.getElementById('editForm').addEventListener('submit', (e) => {
        e.preventDefault();
        isEditMode = false;
        saveRecipe(recipe.id);
    });

    // "Added by" user dropdown
    initAddedByDropdown();
}

async function initAddedByDropdown() {
    const input = document.getElementById('edit-added_by');
    const dropdown = document.getElementById('editAddedByDropdown');
    if (!input || !dropdown) return;

    let users = [];
    try {
        const res = await fetch('/api/users', { credentials: 'same-origin' });
        users = await res.json();
    } catch (e) { return; }

    function renderDropdown(filter = '') {
        const filtered = filter
            ? users.filter(u => u.display_name.toLowerCase().includes(filter.toLowerCase()))
            : users;

        if (filtered.length === 0) {
            dropdown.classList.remove('open');
            return;
        }

        dropdown.innerHTML = filtered.map(u => `
            <div class="added-by-option" data-name="${escapeAttr(u.display_name)}">
                <img class="added-by-option-avatar" src="${u.avatar_url || `https://cdn.discordapp.com/embed/avatars/${parseInt(u.username, 36) % 5}.png`}" alt="" />
                <span class="added-by-option-name">${escapeHtml(u.display_name)}</span>
                <span class="added-by-option-username">@${escapeHtml(u.username)}</span>
            </div>
        `).join('');
        dropdown.classList.add('open');
    }

    input.addEventListener('focus', () => renderDropdown(input.value));
    input.addEventListener('input', () => renderDropdown(input.value));

    dropdown.addEventListener('click', (e) => {
        const option = e.target.closest('.added-by-option');
        if (!option) return;
        input.value = option.dataset.name;
        dropdown.classList.remove('open');
    });

    // Close dropdown on outside click
    document.addEventListener('click', (e) => {
        if (!input.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.classList.remove('open');
        }
    });
}

// ─── Shopping List Panel ─────────────────────────
async function renderShoppingPanel() {
    const cart = getCart();
    const checked = getChecked();

    if (cart.length === 0) {
        shoppingContent.innerHTML = `
            <div class="shopping-header">
                <h2>Shopping List</h2>
            </div>
            <div class="shopping-empty">
                <p>Your shopping list is empty</p>
                <span>Tap + on recipe cards to add ingredients</span>
            </div>
        `;
        return;
    }

    // Fetch all recipes in cart
    const recipes = [];
    for (const id of cart) {
        try {
            const res = await fetch(`/api/recipes/${id}`);
            if (res.ok) {
                const recipe = await res.json();
                recipes.push(recipe);
            }
        } catch (e) {
            // Skip missing recipes
        }
    }

    // Build combined ingredient list
    const allIngredients = [];
    for (const recipe of recipes) {
        // Check if we have scaled ingredients stored
        const scaledKey = `reel-cookbook-scaled-${recipe.id}`;
        const scaledData = localStorage.getItem(scaledKey);
        const ingredients = scaledData ? JSON.parse(scaledData) : recipe.ingredients;

        for (const ing of ingredients) {
            // Handle both formats: string (old) and {text, section} (new)
            if (typeof ing === 'string') {
                allIngredients.push({ text: ing, section: 'other', recipeTitle: recipe.title });
            } else if (ing && typeof ing === 'object') {
                allIngredients.push({ text: ing.text || String(ing), section: ing.section || 'other', recipeTitle: recipe.title });
            }
        }
    }

    // Deduplicate by normalizing ingredient names
    const merged = mergeIngredients(allIngredients);

    // Group by section
    const sectionOrder = ['produce', 'meat', 'seafood', 'dairy', 'bakery', 'pantry', 'spices', 'frozen', 'condiments', 'beverages', 'bar', 'other'];
    const sectionLabels = {
        produce: '🥬 Produce',
        meat: '🥩 Meat',
        seafood: '🐟 Seafood',
        dairy: '🧀 Dairy & Eggs',
        bakery: '🍞 Bakery',
        pantry: '🫙 Pantry',
        spices: '🧂 Spices & Seasonings',
        frozen: '❄️ Frozen',
        condiments: '🫗 Oils & Condiments',
        beverages: '🥤 Beverages',
        bar: '🍸 Bar',
        other: '🧊 Other'
    };

    const grouped = {};
    for (const item of merged) {
        const sec = item.section || 'other';
        if (!grouped[sec]) grouped[sec] = [];
        grouped[sec].push(item);
    }

    // Build grouped HTML
    const targetSystem = unitSystem === 'original' ? null : unitSystem;
    let listHtml = '';
    let itemIdx = 0;
    for (const sec of sectionOrder) {
        if (!grouped[sec] || grouped[sec].length === 0) continue;
        listHtml += `<li class="shopping-section-header">${sectionLabels[sec] || sec}</li>`;
        for (const item of grouped[sec]) {
            const displayText = targetSystem ? convertIngredientLine(item.text, targetSystem) : item.text;
            listHtml += `
                <li class="shopping-item ${checked.includes(item.text) ? 'checked' : ''}">
                    <input type="checkbox" ${checked.includes(item.text) ? 'checked' : ''} data-ing-idx="${itemIdx}" data-ing-text="${escapeAttr(item.text)}">
                    <span class="shopping-item-text">${escapeHtml(displayText)}</span>
                </li>`;
            itemIdx++;
        }
    }

    const unitLabels = { original: 'As Written', imperial: 'oz · lb · cups', metric: 'g · ml · °C' };

    shoppingContent.innerHTML = `
        <div class="shopping-header">
            <h2>Shopping List</h2>
            <div class="shopping-actions">
                <button id="clearCheckedBtn">Clear Checked</button>
                <button id="clearAllBtn" class="empty-cart-btn" title="Empty cart">
                    <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
                </button>
            </div>
        </div>
        <button class="unit-toggle-btn shopping-unit-toggle" id="shoppingUnitToggle" data-units="${unitSystem}" title="Convert units">
            <svg class="unit-toggle-scale" viewBox="0 0 24 20" width="18" height="15">
                <line x1="12" y1="2" x2="12" y2="18" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                <line x1="6" y1="18" x2="18" y2="18" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                <g class="scale-beam">
                    <line x1="3" y1="6" x2="21" y2="6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                    <path d="M1 6 L3 12 L5 12 Z" fill="currentColor" opacity="0.6"/>
                    <path d="M19 6 L21 12 L23 12 Z" fill="currentColor" opacity="0.6"/>
                </g>
            </svg>
            <span class="unit-toggle-label">${unitLabels[unitSystem]}</span>
        </button>
        <div class="shopping-recipes">
            ${recipes.map(r => `
                <span class="shopping-recipe-chip">
                    ${escapeHtml(r.title)}
                    <button data-remove-id="${r.id}" title="Remove">×</button>
                </span>
            `).join('')}
        </div>
        <ul class="shopping-list" id="shoppingListItems">
            ${listHtml}
        </ul>
        <button class="shopping-copy-btn" id="copyListBtn">Copy to Clipboard</button>
    `;

    // Bind remove buttons
    shoppingContent.querySelectorAll('[data-remove-id]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const id = btn.dataset.removeId;
            removeFromCart(id);
            localStorage.removeItem(`reel-cookbook-scaled-${id}`);
            renderShoppingPanel();
            renderGrid(allRecipes);
        });
    });

    // Bind checkboxes
    shoppingContent.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        cb.addEventListener('change', (e) => {
            const text = cb.dataset.ingText;
            let checked = getChecked();
            if (cb.checked) {
                if (!checked.includes(text)) checked.push(text);
                cb.closest('.shopping-item').classList.add('checked');
            } else {
                checked = checked.filter(t => t !== text);
                cb.closest('.shopping-item').classList.remove('checked');
            }
            setChecked(checked);
        });
    });

    // Bind clear buttons
    document.getElementById('clearCheckedBtn').addEventListener('click', () => {
        const checked = getChecked();
        setChecked([]);
        renderShoppingPanel();
    });

    // Unit toggle in shopping panel
    document.getElementById('shoppingUnitToggle').addEventListener('click', () => {
        cycleUnits();
        renderShoppingPanel();
    });

    document.getElementById('clearAllBtn').addEventListener('click', () => {
        if (!confirm('Clear entire shopping list?')) return;
        const cart = getCart();
        cart.forEach(id => localStorage.removeItem(`reel-cookbook-scaled-${id}`));
        setCart([]);
        setChecked([]);
        renderShoppingPanel();
        renderGrid(allRecipes);
    });

    // Copy to clipboard
    document.getElementById('copyListBtn').addEventListener('click', () => {
        const cart = getCart();
        const checked = getChecked();
        const recipes = allRecipes.filter(r => cart.includes(parseInt(r.id)));
        const allIngredients = [];
        recipes.forEach(r => {
            const scaledKey = `reel-cookbook-scaled-${r.id}`;
            const scaledData = localStorage.getItem(scaledKey);
            let ingredients = [];
            if (scaledData) {
                try { ingredients = JSON.parse(scaledData); } catch(e) {}
            } else if (Array.isArray(r.ingredients)) {
                ingredients = r.ingredients;
            } else if (typeof r.ingredients === 'string') {
                ingredients = r.ingredients.split('\n').filter(Boolean);
            }
            ingredients.forEach(ing => {
                if (typeof ing === 'string') {
                    allIngredients.push({ text: ing.trim(), section: 'other', recipeId: r.id });
                } else if (ing && typeof ing === 'object') {
                    allIngredients.push({ text: (ing.text || String(ing)).trim(), section: ing.section || 'other', recipeId: r.id });
                }
            });
        });
        const merged = mergeIngredients(allIngredients);

        // Build formatted text grouped by section
        const sectionOrder = ['produce', 'meat', 'seafood', 'dairy', 'bakery', 'pantry', 'spices', 'frozen', 'condiments', 'beverages', 'bar', 'other'];
        const sectionLabels = {
            produce: '🥬 Produce', meat: '🥩 Meat', seafood: '🐟 Seafood',
            dairy: '🧀 Dairy & Eggs', bakery: '🍞 Bakery', pantry: '🫙 Pantry',
            spices: '🧂 Spices', frozen: '❄️ Frozen', condiments: '🫗 Condiments',
            beverages: '🥤 Beverages', bar: '🍸 Bar', other: '🧊 Other'
        };

        const grouped = {};
        for (const item of merged) {
            const sec = item.section || 'other';
            if (!grouped[sec]) grouped[sec] = [];
            grouped[sec].push(item);
        }

        let text = '🛒 Shopping List\n';
        text += '━━━━━━━━━━━━━━━━\n';

        for (const sec of sectionOrder) {
            if (!grouped[sec] || grouped[sec].length === 0) continue;
            const unchecked = grouped[sec].filter(item => !checked.includes(item.text));
            const checkedItems = grouped[sec].filter(item => checked.includes(item.text));
            if (unchecked.length === 0 && checkedItems.length === 0) continue;

            text += `\n${sectionLabels[sec] || sec}\n`;
            unchecked.forEach(item => { text += `☐ ${item.text}\n`; });
            checkedItems.forEach(item => { text += `☑ ${item.text}\n`; });
        }
        text += `\n— from Reel Cookbook`;

        // Copy to clipboard — must handle HTTP (no secure context)
        copyToClipboard(text).then(success => {
            const btn = document.getElementById('copyListBtn');
            if (success) {
                btn.textContent = '✓ Copied!';
                btn.classList.add('copied');
                setTimeout(() => { btn.textContent = 'Copy to Clipboard'; btn.classList.remove('copied'); }, 2000);
            } else {
                // Last resort: show a modal with selectable text
                showCopyFallback(text);
            }
        });
    });
}

// Robust clipboard copy that works on HTTP
async function copyToClipboard(text) {
    // Method 1: Clipboard API (HTTPS only, or localhost)
    if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch(e) { /* falls through */ }
    }

    // Method 2: execCommand with textarea (works on most browsers over HTTP)
    try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        ta.style.top = '-9999px';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        ta.setSelectionRange(0, text.length);
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        if (ok) return true;
    } catch(e) { /* falls through */ }

    // Method 3: ClipboardItem with Blob (some browsers prefer this)
    if (window.ClipboardItem) {
        try {
            const blob = new Blob([text], { type: 'text/plain' });
            await navigator.clipboard.write([new ClipboardItem({ 'text/plain': blob })]);
            return true;
        } catch(e) { /* falls through */ }
    }

    return false;
}

// Fallback: show text in a selectable modal so user can Cmd+C
function showCopyFallback(text) {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;backdrop-filter:blur(8px);';
    const modal = document.createElement('div');
    modal.style.cssText = 'background:rgba(30,30,40,0.95);border-radius:16px;padding:24px;max-width:400px;width:90%;max-height:70vh;display:flex;flex-direction:column;gap:12px;border:1px solid rgba(255,255,255,0.15);';
    modal.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <span style="color:#fff;font-weight:600;font-size:16px;">Select All & Copy</span>
            <button id="copyFallbackClose" style="background:none;border:none;color:#fff;font-size:20px;cursor:pointer;">✕</button>
        </div>
        <textarea id="copyFallbackText" readonly style="width:100%;height:250px;background:rgba(0,0,0,0.4);color:#e0e0e0;border:1px solid rgba(255,255,255,0.1);border-radius:10px;padding:12px;font-size:14px;font-family:-apple-system,system-ui,sans-serif;resize:none;line-height:1.5;">${text.replace(/</g,'&lt;')}</textarea>
        <button id="copyFallbackSelect" style="background:linear-gradient(135deg,#007aff,#5856d6);color:#fff;border:none;border-radius:10px;padding:12px;font-size:15px;font-weight:500;cursor:pointer;">Select All (then ⌘C)</button>
    `;
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    document.getElementById('copyFallbackClose').onclick = () => overlay.remove();
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    document.getElementById('copyFallbackSelect').onclick = () => {
        const ta = document.getElementById('copyFallbackText');
        ta.focus();
        ta.select();
        ta.setSelectionRange(0, ta.value.length);
    };
    // Auto-select on open
    setTimeout(() => {
        const ta = document.getElementById('copyFallbackText');
        ta.focus();
        ta.select();
    }, 100);
}

function mergeIngredients(allIngredients) {
    // Simple deduplication: normalize ingredient text for matching
    const seen = new Map();
    const result = [];

    for (const item of allIngredients) {
        const normalized = item.text.toLowerCase().trim();
        // Try to extract the "name" part (after quantity and unit)
        const nameMatch = normalized.match(/^[\d\s\/\.]*(?:cups?|tbsp|tsp|oz|lbs?|pounds?|kg|g|ml|l|liters?|quarts?|pints?|gallons?|cloves?|cans?|packages?|bunche?s?|heads?|stalks?|slices?|pieces?)?\s*(.+)$/);
        const key = nameMatch ? nameMatch[1].trim() : normalized;

        if (seen.has(key)) {
            // Already have this ingredient - try to combine quantities
            const existing = seen.get(key);
            const existingParsed = parseIngredientQuantity(existing.text);
            const newParsed = parseIngredientQuantity(item.text);

            if (existingParsed.quantity !== null && newParsed.quantity !== null && existingParsed.rest === newParsed.rest) {
                const combined = existingParsed.quantity + newParsed.quantity;
                existing.text = `${formatNumber(combined)} ${existingParsed.rest}`;
            }
            // If we can't combine, just skip the duplicate
        } else {
            const entry = { text: item.text, section: item.section || 'other', recipeTitle: item.recipeTitle };
            seen.set(key, entry);
            result.push(entry);
        }
    }

    return result;
}

// ─── Cook Mode ───────────────────────────────────
let cookModeStep = 0;
let cookModeRecipe = null;

function openCookMode(recipe) {
    cookModeRecipe = recipe;
    cookModeStep = 0;
    cookModeEl.classList.add('active');
    document.body.style.overflow = 'hidden';
    renderCookModeStep();
    requestWakeLock();
}

function closeCookMode() {
    cookModeEl.classList.remove('active');
    document.body.style.overflow = '';
    cookModeRecipe = null;
    releaseWakeLock();
}

function renderCookModeStep() {
    if (!cookModeRecipe) return;
    const steps = cookModeRecipe.instructions;
    const total = steps.length;
    const current = cookModeStep;

    cookModeContent.innerHTML = `
        <div class="cook-header">
            <h2 class="cook-title">${escapeHtml(cookModeRecipe.title)}</h2>
            <button class="cook-exit" id="cookModeExit">✕ Exit</button>
        </div>
        <details class="cook-ingredients-toggle">
            <summary>📋 Ingredients</summary>
            <div class="cook-ingredients-list">
                ${cookModeRecipe.ingredients.map(ing => `<span>${escapeHtml(ingText(ing))}</span>`).join('')}
            </div>
        </details>
        <div class="cook-step-area">
            <div class="cook-step-counter">Step ${current + 1} of ${total}</div>
            <div class="cook-step-text">${escapeHtml(steps[current])}</div>
            ${current === total - 1 ? `<div class="cook-done"><p>🎉</p><span>You're done! Enjoy your meal!</span></div>` : ''}
        </div>
        <div class="cook-nav">
            <button class="cook-nav-btn" id="cookPrev" ${current === 0 ? 'disabled' : ''}>← Previous</button>
            <button class="cook-nav-btn primary" id="cookNext" ${current === total - 1 ? 'disabled' : ''}>Next →</button>
        </div>
    `;

    document.getElementById('cookModeExit').addEventListener('click', closeCookMode);
    document.getElementById('cookPrev').addEventListener('click', () => {
        if (cookModeStep > 0) {
            cookModeStep--;
            renderCookModeStep();
        }
    });
    document.getElementById('cookNext').addEventListener('click', () => {
        if (cookModeStep < steps.length - 1) {
            cookModeStep++;
            renderCookModeStep();
        }
    });
}

async function requestWakeLock() {
    try {
        if ('wakeLock' in navigator) {
            wakeLockSentinel = await navigator.wakeLock.request('screen');
            wakeLockSentinel.addEventListener('release', () => {
                wakeLockSentinel = null;
            });
        }
    } catch (err) {
        // Wake Lock not supported or failed - silently continue
        wakeLockSentinel = null;
    }
}

function releaseWakeLock() {
    if (wakeLockSentinel) {
        wakeLockSentinel.release();
        wakeLockSentinel = null;
    }
}

// ─── Actions ────────────────────────────────────
async function deleteRecipe(recipe) {
    // Use custom confirm dialog instead of window.confirm (blocked on some mobile browsers)
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'mp-confirm-overlay';
        overlay.style.zIndex = '10001';
        overlay.innerHTML = `
            <div class="mp-confirm-dialog">
                <div class="mp-confirm-title">Delete Recipe?</div>
                <div class="mp-confirm-message">Delete <strong>${escapeHtml(recipe.title)}</strong>? This can't be undone.</div>
                <div class="mp-confirm-actions">
                    <button class="mp-confirm-btn cancel" id="delConfirmCancel">Cancel</button>
                    <button class="mp-confirm-btn remove" id="delConfirmDelete">Delete</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        document.getElementById('delConfirmCancel').addEventListener('click', () => {
            overlay.remove();
            resolve();
        });
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) { overlay.remove(); resolve(); }
        });

        document.getElementById('delConfirmDelete').addEventListener('click', async () => {
            overlay.remove();
            try {
                const res = await fetch(`/api/recipes/${recipe.id}`, {
                    method: 'DELETE',
                    credentials: 'same-origin',
                    headers: { 'Accept': 'application/json' }
                });
                if (res.ok) {
                    removeFromCart(recipe.id);
                    localStorage.removeItem(`reel-cookbook-scaled-${recipe.id}`);
                    doCloseModal();
                    await loadRecipes(searchInput.value);
                    await loadCategories();
                    if (window.refreshTodaysMeals) window.refreshTodaysMeals();
                    if (window.refreshMealPlanBadge) window.refreshMealPlanBadge();
                } else {
                    const data = await res.json().catch(() => ({}));
                    if (data.login_url) {
                        window.location.href = data.login_url;
                    } else {
                        alert('Failed to delete recipe.');
                    }
                }
            } catch (err) {
                console.error('Delete failed:', err);
                alert('Failed to delete recipe.');
            }
            resolve();
        });
    });
}

function getEditFormSnapshot() {
    const fields = ['edit-title','edit-creator','edit-platform','edit-servings',
        'edit-serving_size','edit-prep_time','edit-cook_time','edit-source_url','edit-added_by',
        'edit-ingredients','edit-instructions','edit-tips','edit-macros','edit-tags'];
    const snap = {};
    fields.forEach(id => {
        const el = document.getElementById(id);
        if (el) snap[id] = el.value;
    });
    return JSON.stringify(snap);
}

function hasEditFormChanged() {
    if (!editFormSnapshot) return false;
    return getEditFormSnapshot() !== editFormSnapshot;
}

function openEditMode(recipe) {
    isEditMode = true;
    renderEditModal(recipe);
    // Snapshot after a tick so any async population (added_by dropdown) settles
    requestAnimationFrame(() => {
        editFormSnapshot = getEditFormSnapshot();
    });
}

async function saveRecipe(id) {
    const ingredients = document.getElementById('edit-ingredients').value
        .split('\n').map(s => s.trim()).filter(Boolean);
    const instructions = document.getElementById('edit-instructions').value
        .split('\n').map(s => s.trim()).filter(Boolean);
    const tags = document.getElementById('edit-tags').value
        .split(',').map(s => s.trim()).filter(Boolean);

    const payload = {
        title: document.getElementById('edit-title').value.trim(),
        creator: document.getElementById('edit-creator').value.trim(),
        platform: document.getElementById('edit-platform').value.trim(),
        source_url: document.getElementById('edit-source_url').value.trim(),
        added_by: document.getElementById('edit-added_by').value.trim(),
        servings: document.getElementById('edit-servings').value.trim(),
        serving_size: document.getElementById('edit-serving_size').value.trim(),
        prep_time: document.getElementById('edit-prep_time').value.trim(),
        cook_time: document.getElementById('edit-cook_time').value.trim(),
        total_time: '',
        ingredients,
        instructions,
        tips: document.getElementById('edit-tips').value.trim(),
        macros: document.getElementById('edit-macros').value.trim(),
        tags,
    };

    // Compute total_time
    if (payload.prep_time && payload.cook_time) {
        payload.total_time = `${payload.prep_time} + ${payload.cook_time}`;
    } else {
        payload.total_time = payload.prep_time || payload.cook_time || '';
    }

    const res = await fetch(`/api/recipes/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });

    if (res.ok) {
        // Reload and show updated recipe
        const updated = await fetch(`/api/recipes/${id}`);
        const recipe = await updated.json();
        renderModal(recipe);
        await loadRecipes(searchInput.value);
        await loadCategories();
    } else {
        alert('Failed to save changes.');
    }
}

// ─── Share Recipe (like YouTube — share a link) ─
async function shareRecipe(recipe) {
    const slug = recipe.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    const url = `${location.origin}/recipe/${recipe.id}/${slug}`;
    const title = recipe.title;

    // Native share sheet (works on iOS Safari, Android Chrome, even over HTTP)
    if (navigator.share) {
        try {
            await navigator.share({ title, url });
            return;
        } catch (e) {
            if (e.name === 'AbortError') return; // User cancelled
        }
    }

    // Desktop fallback: copy link to clipboard
    const ok = await copyToClipboard(url);
    if (ok) {
        const btn = document.getElementById('shareCardBtn');
        const origHTML = btn.innerHTML;
        btn.innerHTML = '<svg viewBox="0 0 20 20" fill="currentColor"><path d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"/></svg>';
        btn.title = 'Link copied!';
        setTimeout(() => { btn.innerHTML = origHTML; btn.title = 'Share recipe'; }, 1500);
    } else {
        showCopyFallback(url);
    }
}


// ─── Spotlight (macOS-style convert overlay) ─────
function openSpotlight() {
    spotlightOverlay.classList.add('active');
    document.body.style.overflow = 'hidden';
    const input = document.getElementById('convertInput');
    // Clear previous state
    input.value = '';
    const status = document.getElementById('convertStatus');
    status.style.display = 'none';
    document.getElementById('convertSpinner').style.display = 'none';
    document.getElementById('spotlightHint').style.display = '';
    setTimeout(() => input.focus(), 80);
}

function closeSpotlight() {
    spotlightOverlay.classList.remove('active');
    document.body.style.overflow = '';
}

function toggleSpotlight() {
    if (spotlightOverlay.classList.contains('active')) {
        closeSpotlight();
    } else {
        openSpotlight();
    }
}

// ─── Event Handlers ─────────────────────────────
// ─── Convert URL ─────────────────────────────────
async function convertReel() {
    const input = document.getElementById('convertInput');
    const spinner = document.getElementById('convertSpinner');
    const hint = document.getElementById('spotlightHint');
    const status = document.getElementById('convertStatus');
    const url = input.value.trim();

    if (!url) return;

    // Validate URL
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
        status.textContent = 'Paste a valid URL (https://...)';
        status.className = 'spotlight-status error';
        status.style.display = 'block';
        return;
    }

    // Show loading state
    hint.style.display = 'none';
    spinner.style.display = 'inline-block';
    input.disabled = true;
    status.textContent = 'Queueing conversion…';
    status.className = 'spotlight-status';
    status.style.display = 'block';

    try {
        const resp = await fetch('/api/convert', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });

        const data = await resp.json();

        if (resp.status === 409) {
            status.textContent = `Already in your cookbook`;
            status.className = 'spotlight-status error';
        } else if (!resp.ok && resp.status !== 202) {
            const errMsg = data.error || 'Conversion failed';
            if (errMsg.includes('age-restricted')) {
                status.innerHTML = 'Age-restricted content. <a href="https://github.com/Brenttime/reel-to-recipe/blob/master/docs/instagram-age-restricted.md" target="_blank" rel="noopener" style="color:inherit;text-decoration:underline;">How to fix →</a>';
            } else {
                status.textContent = errMsg;
            }
            status.className = 'spotlight-status error';
        } else if (data.status === 'queued') {
            status.textContent = 'Converting… you can close this and keep browsing';
            status.className = 'spotlight-status';
            input.value = '';
            // Start tracking this job
            trackConversionJob(data.job_id);
        }
    } catch (err) {
        status.textContent = 'Network error — is the server running?';
        status.className = 'spotlight-status error';
    } finally {
        input.disabled = false;
        spinner.style.display = 'none';
        hint.style.display = '';
    }
}

// ─── Conversion Queue Tracking ────────────────────
const activeJobs = new Set();

function trackConversionJob(jobId) {
    activeJobs.add(jobId);
    updateQueueBar();
    pollJob(jobId);
}

async function pollJob(jobId) {
    const poll = async () => {
        try {
            const res = await fetch(`/api/convert/${jobId}`);
            const data = await res.json();

            if (data.status === 'done') {
                activeJobs.delete(jobId);
                updateQueueBar();
                // Auto-add recipe to gallery
                if (data.recipe) {
                    showRecipeAdded(data.recipe);
                    await loadRecipes(searchInput.value);
                    await loadCategories();
                }
                return; // stop polling
            } else if (data.status === 'error') {
                activeJobs.delete(jobId);
                updateQueueBar();
                showQueueError(data.error || 'Conversion failed');
                return; // stop polling
            }

            // Show step detail if available
            if (data.step_detail) {
                updateQueueBarDetail(data.step_detail);
            }

            // Still processing — poll again in 2s
            setTimeout(poll, 2000);
        } catch (e) {
            // Network blip — retry
            setTimeout(poll, 3000);
        }
    };
    poll();
}

function updateQueueBar() {
    const bar = document.getElementById('convertQueueBar');
    const text = document.getElementById('queueBarText');
    const count = activeJobs.size;

    if (count === 0) {
        bar.style.display = 'none';
    } else {
        bar.style.display = 'flex';
        text.textContent = count === 1 ? 'Converting…' : `Converting ${count}…`;
    }
}

function updateQueueBarDetail(detail) {
    const bar = document.getElementById('convertQueueBar');
    const text = document.getElementById('queueBarText');
    if (activeJobs.size > 0) {
        bar.style.display = 'flex';
        text.textContent = detail;
    }
}

function showRecipeAdded(recipe) {
    const bar = document.getElementById('convertQueueBar');
    const text = document.getElementById('queueBarText');

    bar.style.display = 'flex';
    bar.classList.add('queue-bar-success');
    // Truncate title for compact island display
    const title = recipe.title.length > 18 ? recipe.title.slice(0, 16) + '…' : recipe.title;
    text.textContent = `✓ ${title}`;

    setTimeout(() => {
        bar.classList.remove('queue-bar-success');
        if (activeJobs.size === 0) {
            bar.style.display = 'none';
        } else {
            updateQueueBar();
        }
    }, 4000);
}

function showQueueError(error) {
    const bar = document.getElementById('convertQueueBar');
    const text = document.getElementById('queueBarText');

    bar.style.display = 'flex';
    bar.classList.add('queue-bar-error');

    // Check for age-restricted error with doc link
    if (error && error.includes('age-restricted')) {
        text.innerHTML = `✗ Age-restricted`;
    } else {
        // Truncate error for compact island display
        const msg = error && error.length > 20 ? error.slice(0, 18) + '…' : (error || 'Failed');
        text.textContent = `✗ ${msg}`;
    }

    setTimeout(() => {
        bar.classList.remove('queue-bar-error');
        if (activeJobs.size === 0) {
            bar.style.display = 'none';
        } else {
            updateQueueBar();
        }
    }, 8000);
}

function setupListeners() {
    // Search
    searchInput.addEventListener('input', (e) => {
        const val = e.target.value;
        clearBtn.style.display = val ? 'flex' : 'none';

        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => loadRecipes(val), 300);
    });

    clearBtn.addEventListener('click', () => {
        searchInput.value = '';
        clearBtn.style.display = 'none';
        loadRecipes();
        document.querySelectorAll('.chip.active').forEach(c => c.classList.remove('active'));
    });

    // Spotlight convert overlay
    addReelBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleSpotlight();
    });
    spotlightOverlay.addEventListener('click', (e) => {
        // Close only when clicking the dark overlay, not the bar itself
        if (e.target === spotlightOverlay) closeSpotlight();
    });
    document.getElementById('convertInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') convertReel();
    });

    // Filter chips (categories + Added by Me)
    filterChips.addEventListener('click', (e) => {
        const chip = e.target.closest('.chip');
        if (!chip) return;

        const isActive = chip.classList.contains('active');
        document.querySelectorAll('.chip.active').forEach(c => c.classList.remove('active'));

        if (isActive) {
            searchInput.value = '';
            loadRecipes();
        } else {
            chip.classList.add('active');

            // Special "Added by Me" filter — client-side
            if (chip.dataset.filter === 'added-by-me') {
                const myName = currentUser?.display_name || currentUser?.username || '';
                if (myName) {
                    const filtered = allRecipes.filter(r => r.added_by === myName);
                    renderGrid(filtered);
                    searchInput.value = '';
                    clearBtn.style.display = 'none';
                }
            } else if (chip.dataset.filter === 'top-rated') {
                const filtered = allRecipes.filter(r => r.rating_avg >= 4);
                renderGrid(filtered);
                searchInput.value = '';
                clearBtn.style.display = 'none';
            } else {
                const category = chip.dataset.category;
                searchInput.value = category;
                clearBtn.style.display = 'flex';
                loadRecipes(category);
            }
        }
    });

    // iOS: empty touchstart keeps hit-test tree warm after PWA resume
    recipeGrid.addEventListener('touchstart', () => {}, { passive: true });

    // Card click → modal (but not if clicking the add button)
    recipeGrid.addEventListener('click', async (e) => {
        // Handle add to cart button on card
        const addBtn = e.target.closest('.card-cart-btn');
        if (addBtn) {
            e.stopPropagation();
            const id = Number(addBtn.dataset.addId);
            const cart = getCart();
            if (cart.includes(id)) {
                removeFromCart(id);
                localStorage.removeItem(`reel-cookbook-scaled-${id}`);
            } else {
                addToCart(id);
            }
            renderGrid(allRecipes);
            return;
        }

        // Handle add to meal plan button (opens radial menu)
        const planBtn = e.target.closest('.recipe-card-plan-btn');
        if (planBtn) {
            e.stopPropagation();
            const id = Number(planBtn.dataset.planId);
            const title = planBtn.dataset.planTitle;
            if (window.openMealPlanRadial) {
                window.openMealPlanRadial(id, title);
            }
            return;
        }

        const card = e.target.closest('.recipe-card');
        if (!card) return;

        const id = card.dataset.id;
        const res = await fetch(`/api/recipes/${id}`);
        const recipe = await res.json();
        renderModal(recipe);
        openModal();
    });

    // Close modal
    modalClose.addEventListener('click', closeModal);
    modalOverlay.addEventListener('click', (e) => {
        if (e.target === modalOverlay) closeModal();
    });

    // Shopping panel
    cartToggle.addEventListener('click', async () => {
        await renderShoppingPanel();
        openShoppingPanel();
    });

    shoppingClose.addEventListener('click', closeShoppingPanel);
    shoppingOverlay.addEventListener('click', (e) => {
        if (e.target === shoppingOverlay) closeShoppingPanel();
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (spotlightOverlay.classList.contains('active')) {
                closeSpotlight();
            } else if (cookModeEl.classList.contains('active')) {
                closeCookMode();
            } else if (shoppingOverlay.classList.contains('active')) {
                closeShoppingPanel();
            } else {
                closeModal();
            }
        }
        // Arrow keys in cook mode
        if (cookModeEl.classList.contains('active')) {
            if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                e.preventDefault();
                if (cookModeRecipe && cookModeStep < cookModeRecipe.instructions.length - 1) {
                    cookModeStep++;
                    renderCookModeStep();
                }
            } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                e.preventDefault();
                if (cookModeStep > 0) {
                    cookModeStep--;
                    renderCookModeStep();
                }
            }
        }
    });

    // Re-acquire wake lock when page becomes visible again
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && cookModeEl.classList.contains('active')) {
            requestWakeLock();
        }
    });
}

let scrollLockPos = 0;
let _modalTouchHandler = null;

function openModal() {
    modalOverlay.classList.add('active');
    // Reset modal scroll to top for fresh recipe view
    const modal = modalOverlay.querySelector('.glass-modal');
    if (modal) modal.scrollTop = 0;
    // Prevent background scroll: block touchmove on overlay except inside .glass-modal
    _modalTouchHandler = function(e) {
        const modal = modalOverlay.querySelector('.glass-modal');
        if (!modal || !modal.contains(e.target)) {
            e.preventDefault();
        }
    };
    modalOverlay.addEventListener('touchmove', _modalTouchHandler, { passive: false });
    document.body.style.overflow = 'hidden';
    // Update URL to permalink
    if (currentRecipe) {
        const slug = currentRecipe.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
        history.pushState({ recipeId: currentRecipe.id }, '', `/recipe/${currentRecipe.id}/${slug}`);
    }
}

function closeModal() {
    if (isEditMode && hasEditFormChanged()) {
        showEditDiscardDialog();
        return;
    }
    doCloseModal();
}

function doCloseModal() {
    isEditMode = false;
    editFormSnapshot = null;
    modalOverlay.classList.remove('active');
    // Reset modal scroll so next open starts fresh
    const modal = modalOverlay.querySelector('.glass-modal');
    if (modal) modal.scrollTop = 0;
    // Remove touch scroll lock
    if (_modalTouchHandler) {
        modalOverlay.removeEventListener('touchmove', _modalTouchHandler);
        _modalTouchHandler = null;
    }
    document.body.style.overflow = '';
    currentRecipe = null;
    // Remove discard dialog if present
    const dialog = document.getElementById('discardEditDialog');
    if (dialog) dialog.remove();
    // Restore gallery URL
    if (location.pathname.startsWith('/recipe/')) {
        history.pushState({}, '', '/');
    }
}

function confirmDiscardEdit(recipe) {
    if (hasEditFormChanged()) {
        showEditDiscardDialog(() => {
            isEditMode = false;
            editFormSnapshot = null;
            renderModal(recipe);
        });
    } else {
        isEditMode = false;
        editFormSnapshot = null;
        renderModal(recipe);
    }
}

function showEditDiscardDialog(onDiscard) {
    // Remove existing dialog if present
    let existing = document.getElementById('discardEditDialog');
    if (existing) existing.remove();

    const dialog = document.createElement('div');
    dialog.id = 'discardEditDialog';
    dialog.className = 'discard-dialog-overlay';
    dialog.innerHTML = `
        <div class="discard-dialog">
            <h3 class="discard-dialog-title">Unsaved Changes</h3>
            <p class="discard-dialog-message">You have unsaved changes. Would you like to save or discard them?</p>
            <div class="discard-dialog-actions">
                <button class="discard-dialog-btn discard-btn" id="discardChangesBtn">Discard</button>
                <button class="discard-dialog-btn save-btn" id="saveChangesBtn">Save Changes</button>
            </div>
        </div>
    `;
    document.body.appendChild(dialog);

    // Animate in
    requestAnimationFrame(() => dialog.classList.add('active'));

    document.getElementById('discardChangesBtn').addEventListener('click', () => {
        dialog.remove();
        if (onDiscard) {
            onDiscard();
        } else {
            doCloseModal();
        }
    });

    document.getElementById('saveChangesBtn').addEventListener('click', () => {
        dialog.remove();
        // Trigger the form submit
        const form = document.getElementById('editForm');
        if (form) {
            isEditMode = false;
            form.dispatchEvent(new Event('submit', { cancelable: true }));
        }
    });

    // Close dialog on overlay click
    dialog.addEventListener('click', (e) => {
        if (e.target === dialog) dialog.remove();
    });
}

var _shoppingTouchHandler = null;

function openShoppingPanel() {
    shoppingOverlay.classList.add('active');
    document.body.style.overflow = 'hidden';
    // Prevent background scroll on iOS: block touchmove outside panel
    _shoppingTouchHandler = function(e) {
        const panel = shoppingOverlay.querySelector('.glass-modal');
        if (!panel || !panel.contains(e.target)) {
            e.preventDefault();
        }
    };
    shoppingOverlay.addEventListener('touchmove', _shoppingTouchHandler, { passive: false });
}

function closeShoppingPanel() {
    shoppingOverlay.classList.remove('active');
    document.body.style.overflow = '';
    if (_shoppingTouchHandler) {
        shoppingOverlay.removeEventListener('touchmove', _shoppingTouchHandler);
        _shoppingTouchHandler = null;
    }
}

// ─── Util ───────────────────────────────────────
function escapeHtml(text) {
    if (!text) return '';
    const el = document.createElement('span');
    el.textContent = text;
    return el.innerHTML;
}

function escapeAttr(text) {
    if (!text) return '';
    return text.replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ─── Reviews & Ratings ──────────────────────────
let currentUser = null;

async function fetchCurrentUser() {
    if (currentUser !== null) return currentUser;
    try {
        const res = await fetch('/auth/me', { credentials: 'same-origin' });
        const data = await res.json();
        currentUser = data.authenticated ? data : false;
    } catch (e) {
        currentUser = false;
    }
    return currentUser;
}

async function loadReviews(recipeId) {
    const section = document.getElementById('reviewsSection');
    if (!section) return;

    // Preserve scroll position of the modal to prevent scroll jump after re-render
    const modal = section.closest('.glass-modal');
    const scrollTop = modal ? modal.scrollTop : 0;

    try {
        const res = await fetch(`/api/recipes/${recipeId}/reviews`, {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' }
        });
        if (!res.ok) {
            console.warn('Reviews fetch failed:', res.status);
            section.innerHTML = '';
            return;
        }
        const data = await res.json();
        const user = await fetchCurrentUser();
        renderReviewsSection(section, data, recipeId, user);

        // Restore scroll position after DOM update
        if (modal) {
            requestAnimationFrame(() => {
                modal.scrollTop = scrollTop;
            });
        }
    } catch (e) {
        console.error('Reviews error:', e);
        section.innerHTML = '';
    }
}

function renderStars(rating, interactive = false, size = 'sm') {
    const stars = [];
    for (let i = 1; i <= 5; i++) {
        const filled = i <= rating;
        const cls = `review-star ${size} ${filled ? 'filled' : ''} ${interactive ? 'interactive' : ''}`;
        stars.push(`<span class="${cls}" data-star="${i}">&#9733;</span>`);
    }
    return stars.join('');
}

function renderReviewsSection(container, data, recipeId, user) {
    const { average, count, reviews, my_review } = data;

    container.innerHTML = `
        <div class="reviews-header" id="reviewsHeader">
            <div class="reviews-score">
                <span class="reviews-avg">${count > 0 ? average : '\u2014'}</span>
                <div class="reviews-stars">${count > 0 ? renderStars(Math.round(average), false, 'md') : renderStars(0, false, 'md')}</div>
                <span class="reviews-count">${count} ${count === 1 ? 'review' : 'reviews'}</span>
            </div>
            <svg class="reviews-chevron" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
        </div>
        <div class="reviews-panel" id="reviewsPanel">
            ${user ? renderMyReviewForm(my_review, recipeId) : ''}
            <div class="reviews-list" id="reviewsList">
                ${reviews.length > 0 ? reviews.map(r => renderReviewItem(r, user)).join('') : '<p class="reviews-empty">No reviews yet. Be the first!</p>'}
            </div>
        </div>
    `;

    const header = container.querySelector('#reviewsHeader');
    const panel = container.querySelector('#reviewsPanel');
    header.addEventListener('click', () => {
        panel.classList.toggle('open');
        header.classList.toggle('expanded');
    });

    if (user) {
        bindReviewForm(container, recipeId, my_review);
    }
}

function renderMyReviewForm(myReview, recipeId) {
    const existingRating = myReview ? myReview.rating : 0;
    const existingComment = myReview ? myReview.comment : '';

    return `
        <div class="review-form-container">
            <h4 class="review-form-title">${myReview ? 'Your Review' : 'Rate this recipe'}</h4>
            <div class="review-form-stars" id="reviewFormStars">
                ${renderStars(existingRating, true, 'lg')}
            </div>
            <textarea class="review-comment-input" id="reviewCommentInput" placeholder="Add a comment (optional)\u2026" rows="2">${existingComment ? escapeHtml(existingComment) : ''}</textarea>
            <div class="review-form-actions">
                <button class="review-submit-btn" id="reviewSubmitBtn">${myReview ? 'Update' : 'Submit'}</button>
                ${myReview ? '<button class="review-delete-btn" id="reviewDeleteBtn">Remove</button>' : ''}
            </div>
        </div>
    `;
}

function renderReviewItem(review, user) {
    const avatarUrl = review.user.avatar_url || 'https://cdn.discordapp.com/embed/avatars/0.png';
    const displayName = review.user.display_name || review.user.username;
    const isOwn = user && user.id === review.user.id;
    const date = new Date(review.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

    return `
        <div class="review-item ${isOwn ? 'own-review' : ''}">
            <div class="review-item-header">
                <img class="review-avatar" src="${avatarUrl}" alt="${escapeHtml(displayName)}" />
                <div class="review-item-meta">
                    <span class="review-username">${escapeHtml(displayName)}</span>
                    <span class="review-date">${date}</span>
                </div>
                <div class="review-item-stars">${renderStars(review.rating, false, 'sm')}</div>
            </div>
            ${review.comment ? `<p class="review-comment">${escapeHtml(review.comment)}</p>` : ''}
        </div>
    `;
}

function bindReviewForm(container, recipeId, myReview) {
    let selectedRating = myReview ? myReview.rating : 0;
    const starsContainer = container.querySelector('#reviewFormStars');
    const stars = starsContainer.querySelectorAll('.review-star');
    const submitBtn = container.querySelector('#reviewSubmitBtn');
    const deleteBtn = container.querySelector('#reviewDeleteBtn');
    const commentInput = container.querySelector('#reviewCommentInput');

    stars.forEach(star => {
        star.addEventListener('mouseenter', () => {
            const val = parseInt(star.dataset.star);
            stars.forEach(s => {
                s.classList.toggle('hovered', parseInt(s.dataset.star) <= val);
            });
        });

        star.addEventListener('mouseleave', () => {
            stars.forEach(s => s.classList.remove('hovered'));
        });

        star.addEventListener('click', () => {
            selectedRating = parseInt(star.dataset.star);
            stars.forEach(s => {
                s.classList.toggle('filled', parseInt(s.dataset.star) <= selectedRating);
            });
        });
    });

    submitBtn.addEventListener('click', async () => {
        if (selectedRating === 0) {
            submitBtn.textContent = 'Tap a star first';
            setTimeout(() => { submitBtn.textContent = myReview ? 'Update' : 'Submit'; }, 1500);
            return;
        }
        submitBtn.disabled = true;
        submitBtn.textContent = 'Saving\u2026';
        try {
            const res = await fetch(`/api/recipes/${recipeId}/reviews`, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                body: JSON.stringify({ rating: selectedRating, comment: commentInput.value.trim() })
            });
            if (res.ok) {
                await loadReviews(recipeId);
            } else {
                submitBtn.textContent = 'Error';
                setTimeout(() => { submitBtn.textContent = myReview ? 'Update' : 'Submit'; }, 1500);
            }
        } catch (e) {
            submitBtn.textContent = 'Error';
        }
        submitBtn.disabled = false;
    });

    if (deleteBtn) {
        deleteBtn.addEventListener('click', async () => {
            deleteBtn.disabled = true;
            try {
                await fetch(`/api/recipes/${recipeId}/reviews`, {
                    method: 'DELETE',
                    credentials: 'same-origin',
                    headers: { 'Accept': 'application/json' }
                });
                await loadReviews(recipeId);
            } catch (e) { /* ignore */ }
        });
    }
}

// ─── Expose openRecipeById for meal-plan.js ─────
window.openRecipeById = async function(id) {
    try {
        const res = await fetch(`/api/recipes/${id}`);
        if (!res.ok) return;
        const recipe = await res.json();
        renderModal(recipe);
        openModal();
    } catch (e) { /* recipe not found */ }
};

// ─── Boot ───────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
