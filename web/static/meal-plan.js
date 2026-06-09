// ─── OnlyPans Meal Planner ─────────────────────────────────────
// Zelda BotW/TotK radial weapon wheel for day selection
// Shared calendar kanban view
// Grocery list generation

(function() {
'use strict';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// ─── State ─────────────────────────────────────────
let mpWeekStart = getMonday(new Date());
let radialWeekStart = getMonday(new Date());
let currentPlan = [];
let radialRecipeId = null;
let reassigningEntry = null; // entry being moved to another day

// ─── Date Helpers ──────────────────────────────────
function getMonday(d) {
    const date = new Date(d);
    const day = date.getDay();
    date.setDate(date.getDate() - day + (day === 0 ? -6 : 1));
    date.setHours(0, 0, 0, 0);
    return date;
}

function formatDate(d) { return d.toISOString().split('T')[0]; }
function addDays(d, n) { const r = new Date(d); r.setDate(r.getDate() + n); return r; }
function isToday(d) { return formatDate(d) === formatDate(new Date()); }
function isCurrentWeek(d) { return formatDate(getMonday(d)) === formatDate(getMonday(new Date())); }

function weekLabel(start) {
    const end = addDays(start, 6);
    const s = MONTHS[start.getMonth()];
    const e = MONTHS[end.getMonth()];
    const label = s === e
        ? `${s} ${start.getDate()} – ${end.getDate()}`
        : `${s} ${start.getDate()} – ${e} ${end.getDate()}`;
    return isCurrentWeek(start) ? `${label} (current)` : label;
}

// ─── API ───────────────────────────────────────────
async function fetchPlan(weekStart) {
    try {
        const res = await fetch(`/api/meal-plan?week=${formatDate(weekStart)}`);
        if (res.ok) return (await res.json()).plan;
    } catch (e) { console.warn('Failed to fetch meal plan:', e); }
    return [];
}

async function addToPlan(recipeId, date) {
    try {
        const res = await fetch('/api/meal-plan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ recipe_id: recipeId, date })
        });
        return res.ok;
    } catch (e) { return false; }
}

async function addQuickPlan(text, date, emoji) {
    try {
        const res = await fetch('/api/meal-plan/quick', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, date, emoji })
        });
        return res.ok;
    } catch (e) { return false; }
}

async function fetchRecentQuickPlans() {
    // Client-side only — stored in sessionStorage, expires after 10 minutes
    try {
        const stored = JSON.parse(sessionStorage.getItem('qp_recent') || '[]');
        const now = Date.now();
        const fresh = stored.filter(r => (now - r.ts) < 10 * 60 * 1000);
        // Clean up expired
        if (fresh.length !== stored.length) sessionStorage.setItem('qp_recent', JSON.stringify(fresh));
        return fresh;
    } catch (e) { return []; }
}

function saveRecentQuickPlan(text, emoji) {
    try {
        const stored = JSON.parse(sessionStorage.getItem('qp_recent') || '[]');
        // Deduplicate by text
        const filtered = stored.filter(r => r.text !== text);
        filtered.unshift({ text, emoji, ts: Date.now() });
        // Keep max 8
        sessionStorage.setItem('qp_recent', JSON.stringify(filtered.slice(0, 8)));
    } catch (e) {}
}

