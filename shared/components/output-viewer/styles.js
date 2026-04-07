/**
 * Output Viewer Component - Styles
 *
 * CSS styles for the output viewer component including:
 * - Output header and metrics
 * - Output viewer container
 * - Metadata tray with tabs
 */

const OutputViewerStyles = (function() {
  'use strict';

  const STYLES = `
    /* Output Viewer Container */
    .output-viewer-panel {
      display: flex;
      flex-direction: column;
      height: 100%;
      background: var(--bg-secondary, #111113);
      border: 1px solid var(--border, #1e1e22);
      border-radius: 12px;
      overflow: hidden;
    }

    /* Output Header */
    .output-viewer-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      background: var(--bg-tertiary, #1a1a1d);
      border-bottom: 1px solid var(--border, #1e1e22);
      flex-shrink: 0;
    }

    .output-viewer-title {
      font-size: 14px;
      font-weight: 600;
      color: var(--text-primary, #fafafa);
    }

    .output-viewer-close-btn {
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

    .output-viewer-close-btn:hover {
      background: var(--bg-hover, #1e1e22);
      border-color: var(--border, #1e1e22);
      color: var(--text-primary, #fafafa);
    }

    .output-viewer-close-btn svg {
      width: 16px;
      height: 16px;
    }

    .output-viewer-metrics {
      display: flex;
      gap: 16px;
    }

    .output-viewer-metric {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
    }

    .output-viewer-metric-label {
      color: var(--text-muted, #71717a);
    }

    .output-viewer-metric-value {
      color: var(--text-primary, #fafafa);
      font-weight: 500;
      font-family: 'SF Mono', Monaco, monospace;
    }

    /* Output Content Area */
    .output-viewer-panel-content {
      flex: 1;
      overflow: auto;
      min-height: 200px;
    }

    /* Empty State */
    .output-viewer-empty {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100%;
      padding: 40px;
      color: var(--text-muted, #71717a);
      text-align: center;
    }

    .output-viewer-empty svg {
      width: 48px;
      height: 48px;
      margin-bottom: 16px;
      opacity: 0.5;
    }

    .output-viewer-empty-title {
      font-size: 14px;
      font-weight: 500;
      color: var(--text-secondary, #a1a1aa);
      margin-bottom: 8px;
    }

    .output-viewer-empty-desc {
      font-size: 12px;
    }

    /* Metadata Tray */
    .output-viewer-metadata {
      border-top: 1px solid var(--border, #1e1e22);
      background: var(--bg-tertiary, #1a1a1d);
      flex-shrink: 0;
    }

    .output-viewer-metadata.collapsed .output-viewer-metadata-content {
      display: none;
    }

    .output-viewer-metadata.collapsed .output-viewer-metadata-toggle svg {
      transform: rotate(180deg);
    }

    .output-viewer-metadata.collapsed .output-viewer-metadata-tabs {
      border-bottom: none;
    }

    /* Metadata Tabs */
    .output-viewer-metadata-tabs {
      display: flex;
      gap: 0;
      border-bottom: 1px solid var(--border, #1e1e22);
    }

    .output-viewer-metadata-tab {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 8px 14px;
      font-size: 11px;
      font-weight: 500;
      color: var(--text-muted, #71717a);
      background: transparent;
      border: none;
      border-right: 1px solid var(--border, #1e1e22);
      cursor: pointer;
      transition: all 0.15s;
    }

    .output-viewer-metadata-tab:hover {
      background: var(--bg-hover, #1e1e22);
      color: var(--text-primary, #fafafa);
    }

    .output-viewer-metadata-tab.active {
      background: var(--bg-secondary, #111113);
      color: var(--text-primary, #fafafa);
    }

    .output-viewer-metadata-tab svg {
      width: 12px;
      height: 12px;
    }

    .output-viewer-metadata-count {
      font-size: 9px;
      padding: 1px 5px;
      background: var(--bg-primary, #0a0a0b);
      border-radius: 8px;
      color: var(--text-muted, #71717a);
    }

    .output-viewer-metadata-tab.active .output-viewer-metadata-count {
      background: var(--color-cxu-dim, rgba(59, 130, 246, 0.12));
      color: var(--color-cxu, #3b82f6);
    }

    .output-viewer-metadata-toggle {
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 4px 8px;
      background: transparent;
      border: none;
      color: var(--text-muted, #71717a);
      cursor: pointer;
      margin-left: auto;
    }

    .output-viewer-metadata-toggle:hover {
      color: var(--text-primary, #fafafa);
    }

    .output-viewer-metadata-toggle svg {
      width: 14px;
      height: 14px;
      transition: transform 0.2s;
    }

    /* Metadata Content Panels */
    .output-viewer-metadata-content {
      padding: 12px 16px;
      max-height: 180px;
      overflow-y: auto;
    }

    .output-viewer-metadata-panel {
      display: none;
    }

    .output-viewer-metadata-panel.active {
      display: block;
    }

    /* Run Params Grid */
    .output-viewer-params-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
      gap: 12px;
    }

    .output-viewer-param {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }

    .output-viewer-param-label {
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted, #71717a);
    }

    .output-viewer-param-value {
      font-size: 13px;
      font-weight: 500;
      color: var(--text-primary, #fafafa);
      font-family: 'SF Mono', Monaco, monospace;
    }

    /* CxU Reference List */
    .output-viewer-ref-list {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .output-viewer-ref-empty {
      font-size: 12px;
      color: var(--text-muted, #71717a);
      font-style: italic;
      padding: 8px 0;
    }

    .output-viewer-cxu-item {
      padding: 6px 12px;
      background: var(--color-cxu-dim, rgba(59, 130, 246, 0.12));
      border: 1px solid var(--color-cxu, #3b82f6);
      border-radius: 6px;
      font-size: 12px;
      font-weight: 500;
      color: var(--color-cxu, #3b82f6);
      cursor: pointer;
      transition: all 0.15s;
    }

    .output-viewer-cxu-item:hover {
      background: var(--color-cxu, #3b82f6);
      color: white;
    }

    /* Preview Mode Styles */
    .output-viewer-preview {
      position: relative;
      font-size: 12px;
      line-height: 1.5;
    }

    .output-viewer-preview-content {
      color: var(--text-secondary, #a1a1aa);
    }

    .output-viewer-preview-content .output-viewer {
      font-size: 12px;
      padding: 0;
      background: transparent;
    }

    .output-viewer-preview-content .output-viewer-content {
      padding: 0;
    }

    .output-viewer-preview-content .output-viewer h1,
    .output-viewer-preview-content .output-viewer h2,
    .output-viewer-preview-content .output-viewer h3 {
      font-size: 12px;
      margin: 0 0 4px 0;
      color: var(--text-primary, #fafafa);
    }

    .output-viewer-preview-content .output-viewer p {
      margin: 0 0 6px 0;
    }

    .output-viewer-preview-content .output-viewer ul,
    .output-viewer-preview-content .output-viewer ol {
      margin: 0 0 6px 0;
      padding-left: 16px;
    }

    .output-viewer-preview-content .output-viewer li {
      margin-bottom: 2px;
    }

    .output-viewer-preview-content .cxu-pill {
      font-size: 10px;
      padding: 1px 5px;
    }

    .output-viewer-preview-text {
      white-space: pre-wrap;
      word-break: break-word;
    }

    .output-viewer-preview-empty {
      color: var(--text-muted, #71717a);
      font-style: italic;
    }

    .output-viewer-preview-fade {
      position: absolute;
      bottom: 0;
      left: 0;
      right: 0;
      height: 40px;
      background: linear-gradient(to bottom, transparent, var(--bg-secondary, #111113));
      pointer-events: none;
    }
  `;

  let stylesInjected = false;

  function inject() {
    if (stylesInjected) return;

    const styleEl = document.createElement('style');
    styleEl.id = 'output-viewer-styles';
    styleEl.textContent = STYLES;
    document.head.appendChild(styleEl);
    stylesInjected = true;
  }

  return {
    inject,
    STYLES
  };
})();

// Export for Node.js if needed
if (typeof module !== 'undefined' && module.exports) {
  module.exports = OutputViewerStyles;
}
