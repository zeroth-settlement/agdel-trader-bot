/**
 * Pyrana Library Component - Modal
 *
 * Modal container for viewing/editing resources.
 * Handles edit mode, save functionality, and footer action buttons.
 */

const LibraryModal = (function() {
  'use strict';

  // Track modal state
  let modalState = {
    isOpen: false,
    editMode: false,
    currentItem: null,
    currentItemId: null,
    currentApi: null
  };

  // Event callbacks
  let callbacks = {
    onSave: null,
    onRetire: null,
    onClose: null
  };

  /**
   * Normalize status label for display
   */
  function formatStatusLabel(status) {
    const value = String(status ?? '').trim();
    if (!value) return '';
    return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();
  }

  /**
   * Normalize status to a safe CSS class suffix
   */
  function statusClass(status) {
    return String(status ?? '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-');
  }

  /**
   * Generate modal HTML structure
   */
  function generateModalHtml() {
    return `
      <div class="library-modal-overlay" id="libraryModalOverlay">
        <div class="library-modal">
          <div class="library-modal-header">
            <div class="library-modal-title-wrap">
              <h2 class="library-modal-title" id="libraryModalTitle">Resource Details</h2>
              <span class="library-modal-status-tag" id="libraryModalStatusTag" hidden></span>
            </div>
            <button class="library-modal-close" id="libraryModalClose">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          </div>
          <div class="library-modal-body" id="libraryModalBody">
            <!-- Content injected dynamically -->
          </div>
          <div class="library-modal-footer" id="libraryModalFooter">
            <!-- Buttons injected dynamically -->
          </div>
        </div>
      </div>
    `;
  }

  /**
   * Initialize modal in the DOM
   */
  function init(container, eventCallbacks = {}) {
    Object.assign(callbacks, eventCallbacks);

    // Add modal HTML to container
    const modalContainer = document.createElement('div');
    modalContainer.innerHTML = generateModalHtml();
    container.appendChild(modalContainer.firstElementChild);

    // Bind close handlers
    const overlay = document.getElementById('libraryModalOverlay');
    const closeBtn = document.getElementById('libraryModalClose');

    closeBtn.addEventListener('click', close);
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) {
        close();
      }
    });

    // Escape key to close
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modalState.isOpen) {
        close();
      }
    });
  }

  /**
   * Open modal with item content
   */
  function open(title, bodyHtml, footerOptions = {}) {
    const overlay = document.getElementById('libraryModalOverlay');
    const titleEl = document.getElementById('libraryModalTitle');
    const statusEl = document.getElementById('libraryModalStatusTag');
    const bodyEl = document.getElementById('libraryModalBody');

    titleEl.textContent = title;
    if (statusEl) {
      const statusText = formatStatusLabel(footerOptions.status);
      if (statusText) {
        statusEl.textContent = statusText;
        statusEl.className = `library-modal-status-tag ${statusClass(statusText)}`;
        statusEl.hidden = false;
      } else {
        statusEl.textContent = '';
        statusEl.className = 'library-modal-status-tag';
        statusEl.hidden = true;
      }
    }
    bodyEl.innerHTML = bodyHtml;

    updateFooter(footerOptions);

    overlay.classList.add('open');
    modalState.isOpen = true;
    modalState.editMode = false;
  }

  /**
   * Close modal
   */
  function close() {
    const overlay = document.getElementById('libraryModalOverlay');
    overlay.classList.remove('open');
    modalState.isOpen = false;
    modalState.editMode = false;
    modalState.currentItem = null;
    modalState.currentItemId = null;

    if (callbacks.onClose) {
      callbacks.onClose();
    }
  }

  /**
   * Set current item context
   */
  function setItemContext(item, itemId, apiKey) {
    modalState.currentItem = item;
    modalState.currentItemId = itemId;
    modalState.currentApi = apiKey;
  }

  /**
   * Get current item context
   */
  function getItemContext() {
    return {
      item: modalState.currentItem,
      itemId: modalState.currentItemId,
      apiKey: modalState.currentApi
    };
  }

  /**
   * Update modal footer buttons (Active items only)
   */
  function updateFooter(options = {}) {
    const footer = document.getElementById('libraryModalFooter');
    const { itemId } = options;

    footer.innerHTML = `
      <button class="library-modal-btn library-modal-btn-warning" id="modalRetire" style="margin-right: auto;">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18.36 6.64A9 9 0 0 1 20.77 15"/>
          <path d="M6.16 6.16a9 9 0 1 0 12.68 12.68"/>
          <line x1="2" y1="2" x2="22" y2="22"/>
        </svg>
        Retire
      </button>
      <button class="library-modal-btn library-modal-btn-secondary" id="modalCancel">Close</button>
      <button class="library-modal-btn library-modal-btn-primary" id="modalEdit">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
          <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
        </svg>
        Edit
      </button>
    `;

    bindFooterEvents({ itemId });
  }

  /**
   * Bind footer button events
   */
  function bindFooterEvents(options) {
    const { itemId } = options;

    const cancelBtn = document.getElementById('modalCancel');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', close);
    }

    const retireBtn = document.getElementById('modalRetire');
    const editBtn = document.getElementById('modalEdit');

    if (retireBtn) {
      retireBtn.addEventListener('click', () => handleRetire(itemId));
    }
    if (editBtn) {
      editBtn.addEventListener('click', () => enableEditMode(itemId));
    }
  }

  /**
   * Enable edit mode
   */
  function enableEditMode(itemId) {
    modalState.editMode = true;
    const footer = document.getElementById('libraryModalFooter');
    const body = document.getElementById('libraryModalBody');

    // Update footer to show Save/Cancel
    footer.innerHTML = `
      <button class="library-modal-btn library-modal-btn-secondary" id="modalCancelEdit">Cancel</button>
      <button class="library-modal-btn library-modal-btn-primary" id="modalSave">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/>
          <polyline points="17 21 17 13 7 13 7 21"/>
          <polyline points="7 3 7 8 15 8"/>
        </svg>
        Save Changes
      </button>
    `;

    document.getElementById('modalCancelEdit').addEventListener('click', () => {
      // Re-render modal to exit edit mode
      if (callbacks.onClose) {
        callbacks.onClose();
      }
    });

    document.getElementById('modalSave').addEventListener('click', () => handleSave(itemId));

    // Enable editing on all fields with data-field attribute
    body.querySelectorAll('[data-field]').forEach(field => {
      field.removeAttribute('readonly');
      field.removeAttribute('disabled');
      field.style.background = '';
      field.style.borderColor = 'var(--accent)';

      // Show hidden JSON editors
      if (field.style.display === 'none') {
        field.style.display = '';
      }
    });

    // Hide formatted display views
    body.querySelectorAll('.supporting-contexts-display').forEach(display => {
      display.style.display = 'none';
    });

    // Add edit mode banner
    const editBanner = document.createElement('div');
    editBanner.id = 'editModeBanner';
    editBanner.style.cssText = 'margin-bottom: 16px; padding: 12px; background: var(--accent-dim); border-radius: 8px; color: var(--accent);';
    editBanner.innerHTML = `
      <div style="font-weight: 500; margin-bottom: 6px;">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 8px;">
          <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
          <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
        </svg>
        Edit Mode
      </div>
      <div style="font-size: 12px; color: var(--text-secondary);">
        All fields are editable. Fields marked with &#128274; are immutable - changing them creates a new version.
      </div>
    `;
    body.insertBefore(editBanner, body.firstChild);
  }

  /**
   * Handle save
   */
  async function handleSave(itemId) {
    if (!callbacks.onSave) return;

    const saveBtn = document.getElementById('modalSave');
    const body = document.getElementById('libraryModalBody');
    const originalItem = modalState.currentItem;
    const mutableFields = originalItem?._mutableFields || new Set();

    // Collect all changed values
    const mutableChanges = {};
    const immutableChanges = {};
    let hasChanges = false;
    let jsonError = null;

    body.querySelectorAll('[data-field]').forEach(field => {
      if (jsonError) return;

      const fieldPath = field.dataset.field;
      let value = field.value;

      // Handle select elements
      if (field.tagName === 'SELECT') {
        if (value === 'true') value = true;
        else if (value === 'false') value = false;
      }

      // Handle array fields
      if (field.dataset.isArray === 'true') {
        value = value.split(',').map(v => v.trim()).filter(v => v);
      }

      // Handle JSON fields
      if (field.dataset.isJson === 'true') {
        try {
          value = JSON.parse(value);
        } catch (e) {
          jsonError = `Invalid JSON in field "${fieldPath}". Please fix the JSON syntax.`;
          return;
        }
      }

      // Handle number fields
      if (field.type === 'number' && value !== '') {
        value = Number(value);
      }

      // Get original value
      const originalValue = getNestedValue(originalItem, fieldPath);

      // Compare values
      let originalStr, newStr;
      if (Array.isArray(originalValue) && Array.isArray(value)) {
        originalStr = JSON.stringify(originalValue);
        newStr = JSON.stringify(value);
      } else if (typeof originalValue === 'object' && typeof value === 'object') {
        originalStr = JSON.stringify(originalValue);
        newStr = JSON.stringify(value);
      } else {
        originalStr = String(originalValue ?? '');
        newStr = String(value ?? '');
      }

      if (originalStr !== newStr) {
        hasChanges = true;
        const topLevelField = fieldPath.split('.')[0];
        if (mutableFields.has(topLevelField) || mutableFields.has(fieldPath)) {
          setNestedValue(mutableChanges, fieldPath, value);
        } else {
          setNestedValue(immutableChanges, fieldPath, value);
        }
      }
    });

    if (jsonError) {
      alert(jsonError);
      return;
    }

    if (!hasChanges) {
      alert('No changes to save');
      return;
    }

    // Warn about immutable changes
    const hasImmutableChanges = Object.keys(immutableChanges).length > 0;
    if (hasImmutableChanges) {
      const changedFields = Object.keys(immutableChanges).join(', ');
      const proceed = confirm(`You're changing immutable fields (${changedFields}). This will create a new version of this resource. Continue?`);
      if (!proceed) return;
    }

    // Show saving state
    saveBtn.disabled = true;
    saveBtn.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation: library-spin 1s linear infinite;">
        <path d="M21 12a9 9 0 11-6.219-8.56"/>
      </svg>
      Saving...
    `;

    try {
      await callbacks.onSave(itemId, { mutableChanges, immutableChanges });
      close();
    } catch (err) {
      saveBtn.disabled = false;
      saveBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/>
          <polyline points="17 21 17 13 7 13 7 21"/>
          <polyline points="7 3 7 8 15 8"/>
        </svg>
        Save Changes
      `;
      alert(`Failed to save: ${err.message}`);
    }
  }

  /**
   * Handle retire
   */
  async function handleRetire(itemId) {
    if (!callbacks.onRetire) return;

    if (!confirm('Retire this resource?\n\nRetired items are hidden from the list but the data is preserved. This can be undone by editing the status back to Active.')) {
      return;
    }

    const retireBtn = document.getElementById('modalRetire');
    retireBtn.disabled = true;
    retireBtn.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation: library-spin 1s linear infinite;">
        <path d="M21 12a9 9 0 11-6.219-8.56"/>
      </svg>
      Retiring...
    `;

    try {
      await callbacks.onRetire(itemId);
      close();
    } catch (err) {
      retireBtn.disabled = false;
      retireBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18.36 6.64A9 9 0 0 1 20.77 15"/>
          <path d="M6.16 6.16a9 9 0 1 0 12.68 12.68"/>
          <line x1="2" y1="2" x2="22" y2="22"/>
        </svg>
        Retire
      `;
      alert(`Failed to retire: ${err.message}`);
    }
  }

  /**
   * Helper: Get nested value from object
   */
  function getNestedValue(obj, path) {
    const parts = path.split('.');
    let current = obj;
    for (const part of parts) {
      if (current === null || current === undefined) return undefined;
      current = current[part];
    }
    return current;
  }

  /**
   * Helper: Set nested value in object
   */
  function setNestedValue(obj, path, value) {
    const parts = path.split('.');
    let current = obj;
    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i];
      if (!(part in current) || current[part] === null) {
        current[part] = {};
      }
      current = current[part];
    }
    current[parts[parts.length - 1]] = value;
  }

  /**
   * Show loading state in modal
   */
  function showLoading(title = 'Loading...') {
    const body = document.getElementById('libraryModalBody');
    const titleEl = document.getElementById('libraryModalTitle');

    titleEl.textContent = title;
    body.innerHTML = `
      <div class="library-loading">
        <div class="library-loading-spinner"></div>
        <span>Loading details...</span>
      </div>
    `;
  }

  /**
   * Show error in modal
   */
  function showError(message) {
    const body = document.getElementById('libraryModalBody');
    body.innerHTML = `
      <div style="text-align: center; padding: 40px; color: var(--error);">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-bottom: 16px;">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <div>${message}</div>
      </div>
    `;
  }

  return {
    init,
    open,
    close,
    setItemContext,
    getItemContext,
    updateFooter,
    enableEditMode,
    showLoading,
    showError,
    isOpen: () => modalState.isOpen,
    isEditMode: () => modalState.editMode
  };
})();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = LibraryModal;
}
