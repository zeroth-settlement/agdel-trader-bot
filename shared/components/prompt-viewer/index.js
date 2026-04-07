/**
 * Prompt Viewer Component - Main Entry Point
 *
 * A reusable component for viewing prompt details with multiple views:
 * - Formatted View: Structured display with collapsible sections
 * - Raw JSON View: Full JSON representation
 * - Payload View: Preview of what gets sent to the LLM
 *
 * Usage:
 *   // Initialize in a container
 *   PromptViewer.init(document.getElementById('container'), {
 *     promptApiBase: 'http://localhost:8102',
 *     cxuApiBase: 'http://localhost:8101'
 *   });
 *
 *   // Load a specific prompt
 *   PromptViewer.loadPrompt('prompt-id-here');
 *
 *   // Or set prompt data directly
 *   PromptViewer.setPrompt(promptObject);
 */

const PromptViewer = (function() {
  'use strict';

  // State
  let container = null;
  let currentPrompt = null;
  let currentView = 'formatted';
  let options = {};

  // Callbacks
  let onPromptLoaded = null;
  let onCxuClicked = null;
  let onClose = null;
  let showCloseButton = true;

  /**
   * Escape HTML special characters
   */
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /**
   * Initialize the component
   */
  function init(containerEl, opts = {}) {
    container = containerEl;
    options = opts;
    onClose = opts.onClose || null;
    showCloseButton = opts.showCloseButton !== false; // default true

    // Inject styles
    if (typeof PromptViewerStyles !== 'undefined') {
      PromptViewerStyles.inject();
    }

    // Configure API client
    if (typeof PromptViewerAPI !== 'undefined') {
      PromptViewerAPI.configure({
        promptApiBase: opts.promptApiBase || 'http://localhost:8102',
        cxuApiBase: opts.cxuApiBase || 'http://localhost:8101'
      });
    }

    // Render initial structure
    render();

    return PromptViewer;
  }

  /**
   * Render the component structure
   */
  function render() {
    if (!container) return;

    const name = currentPrompt?.name || 'Select a Prompt';
    const status = currentPrompt?.status || '';

    container.innerHTML = `
      <div class="prompt-viewer">
        <div class="prompt-viewer-header">
          <div class="prompt-viewer-title">
            <span id="pvTitle">${escapeHtml(name)}</span>
            ${status ? `<span class="prompt-viewer-title-badge" id="pvStatusBadge" style="background: ${status === 'Active' ? 'var(--success-dim)' : 'var(--warning-dim)'}; color: ${status === 'Active' ? 'var(--success)' : 'var(--warning)'}; border-color: ${status === 'Active' ? 'var(--success)' : 'var(--warning)'};">${status}</span>` : '<span class="prompt-viewer-title-badge" id="pvStatusBadge" style="display: none;"></span>'}
          </div>
          <div class="prompt-viewer-header-actions">
            <div class="prompt-viewer-toggle">
              <button class="prompt-viewer-toggle-btn ${currentView === 'formatted' ? 'active' : ''}" data-view="formatted" onclick="PromptViewer.switchView('formatted')">Formatted</button>
              <button class="prompt-viewer-toggle-btn ${currentView === 'raw' ? 'active' : ''}" data-view="raw" onclick="PromptViewer.switchView('raw')">Raw JSON</button>
              <button class="prompt-viewer-toggle-btn ${currentView === 'payload' ? 'active' : ''}" data-view="payload" onclick="PromptViewer.switchView('payload')">LLM Payload</button>
            </div>
            ${showCloseButton ? `
              <button class="prompt-viewer-close-btn" onclick="PromptViewer.handleClose()" title="Close">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="18" y1="6" x2="6" y2="18"/>
                  <line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            ` : ''}
          </div>
        </div>
        <div class="prompt-viewer-content" id="pvContent">
          ${renderContent()}
        </div>
      </div>
    `;
  }

  /**
   * Render the content based on current view
   */
  function renderContent() {
    if (!currentPrompt) {
      return `
        <div class="pv-empty">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/>
            <line x1="16" y1="17" x2="8" y2="17"/>
          </svg>
          <div class="pv-empty-title">No Prompt Selected</div>
          <div class="pv-empty-desc">Select a prompt to view its details, including the full configuration sent to the LLM.</div>
        </div>
      `;
    }

    switch (currentView) {
      case 'formatted':
        return typeof PromptFormattedView !== 'undefined'
          ? PromptFormattedView.generate(currentPrompt, options)
          : '<div class="pv-empty">Formatted view not available</div>';

      case 'raw':
        return renderRawView();

      case 'payload':
        return typeof PromptPayloadView !== 'undefined'
          ? PromptPayloadView.generate(currentPrompt, options)
          : '<div class="pv-empty">Payload view not available</div>';

      default:
        return '<div class="pv-empty">Unknown view</div>';
    }
  }

  /**
   * Render raw JSON view
   */
  function renderRawView() {
    const rawJson = JSON.stringify(currentPrompt._original || currentPrompt, null, 2);

    return `
      <div style="display: flex; justify-content: flex-end; margin-bottom: 10px;">
        <button class="pv-copy-btn" onclick="PromptViewer.copyToClipboard(document.getElementById('pvRawJson').textContent)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
            <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
          </svg>
          Copy JSON
        </button>
      </div>
      <pre class="pv-raw-json" id="pvRawJson">${escapeHtml(rawJson)}</pre>
    `;
  }

  /**
   * Update the content area only
   */
  function updateContent() {
    const contentEl = container?.querySelector('#pvContent');
    if (contentEl) {
      contentEl.innerHTML = renderContent();
    }
  }

  /**
   * Update the header
   */
  function updateHeader() {
    const titleEl = container?.querySelector('#pvTitle');
    const badgeEl = container?.querySelector('#pvStatusBadge');

    if (titleEl) {
      titleEl.textContent = currentPrompt?.name || 'Select a Prompt';
    }

    if (badgeEl) {
      const status = currentPrompt?.status || '';
      if (status) {
        badgeEl.textContent = status;
        badgeEl.style.display = 'inline-flex';
        badgeEl.style.background = status === 'Active' ? 'var(--success-dim)' : 'var(--warning-dim)';
        badgeEl.style.color = status === 'Active' ? 'var(--success)' : 'var(--warning)';
        badgeEl.style.borderColor = status === 'Active' ? 'var(--success)' : 'var(--warning)';
      } else {
        badgeEl.style.display = 'none';
      }
    }

    // Update toggle buttons
    container?.querySelectorAll('.prompt-viewer-toggle-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.view === currentView);
    });
  }

  /**
   * Switch between views
   */
  function switchView(view) {
    if (view === currentView) return;

    currentView = view;
    updateHeader();
    updateContent();
  }

  /**
   * Load a prompt by ID
   */
  async function loadPrompt(promptId) {
    if (typeof PromptViewerAPI === 'undefined') {
      console.error('[PromptViewer] API client not available');
      return;
    }

    try {
      currentPrompt = await PromptViewerAPI.fetchPrompt(promptId);
      updateHeader();
      updateContent();

      if (onPromptLoaded) {
        onPromptLoaded(currentPrompt);
      }
    } catch (err) {
      console.error('[PromptViewer] Failed to load prompt:', err);
    }
  }

  /**
   * Set prompt data directly
   */
  function setPrompt(promptData) {
    // Flatten if needed
    if (typeof PromptViewerAPI !== 'undefined' && promptData) {
      currentPrompt = PromptViewerAPI.flattenPrompt(promptData);
    } else {
      currentPrompt = promptData;
    }

    updateHeader();
    updateContent();

    if (onPromptLoaded && currentPrompt) {
      onPromptLoaded(currentPrompt);
    }
  }

  /**
   * Get current prompt
   */
  function getPrompt() {
    return currentPrompt;
  }

  /**
   * Get current view
   */
  function getView() {
    return currentView;
  }

  /**
   * Toggle a collapsible section
   */
  function toggleSection(header) {
    const section = header.closest('.pv-section');
    if (section) {
      section.classList.toggle('collapsed');
    }
  }

  /**
   * Toggle a payload section
   */
  function togglePayloadSection(header) {
    const section = header.closest('.pv-payload-section');
    if (section) {
      section.classList.toggle('collapsed');
    }
  }

  /**
   * Switch data payload tab
   */
  function switchDataTab(tab, view) {
    const container = tab.closest('.pv-section-content');
    if (!container) return;

    // Update tab active state
    container.querySelectorAll('.pv-data-tab').forEach(t => {
      t.classList.toggle('active', t === tab);
    });

    // Show/hide views
    const tableView = container.querySelector('#pvDataTableView');
    const jsonView = container.querySelector('#pvDataJsonView');

    if (tableView) tableView.style.display = view === 'table' ? 'block' : 'none';
    if (jsonView) jsonView.style.display = view === 'json' ? 'block' : 'none';
  }

  /**
   * Copy text to clipboard
   */
  async function copyToClipboard(text) {
    try {
      await navigator.clipboard.writeText(text);
      console.log('[PromptViewer] Copied to clipboard');
      // Could emit an event or show toast here
    } catch (err) {
      console.error('[PromptViewer] Failed to copy:', err);
    }
  }

  /**
   * Show CxU detail
   */
  async function showCxuDetail(cxuId) {
    if (onCxuClicked) {
      onCxuClicked(cxuId);
      return;
    }

    // Default behavior: try to fetch and show in console
    if (typeof PromptViewerAPI !== 'undefined') {
      try {
        const cxu = await PromptViewerAPI.fetchCxu(cxuId);
        console.log('[PromptViewer] CxU detail:', cxu);
      } catch (err) {
        console.warn('[PromptViewer] Failed to fetch CxU:', err);
      }
    }
  }

  /**
   * Set callback for when a prompt is loaded
   */
  function setOnPromptLoaded(callback) {
    onPromptLoaded = callback;
  }

  /**
   * Set callback for when a CxU is clicked
   */
  function setOnCxuClicked(callback) {
    onCxuClicked = callback;
  }

  /**
   * Set data payload for the prompt
   */
  function setDataPayload(payload) {
    options.dataPayload = payload;
    if (currentPrompt) {
      updateContent();
    }
  }

  /**
   * Build the system prompt for current prompt
   */
  function buildSystemPrompt() {
    if (!currentPrompt || typeof PromptPayloadView === 'undefined') return '';
    return PromptPayloadView.buildSystemPrompt(currentPrompt, options.dataPayload);
  }

  /**
   * Build the user prompt for current prompt
   */
  function buildUserPrompt() {
    if (!currentPrompt || typeof PromptPayloadView === 'undefined') return '';
    return PromptPayloadView.buildUserPrompt(currentPrompt, options.dataPayload);
  }

  /**
   * Build the full API request for current prompt
   */
  function buildApiRequest() {
    if (!currentPrompt || typeof PromptPayloadView === 'undefined') return null;
    return PromptPayloadView.buildApiRequest(currentPrompt, options);
  }

  // Callback for opening prompt in resources
  let onPromptClicked = null;

  /**
   * Set callback for when a prompt link is clicked
   */
  function setOnPromptClicked(callback) {
    onPromptClicked = callback;
  }

  /**
   * Open prompt in resources tray
   */
  function openPromptInResources(promptId) {
    if (onPromptClicked) {
      onPromptClicked(promptId);
      return;
    }

    // Default behavior: try to open in PyranaLibrary
    if (typeof PyranaLibrary !== 'undefined') {
      PyranaLibrary.openItem(promptId);
    } else {
      console.log('[PromptViewer] Prompt clicked:', promptId);
    }
  }

  /**
   * Handle close button click
   */
  function handleClose() {
    if (onClose) {
      onClose();
    } else {
      // Default behavior: clear the prompt
      setPrompt(null);
    }
  }

  /**
   * Set callback for when close button is clicked
   */
  function setOnClose(callback) {
    onClose = callback;
  }

  /**
   * Destroy the component
   */
  function destroy() {
    if (container) {
      container.innerHTML = '';
    }
    container = null;
    currentPrompt = null;
    currentView = 'formatted';
    options = {};
    onPromptLoaded = null;
    onCxuClicked = null;
    onPromptClicked = null;
    onClose = null;
  }

  // Public API
  return {
    init,
    loadPrompt,
    setPrompt,
    getPrompt,
    getView,
    switchView,
    toggleSection,
    togglePayloadSection,
    switchDataTab,
    copyToClipboard,
    showCxuDetail,
    setOnPromptLoaded,
    setOnCxuClicked,
    setOnPromptClicked,
    setOnClose,
    handleClose,
    setDataPayload,
    buildSystemPrompt,
    buildUserPrompt,
    buildApiRequest,
    openPromptInResources,
    destroy
  };
})();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = PromptViewer;
}