async function moveEntry(entryId, newDate) {
    try {
        const res = await fetch(`/api/meal-plan/${entryId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ date: newDate })
        });
        return res.ok;
    } catch (e) { return false; }
}

async function removeEntry(entryId) {
    try {
        const res = await fetch(`/api/meal-plan/${entryId}`, { method: 'DELETE' });
        return res.ok;
    } catch (e) { return false; }
}

// ─── Meal Plan Panel ───────────────────────────────
function openMealPlan() {
    document.getElementById('mealPlanOverlay').classList.add('active');
    document.body.style.overflow = 'hidden';
    refreshMealPlan();
}

function closeMealPlan() {
    document.getElementById('mealPlanOverlay').classList.remove('active');
    document.body.style.overflow = '';
    cancelReassign();
}

async function refreshMealPlan() {
    // Preserve scroll position during re-render
    const panel = document.querySelector('.meal-plan-panel');
    const scrollTop = panel ? panel.scrollTop : 0;
    currentPlan = await fetchPlan(mpWeekStart);
    renderWeekGrid();
    renderWeekTitle();
    updateBadge();
    if (panel) panel.scrollTop = scrollTop;
}

function renderWeekTitle() {
    document.getElementById('mpWeekTitle').textContent = weekLabel(mpWeekStart);
}

function renderWeekGrid() {
    const grid = document.getElementById('mpWeekGrid');
    grid.innerHTML = '';

    for (let i = 0; i < 7; i++) {
        const day = addDays(mpWeekStart, i);
        const dateStr = formatDate(day);
        const dayEntries = currentPlan.filter(e => e.date === dateStr);
        const today = isToday(day);

        const col = document.createElement('div');
        col.className = `mp-day-col${today ? ' is-today' : ''}`;
        col.dataset.date = dateStr;

        col.innerHTML = `
            <div class="mp-day-header">
                <div class="mp-day-name">${DAYS[i]}</div>
                <div class="mp-day-num">${day.getDate()}</div>
            </div>
            <div class="mp-day-meals">
                ${dayEntries.map(entry => {
                    if (entry.type === 'quick_plan') {
                        return `
                            <div class="mp-meal-chip quick-plan" data-entry-id="${entry.id}">
                                <span class="mp-chip-emoji">${escapeHtml(entry.emoji || '🍽️')}</span>
                                <span class="mp-chip-title">${escapeHtml(entry.title)}</span>
                                <button class="mp-chip-remove" data-entry-id="${entry.id}" title="Remove">✕</button>
                            </div>
                        `;
                    }
                    return `
                        <div class="mp-meal-chip" data-entry-id="${entry.id}" data-recipe-id="${entry.recipe_id}">
                            <span class="mp-chip-title">${escapeHtml(entry.title)}</span>
                            <button class="mp-chip-remove" data-entry-id="${entry.id}" title="Remove">✕</button>
                        </div>
                    `;
                }).join('')}
                <button class="mp-day-add" data-date="${dateStr}">+ Quick Plan</button>
            </div>
        `;
        grid.appendChild(col);
    }
}

// ─── Kanban Interactions ───────────────────────────
function startReassign(entryId) {
    reassigningEntry = entryId;
    // Highlight the active chip
    document.querySelectorAll('.mp-meal-chip').forEach(c => {
        if (c.dataset.entryId == entryId) c.classList.add('reassigning');
        else c.classList.remove('reassigning');
    });
    // Highlight target day columns
    document.querySelectorAll('.mp-day-col').forEach(d => d.classList.add('reassign-target'));
}

function cancelReassign() {
    reassigningEntry = null;
    document.querySelectorAll('.mp-meal-chip.reassigning').forEach(c => c.classList.remove('reassigning'));
    document.querySelectorAll('.mp-day-col.reassign-target').forEach(d => d.classList.remove('reassign-target'));
}

async function handleDayColumnClick(dateStr) {
    if (!reassigningEntry) return;
    await moveEntry(reassigningEntry, dateStr);
    cancelReassign();
    await refreshMealPlan();
}

function showRemoveConfirm(entryId, title) {
    const overlay = document.createElement('div');
    overlay.className = 'mp-confirm-overlay';
    overlay.innerHTML = `
        <div class="mp-confirm-dialog">
            <div class="mp-confirm-title">Remove from Plan?</div>
            <div class="mp-confirm-message">Remove <strong>${escapeHtml(title)}</strong> from this week's meal plan?</div>
            <div class="mp-confirm-actions">
                <button class="mp-confirm-btn cancel" id="mpConfirmCancel">Cancel</button>
                <button class="mp-confirm-btn remove" id="mpConfirmRemove">Remove</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);

    document.getElementById('mpConfirmCancel').addEventListener('click', () => overlay.remove());
    document.getElementById('mpConfirmRemove').addEventListener('click', async () => {
        overlay.remove();
        await removeEntry(entryId);
        await refreshMealPlan();
        renderTodaysMeals();
    });
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
}

// ─── Radial Menu (Zelda Weapon Wheel) ──────────────
function openRadialMenu(recipeId, recipeTitle) {
    radialRecipeId = recipeId;
    radialWeekStart = getMonday(new Date());

    document.getElementById('radialRecipeTitle').textContent = recipeTitle;
    document.getElementById('radialOverlay').classList.add('active');
    document.body.style.overflow = 'hidden';
    renderRadialRing();
}

function closeRadialMenu() {
    document.getElementById('radialOverlay').classList.remove('active');
    document.body.style.overflow = '';
    radialRecipeId = null;
}

async function renderRadialRing() {
    const ring = document.getElementById('radialRing');
    const label = document.getElementById('radialWeekLabel');
    label.textContent = weekLabel(radialWeekStart);

    // Fetch plan for this week to show dots on days with meals
    const plan = await fetchPlan(radialWeekStart);

    ring.innerHTML = '';
    // Dynamic radius based on actual menu size
    const menu = document.getElementById('radialMenu');
    const menuSize = menu.offsetWidth || 680;
    const radius = (menuSize / 2) - 56; // distance from center to segment midpoint
    const centerX = menuSize / 2;
    const centerY = menuSize / 2;
    const segW = 88, segH = 72; // match CSS dimensions

    for (let i = 0; i < 7; i++) {
        const day = addDays(radialWeekStart, i);
        const dateStr = formatDate(day);
        const today = isToday(day);
        const hasMeals = plan.some(e => e.date === dateStr);

        // Distribute in a circle starting from top (-90deg)
        const angleDeg = (i / 7) * 360 - 90;
        const angleRad = angleDeg * (Math.PI / 180);
        const x = centerX + radius * Math.cos(angleRad) - (segW / 2);
        const y = centerY + radius * Math.sin(angleRad) - (segH / 2);

        // Rotate so the rounded bottom (inner edge) faces the center
        const rotation = angleDeg + 90; // +90 because bottom of element points down by default

        const dayEl = document.createElement('div');
        dayEl.className = `radial-day${today ? ' is-today' : ''}${hasMeals ? ' has-meals' : ''}`;
        dayEl.style.left = `${x}px`;
        dayEl.style.top = `${y}px`;
        dayEl.dataset.date = dateStr;

        dayEl.innerHTML = `
            <div class="radial-day-inner" style="transform: rotate(${-rotation}deg)">
                <div class="radial-day-name">${DAYS[i]}</div>
                <div class="radial-day-num">${day.getDate()}</div>
            </div>
        `;

        // Staggered entrance animation — Apple ease, include rotation
        dayEl.style.opacity = '0';
        dayEl.style.transform = `rotate(${rotation}deg) scale(0.6)`;
        setTimeout(() => {
            dayEl.style.transition = '0.4s cubic-bezier(0.2, 0, 0, 1)';
            dayEl.style.opacity = '1';
            dayEl.style.transform = `rotate(${rotation}deg) scale(1)`;
        }, 60 + i * 50);

        dayEl.addEventListener('click', async () => {
            // Visual feedback
            dayEl.style.transform = `rotate(${rotation}deg) scale(1.1)`;
            dayEl.style.background = 'var(--accent)';
            dayEl.style.color = 'white';
            dayEl.style.borderColor = 'var(--accent)';

            const success = await addToPlan(radialRecipeId, dateStr);
            if (success) {
                setTimeout(() => {
                    closeRadialMenu();
                    updateBadge();
                    renderTodaysMeals();
                }, 300);
            } else {
                dayEl.style.transform = `rotate(${rotation}deg) scale(1)`;
                dayEl.style.background = '';
                dayEl.style.color = '';
                dayEl.style.borderColor = '';
            }
        });

        ring.appendChild(dayEl);
    }
}

// ─── Grocery List ──────────────────────────────────
async function openGroceryList() {
    document.getElementById('groceryOverlay').classList.add('active');
    const body = document.getElementById('groceryBody');
    const subtitle = document.getElementById('grocerySubtitle');

    body.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-tertiary)">Loading...</div>';

    try {
        const res = await fetch(`/api/meal-plan/grocery-list?week=${formatDate(mpWeekStart)}`);
        const data = await res.json();

        subtitle.textContent = `${data.recipes.length} recipe${data.recipes.length !== 1 ? 's' : ''} this week`;

        if (data.ingredients.length === 0) {
            body.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-secondary)">No meals planned this week</div>';
            return;
        }

        const sections = groupIngredients(data.ingredients);
        body.innerHTML = Object.entries(sections).map(([section, items]) => `
            <div class="grocery-section">
                <div class="grocery-section-title">${section}</div>
                ${items.map(i => `<div class="grocery-item">• ${escapeHtml(i)}</div>`).join('')}
            </div>
        `).join('');
    } catch (e) {
        body.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-secondary)">Failed to load</div>';
    }
}

