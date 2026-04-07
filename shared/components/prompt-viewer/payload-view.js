/**
 * Prompt Viewer Component - Payload View
 *
 * Renders the LLM payload preview showing exactly what gets sent to the API.
 */

const PromptPayloadView = (function() {
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
   * Build system prompt from prompt object
   */
  function buildSystemPrompt(prompt, dataPayload) {
    // If there's a custom system_prompt, use it with template substitution
    if (prompt.system_prompt) {
      let systemPrompt = prompt.system_prompt;

      // Substitute {{cxu_context}} if present
      if (systemPrompt.includes('{{cxu_context}}')) {
        const cxus = prompt.cxu_context || [];
        const cxuText = cxus.map(cxu =>
          `[${cxu.alias}] (ID: ${cxu.cxu_id})\nClaim: ${cxu.claim}`
        ).join('\n\n');
        systemPrompt = systemPrompt.replace('{{cxu_context}}', cxuText || 'No CxU context available.');
      }

      // Substitute {{script_output}} with actual data payload
      if (systemPrompt.includes('{{script_output}}')) {
        if (dataPayload && Object.keys(dataPayload).length > 0) {
          systemPrompt = systemPrompt.replace('{{script_output}}', '```json\n' + JSON.stringify(dataPayload, null, 2) + '\n```');
        } else {
          systemPrompt = systemPrompt.replace('{{script_output}}', 'No data payload provided.');
        }
      }

      return systemPrompt;
    }

    // Otherwise build from structured fields
    let text = '';

    // Agent Identity
    text += `# ${prompt.name || 'Agent'}\n`;
    if (prompt.description) {
      text += `${prompt.description}\n`;
    }
    text += '\n';

    // Objective
    if (prompt.objective) {
      text += '## Objective\n';
      if (prompt.objective.intent) {
        text += `${prompt.objective.intent}\n\n`;
      }
      if (prompt.objective.success_criteria) {
        text += `**Success Criteria:** ${prompt.objective.success_criteria}\n\n`;
      }
    }

    // Output Requirements
    if (prompt.output_contract) {
      text += '## Output Requirements\n';
      if (prompt.output_contract.output_type) {
        text += `**Output Type:** ${prompt.output_contract.output_type}\n`;
      }
      if (prompt.output_contract.format) {
        text += `**Format:** ${prompt.output_contract.format}\n`;
      }
      if (prompt.output_contract.output_details) {
        text += `${prompt.output_contract.output_details}\n`;
      }
      text += '\n';
    }

    // Constraints
    if (prompt.constraints && prompt.constraints.length > 0) {
      text += '## Constraints\n';
      prompt.constraints.forEach((c, i) => {
        text += `${i + 1}. ${c}\n`;
      });
      text += '\n';
    }

    // Quality Standards
    if (prompt.quality_standards) {
      text += '## Quality Standards\n';
      text += `${prompt.quality_standards}\n\n`;
    }

    // Error Handling
    if (prompt.error_handling) {
      text += '## Error Handling\n';
      text += `${prompt.error_handling}\n\n`;
    }

    // Citation Requirements (always added)
    text += `## CRITICAL: Citation Requirements

You MUST cite the source CxU for EVERY conclusion, finding, or factual claim. Use this EXACT format:
[cxu_alias:cxu_id]

Example: "Overtime exceeded threshold [labor-010:1220029f88ace65e75d1c92791a56719b422bb3636c85982fe6e94b3fbaf5a514105]"

The cxu_id MUST be the FULL 68-character hash. Every statement derived from context MUST have a citation immediately after it.
`;

    return text;
  }

  /**
   * Build user prompt with CxU context and data payload
   */
  function buildUserPrompt(prompt, dataPayload) {
    let text = '';

    // CxU Context
    const cxuContext = prompt.cxu_context || [];
    if (cxuContext.length > 0) {
      text += '## Policy Context (CxUs)\n\n';
      cxuContext.forEach(cxu => {
        const alias = cxu.alias || `CxU-${(cxu.cxu_id || cxu.id).substring(0, 8)}`;
        const cxuId = cxu.cxu_id || cxu.id;
        const claim = cxu.claim || '';
        const knowledgeType = cxu.knowledge_type || 'unknown';
        const claimType = cxu.claim_type || 'unknown';
        text += `[${alias}] (ID: ${cxuId})\n`;
        text += `Type: ${knowledgeType}/${claimType}\n`;
        text += `Claim: ${claim}\n\n`;
      });
    }

    // Data Payload
    if (!dataPayload) {
      dataPayload = {
        source: 'vw_demo_labor_by_entity_month',
        period: 'January 2026',
        entities: [
          { entity: 'Alpha Systems', headcount: 145, budget_hc: 140, hc_variance_pct: 3.6, ot_rate: 8.5, labor_cost: 520000 },
          { entity: 'Beta Cloud', headcount: 89, budget_hc: 95, hc_variance_pct: -6.3, ot_rate: 11.2, labor_cost: 385000 },
          { entity: 'Sigma Health', headcount: 167, budget_hc: 150, hc_variance_pct: 11.3, ot_rate: 13.5, labor_cost: 1089000 }
        ]
      };
    }

    text += '## Data Payload\n\n';
    text += '```json\n';
    text += JSON.stringify(dataPayload, null, 2);
    text += '\n```\n\n';

    // Task
    text += '## Task\n\n';
    if (prompt.objective && prompt.objective.intent) {
      text += prompt.objective.intent;
    } else {
      text += 'Analyze the provided data according to the policy context and produce the required output.';
    }

    return text;
  }

  /**
   * Build the full API request body
   */
  function buildApiRequest(prompt, options = {}) {
    const systemPrompt = buildSystemPrompt(prompt, options.dataPayload);
    const userPrompt = buildUserPrompt(prompt, options.dataPayload);

    return {
      model: options.model || 'claude-3-5-sonnet-20241022',
      max_tokens: options.maxTokens || 4096,
      temperature: options.temperature || 0.7,
      system: systemPrompt,
      messages: [
        { role: 'user', content: userPrompt }
      ]
    };
  }

  /**
   * Render copy button
   */
  function renderCopyButton(text) {
    const escaped = text.replace(/\\/g, '\\\\').replace(/`/g, '\\`');
    return `
      <button class="pv-copy-btn" onclick="event.stopPropagation(); PromptViewer.copyToClipboard(\`${escaped}\`)">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
          <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
        </svg>
      </button>
    `;
  }

  /**
   * Generate the payload view
   */
  function generate(prompt, options = {}) {
    if (!prompt) {
      return `
        <div class="pv-empty">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
          <div class="pv-empty-title">No Prompt Selected</div>
          <div class="pv-empty-desc">Select a prompt to preview the LLM payload.</div>
        </div>
      `;
    }

    const systemPrompt = buildSystemPrompt(prompt, options.dataPayload);
    const userPrompt = buildUserPrompt(prompt, options.dataPayload);
    const apiRequest = buildApiRequest(prompt, options);

    return `
      <div class="pv-info-banner">
        <strong>LLM Payload Preview</strong> - This shows what would be sent to the LLM API when this prompt is executed.
      </div>

      <div class="pv-payload-preview">
        <!-- System Prompt Section -->
        <div class="pv-payload-section" data-payload="system">
          <div class="pv-payload-header" onclick="PromptViewer.togglePayloadSection(this)">
            <span class="pv-payload-title">System Prompt</span>
            <div style="display: flex; align-items: center; gap: 8px;">
              <span class="pv-payload-badge">${systemPrompt.length.toLocaleString()} chars</span>
              ${renderCopyButton(systemPrompt)}
            </div>
          </div>
          <div class="pv-payload-content">${escapeHtml(systemPrompt)}</div>
        </div>

        <!-- User Prompt Section -->
        <div class="pv-payload-section" data-payload="user">
          <div class="pv-payload-header" onclick="PromptViewer.togglePayloadSection(this)">
            <span class="pv-payload-title">User Prompt (with CxU Context + Data)</span>
            <div style="display: flex; align-items: center; gap: 8px;">
              <span class="pv-payload-badge">${userPrompt.length.toLocaleString()} chars</span>
              ${renderCopyButton(userPrompt)}
            </div>
          </div>
          <div class="pv-payload-content">${escapeHtml(userPrompt)}</div>
        </div>

        <!-- Full API Request Section -->
        <div class="pv-payload-section collapsed" data-payload="api">
          <div class="pv-payload-header" onclick="PromptViewer.togglePayloadSection(this)">
            <span class="pv-payload-title">Full API Request Body</span>
            <span class="pv-payload-badge">JSON</span>
          </div>
          <div class="pv-payload-content">${escapeHtml(JSON.stringify(apiRequest, null, 2))}</div>
        </div>
      </div>
    `;
  }

  /**
   * Get token estimate (rough approximation)
   */
  function estimateTokens(text) {
    // Rough estimate: ~4 characters per token
    return Math.ceil(text.length / 4);
  }

  return {
    generate,
    buildSystemPrompt,
    buildUserPrompt,
    buildApiRequest,
    estimateTokens
  };
})();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = PromptPayloadView;
}
