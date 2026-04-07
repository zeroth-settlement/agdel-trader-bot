/**
 * Output Viewer Component
 *
 * A reusable component for displaying agent output with:
 * - Output header with title and metrics
 * - OutputViewer integration for markdown rendering with CxU pills
 * - Metadata tray with tabs for Run params, CxUs, and Agent info
 *
 * Usage:
 *   // Initialize the component
 *   const panel = OutputViewerPanel.create(document.getElementById('outputContainer'), {
 *     title: 'Agent Output',
 *     onCxuClick: (cxuId) => { ... }
 *   });
 *
 *   // Display output
 *   panel.setOutput({
 *     content: 'Markdown content...',
 *     cxuList: [...],
 *     metrics: {
 *       model: 'gemini-2.0-flash',
 *       temperature: 0.2,
 *       promptTokens: 1000,
 *       outputTokens: 500,
 *       totalTokens: 1500,
 *       executionTimeMs: 2500
 *     },
 *     agent: {
 *       agent_id: '...',
 *       name: 'Agent Name',
 *       prompt_id: '...'
 *     }
 *   });
 *
 *   // Clear output
 *   panel.clear();
 */

const OutputViewerPanel = (function() {
  'use strict';

  // Inject styles on load
  function injectStyles() {
    if (typeof OutputViewerStyles !== 'undefined') {
      OutputViewerStyles.inject();
    }
  }

  /**
   * Create an Output Viewer instance
   */
  function create(containerEl, config = {}) {
    const state = {
      container: containerEl,
      title: config.title || 'Agent Output',
      onCxuClick: config.onCxuClick || null,
      onClose: config.onClose || null,
      showCloseButton: config.showCloseButton !== false, // default true
      currentTab: 'run',
      collapsed: false,
      outputViewer: null,
      data: null
    };

    // Element references
    let elements = {};

    // Initialize
    function init() {
      console.log('[OutputViewerPanel] Initializing...');
      console.log('[OutputViewerPanel] Container:', state.container);
      injectStyles();
      render();
      console.log('[OutputViewerPanel] Rendered HTML, elements:', elements);
      bindEvents();
      console.log('[OutputViewerPanel] Events bound, ready');
    }

    // Render the component
    function render() {
      state.container.innerHTML = `
        <div class="output-viewer-panel">
          <div class="output-viewer-header">
            <div class="output-viewer-title">${escapeHtml(state.title)}</div>
            ${state.showCloseButton ? `
              <button class="output-viewer-close-btn" title="Close">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="18" y1="6" x2="6" y2="18"/>
                  <line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            ` : ''}
          </div>

          <div class="output-viewer-panel-content">
            <div class="output-viewer-empty">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
              </svg>
              <div class="output-viewer-empty-title">No output yet</div>
              <div class="output-viewer-empty-desc">Select an agent and run it to see output</div>
            </div>
          </div>

          <div class="output-viewer-metadata">
            <div class="output-viewer-metadata-tabs">
              <button class="output-viewer-metadata-tab active" data-tab="run">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
                </svg>
                Run
              </button>
              <button class="output-viewer-metadata-tab" data-tab="cxus">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z"/>
                  <path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z"/>
                </svg>
                CxUs
                <span class="output-viewer-metadata-count" data-count="cxus">0</span>
              </button>
              <button class="output-viewer-metadata-tab" data-tab="agent">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="3"/>
                  <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
                </svg>
                Agent
              </button>
              <button class="output-viewer-metadata-toggle" title="Toggle metadata">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M18 15l-6-6-6 6"/>
                </svg>
              </button>
            </div>

            <div class="output-viewer-metadata-content">
              <!-- Run Parameters Panel -->
              <div class="output-viewer-metadata-panel active" data-panel="run">
                <div class="output-viewer-params-grid">
                  <div class="output-viewer-param">
                    <span class="output-viewer-param-label">Model</span>
                    <span class="output-viewer-param-value" data-param="model">-</span>
                  </div>
                  <div class="output-viewer-param">
                    <span class="output-viewer-param-label">Temperature</span>
                    <span class="output-viewer-param-value" data-param="temperature">-</span>
                  </div>
                  <div class="output-viewer-param">
                    <span class="output-viewer-param-label">Prompt Tokens</span>
                    <span class="output-viewer-param-value" data-param="promptTokens">-</span>
                  </div>
                  <div class="output-viewer-param">
                    <span class="output-viewer-param-label">Output Tokens</span>
                    <span class="output-viewer-param-value" data-param="outputTokens">-</span>
                  </div>
                  <div class="output-viewer-param">
                    <span class="output-viewer-param-label">Total Tokens</span>
                    <span class="output-viewer-param-value" data-param="totalTokens">-</span>
                  </div>
                  <div class="output-viewer-param">
                    <span class="output-viewer-param-label">Execution Time</span>
                    <span class="output-viewer-param-value" data-param="execTime">-</span>
                  </div>
                </div>
              </div>

              <!-- CxU References Panel -->
              <div class="output-viewer-metadata-panel" data-panel="cxus">
                <div class="output-viewer-ref-list">
                  <div class="output-viewer-ref-empty">No CxUs referenced</div>
                </div>
              </div>

              <!-- Agent Info Panel -->
              <div class="output-viewer-metadata-panel" data-panel="agent">
                <div class="output-viewer-params-grid">
                  <div class="output-viewer-param">
                    <span class="output-viewer-param-label">Agent ID</span>
                    <span class="output-viewer-param-value" data-param="agentId">-</span>
                  </div>
                  <div class="output-viewer-param">
                    <span class="output-viewer-param-label">Agent Name</span>
                    <span class="output-viewer-param-value" data-param="agentName">-</span>
                  </div>
                  <div class="output-viewer-param">
                    <span class="output-viewer-param-label">Prompt ID</span>
                    <span class="output-viewer-param-value" data-param="promptId">-</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      `;

      // Cache element references
      elements = {
        panel: state.container.querySelector('.output-viewer-panel'),
        header: state.container.querySelector('.output-viewer-header'),
        title: state.container.querySelector('.output-viewer-title'),
        content: state.container.querySelector('.output-viewer-panel-content'),
        metadata: state.container.querySelector('.output-viewer-metadata'),
        tabs: state.container.querySelectorAll('.output-viewer-metadata-tab'),
        panels: state.container.querySelectorAll('.output-viewer-metadata-panel'),
        toggle: state.container.querySelector('.output-viewer-metadata-toggle'),
        refList: state.container.querySelector('.output-viewer-ref-list')
      };
    }

    // Bind event handlers
    function bindEvents() {
      // Tab switching
      elements.tabs.forEach(tab => {
        tab.addEventListener('click', () => {
          const tabId = tab.dataset.tab;
          switchTab(tabId);
        });
      });

      // Toggle metadata tray
      elements.toggle.addEventListener('click', () => {
        state.collapsed = !state.collapsed;
        elements.metadata.classList.toggle('collapsed', state.collapsed);
      });

      // Close button
      const closeBtn = state.container.querySelector('.output-viewer-close-btn');
      if (closeBtn) {
        closeBtn.addEventListener('click', () => {
          if (state.onClose) {
            state.onClose();
          } else {
            // Default behavior: clear the panel
            clear();
          }
        });
      }
    }

    // Switch metadata tab
    function switchTab(tabId) {
      state.currentTab = tabId;

      elements.tabs.forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === tabId);
      });

      elements.panels.forEach(panel => {
        panel.classList.toggle('active', panel.dataset.panel === tabId);
      });
    }

    // Set output content
    function setOutput(data) {
      state.data = data;

      // Update title if provided
      if (data.title) {
        state.title = data.title;
        elements.title.textContent = data.title;
      }

      // Update run params panel (bottom metadata)
      if (data.metrics) {
        setParam('model', data.metrics.modelName || data.metrics.model || '-');
        setParam('temperature', data.metrics.temperature ?? '-');
        setParam('promptTokens', data.metrics.promptTokens?.toLocaleString() || '-');
        setParam('outputTokens', data.metrics.outputTokens?.toLocaleString() || '-');
        setParam('totalTokens', data.metrics.totalTokens?.toLocaleString() || '-');
        setParam('execTime', data.metrics.executionTimeMs ? `${data.metrics.executionTimeMs}ms` : '-');
      }

      // Update agent info
      if (data.agent) {
        setParam('agentId', truncateId(data.agent.agent_id));
        setParam('agentName', data.agent.name || '-');
        setParam('promptId', truncateId(data.agent.prompt_id));
      }

      // Update CxU references
      const cxuList = data.cxuList || [];
      setCount('cxus', cxuList.length);

      if (cxuList.length > 0) {
        elements.refList.innerHTML = cxuList.map(cxu => `
          <div class="output-viewer-cxu-item" data-cxu-id="${cxu.cxu_id}">
            ${escapeHtml(cxu.alias)}
          </div>
        `).join('');

        // Bind click handlers for CxU items
        elements.refList.querySelectorAll('.output-viewer-cxu-item').forEach(item => {
          item.addEventListener('click', () => {
            const cxuId = item.dataset.cxuId;
            if (state.onCxuClick) {
              state.onCxuClick(cxuId);
            } else if (typeof openCxuExpanded === 'function') {
              openCxuExpanded(cxuId);
            } else if (typeof openCxuInLibraryTray === 'function') {
              openCxuInLibraryTray(cxuId);
            }
          });
        });
      } else {
        elements.refList.innerHTML = '<div class="output-viewer-ref-empty">No CxUs referenced</div>';
      }

      // Render output content with OutputViewer
      console.log('[OutputViewerPanel] Rendering content, OutputViewer available:', typeof OutputViewer !== 'undefined');
      console.log('[OutputViewerPanel] Content length:', data.content?.length, 'CxUs:', cxuList.length);

      if (data.content && typeof OutputViewer !== 'undefined') {
        elements.content.innerHTML = '';
        console.log('[OutputViewerPanel] Creating OutputViewer in:', elements.content);
        state.outputViewer = OutputViewer.create(elements.content, {
          content: data.content,
          cxuList: cxuList,
          showRaw: false
        });
        console.log('[OutputViewerPanel] OutputViewer created:', state.outputViewer);
      } else if (data.content) {
        console.warn('[OutputViewerPanel] OutputViewer not available, using plain text');
        elements.content.innerHTML = `<div style="padding: 16px; white-space: pre-wrap;">${escapeHtml(data.content)}</div>`;
      } else {
        console.warn('[OutputViewerPanel] No content to display');
      }
    }

    // Helper to set param value
    function setParam(key, value) {
      const el = state.container.querySelector(`[data-param="${key}"]`);
      if (el) el.textContent = value;
    }

    // Helper to set count badge
    function setCount(key, value) {
      const el = state.container.querySelector(`[data-count="${key}"]`);
      if (el) el.textContent = value;
    }

    // Helper to truncate ID
    function truncateId(id) {
      if (!id) return '-';
      return id.length > 16 ? id.substring(0, 16) + '...' : id;
    }

    // Clear output
    function clear() {
      state.data = null;
      state.outputViewer = null;

      elements.content.innerHTML = `
        <div class="output-viewer-empty">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
          <div class="output-viewer-empty-title">No output yet</div>
          <div class="output-viewer-empty-desc">Select an agent and run it to see output</div>
        </div>
      `;

      // Reset params
      ['model', 'temperature', 'promptTokens', 'outputTokens', 'totalTokens', 'execTime', 'agentId', 'agentName', 'promptId'].forEach(key => {
        setParam(key, '-');
      });

      setCount('cxus', 0);
      elements.refList.innerHTML = '<div class="output-viewer-ref-empty">No CxUs referenced</div>';
    }

    // Set title
    function setTitle(title) {
      state.title = title;
      elements.title.textContent = title;
    }

    // Initialize and return public API
    init();

    return {
      setOutput,
      clear,
      setTitle,
      switchTab,
      getState: () => ({ ...state })
    };
  }

  // Escape HTML utility
  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /**
   * Create a compact preview of output content
   * @param {HTMLElement} containerEl - Container element
   * @param {Object} options - Preview options
   * @param {string} options.content - The markdown content to preview
   * @param {Array} options.cxuList - List of CxUs for pill rendering
   * @param {number} options.maxHeight - Max height in pixels (default: 120)
   * @param {boolean} options.fadeBottom - Show gradient fade at bottom (default: true)
   * @param {Function} options.onCxuClick - Callback when CxU is clicked
   */
  function createPreview(containerEl, options = {}) {
    const {
      content = '',
      cxuList = [],
      maxHeight = 120,
      fadeBottom = true,
      onCxuClick = null
    } = options;

    injectStyles();

    // Create preview wrapper
    const wrapper = document.createElement('div');
    wrapper.className = 'output-viewer-preview';
    wrapper.style.cssText = `
      position: relative;
      max-height: ${maxHeight}px;
      overflow: hidden;
    `;

    // Create content container
    const contentContainer = document.createElement('div');
    contentContainer.className = 'output-viewer-preview-content';

    // Render with OutputViewer if available, otherwise plain text
    if (content && typeof OutputViewer !== 'undefined') {
      OutputViewer.create(contentContainer, {
        content: content,
        cxuList: cxuList,
        showRaw: false,
        compact: true
      });
    } else if (content) {
      // Fallback: render as simple text with basic markdown
      const previewText = content.substring(0, 500);
      contentContainer.innerHTML = `<div class="output-viewer-preview-text">${escapeHtml(previewText)}${content.length > 500 ? '...' : ''}</div>`;
    } else {
      contentContainer.innerHTML = '<div class="output-viewer-preview-empty">No output</div>';
    }

    wrapper.appendChild(contentContainer);

    // Add fade gradient at bottom if enabled
    if (fadeBottom && content && content.length > 100) {
      const fadeEl = document.createElement('div');
      fadeEl.className = 'output-viewer-preview-fade';
      wrapper.appendChild(fadeEl);
    }

    // Clear container and add preview
    containerEl.innerHTML = '';
    containerEl.appendChild(wrapper);

    // Return API for external control
    return {
      getContent: () => content,
      destroy: () => {
        containerEl.innerHTML = '';
      }
    };
  }

  return {
    create,
    createPreview,
    injectStyles
  };
})();

// Backwards compatibility alias
const OutputPanel = OutputViewerPanel;

// Export for Node.js if needed
if (typeof module !== 'undefined' && module.exports) {
  module.exports = OutputViewerPanel;
}