function closeGroceryList() {
    document.getElementById('groceryOverlay').classList.remove('active');
}

function groupIngredients(ingredients) {
    const cats = {
        '🥬 Produce': /lettuce|tomato|onion|garlic|pepper|cilantro|lime|lemon|avocado|potato|carrot|ginger|scallion|green onion|mushroom|cabbage|spinach|basil|cucumber|jalapeno|broccoli|corn|celery|parsley|thyme|rosemary|zucchini/i,
        '🥩 Meat & Seafood': /chicken|beef|pork|shrimp|fish|salmon|bacon|sausage|ground|steak|lamb|duck|octopus|turkey|crab|lobster/i,
        '🧈 Dairy & Eggs': /milk|cheese|butter|cream|egg|yogurt|sour cream|mozzarella|parmesan|cheddar|burrata|ricotta|goat/i,
        '🍞 Bakery': /bread|bun|tortilla|wrap|pita|naan|baguette|roll|crostini|dough|pizza/i,
        '🫙 Pantry': /oil|vinegar|soy sauce|flour|sugar|salt|pepper|spice|sauce|paste|rice|noodle|pasta|broth|stock|can|mayo|ketchup|mustard|sriracha|honey|sesame|panko|cornstarch|baking|cumin|paprika|oregano/i,
        '🍸 Bar': /vodka|rum|gin|tequila|whiskey|bourbon|soju|liqueur|bitters|syrup|grenadine|soda|tonic|sprite|beer|wine/i,
    };
    const grouped = {};
    const other = [];
    for (const item of ingredients) {
        let matched = false;
        for (const [section, regex] of Object.entries(cats)) {
            if (regex.test(item)) {
                (grouped[section] = grouped[section] || []).push(item);
                matched = true;
                break;
            }
        }
        if (!matched) other.push(item);
    }
    if (other.length) grouped['🧊 Other'] = other;
    return grouped;
}

