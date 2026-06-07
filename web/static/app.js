/**
 * Reel Cookbook — Frontend Logic
 */

const searchInput = document.getElementById('searchInput');
const clearBtn = document.getElementById('clearSearch');
const recipeGrid = document.getElementById('recipeGrid');
const emptyState = document.getElementById('emptyState');
const filterChips = document.getElementById('filterChips');
const modalOverlay = document.getElementById('modalOverlay');
const modalContent = document.getElementById('modalContent');
const modalClose = document.getElementById('modalClose');

let allRecipes = [];
let currentRecipe = null;
let debounceTimer = null;

// ─── Init ───────────────────────────────────────
async function init() {
    await loadRecipes();
    await loadCreators();
    setupListeners();
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
    recipeGrid.innerHTML = recipes.map((r, i) => `
        <article class="recipe-card" data-id="${r.id}" style="animation-delay: ${i * 0.05}s">
            <div class="card-platform">
                <span class="dot"></span>
                ${r.platform || 'recipe'}
            </div>
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
        <button class="chip" data-creator="${escapeHtml(c)}">${escapeHtml(c)}</button>
    `).join('');
}

function renderModal(recipe) {
    currentRecipe = recipe;
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
                ${recipe.servings ? `<div class="modal-meta-item"><strong>Servings:</strong> ${escapeHtml(recipe.servings)}</div>` : ''}
                ${recipe.prep_time ? `<div class="modal-meta-item"><strong>Prep:</strong> ${escapeHtml(recipe.prep_time)}</div>` : ''}
                ${recipe.cook_time ? `<div class="modal-meta-item"><strong>Cook:</strong> ${escapeHtml(recipe.cook_time)}</div>` : ''}
                ${recipe.total_time ? `<div class="modal-meta-item"><strong>Total:</strong> ${escapeHtml(recipe.total_time)}</div>` : ''}
            </div>
        ` : ''}

        <h4 class="section-title">Ingredients</h4>
        <ul class="ingredients-list">
            ${recipe.ingredients.map(ing => `<li>${escapeHtml(ing)}</li>`).join('')}
        </ul>

        <h4 class="section-title">Instructions</h4>
        <ol class="instructions-list">
            ${recipe.instructions.map(step => `<li>${escapeHtml(step)}</li>`).join('')}
        </ol>

        ${recipe.tips ? `<div class="modal-tips">${escapeHtml(recipe.tips)}</div>` : ''}
        ${recipe.macros ? `<div class="modal-macros">📊 ${escapeHtml(recipe.macros)}</div>` : ''}
    `;

    // Bind action buttons
    document.getElementById('deleteRecipeBtn').addEventListener('click', () => deleteRecipe(recipe));
    document.getElementById('editRecipeBtn').addEventListener('click', () => openEditMode(recipe));
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

// ─── Actions ────────────────────────────────────
async function deleteRecipe(recipe) {
    if (!confirm(`Delete "${recipe.title}"? This can't be undone.`)) return;

    const res = await fetch(`/api/recipes/${recipe.id}`, { method: 'DELETE' });
    if (res.ok) {
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

    // Card click → modal
    recipeGrid.addEventListener('click', async (e) => {
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
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeModal();
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
