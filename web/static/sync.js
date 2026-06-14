/**
 * OnlyPans Sync Manager — generic server-sync utility.
 *
 * Usage:
 *   const sync = window.SyncManager.create({
 *       id: 'grocery',                        // unique name for this sync
 *       interval: 60000,                      // poll interval in ms (default 60s)
 *       isActive: () => overlay.classList.contains('active'),  // guard — only sync when true
 *       fetch: async () => { ... },           // returns server state (any shape)
 *       diff: (serverState, domState) => { .. },  // returns { changed: bool, patches: [] }
 *       apply: (patches) => { ... },          // apply incremental patches to DOM
 *       rerender: () => { ... },              // full re-render when diff detects structural change
 *   });
 *
 *   sync.start();   // begins interval polling
 *   sync.stop();    // clears interval
 *   sync.now();     // trigger an immediate sync (e.g. after regaining focus)
 *
 * Design principles:
 *   - No coupling to specific DOM structure or API shape
 *   - Consumer provides fetch/diff/apply/rerender callbacks
 *   - Guard function prevents wasted fetches when UI is hidden
 *   - Automatic stop on visibility change (page hidden)
 *   - Re-sync on visibility return (page shown again)
 *   - Silent failures — never throws, retries on next interval
 */

(function() {
'use strict';

const _instances = {};

function create(opts) {
    const {
        id,
        interval = 60000,
        isActive,
        fetch: fetchState,
        diff,
        apply,
        rerender,
    } = opts;

    if (!id || !fetchState || !diff || !apply || !rerender || !isActive) {
        throw new Error('SyncManager.create requires: id, isActive, fetch, diff, apply, rerender');
    }

    // Clean up any existing instance with same id
    if (_instances[id]) {
        _instances[id].stop();
    }

    let _intervalId = null;
    let _syncing = false;

    async function doSync() {
        if (_syncing) return; // prevent overlapping syncs
        if (!isActive()) {
            stop();
            return;
        }
        _syncing = true;
        try {
            const serverState = await fetchState();
            const result = diff(serverState);
            if (result.structural) {
                // Structural change — full re-render needed
                rerender();
            } else if (result.patches && result.patches.length > 0) {
                // Incremental patches — apply without re-render
                apply(result.patches);
            }
            // else: no changes — do nothing
        } catch (e) {
            // Silent failure — retry next interval
        } finally {
            _syncing = false;
        }
    }

    function start() {
        stop(); // clear any existing
        _intervalId = setInterval(doSync, interval);
    }

    function stop() {
        if (_intervalId) {
            clearInterval(_intervalId);
            _intervalId = null;
        }
    }

    function now() {
        doSync();
    }

    function isRunning() {
        return _intervalId !== null;
    }

    const instance = { id, start, stop, now, isRunning };
    _instances[id] = instance;
    return instance;
}

// Auto-pause all syncs when page is hidden, resume when visible
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        // Pause all — clear intervals but remember they were running
        Object.values(_instances).forEach(inst => {
            if (inst.isRunning()) {
                inst._wasRunning = true;
                inst.stop();
            }
        });
    } else {
        // Resume any that were running + immediate sync
        Object.values(_instances).forEach(inst => {
            if (inst._wasRunning) {
                inst._wasRunning = false;
                inst.start();
                inst.now(); // immediate sync on wake
            }
        });
    }
});

// Expose globally
window.SyncManager = { create, instances: _instances };

})();