function copyGroceryList() {
    const body = document.getElementById('groceryBody');
    const lines = [];
    body.querySelectorAll('.grocery-section').forEach(s => {
        lines.push(`\n${s.querySelector('.grocery-section-title').textContent}`);
        s.querySelectorAll('.grocery-item').forEach(i => lines.push(i.textContent));
    });
    navigator.clipboard.writeText(lines.join('\n').trim()).then(() => {
        const btn = document.getElementById('groceryCopyBtn');
        btn.textContent = '✓ Copied!';
        btn.classList.add('copied');
        setTimeout(() => { btn.textContent = 'Copy to Clipboard'; btn.classList.remove('copied'); }, 2000);
    });
}

// ─── Badge ─────────────────────────────────────────
async function updateBadge() {
    const thisWeek = getMonday(new Date());
    const plan = await fetchPlan(thisWeek);
    const badge = document.getElementById('mealPlanBadge');
    if (plan.length > 0) {
        badge.style.display = 'flex';
        badge.textContent = plan.length;
    } else {
        badge.style.display = 'none';
    }
}

// ─── Util ──────────────────────────────────────────
function escapeHtml(str) {
    if (!str) return '';
    const d = document.createElement('span');
    d.textContent = str;
    return d.innerHTML;
}

// ─── Long-Press on Meal Chips (opens recipe detail) ───
let longPressTimer = null;
let longPressTriggered = false;

