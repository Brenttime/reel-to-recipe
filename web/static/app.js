/**
 * Recipe Glass — Frontend Logic
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
    modalContent.innerHTML = `
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
}

// ─── Util ───────────────────────────────────────
function escapeHtml(text) {
    if (!text) return '';
    const el = document.createElement('span');
    el.textContent = text;
    return el.innerHTML;
}

// ─── Boot ───────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
