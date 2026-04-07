/**
 * Prompt Viewer Component - API Client
 *
 * Handles all API interactions for prompts and CxUs.
 * Provides caching and uses shared Flatten utility for data normalization.
 */

const PromptViewerAPI = (function() {
  'use strict';

  // Default API endpoints
  let config = {
    promptApiBase: 'http://localhost:8102',
    cxuApiBase: 'http://localhost:8101'
  };

  // Cache for CxU data
  const cxuCache = {};

  /**
   * Configure API endpoints
   */
  function configure(options) {
    if (options.promptApiBase) config.promptApiBase = options.promptApiBase;
    if (options.cxuApiBase) config.cxuApiBase = options.cxuApiBase;
  }

  /**
   * Flatten prompt API response
   * Uses shared Flatten utility if available, otherwise falls back to simple spread
   */
  function flattenPrompt(data) {
    if (!data) return null;

    // Use shared Flatten utility if available
    if (typeof Flatten !== 'undefined') {
      return Flatten.prompt(data);
    }

    // Fallback for when Flatten is not loaded
    const prompt = data.prompt || data;

    if (prompt.prompt_object) {
      return {
        ...prompt,
        ...prompt.prompt_object,
        _original: data,
        _hasNestedObject: true
      };
    }

    return {
      ...prompt,
      _original: data
    };
  }

  /**
   * Flatten CxU API response
   * Uses shared Flatten utility if available
   */
  function flattenCxu(cxu) {
    if (!cxu) return null;

    // Use shared Flatten utility if available
    if (typeof Flatten !== 'undefined') {
      return Flatten.cxu(cxu);
    }

    // Fallback for when Flatten is not loaded
    const obj = cxu.cxu_object || {};
    const mutable = cxu.mutable_metadata || {};
    const metadata = obj.metadata || cxu.metadata || {};

    return {
      cxu_id: cxu.cxu_id || cxu.id || obj.cxu_id,
      alias: cxu.alias || obj.name || cxu.name,
      claim: obj.claim || cxu.claim,
      knowledge_type: metadata.knowledge_type || obj.knowledge_type || cxu.knowledge_type,
      claim_type: metadata.claim_type || obj.claim_type || cxu.claim_type,
      supporting_contexts: obj.supporting_contexts || cxu.supporting_contexts || [],
      keywords: metadata.keywords || obj.keywords || cxu.keywords || [],
      tags: mutable.tags || cxu.tags || obj.tags || [],
      status: mutable.status || cxu.status || 'Active',
      _raw: cxu
    };
  }

  /**
   * Fetch all prompts
   */
  async function fetchPrompts() {
    try {
      const response = await fetch(`${config.promptApiBase}/api/prompts`);
      if (!response.ok) {
        throw new Error(`Failed to fetch prompts: ${response.status}`);
      }

      const data = await response.json();
      const prompts = data.prompts || data.items || (Array.isArray(data) ? data : []);

      return prompts.map(p => flattenPrompt(p));
    } catch (err) {
      console.error('[PromptViewerAPI] fetchPrompts error:', err);
      throw err;
    }
  }

  /**
   * Fetch a single prompt by ID
   */
  async function fetchPrompt(promptId) {
    try {
      const response = await fetch(`${config.promptApiBase}/api/prompts/${promptId}`);
      if (!response.ok) {
        throw new Error(`Failed to fetch prompt: ${response.status}`);
      }

      const data = await response.json();
      return flattenPrompt(data);
    } catch (err) {
      console.error('[PromptViewerAPI] fetchPrompt error:', err);
      throw err;
    }
  }

  /**
   * Fetch a CxU by ID (with caching)
   */
  async function fetchCxu(cxuId) {
    // Check cache first
    if (cxuCache[cxuId]) {
      return cxuCache[cxuId];
    }

    try {
      const response = await fetch(`${config.cxuApiBase}/cxus/${cxuId}`);
      if (!response.ok) {
        throw new Error(`Failed to fetch CxU: ${response.status}`);
      }

      const data = await response.json();
      const flattened = flattenCxu(data);

      // Cache the result
      cxuCache[cxuId] = flattened;

      return flattened;
    } catch (err) {
      console.error('[PromptViewerAPI] fetchCxu error:', err);
      throw err;
    }
  }

  /**
   * Fetch multiple CxUs by IDs
   */
  async function fetchCxus(cxuIds) {
    const results = [];
    const toFetch = [];

    // Check cache first
    for (const id of cxuIds) {
      if (cxuCache[id]) {
        results.push(cxuCache[id]);
      } else {
        toFetch.push(id);
      }
    }

    // Fetch missing CxUs in parallel
    if (toFetch.length > 0) {
      const fetched = await Promise.allSettled(
        toFetch.map(id => fetchCxu(id))
      );

      for (const result of fetched) {
        if (result.status === 'fulfilled' && result.value) {
          results.push(result.value);
        }
      }
    }

    return results;
  }

  /**
   * Check if prompt API is available
   */
  async function checkHealth() {
    try {
      const response = await fetch(`${config.promptApiBase}/health`, {
        signal: AbortSignal.timeout(3000)
      });
      return response.ok;
    } catch {
      return false;
    }
  }

  /**
   * Clear the CxU cache
   */
  function clearCache() {
    Object.keys(cxuCache).forEach(key => delete cxuCache[key]);
  }

  /**
   * Get current configuration
   */
  function getConfig() {
    return { ...config };
  }

  return {
    configure,
    fetchPrompts,
    fetchPrompt,
    fetchCxu,
    fetchCxus,
    checkHealth,
    clearCache,
    getConfig,
    flattenPrompt,
    flattenCxu
  };
})();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = PromptViewerAPI;
}