function initLongPress(container) {
    container.addEventListener('pointerdown', (e) => {
        const chip = e.target.closest('.mp-meal-chip');
        if (!chip || e.target.closest('.mp-chip-remove')) return;

        longPressTriggered = false;
        chip.classList.add('long-pressing');
        chip.setPointerCapture(e.pointerId);

        longPressTimer = setTimeout(async () => {
            longPressTriggered = true;
            chip.classList.remove('long-pressing');

            // Haptic feedback if available
            if (navigator.vibrate) navigator.vibrate(30);

            // Open recipe detail
            const recipeId = chip.dataset.recipeId;
            if (recipeId && window.openRecipeById) {
                window.openRecipeById(Number(recipeId));
            }
        }, 500); // 500ms long-press threshold
    });

    container.addEventListener('pointerup', (e) => {
        clearTimeout(longPressTimer);
        const chip = e.target.closest('.mp-meal-chip');
        if (chip) chip.classList.remove('long-pressing');
    });

    container.addEventListener('pointercancel', (e) => {
        clearTimeout(longPressTimer);
        const chip = e.target.closest('.mp-meal-chip');
        if (chip) chip.classList.remove('long-pressing');
    });

    container.addEventListener('pointermove', (e) => {
        // Cancel if finger moves too much
        if (longPressTimer && e.pointerType === 'touch') {
            // Let small movements pass
        }
    });
}

// ─── Today's Meals Card ─────────────────────────────
const MEAL_EMOJI_MAP = {
    'chicken': '🍗', 'beef': '🥩', 'pork': '🥓', 'seafood': '🦐',
    'fish': '🐟', 'salmon': '🍣', 'shrimp': '🦐', 'pasta': '🍝',
    'pizza': '🍕', 'soup': '🍲', 'salad': '🥗', 'sandwich': '🥪',
    'burger': '🍔', 'taco': '🌮', 'sushi': '🍣', 'rice': '🍚',
    'noodle': '🍜', 'dessert': '🍰', 'cake': '🎂', 'cookie': '🍪',
    'breakfast': '🍳', 'pancake': '🥞', 'waffle': '🧇', 'smoothie': '🥤',
    'cocktail': '🍸', 'drink': '🥤', 'steak': '🥩', 'curry': '🍛',
    'ramen': '🍜', 'bbq': '🔥', 'grill': '🔥', 'bread': '🍞',
    'wing': '🍗', 'fry': '🍟', 'wrap': '🌯', 'bowl': '🥣',
};

function getMealEmoji(title, tags) {
    const searchText = `${title} ${(tags || []).join(' ')}`.toLowerCase();
    for (const [key, emoji] of Object.entries(MEAL_EMOJI_MAP)) {
        if (searchText.includes(key)) return emoji;
    }
    return '🍽️';
}

async function renderTodaysMeals() {
    const card = document.getElementById('todaysMealsCard');
    const list = document.getElementById('tmMealsList');
    const subtitle = document.getElementById('tmSubtitle');

    // Fetch today's plan
    const today = new Date();
    const monday = getMonday(today);
    const plan = await fetchPlan(monday);
    const todayStr = formatDate(today);
    const todayMeals = plan.filter(e => e.date === todayStr);

    if (todayMeals.length === 0) {
        card.style.display = 'none';
        return;
    }

    card.style.display = 'block';
    subtitle.textContent = `${todayMeals.length} meal${todayMeals.length !== 1 ? 's' : ''} planned`;

    list.innerHTML = todayMeals.map(meal => {
        if (meal.type === 'quick_plan') {
            return `
                <div class="tm-meal-row quick-plan-row">
                    <div class="tm-meal-emoji">${meal.emoji || '🍽️'}</div>
                    <div class="tm-meal-info">
                        <div class="tm-meal-name" style="font-style:italic">${escapeHtml(meal.title)}</div>
                    </div>
                </div>
            `;
        }
        return `
            <div class="tm-meal-row" data-recipe-id="${meal.recipe_id}">
                <div class="tm-meal-emoji">${getMealEmoji(meal.title, meal.tags)}</div>
                <div class="tm-meal-info">
                    <div class="tm-meal-name">${escapeHtml(meal.title)}</div>
                    ${meal.creator ? `<div class="tm-meal-creator">by ${escapeHtml(meal.creator)}</div>` : ''}
                </div>
                <div class="tm-meal-arrow">›</div>
            </div>
        `;
    }).join('');

    // Click handler — open recipe detail (only for recipe rows)
    list.querySelectorAll('.tm-meal-row[data-recipe-id]').forEach(row => {
        row.addEventListener('click', () => {
            const recipeId = Number(row.dataset.recipeId);
            if (window.openRecipeById) {
                window.openRecipeById(recipeId);
            }
        });
    });
}

