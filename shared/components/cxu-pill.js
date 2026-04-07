/**
 * CxU Pill Component
 *
 * A reusable component for rendering clickable CxU reference pills.
 * Used throughout the Pyrana Agent Builder for displaying CxU citations.
 *
 * Usage:
 *   // Render a single pill
 *   const html = CxuPill.render({ alias: 'sales-data', cxuId: '1220abc...', claim: 'Sales metrics' });
 *
 *   // Render from citation text like [alias:cxu_id]
 *   const html = CxuPill.renderFromCitation('[sales-data:1220abc...]', cxuList);
 *
 *   // Process markdown text and convert all citations to pills
 *   const processedHtml = CxuPill.processMarkdownCitations(markdownText, cxuList);
 */

const CxuPill = (function() {
  'use strict';

  // Configuration
  const CONFIG = {
    truncateIdLength: 8,
    maxTooltipLength: 50
  };

  // CSS styles for the component (injected once)
  const STYLES = `
    .cxu-pill {
      display: inline-flex;
      align-items: center;
      gap: 3px;
      padding: 2px 8px;
      background: var(--color-cxu-dim, rgba(59, 130, 246, 0.12));
      border: 1px solid var(--color-cxu, #3b82f6);
      border-radius: 12px;
      font-size: 11px;
      font-weight: 600;
      color: var(--color-cxu, #3b82f6);
      cursor: pointer;
      transition: all 0.15s ease;
      text-decoration: none;
      position: relative;
      vertical-align: middle;
      white-space: nowrap;
      margin: 0 2px;
    }

    .cxu-pill:hover {
      background: var(--color-cxu, #3b82f6);
      color: white;
      transform: translateY(-1px);
      box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3);
      z-index: 100;
    }

    .cxu-pill__label {
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.3px;
    }

    .cxu-pill__tooltip {
      position: absolute;
      bottom: calc(100% + 6px);
      left: 50%;
      transform: translateX(-50%);
      display: inline-flex;
      align-items: center;
      gap: 0;
      background: var(--bg-primary, #0a0a0b);
      border: 1px solid var(--border-light, #2a2a2e);
      border-radius: 6px;
      padding: 5px 10px;
      font-size: 11px;
      font-weight: 500;
      color: var(--text-primary, #fafafa);
      white-space: nowrap;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.15s ease;
      z-index: 10000;
    }

    .cxu-pill:hover .cxu-pill__tooltip {
      opacity: 1;
    }

    .cxu-pill__tooltip-alias {
      color: var(--color-cxu, #3b82f6);
      font-weight: 600;
    }

    .cxu-pill__tooltip-sep {
      color: var(--text-muted, #71717a);
      margin: 0 2px;
    }

    .cxu-pill__tooltip-id {
      color: var(--text-muted, #71717a);
      font-family: 'SF Mono', Monaco, monospace;
      font-size: 10px;
    }
  `;

  // Track if styles have been injected
  let stylesInjected = false;

  /**
   * Inject component styles into the document head
   */
  function injectStyles() {
    if (stylesInjected) return;

    const styleEl = document.createElement('style');
    styleEl.id = 'cxu-pill-styles';
    styleEl.textContent = STYLES;
    document.head.appendChild(styleEl);
    stylesInjected = true;
  }

  /**
   * Escape HTML special characters
   */
  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /**
   * Escape content for single-quoted JS string literals in inline handlers.
   */
  function escapeJsString(str) {
    return String(str || '')
      .replace(/\\/g, '\\\\')
      .replace(/'/g, "\\'")
      .replace(/\r?\n/g, ' ');
  }

  /**
   * Truncate a string with ellipsis
   */
  function truncate(str, maxLength) {
    if (!str || str.length <= maxLength) return str;
    return str.substring(0, maxLength) + '...';
  }

  /**
   * Get the book icon SVG
   */
  function getIcon() {
    return `<svg class="cxu-pill__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z"/>
      <path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z"/>
    </svg>`;
  }

  /**
   * Find a CxU in a list by alias or ID
   */
  function findCxu(identifier, cxuList) {
    if (!identifier || !cxuList || !Array.isArray(cxuList)) return null;

    const lower = identifier.toLowerCase().trim();

    return cxuList.find(cxu => {
      // Match by alias
      if (cxu.alias && cxu.alias.toLowerCase() === lower) return true;

      // Match by ID (exact or prefix)
      const cxuId = (cxu.cxu_id || cxu.id || '').toLowerCase();
      if (cxuId === lower || cxuId.startsWith(lower)) return true;

      // Match by partial alias
      if (cxu.alias && cxu.alias.toLowerCase().includes(lower)) return true;

      return false;
    });
  }

  /**
   * Render a CxU pill
   *
   * @param {Object} options
   * @param {string} options.cxuId - The full CxU ID
   * @param {string} options.alias - The CxU alias (for tooltip)
   * @param {string} [options.claim] - Optional claim text (for extended tooltip)
   * @returns {string} HTML string for the pill
   */
  function render(options = {}) {
    const { cxuId, alias, claim } = options;

    const displayAlias = alias || 'Unknown';
    const truncatedId = truncate(cxuId || '', CONFIG.truncateIdLength);
    const safeId = escapeHtml(cxuId || '');
    const safeAlias = escapeHtml(displayAlias);
    const jsId = escapeJsString(cxuId || '');
    const jsAlias = escapeJsString(displayAlias);

    return `<span class="cxu-pill" data-cxu-id="${safeId}" onclick="CxuPill.openInTray('${jsId}', '${jsAlias}')">
      <span class="cxu-pill__label">CxU</span>
      <span class="cxu-pill__tooltip">
        <span class="cxu-pill__tooltip-alias">${safeAlias}</span><span class="cxu-pill__tooltip-sep">:</span><span class="cxu-pill__tooltip-id">${escapeHtml(truncatedId)}</span>
      </span>
    </span>`;
  }

  /**
   * Render a CxU pill from a citation string like [alias:cxu_id]
   *
   * @param {string} citation - Citation string like "[sales-data:1220abc...]"
   * @param {Array} cxuList - List of CxU objects to search
   * @returns {string} HTML string for the pill
   */
  function renderFromCitation(citation, cxuList = []) {
    // Parse citation format: [alias:cxu_id]
    const match = citation.match(/\[([^\]:]+):([^\]]+)\]/);
    if (!match) return escapeHtml(citation);

    const [, aliasFromCitation, idFromCitation] = match;

    // Try to find the full CxU object
    const cxu = findCxu(aliasFromCitation, cxuList) || findCxu(idFromCitation.replace(/\.+$/, ''), cxuList);

    return render({
      cxuId: cxu ? (cxu.cxu_id || cxu.id) : idFromCitation,
      alias: cxu ? (cxu.alias || aliasFromCitation) : aliasFromCitation,
      claim: cxu ? cxu.claim : null
    });
  }

  /**
   * Process markdown/text and convert all CxU citations to pills
   *
   * Supported formats:
   * - (cxu_alias:alias:cxu_id) - Three-part format from LLM
   * - (alias:cxu_id) - Two-part parentheses format (PREFERRED)
   * - [alias] (ID: cxu_id) - Bracket alias with ID reference
   * - [alias] (cxu_id) - Bracket alias with ID in parens (no prefix)
   * - [alias:cxu_id] - Bracket format
   * - [[CxURef:alias]] - Schema format
   * - [CxU:identifier] - Legacy format
   * - (alias:partial_id - Truncated citation at end of content (no closing paren)
   *
   * @param {string} text - Text containing CxU citations
   * @param {Array} cxuList - List of CxU objects
   * @returns {string} Text with citations replaced by pill HTML
   */
  function processMarkdownCitations(text, cxuList = []) {
    if (!text) return '';

    let result = text;

    // Pattern 0: (cxu_alias:alias:cxu_id) - Three-part format from LLM
    // e.g., (cxu_alias:mandatory-citation-guardrail:12206623987e65670bba6f6475e87f8b5ca66d97142fe88089e274ef4f75fe5a7c09)
    result = result.replace(/\(cxu_alias:([a-zA-Z][a-zA-Z0-9_-]*):([a-f0-9]{16,})\)/gi, (match, alias, cxuId) => {
      const cxu = findCxu(alias, cxuList) || findCxu(cxuId, cxuList);

      return render({
        cxuId: cxu ? (cxu.cxu_id || cxu.id) : cxuId,
        alias: cxu ? (cxu.alias || alias) : alias,
        claim: cxu ? cxu.claim : null
      });
    });

    // Pattern 1a: [alias] (ID: cxu_id) - Bracket alias with separate ID reference
    // e.g., [risk-tier-thresholds] (ID: 1220efd168b58a95d0b5be659325640594020f6a39221185435d574e103ef3429dbe)
    result = result.replace(/\[([a-zA-Z][a-zA-Z0-9_-]*)\]\s*\(ID:\s*([a-f0-9]{16,})\)/gi, (match, alias, cxuId) => {
      const cxu = findCxu(alias, cxuList) || findCxu(cxuId, cxuList);

      return render({
        cxuId: cxu ? (cxu.cxu_id || cxu.id) : cxuId,
        alias: cxu ? (cxu.alias || alias) : alias,
        claim: cxu ? cxu.claim : null
      });
    });

    // Pattern 1b: [alias] (cxu_id) - Bracket alias with ID in parens (no "ID:" prefix)
    // e.g., [capa-requirements] (1220070f3dfb3cdaf4e9f3538d8c766cc1808ab0460c3516be94807f3563a6482d51)
    result = result.replace(/\[([a-zA-Z][a-zA-Z0-9_-]*)\]\s*\(([a-f0-9]{16,})\)/gi, (match, alias, cxuId) => {
      const cxu = findCxu(alias, cxuList) || findCxu(cxuId, cxuList);

      return render({
        cxuId: cxu ? (cxu.cxu_id || cxu.id) : cxuId,
        alias: cxu ? (cxu.alias || alias) : alias,
        claim: cxu ? cxu.claim : null
      });
    });

    // Pattern 1c: Multi-citation in single parens (alias1:id1, alias2:id2, ...)
    // e.g., (hotel-ind-40:1220b0e475da83b6..., hotel-ind-62:12206981dd67ab5c...)
    result = result.replace(/\(([a-zA-Z][a-zA-Z0-9_-]*:[a-f0-9]{16,}(?:\.{0,3})?)(?:\s*,\s*[a-zA-Z][a-zA-Z0-9_-]*:[a-f0-9]{16,}(?:\.{0,3})?)+\)/gi, (match) => {
      // Extract all alias:id pairs from inside the parens
      const inner = match.slice(1, -1); // strip ( and )
      const pairs = inner.split(/\s*,\s*/);
      return pairs.map(pair => {
        const pairMatch = pair.match(/^([a-zA-Z][a-zA-Z0-9_-]*):([a-f0-9]{16,}(?:\.{0,3})?)$/i);
        if (!pairMatch) return escapeHtml(pair);
        const [, pAlias, pId] = pairMatch;
        const cleanId = pId.replace(/\.+$/, '');
        const cxu = findCxu(pAlias, cxuList) || findCxu(cleanId, cxuList);
        if (!cxu) return escapeHtml(pair);
        return render({
          cxuId: cxu.cxu_id || cxu.id || pId,
          alias: cxu.alias || pAlias,
          claim: cxu.claim || null
        });
      }).join(' ');
    });

    // Pattern 2a: (alias:cxu_id) format with PARENTHESES (e.g., (vendor-a:1220def456...))
    result = result.replace(/\(([a-zA-Z][a-zA-Z0-9_-]*):([a-f0-9]{16,}(?:\.{0,3})?)\)/gi, (match, alias, partialId) => {
      const cleanId = partialId.replace(/\.+$/, '');
      const cxu = findCxu(alias, cxuList) || findCxu(cleanId, cxuList);

      if (!cxu) {
        // If no CxU found, don't convert - might be something else
        return match;
      }

      return render({
        cxuId: cxu.cxu_id || cxu.id || partialId,
        alias: cxu.alias || alias,
        claim: cxu.claim || null
      });
    });

    // Pattern 2b: [alias:cxu_id] format with BRACKETS (e.g., [analyze-top-customer-trends:1220def456...])
    result = result.replace(/\[([a-zA-Z][a-zA-Z0-9_-]*):([a-f0-9]{16,}(?:\.{0,3})?)\]/gi, (match, alias, partialId) => {
      const cleanId = partialId.replace(/\.+$/, '');
      const cxu = findCxu(alias, cxuList) || findCxu(cleanId, cxuList);

      return render({
        cxuId: cxu ? (cxu.cxu_id || cxu.id) : partialId,
        alias: cxu ? (cxu.alias || alias) : alias,
        claim: cxu ? cxu.claim : null
      });
    });

    // Pattern 3: [[CxURef:alias]] format (canonical schema format)
    result = result.replace(/\[\[CxURef:([^\]]+)\]\]/gi, (match, alias) => {
      const cxu = findCxu(alias.trim(), cxuList);

      return render({
        cxuId: cxu ? (cxu.cxu_id || cxu.id) : '',
        alias: cxu ? (cxu.alias || alias) : alias,
        claim: cxu ? cxu.claim : null
      });
    });

    // Pattern 4: [CxU:identifier] format (legacy)
    result = result.replace(/\[CxU:([^\]]+)\]/gi, (match, identifier) => {
      const cxu = findCxu(identifier.trim(), cxuList);

      return render({
        cxuId: cxu ? (cxu.cxu_id || cxu.id) : '',
        alias: cxu ? (cxu.alias || identifier) : identifier,
        claim: cxu ? cxu.claim : null
      });
    });

    // Pattern 5: Truncated citations at end of content - (alias:partial_id without closing paren
    // e.g., (audit_protocol:1220d4b2cea3b266e67f186e942326e2586caafd26782442afe495d50054f35
    // This handles cases where LLM output was truncated
    result = result.replace(/\(([a-zA-Z][a-zA-Z0-9_-]*):([a-f0-9]{16,})$/gi, (match, alias, partialId) => {
      const cxu = findCxu(alias, cxuList) || findCxu(partialId, cxuList);

      if (!cxu) {
        // If no CxU found, don't convert - might be something else
        return match;
      }

      return render({
        cxuId: cxu.cxu_id || cxu.id || partialId,
        alias: cxu.alias || alias,
        claim: cxu.claim || null
      });
    });

    // Pattern 6: Truncated citations at end of line (before newline) - same as above but not at absolute end
    // e.g., (audit_protocol:1220d4b2cea3b266e67f186e942326e2586caafd26782442afe495d50054f35\n
    result = result.replace(/\(([a-zA-Z][a-zA-Z0-9_-]*):([a-f0-9]{16,})(\s*[\n\r])/gi, (match, alias, partialId, trailing) => {
      const cxu = findCxu(alias, cxuList) || findCxu(partialId, cxuList);

      if (!cxu) {
        // If no CxU found, don't convert - might be something else
        return match;
      }

      return render({
        cxuId: cxu.cxu_id || cxu.id || partialId,
        alias: cxu.alias || alias,
        claim: cxu.claim || null
      }) + trailing;
    });

    // Pattern 7: Simple [alias] format - just alias in brackets, no ID
    // e.g., [labor-010], [overtime-policy], [risk-tier-thresholds]
    // Only converts if the alias matches a known CxU in the list
    result = result.replace(/\[([a-zA-Z][a-zA-Z0-9_-]*)\](?!\s*\()/gi, (match, alias) => {
      const cxu = findCxu(alias, cxuList);

      if (!cxu) {
        // If no CxU found, don't convert - might be a regular markdown link or something else
        return match;
      }

      return render({
        cxuId: cxu.cxu_id || cxu.id || '',
        alias: cxu.alias || alias,
        claim: cxu.claim || null
      });
    });

    return result;
  }

  /**
   * Open a CxU in the resources tray
   * This function is called from onclick handlers
   *
   * @param {string} cxuId - The CxU ID to open
   * @param {string} cxuAlias - CxU alias fallback for superseded IDs
   */
  function openInTray(cxuId, cxuAlias = '') {
    if (!cxuId && !cxuAlias) return;

    // Check if the global function exists (defined in agent-builder.html)
    if (typeof openCxuInResourcesTray === 'function') {
      openCxuInResourcesTray(cxuId, cxuAlias);
    } else {
      console.warn('[CxuPill] openCxuInResourcesTray function not found');
    }
  }

  /**
   * Initialize the component (inject styles)
   */
  function init() {
    injectStyles();
  }

  // Auto-initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Public API
  return {
    render,
    renderFromCitation,
    processMarkdownCitations,
    openInTray,
    findCxu,
    init
  };
})();

// Make available globally
if (typeof window !== 'undefined') {
  window.CxuPill = CxuPill;
}
