/**
 * Output Viewer Component
 *
 * A reusable component for rendering agent output with:
 * - Markdown rendering (using marked.js)
 * - CxU pill citations
 * - Raw/Rendered toggle
 * - Copy functionality
 *
 * Usage:
 *   const viewer = OutputViewer.create(container, {
 *     content: 'Markdown with [[CxURef:my-cxu]] citations',
 *     cxuList: [...],  // Optional: CxU objects for citation lookup
 *     showRaw: false   // Optional: start in rendered mode
 *   });
 *
 *   viewer.setContent(newContent);
 *   viewer.setCxuList(cxuList);
 *   viewer.toggleView();
 */

const OutputViewer = (function() {
  'use strict';

  // Debug mode - set to true to see console logs
  const DEBUG = true;

  function log(...args) {
    if (DEBUG) console.log('[OutputViewer]', ...args);
  }

  // CSS styles for the component
  const STYLES = `
    .output-viewer {
      background: var(--bg-tertiary, #1a1a1d);
      border-radius: 12px;
      overflow: visible;
      border: 1px solid var(--border, #1e1e22);
      position: relative;
    }

    .output-viewer-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 12px;
      background: var(--bg-secondary, #111113);
      border-bottom: 1px solid var(--border, #1e1e22);
      border-radius: 12px 12px 0 0;
    }

    .output-viewer-tabs {
      display: flex;
      gap: 4px;
    }

    .output-viewer-tab {
      padding: 6px 12px;
      background: transparent;
      border: 1px solid transparent;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 500;
      color: var(--text-muted, #71717a);
      cursor: pointer;
      transition: all 0.15s;
    }

    .output-viewer-tab:hover {
      color: var(--text-secondary, #a1a1aa);
      background: var(--bg-hover, #1e1e22);
    }

    .output-viewer-tab.active {
      background: var(--bg-tertiary, #1a1a1d);
      border-color: var(--border, #1e1e22);
      color: var(--text-primary, #fafafa);
    }

    .output-viewer-actions {
      display: flex;
      gap: 8px;
    }

    .output-viewer-btn {
      display: flex;
      align-items: center;
      gap: 4px;
      padding: 5px 10px;
      background: var(--bg-tertiary, #1a1a1d);
      border: 1px solid var(--border, #1e1e22);
      border-radius: 6px;
      font-size: 11px;
      font-weight: 500;
      color: var(--text-muted, #71717a);
      cursor: pointer;
      transition: all 0.15s;
    }

    .output-viewer-btn:hover {
      background: var(--bg-hover, #1e1e22);
      color: var(--text-primary, #fafafa);
    }

    .output-viewer-btn.copied {
      background: var(--success-dim, rgba(34, 197, 94, 0.12));
      border-color: var(--success, #22c55e);
      color: var(--success, #22c55e);
    }

    .output-viewer-btn svg {
      width: 14px;
      height: 14px;
    }

    .output-viewer-content {
      padding: 16px;
      padding-top: 20px;
      max-height: 600px;
      overflow-y: auto;
      overflow-x: hidden;
      background: var(--bg-tertiary, #1a1a1d);
      border-radius: 0 0 12px 12px;
    }

    .output-viewer-raw {
      font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
      font-size: 12px;
      line-height: 1.6;
      color: var(--text-secondary, #a1a1aa);
      white-space: pre-wrap;
      word-break: break-word;
    }

    .output-viewer-rendered {
      font-size: 14px;
      line-height: 1.7;
      color: var(--text-primary, #fafafa);
    }

    /* Ensure CxU pills display inline */
    .output-viewer-rendered .cxu-pill {
      display: inline-flex;
      vertical-align: middle;
    }

    /* Markdown styles */
    .output-viewer-rendered h1,
    .output-viewer-rendered h2,
    .output-viewer-rendered h3,
    .output-viewer-rendered h4,
    .output-viewer-rendered h5,
    .output-viewer-rendered h6 {
      margin-top: 1.25em;
      margin-bottom: 0.5em;
      font-weight: 600;
      color: var(--text-primary, #fafafa);
      line-height: 1.3;
    }

    /* Remove top margin from first element */
    .output-viewer-rendered > :first-child {
      margin-top: 0;
    }

    .output-viewer-rendered h1 { font-size: 1.5em; }
    .output-viewer-rendered h2 { font-size: 1.25em; }
    .output-viewer-rendered h3 { font-size: 1.1em; }
    .output-viewer-rendered h4 { font-size: 1em; }

    .output-viewer-rendered p {
      margin-top: 0;
      margin-bottom: 1em;
    }

    .output-viewer-rendered p:last-child {
      margin-bottom: 0;
    }

    .output-viewer-rendered ul,
    .output-viewer-rendered ol {
      margin-top: 0;
      margin-bottom: 1em;
      padding-left: 1.5em;
    }

    .output-viewer-rendered li {
      margin-bottom: 0.4em;
      line-height: 1.6;
    }

    .output-viewer-rendered li:last-child {
      margin-bottom: 0;
    }

    .output-viewer-rendered li > ul,
    .output-viewer-rendered li > ol {
      margin-top: 0.4em;
      margin-bottom: 0;
    }

    .output-viewer-rendered strong,
    .output-viewer-rendered b {
      font-weight: 600;
      color: var(--text-primary, #fafafa);
    }

    .output-viewer-rendered em,
    .output-viewer-rendered i {
      font-style: italic;
    }

    .output-viewer-rendered code {
      background: var(--bg-secondary, #111113);
      padding: 2px 6px;
      border-radius: 4px;
      font-family: 'SF Mono', Monaco, monospace;
      font-size: 0.9em;
      color: var(--pyrana-orange, #ed7445);
    }

    .output-viewer-rendered pre {
      background: var(--bg-secondary, #111113);
      padding: 16px;
      border-radius: 8px;
      overflow-x: auto;
      margin-bottom: 1em;
    }

    .output-viewer-rendered pre code {
      background: transparent;
      padding: 0;
      color: var(--text-secondary, #a1a1aa);
    }

    .output-viewer-rendered blockquote {
      border-left: 3px solid var(--accent, #22c55e);
      padding-left: 16px;
      margin: 1em 0;
      color: var(--text-secondary, #a1a1aa);
      font-style: italic;
    }

    .output-viewer-rendered table {
      width: 100%;
      border-collapse: collapse;
      margin-bottom: 1em;
    }

    .output-viewer-rendered th,
    .output-viewer-rendered td {
      padding: 8px 12px;
      border: 1px solid var(--border, #1e1e22);
      text-align: left;
    }

    .output-viewer-rendered th {
      background: var(--bg-secondary, #111113);
      font-weight: 600;
    }

    .output-viewer-rendered a {
      color: var(--color-cxu, #3b82f6);
      text-decoration: none;
    }

    .output-viewer-rendered a:hover {
      text-decoration: underline;
    }

    .output-viewer-rendered hr {
      border: none;
      border-top: 1px solid var(--border, #1e1e22);
      margin: 1.5em 0;
    }

    .output-viewer-rendered img {
      max-width: 100%;
      border-radius: 8px;
    }

    /* Citation highlight */
    .output-viewer-rendered .cxu-pill {
      vertical-align: middle;
    }

    /* Empty state */
    .output-viewer-empty {
      text-align: center;
      padding: 40px;
      color: var(--text-muted, #71717a);
    }

    .output-viewer-empty svg {
      width: 48px;
      height: 48px;
      margin-bottom: 12px;
      opacity: 0.5;
    }
  `;

  // Track if styles have been injected
  let stylesInjected = false;

  /**
   * Inject component styles
   */
  function injectStyles() {
    if (stylesInjected) return;

    const styleEl = document.createElement('style');
    styleEl.id = 'output-viewer-styles';
    styleEl.textContent = STYLES;
    document.head.appendChild(styleEl);
    stylesInjected = true;
  }

  /**
   * Escape HTML special characters
   */
  function escapeHtml(str) {
    return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /**
   * Check if marked.js is available
   */
  function hasMarked() {
    return typeof marked !== 'undefined';
  }

  /**
   * Check if CxuPill component is available
   */
  function hasCxuPill() {
    return typeof CxuPill !== 'undefined';
  }

  /**
   * Render markdown to HTML
   */
  function renderMarkdown(content, cxuList = []) {
    if (!content) return '';

    log('Input content length:', content.length);
    log('First 100 chars:', content.substring(0, 100));

    let text = content;

    // Strip outer markdown/text code fences if present (LLM sometimes wraps response)
    const originalLength = text.length;
    text = stripOuterCodeFence(text);
    if (text.length !== originalLength) {
      log('Stripped code fence, new length:', text.length);
    }

    // Parse markdown
    if (hasMarked()) {
      log('marked.js available, parsing markdown');
      try {
        // Configure marked for GFM (GitHub Flavored Markdown)
        marked.setOptions({
          breaks: true,       // Convert \n to <br>
          gfm: true,          // GitHub Flavored Markdown
          headerIds: false,   // Don't add IDs to headers
          mangle: false       // Don't mangle email addresses
        });

        const html = marked.parse(text);
        log('Parsed HTML length:', html.length);
        log('First 200 chars of HTML:', html.substring(0, 200));

        // Process CxU citations in the rendered HTML
        if (hasCxuPill()) {
          log('Processing CxU citations, count:', cxuList.length);
          return CxuPill.processMarkdownCitations(html, cxuList);
        }

        return html;
      } catch (err) {
        console.error('[OutputViewer] Markdown parsing failed:', err);
        // Fall through to plain text rendering
      }
    } else {
      log('marked.js NOT available, using fallback');
    }

    // Fallback: escape HTML and convert newlines to <br>
    let html = escapeHtml(text).replace(/\n/g, '<br>');

    // Still try to process CxU citations
    if (hasCxuPill()) {
      html = CxuPill.processMarkdownCitations(html, cxuList);
    }

    return html;
  }

  /**
   * Strip outer code fences that LLMs sometimes wrap responses in
   */
  function stripOuterCodeFence(text) {
    if (!text) return text;

    // Trim whitespace first
    let trimmed = text.trim();

    // Split into lines for processing
    const lines = trimmed.split('\n');
    if (lines.length < 3) return text; // Need at least opener, content, closer

    const firstLine = lines[0].trim();

    // Check if first line is a code fence opener (```markdown, ```text, ```md, or just ```)
    if (/^```(?:markdown|text|md)?$/i.test(firstLine)) {
      log('Detected opening code fence:', firstLine);

      // Find the LAST line that is just ``` (the closing fence)
      let closingIndex = -1;
      for (let i = lines.length - 1; i > 0; i--) {
        if (lines[i].trim() === '```') {
          closingIndex = i;
          break;
        }
      }

      if (closingIndex > 0) {
        log('Found closing fence at line:', closingIndex);
        // Extract content between fences
        const content = lines.slice(1, closingIndex).join('\n');
        return content.trim();
      } else {
        log('No closing fence found, stripping only opening fence');
        // No closing fence found - just strip the opening line
        return lines.slice(1).join('\n').trim();
      }
    }

    return text;
  }

  /**
   * Create an output viewer instance
   */
  function create(container, options = {}) {
    injectStyles();

    // Initialize CxU pill if available
    if (hasCxuPill()) {
      CxuPill.init();
    }

    // State
    let state = {
      content: options.content || '',
      cxuList: options.cxuList || [],
      showRaw: options.showRaw || false
    };

    // Render initial HTML
    container.innerHTML = generateHtml(state);

    // Bind events
    bindEvents(container, state);

    // Return viewer API
    return {
      setContent(content) {
        state.content = content;
        updateContent(container, state);
      },

      setCxuList(cxuList) {
        state.cxuList = cxuList;
        if (!state.showRaw) {
          updateContent(container, state);
        }
      },

      toggleView() {
        state.showRaw = !state.showRaw;
        updateView(container, state);
      },

      showRaw() {
        state.showRaw = true;
        updateView(container, state);
      },

      showRendered() {
        state.showRaw = false;
        updateView(container, state);
      },

      getContent() {
        return state.content;
      },

      destroy() {
        container.innerHTML = '';
      }
    };
  }

  /**
   * Generate viewer HTML
   */
  function generateHtml(state) {
    const copyIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
      <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
    </svg>`;

    const checkIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M5 12l5 5L20 7"/>
    </svg>`;

    return `
      <div class="output-viewer">
        <div class="output-viewer-toolbar">
          <div class="output-viewer-tabs">
            <button class="output-viewer-tab ${!state.showRaw ? 'active' : ''}" data-view="rendered">
              Rendered
            </button>
            <button class="output-viewer-tab ${state.showRaw ? 'active' : ''}" data-view="raw">
              Raw
            </button>
          </div>
          <div class="output-viewer-actions">
            <button class="output-viewer-btn" data-action="copy">
              ${copyIcon}
              Copy
            </button>
          </div>
        </div>
        <div class="output-viewer-content">
          ${renderContent(state)}
        </div>
      </div>
    `;
  }

  /**
   * Render content based on view mode
   */
  function renderContent(state) {
    if (!state.content) {
      return `
        <div class="output-viewer-empty">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M9 12h6m-3-3v6m-5 5h10a2 2 0 002-2V7l-5-5H6a2 2 0 00-2 2v14a2 2 0 002 2z"/>
          </svg>
          <div>No content to display</div>
        </div>
      `;
    }

    if (state.showRaw) {
      return `<div class="output-viewer-raw">${escapeHtml(state.content)}</div>`;
    }

    const rendered = renderMarkdown(state.content, state.cxuList);
    return `<div class="output-viewer-rendered">${rendered}</div>`;
  }

  /**
   * Bind event listeners
   */
  function bindEvents(container, state) {
    // Tab clicks
    container.querySelectorAll('.output-viewer-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        const view = tab.dataset.view;
        state.showRaw = view === 'raw';
        updateView(container, state);
      });
    });

    // Copy button
    const copyBtn = container.querySelector('[data-action="copy"]');
    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        copyToClipboard(state.content, copyBtn);
      });
    }
  }

  /**
   * Update content display
   */
  function updateContent(container, state) {
    const contentEl = container.querySelector('.output-viewer-content');
    if (contentEl) {
      contentEl.innerHTML = renderContent(state);
    }
  }

  /**
   * Update view mode (tabs and content)
   */
  function updateView(container, state) {
    // Update tabs
    container.querySelectorAll('.output-viewer-tab').forEach(tab => {
      const isActive = (tab.dataset.view === 'raw') === state.showRaw;
      tab.classList.toggle('active', isActive);
    });

    // Update content
    updateContent(container, state);
  }

  /**
   * Copy content to clipboard
   */
  async function copyToClipboard(content, button) {
    try {
      await navigator.clipboard.writeText(content);

      // Show success state
      const originalHtml = button.innerHTML;
      button.classList.add('copied');
      button.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M5 12l5 5L20 7"/>
        </svg>
        Copied!
      `;

      // Reset after delay
      setTimeout(() => {
        button.classList.remove('copied');
        button.innerHTML = originalHtml;
      }, 2000);
    } catch (err) {
      console.error('[OutputViewer] Copy failed:', err);
    }
  }

  // Public API
  return {
    create,
    renderMarkdown,
    injectStyles
  };
})();

// Make available globally
if (typeof window !== 'undefined') {
  window.OutputViewer = OutputViewer;
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = OutputViewer;
}