// ─── Quick Add Sheet ────────────────────────────────
const SMART_EMOJI_MAP = {
    'pizza': '🍕', 'taco': '🌮', 'sushi': '🍣', 'burger': '🍔',
    'pasta': '🍝', 'noodle': '🍜', 'ramen': '🍜', 'salad': '🥗',
    'soup': '🍲', 'steak': '🥩', 'chicken': '🍗', 'fish': '🐟',
    'shrimp': '🦐', 'rice': '🍚', 'sandwich': '🥪', 'wrap': '🌯',
    'egg': '🍳', 'pancake': '🥞', 'waffle': '🧇', 'bread': '🍞',
    'cake': '🎂', 'cookie': '🍪', 'ice cream': '🍦', 'donut': '🍩',
    'smoothie': '🥤', 'coffee': '☕', 'cocktail': '🍸', 'wine': '🍷',
    'beer': '🍺', 'bbq': '🔥', 'grill': '🔥', 'curry': '🍛',
    'chinese': '🥡', 'takeout': '🥡', 'delivery': '📦',
    'leftovers': '🍳', 'date': '🎉', 'fancy': '✨', 'healthy': '🥬',
    'breakfast': '🍳', 'brunch': '🥂', 'snack': '🍿', 'dessert': '🍰',
    'mexican': '🌮', 'italian': '🇮🇹', 'thai': '🇹🇭', 'indian': '🇮🇳',
    'japanese': '🇯🇵', 'korean': '🇰🇷', 'wing': '🍗', 'fry': '🍟',
    'hotdog': '🌭', 'sub': '🥖', 'bowl': '🥣', 'poke': '🐟',
};

let quickAddDate = null;
let quickAddEmoji = '🍽️';
let mpScrollBeforeQuickAdd = 0;

function detectEmoji(text) {
    const lower = text.toLowerCase();
    for (const [key, emoji] of Object.entries(SMART_EMOJI_MAP)) {
        if (lower.includes(key)) return emoji;
    }
    return '🍽️';
}

function openQuickAdd(dateStr) {
    quickAddDate = dateStr;
    const date = new Date(dateStr + 'T12:00:00');
    const dayName = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][date.getDay()];
    const monthDay = `${MONTHS[date.getMonth()]} ${date.getDate()}`;

    // Save scroll positions before keyboard disrupts them
    const panel = document.querySelector('.meal-plan-panel');
    mpScrollBeforeQuickAdd = panel ? panel.scrollTop : 0;

    document.getElementById('quickAddDayLabel').textContent = `${dayName}, ${monthDay}`;
    document.getElementById('quickAddInput').value = '';
    document.getElementById('quickAddSubmit').disabled = true;
    quickAddEmoji = '🍽️';
    document.getElementById('quickAddEmojiBtn').textContent = quickAddEmoji;

    // Clear vibe tag selection
    document.querySelectorAll('.vibe-tag').forEach(t => t.classList.remove('selected'));

    // Load recent quick plans
    loadRecentPills();

    document.getElementById('quickAddOverlay').classList.add('active');
    setTimeout(() => document.getElementById('quickAddInput').focus(), 350);
}

