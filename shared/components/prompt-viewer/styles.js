/**
 * Prompt Viewer Component - Styles
 *
 * Provides CSS styles for the prompt viewer component.
 * Can be injected into any page to style the prompt viewer.
 */

const PromptViewerStyles = (function() {
  'use strict';

  const CSS = `
    /* Prompt Viewer Container */
    .prompt-viewer {
      display: flex;
      flex-direction: column;
      height: 100%;
      background: var(--bg-primary);
      color: var(--text-primary);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, sans-serif;
      font-size: 14px;
    }

    /* Prompt Viewer Header */
    .prompt-viewer-header {
      padding: 14px 16px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: var(--bg-secondary);
      flex-shrink: 0;
    }

    .prompt-viewer-title {
      font-size: 14px;
      font-weight: 600;
      color: var(--text-primary);
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .prompt-viewer-title-badge {
      padding: 2px 8px;
      background: var(--color-prompt-dim);
      border: 1px solid var(--color-prompt);
      border-radius: 4px;
      font-size: 10px;
      font-weight: 600;
      color: var(--color-prompt);
    }

    /* Header Actions */
    .prompt-viewer-header-actions {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    /* Close Button */
    .prompt-viewer-close-btn {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      background: transparent;
      border: 1px solid transparent;
      border-radius: 6px;
      color: var(--text-muted, #71717a);
      cursor: pointer;
      transition: all 0.15s;
    }

    .prompt-viewer-close-btn:hover {
      background: var(--bg-hover, #1e1e22);
      border-color: var(--border, #1e1e22);
      color: var(--text-primary, #fafafa);
    }

    .prompt-viewer-close-btn svg {
      width: 16px;
      height: 16px;
    }

    /* View Toggle */
    .prompt-viewer-toggle {
      display: flex;
      gap: 4px;
      background: var(--bg-tertiary);
      padding: 3px;
      border-radius: 6px;
    }

    .prompt-viewer-toggle-btn {
      padding: 6px 12px;
      border: none;
      border-radius: 4px;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.15s;
      background: transparent;
      color: var(--text-muted);
    }

    .prompt-viewer-toggle-btn.active {
      background: var(--bg-card);
      color: var(--text-primary);
    }

    .prompt-viewer-toggle-btn:hover:not(.active) {
      color: var(--text-secondary);
    }

    /* Prompt Viewer Content */
    .prompt-viewer-content {
      flex: 1;
      overflow: auto;
      padding: 16px;
    }

    /* Collapsible Sections */
    .pv-section {
      margin-bottom: 16px;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
    }

    .pv-section-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 14px;
      background: var(--bg-tertiary);
      cursor: pointer;
      user-select: none;
      transition: background 0.15s;
    }

    .pv-section-header:hover {
      background: var(--bg-hover);
    }

    .pv-section-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-primary);
    }

    .pv-section-title svg {
      width: 12px;
      height: 12px;
      color: var(--color-prompt);
      transition: transform 0.2s;
    }

    .pv-section.collapsed .pv-section-title svg {
      transform: rotate(-90deg);
    }

    .pv-section-badge {
      font-size: 10px;
      padding: 2px 8px;
      background: var(--bg-secondary);
      border-radius: 10px;
      color: var(--text-muted);
    }

    .pv-section-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .pv-section-content {
      padding: 14px;
      border-top: 1px solid var(--border);
    }

    .pv-section.collapsed .pv-section-content {
      display: none;
    }

    /* Field Groups */
    .pv-field-group {
      margin-bottom: 14px;
    }

    .pv-field-group:last-child {
      margin-bottom: 0;
    }

    .pv-field-label {
      display: block;
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
      margin-bottom: 4px;
    }

    .pv-field-value {
      font-size: 13px;
      color: var(--text-primary);
      line-height: 1.5;
    }

    .pv-field-value.mono {
      font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
      font-size: 11px;
      padding: 6px 10px;
      background: var(--bg-tertiary);
      border-radius: 4px;
      word-break: break-all;
    }

    .pv-field-value.pv-link {
      cursor: pointer;
      transition: all 0.15s;
    }

    .pv-field-value.pv-link:hover {
      color: var(--color-prompt);
      text-decoration: underline;
    }

    .pv-field-value.multiline {
      white-space: pre-wrap;
      padding: 10px 12px;
      background: var(--bg-tertiary);
      border-radius: 6px;
      font-size: 12px;
    }

    /* Markdown rendered content */
    .pv-field-value.pv-markdown {
      padding: 10px 12px;
      background: var(--bg-tertiary);
      border-radius: 6px;
      font-size: 12px;
      line-height: 1.6;
    }

    .pv-field-value.pv-markdown p {
      margin: 0 0 0.75em 0;
    }

    .pv-field-value.pv-markdown p:last-child {
      margin-bottom: 0;
    }

    .pv-field-value.pv-markdown ul,
    .pv-field-value.pv-markdown ol {
      margin: 0 0 0.75em 0;
      padding-left: 1.5em;
    }

    .pv-field-value.pv-markdown li {
      margin-bottom: 0.25em;
    }

    .pv-field-value.pv-markdown strong {
      font-weight: 600;
      color: var(--text-primary);
    }

    .pv-field-value.pv-markdown code {
      background: var(--bg-secondary);
      padding: 1px 4px;
      border-radius: 3px;
      font-family: 'SF Mono', Monaco, monospace;
      font-size: 0.9em;
    }

    .pv-field-value.pv-markdown pre {
      background: var(--bg-secondary);
      padding: 8px 10px;
      border-radius: 4px;
      overflow-x: auto;
      margin: 0.75em 0;
    }

    .pv-field-value.pv-markdown pre code {
      background: transparent;
      padding: 0;
    }

    .pv-field-value.pv-markdown h1,
    .pv-field-value.pv-markdown h2,
    .pv-field-value.pv-markdown h3,
    .pv-field-value.pv-markdown h4 {
      margin: 0.75em 0 0.5em 0;
      font-weight: 600;
      color: var(--text-primary);
    }

    .pv-field-value.pv-markdown h1:first-child,
    .pv-field-value.pv-markdown h2:first-child,
    .pv-field-value.pv-markdown h3:first-child,
    .pv-field-value.pv-markdown h4:first-child {
      margin-top: 0;
    }

    .pv-field-value.pv-markdown blockquote {
      margin: 0.75em 0;
      padding-left: 12px;
      border-left: 3px solid var(--border-light);
      color: var(--text-secondary);
    }

    .pv-field-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 14px;
    }

    /* CxU List */
    .pv-cxu-list {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 12px;
    }

    .pv-cxu-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 10px;
      background: var(--color-cxu-dim);
      border: 1px solid var(--color-cxu);
      border-radius: 5px;
      font-size: 11px;
      color: var(--color-cxu);
      cursor: pointer;
      transition: all 0.15s;
    }

    .pv-cxu-chip:hover {
      background: var(--color-cxu);
      color: white;
    }

    .pv-cxu-chip-alias {
      font-weight: 600;
    }

    .pv-cxu-chip-id {
      font-family: 'SF Mono', Monaco, monospace;
      font-size: 9px;
      opacity: 0.7;
    }

    .pv-cxu-card {
      padding: 10px 12px;
      background: var(--bg-tertiary);
      border-radius: 6px;
      margin-bottom: 8px;
      border-left: 3px solid var(--color-cxu);
    }

    .pv-cxu-card:last-child {
      margin-bottom: 0;
    }

    .pv-cxu-card.pv-cxu-card-clickable {
      cursor: pointer;
      transition: all 0.15s;
    }

    .pv-cxu-card.pv-cxu-card-clickable:hover {
      background: var(--bg-hover);
      border-left-color: var(--color-cxu);
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    }

    .pv-cxu-card-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 6px;
    }

    .pv-cxu-card-alias {
      font-weight: 600;
      color: var(--color-cxu);
      font-size: 12px;
    }

    .pv-cxu-card-type {
      font-size: 9px;
      color: var(--text-muted);
    }

    .pv-cxu-card-claim {
      font-size: 12px;
      color: var(--text-secondary);
      line-height: 1.4;
    }

    .pv-cxu-card-id {
      font-size: 9px;
      color: var(--text-muted);
      margin-top: 6px;
      font-family: 'SF Mono', Monaco, monospace;
    }

    /* Constraint List */
    .pv-constraint-list {
      list-style: none;
      margin: 0;
      padding: 0;
    }

    .pv-constraint-item {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 8px 10px;
      background: var(--bg-tertiary);
      border-radius: 5px;
      margin-bottom: 6px;
      font-size: 12px;
      color: var(--text-primary);
    }

    .pv-constraint-item:last-child {
      margin-bottom: 0;
    }

    .pv-constraint-number {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 18px;
      height: 18px;
      background: var(--color-prompt-dim);
      border-radius: 50%;
      font-size: 9px;
      font-weight: 600;
      color: var(--color-prompt);
      flex-shrink: 0;
    }

    /* Raw JSON View */
    .pv-raw-json {
      font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
      font-size: 11px;
      line-height: 1.5;
      padding: 14px;
      background: var(--bg-tertiary);
      border-radius: 6px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      color: var(--text-secondary);
      max-height: 600px;
    }

    /* Payload Preview */
    .pv-payload-preview {
      background: var(--bg-tertiary);
      border-radius: 6px;
      overflow: hidden;
    }

    .pv-payload-section {
      border-bottom: 1px solid var(--border);
    }

    .pv-payload-section:last-child {
      border-bottom: none;
    }

    .pv-payload-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 12px;
      background: var(--bg-secondary);
      cursor: pointer;
    }

    .pv-payload-title {
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
    }

    .pv-payload-badge {
      font-size: 9px;
      padding: 2px 6px;
      background: var(--bg-card);
      border-radius: 4px;
      color: var(--text-muted);
    }

    .pv-payload-content {
      padding: 10px 12px;
      font-family: 'SF Mono', Monaco, monospace;
      font-size: 11px;
      line-height: 1.4;
      color: var(--text-secondary);
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 300px;
      overflow: auto;
    }

    .pv-payload-section.collapsed .pv-payload-content {
      display: none;
    }

    /* Data Payload Tabs */
    .pv-data-tabs {
      display: flex;
      border-bottom: 1px solid var(--border);
    }

    .pv-data-tab {
      padding: 8px 14px;
      font-size: 11px;
      font-weight: 500;
      color: var(--text-muted);
      background: transparent;
      border: none;
      cursor: pointer;
      transition: all 0.15s;
    }

    .pv-data-tab.active {
      color: var(--text-primary);
      background: var(--bg-card);
    }

    .pv-data-tab:hover:not(.active) {
      color: var(--text-secondary);
    }

    .pv-data-content {
      padding: 12px;
      max-height: 350px;
      overflow: auto;
    }

    /* Data Table */
    .pv-data-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 11px;
    }

    .pv-data-table th {
      padding: 6px 8px;
      text-align: left;
      background: var(--bg-secondary);
      border-bottom: 1px solid var(--border);
      font-weight: 600;
      color: var(--text-muted);
      white-space: nowrap;
    }

    .pv-data-table td {
      padding: 6px 8px;
      border-bottom: 1px solid var(--border-subtle);
      color: var(--text-secondary);
    }

    .pv-data-table tr:nth-child(even) {
      background: var(--bg-card);
    }

    /* Copy Button */
    .pv-copy-btn {
      padding: 3px 6px;
      background: var(--bg-secondary);
      border: 1px solid var(--border);
      border-radius: 3px;
      color: var(--text-muted);
      font-size: 10px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 4px;
    }

    .pv-copy-btn:hover {
      background: var(--bg-hover);
      color: var(--text-primary);
    }

    .pv-copy-btn svg {
      width: 10px;
      height: 10px;
    }

    /* Empty State */
    .pv-empty {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 40px 20px;
      text-align: center;
      color: var(--text-muted);
    }

    .pv-empty svg {
      width: 40px;
      height: 40px;
      margin-bottom: 12px;
      opacity: 0.5;
    }

    .pv-empty-title {
      font-size: 14px;
      font-weight: 500;
      color: var(--text-secondary);
      margin-bottom: 6px;
    }

    .pv-empty-desc {
      font-size: 12px;
      max-width: 280px;
    }

    /* Info Banner */
    .pv-info-banner {
      margin-bottom: 14px;
      padding: 10px 12px;
      background: var(--info-dim);
      border-radius: 6px;
      color: var(--info);
      font-size: 12px;
    }

    .pv-info-banner strong {
      font-weight: 600;
    }

    /* Scrollbar */
    .prompt-viewer ::-webkit-scrollbar {
      width: 6px;
      height: 6px;
    }

    .prompt-viewer ::-webkit-scrollbar-track {
      background: var(--bg-tertiary);
    }

    .prompt-viewer ::-webkit-scrollbar-thumb {
      background: var(--border-light);
      border-radius: 3px;
    }

    .prompt-viewer ::-webkit-scrollbar-thumb:hover {
      background: var(--text-muted);
    }
  `;

  /**
   * Inject styles into the document
   */
  function inject() {
    if (document.getElementById('prompt-viewer-styles')) return;

    const style = document.createElement('style');
    style.id = 'prompt-viewer-styles';
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  /**
   * Get the CSS string
   */
  function getCSS() {
    return CSS;
  }

  return {
    inject,
    getCSS
  };
})();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = PromptViewerStyles;
}
