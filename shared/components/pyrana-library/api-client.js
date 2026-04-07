/**
 * Pyrana Library Component - API Client
 *
 * Handles all API communication for the Pyrana Library.
 * Includes API configuration, health checking, and request utilities.
 */

const LibraryApiClient = (function() {
  'use strict';

  // Default API base URLs - can be overridden via init()
  let API_BASES = {
    cxu: 'http://localhost:8101',
    prompt: 'http://localhost:8102',
    script: 'http://localhost:8103',
    agent: 'http://localhost:8105'
  };

  // API Configuration for each manager
  // This structure defines endpoints, fields, and form configurations
  const API_CONFIG = {
    cxu_manager: {
      name: 'CxUs',
      baseUrlKey: 'cxu',
      listEndpoint: '/cxus',
      itemEndpoint: '/cxus',
      createEndpoint: '/drafts',
      healthEndpoint: '/health',
      fields: ['cxu_id', 'alias', 'claim', 'knowledge_type', 'claim_type', 'keywords', 'tags', 'status'],
      displayField: 'alias',
      descField: 'claim',
      idField: 'cxu_id',
      formFields: [
        { name: 'alias', label: 'Alias', type: 'text', required: false, placeholder: 'Short identifier (e.g., labor_schema)' },
        { name: 'claim', label: 'Claim', type: 'textarea', required: true, placeholder: 'The main knowledge claim (10-5000 chars)' },
        { name: 'knowledge_type', label: 'Knowledge Type', type: 'select', required: true, options: ['axiom', 'derived', 'prescribed'] },
        { name: 'claim_type', label: 'Claim Type', type: 'select', required: true, options: ['definition', 'observation', 'hypothesis', 'requirement', 'procedure', 'constraint', 'relationship', 'specification', 'step', 'reference', 'summary', 'finding', 'statement'] },
        { name: 'keywords', label: 'Keywords', type: 'text', required: false, placeholder: 'Comma-separated keywords' },
        { name: 'tags', label: 'Tags', type: 'text', required: false, placeholder: 'Comma-separated tags' }
      ]
    },
    script_manager: {
      name: 'Scripts',
      baseUrlKey: 'script',
      listEndpoint: '/api/scripts',
      itemEndpoint: '/api/scripts',
      createEndpoint: '/api/scripts',
      healthEndpoint: '/health',
      fields: ['script_id', 'name', 'display_name', 'description', 'category', 'language', 'code', 'entry_point'],
      displayField: 'display_name',
      descField: 'description',
      idField: 'script_id',
      formFields: [
        { name: 'name', label: 'Name (slug)', type: 'text', required: true, placeholder: 'lowercase-with-hyphens' },
        { name: 'display_name', label: 'Display Name', type: 'text', required: true, placeholder: 'Human readable name' },
        { name: 'description', label: 'Description', type: 'textarea', required: false, placeholder: 'What does this script do?' },
        { name: 'category', label: 'Category', type: 'select', required: true, options: ['validation', 'cache', 'integration', 'setup', 'deployment', 'utility', 'data', 'reporting', 'monitoring', 'maintenance'] },
        { name: 'language', label: 'Language', type: 'select', required: true, options: ['python', 'shell', 'node'] },
        { name: 'entry_point', label: 'Entry Point', type: 'text', required: true, placeholder: 'main' },
        { name: 'code', label: 'Code', type: 'code', required: true, placeholder: 'def main():\n    pass' }
      ]
    },
    prompt_manager: {
      name: 'Prompts',
      baseUrlKey: 'prompt',
      listEndpoint: '/api/prompts',
      itemEndpoint: '/api/prompts',
      createEndpoint: '/api/prompts',
      healthEndpoint: '/health',
      fields: ['prompt_id', 'name', 'description', 'category', 'objective', 'output_contract', 'status', 'cxu_count'],
      displayField: 'name',
      descField: 'description',
      idField: 'prompt_id',
      formFields: [
        { name: 'name', label: 'Name', type: 'text', required: true, placeholder: 'Agent prompt name' },
        { name: 'description', label: 'Description', type: 'textarea', required: false, placeholder: 'What does this agent prompt do?' },
        { name: 'category', label: 'Category', type: 'select', required: true, options: ['extraction', 'generation', 'analysis', 'agent', 'system', 'other'] },
        { name: 'objective', label: 'Objective (JSON)', type: 'json', required: false, placeholder: '{"intent": "...", "success_criteria": "..."}' },
        { name: 'system_prompt', label: 'System Prompt', type: 'textarea', required: false, placeholder: 'Optional system prompt override' }
      ]
    },
    agent_manager: {
      name: 'Agents',
      baseUrlKey: 'agent',
      listEndpoint: '/api/agents',
      itemEndpoint: '/api/agents',
      createEndpoint: '/api/agents',
      healthEndpoint: '/health',
      fields: ['agent_id', 'name', 'description', 'category', 'status'],
      displayField: 'name',
      descField: 'description',
      idField: 'agent_id',
      formFields: [
        { name: 'name', label: 'Name', type: 'text', required: true, placeholder: 'Agent name' },
        { name: 'description', label: 'Description', type: 'textarea', required: true, placeholder: 'What does this agent do?' },
        { name: 'category', label: 'Category', type: 'select', required: true, options: ['analysis', 'generation', 'data', 'integration', 'utility', 'other'] }
      ]
    }
  };

  // API health status tracking
  const healthStatus = {
    cxu_manager: 'pending',
    script_manager: 'pending',
    prompt_manager: 'pending',
    agent_manager: 'pending'
  };

  // Request logging
  const requestLog = [];
  const MAX_LOG_ENTRIES = 100;

  // Event callback for logging
  let onLogEntry = null;

  /**
   * Initialize the API client with custom base URLs
   */
  function init(customBases = {}) {
    Object.assign(API_BASES, customBases);
  }

  /**
   * Get base URL for a manager
   */
  function getBaseUrl(apiKey) {
    const config = API_CONFIG[apiKey];
    if (!config) return null;
    return API_BASES[config.baseUrlKey];
  }

  /**
   * Build full URL for an endpoint
   */
  function buildUrl(config, endpoint, id = null) {
    const baseUrl = API_BASES[config.baseUrlKey];
    let url = baseUrl + endpoint;
    if (id) {
      url += '/' + encodeURIComponent(id);
    }
    return url;
  }

  /**
   * Log an API request/response
   */
  function logRequest(method, url, status, duration, error = null) {
    const entry = {
      timestamp: new Date(),
      method,
      url,
      status,
      duration,
      error
    };

    requestLog.unshift(entry);
    if (requestLog.length > MAX_LOG_ENTRIES) {
      requestLog.pop();
    }

    if (onLogEntry) {
      onLogEntry(entry);
    }

    return entry;
  }

  /**
   * Make an API call with logging
   */
  async function apiCall(method, url, body = null) {
    const startTime = performance.now();
    const options = {
      method,
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      }
    };

    if (body && (method === 'POST' || method === 'PUT' || method === 'PATCH')) {
      options.body = JSON.stringify(body);
    }

    try {
      const response = await fetch(url, options);
      const duration = Math.round(performance.now() - startTime);

      if (!response.ok) {
        const errorText = await response.text();
        logRequest(method, url, response.status, duration, errorText);
        throw new Error(`API Error ${response.status}: ${errorText}`);
      }

      const data = await response.json();
      logRequest(method, url, response.status, duration);
      return data;
    } catch (error) {
      const duration = Math.round(performance.now() - startTime);
      if (!error.message.startsWith('API Error')) {
        logRequest(method, url, 0, duration, error.message);
      }
      throw error;
    }
  }

  /**
   * Check health of all APIs
   */
  async function checkAllHealth() {
    const checks = Object.keys(API_CONFIG).map(async (apiKey) => {
      const config = API_CONFIG[apiKey];
      const url = getBaseUrl(apiKey) + config.healthEndpoint;

      try {
        const response = await fetch(url, {
          method: 'GET',
          signal: AbortSignal.timeout(5000)
        });

        healthStatus[apiKey] = response.ok ? 'healthy' : 'warning';
      } catch (error) {
        healthStatus[apiKey] = 'error';
      }
    });

    await Promise.allSettled(checks);
    return { ...healthStatus };
  }

  /**
   * Check health of a single API
   */
  async function checkHealth(apiKey) {
    const config = API_CONFIG[apiKey];
    if (!config) return 'error';

    const url = getBaseUrl(apiKey) + config.healthEndpoint;

    try {
      const response = await fetch(url, {
        method: 'GET',
        signal: AbortSignal.timeout(5000)
      });

      healthStatus[apiKey] = response.ok ? 'healthy' : 'warning';
    } catch (error) {
      healthStatus[apiKey] = 'error';
    }

    return healthStatus[apiKey];
  }

  /**
   * Fetch list of items for a manager (Active items only)
   */
  async function fetchList(apiKey) {
    const config = API_CONFIG[apiKey];
    if (!config) throw new Error(`Unknown API: ${apiKey}`);

    let url;
    if (apiKey === 'cxu_manager') {
      url = buildUrl(config, config.listEndpoint) + '?limit=5000';
    } else {
      url = buildUrl(config, config.listEndpoint);
    }

    const data = await apiCall('GET', url);

    // Normalize response - some APIs return array, others return object with items
    let items = [];
    if (Array.isArray(data)) {
      items = data;
    } else if (data.items) {
      items = data.items;
    } else if (data.cxus) {
      items = data.cxus;
    } else if (data.scripts) {
      items = data.scripts;
    } else if (data.prompts) {
      items = data.prompts;
    } else if (data.agents) {
      items = data.agents;
    }

    // Exclude Retired items, keep only Active
    items = items.filter(item => {
      const itemStatus = (item.status || item.mutable_metadata?.status || '').toLowerCase();
      return itemStatus === 'active';
    });

    return items;
  }

  /**
   * Fetch a single item by ID
   */
  async function fetchItem(apiKey, itemId) {
    const config = API_CONFIG[apiKey];
    if (!config) throw new Error(`Unknown API: ${apiKey}`);

    const url = buildUrl(config, config.itemEndpoint, itemId);
    return await apiCall('GET', url);
  }

  /**
   * Create a new item
   */
  async function createItem(apiKey, data) {
    const config = API_CONFIG[apiKey];
    if (!config) throw new Error(`Unknown API: ${apiKey}`);

    const url = buildUrl(config, config.createEndpoint);
    return await apiCall('POST', url, data);
  }

  /**
   * Update an existing item
   */
  async function updateItem(apiKey, itemId, data) {
    const config = API_CONFIG[apiKey];
    if (!config) throw new Error(`Unknown API: ${apiKey}`);

    const url = buildUrl(config, config.itemEndpoint, itemId);
    // CXU Manager uses PATCH, others use PUT
    const method = apiKey === 'cxu_manager' ? 'PATCH' : 'PUT';
    return await apiCall(method, url, data);
  }

  /**
   * Delete an item
   */
  async function deleteItem(apiKey, itemId) {
    const config = API_CONFIG[apiKey];
    if (!config) throw new Error(`Unknown API: ${apiKey}`);

    const url = buildUrl(config, config.itemEndpoint, itemId);
    return await apiCall('DELETE', url);
  }

  /**
   * Flatten nested API responses
   * Extracts fields from wrapper objects like mutable_metadata, script_object, etc.
   */
  function flattenApiResponse(obj, mutableFields = new Set(), currentPath = '') {
    const result = {};

    for (const [key, value] of Object.entries(obj)) {
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        const isMutableWrapper = key === 'mutable_metadata';
        const isImmutableWrapper = ['script_object', 'prompt_object', 'agent_object',
          'cxu_object', 'immutable_metadata', 'metadata', 'version'].includes(key);

        if (isMutableWrapper) {
          const nested = flattenApiResponse(value, mutableFields, 'mutable');
          Object.keys(nested).forEach(k => mutableFields.add(k));
          Object.assign(result, nested);
        } else if (isImmutableWrapper) {
          Object.assign(result, flattenApiResponse(value, mutableFields, currentPath));
        } else {
          result[key] = value;
        }
      } else {
        result[key] = value;
        if (currentPath === 'mutable') {
          mutableFields.add(key);
        }
      }
    }

    result._mutableFields = mutableFields;
    return result;
  }

  /**
   * Set the log callback
   */
  function setLogCallback(callback) {
    onLogEntry = callback;
  }

  /**
   * Get request log
   */
  function getRequestLog() {
    return [...requestLog];
  }

  /**
   * Clear request log
   */
  function clearRequestLog() {
    requestLog.length = 0;
  }

  return {
    // Configuration
    API_CONFIG,
    init,
    getBaseUrl,
    buildUrl,

    // Core API methods
    apiCall,
    fetchList,
    fetchItem,
    createItem,
    updateItem,
    deleteItem,

    // Health checking
    checkAllHealth,
    checkHealth,
    getHealthStatus: () => ({ ...healthStatus }),

    // Response processing
    flattenApiResponse,

    // Logging
    setLogCallback,
    getRequestLog,
    clearRequestLog
  };
})();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = LibraryApiClient;
}