function closeQuickAdd() {
    // Blur input first to dismiss keyboard before restoring scroll
    document.getElementById('quickAddInput').blur();
    document.getElementById('quickAddOverlay').classList.remove('active');
    quickAddDate = null;
    // Keep body scroll locked if meal plan panel is still open
    if (!document.getElementById('mealPlanOverlay').classList.contains('active')) {
        document.body.style.overflow = '';
    }
    // Restore meal plan panel scroll after keyboard dismissed
    requestAnimationFrame(() => {
        const panel = document.querySelector('.meal-plan-panel');
        if (panel) panel.scrollTop = mpScrollBeforeQuickAdd;
        // iOS sometimes needs extra time after keyboard animation
        setTimeout(() => { if (panel) panel.scrollTop = mpScrollBeforeQuickAdd; }, 350);
    });
}

async function loadRecentPills() {
    const recent = await fetchRecentQuickPlans();
    const container = document.getElementById('quickAddRecentPills');
    const wrapper = document.getElementById('quickAddRecent');

    if (recent.length === 0) {
        wrapper.classList.remove('has-items');
        return;
    }

    wrapper.classList.add('has-items');
    container.innerHTML = recent.map(r => `
        <button class="recent-pill" data-text="${escapeHtml(r.text)}" data-emoji="${r.emoji}">
            ${r.emoji} ${escapeHtml(r.text)}
        </button>
    `).join('');
}

async function submitQuickPlan() {
    const input = document.getElementById('quickAddInput');
    const text = input.value.trim();
    if (!text || !quickAddDate) return;

    const btn = document.getElementById('quickAddSubmit');
    btn.disabled = true;
    btn.querySelector('span').textContent = 'Adding...';

    const success = await addQuickPlan(text, quickAddDate, quickAddEmoji);

    if (success) {
        saveRecentQuickPlan(text, quickAddEmoji);
        btn.querySelector('span').textContent = '✓ Added!';
        setTimeout(() => {
            closeQuickAdd();
            refreshMealPlan();
            renderTodaysMeals();
            btn.querySelector('span').textContent = 'Add to Plan';
        }, 400);
    } else {
        btn.querySelector('span').textContent = 'Failed — try again';
        btn.disabled = false;
        setTimeout(() => { btn.querySelector('span').textContent = 'Add to Plan'; }, 1500);
    }
}

