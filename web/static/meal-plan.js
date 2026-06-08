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
    currentPlan = await fetchPlan(mpWeekStart);
    renderWeekGrid();
    renderWeekTitle();
    updateBadge();
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
                ${dayEntries.map(entry => `
                    <div class="mp-meal-chip" data-entry-id="${entry.id}" data-recipe-id="${entry.recipe_id}">
                        <span class="mp-chip-title">${escapeHtml(entry.title)}</span>
                        <button class="mp-chip-remove" data-entry-id="${entry.id}" title="Remove">✕</button>
                    </div>
                `).join('')}
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
    const radius = 125; // distance from center
    const centerX = 170; // half of 340px
    const centerY = 170;

    for (let i = 0; i < 7; i++) {
        const day = addDays(radialWeekStart, i);
        const dateStr = formatDate(day);
        const today = isToday(day);
        const hasMeals = plan.some(e => e.date === dateStr);

        // Distribute in a circle starting from top (-90deg)
        const angle = ((i / 7) * 360 - 90) * (Math.PI / 180);
        const x = centerX + radius * Math.cos(angle) - 28; // subtract half width (56/2)
        const y = centerY + radius * Math.sin(angle) - 28;

        const dayEl = document.createElement('div');
        dayEl.className = `radial-day${today ? ' is-today' : ''}${hasMeals ? ' has-meals' : ''}`;
        dayEl.style.left = `${x}px`;
        dayEl.style.top = `${y}px`;
        dayEl.dataset.date = dateStr;

        dayEl.innerHTML = `
            <div class="radial-day-name">${DAYS[i]}</div>
            <div class="radial-day-num">${day.getDate()}</div>
        `;

        // Staggered entrance animation
        dayEl.style.opacity = '0';
        dayEl.style.transform = 'scale(0.3)';
        setTimeout(() => {
            dayEl.style.transition = '0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275)';
            dayEl.style.opacity = '1';
            dayEl.style.transform = 'scale(1)';
        }, 50 + i * 40);

        dayEl.addEventListener('click', async () => {
            // Visual feedback
            dayEl.style.transform = 'scale(1.3)';
            dayEl.style.background = 'var(--accent)';
            dayEl.style.color = 'white';
            dayEl.style.borderColor = 'var(--accent)';

            const success = await addToPlan(radialRecipeId, dateStr);
            if (success) {
                setTimeout(() => {
                    closeRadialMenu();
                    updateBadge();
                }, 300);
            } else {
                dayEl.style.transform = 'scale(1)';
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

    // Delegate clicks inside the meal plan grid
    document.getElementById('mpWeekGrid').addEventListener('click', (e) => {
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

        // Chip click → start reassign
        const chip = e.target.closest('.mp-meal-chip');
        if (chip) {
            e.stopPropagation();
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
            if (document.getElementById('radialOverlay').classList.contains('active')) {
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
}

// Expose the radial menu opener for recipe cards
window.openMealPlanRadial = openRadialMenu;
window.refreshMealPlanBadge = updateBadge;

// Boot
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

})();
