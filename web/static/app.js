/**
 * Reel Cookbook — Frontend Logic
 * Features: Search, Filter, Recipe Modal, Edit, Delete,
 *           Shopping List, Serving Scaler, Cook Mode
 */

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

let allRecipes = [];
let currentRecipe = null;
let debounceTimer = null;
let currentScale = 1;
let originalServings = 1;
let wakeLockSentinel = null;

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
const FRACTION_MAP = {
    '1/8': 0.125, '1/4': 0.25, '1/3': 0.333333, '3/8': 0.375,
    '1/2': 0.5, '5/8': 0.625, '2/3': 0.666667, '3/4': 0.75, '7/8': 0.875
};

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

function parseServingsNumber(servingsStr) {
    if (!servingsStr) return null;
    // Try to get first number from string like "4", "2-4", "8 tacos", "4 servings"
    const match = servingsStr.match(/(\d+)/);
    return match ? parseInt(match[1]) : null;
}

// ─── Init ───────────────────────────────────────
async function init() {
    await loadRecipes();
    await loadCreators();
    setupListeners();
    updateCartBadge();
}

// ─── Data Loading ───────────────────────────────
async function loadRecipes(query = '') {
    const url = query ? `/api/recipes?q=${encodeURIComponent(query)}` : '/api/recipes';
    const res = await fetch(url);
    allRecipes = await res.json();
    renderGrid(allRecipes);
}

async function loadCreators() {
    const res = await fetch('/api/creators');
    const creators = await res.json();
    renderChips(creators);
}

// ─── Rendering ──────────────────────────────────
function renderGrid(recipes) {
    if (recipes.length === 0) {
        recipeGrid.innerHTML = '';
        emptyState.style.display = 'block';
        return;
    }

    emptyState.style.display = 'none';
    const cart = getCart();
    recipeGrid.innerHTML = recipes.map((r, i) => `
        <article class="recipe-card" data-id="${r.id}" style="animation-delay: ${i * 0.05}s">
            <div class="card-platform">
                <span class="dot"></span>
                ${r.platform || 'recipe'}
            </div>
            <button class="card-add-btn ${cart.includes(r.id) ? 'in-cart' : ''}" data-add-id="${r.id}" title="${cart.includes(r.id) ? 'In shopping list' : 'Add to shopping list'}">
                ${cart.includes(r.id) ? '✓' : '+'}
            </button>
            <h3 class="card-title">${escapeHtml(r.title)}</h3>
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
                        ${escapeHtml(r.servings)}
                    </span>
                ` : ''}
                <span class="meta-item">
                    <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clip-rule="evenodd"/></svg>
                    ${r.ingredients.length} ingredients
                </span>
            </div>
        </article>
    `).join('');
}

function renderChips(creators) {
    if (creators.length === 0) return;
    filterChips.innerHTML = creators.map(c => `
        <button class="chip" data-creator="${escapeAttr(c)}">${escapeHtml(c)}</button>
    `).join('');
}

function renderModal(recipe) {
    currentRecipe = recipe;
    originalServings = parseServingsNumber(recipe.servings) || 1;
    currentScale = 1;

    const cart = getCart();
    const inCart = cart.includes(recipe.id);

    modalContent.innerHTML = `
        <div class="modal-actions">
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

        ${(recipe.servings || recipe.prep_time || recipe.cook_time || recipe.total_time) ? `
            <div class="modal-meta-bar">
                ${recipe.servings ? `
                    <div class="modal-meta-item">
                        <strong>Servings:</strong>
                        ${parseServingsNumber(recipe.servings) ? `
                            <span class="scaler-widget">
                                <button class="scaler-btn" id="scalerMinus">−</button>
                                <span class="scaler-value" id="scalerValue">${parseServingsNumber(recipe.servings)}</span>
                                <button class="scaler-btn" id="scalerPlus">+</button>
                            </span>
                        ` : `${escapeHtml(recipe.servings)}`}
                    </div>
                ` : ''}
                ${recipe.prep_time ? `<div class="modal-meta-item"><strong>Prep:</strong> ${escapeHtml(recipe.prep_time)}</div>` : ''}
                ${recipe.cook_time ? `<div class="modal-meta-item"><strong>Cook:</strong> ${escapeHtml(recipe.cook_time)}</div>` : ''}
                ${recipe.total_time ? `<div class="modal-meta-item"><strong>Total:</strong> ${escapeHtml(recipe.total_time)}</div>` : ''}
            </div>
        ` : ''}

        <h4 class="section-title">Ingredients</h4>
        <ul class="ingredients-list" id="ingredientsList">
            ${recipe.ingredients.map(ing => `<li>${escapeHtml(ing)}</li>`).join('')}
        </ul>

        <button class="btn btn-add-list" id="addToListBtn">
            ${inCart ? '✓ In Shopping List' : '🛒 Add to Shopping List'}
        </button>

        <h4 class="section-title">Instructions</h4>
        <ol class="instructions-list">
            ${recipe.instructions.map(step => `<li>${escapeHtml(step)}</li>`).join('')}
        </ol>

        ${recipe.tips ? `<div class="modal-tips">${escapeHtml(recipe.tips)}</div>` : ''}
        ${recipe.macros ? `<div class="modal-macros">📊 ${escapeHtml(recipe.macros)}</div>` : ''}

        ${recipe.instructions.length > 0 ? `
            <button class="btn btn-cook-mode" id="startCookModeBtn">👨‍🍳 Start Cooking</button>
        ` : ''}
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
        } else {
            addToCartWithScaledIngredients(recipe);
            addBtn.textContent = '✓ In Shopping List';
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
}

