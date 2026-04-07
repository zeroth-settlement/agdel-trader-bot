/**
 * Shared Flattening Utilities
 *
 * Provides consistent flattening of nested API responses for CxUs, Prompts, and other resources.
 * These utilities normalize the various nested structures returned by APIs into flat objects
 * that are easier to work with in the UI.
 *
 * Usage:
 *   const flattened = Flatten.cxu(apiResponse);
 *   const flattened = Flatten.prompt(apiResponse);
 */

const Flatten = (function() {
  'use strict';

  // ─────────────────────────────────────────────────────────────────────────────
  // Helper Functions
  // ─────────────────────────────────────────────────────────────────────────────

  /**
   * Get first non-empty string value from multiple sources
   */
  function getString(...values) {
    for (const v of values) {
      if (v && typeof v === 'string' && v.trim()) return v.trim();
    }
    return '';
  }

  /**
   * Get first non-empty array from multiple sources
   */
  function getArray(...values) {
    for (const v of values) {
      if (Array.isArray(v) && v.length > 0) return v;
    }
    return [];
  }

  /**
   * Get first non-null/non-empty object from multiple sources
   */
  function getObject(...values) {
    for (const v of values) {
      if (v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length > 0) return v;
    }
    return {};
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // CxU Flattening
  // ─────────────────────────────────────────────────────────────────────────────

  /**
   * Flatten nested CxU API response to expose ALL fields
   *
   * CxU Manager API returns (aligned with Context Engine):
   *   {
   *     cxu_id,
   *     alias,
   *     cxu_object: { claim, supporting_contexts, metadata },
   *     version,
   *     mutable_metadata: { status, tags }
   *   }
   *
   * Note: alias and version are at top level, metadata renamed from immutable_metadata
   *
   * @param {Object} cxu - Raw CxU object from API
   * @returns {Object} Flattened CxU with all fields accessible at top level
   */
  function cxu(rawCxu) {
    if (!rawCxu) return null;

    // Extract nested objects
    const obj = rawCxu.cxu_object || {};
    const mutable = rawCxu.mutable_metadata || {};
    // metadata is now the field name (renamed from immutable_metadata)
    const metadata = obj.metadata || rawCxu.metadata || {};
    // version is now at top level (not inside cxu_object)
    const version = rawCxu.version || {};

    // Build flattened result with ALL fields
    const result = {
      // IDs
      cxu_id: getString(rawCxu.cxu_id, rawCxu.id, obj.cxu_id, rawCxu.draft_id),
      draft_id: getString(rawCxu.draft_id),

      // Core fields - alias is now at top level only
      alias: getString(rawCxu.alias, obj.name, rawCxu.name),
      claim: getString(obj.claim, rawCxu.claim),
      knowledge_type: getString(metadata.knowledge_type, obj.knowledge_type, rawCxu.knowledge_type),
      claim_type: getString(metadata.claim_type, obj.claim_type, rawCxu.claim_type),

      // Supporting contexts - CRITICAL: this is often nested JSON
      supporting_contexts: getArray(obj.supporting_contexts, rawCxu.supporting_contexts),

      // Arrays
      keywords: getArray(metadata.keywords, obj.keywords, rawCxu.keywords),
      tags: getArray(mutable.tags, rawCxu.tags, obj.tags),

      // Status and metadata
      status: getString(mutable.status, rawCxu.status, 'Active'),

      // Timestamps
      created_at: getString(rawCxu.created_at, obj.created_at, version.created_at),
      updated_at: getString(rawCxu.updated_at, obj.updated_at, version.updated_at, mutable.updated_at),
      approved_at: getString(rawCxu.approved_at, mutable.approved_at),

      // Source information
      source: getObject(obj.source, rawCxu.source, version.source),
      metadata: getObject(obj.metadata, rawCxu.metadata, metadata),

      // Version info - version is now at top level
      version_number: version.number || version.version_number || rawCxu.version_number,
      lineage: getArray(version.lineage, rawCxu.lineage),

      // Keep original nested structures for reference
      _raw: rawCxu,
      _cxu_object: obj,
      _mutable_metadata: mutable,
      _metadata: metadata
    };

    // Set alias fallback if empty
    if (!result.alias && result.cxu_id) {
      result.alias = `CxU-${result.cxu_id.substring(0, 8)}`;
    }

    // Parse supporting_contexts if they're JSON strings
    if (result.supporting_contexts.length > 0) {
      result.supporting_contexts = result.supporting_contexts.map(ctx => {
        if (typeof ctx === 'string') {
          try {
            return JSON.parse(ctx);
          } catch {
            return { text: ctx };
          }
        }
        return ctx;
      });
    }

    return result;
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // Prompt Flattening
  // ─────────────────────────────────────────────────────────────────────────────

  /**
   * Flatten prompt API response
   *
   * The Prompt Manager API may return nested prompt_object structure:
   *   {
   *     prompt_id,
   *     prompt_object: { name, description, objective, output_contract, ... }
   *   }
   *
   * @param {Object} data - Raw prompt object from API
   * @returns {Object} Flattened prompt with all fields accessible at top level
   */
  function prompt(data) {
    if (!data) return null;

    const rawPrompt = data.prompt || data;

    // If there's a nested prompt_object, flatten it
    if (rawPrompt.prompt_object) {
      const obj = rawPrompt.prompt_object;

      return {
        // Top-level fields
        prompt_id: getString(rawPrompt.prompt_id, rawPrompt.id, obj.prompt_id),

        // Fields from prompt_object
        name: getString(obj.name, rawPrompt.name),
        description: getString(obj.description, rawPrompt.description),
        category: getString(obj.category, rawPrompt.category),
        status: getString(rawPrompt.status, obj.status, 'Active'),

        // Objective
        objective: obj.objective || rawPrompt.objective || {},

        // Output contract
        output_contract: obj.output_contract || rawPrompt.output_contract || {},

        // Constraints and quality
        constraints: getArray(obj.constraints, rawPrompt.constraints),
        quality_standards: getString(obj.quality_standards, rawPrompt.quality_standards),
        error_handling: getString(obj.error_handling, rawPrompt.error_handling),

        // System prompt
        system_prompt: getString(obj.system_prompt, rawPrompt.system_prompt),

        // CxU context
        cxu_context: getArray(obj.cxu_context, rawPrompt.cxu_context),
        cxu_count: (obj.cxu_context || rawPrompt.cxu_context || []).length,

        // Timestamps
        created_at: getString(rawPrompt.created_at, obj.created_at),
        updated_at: getString(rawPrompt.updated_at, obj.updated_at),

        // Keep original for reference
        _original: data,
        _prompt_object: obj,
        _hasNestedObject: true
      };
    }

    // No nested structure, return with minimal processing
    return {
      prompt_id: getString(rawPrompt.prompt_id, rawPrompt.id),
      name: getString(rawPrompt.name),
      description: getString(rawPrompt.description),
      category: getString(rawPrompt.category),
      status: getString(rawPrompt.status, 'Active'),
      objective: rawPrompt.objective || {},
      output_contract: rawPrompt.output_contract || {},
      constraints: getArray(rawPrompt.constraints),
      quality_standards: getString(rawPrompt.quality_standards),
      error_handling: getString(rawPrompt.error_handling),
      system_prompt: getString(rawPrompt.system_prompt),
      cxu_context: getArray(rawPrompt.cxu_context),
      cxu_count: (rawPrompt.cxu_context || []).length,
      created_at: getString(rawPrompt.created_at),
      updated_at: getString(rawPrompt.updated_at),
      _original: data,
      _hasNestedObject: false
    };
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // Agent Flattening
  // ─────────────────────────────────────────────────────────────────────────────

  /**
   * Flatten agent API response
   *
   * @param {Object} data - Raw agent object from API
   * @returns {Object} Flattened agent with all fields accessible at top level
   */
  function agent(data) {
    if (!data) return null;

    const rawAgent = data.agent || data;
    const obj = rawAgent.agent_object || {};

    return {
      agent_id: getString(rawAgent.agent_id, rawAgent.id, obj.agent_id),
      name: getString(obj.name, rawAgent.name, rawAgent.display_name),
      description: getString(obj.description, rawAgent.description),
      category: getString(obj.category, rawAgent.category),
      status: getString(rawAgent.status, obj.status, 'Active'),

      // References
      prompt_id: getString(obj.prompt_id, rawAgent.prompt_id),
      scripts: getArray(obj.scripts, rawAgent.scripts),

      // Configuration
      model: getString(obj.model, rawAgent.model),
      temperature: obj.temperature ?? rawAgent.temperature,
      max_tokens: obj.max_tokens ?? rawAgent.max_tokens,

      // Timestamps
      created_at: getString(rawAgent.created_at, obj.created_at),
      updated_at: getString(rawAgent.updated_at, obj.updated_at),

      // Keep original
      _original: data,
      _agent_object: obj
    };
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // Script Flattening
  // ─────────────────────────────────────────────────────────────────────────────

  /**
   * Flatten script API response
   *
   * @param {Object} data - Raw script object from API
   * @returns {Object} Flattened script with all fields accessible at top level
   */
  function script(data) {
    if (!data) return null;

    const rawScript = data.script || data;
    const obj = rawScript.script_object || {};

    return {
      script_id: getString(rawScript.script_id, rawScript.id, obj.script_id),
      name: getString(obj.name, rawScript.name, rawScript.display_name),
      description: getString(obj.description, rawScript.description),
      category: getString(obj.category, rawScript.category),
      status: getString(rawScript.status, obj.status, 'Active'),

      // Script content
      content: getString(obj.content, rawScript.content),
      language: getString(obj.language, rawScript.language, 'sql'),

      // Parameters
      parameters: getArray(obj.parameters, rawScript.parameters),

      // Timestamps
      created_at: getString(rawScript.created_at, obj.created_at),
      updated_at: getString(rawScript.updated_at, obj.updated_at),

      // Keep original
      _original: data,
      _script_object: obj
    };
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // Batch Operations
  // ─────────────────────────────────────────────────────────────────────────────

  /**
   * Flatten an array of items using the specified flattener
   *
   * @param {Array} items - Array of raw items
   * @param {Function} flattener - Flattening function to use (cxu, prompt, agent, script)
   * @returns {Array} Array of flattened items (nulls filtered out)
   */
  function batch(items, flattener) {
    if (!Array.isArray(items)) return [];
    return items.map(flattener).filter(Boolean);
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // Public API
  // ─────────────────────────────────────────────────────────────────────────────

  return {
    cxu,
    prompt,
    agent,
    script,
    batch,

    // Also expose helpers for custom flattening
    helpers: {
      getString,
      getArray,
      getObject
    }
  };
})();

// Make available globally
if (typeof window !== 'undefined') {
  window.Flatten = Flatten;
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = Flatten;
}
