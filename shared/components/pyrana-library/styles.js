/**
 * Pyrana Library Component - Styles
 *
 * CSS styles for the Pyrana Library side tray component.
 * Injected once when the component initializes.
 */

const PyranaLibraryStyles = (function() {
  'use strict';

  const STYLES = `
    /* Library Side Tray */
    .library-tray {
      width: var(--tray-width, 340px);
      height: 100%;
      max-height: 100vh;
      background: var(--bg-secondary);
      border-left: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
      overflow: hidden;
      transition: margin 0.3s ease, opacity 0.2s ease;
    }

    /* Inner container must also be flex column for scrolling to work */
    .library-tray > div,
    #libraryObjectListContainer {
      display: flex;
      flex-direction: column;
      flex: 1;
      min-height: 0;
      overflow: hidden;
    }

    .library-tray.collapsed {
      margin-right: calc(-1 * var(--tray-width, 340px));
      opacity: 0;
      pointer-events: none;
    }

    .library-tray-header {
      padding: 14px 16px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-shrink: 0;
    }

    .library-tray-title {
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
    }

    /* API Tabs */
    .library-api-tabs {
      display: flex;
      padding: 10px 12px;
      gap: 6px;
      border-bottom: 1px solid var(--border);
      overflow-x: auto;
      flex-shrink: 0;
    }

    .library-api-tab {
      padding: 8px 12px;
      background: none;
      border: 1px solid transparent;
      border-radius: 8px;
      color: var(--text-muted);
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      white-space: nowrap;
      transition: all 0.15s;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 2px;
    }

    .library-api-tab-name {
      font-weight: 500;
    }

    .library-api-tab-counts {
      font-size: 10px;
      opacity: 0.7;
      font-weight: 400;
      letter-spacing: 0.5px;
    }

    .library-api-tab.active .library-api-tab-counts {
      opacity: 0.85;
    }

    .library-api-tab-count-row {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 10px;
      opacity: 0.7;
    }

    .library-api-tab.active .library-api-tab-count-row {
      opacity: 0.85;
    }

    .library-api-tab-health-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      flex-shrink: 0;
    }

    .library-api-tab-health-dot.healthy {
      background: var(--success);
      animation: resources-pulse 1.5s infinite;
    }

    .library-api-tab-health-dot.error {
      background: var(--error);
    }

    .library-api-tab-health-dot.warning {
      background: var(--warning);
    }

    .library-api-tab-health-dot.pending {
      background: var(--text-muted);
      animation: resources-pulse 1.5s infinite;
    }

    .library-api-tab:hover {
      color: var(--text-secondary);
      background: var(--bg-tertiary);
    }

    .library-api-tab.active {
      background: var(--accent-dim);
      border-color: var(--accent);
      color: var(--accent);
    }

    .library-api-tab[data-api="cxu_manager"].active {
      background: var(--color-cxu-dim);
      border-color: var(--color-cxu);
      color: var(--color-cxu);
    }

    .library-api-tab[data-api="script_manager"].active {
      background: var(--color-script-dim);
      border-color: var(--color-script);
      color: var(--color-script);
    }

    .library-api-tab[data-api="prompt_manager"].active {
      background: var(--color-prompt-dim);
      border-color: var(--color-prompt);
      color: var(--color-prompt);
    }

    .library-api-tab[data-api="agent_manager"].active {
      background: var(--color-agent-dim);
      border-color: var(--color-agent);
      color: var(--color-agent);
    }

    .library-api-tab.offline {
      opacity: 0.5;
      cursor: not-allowed;
    }

    .library-api-tab.offline::after {
      content: '';
      width: 6px;
      height: 6px;
      background: var(--error);
      border-radius: 50%;
      margin-left: 4px;
    }

    .library-item-count {
      font-size: 13px;
      color: var(--text-muted);
    }

    /* Search Bar */
    .library-search-bar {
      padding: 12px;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }

    .library-search-input-wrapper {
      position: relative;
      display: flex;
      align-items: center;
    }

    .library-search-icon {
      position: absolute;
      left: 10px;
      width: 16px;
      height: 16px;
      color: var(--text-muted);
      pointer-events: none;
    }

    .library-search-input {
      width: 100%;
      padding: 8px 32px 8px 32px;
      background: var(--bg-tertiary);
      border: 1px solid var(--border);
      border-radius: 6px;
      color: var(--text-primary);
      font-size: 12px;
      transition: all 0.15s;
    }

    .library-search-input::placeholder {
      color: var(--text-muted);
    }

    .library-search-input:focus {
      outline: none;
      border-color: var(--accent);
      background: var(--bg-secondary);
    }

    .library-search-clear {
      position: absolute;
      right: 6px;
      width: 20px;
      height: 20px;
      padding: 0;
      border: none;
      background: transparent;
      color: var(--text-muted);
      cursor: pointer;
      border-radius: 4px;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s;
    }

    .library-search-clear:hover {
      background: var(--bg-hover);
      color: var(--text-primary);
    }

    .library-search-clear svg {
      width: 12px;
      height: 12px;
    }

    /* Filter Dropdowns */
    .library-filter-row {
      display: flex;
      gap: 8px;
      margin-top: 10px;
    }

    .library-filter-dropdown {
      flex: 1;
      position: relative;
    }

    .library-filter-display {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 6px 10px;
      background: var(--bg-tertiary);
      border: 1px solid var(--border);
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.15s;
      font-size: 12px;
    }

    .library-filter-display:hover {
      border-color: var(--border-light);
      background: var(--bg-hover);
    }

    .library-filter-display.open {
      border-color: var(--accent);
      background: var(--bg-secondary);
    }

    .library-filter-placeholder {
      color: var(--text-muted);
    }

    .library-filter-badge {
      background: var(--accent-dim);
      color: var(--accent);
      padding: 2px 6px;
      border-radius: 10px;
      font-size: 11px;
      font-weight: 500;
    }

    .library-filter-chevron {
      width: 14px;
      height: 14px;
      color: var(--text-muted);
      transition: transform 0.15s;
    }

    .library-filter-display.open .library-filter-chevron {
      transform: rotate(180deg);
    }

    .library-filter-menu {
      position: absolute;
      top: 100%;
      left: 0;
      right: 0;
      margin-top: 4px;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
      z-index: 100;
      display: none;
      max-height: 200px;
      overflow: hidden;
      flex-direction: column;
    }

    .library-filter-menu.open {
      display: flex;
    }

    .library-filter-menu-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 12px;
      border-bottom: 1px solid var(--border);
      font-size: 11px;
      font-weight: 500;
      color: var(--text-secondary);
    }

    .library-filter-clear-btn {
      padding: 2px 6px;
      font-size: 10px;
      background: transparent;
      border: none;
      color: var(--accent);
      cursor: pointer;
      border-radius: 4px;
    }

    .library-filter-clear-btn:hover {
      background: var(--accent-dim);
    }

    .library-filter-menu-list {
      overflow-y: auto;
      padding: 6px 0;
      flex: 1;
    }

    .library-filter-option {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 12px;
      cursor: pointer;
      transition: background 0.1s;
    }

    .library-filter-option:hover {
      background: var(--bg-hover);
    }

    .library-filter-option input[type="checkbox"] {
      display: none;
    }

    .library-filter-checkbox {
      width: 14px;
      height: 14px;
      border: 1px solid var(--border);
      border-radius: 3px;
      background: var(--bg-tertiary);
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      transition: all 0.15s;
    }

    .library-filter-option input:checked + .library-filter-checkbox {
      background: var(--accent);
      border-color: var(--accent);
    }

    .library-filter-option input:checked + .library-filter-checkbox::after {
      content: '';
      width: 8px;
      height: 5px;
      border: 2px solid white;
      border-top: none;
      border-right: none;
      transform: rotate(-45deg);
      margin-top: -2px;
    }

    .library-filter-option-text {
      font-size: 12px;
      color: var(--text-primary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    /* Active Filter Chips */
    .library-active-filters {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 10px;
      align-items: center;
    }

    .library-active-filter {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 3px 8px;
      background: var(--accent-dim);
      border: 1px solid var(--accent);
      border-radius: 12px;
      font-size: 11px;
      font-weight: 500;
      color: var(--accent);
      cursor: pointer;
      transition: all 0.15s;
    }

    .library-active-filter.keyword {
      background: var(--color-skill-dim, rgba(249, 115, 22, 0.1));
      border-color: var(--color-skill, #f97316);
      color: var(--color-skill, #f97316);
    }

    .library-active-filter:hover {
      background: var(--accent);
      color: white;
    }

    .library-active-filter.keyword:hover {
      background: var(--color-skill, #f97316);
      color: white;
    }

    .library-active-filter svg {
      width: 10px;
      height: 10px;
    }

    .library-clear-all-filters {
      padding: 3px 8px;
      background: transparent;
      border: none;
      font-size: 11px;
      color: var(--text-muted);
      cursor: pointer;
      border-radius: 4px;
    }

    .library-clear-all-filters:hover {
      background: var(--bg-hover);
      color: var(--text-primary);
    }

    /* Object List */
    .library-object-list {
      flex: 1;
      overflow-y: auto;
      padding: 12px;
      scroll-behavior: smooth;
    }

    /* Scrollbar Styling */
    .library-object-list::-webkit-scrollbar {
      width: 8px;
    }

    .library-object-list::-webkit-scrollbar-track {
      background: transparent;
    }

    .library-object-list::-webkit-scrollbar-thumb {
      background: var(--border);
      border-radius: 4px;
    }

    .library-object-list::-webkit-scrollbar-thumb:hover {
      background: var(--text-muted);
    }

    /* Firefox scrollbar */
    .library-object-list {
      scrollbar-width: thin;
      scrollbar-color: var(--border) transparent;
    }

    /* No Results State */
    .library-no-results .library-empty-icon {
      color: var(--text-muted);
    }

    .library-object-tile {
      padding: 12px;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      cursor: pointer;
      transition: all 0.15s;
      margin-bottom: 8px;
    }

    .library-object-tile:hover {
      background: var(--bg-hover);
      border-color: var(--border-light);
    }

    .library-object-tile.selected {
      border-color: var(--accent);
      background: var(--accent-dim);
    }

    .library-object-tile-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 6px;
    }

    .library-object-tile-name {
      font-size: 13px;
      font-weight: 600;
      color: var(--text-primary);
      word-break: break-word;
    }

    .library-object-tile-status {
      font-size: 10px;
      padding: 2px 6px;
      border-radius: 4px;
      font-weight: 500;
      flex-shrink: 0;
    }

    .library-object-tile-status.active {
      background: var(--success-dim);
      color: var(--success);
    }

    .library-object-tile-status.retired {
      background: var(--bg-tertiary);
      color: var(--text-muted);
    }

    .library-object-tile-desc {
      font-size: 12px;
      color: var(--text-secondary);
      line-height: 1.4;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .library-object-tile-id {
      font-size: 10px;
      color: var(--text-muted);
      font-family: 'SF Mono', Monaco, monospace;
      margin-top: 6px;
    }

    /* Loading and Empty States */
    .library-loading {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 40px;
      color: var(--text-muted);
    }

    .library-loading-spinner {
      width: 24px;
      height: 24px;
      border: 2px solid var(--border);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: resources-spin 0.8s linear infinite;
      margin-bottom: 12px;
    }

    @keyframes resources-spin {
      to { transform: rotate(360deg); }
    }

    .library-empty {
      text-align: center;
      padding: 40px 20px;
      color: var(--text-muted);
    }

    .library-empty-icon {
      width: 48px;
      height: 48px;
      margin: 0 auto 12px;
      opacity: 0.5;
    }

    .library-empty-text {
      font-size: 13px;
      margin-bottom: 8px;
    }

    .library-empty-hint {
      font-size: 12px;
      color: var(--text-muted);
    }

    /* New Item Button */
    .library-new-btn {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      width: 100%;
      padding: 10px;
      background: var(--bg-tertiary);
      border: 1px dashed var(--border);
      border-radius: 8px;
      color: var(--text-muted);
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.15s;
      margin-bottom: 12px;
    }

    .library-new-btn:hover {
      background: var(--bg-hover);
      border-color: var(--accent);
      color: var(--accent);
    }

    .library-new-btn svg {
      width: 14px;
      height: 14px;
    }

    /* Health Status Indicators */
    .library-health-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 8px;
      padding: 12px;
      border-bottom: 1px solid var(--border);
    }

    .library-health-item {
      padding: 8px 10px;
      background: var(--bg-tertiary);
      border-radius: 6px;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .library-health-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;
    }

    .library-health-dot.healthy {
      background: var(--success);
      animation: resources-pulse 1.5s infinite;
    }

    .library-health-dot.warning {
      background: var(--warning);
    }

    .library-health-dot.error {
      background: var(--error);
    }

    .library-health-dot.pending {
      background: var(--text-muted);
      animation: resources-pulse 1.5s infinite;
    }

    @keyframes resources-pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.4; }
    }

    .library-health-name {
      font-size: 11px;
      color: var(--text-secondary);
    }

    /* Modal Styles */
    .library-modal-overlay {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(0, 0, 0, 0.7);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 1000;
      opacity: 0;
      visibility: hidden;
      transition: all 0.2s;
    }

    .library-modal-overlay.open {
      opacity: 1;
      visibility: visible;
    }

    .library-modal {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 12px;
      width: 90%;
      max-width: 700px;
      max-height: 85vh;
      display: flex;
      flex-direction: column;
      transform: translateY(20px);
      transition: transform 0.2s;
    }

    .library-modal-overlay.open .library-modal {
      transform: translateY(0);
    }

    .library-modal-header {
      padding: 16px 20px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .library-modal-title-wrap {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }

    .library-modal-title {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
      color: var(--text-primary);
    }

    .library-modal-status-tag {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 10px;
      padding: 2px 8px;
      border-radius: 999px;
      font-weight: 600;
      letter-spacing: 0.35px;
      text-transform: uppercase;
      background: var(--bg-tertiary);
      color: var(--text-muted);
      border: 1px solid var(--border);
      flex-shrink: 0;
    }

    .library-modal-status-tag.active {
      background: var(--success-dim);
      color: var(--success);
      border-color: var(--success);
    }

    .library-modal-status-tag.superseded {
      background: var(--warning-dim, var(--bg-tertiary));
      color: var(--warning);
      border-color: var(--warning);
    }

    .library-modal-status-tag.retired {
      background: var(--bg-tertiary);
      color: var(--text-muted);
      border-color: var(--border);
    }

    .library-modal-close {
      width: 32px;
      height: 32px;
      border: none;
      background: transparent;
      color: var(--text-muted);
      cursor: pointer;
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s;
    }

    .library-modal-close:hover {
      background: var(--bg-hover);
      color: var(--text-primary);
    }

    .library-modal-body {
      flex: 1;
      overflow-y: auto;
      padding: 20px;
    }

    .library-modal-footer {
      padding: 16px 20px;
      border-top: 1px solid var(--border);
      display: flex;
      justify-content: flex-end;
      gap: 8px;
    }

    /* Modal Buttons */
    .library-modal-btn {
      padding: 10px 16px;
      border: none;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.15s;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .library-modal-btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    .library-modal-btn-primary {
      background: var(--accent);
      color: white;
    }

    .library-modal-btn-primary:hover:not(:disabled) {
      filter: brightness(1.1);
    }

    .library-modal-btn-secondary {
      background: var(--bg-tertiary);
      color: var(--text-secondary);
      border: 1px solid var(--border);
    }

    .library-modal-btn-secondary:hover:not(:disabled) {
      background: var(--bg-hover);
      color: var(--text-primary);
    }

    .library-modal-btn-danger {
      background: var(--error);
      color: white;
    }

    .library-modal-btn-danger:hover:not(:disabled) {
      filter: brightness(1.1);
    }

    .library-modal-btn-warning {
      background: var(--warning);
      color: white;
    }

    .library-modal-btn-warning:hover:not(:disabled) {
      filter: brightness(1.1);
    }

    /* Modal Form Fields */
    .library-modal-field {
      margin-bottom: 16px;
    }

    .library-modal-field label {
      display: block;
      font-size: 12px;
      font-weight: 500;
      color: var(--text-secondary);
      margin-bottom: 6px;
    }

    .library-modal-field input,
    .library-modal-field textarea,
    .library-modal-field select {
      width: 100%;
      padding: 10px 12px;
      background: var(--bg-tertiary);
      border: 1px solid var(--border);
      border-radius: 6px;
      color: var(--text-primary);
      font-size: 13px;
      transition: all 0.15s;
    }

    .library-modal-field input:focus,
    .library-modal-field textarea:focus,
    .library-modal-field select:focus {
      outline: none;
      border-color: var(--accent);
      background: var(--bg-secondary);
    }

    .library-modal-field textarea {
      resize: vertical;
      min-height: 80px;
    }

    /* Expanded View Styles */
    .expanded-view-toggle {
      display: flex;
      gap: 4px;
      margin-bottom: 16px;
      background: var(--bg-tertiary);
      padding: 4px;
      border-radius: 8px;
    }

    .expanded-view-btn {
      flex: 1;
      padding: 8px 16px;
      border: none;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.15s;
      background: transparent;
      color: var(--text-muted);
    }

    .expanded-view-btn.active {
      background: var(--bg-card);
      color: var(--text-primary);
    }

    .collapsible-section-header {
      display: flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
      user-select: none;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
      margin-bottom: 12px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--border);
    }

    .collapsible-section-header:hover {
      color: var(--text-secondary);
    }

    .collapse-arrow {
      transition: transform 0.2s;
    }
  `;

  let stylesInjected = false;

  function inject() {
    if (stylesInjected) return;

    const styleEl = document.createElement('style');
    styleEl.id = 'pyrana-library-styles';
    styleEl.textContent = STYLES;
    document.head.appendChild(styleEl);
    stylesInjected = true;
  }

  function remove() {
    const styleEl = document.getElementById('pyrana-library-styles');
    if (styleEl) {
      styleEl.remove();
      stylesInjected = false;
    }
  }

  return {
    inject,
    remove,
    STYLES
  };
})();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = PyranaLibraryStyles;
}
