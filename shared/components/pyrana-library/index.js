/**
 * Pyrana Library Component
 *
 * A reusable side tray component for browsing Pyrana platform resources.
 * Supports CxUs, Scripts, Prompts, and Agents.
 * All items are treated as Active (no Draft workflow).
 *
 * Usage:
 *   // Initialize the component
 *   PyranaLibrary.init(document.getElementById('libraryTray'), {
 *     apiBases: {
 *       cxu: 'http://localhost:8001',
 *       script: 'http://localhost:8002',
 *       // ...
 *     }
 *   });
 *
 *   // Control the tray
 *   PyranaLibrary.open();
 *   PyranaLibrary.close();
 *   PyranaLibrary.toggle();
 *
 *   // Select a specific manager
 *   PyranaLibrary.selectManager('cxu_manager');
 *
 *   // Open a specific item
 *   PyranaLibrary.openItem('item-id');
 *
 *   // Event hooks
 *   PyranaLibrary.onItemOpened = (item) => { ... };
 *   PyranaLibrary.onItemSaved = (item) => { ... };
 */

const PyranaLibrary = (function() {
  'use strict';

  // Component state
  let state = {
    initialized: false,
    isOpen: true,
    currentApi: 'cxu_manager',
    apiData: {},
    healthStatus: {},
    hiddenApis: [],
    requiredTag: ''
  };
  const TAG_SCOPED_APIS = new Set(['cxu_manager', 'script_manager', 'prompt_manager', 'agent_manager']);

  // Container element
  let container = null;

  // Sub-components
  let objectList = null;

  // Event hooks (public callbacks)
  let onItemOpened = null;
  let onItemSaved = null;

  /**
   * Initialize the Pyrana Library
   */
  function init(containerEl, config = {}) {
    if (state.initialized) {
      console.warn('[PyranaLibrary] Already initialized');
      return;
    }

    container = containerEl;

    // Inject styles
    if (typeof PyranaLibraryStyles !== 'undefined') {
      PyranaLibraryStyles.inject();
    }

    // Store hidden APIs config
    if (config.hiddenApis) {
      state.hiddenApis = config.hiddenApis;
    }

    // Optional project-level tag guard (applied before side-tray filters)
    if (typeof config.requiredTag === 'string') {
      state.requiredTag = config.requiredTag.trim();
    }

    // Initialize API client with custom bases
    if (config.apiBases && typeof LibraryApiClient !== 'undefined') {
      LibraryApiClient.init(config.apiBases);
    }

    // Setup container structure
    container.innerHTML = generateTrayHtml();
    container.classList.add('library-tray');

    // Initialize sub-components
    initObjectList();
    initModal();

    // Start health checks
    checkApiHealth();

    // Load initial data and fetch all counts
    loadData();
    fetchResourceCounts();

    state.initialized = true;
    console.log('[PyranaLibrary] Initialized');
  }

  /**
   * Generate main tray HTML structure
   */
  function generateTrayHtml() {
    return `
      <div id="libraryObjectListContainer"></div>
    `;
  }

  /**
   * Initialize the object list sub-component
   */
  function initObjectList() {
    const listContainer = container.querySelector('#libraryObjectListContainer');

    if (typeof LibraryObjectList !== 'undefined') {
      LibraryObjectList.init(listContainer, {
        initialApi: state.currentApi,
        hiddenApis: state.hiddenApis
      }, {
        onApiChange: handleApiChange,
        onItemClick: handleItemClick,
        onNewClick: handleNewClick
      });

      // Pass API config to object list
      if (typeof LibraryApiClient !== 'undefined') {
        LibraryObjectList.setApiConfig(LibraryApiClient.API_CONFIG);
      }

      objectList = LibraryObjectList;
    }
  }

  /**
   * Initialize the modal sub-component
   */
  function initModal() {
    if (typeof LibraryModal !== 'undefined') {
      LibraryModal.init(document.body, {
        onSave: handleSave,
        onRetire: handleRetire,
        onClose: handleModalClose
      });
    }
  }

  /**
   * Check API health for all managers
   */
  async function checkApiHealth() {
    if (typeof LibraryApiClient === 'undefined') return;

    try {
      state.healthStatus = await LibraryApiClient.checkAllHealth();

      // Update UI to reflect health status
      Object.keys(state.healthStatus).forEach(apiKey => {
        const status = state.healthStatus[apiKey];
        if (objectList) {
          objectList.setApiOffline(apiKey, status === 'error');
          // Map health status to dot state
          const dotStatus = status === 'ok' ? 'healthy' : status === 'error' ? 'error' : 'warning';
          objectList.setApiHealth(apiKey, dotStatus);
        }
      });
    } catch (err) {
      console.error('[PyranaLibrary] Health check failed:', err);
    }
  }

  /**
   * Normalize tags from array/string inputs into a lowercase-safe list
   */
  function normalizeTagValues(rawValue) {
    if (Array.isArray(rawValue)) {
      return rawValue
        .map(tag => String(tag || '').trim())
        .filter(Boolean);
    }

    if (typeof rawValue === 'string' && rawValue.trim()) {
      return rawValue
        .split(',')
        .map(tag => tag.trim())
        .filter(Boolean);
    }

    return [];
  }

  /**
   * Extract tags from common payload shapes across CxU/Script/Prompt/Agent services
   */
  function extractItemTags(item) {
    if (!item || typeof item !== 'object') return [];

    const tagSources = [
      item.tags,
      item.categories,
      item.mutable_metadata?.tags,
      item.metadata?.tags,
      item.immutable_metadata?.tags,
      item.cxu_object?.tags,
      item.cxu_object?.metadata?.tags,
      item.script_object?.tags,
      item.script_object?.metadata?.tags,
      item.prompt_object?.tags,
      item.prompt_object?.metadata?.tags,
      item.agent?.tags,
      item.agent_object?.tags
    ];

    const tags = new Set();
    tagSources.forEach(source => {
      normalizeTagValues(source).forEach(tag => tags.add(tag));
    });

    return Array.from(tags);
  }

  /**
   * Apply project tag scoping before list/search UI filters
   */
  function applyRequiredTagFilter(items, apiKey) {
    if (!Array.isArray(items) || items.length === 0) return [];
    if (!TAG_SCOPED_APIS.has(apiKey)) return items;

    const requiredTag = String(state.requiredTag || '').trim().toLowerCase();
    if (!requiredTag) return items;

    return items.filter(item => {
      const tags = extractItemTags(item);
      return tags.some(tag => tag.toLowerCase() === requiredTag);
    });
  }

  /**
   * Load data for current API (Active only)
   */
  async function loadData() {
    if (typeof LibraryApiClient === 'undefined') return;

    const apiKey = state.currentApi;

    if (objectList) {
      objectList.setLoading(true);
    }

    try {
      const items = await LibraryApiClient.fetchList(apiKey);
      const scopedItems = applyRequiredTagFilter(items, apiKey);
      state.apiData[apiKey] = scopedItems;

      if (objectList) {
        objectList.setItems(scopedItems);
        objectList.setCount(apiKey, scopedItems.length);
      }
    } catch (err) {
      console.error('[PyranaLibrary] Failed to load data:', err);
      if (objectList) {
        objectList.setItems([]);
      }
    } finally {
      if (objectList) {
        objectList.setLoading(false);
      }
    }
  }

  /**
   * Fetch resource counts for all APIs (Active only)
   */
  async function fetchResourceCounts() {
    if (typeof LibraryApiClient === 'undefined') return;

    const allApis = ['cxu_manager', 'script_manager', 'prompt_manager', 'agent_manager'];
    const apis = allApis.filter(key => !state.hiddenApis.includes(key));

    // Fetch Active counts for all APIs in parallel
    const countPromises = apis.map(apiKey =>
      LibraryApiClient.fetchList(apiKey)
        .then(items => ({ apiKey, count: applyRequiredTagFilter(items, apiKey).length }))
        .catch(() => ({ apiKey, count: 0 }))
    );

    const results = await Promise.allSettled(countPromises);

    // Update object list with counts
    if (objectList) {
      results.forEach(result => {
        if (result.status === 'fulfilled') {
          const { apiKey, count } = result.value;
          objectList.setCount(apiKey, count);
        }
      });
    }
  }

  /**
   * Handle API tab change
   */
  function handleApiChange(apiKey) {
    state.currentApi = apiKey;
    loadData();
  }

  function isApi404Error(err) {
    const message = String(err?.message || '');
    return /^API Error 404\b/.test(message) || /\b404\b/.test(message);
  }

  function normalizeAliasCandidates(rawAlias) {
    const trimmed = String(rawAlias || '').trim().toLowerCase();
    if (!trimmed) return [];

    const out = [trimmed];
    let cursor = trimmed;
    while (cursor.includes('.')) {
      cursor = cursor.slice(0, cursor.lastIndexOf('.')).trim();
      if (cursor && !out.includes(cursor)) {
        out.push(cursor);
      }
    }
    return out;
  }

  async function resolveCxuFallbackId(preferredId, fallbackAlias = '') {
    if (typeof LibraryApiClient === 'undefined') return '';

    let items = state.apiData.cxu_manager;
    if (!Array.isArray(items) || items.length === 0) {
      try {
        const fetched = await LibraryApiClient.fetchList('cxu_manager');
        items = applyRequiredTagFilter(fetched, 'cxu_manager');
        state.apiData.cxu_manager = items;
      } catch (_err) {
        items = [];
      }
    }
    if (!Array.isArray(items) || items.length === 0) return '';

    const normalizedPreferredId = String(preferredId || '').trim().toLowerCase();
    if (normalizedPreferredId) {
      const byId = items.find((item) => {
        const rowId = String(item?.cxu_id || item?.id || '').trim().toLowerCase();
        if (!rowId) return false;
        return rowId === normalizedPreferredId || rowId.startsWith(normalizedPreferredId) || normalizedPreferredId.startsWith(rowId);
      });
      if (byId) return String(byId.cxu_id || byId.id || '').trim();
    }

    const aliasCandidates = normalizeAliasCandidates(fallbackAlias);
    if (aliasCandidates.length === 0) return '';

    const byAlias = items.find((item) => {
      const alias = String(item?.alias || item?.cxu_object?.alias || '').trim().toLowerCase();
      if (!alias) return false;
      return aliasCandidates.includes(alias);
    });
    if (byAlias) return String(byAlias.cxu_id || byAlias.id || '').trim();

    return '';
  }

  /**
   * Handle item click - open in modal
   */
  async function handleItemClick(itemId, options = {}) {
    if (typeof LibraryApiClient === 'undefined' || typeof LibraryModal === 'undefined') return;

    const config = LibraryApiClient.API_CONFIG[state.currentApi];
    const fallbackAlias = typeof options?.fallbackAlias === 'string' ? options.fallbackAlias.trim() : '';

    // Show loading state
    LibraryModal.open('Loading...', '', { itemId });
    LibraryModal.showLoading();

    try {
      let resolvedItemId = itemId;
      let rawItem = null;
      if (state.currentApi === 'cxu_manager' && fallbackAlias && !String(resolvedItemId || '').trim()) {
        resolvedItemId = await resolveCxuFallbackId('', fallbackAlias);
        if (!resolvedItemId) {
          throw new Error(`Unable to resolve CxU alias '${fallbackAlias}'`);
        }
      }
      try {
        // Fetch full item details
        rawItem = await LibraryApiClient.fetchItem(state.currentApi, resolvedItemId);
      } catch (err) {
        const shouldTryCxuFallback = state.currentApi === 'cxu_manager' && fallbackAlias && isApi404Error(err);
        if (!shouldTryCxuFallback) throw err;

        const fallbackId = await resolveCxuFallbackId(resolvedItemId, fallbackAlias);
        if (!fallbackId || fallbackId === resolvedItemId) throw err;

        resolvedItemId = fallbackId;
        rawItem = await LibraryApiClient.fetchItem(state.currentApi, resolvedItemId);
      }
      const item = LibraryApiClient.flattenApiResponse(rawItem);

      // Store item context
      LibraryModal.setItemContext(item, resolvedItemId, state.currentApi);

      // Generate expanded view
      let bodyHtml = '';
      if (typeof LibraryExpandedView !== 'undefined') {
        bodyHtml = LibraryExpandedView.generate(item, config, false);
      } else {
        bodyHtml = `<pre>${JSON.stringify(item, null, 2)}</pre>`;
      }

      // Update modal
      const title = `View ${config.name.slice(0, -1)}`;
      const status = item?.status || rawItem?.status || rawItem?.mutable_metadata?.status;
      const modalOptions = {
        itemId: resolvedItemId,
        status: state.currentApi === 'cxu_manager' ? status : null
      };
      LibraryModal.open(title, bodyHtml, modalOptions);

      // Bind expanded view events
      const modalBody = document.getElementById('libraryModalBody');
      if (modalBody && typeof LibraryExpandedView !== 'undefined') {
        LibraryExpandedView.bindEvents(modalBody);
      }

      // Fire callback
      if (onItemOpened) {
        onItemOpened(item);
      }
    } catch (err) {
      console.error('[PyranaLibrary] Failed to load item:', err);
      LibraryModal.showError('Failed to load item details.');
    }
  }

  /**
   * Handle new item click
   */
  function handleNewClick(apiKey) {
    // TODO: Implement new item form
    console.log('[PyranaLibrary] New item clicked for:', apiKey);
  }

  /**
   * Handle save
   */
  async function handleSave(itemId, changes) {
    if (typeof LibraryApiClient === 'undefined') return;

    const { mutableChanges, immutableChanges } = changes;
    const config = LibraryApiClient.API_CONFIG[state.currentApi];

    // Build update payload
    const updatePayload = {};
    if (Object.keys(mutableChanges).length > 0) {
      updatePayload.mutable_metadata = mutableChanges;
    }
    if (Object.keys(immutableChanges).length > 0) {
      const objectKey = state.currentApi.replace('_manager', '_object');
      updatePayload[objectKey] = immutableChanges;
    }

    await LibraryApiClient.updateItem(state.currentApi, itemId, updatePayload);

    // Refresh data
    await loadData();

    // Fire callback
    if (onItemSaved) {
      onItemSaved({ itemId, changes });
    }

    showNotification('Changes saved successfully', 'success');
  }

  /**
   * Handle retire
   */
  async function handleRetire(itemId) {
    if (typeof LibraryApiClient === 'undefined') return;

    const updatePayload = {
      mutable_metadata: {
        status: 'Retired'
      }
    };

    await LibraryApiClient.updateItem(state.currentApi, itemId, updatePayload);

    // Refresh data
    await loadData();

    showNotification('Item retired successfully', 'success');
  }

  /**
   * Handle modal close
   */
  function handleModalClose() {
    if (objectList) {
      objectList.clearSelection();
    }
  }

  /**
   * Show notification (uses global function if available)
   */
  function showNotification(message, type = 'info') {
    if (typeof window.showNotification === 'function') {
      window.showNotification(message, type);
    } else {
      console.log(`[Notification] ${type}: ${message}`);
    }
  }

  /**
   * Open the tray
   */
  function open() {
    if (!container) return;
    container.classList.remove('collapsed');
    state.isOpen = true;
  }

  /**
   * Close the tray
   */
  function close() {
    if (!container) return;
    container.classList.add('collapsed');
    state.isOpen = false;
  }

  /**
   * Toggle tray open/closed
   */
  function toggle() {
    if (state.isOpen) {
      close();
    } else {
      open();
    }
  }

  /**
   * Select a manager tab
   */
  function selectManager(apiKey) {
    if (!state.initialized) return;

    state.currentApi = apiKey;
    if (objectList) {
      objectList.selectApi(apiKey);
    }
    loadData();
  }

  /**
   * Open a specific item in the modal
   * @param {string} itemId - The item ID to open
   * @param {string} [apiType] - Optional API type (e.g., 'prompt_manager', 'cxu_manager')
   * @param {Object} [options] - Optional open behavior flags
   * @param {string} [options.fallbackAlias] - Alias used to resolve superseded CxU IDs
   */
  function openItem(itemId, apiType, options = {}) {
    if (!state.initialized) return;

    // If apiType is specified, switch to that API first
    if (apiType && apiType !== state.currentApi) {
      state.currentApi = apiType;
      if (objectList) {
        objectList.selectApi(apiType);
      }
    }

    handleItemClick(itemId, options);
  }

  /**
   * Refresh data from APIs
   */
  function refresh() {
    if (!state.initialized) return;
    loadData();
    fetchResourceCounts();
  }

  /**
   * Get current state
   */
  function getState() {
    return {
      isOpen: state.isOpen,
      currentApi: state.currentApi,
      healthStatus: { ...state.healthStatus }
    };
  }

  /**
   * Destroy the component
   */
  function destroy() {
    if (!state.initialized) return;

    // Remove styles
    if (typeof PyranaLibraryStyles !== 'undefined') {
      PyranaLibraryStyles.remove();
    }

    // Clear container
    if (container) {
      container.innerHTML = '';
      container.classList.remove('library-tray');
    }

    // Reset state
    state = {
      initialized: false,
      isOpen: true,
      currentApi: 'cxu_manager',
      apiData: {},
      healthStatus: {},
      hiddenApis: [],
      requiredTag: ''
    };

    container = null;
    objectList = null;
  }

  // Public API
  return {
    // Initialization
    init,
    destroy,

    // Tray control
    open,
    close,
    toggle,

    // Navigation
    selectManager,
    openItem,

    // Data
    refresh,
    getState,

    // Event hooks (set these to receive callbacks)
    get onItemOpened() { return onItemOpened; },
    set onItemOpened(fn) { onItemOpened = fn; },
    get onItemSaved() { return onItemSaved; },
    set onItemSaved(fn) { onItemSaved = fn; }
  };
})();

// Make available globally
if (typeof window !== 'undefined') {
  window.PyranaLibrary = PyranaLibrary;
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = PyranaLibrary;
}
