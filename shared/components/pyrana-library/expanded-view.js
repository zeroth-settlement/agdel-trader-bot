/**
 * Pyrana Library Component - Expanded View
 *
 * Dynamically renders all fields from an API response with consistent UI/UX.
 * This is the CRITICAL feature that adapts to new API fields automatically.
 *
 * Field Categorization:
 * - *_id fields -> Identifiers section
 * - *_at fields -> Metadata section
 * - Arrays -> Collections section
 * - Objects -> Nested Objects section
 * - Long strings (>100 chars or multiline) -> Content section
 * - Everything else -> Properties section
 *
 * Managing New Fields:
 * The dynamic categorization handles new fields automatically. To customize display:
 * 1. Update API_CONFIG[manager].fields for tile display
 * 2. Update API_CONFIG[manager].formFields for "New" form
 * 3. Expanded view adapts automatically to any new schema fields
 */

const LibraryExpandedView = (function() {
  'use strict';

  /**
   * Escape HTML special characters
   */
  function escapeHtml(str) {
    return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /**
   * Format field labels from snake_case
   */
  function formatLabel(key) {
    return key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  }

  /**
   * Render lock icon for immutable fields
   */
  function lockIcon(mutable) {
    return mutable ? '' : ' <span style="color: var(--text-muted); font-weight: normal;">&#128274;</span>';
  }

  /**
   * Generate unique section ID
   */
  function sectionId() {
    return 'section_' + Math.random().toString(36).substr(2, 9);
  }

  /**
   * Render collapsible section header
   */
  function renderSectionHeader(title, contentId, collapsed = false, count = null) {
    const countBadge = count !== null ? ` <span style="font-weight: normal; color: var(--text-muted);">(${count})</span>` : '';
    return `
      <div class="collapsible-section-header" data-target="${contentId}" style="display: flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border);">
        <svg class="collapse-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="transition: transform 0.2s; transform: rotate(${collapsed ? '0' : '90'}deg);">
          <polyline points="9 18 15 12 9 6"/>
        </svg>
        <span>${title}${countBadge}</span>
      </div>
    `;
  }

  /**
   * Check if JSON data is considered "large"
   */
  function isLargeJson(text, parsed) {
    // Large if text is over 500 characters
    if (text.length > 500) return true;

    // Large if it's an array with many items
    if (Array.isArray(parsed) && parsed.length > 5) return true;

    // Large if it's an object with many keys or deeply nested
    if (typeof parsed === 'object' && parsed !== null) {
      const keys = Object.keys(parsed);
      if (keys.length > 8) return true;

      // Check for nested arrays with many items
      for (const key of keys) {
        if (Array.isArray(parsed[key]) && parsed[key].length > 5) return true;
      }
    }

    return false;
  }

  /**
   * Render a placeholder for large JSON data
   */
  function renderLargeJsonPlaceholder(textLength, parsed) {
    let summary = '';
    if (Array.isArray(parsed)) {
      summary = `Array with ${parsed.length} items`;
    } else if (typeof parsed === 'object' && parsed !== null) {
      const keys = Object.keys(parsed);
      summary = `Object with ${keys.length} keys: ${keys.slice(0, 5).join(', ')}${keys.length > 5 ? '...' : ''}`;
    }

    return `
      <div style="padding: 20px; text-align: center; color: var(--text-muted);">
        <svg style="width: 32px; height: 32px; margin-bottom: 8px; opacity: 0.5;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
          <line x1="16" y1="13" x2="8" y2="13"/>
          <line x1="16" y1="17" x2="8" y2="17"/>
          <polyline points="10 9 9 9 8 9"/>
        </svg>
        <div style="font-size: 13px; font-weight: 500; margin-bottom: 4px;">Large JSON data stored in supporting context</div>
        <div style="font-size: 11px; margin-bottom: 8px;">${summary} (${(textLength / 1024).toFixed(1)} KB)</div>
        <div style="font-size: 11px; color: var(--accent);">Switch to Raw JSON view to see full data</div>
      </div>
    `;
  }

  /**
   * Render supporting contexts with intelligent formatting
   */
  function renderSupportingContextsFormatted(contexts) {
    if (!contexts || contexts.length === 0) {
      return '<div style="padding: 16px; background: var(--bg-tertiary); border-radius: 8px; color: var(--text-muted); text-align: center; font-size: 13px;">No supporting contexts</div>';
    }

    return contexts.map((ctx, idx) => {
      let text = '';
      let line = undefined;
      let source = '';
      let parsedJson = null;

      // Handle different context structures
      if (typeof ctx === 'string') {
        text = ctx;
      } else if (typeof ctx === 'object' && ctx !== null) {
        // Check if it has a .text field
        if (ctx.text !== undefined) {
          text = ctx.text;
          line = ctx.line;
          source = ctx.source || '';
        } else {
          // The context object IS the data (no .text wrapper)
          text = JSON.stringify(ctx);
          parsedJson = ctx; // Already parsed
        }
      }

      let contentHtml = '';
      let isJson = false;
      let isLarge = false;

      // Try to parse as JSON if we don't already have it parsed
      if (parsedJson) {
        isJson = true;
        if (isLargeJson(text, parsedJson)) {
          isLarge = true;
          contentHtml = renderLargeJsonPlaceholder(text.length, parsedJson);
        } else {
          contentHtml = renderJsonContent(parsedJson);
        }
      } else if (text.trim().startsWith('{') || text.trim().startsWith('[')) {
        try {
          const parsed = JSON.parse(text);
          isJson = true;

          // Check if JSON is too large to render nicely
          if (isLargeJson(text, parsed)) {
            isLarge = true;
            contentHtml = renderLargeJsonPlaceholder(text.length, parsed);
          } else {
            contentHtml = renderJsonContent(parsed);
          }
        } catch (e) {
          contentHtml = renderTextContent(text);
        }
      } else {
        contentHtml = renderTextContent(text);
      }

      return `
        <div class="supporting-context-card" style="margin-bottom: 8px; background: var(--bg-tertiary); border-radius: 8px; border: 1px solid var(--border); overflow: hidden;">
          <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: var(--bg-secondary); border-bottom: 1px solid var(--border);">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase;">Context ${idx + 1}</span>
              ${isJson ? `<span style="font-size: 10px; padding: 2px 6px; background: var(--accent-dim); color: var(--accent); border-radius: 4px;">${isLarge ? 'LARGE JSON' : 'JSON'}</span>` : ''}
              ${source ? `<span style="font-size: 11px; color: var(--text-muted);">Source: ${escapeHtml(source)}</span>` : ''}
            </div>
            ${line !== undefined ? `<span style="font-size: 11px; color: var(--text-muted);">Line ${line}</span>` : ''}
          </div>
          <div style="padding: 12px; ${isLarge ? '' : 'max-height: 200px; overflow: auto;'}">
            ${contentHtml}
          </div>
        </div>
      `;
    }).join('');
  }

  /**
   * Render JSON content with intelligent formatting
   */
  function renderJsonContent(obj) {
    // Check if it's a schema/data profile
    const schemaTable = tryRenderAsSchemaTable(obj);
    if (schemaTable) return schemaTable;

    // Render as key-value pairs for objects
    if (typeof obj === 'object' && obj !== null && !Array.isArray(obj)) {
      const keys = Object.keys(obj);

      const rows = keys.map(key => {
        const value = obj[key];
        let valueHtml = '';

        if (Array.isArray(value)) {
          const schemaArrayTable = tryRenderAsSchemaTable(value);
          if (schemaArrayTable) {
            valueHtml = schemaArrayTable;
          } else if (value.length === 0) {
            valueHtml = `<span style="color: var(--text-muted);">Empty array</span>`;
          } else if (typeof value[0] !== 'object') {
            valueHtml = `<span style="color: var(--text-secondary);">${value.map(v => escapeHtml(String(v))).join(', ')}</span>`;
          } else {
            valueHtml = `<span style="color: var(--text-secondary);">[${value.length} items]</span>`;
          }
        } else if (typeof value === 'object' && value !== null) {
          const nestedSchema = tryRenderAsSchemaTable(value);
          if (nestedSchema) {
            valueHtml = nestedSchema;
          } else {
            valueHtml = `<pre style="margin: 4px 0 0 0; padding: 8px; background: var(--bg-card); border-radius: 4px; font-size: 11px; overflow: auto;">${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
          }
        } else if (typeof value === 'string' && value.length > 100) {
          valueHtml = `<div style="color: var(--text-secondary); font-size: 12px; line-height: 1.4;">${escapeHtml(value)}</div>`;
        } else {
          valueHtml = `<span style="color: var(--text-secondary);">${escapeHtml(String(value))}</span>`;
        }

        return `
          <div style="margin-bottom: 8px;">
            <div style="font-size: 11px; font-weight: 600; color: var(--color-cxu); margin-bottom: 2px;">${escapeHtml(key)}</div>
            ${valueHtml}
          </div>
        `;
      }).join('');

      return `<div style="font-size: 13px;">${rows}</div>`;
    }

    // For arrays, check if they look like schema fields
    if (Array.isArray(obj)) {
      const schemaArrayTable = tryRenderAsSchemaTable(obj);
      if (schemaArrayTable) return schemaArrayTable;
    }

    // Fallback to formatted JSON
    const formatted = JSON.stringify(obj, null, 2);
    return `<pre style="margin: 0; font-family: 'SF Mono', Monaco, monospace; font-size: 12px; color: var(--text-secondary); white-space: pre-wrap;">${escapeHtml(formatted)}</pre>`;
  }

  /**
   * Render plain text content
   */
  function renderTextContent(text) {
    const escapedText = escapeHtml(text);
    const formatted = escapedText
      .replace(/\\n/g, '\n')
      .replace(/\n/g, '<br>')
      .replace(/\\"/g, '"');

    return `<div style="font-size: 13px; line-height: 1.5; color: var(--text-secondary);">${formatted}</div>`;
  }

  /**
   * Try to render data as a schema/data profile table
   */
  function tryRenderAsSchemaTable(data) {
    // Handle array of field definitions
    if (Array.isArray(data) && data.length > 0) {
      const firstItem = data[0];
      if (typeof firstItem === 'object' && firstItem !== null) {
        const hasSchemaPattern = data.every(item =>
          item && typeof item === 'object' &&
          (item.name || item.field || item.column || item.field_name || item.column_name) &&
          (item.type || item.data_type || item.dataType)
        );

        if (hasSchemaPattern) {
          return renderSchemaFieldsTable(data);
        }
      }
    }

    // Handle object with schema keys
    if (typeof data === 'object' && data !== null && !Array.isArray(data)) {
      const schemaKeys = ['fields', 'columns', 'properties', 'schema', 'attributes', 'field_definitions'];
      for (const key of schemaKeys) {
        if (Array.isArray(data[key]) && data[key].length > 0) {
          const fields = data[key];
          const firstField = fields[0];
          if (typeof firstField === 'object' && firstField !== null) {
            const hasSchemaPattern = fields.every(item =>
              item && typeof item === 'object' &&
              (item.name || item.field || item.column || item.field_name || item.column_name || Object.keys(item).length > 0)
            );

            if (hasSchemaPattern) {
              let metaHtml = '';
              const metaKeys = Object.keys(data).filter(k => !schemaKeys.includes(k));
              if (metaKeys.length > 0) {
                metaHtml = `
                  <div style="margin-bottom: 8px; padding: 8px; background: var(--bg-card); border-radius: 4px; font-size: 11px;">
                    ${metaKeys.map(k => `<span style="margin-right: 12px;"><strong>${k}:</strong> ${escapeHtml(String(data[k]))}</span>`).join('')}
                  </div>
                `;
              }
              return metaHtml + renderSchemaFieldsTable(fields);
            }
          }
        }
      }
    }

    return null;
  }

  /**
   * Render schema fields as a formatted table
   */
  function renderSchemaFieldsTable(fields) {
    const possibleColumns = [
      { key: 'name', aliases: ['field', 'column', 'field_name', 'column_name', 'property'], label: 'Field Name' },
      { key: 'type', aliases: ['data_type', 'dataType', 'field_type'], label: 'Type' },
      { key: 'description', aliases: ['desc', 'comment'], label: 'Description' },
      { key: 'required', aliases: ['nullable', 'optional', 'is_required'], label: 'Required' },
      { key: 'default', aliases: ['default_value', 'defaultValue'], label: 'Default' },
      { key: 'format', aliases: [], label: 'Format' },
      { key: 'example', aliases: ['examples', 'sample'], label: 'Example' }
    ];

    const activeColumns = possibleColumns.filter(col => {
      return fields.some(field => {
        if (field[col.key] !== undefined) return true;
        return col.aliases.some(alias => field[alias] !== undefined);
      });
    });

    const displayColumns = activeColumns.slice(0, 5);

    const getValue = (field, col) => {
      if (field[col.key] !== undefined) return field[col.key];
      for (const alias of col.aliases) {
        if (field[alias] !== undefined) return field[alias];
      }
      return null;
    };

    return `
      <div style="overflow-x: auto; border: 1px solid var(--border); border-radius: 6px;">
        <table style="width: 100%; border-collapse: collapse; font-size: 11px;">
          <thead>
            <tr style="background: var(--bg-secondary);">
              ${displayColumns.map(col => `
                <th style="padding: 6px 10px; text-align: left; font-weight: 600; color: var(--text-muted); border-bottom: 1px solid var(--border); white-space: nowrap;">${col.label}</th>
              `).join('')}
            </tr>
          </thead>
          <tbody>
            ${fields.map((field, idx) => `
              <tr style="background: ${idx % 2 === 0 ? 'var(--bg-primary)' : 'var(--bg-card)'};">
                ${displayColumns.map(col => {
      let val = getValue(field, col);
      let displayVal = '';

      if (val === null || val === undefined) {
        displayVal = '<span style="color: var(--text-muted);">-</span>';
      } else if (col.key === 'required') {
        if (typeof val === 'boolean') {
          displayVal = val ? '&#10003;' : '';
        } else {
          displayVal = escapeHtml(String(val));
        }
      } else if (col.key === 'type') {
        displayVal = `<code style="background: var(--accent-dim); color: var(--accent); padding: 1px 4px; border-radius: 3px; font-size: 10px;">${escapeHtml(String(val))}</code>`;
      } else if (typeof val === 'object') {
        displayVal = `<code style="font-size: 9px;">${escapeHtml(JSON.stringify(val).substring(0, 30))}${JSON.stringify(val).length > 30 ? '...' : ''}</code>`;
      } else {
        const strVal = String(val);
        displayVal = strVal.length > 40 ? escapeHtml(strVal.substring(0, 40)) + '...' : escapeHtml(strVal);
      }

      return `<td style="padding: 6px 10px; border-bottom: 1px solid var(--border-subtle); color: var(--text-secondary);">${displayVal}</td>`;
    }).join('')}
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
      <div style="font-size: 10px; color: var(--text-muted); margin-top: 4px; text-align: right;">${fields.length} fields</div>
    `;
  }

  /**
   * Render a nested object as flattened key-value pairs
   */
  function renderFlattenedObject(key, obj, mutable) {
    const entries = Object.entries(obj);
    if (entries.length === 0) {
      return `
        <div style="margin-bottom: 16px; padding: 12px; background: var(--bg-card); border-radius: 8px; border: 1px solid var(--border);">
          <div style="font-size: 12px; font-weight: 600; color: var(--accent); margin-bottom: 8px;">${formatLabel(key)}${lockIcon(mutable)}</div>
          <div style="color: var(--text-muted); font-size: 12px; font-style: italic;">Empty object</div>
        </div>
      `;
    }

    const simpleEntries = [];
    const complexEntries = [];

    entries.forEach(([k, v]) => {
      if (v === null || v === undefined) return;
      if (typeof v === 'object') {
        complexEntries.push([k, v]);
      } else {
        simpleEntries.push([k, v]);
      }
    });

    let html = `
      <div style="margin-bottom: 16px; padding: 12px; background: var(--bg-card); border-radius: 8px; border: 1px solid var(--border);">
        <div style="font-size: 12px; font-weight: 600; color: var(--accent); margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border-subtle);">${formatLabel(key)}${lockIcon(mutable)}</div>
    `;

    if (simpleEntries.length > 0) {
      html += `
        <table style="width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: ${complexEntries.length > 0 ? '12px' : '0'};">
          <tbody>
            ${simpleEntries.map(([k, v]) => {
        let displayValue = v;
        if (typeof v === 'boolean') {
          displayValue = v ? 'Yes' : 'No';
        }
        if (k.endsWith('_at') && typeof v === 'string') {
          try { displayValue = new Date(v).toLocaleString(); } catch (e) { }
        }
        return `
                <tr>
                  <td style="padding: 4px 8px 4px 0; color: var(--text-muted); white-space: nowrap; width: 30%;">${formatLabel(k)}</td>
                  <td style="padding: 4px 0; color: var(--text-primary);">${escapeHtml(String(displayValue))}</td>
                </tr>
              `;
      }).join('')}
          </tbody>
        </table>
      `;
    }

    if (complexEntries.length > 0) {
      complexEntries.forEach(([k, v]) => {
        const isArray = Array.isArray(v);
        const jsonStr = JSON.stringify(v, null, 2);
        const rows = Math.min(6, Math.max(2, jsonStr.split('\n').length));
        html += `
          <div style="margin-top: 8px;">
            <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 4px;">${formatLabel(k)} ${isArray ? `(${v.length} items)` : ''}</div>
            <textarea class="step-input" data-field="${key}.${k}" data-is-json="true" rows="${rows}" readonly style="background: var(--bg-tertiary); font-family: 'SF Mono', Monaco, monospace; font-size: 11px; width: 100%;">${escapeHtml(jsonStr)}</textarea>
          </div>
        `;
      });
    }

    html += '</div>';
    return html;
  }

  /**
   * Render an array of objects as a table
   */
  function renderObjectArrayAsTable(key, items) {
    if (!items || items.length === 0) {
      return '<div style="color: var(--text-muted); font-style: italic; padding: 8px;">No items</div>';
    }

    const allKeys = new Set();
    items.forEach(item => {
      if (typeof item === 'object' && item !== null) {
        Object.keys(item).forEach(k => allKeys.add(k));
      }
    });

    const columns = Array.from(allKeys);

    if (columns.length > 6 || columns.length === 0) {
      return renderObjectArrayAsCards(key, items);
    }

    return `
      <div style="overflow-x: auto; max-height: 300px; border: 1px solid var(--border); border-radius: 8px;">
        <table style="width: 100%; border-collapse: collapse; font-size: 12px;">
          <thead style="position: sticky; top: 0; background: var(--bg-secondary);">
            <tr>
              ${columns.map(col => `
                <th style="padding: 8px 12px; text-align: left; font-weight: 600; color: var(--text-muted); border-bottom: 1px solid var(--border); white-space: nowrap;">${formatLabel(col)}</th>
              `).join('')}
            </tr>
          </thead>
          <tbody>
            ${items.map((item, idx) => `
              <tr style="background: ${idx % 2 === 0 ? 'var(--bg-primary)' : 'var(--bg-card)'};">
                ${columns.map(col => {
      const val = item[col];
      let displayVal = '';
      if (val === null || val === undefined) {
        displayVal = '<span style="color: var(--text-muted);">-</span>';
      } else if (typeof val === 'object') {
        displayVal = `<code style="font-size: 10px; background: var(--bg-tertiary); padding: 2px 4px; border-radius: 3px;">${escapeHtml(JSON.stringify(val).substring(0, 50))}${JSON.stringify(val).length > 50 ? '...' : ''}</code>`;
      } else if (typeof val === 'boolean') {
        displayVal = val ? '&#10003;' : '&#10007;';
      } else {
        const strVal = String(val);
        displayVal = strVal.length > 50 ? escapeHtml(strVal.substring(0, 50)) + '...' : escapeHtml(strVal);
      }
      return `<td style="padding: 8px 12px; border-bottom: 1px solid var(--border-subtle); color: var(--text-secondary);">${displayVal}</td>`;
    }).join('')}
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  /**
   * Render an array of objects as cards (fallback)
   */
  function renderObjectArrayAsCards(key, items) {
    return `
      <div style="max-height: 300px; overflow-y: auto;">
        ${items.map((item, idx) => {
      if (typeof item !== 'object' || item === null) {
        return `<div style="padding: 8px; background: var(--bg-tertiary); border-radius: 4px; margin-bottom: 4px; font-size: 12px;">${escapeHtml(String(item))}</div>`;
      }

      const entries = Object.entries(item);
      return `
            <div style="padding: 10px; background: var(--bg-card); border-radius: 6px; margin-bottom: 8px; border: 1px solid var(--border);">
              <div style="font-size: 10px; color: var(--text-muted); margin-bottom: 6px;">Item ${idx + 1}</div>
              ${entries.slice(0, 5).map(([k, v]) => {
        let displayVal = v;
        if (typeof v === 'object' && v !== null) {
          displayVal = JSON.stringify(v).substring(0, 100) + (JSON.stringify(v).length > 100 ? '...' : '');
        }
        return `
                  <div style="display: flex; gap: 8px; font-size: 11px; margin-bottom: 2px;">
                    <span style="color: var(--text-muted); min-width: 80px;">${formatLabel(k)}:</span>
                    <span style="color: var(--text-secondary); word-break: break-word;">${escapeHtml(String(displayVal))}</span>
                  </div>
                `;
      }).join('')}
              ${entries.length > 5 ? `<div style="font-size: 10px; color: var(--text-muted); margin-top: 4px;">...and ${entries.length - 5} more fields</div>` : ''}
            </div>
          `;
    }).join('')}
      </div>
    `;
  }

  /**
   * MAIN FUNCTION: Generate the expanded view HTML
   *
   * @param {Object} item - The flattened item object from API
   * @param {Object} config - API configuration for this manager
   * @returns {string} HTML string for the expanded view
   */
  function generate(item, config) {
    const mutableFields = item._mutableFields || new Set();
    const resourceName = config?.name?.slice(0, -1) || 'Resource';
    const fullJsonEscaped = escapeHtml(JSON.stringify(item, null, 2));

    // Categorize fields dynamically
    const idFields = [];
    const metaFields = [];
    const shortFields = [];
    const longFields = [];
    const arrayFields = [];
    const objectFields = [];
    // Fields starting with underscore are internal and should be hidden
    const hiddenFields = ['_mutableFields', '_raw', '_cxu_object', '_mutable_metadata', '_immutable_metadata', '_metadata'];

    Object.entries(item).forEach(([key, value]) => {
      // Skip undefined, hidden fields, and any field starting with underscore
      if (value === undefined || hiddenFields.includes(key) || key.startsWith('_')) return;

      if (key.endsWith('_id') || key === 'id') {
        idFields.push({ key, value, mutable: mutableFields.has(key) });
      } else if (key.endsWith('_at') || key === 'created_at' || key === 'updated_at' || key === 'last_used_at') {
        metaFields.push({ key, value, mutable: mutableFields.has(key) });
      } else if (key === 'status' || key === 'version' || key === 'usage_count') {
        metaFields.push({ key, value, mutable: mutableFields.has(key) });
      } else if (Array.isArray(value)) {
        arrayFields.push({ key, value, mutable: mutableFields.has(key) });
      } else if (typeof value === 'object' && value !== null) {
        objectFields.push({ key, value, mutable: mutableFields.has(key) });
      } else if (typeof value === 'string' && (value.length > 100 || value.includes('\n'))) {
        longFields.push({ key, value, mutable: mutableFields.has(key) });
      } else {
        shortFields.push({ key, value, mutable: mutableFields.has(key) });
      }
    });

    // Build formatted view HTML
    let formattedHtml = '';

    // ID Fields Section
    if (idFields.length > 0) {
      formattedHtml += `
        <div style="margin-bottom: 20px;">
          <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border);">
            Identifiers
          </div>
          <div style="display: grid; grid-template-columns: repeat(${Math.min(idFields.length, 2)}, 1fr); gap: 12px;">
            ${idFields.map(({ key, value, mutable }) => {
      // Check if this is a reference to another object (prior_cxu_id, prior_script_id, etc.)
      const isReference = key !== 'cxu_id' && key !== 'script_id' && key !== 'id'
        && key.includes('_id') && value && String(value).length > 10;
      const isCxuRef = isReference && (key.includes('cxu') || String(value).startsWith('1220'));
      const isScriptRef = isReference && key.includes('script') && !isCxuRef;
      const refBtnHtml = isCxuRef
        ? `<button type="button" class="open-ref-btn" data-ref-type="cxu" data-ref-id="${escapeHtml(value)}" title="Open ${formatLabel(key)}" style="flex-shrink: 0; width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; background: var(--bg-tertiary); border: 1px solid var(--color-cxu, var(--border)); border-radius: 6px; color: var(--color-cxu, var(--accent)); cursor: pointer; transition: all 0.15s;">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/>
                <polyline points="15 3 21 3 21 9"/>
                <line x1="10" y1="14" x2="21" y2="3"/>
              </svg>
            </button>`
        : isScriptRef
        ? `<button type="button" class="open-ref-btn" data-ref-type="script" data-ref-id="${escapeHtml(value)}" title="Open ${formatLabel(key)}" style="flex-shrink: 0; width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; background: var(--bg-tertiary); border: 1px solid var(--color-script, var(--border)); border-radius: 6px; color: var(--color-script, var(--accent)); cursor: pointer; transition: all 0.15s;">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/>
                <polyline points="15 3 21 3 21 9"/>
                <line x1="10" y1="14" x2="21" y2="3"/>
              </svg>
            </button>`
        : '';
      return `
              <div class="resources-modal-field">
                <label>${formatLabel(key)}${lockIcon(mutable)}</label>
                <div class="id-field-wrapper" style="display: flex; gap: 6px; align-items: center;">
                  <input type="text" data-field="${key}" value="${escapeHtml(value)}" readonly style="flex: 1; background: var(--bg-tertiary); font-family: 'SF Mono', Monaco, monospace; font-size: 11px;${isReference ? ' cursor: pointer; color: var(--accent);' : ''}">
                  ${refBtnHtml}
                  <button type="button" class="copy-id-btn" data-copy-value="${escapeHtml(value)}" title="Copy ${formatLabel(key)}" style="flex-shrink: 0; width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; background: var(--bg-tertiary); border: 1px solid var(--border); border-radius: 6px; color: var(--text-muted); cursor: pointer; transition: all 0.15s;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                      <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
                    </svg>
                  </button>
                </div>
              </div>
            `;
    }).join('')}
          </div>
        </div>
      `;
    }

    // Short Fields Section (collapsible)
    if (shortFields.length > 0) {
      const propsId = sectionId();
      const gridCols = shortFields.length >= 3 ? 3 : Math.min(shortFields.length, 2);
      formattedHtml += `
        <div style="margin-bottom: 20px;">
          ${renderSectionHeader('Properties', propsId, true, shortFields.length)}
          <div id="${propsId}" class="collapsible-content" style="display: none;">
            <div style="display: grid; grid-template-columns: repeat(${gridCols}, 1fr); gap: 12px;">
              ${shortFields.map(({ key, value, mutable }) => `
                <div class="resources-modal-field">
                  <label>${formatLabel(key)}${lockIcon(mutable)}</label>
                  <input type="text" data-field="${key}" value="${escapeHtml(value)}" readonly style="background: var(--bg-tertiary);">
                </div>
              `).join('')}
            </div>
          </div>
        </div>
      `;
    }

    // Long Text Fields Section
    if (longFields.length > 0) {
      const contentId = sectionId();
      formattedHtml += `
        <div style="margin-bottom: 20px;">
          ${renderSectionHeader('Content', contentId, false)}
          <div id="${contentId}" class="collapsible-content">
            ${longFields.map(({ key, value, mutable }) => {
        const isCode = key === 'code' || key === 'template' || key === 'body';
        const rows = Math.min(15, Math.max(4, String(value).split('\n').length));
        const fontStyle = isCode ? "font-family: 'SF Mono', Monaco, monospace; font-size: 12px;" : '';
        return `
                <div class="resources-modal-field">
                  <label>${formatLabel(key)}${lockIcon(mutable)}</label>
                  <textarea data-field="${key}" rows="${rows}" readonly style="background: var(--bg-tertiary); ${fontStyle}">${escapeHtml(value)}</textarea>
                </div>
              `;
      }).join('')}
          </div>
        </div>
      `;
    }

    // Array Fields Section
    if (arrayFields.length > 0) {
      const collectionsId = sectionId();
      formattedHtml += `
        <div style="margin-bottom: 20px;">
          ${renderSectionHeader('Collections', collectionsId, false, arrayFields.reduce((sum, f) => sum + f.value.length, 0) + ' total items')}
          <div id="${collectionsId}" class="collapsible-content">
            ${arrayFields.map(({ key, value, mutable }) => {
        // Special handling for supporting_contexts
        if (key === 'supporting_contexts' && value.length > 0) {
          return `
                  <div class="resources-modal-field">
                    <label>${formatLabel(key)} <span style="font-weight: normal; color: var(--text-muted);">(${value.length} items)</span>${lockIcon(mutable)}</label>
                    <div class="supporting-contexts-display" style="max-height: 400px; overflow-y: auto;">
                      ${renderSupportingContextsFormatted(value)}
                    </div>
                    <textarea data-field="${key}" data-is-json="true" rows="6" style="display: none; background: var(--bg-tertiary); font-family: 'SF Mono', Monaco, monospace; font-size: 12px;">${escapeHtml(JSON.stringify(value, null, 2))}</textarea>
                  </div>
                `;
        }

        // Simple arrays
        const isSimpleArray = value.length === 0 || typeof value[0] !== 'object';
        if (isSimpleArray) {
          return `
                <div class="resources-modal-field">
                  <label>${formatLabel(key)} <span style="font-weight: normal; color: var(--text-muted);">(${value.length} items)</span>${lockIcon(mutable)}</label>
                  <input type="text" data-field="${key}" data-is-array="true" value="${escapeHtml(value.join(', '))}" readonly style="background: var(--bg-tertiary);">
                </div>
              `;
        } else {
          // Complex arrays
          return `
                <div class="resources-modal-field">
                  <label>${formatLabel(key)} <span style="font-weight: normal; color: var(--text-muted);">(${value.length} items)</span>${lockIcon(mutable)}</label>
                  ${renderObjectArrayAsTable(key, value)}
                  <textarea data-field="${key}" data-is-json="true" rows="6" style="display: none; background: var(--bg-tertiary); font-family: 'SF Mono', Monaco, monospace; font-size: 12px;">${escapeHtml(JSON.stringify(value, null, 2))}</textarea>
                </div>
              `;
        }
      }).join('')}
          </div>
        </div>
      `;
    }

    // Object Fields Section
    if (objectFields.length > 0) {
      const nestedId = sectionId();
      formattedHtml += `
        <div style="margin-bottom: 20px;">
          ${renderSectionHeader('Nested Objects', nestedId, false, objectFields.length)}
          <div id="${nestedId}" class="collapsible-content">
            ${objectFields.map(({ key, value, mutable }) => renderFlattenedObject(key, value, mutable)).join('')}
          </div>
        </div>
      `;
    }

    // Meta Fields Section
    if (metaFields.length > 0) {
      formattedHtml += `
        <div style="margin-bottom: 20px; padding-top: 16px; border-top: 1px solid var(--border);">
          <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); margin-bottom: 12px;">
            Metadata
          </div>
          <div style="display: grid; grid-template-columns: repeat(${Math.min(metaFields.length, 4)}, 1fr); gap: 12px;">
            ${metaFields.map(({ key, value, mutable }) => {
        let displayValue = value;
        if (key.endsWith('_at') && value) {
          try { displayValue = new Date(value).toLocaleString(); } catch (e) { }
        }
        if (key === 'version' && typeof value === 'object') {
          displayValue = value.number || JSON.stringify(value);
        }
        return `
                <div class="resources-modal-field">
                  <label style="color: var(--text-muted);">${formatLabel(key)}${lockIcon(mutable)}</label>
                  <input type="text" data-field="${key}" value="${escapeHtml(displayValue)}" readonly style="background: var(--bg-tertiary); font-size: 12px;">
                </div>
              `;
      }).join('')}
          </div>
        </div>
      `;
    }

    // Build complete view with toggle
    return `
      <!-- View Toggle -->
      <div class="expanded-view-toggle" style="display: flex; gap: 4px; margin-bottom: 16px; background: var(--bg-tertiary); padding: 4px; border-radius: 8px;">
        <button type="button" class="expanded-view-btn active" data-view="formatted" style="flex: 1; padding: 8px 16px; border: none; border-radius: 6px; font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.15s; background: var(--bg-card); color: var(--text-primary);">
          Formatted View
        </button>
        <button type="button" class="expanded-view-btn" data-view="json" style="flex: 1; padding: 8px 16px; border: none; border-radius: 6px; font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.15s; background: transparent; color: var(--text-muted);">
          View JSON
        </button>
      </div>

      <!-- Formatted View -->
      <div id="expandedFormattedView">
        ${formattedHtml}
      </div>

      <!-- Raw JSON View -->
      <div id="expandedJsonView" style="display: none;">
        <div class="resources-modal-field">
          <label>Full ${resourceName} Object (Raw JSON)</label>
          <pre id="expandedRawJson" style="margin: 0; padding: 16px; background: var(--bg-tertiary); border-radius: 8px; font-family: 'SF Mono', Monaco, monospace; font-size: 12px; line-height: 1.5; overflow: auto; max-height: 600px; white-space: pre-wrap; word-break: break-word; color: var(--text-secondary);">${fullJsonEscaped}</pre>
        </div>
      </div>
    `;
  }

  /**
   * Bind event listeners for the expanded view toggle and collapsible sections
   */
  function bindEvents(container) {
    // Bind view toggle buttons
    const toggleBtns = container.querySelectorAll('.expanded-view-btn');
    toggleBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        const view = btn.dataset.view;
        const formattedView = container.querySelector('#expandedFormattedView');
        const jsonView = container.querySelector('#expandedJsonView');

        if (!formattedView || !jsonView) return;

        toggleBtns.forEach(b => {
          if (b.dataset.view === view) {
            b.classList.add('active');
            b.style.background = 'var(--bg-card)';
            b.style.color = 'var(--text-primary)';
          } else {
            b.classList.remove('active');
            b.style.background = 'transparent';
            b.style.color = 'var(--text-muted)';
          }
        });

        if (view === 'json') {
          formattedView.style.display = 'none';
          jsonView.style.display = 'block';
        } else {
          formattedView.style.display = 'block';
          jsonView.style.display = 'none';
        }
      });
    });

    // Bind collapsible section headers
    const sectionHeaders = container.querySelectorAll('.collapsible-section-header');
    sectionHeaders.forEach(header => {
      header.addEventListener('click', () => {
        const targetId = header.dataset.target;
        const content = container.querySelector('#' + targetId);
        const arrow = header.querySelector('.collapse-arrow');

        if (!content || !arrow) return;

        const isCollapsed = content.style.display === 'none';

        if (isCollapsed) {
          content.style.display = 'block';
          arrow.style.transform = 'rotate(90deg)';
        } else {
          content.style.display = 'none';
          arrow.style.transform = 'rotate(0deg)';
        }
      });
    });

    // Bind reference link buttons (prior_cxu_id, prior_script_id, etc.)
    const refBtns = container.querySelectorAll('.open-ref-btn');
    refBtns.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const refType = btn.dataset.refType;
        const refId = btn.dataset.refId;
        if (!refId) return;

        // Use CxuPill.openInTray for CxU references, or dispatch a custom event
        if (refType === 'cxu' && typeof CxuPill !== 'undefined' && CxuPill.openInTray) {
          CxuPill.openInTray(refId);
        } else if (typeof LibraryModal !== 'undefined' && LibraryModal.openById) {
          LibraryModal.openById(refId, refType === 'script' ? 'scripts' : 'cxus');
        } else {
          // Fallback: dispatch event for app-level handling
          container.dispatchEvent(new CustomEvent('open-reference', {
            bubbles: true,
            detail: { type: refType, id: refId },
          }));
        }
      });

      // Hover effects
      btn.addEventListener('mouseenter', () => {
        btn.style.background = 'var(--bg-hover)';
        btn.style.transform = 'scale(1.05)';
      });
      btn.addEventListener('mouseleave', () => {
        btn.style.background = 'var(--bg-tertiary)';
        btn.style.transform = 'scale(1)';
      });
    });

    // Also make reference input fields clickable
    const refInputs = container.querySelectorAll('input[style*="cursor: pointer"]');
    refInputs.forEach(input => {
      input.addEventListener('click', () => {
        const wrapper = input.closest('.id-field-wrapper');
        const refBtn = wrapper?.querySelector('.open-ref-btn');
        if (refBtn) refBtn.click();
      });
    });

    // Bind copy ID buttons
    const copyBtns = container.querySelectorAll('.copy-id-btn');
    copyBtns.forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();

        const value = btn.dataset.copyValue;
        if (!value) return;

        try {
          await navigator.clipboard.writeText(value);

          // Show success state
          const originalColor = btn.style.color;
          const originalBg = btn.style.background;
          const originalBorder = btn.style.borderColor;

          btn.style.background = 'var(--success-dim)';
          btn.style.borderColor = 'var(--success)';
          btn.style.color = 'var(--success)';
          btn.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
          `;

          // Reset after delay
          setTimeout(() => {
            btn.style.background = originalBg;
            btn.style.borderColor = originalBorder;
            btn.style.color = originalColor;
            btn.innerHTML = `
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
              </svg>
            `;
          }, 1500);

        } catch (err) {
          console.error('[ExpandedView] Failed to copy:', err);
        }
      });

      // Hover effects
      btn.addEventListener('mouseenter', () => {
        btn.style.background = 'var(--bg-hover)';
        btn.style.borderColor = 'var(--accent)';
        btn.style.color = 'var(--accent)';
      });

      btn.addEventListener('mouseleave', () => {
        // Only reset if not in success state
        if (!btn.style.background.includes('success')) {
          btn.style.background = 'var(--bg-tertiary)';
          btn.style.borderColor = 'var(--border)';
          btn.style.color = 'var(--text-muted)';
        }
      });
    });
  }

  return {
    generate,
    bindEvents,
    escapeHtml,
    formatLabel,
    renderSupportingContextsFormatted
  };
})();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = LibraryExpandedView;
}