// ─── Event Wiring ──────────────────────────────────
function init() {
    // Meal plan button (left of title)
    document.getElementById('mealPlanBtn').addEventListener('click', openMealPlan);
    document.getElementById('mealPlanClose').addEventListener('click', closeMealPlan);
    document.getElementById('mealPlanOverlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeMealPlan();
    });

    // Week nav
    document.getElementById('mpPrevWeek').addEventListener('click', () => {
        mpWeekStart = addDays(mpWeekStart, -7);
        refreshMealPlan();
    });
    document.getElementById('mpNextWeek').addEventListener('click', () => {
        mpWeekStart = addDays(mpWeekStart, 7);
        refreshMealPlan();
    });

    // Radial menu close
    document.getElementById('radialOverlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeRadialMenu();
    });
    document.getElementById('radialPrev').addEventListener('click', () => {
        radialWeekStart = addDays(radialWeekStart, -7);
        renderRadialRing();
    });
    document.getElementById('radialNext').addEventListener('click', () => {
        radialWeekStart = addDays(radialWeekStart, 7);
        renderRadialRing();
    });

    // Grocery list
    document.getElementById('groceryListBtn').addEventListener('click', openGroceryList);
    document.getElementById('groceryClose').addEventListener('click', closeGroceryList);
    document.getElementById('groceryOverlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeGroceryList();
    });
    document.getElementById('groceryCopyBtn').addEventListener('click', copyGroceryList);

    // Quick Add Sheet
    document.getElementById('quickAddClose').addEventListener('click', closeQuickAdd);
    document.getElementById('quickAddOverlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeQuickAdd();
    });
    document.getElementById('quickAddSubmit').addEventListener('click', submitQuickPlan);

    // Smart emoji detection on input
    const qaInput = document.getElementById('quickAddInput');
    qaInput.addEventListener('input', () => {
        const text = qaInput.value.trim();
        document.getElementById('quickAddSubmit').disabled = !text;
        // Auto-detect emoji unless user manually picked a vibe tag
        if (!document.querySelector('.vibe-tag.selected')) {
            quickAddEmoji = detectEmoji(text);
            document.getElementById('quickAddEmojiBtn').textContent = quickAddEmoji;
        }
    });

    // Enter to submit
    qaInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && qaInput.value.trim()) {
            e.preventDefault();
            submitQuickPlan();
        }
    });

    // Vibe tags
    document.getElementById('quickAddVibeTags').addEventListener('click', (e) => {
        const tag = e.target.closest('.vibe-tag');
        if (!tag) return;

        const wasSelected = tag.classList.contains('selected');
        document.querySelectorAll('.vibe-tag').forEach(t => t.classList.remove('selected'));

        if (wasSelected) {
            // Deselect — revert to smart detection
            quickAddEmoji = detectEmoji(qaInput.value);
            document.getElementById('quickAddEmojiBtn').textContent = quickAddEmoji;
        } else {
            tag.classList.add('selected');
            qaInput.value = tag.dataset.text;
            quickAddEmoji = tag.dataset.emoji;
            document.getElementById('quickAddEmojiBtn').textContent = quickAddEmoji;
            document.getElementById('quickAddSubmit').disabled = false;
        }
    });

    // Recent pills
    document.getElementById('quickAddRecentPills').addEventListener('click', (e) => {
        const pill = e.target.closest('.recent-pill');
        if (!pill) return;
        qaInput.value = pill.dataset.text;
        quickAddEmoji = pill.dataset.emoji || detectEmoji(pill.dataset.text);
        document.getElementById('quickAddEmojiBtn').textContent = quickAddEmoji;
        document.getElementById('quickAddSubmit').disabled = false;
        document.querySelectorAll('.vibe-tag').forEach(t => t.classList.remove('selected'));
    });

    // Delegate clicks inside the meal plan grid
    document.getElementById('mpWeekGrid').addEventListener('click', (e) => {
        // Quick Plan add button
        const addBtn = e.target.closest('.mp-day-add');
        if (addBtn) {
            e.stopPropagation();
            openQuickAdd(addBtn.dataset.date);
            return;
        }

        // Remove button
        const removeBtn = e.target.closest('.mp-chip-remove');
        if (removeBtn) {
            e.stopPropagation();
            const entryId = removeBtn.dataset.entryId;
            const chip = removeBtn.closest('.mp-meal-chip');
            const title = chip.querySelector('.mp-chip-title').textContent;
            showRemoveConfirm(entryId, title);
            return;
        }

        // Chip click → start reassign (but NOT if long-press just fired)
        const chip = e.target.closest('.mp-meal-chip');
        if (chip) {
            e.stopPropagation();
            if (longPressTriggered) {
                longPressTriggered = false;
                return;
            }
            const entryId = chip.dataset.entryId;
            if (reassigningEntry == entryId) {
                cancelReassign();
            } else {
                startReassign(entryId);
            }
            return;
        }

        // Day column click → assign here
        const dayCol = e.target.closest('.mp-day-col');
        if (dayCol && reassigningEntry) {
            handleDayColumnClick(dayCol.dataset.date);
            return;
        }

        // Click on empty area → cancel reassign
        if (reassigningEntry) cancelReassign();
    });

    // Escape key to close overlays
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (document.getElementById('quickAddOverlay').classList.contains('active')) {
                closeQuickAdd();
            } else if (document.getElementById('radialOverlay').classList.contains('active')) {
                closeRadialMenu();
            } else if (document.getElementById('groceryOverlay').classList.contains('active')) {
                closeGroceryList();
            } else if (document.getElementById('mealPlanOverlay').classList.contains('active')) {
                closeMealPlan();
            }
        }
    });

    // Initial badge update
    updateBadge();

    // Initialize long-press on meal plan grid
    initLongPress(document.getElementById('mpWeekGrid'));

    // Render today's meals card on homepage
    renderTodaysMeals();

    // "View Plan" button on today card
    document.getElementById('tmViewAll').addEventListener('click', openMealPlan);
}

// Expose the radial menu opener for recipe cards
window.openMealPlanRadial = openRadialMenu;
window.refreshMealPlanBadge = updateBadge;
window.refreshTodaysMeals = renderTodaysMeals;

// Boot
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

})();