function addToCartWithScaledIngredients(recipe) {
    addToCart(recipe.id);
    // Store scaled ingredients if scale != 1
    if (currentScale !== 1) {
        const scaledKey = `reel-cookbook-scaled-${recipe.id}`;
        const ratio = currentScale / originalServings;
        const scaledIngredients = recipe.ingredients.map(ing => scaleIngredient(ing, ratio));
        localStorage.setItem(scaledKey, JSON.stringify(scaledIngredients));
    } else {
        // Remove any old scaled data
        localStorage.removeItem(`reel-cookbook-scaled-${recipe.id}`);
    }
}

function updateScale(delta) {
    const newVal = currentScale + delta;
    if (newVal < 1) return;
    currentScale = newVal;

    const scalerValue = document.getElementById('scalerValue');
    if (scalerValue) scalerValue.textContent = currentScale;

    // Update ingredients display
    const ratio = currentScale / originalServings;
    const ingredientsList = document.getElementById('ingredientsList');
    if (ingredientsList && currentRecipe) {
        ingredientsList.innerHTML = currentRecipe.ingredients.map(ing => {
            const scaled = ratio === 1 ? ing : scaleIngredient(ing, ratio);
            return `<li>${escapeHtml(scaled)}</li>`;
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
                    <label class="edit-label">Servings</label>
                    <input type="text" class="edit-input" id="edit-servings" value="${escapeAttr(recipe.servings)}">
                </div>
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

            <label class="edit-label">Ingredients <span class="edit-hint">(one per line)</span></label>
            <textarea class="edit-textarea" id="edit-ingredients" rows="8">${recipe.ingredients.join('\n')}</textarea>

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

    document.getElementById('cancelEditBtn').addEventListener('click', () => renderModal(recipe));
    document.getElementById('editForm').addEventListener('submit', (e) => {
        e.preventDefault();
        saveRecipe(recipe.id);
    });
}

// ─── Shopping List Panel ─────────────────────────
async function renderShoppingPanel() {
    const cart = getCart();
    const checked = getChecked();

    if (cart.length === 0) {
        shoppingContent.innerHTML = `
            <h2 class="shopping-title">🛒 Shopping List</h2>
            <div class="shopping-empty">
                <p>Your shopping list is empty</p>
                <span>Add recipes by clicking the + button on recipe cards</span>
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
            allIngredients.push({ text: ing, recipeTitle: recipe.title });
        }
    }

    // Deduplicate by normalizing ingredient names
    const merged = mergeIngredients(allIngredients);

    shoppingContent.innerHTML = `
        <h2 class="shopping-title">🛒 Shopping List</h2>
        <div class="shopping-recipes">
            <h4>Recipes (${recipes.length})</h4>
            ${recipes.map(r => `
                <div class="shopping-recipe-item">
                    <span>${escapeHtml(r.title)}</span>
                    <button class="shopping-remove-btn" data-remove-id="${r.id}" title="Remove">×</button>
                </div>
            `).join('')}
        </div>
        <div class="shopping-ingredients">
            <h4>Ingredients (${merged.length})</h4>
            <div class="shopping-list" id="shoppingListItems">
                ${merged.map((item, idx) => `
                    <label class="shopping-item ${checked.includes(item.text) ? 'checked' : ''}">
                        <input type="checkbox" ${checked.includes(item.text) ? 'checked' : ''} data-ing-idx="${idx}" data-ing-text="${escapeAttr(item.text)}">
                        <span class="shopping-item-text">${escapeHtml(item.text)}</span>
                    </label>
                `).join('')}
            </div>
        </div>
        <div class="shopping-actions">
            <button class="btn btn-clear-checked" id="clearCheckedBtn">Clear Checked</button>
            <button class="btn btn-clear-all" id="clearAllBtn">Clear All</button>
        </div>
    `;

    // Bind remove buttons
    shoppingContent.querySelectorAll('.shopping-remove-btn').forEach(btn => {
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

    document.getElementById('clearAllBtn').addEventListener('click', () => {
        if (!confirm('Clear entire shopping list?')) return;
        const cart = getCart();
        cart.forEach(id => localStorage.removeItem(`reel-cookbook-scaled-${id}`));
        setCart([]);
        setChecked([]);
        renderShoppingPanel();
        renderGrid(allRecipes);
    });
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
            const entry = { text: item.text, recipeTitle: item.recipeTitle };
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
        <button class="cook-exit-btn" id="cookModeExit">✕ Exit</button>
        <div class="cook-header">
            <h2 class="cook-title">${escapeHtml(cookModeRecipe.title)}</h2>
            <div class="cook-ingredients-ref">
                <details>
                    <summary>📋 Ingredients</summary>
                    <ul>
                        ${cookModeRecipe.ingredients.map(ing => `<li>${escapeHtml(ing)}</li>`).join('')}
                    </ul>
                </details>
            </div>
        </div>
        <div class="cook-step-counter">Step ${current + 1} of ${total}</div>
        <div class="cook-step-text">${escapeHtml(steps[current])}</div>
        <div class="cook-nav">
            <button class="cook-nav-btn" id="cookPrev" ${current === 0 ? 'disabled' : ''}>← Previous</button>
            <button class="cook-nav-btn" id="cookNext" ${current === total - 1 ? 'disabled' : ''}>Next →</button>
        </div>
        ${current === total - 1 ? `<div class="cook-done">🎉 You're done! Enjoy your meal!</div>` : ''}
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
    if (!confirm(`Delete "${recipe.title}"? This can't be undone.`)) return;

    const res = await fetch(`/api/recipes/${recipe.id}`, { method: 'DELETE' });
    if (res.ok) {
        // Also remove from cart if present
        removeFromCart(recipe.id);
        localStorage.removeItem(`reel-cookbook-scaled-${recipe.id}`);
        closeModal();
        await loadRecipes(searchInput.value);
        await loadCreators();
    } else {
        alert('Failed to delete recipe.');
    }
}

function openEditMode(recipe) {
    renderEditModal(recipe);
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
        servings: document.getElementById('edit-servings').value.trim(),
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
        await loadCreators();
    } else {
        alert('Failed to save changes.');
    }
}

// ─── Event Handlers ─────────────────────────────
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

    // Filter chips
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
            const creator = chip.dataset.creator;
            searchInput.value = creator;
            clearBtn.style.display = 'flex';
            loadRecipes(creator);
        }
    });

    // Card click → modal (but not if clicking the add button)
    recipeGrid.addEventListener('click', async (e) => {
        // Handle add to cart button on card
        const addBtn = e.target.closest('.card-add-btn');
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
    cartToggle.addEventListener('click', () => {
        renderShoppingPanel();
        openShoppingPanel();
    });

    shoppingClose.addEventListener('click', closeShoppingPanel);
    shoppingOverlay.addEventListener('click', (e) => {
        if (e.target === shoppingOverlay) closeShoppingPanel();
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (cookModeEl.classList.contains('active')) {
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

function openModal() {
    modalOverlay.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    modalOverlay.classList.remove('active');
    document.body.style.overflow = '';
    currentRecipe = null;
}

function openShoppingPanel() {
    shoppingOverlay.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeShoppingPanel() {
    shoppingOverlay.classList.remove('active');
    document.body.style.overflow = '';
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

// ─── Boot ───────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
