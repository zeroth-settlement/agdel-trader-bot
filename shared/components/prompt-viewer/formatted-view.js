/**
 * Prompt Viewer Component - Formatted View
 *
 * Renders the formatted view of a prompt with collapsible sections.
 */

const PromptFormattedView = (function() {
  'use strict';

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
   * Render markdown to HTML if marked.js is available, otherwise escape
   */
  function renderMarkdown(str) {
    if (!str) return '';

    // If marked.js is available, render markdown
    if (typeof marked !== 'undefined') {
      // Configure marked for inline rendering
      marked.setOptions({
        breaks: true,
        gfm: true,
        headerIds: false,
        mangle: false
      });
      return marked.parse(String(str));
    }

    // Fallback: escape HTML and preserve line breaks
    return escapeHtml(str).replace(/\n/g, '<br>');
  }

  /**
   * Format a label from snake_case
   */
  function formatLabel(key) {
    return key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  }

  /**
   * Render the chevron icon for collapsible sections
   */
  function chevronIcon() {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>`;
  }

  /**
   * Render copy button
   */
  function copyButton(text) {
    const escaped = escapeHtml(text).replace(/`/g, '\\`').replace(/\\/g, '\\\\');
    return `
      <button class="pv-copy-btn" onclick="event.stopPropagation(); PromptViewer.copyToClipboard(\`${escaped}\`)">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
          <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
        </svg>
        Copy
      </button>
    `;
  }

  /**
   * Render Basic Info Section
   */
  function renderBasicInfo(prompt) {
    const promptId = prompt.prompt_id || prompt.id || '-';
    const name = prompt.name || '-';
    const description = prompt.description || '';
    const category = prompt.category || '-';
    const status = prompt.status || 'Active';

    return `
      <div class="pv-section" data-section="basic-info">
        <div class="pv-section-header" onclick="PromptViewer.toggleSection(this)">
          <div class="pv-section-title">
            ${chevronIcon()}
            Basic Information
          </div>
        </div>
        <div class="pv-section-content">
          <div class="pv-field-grid">
            <div class="pv-field-group">
              <span class="pv-field-label">Prompt ID</span>
              <div class="pv-field-value mono pv-link" onclick="PromptViewer.openPromptInResources('${promptId}')" title="Open in Resources">${escapeHtml(promptId)}</div>
            </div>
            <div class="pv-field-group">
              <span class="pv-field-label">Name</span>
              <div class="pv-field-value pv-link" onclick="PromptViewer.openPromptInResources('${promptId}')" title="Open in Resources">${escapeHtml(name)}</div>
            </div>
            <div class="pv-field-group">
              <span class="pv-field-label">Category</span>
              <div class="pv-field-value">${escapeHtml(category)}</div>
            </div>
            <div class="pv-field-group">
              <span class="pv-field-label">Status</span>
              <div class="pv-field-value">${escapeHtml(status)}</div>
            </div>
          </div>
          ${description ? `
            <div class="pv-field-group" style="margin-top: 14px;">
              <span class="pv-field-label">Description</span>
              <div class="pv-field-value">${escapeHtml(description)}</div>
            </div>
          ` : ''}
        </div>
      </div>
    `;
  }

  /**
   * Render Objective Section
   */
  function renderObjective(prompt) {
    const objective = prompt.objective || {};
    if (!objective.intent && !objective.success_criteria) return '';

    return `
      <div class="pv-section" data-section="objective">
        <div class="pv-section-header" onclick="PromptViewer.toggleSection(this)">
          <div class="pv-section-title">
            ${chevronIcon()}
            Objective
          </div>
        </div>
        <div class="pv-section-content">
          ${objective.intent ? `
            <div class="pv-field-group">
              <span class="pv-field-label">Intent</span>
              <div class="pv-field-value pv-markdown">${renderMarkdown(objective.intent)}</div>
            </div>
          ` : ''}
          ${objective.success_criteria ? `
            <div class="pv-field-group">
              <span class="pv-field-label">Success Criteria</span>
              <div class="pv-field-value pv-markdown">${renderMarkdown(objective.success_criteria)}</div>
            </div>
          ` : ''}
        </div>
      </div>
    `;
  }

  /**
   * Render Output Contract Section
   */
  function renderOutputContract(prompt) {
    const contract = prompt.output_contract || {};
    if (!contract.output_type && !contract.format && !contract.output_details) return '';

    return `
      <div class="pv-section" data-section="output-contract">
        <div class="pv-section-header" onclick="PromptViewer.toggleSection(this)">
          <div class="pv-section-title">
            ${chevronIcon()}
            Output Contract
          </div>
        </div>
        <div class="pv-section-content">
          <div class="pv-field-grid">
            ${contract.output_type ? `
              <div class="pv-field-group">
                <span class="pv-field-label">Output Type</span>
                <div class="pv-field-value">${escapeHtml(contract.output_type)}</div>
              </div>
            ` : ''}
            ${contract.format ? `
              <div class="pv-field-group">
                <span class="pv-field-label">Format</span>
                <div class="pv-field-value">${escapeHtml(contract.format)}</div>
              </div>
            ` : ''}
          </div>
          ${contract.output_details ? `
            <div class="pv-field-group" style="margin-top: 14px;">
              <span class="pv-field-label">Output Details</span>
              <div class="pv-field-value pv-markdown">${renderMarkdown(contract.output_details)}</div>
            </div>
          ` : ''}
        </div>
      </div>
    `;
  }

  /**
   * Render Constraints Section
   */
  function renderConstraints(prompt) {
    const constraints = prompt.constraints || [];
    if (constraints.length === 0) return '';

    return `
      <div class="pv-section" data-section="constraints">
        <div class="pv-section-header" onclick="PromptViewer.toggleSection(this)">
          <div class="pv-section-title">
            ${chevronIcon()}
            Constraints
          </div>
          <span class="pv-section-badge">${constraints.length}</span>
        </div>
        <div class="pv-section-content">
          <ul class="pv-constraint-list">
            ${constraints.map((c, i) => `
              <li class="pv-constraint-item">
                <span class="pv-constraint-number">${i + 1}</span>
                <span>${escapeHtml(c)}</span>
              </li>
            `).join('')}
          </ul>
        </div>
      </div>
    `;
  }

  /**
   * Render Quality Standards Section
   */
  function renderQualityStandards(prompt) {
    const qualityStandards = prompt.quality_standards;
    if (!qualityStandards) return '';

    return `
      <div class="pv-section" data-section="quality-standards">
        <div class="pv-section-header" onclick="PromptViewer.toggleSection(this)">
          <div class="pv-section-title">
            ${chevronIcon()}
            Quality Standards
          </div>
        </div>
        <div class="pv-section-content">
          <div class="pv-field-value pv-markdown">${renderMarkdown(qualityStandards)}</div>
        </div>
      </div>
    `;
  }

  /**
   * Render Error Handling Section
   */
  function renderErrorHandling(prompt) {
    const errorHandling = prompt.error_handling;
    if (!errorHandling) return '';

    return `
      <div class="pv-section" data-section="error-handling">
        <div class="pv-section-header" onclick="PromptViewer.toggleSection(this)">
          <div class="pv-section-title">
            ${chevronIcon()}
            Error Handling
          </div>
        </div>
        <div class="pv-section-content">
          <div class="pv-field-value pv-markdown">${renderMarkdown(errorHandling)}</div>
        </div>
      </div>
    `;
  }

  /**
   * Render System Prompt Section
   */
  function renderSystemPrompt(prompt) {
    const systemPrompt = prompt.system_prompt;
    if (!systemPrompt) return '';

    return `
      <div class="pv-section" data-section="system-prompt">
        <div class="pv-section-header" onclick="PromptViewer.toggleSection(this)">
          <div class="pv-section-title">
            ${chevronIcon()}
            System Prompt Override
          </div>
          <div class="pv-section-actions">
            ${copyButton(systemPrompt)}
          </div>
        </div>
        <div class="pv-section-content">
          <div class="pv-field-value multiline" style="font-family: 'SF Mono', Monaco, monospace; font-size: 11px; max-height: 400px; overflow: auto;">${escapeHtml(systemPrompt)}</div>
        </div>
      </div>
    `;
  }

  /**
   * Render CxU Context Section
   */
  function renderCxuContext(prompt, options = {}) {
    const cxuContext = prompt.cxu_context || [];
    const cxuCount = prompt.cxu_count || cxuContext.length;
    const collapsed = cxuContext.length === 0;

    return `
      <div class="pv-section ${collapsed ? 'collapsed' : ''}" data-section="cxu-context">
        <div class="pv-section-header" onclick="PromptViewer.toggleSection(this)">
          <div class="pv-section-title">
            ${chevronIcon()}
            CxU Context
          </div>
          <span class="pv-section-badge">${cxuCount} CxUs</span>
        </div>
        <div class="pv-section-content">
          ${cxuContext.length > 0 ? `
            ${cxuContext.map(cxu => {
              const cxuId = cxu.cxu_id || cxu.id || '';
              const alias = cxu.alias || `CxU-${cxuId.substring(0, 8)}`;
              const claim = cxu.claim || '';
              const knowledgeType = cxu.knowledge_type || '';
              const claimType = cxu.claim_type || '';
              return `
                <div class="pv-cxu-card pv-cxu-card-clickable" onclick="PromptViewer.showCxuDetail('${cxuId}')">
                  <div class="pv-cxu-card-header">
                    <span class="pv-cxu-card-alias">${escapeHtml(alias)}</span>
                    <span class="pv-cxu-card-type">${escapeHtml(knowledgeType)}/${escapeHtml(claimType)}</span>
                  </div>
                  <div class="pv-cxu-card-claim">${escapeHtml(claim)}</div>
                </div>
              `;
            }).join('')}
          ` : `
            <div style="color: var(--text-muted); font-style: italic; font-size: 12px;">No CxU context configured</div>
          `}
        </div>
      </div>
    `;
  }

  /**
   * Render Data Payload Section
   */
  function renderDataPayload(prompt, dataPayload) {
    // If no data payload provided, don't show this section
    if (!dataPayload || Object.keys(dataPayload).length === 0) {
      return `
        <div class="pv-section collapsed" data-section="data-payload">
          <div class="pv-section-header" onclick="PromptViewer.toggleSection(this)">
            <div class="pv-section-title">
              ${chevronIcon()}
              Data Payload
            </div>
            <span class="pv-section-badge">None</span>
          </div>
          <div class="pv-section-content">
            <div style="color: var(--text-muted); font-style: italic; font-size: 12px; padding: 10px;">
              No data payload provided. Add data in the Input Data tab.
            </div>
          </div>
        </div>
      `;
    }

    const jsonStr = JSON.stringify(dataPayload, null, 2);
    const lineCount = jsonStr.split('\n').length;

    return `
      <div class="pv-section collapsed" data-section="data-payload">
        <div class="pv-section-header" onclick="PromptViewer.toggleSection(this)">
          <div class="pv-section-title">
            ${chevronIcon()}
            Data Payload
          </div>
          <span class="pv-section-badge">JSON · ${lineCount} lines</span>
        </div>
        <div class="pv-section-content">
          <div class="pv-data-content">
            <pre style="margin: 0; font-size: 11px; line-height: 1.4; color: var(--text-secondary); white-space: pre-wrap; word-break: break-word;">${escapeHtml(jsonStr)}</pre>
          </div>
        </div>
      </div>
    `;
  }

  /**
   * Generate the complete formatted view
   */
  function generate(prompt, options = {}) {
    if (!prompt) {
      return `
        <div class="pv-empty">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/>
            <line x1="16" y1="17" x2="8" y2="17"/>
          </svg>
          <div class="pv-empty-title">No Prompt Selected</div>
          <div class="pv-empty-desc">Select a prompt to view its details.</div>
        </div>
      `;
    }

    return `
      ${renderBasicInfo(prompt)}
      ${renderObjective(prompt)}
      ${renderOutputContract(prompt)}
      ${renderConstraints(prompt)}
      ${renderQualityStandards(prompt)}
      ${renderErrorHandling(prompt)}
      ${renderSystemPrompt(prompt)}
      ${renderCxuContext(prompt, options)}
      ${renderDataPayload(prompt, options.dataPayload)}
    `;
  }

  return {
    generate,
    escapeHtml,
    formatLabel
  };
})();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = PromptFormattedView;
}
