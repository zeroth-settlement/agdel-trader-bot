/**
 * Pyrana Library Component - Object List
 *
 * Renders tiles/list view of library resources with filtering.
 * Handles API tabs, search, tag/keyword filters, and item selection.
 * Only shows Active resources (no Draft status toggle).
 */

const LibraryObjectList = (function() {
  'use strict';

  // Component state
  let state = {
    currentApi: 'cxu_manager',
    items: [],
    filteredItems: [],
    loading: false,
    selectedItemId: null,
    searchQuery: '',
    selectedTags: [],
    selectedKeywords: [],
    hiddenApis: [],
    counts: {
      cxu_manager: 0,
      script_manager: 0,
      prompt_manager: 0,
      agent_manager: 0
    }
  };

  // Event callbacks
  let callbacks = {
    onApiChange: null,
    onItemClick: null,
    onNewClick: null
  };

  // Container element
  let container = null;

  /**
   * Escape HTML special characters
   */
  function escapeHtml(str) {
    return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /**
   * Truncate text with ellipsis
   */
  function truncate(str, maxLength = 100) {
    if (!str || str.length <= maxLength) return str;
    return str.substring(0, maxLength) + '...';
  }

  /**
   * Initialize the object list
   */
  function init(containerEl, config, eventCallbacks = {}) {
    container = containerEl;
    Object.assign(callbacks, eventCallbacks);

    if (config?.initialApi) {
      state.currentApi = config.initialApi;
    }
    if (config?.hiddenApis) {
      state.hiddenApis = config.hiddenApis;
    }

    render();
  }

  /**
   * Set API configuration (passed from parent)
   */
  function setApiConfig(apiConfig) {
    state.apiConfig = apiConfig;
  }

  /**
   * Render the complete object list section
   */
  function render() {
    if (!container) return;

    container.innerHTML = `
      ${renderApiTabs()}
      ${renderSearchBar()}
      <div class="library-object-list" id="libraryItemList">
        ${renderItems()}
      </div>
    `;

    bindEvents();
  }

  /**
   * Render search bar with text input and filter dropdowns
   */
  function renderSearchBar() {
    const { tags: availableTags, keywords: availableKeywords } = extractFilterOptions();
    const hasFilters = availableTags.length > 0 || availableKeywords.length > 0;

    return `
      <div class="library-search-bar">
        <div class="library-search-input-wrapper">
          <svg class="library-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/>
            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            type="text"
            class="library-search-input"
            id="librarySearchInput"
            placeholder="Search by name, description, or ID..."
            value="${escapeHtml(state.searchQuery)}"
          />
          ${state.searchQuery ? `
            <button class="library-search-clear" id="librarySearchClear" title="Clear search">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          ` : ''}
        </div>
        ${hasFilters ? `
          <div class="library-filter-row">
            ${availableTags.length > 0 ? `
              <div class="library-filter-dropdown">
                <div class="library-filter-display" id="libraryTagDisplay">
                  ${state.selectedTags.length > 0
                    ? `<span class="library-filter-badge">${state.selectedTags.length} selected</span>`
                    : '<span class="library-filter-placeholder">All tags</span>'}
                  <svg class="library-filter-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="6 9 12 15 18 9"/>
                  </svg>
                </div>
                <div class="library-filter-menu" id="libraryTagMenu">
                  <div class="library-filter-menu-header">
                    <span>Filter by Tags</span>
                    ${state.selectedTags.length > 0 ? `<button class="library-filter-clear-btn" data-filter="tags">Clear</button>` : ''}
                  </div>
                  <div class="library-filter-menu-list">
                    ${availableTags.map(tag => `
                      <label class="library-filter-option">
                        <input type="checkbox" value="${escapeHtml(tag)}" ${state.selectedTags.includes(tag) ? 'checked' : ''} data-filter-type="tag"/>
                        <span class="library-filter-checkbox"></span>
                        <span class="library-filter-option-text">${escapeHtml(tag)}</span>
                      </label>
                    `).join('')}
                  </div>
                </div>
              </div>
            ` : ''}
            ${availableKeywords.length > 0 ? `
              <div class="library-filter-dropdown">
                <div class="library-filter-display" id="libraryKeywordDisplay">
                  ${state.selectedKeywords.length > 0
                    ? `<span class="library-filter-badge">${state.selectedKeywords.length} selected</span>`
                    : '<span class="library-filter-placeholder">All keywords</span>'}
                  <svg class="library-filter-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="6 9 12 15 18 9"/>
                  </svg>
                </div>
                <div class="library-filter-menu" id="libraryKeywordMenu">
                  <div class="library-filter-menu-header">
                    <span>Filter by Keywords</span>
                    ${state.selectedKeywords.length > 0 ? `<button class="library-filter-clear-btn" data-filter="keywords">Clear</button>` : ''}
                  </div>
                  <div class="library-filter-menu-list">
                    ${availableKeywords.map(keyword => `
                      <label class="library-filter-option">
                        <input type="checkbox" value="${escapeHtml(keyword)}" ${state.selectedKeywords.includes(keyword) ? 'checked' : ''} data-filter-type="keyword"/>
                        <span class="library-filter-checkbox"></span>
                        <span class="library-filter-option-text">${escapeHtml(keyword)}</span>
                      </label>
                    `).join('')}
                  </div>
                </div>
              </div>
            ` : ''}
          </div>
          ${(state.selectedTags.length > 0 || state.selectedKeywords.length > 0) ? `
            <div class="library-active-filters">
              ${state.selectedTags.map(tag => `
                <span class="library-active-filter" data-type="tag" data-value="${escapeHtml(tag)}">
                  ${escapeHtml(tag)}
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"/>
                    <line x1="6" y1="6" x2="18" y2="18"/>
                  </svg>
                </span>
              `).join('')}
              ${state.selectedKeywords.map(keyword => `
                <span class="library-active-filter keyword" data-type="keyword" data-value="${escapeHtml(keyword)}">
                  ${escapeHtml(keyword)}
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"/>
                    <line x1="6" y1="6" x2="18" y2="18"/>
                  </svg>
                </span>
              `).join('')}
              <button class="library-clear-all-filters" id="libraryClearAllFilters">Clear all</button>
            </div>
          ` : ''}
        ` : ''}
      </div>
    `;
  }

  /**
   * Extract unique tags and keywords from current items
   */
  function extractFilterOptions() {
    const tagSet = new Set();
    const keywordSet = new Set();

    if (!state.items || state.items.length === 0) {
      return { tags: [], keywords: [] };
    }

    state.items.forEach(item => {
      // Extract tags
      const tags = getItemField(item, 'tags', null) || getItemField(item, 'categories', null);
      if (Array.isArray(tags)) {
        tags.forEach(tag => {
          if (typeof tag === 'string' && tag.trim()) {
            tagSet.add(tag.trim());
          }
        });
      }

      // Extract keywords (separate field)
      const keywords = getItemField(item, 'keywords', null);
      if (Array.isArray(keywords)) {
        keywords.forEach(keyword => {
          if (typeof keyword === 'string' && keyword.trim()) {
            keywordSet.add(keyword.trim());
          }
        });
      }
    });

    return {
      tags: Array.from(tagSet).sort(),
      keywords: Array.from(keywordSet).sort()
    };
  }

  /**
   * Filter items based on search query, selected tags, and keywords
   */
  function filterItems() {
    if (!state.items || state.items.length === 0) {
      state.filteredItems = [];
      return;
    }

    const config = state.apiConfig?.[state.currentApi];
    const idField = config?.idField || 'id';
    const displayField = config?.displayField || 'name';
    const descField = config?.descField || 'description';

    const query = state.searchQuery.toLowerCase().trim();
    const selectedTags = state.selectedTags;
    const selectedKeywords = state.selectedKeywords;

    state.filteredItems = state.items.filter(item => {
      // Text search filter
      if (query) {
        const name = String(getItemField(item, displayField, '') || getItemField(item, 'name', '')).toLowerCase();
        const desc = String(getItemField(item, descField, '') || getItemField(item, 'description', '')).toLowerCase();
        const id = String(getItemField(item, idField, item.id || '')).toLowerCase();
        const alias = String(getItemField(item, 'alias', '')).toLowerCase();

        const matchesText = name.includes(query) ||
                           desc.includes(query) ||
                           id.includes(query) ||
                           alias.includes(query);

        if (!matchesText) return false;
      }

      // Tag filter
      if (selectedTags.length > 0) {
        const itemTags = getItemField(item, 'tags', null) || getItemField(item, 'categories', null) || [];

        const itemTagsLower = Array.isArray(itemTags)
          ? itemTags.map(t => String(t).toLowerCase().trim())
          : [];

        const hasMatchingTag = selectedTags.some(tag =>
          itemTagsLower.includes(tag.toLowerCase())
        );

        if (!hasMatchingTag) return false;
      }

      // Keyword filter
      if (selectedKeywords.length > 0) {
        const itemKeywords = getItemField(item, 'keywords', null) || [];

        const itemKeywordsLower = Array.isArray(itemKeywords)
          ? itemKeywords.map(k => String(k).toLowerCase().trim())
          : [];

        const hasMatchingKeyword = selectedKeywords.some(keyword =>
          itemKeywordsLower.includes(keyword.toLowerCase())
        );

        if (!hasMatchingKeyword) return false;
      }

      return true;
    });
  }

  /**
   * Render API tabs with active count
   */
  function renderApiTabs() {
    const allApis = [
      { key: 'cxu_manager', name: 'CxUs', color: 'cxu' },
      { key: 'script_manager', name: 'Scripts', color: 'script' },
      { key: 'prompt_manager', name: 'Prompts', color: 'prompt' },
      { key: 'agent_manager', name: 'Agents', color: 'agent' }
    ];
    const apis = allApis.filter(api => !state.hiddenApis.includes(api.key));

    return `
      <div class="library-api-tabs">
        ${apis.map(api => {
          const count = state.counts[api.key] || 0;
          return `
            <button class="library-api-tab ${state.currentApi === api.key ? 'active' : ''}"
                    data-api="${api.key}"
                    title="${count} active">
              <span class="library-api-tab-name">${api.name}</span>
              <span class="library-api-tab-count-row">
                <span class="library-api-tab-health-dot pending" data-health="${api.key}"></span>
                <span class="library-api-tab-count">${count}</span>
              </span>
            </button>
          `;
        }).join('')}
      </div>
    `;
  }

  /**
   * Render items list
   */
  function renderItems() {
    if (state.loading) {
      return `
        <div class="library-loading">
          <div class="library-loading-spinner"></div>
          <span>Loading resources...</span>
        </div>
      `;
    }

    if (!state.items || state.items.length === 0) {
      return `
        <div class="library-empty">
          <svg class="library-empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/>
          </svg>
          <div class="library-empty-text">No resources found</div>
          <div class="library-empty-hint">Try creating a new resource</div>
        </div>
      `;
    }

    const config = state.apiConfig?.[state.currentApi];
    const idField = config?.idField || 'id';
    const displayField = config?.displayField || 'name';
    const descField = config?.descField || 'description';

    // Use filtered items if search/tags are active
    const itemsToRender = state.filteredItems;

    // Show "no results" if filter active but no matches
    if (itemsToRender.length === 0 && (state.searchQuery || state.selectedTags.length > 0 || state.selectedKeywords.length > 0)) {
      return `
        <button class="library-new-btn" id="libraryNewBtn">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          New ${config?.name?.slice(0, -1) || 'Item'}
        </button>
        <div class="library-empty library-no-results">
          <svg class="library-empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="11" cy="11" r="8"/>
            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <div class="library-empty-text">No matching resources</div>
          <div class="library-empty-hint">Try adjusting your search or clearing filters</div>
        </div>
      `;
    }

    return `
      <button class="library-new-btn" id="libraryNewBtn">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19"/>
          <line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        New ${config?.name?.slice(0, -1) || 'Item'}
      </button>
      ${itemsToRender.map(item => renderTile(item, idField, displayField, descField)).join('')}
    `;
  }

  /**
   * Extract field value from potentially nested item structure
   * Handles: item.field, item.cxu_object.field, item.mutable_metadata.field
   */
  function getItemField(item, fieldName, fallback = '') {
    if (!item) return fallback;

    // Direct field access
    if (item[fieldName] !== undefined && item[fieldName] !== null && item[fieldName] !== '') {
      return item[fieldName];
    }

    // Check nested cxu_object (CxU Manager)
    if (item.cxu_object && item.cxu_object[fieldName]) {
      return item.cxu_object[fieldName];
    }
    // Check cxu_object.metadata for CxU knowledge_type, claim_type, keywords
    if (item.cxu_object && item.cxu_object.metadata && item.cxu_object.metadata[fieldName]) {
      return item.cxu_object.metadata[fieldName];
    }

    // Check nested script_object, prompt_object, etc.
    const objectKeys = ['script_object', 'prompt_object', 'agent_object'];
    for (const key of objectKeys) {
      if (item[key] && item[key][fieldName]) {
        return item[key][fieldName];
      }
    }

    // Check mutable_metadata
    if (item.mutable_metadata && item.mutable_metadata[fieldName]) {
      return item.mutable_metadata[fieldName];
    }

    // Check metadata (CxU new structure) or immutable_metadata (other object types)
    if (item.metadata && item.metadata[fieldName]) {
      return item.metadata[fieldName];
    }
    if (item.immutable_metadata && item.immutable_metadata[fieldName]) {
      return item.immutable_metadata[fieldName];
    }

    return fallback;
  }

  /**
   * Render a single item tile
   */
  function renderTile(item, idField, displayField, descField) {
    const id = getItemField(item, idField, item.id || '');
    const name = getItemField(item, displayField, '') || getItemField(item, 'name', '') || 'Unnamed';
    const desc = getItemField(item, descField, '') || getItemField(item, 'description', '');
    const status = (getItemField(item, 'status', 'Active')).toLowerCase();
    const isSelected = state.selectedItemId === id;

    return `
      <div class="library-object-tile ${isSelected ? 'selected' : ''}" data-item-id="${escapeHtml(id)}">
        <div class="library-object-tile-header">
          <span class="library-object-tile-name">${escapeHtml(name)}</span>
          <span class="library-object-tile-status ${status}">${escapeHtml(status)}</span>
        </div>
        ${desc ? `<div class="library-object-tile-desc">${escapeHtml(truncate(desc, 100))}</div>` : ''}
        <div class="library-object-tile-id">${escapeHtml(truncate(id, 20))}</div>
      </div>
    `;
  }

  /**
   * Bind event listeners
   */
  function bindEvents() {
    if (!container) return;

    // API tab clicks
    container.querySelectorAll('.library-api-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        const apiKey = tab.dataset.api;
        if (apiKey !== state.currentApi) {
          state.currentApi = apiKey;
          state.selectedItemId = null;
          // Clear search when switching APIs
          state.searchQuery = '';
          state.selectedTags = [];
          state.selectedKeywords = [];
          updateTabStyles();

          if (callbacks.onApiChange) {
            callbacks.onApiChange(apiKey);
          }
        }
      });
    });

    // Search input events
    bindSearchEvents();

    // Item tile clicks
    container.querySelectorAll('.library-object-tile').forEach(tile => {
      tile.addEventListener('click', () => {
        const itemId = tile.dataset.itemId;
        state.selectedItemId = itemId;
        updateTileStyles();

        if (callbacks.onItemClick) {
          callbacks.onItemClick(itemId);
        }
      });
    });

    // New button click
    const newBtn = container.querySelector('#libraryNewBtn');
    if (newBtn) {
      newBtn.addEventListener('click', () => {
        if (callbacks.onNewClick) {
          callbacks.onNewClick(state.currentApi);
        }
      });
    }
  }

  /**
   * Bind search-related event listeners
   */
  function bindSearchEvents() {
    // Search input
    const searchInput = container?.querySelector('#librarySearchInput');
    if (searchInput) {
      // Debounce search input
      let searchTimeout = null;
      searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
          state.searchQuery = e.target.value;
          filterItems();
          renderItemsList();
          updateItemCount();
        }, 200);
      });

      // Handle Escape key
      searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
          state.searchQuery = '';
          searchInput.value = '';
          filterItems();
          renderItemsList();
          updateItemCount();
          updateSearchBar();
        }
      });
    }

    // Clear search button
    const clearBtn = container?.querySelector('#librarySearchClear');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        state.searchQuery = '';
        filterItems();
        renderItemsList();
        updateItemCount();
        updateSearchBar();
      });
    }

    // Dropdown toggle events
    bindDropdownEvents();

    // Active filter chip removal
    container?.querySelectorAll('.library-active-filter').forEach(chip => {
      chip.addEventListener('click', () => {
        const type = chip.dataset.type;
        const value = chip.dataset.value;

        if (type === 'tag') {
          state.selectedTags = state.selectedTags.filter(t => t !== value);
        } else if (type === 'keyword') {
          state.selectedKeywords = state.selectedKeywords.filter(k => k !== value);
        }

        filterItems();
        render();
      });
    });

    // Clear all filters button
    const clearAllBtn = container?.querySelector('#libraryClearAllFilters');
    if (clearAllBtn) {
      clearAllBtn.addEventListener('click', () => {
        state.selectedTags = [];
        state.selectedKeywords = [];
        filterItems();
        render();
      });
    }
  }

  /**
   * Bind dropdown menu events
   */
  function bindDropdownEvents() {
    // Tag dropdown
    const tagDisplay = container?.querySelector('#libraryTagDisplay');
    const tagMenu = container?.querySelector('#libraryTagMenu');
    if (tagDisplay && tagMenu) {
      tagDisplay.addEventListener('click', (e) => {
        e.stopPropagation();
        closeAllDropdowns();
        tagMenu.classList.add('open');
        tagDisplay.classList.add('open');
      });
    }

    // Keyword dropdown
    const keywordDisplay = container?.querySelector('#libraryKeywordDisplay');
    const keywordMenu = container?.querySelector('#libraryKeywordMenu');
    if (keywordDisplay && keywordMenu) {
      keywordDisplay.addEventListener('click', (e) => {
        e.stopPropagation();
        closeAllDropdowns();
        keywordMenu.classList.add('open');
        keywordDisplay.classList.add('open');
      });
    }

    // Checkbox changes in dropdowns
    container?.querySelectorAll('[data-filter-type="tag"]').forEach(checkbox => {
      checkbox.addEventListener('change', () => {
        const value = checkbox.value;
        if (checkbox.checked) {
          if (!state.selectedTags.includes(value)) {
            state.selectedTags.push(value);
          }
        } else {
          state.selectedTags = state.selectedTags.filter(t => t !== value);
        }
        filterItems();
        renderItemsList();
        updateItemCount();
        updateFilterDisplays();
      });
    });

    container?.querySelectorAll('[data-filter-type="keyword"]').forEach(checkbox => {
      checkbox.addEventListener('change', () => {
        const value = checkbox.value;
        if (checkbox.checked) {
          if (!state.selectedKeywords.includes(value)) {
            state.selectedKeywords.push(value);
          }
        } else {
          state.selectedKeywords = state.selectedKeywords.filter(k => k !== value);
        }
        filterItems();
        renderItemsList();
        updateItemCount();
        updateFilterDisplays();
      });
    });

    // Clear buttons in dropdown headers
    container?.querySelectorAll('.library-filter-clear-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const filterType = btn.dataset.filter;
        if (filterType === 'tags') {
          state.selectedTags = [];
        } else if (filterType === 'keywords') {
          state.selectedKeywords = [];
        }
        filterItems();
        render();
      });
    });

    // Close dropdowns when clicking outside
    document.addEventListener('click', closeAllDropdowns);
  }

  /**
   * Close all open dropdown menus
   */
  function closeAllDropdowns() {
    container?.querySelectorAll('.library-filter-menu.open').forEach(menu => {
      menu.classList.remove('open');
    });
    container?.querySelectorAll('.library-filter-display.open').forEach(display => {
      display.classList.remove('open');
    });
  }

  /**
   * Update filter display badges without full re-render
   */
  function updateFilterDisplays() {
    const tagDisplay = container?.querySelector('#libraryTagDisplay');
    if (tagDisplay) {
      tagDisplay.innerHTML = `
        ${state.selectedTags.length > 0
          ? `<span class="library-filter-badge">${state.selectedTags.length} selected</span>`
          : '<span class="library-filter-placeholder">All tags</span>'}
        <svg class="library-filter-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      `;
    }

    const keywordDisplay = container?.querySelector('#libraryKeywordDisplay');
    if (keywordDisplay) {
      keywordDisplay.innerHTML = `
        ${state.selectedKeywords.length > 0
          ? `<span class="library-filter-badge">${state.selectedKeywords.length} selected</span>`
          : '<span class="library-filter-placeholder">All keywords</span>'}
        <svg class="library-filter-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      `;
    }
  }

  /**
   * Update item count display
   */
  function updateItemCount() {
    const countEl = container?.querySelector('.library-item-count');
    if (countEl) {
      const totalCount = state.items?.length || 0;
      const filteredCount = state.filteredItems?.length || 0;
      const hasFilter = state.searchQuery || state.selectedTags.length > 0 || state.selectedKeywords.length > 0;

      countEl.textContent = hasFilter
        ? `${filteredCount} of ${totalCount} item${filteredCount !== 1 ? 's' : ''}`
        : `${totalCount} item${totalCount !== 1 ? 's' : ''}`;
    }
  }

  /**
   * Update search bar (e.g., show/hide clear button)
   */
  function updateSearchBar() {
    const searchBarEl = container?.querySelector('.library-search-bar');
    if (searchBarEl) {
      const newSearchHtml = renderSearchBar();
      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = newSearchHtml;
      searchBarEl.innerHTML = tempDiv.firstElementChild.innerHTML;
      bindSearchEvents();
    }
  }

  /**
   * Update API tab styles
   */
  function updateTabStyles() {
    container.querySelectorAll('.library-api-tab').forEach(tab => {
      if (tab.dataset.api === state.currentApi) {
        tab.classList.add('active');
      } else {
        tab.classList.remove('active');
      }
    });
  }

  /**
   * Update tile selection styles
   */
  function updateTileStyles() {
    container.querySelectorAll('.library-object-tile').forEach(tile => {
      if (tile.dataset.itemId === state.selectedItemId) {
        tile.classList.add('selected');
      } else {
        tile.classList.remove('selected');
      }
    });
  }

  /**
   * Set items and re-render list
   */
  function setItems(items) {
    state.items = items || [];
    filterItems();

    // Check if we need to update filter dropdowns
    const { tags: currentTags, keywords: currentKeywords } = extractFilterOptions();
    const searchBarEl = container?.querySelector('.library-search-bar');
    const hadFilters = searchBarEl?.querySelector('.library-filter-row') !== null;
    const hasFilters = currentTags.length > 0 || currentKeywords.length > 0;

    if (hadFilters !== hasFilters || hasFilters) {
      // Filters changed, need to update search bar
      const activeElement = document.activeElement;
      const wasSearchFocused = activeElement?.id === 'librarySearchInput';
      const cursorPos = wasSearchFocused ? activeElement.selectionStart : null;

      render();

      // Restore focus if search was focused
      if (wasSearchFocused) {
        const searchInput = container?.querySelector('#librarySearchInput');
        if (searchInput) {
          searchInput.focus();
          if (cursorPos !== null) {
            searchInput.setSelectionRange(cursorPos, cursorPos);
          }
        }
      }
    } else {
      // Just update the items list
      renderItemsList();
    }
  }

  /**
   * Re-render just the items list
   */
  function renderItemsList() {
    const listEl = container?.querySelector('#libraryItemList');
    if (listEl) {
      listEl.innerHTML = renderItems();
      bindItemEvents();
    }
    updateItemCount();
  }

  /**
   * Bind only item-related events (for partial re-renders)
   */
  function bindItemEvents() {
    if (!container) return;

    // Item tile clicks
    container.querySelectorAll('.library-object-tile').forEach(tile => {
      tile.addEventListener('click', () => {
        const itemId = tile.dataset.itemId;
        state.selectedItemId = itemId;
        updateTileStyles();

        if (callbacks.onItemClick) {
          callbacks.onItemClick(itemId);
        }
      });
    });

    // New button click
    const newBtn = container.querySelector('#libraryNewBtn');
    if (newBtn) {
      newBtn.addEventListener('click', () => {
        if (callbacks.onNewClick) {
          callbacks.onNewClick(state.currentApi);
        }
      });
    }
  }

  /**
   * Set loading state
   */
  function setLoading(loading) {
    state.loading = loading;
    renderItemsList();
  }

  /**
   * Update count for an API (active count only)
   */
  function setCount(apiKey, count) {
    state.counts[apiKey] = count >= 0 ? count : 0;
    updateTabCounts();
  }

  /**
   * Set active count for an API
   */
  function setCounts(apiKey, activeCount) {
    state.counts[apiKey] = activeCount >= 0 ? activeCount : 0;
    updateTabCounts();
  }

  /**
   * Update tab count displays
   */
  function updateTabCounts() {
    Object.keys(state.counts).forEach(apiKey => {
      const count = state.counts[apiKey];
      const tab = container?.querySelector(`.library-api-tab[data-api="${apiKey}"]`);
      if (tab) {
        const countEl = tab.querySelector('.library-api-tab-count');
        if (countEl) countEl.textContent = count;
        tab.title = `${count} active`;
      }
    });
  }

  /**
   * Mark an API tab as offline
   */
  function setApiOffline(apiKey, offline) {
    const tab = container?.querySelector(`.library-api-tab[data-api="${apiKey}"]`);
    if (tab) {
      if (offline) {
        tab.classList.add('offline');
      } else {
        tab.classList.remove('offline');
      }
    }
  }

  /**
   * Set health status for an API tab dot
   * @param {string} apiKey - The API key
   * @param {string} status - 'healthy', 'error', 'warning', or 'pending'
   */
  function setApiHealth(apiKey, status) {
    const dot = container?.querySelector(`.library-api-tab-health-dot[data-health="${apiKey}"]`);
    if (dot) {
      dot.className = `library-api-tab-health-dot ${status}`;
      dot.setAttribute('data-health', apiKey);
    }
  }

  /**
   * Get current state
   */
  function getState() {
    return { ...state };
  }

  /**
   * Select an API programmatically
   */
  function selectApi(apiKey) {
    if (apiKey !== state.currentApi) {
      state.currentApi = apiKey;
      state.selectedItemId = null;
      updateTabStyles();
    }
  }

  /**
   * Clear selection
   */
  function clearSelection() {
    state.selectedItemId = null;
    updateTileStyles();
  }

  /**
   * Clear search and all filters
   */
  function clearSearch() {
    state.searchQuery = '';
    state.selectedTags = [];
    state.selectedKeywords = [];
    filterItems();
    render();
  }

  /**
   * Set search query programmatically
   */
  function setSearchQuery(query) {
    state.searchQuery = query;
    filterItems();
    renderItemsList();
    updateItemCount();
    updateSearchBar();
  }

  return {
    init,
    render,
    setApiConfig,
    setItems,
    setLoading,
    setCount,
    setCounts,
    setApiOffline,
    setApiHealth,
    getState,
    selectApi,
    clearSelection,
    clearSearch,
    setSearchQuery
  };
})();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = LibraryObjectList;
}
