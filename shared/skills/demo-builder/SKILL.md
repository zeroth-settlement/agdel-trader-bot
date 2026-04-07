---
name: demo-builder
description: Scaffold and design a Pyrana demo project. Creates a new repo, adds pyrana-playground-shared as a submodule, generates the dashboard, defines output contracts, and registers the project in the playground. Use when the user wants to create a new demo, modify a dashboard, or configure visualization mappings.
allowed-tools: Bash, Read, Write, Edit, WebFetch, Glob, Grep
argument-hint: [project-name or "new"]
---

# Pyrana Demo Builder

You are helping the user scaffold and design a Pyrana demo project — from repo creation to a working dashboard.

## Your Role

You are the **creative skill**. You focus on:
- **Scaffolding** — creating new demo repos with the `pyrana-playground-shared` submodule
- **What the user sees** — dashboard layout, tabs, visualizations, interactions
- **What data the dashboard needs** — the output contract that agents must fulfill
- **How agent output maps to UI** — which agent produces which chart, insight card, action item

You do NOT build agents, create CxUs, write scripts, or design prompts. That's `/build-agent`'s job. You define the **requirements** that build-agent fulfills.

## Understanding the Pyrana Flow

```
Background Knowledge -> CxUs --+
                               +-> Prompt -> LLM -> Structured Output -> Dashboard
Input Data -> Script -> Payload +
```

Every insight on the dashboard traces back to a CxU citation. Your dashboard must support this traceability — CxU pills on insight cards, a Library side tray for browsing platform objects, and output viewers for raw agent responses.

## Design System (Required)

All Pyrana dashboards MUST use the Pyrana Design Guide as their styling foundation. No exceptions.

### CSS Files (mandatory in `<head>`)

```html
<link rel="stylesheet" href="/design-guide/pyrana-theme.css">
<link rel="stylesheet" href="/design-guide/pyrana-components.css">
<link rel="stylesheet" href="/design-guide/pyrana-utilities.css">
```

### Rules

- Use CSS custom properties from `pyrana-theme.css` — **never hardcode colors**. The design guide defines `--bg-primary`, `--bg-secondary`, `--text-primary`, `--accent`, `--border`, etc.
- Use **feature color tokens** for Pyrana object types:
  - CxU: blue `--py-color-cxu`
  - Agent: green `--py-color-agent`
  - Prompt: purple `--py-color-prompt`
  - Script: indigo `--py-color-script`
  - Skill: orange `--py-color-skill`
  - Data: amber `--py-color-data`
- Use **utility classes** from `pyrana-utilities.css`: `.py-flex`, `.py-card`, `.py-badge-*`, `.py-gap-*`, `.py-p-*`, `.py-m-*`, etc.
- Use **component classes** from `pyrana-components.css`: `.py-btn`, `.py-alert`, `.py-tab`, `.py-input`, etc.
- Reference the **Pyrana logo SVG** from `/design-guide/logos/`
- Dashboard `<style>` blocks should ONLY contain layout-specific CSS (grid layouts, custom components). Do NOT duplicate theme variables — they come from the design guide CSS.

## Mode Selection

Before starting any work, determine which mode to use:

```
User says "new" or provides a project name with no existing repo?
  └─ YES → Mode 1: Create New Demo
User references an existing repo, or is already in a non-template repo?
  └─ YES → Mode 2: Retrofit Existing Repo
User is in a repo that already matches the template?
  └─ Skip to Phase 1
```

| Mode | When to Use | Starting Phase |
|------|------------|----------------|
| **Mode 1: Create New Demo** (Preferred) | Fresh project, no existing repo | Phase 0a |
| **Mode 2: Retrofit Existing Repo** | Existing codebase needs Pyrana structure | Phase 0b |

## The Workflow

### Starting the Conversation

If `$ARGUMENTS` is "new" or empty, start fresh — go to **Phase 0a** (Mode 1) to scaffold a new repo.

If `$ARGUMENTS` is a project name:
1. Check if a repo already exists at `~/Code/github/pyrana-<project-name>/` or similar
2. If yes and it has `project.json` — ask: **scaffold new or retrofit existing?**
   - **Retrofit** → go to **Phase 0b** (Mode 2: audit & patch)
   - **Continue** → skip to Phase 1 (project already matches template)
3. If no repo exists — go to **Phase 0a** (Mode 1) to scaffold a new repo

### Phase 0a: Scaffold New Demo Repo (Mode 1)

Create a new demo project from scratch, using `pyrana-playground-shared` as a submodule.

**Step 1: Collect project basics**

> "Let's create a new Pyrana demo! First, some basics:
>
> 1. **Project name** — Human-readable (e.g., "Last Mile Hotel Analytics")
> 2. **Project slug** — Short tag (e.g., `lastmile-hotel`)
> 3. **GitHub org** — Where to create the repo (default: `zeroth-tech`)
> 4. **Repo name** — GitHub repo name (default: `pyrana-<slug>`)"

**Step 2: Create the repo and add shared submodule**

```bash
# Create empty repo
gh repo create <org>/<repo-name> --public --clone
cd <repo-name>

# Add shared submodule (design guide + components + starters)
git submodule add https://github.com/zeroth-tech/pyrana-playground-shared.git shared

# Copy starter files from shared into project root
cp shared/starters/bridge_server.py .
cp shared/starters/start.py .
cp shared/starters/requirements.txt .
cp shared/starters/.gitignore .
cp shared/starters/setup.sh .
chmod +x setup.sh

# Run setup (configures shared submodule paths)
./setup.sh
```

**Step 3: Generate scaffold files**

The skill generates these files (they are NOT in the shared repo — they are project-specific):

- `project.json` — Project manifest with name, tag, description, services config
- `dashboard.html` — Starter dashboard with design guide CSS, library side tray, 4 default tabs
- `CLAUDE.md` — Project documentation
- `requirements/architecture.md` — Architecture reference
- `data/sample-output.json` — Minimal valid orchestration output (empty phases)
- `pyrana_objects/` — Platform artifacts directory with subdirs and `.gitkeep` files:
  - `pyrana_objects/README.md`
  - `pyrana_objects/{cxus,agents,prompts,scripts,skills}/.gitkeep`

**Step 4: Verify the scaffold**

```bash
# Check shared assets
ls shared/components/
ls shared/design-guide/

# Install dependencies
pip install -r requirements.txt

# Test the bridge server
python start.py &
sleep 2
curl http://localhost:9002/health
curl -s http://localhost:9002/components/cxu-pill.js | head -5
curl -s http://localhost:9002/design-guide/pyrana-theme.css | head -5
# Kill the test server
kill %1
```

**Step 5: Initial commit**

```bash
git add -A
git commit -m "Initial scaffold via /demo-builder"
git push -u origin main
```

**Deliverable:** A repo with working bridge server, shared submodule, generated scaffold files, and project.json configured with basics.

### Phase 0b: Retrofit Existing Repo (Mode 2)

Bring an existing repo into alignment with the Pyrana demo standard. Always work on a dedicated branch to preserve the original repo state.

**Step 0: Create a branch**

```bash
git checkout -b pyrana-demo
```

**Step 1: Audit the repo**

Audit existing files and map them to the Pyrana demo structure. Check for each required file and report what's present, missing, or outdated:

```
Required File               | Status
----------------------------|--------
shared/                     | Check submodule exists, URL points to pyrana-playground-shared
bridge_server.py            | Check has PROJECT_NAME loading + /design-guide/ + /pyrana-objects/ mounts
start.py                    | Check exists
project.json                | Check exists + has required keys
dashboard.html              | Check exists + uses design guide CSS + library tray (not tab)
CLAUDE.md                   | Check exists
.gitignore                  | Check exists + covers data/exports/
requirements.txt            | Check exists
requirements/architecture.md| Check exists
data/sample-output.json     | Check exists
data/test-data/             | Check exists
pyrana_objects/              | Check exists with subdirs (cxus/, agents/, prompts/, scripts/, skills/)
```

**Step 1b: Map existing files to template structure**

- Move existing data files (CSVs, JSON inputs) to `data/`
- Move any existing agent definitions, CxU exports, prompt templates to `pyrana_objects/`
- Preserve the original repo's code and logic — restructure around it, don't rewrite

**Step 2: Add or fix shared submodule**

If no submodule exists, add `pyrana-playground-shared`:
```bash
git submodule add https://github.com/zeroth-tech/pyrana-playground-shared.git shared
```

If a submodule exists but points to the wrong repo (e.g., `agent-builder-dev`):
```bash
# In .gitmodules, change url to:
# https://github.com/zeroth-tech/pyrana-playground-shared.git
git submodule sync
git submodule update --init
```

**Step 3: Add missing files and directories**

Copy starter files from the shared submodule and generate project-specific files:

Starter files (copy from `shared/starters/`):
- `bridge_server.py` → `cp shared/starters/bridge_server.py .`
- `start.py` → `cp shared/starters/start.py .`
- `requirements.txt` → `cp shared/starters/requirements.txt .`
- `.gitignore` → `cp shared/starters/.gitignore .`
- `setup.sh` → `cp shared/starters/setup.sh . && chmod +x setup.sh`

Generated files (the skill creates these):
- `project.json` → Generate with project name/tag/description
- `dashboard.html` → Generate with design guide CSS and library tray
- `CLAUDE.md` → Generate, customize for project
- `requirements/architecture.md` → Generate, customize for project
- `pyrana_objects/` → Create directory with subdirs (`cxus/`, `agents/`, `prompts/`, `scripts/`, `skills/`) and `.gitkeep` files
- `data/sample-output.json` → Generate minimal valid orchestration output

**Step 4: Verify bridge_server.py**

If you copied from `shared/starters/bridge_server.py`, it should already be correct. Verify it has:
- Dynamic PROJECT_NAME loading from `project.json`
- `/components/` mount → `shared/components/`
- `/design-guide/` mount → `shared/design-guide/`
- `/pyrana-objects/` mount → `pyrana_objects/`
- `/data/` mount → `data/`

If the file is from an older version, replace it: `cp shared/starters/bridge_server.py .`

**Step 5: Verify**

```bash
python start.py &
sleep 2
curl http://localhost:9002/health
curl -s http://localhost:9002/components/cxu-pill.js | head -5
curl -s http://localhost:9002/design-guide/pyrana-theme.css | head -5
kill %1
```

**Deliverable:** Existing repo now matches Pyrana demo structure. Shared submodule added, starter files in place, bridge server working.

### Phase 1: Define the Problem & MVP

> "Now let's define what this demo shows:
>
> 1. **Domain** — What industry or problem space? (e.g., hotel analytics, supply chain, compliance)
> 2. **Problem** — What specific question does this demo answer for its users?
> 3. **Audience** — Who looks at this dashboard? (e.g., C-suite, portfolio managers, analysts)
> 4. **Wow factor** — What's the one thing that makes someone say 'I need this'?"

Collect through conversation:
- Domain description
- Target audience and their key questions
- The 3-5 most important metrics/KPIs
- The "golden path" — what does the demo walkthrough look like?

**Deliverable:** A written problem statement and MVP scope. Save to `requirements/problem-statement.md`.

### Phase 2: Design the Dashboard Layout

For each tab, define:

**Overview Tab:**
- Which KPIs appear as cards (label, format: currency/percent/number, icon)
- Which charts (type: line/bar/area/doughnut, what data they show)
- Any benchmark or comparison grids

**Insights Tab:**
- What categories of insights
- What insight types matter (positive/negative/warning/info)
- What fields each insight shows (signal, hypothesis, data points, comparison)
- How CxU citations should render

**Actions Tab:**
- Kanban columns (default: recommended -> assigned -> in_progress -> closed)
- What fields action items have (title, description, priority, assignee, entity, impact)

**Custom Tabs** (if any):
- What they show and how they're structured

Present the layout plan to the user for feedback before writing code.

**Deliverable:** Updated `project.json` with dashboard config (tabs, kpiLayout, chartConfig).

### Phase 3: Define the Output Contract

This is the critical handoff to `/build-agent`. For each agent phase, define:
- What structured data type the agent produces
- The exact JSON shape (fields, types, required/optional)
- How it maps to the dashboard (which tab, which component)

**Deliverable:** Updated `project.json` with outputMappings. Save detailed output contract to `requirements/output-contract.md`. Agent definitions should be saved as JSON exports in `pyrana_objects/agents/`.

**Note:** `data/` holds **source data** (CSVs, raw inputs) while `pyrana_objects/` holds **platform artifacts** (CxUs, agents, prompts, scripts, skills). The bridge server serves `pyrana_objects/` at `/pyrana-objects/` for dashboard access.

### Phase 4: Build the Dashboard

Customize `dashboard.html` (Phase 0a generates a working skeleton with design guide CSS already linked):
1. Update KPI rendering for your domain's metrics — use design guide card classes
2. Implement Chart.js charts based on your data
3. Customize insight card rendering if needed
4. Customize kanban card rendering if needed
5. Add any domain-specific tabs (do NOT add a Resources tab — use the Library side tray)
6. Update `processOrchestrationData()` output mapping logic if needed
7. Use design guide utility and component classes — avoid inline styles for colors/spacing

### Phase 5: Register in Playground

Add the project to `pyrana_playground.html` in the agent-builder-dev repo:

1. Add to `PROJECTS` constant:
```javascript
'project-tag': {
  name: 'Project Display Name',
  tag: 'project-tag',
  testDataPath: '/test-data/project-tag/',
  testDataFiles: [ /* mapped in agent-builder */ ],
  executionPhases: [ /* defined with agents */ ],
  output: { format: 'json', filename: 'project-output' },
  dashboard: { bridgeUrl: 'http://localhost:9002' }
}
```

2. Add to the `<select id="projectSelector">` dropdown.

### Phase 6: Create Sample Data

Generate `data/sample-output.json` — a realistic orchestration output that matches the output contract. This enables dashboard development without running actual agents.

## pyrana-playground-shared Repo

The shared repo lives at `https://github.com/zeroth-tech/pyrana-playground-shared` and is added as a git submodule at `shared/` in every demo repo.

### Repo Structure

```
pyrana-playground-shared/
├── design-guide/              ← CSS theme, components, utilities, logos
│   ├── pyrana-theme.css
│   ├── pyrana-components.css
│   ├── pyrana-utilities.css
│   └── logos/
├── components/                ← Shared UI components (JS)
│   ├── cxu-pill.js
│   ├── output-viewer.js
│   ├── output-viewer/
│   ├── pyrana-library/
│   ├── agent-executor/
│   └── utils/
├── starters/                  ← Copyable boilerplate files for new demos
│   ├── bridge_server.py
│   ├── start.py
│   ├── requirements.txt
│   ├── .gitignore
│   └── setup.sh
├── skills/                    ← Reference copies of skills (shareable with team)
│   ├── demo-builder/SKILL.md
│   └── build-agent/SKILL.md
└── PYRANA_PLAYGROUND_ARCHITECTURE.md
```

### What's shared (submodule) vs generated (skill)

| Shared (from submodule, updateable) | Generated (by skill, project-specific) |
|-------------------------------------|---------------------------------------|
| `shared/design-guide/` | `dashboard.html` |
| `shared/components/` | `project.json` |
| `shared/starters/` (copied to root) | `CLAUDE.md` |
| | `pyrana_objects/` |
| | `requirements/` |
| | `data/sample-output.json` |

### Updating shared assets in a demo

To pull updates from `pyrana-playground-shared` into an existing demo:

```bash
cd shared
git fetch origin
git log HEAD..origin/main --oneline   # review what changed
git pull origin main                   # import updates
cd ..

# If starters were updated, re-copy any you want:
cp shared/starters/bridge_server.py .

git add shared
git commit -m "Update shared assets to latest"
```

The submodule pins to a specific commit. Demos don't auto-update — you choose when.

## Shared Components

> **CRITICAL: Never use mock data for shared components.**
> The `_example/` directory in `pyrana-playground-shared` contains a component showcase that uses hardcoded mock data and stubs out `LibraryApiClient`. That pattern is for visual testing ONLY.
> Demo dashboards MUST use the **real `LibraryApiClient`** from `/components/pyrana-library/api-client.js` and connect to the **pyrana-playground-services APIs** (CxU Manager `:8101`, Prompt Manager `:8102`, Script Manager `:8103`, Skill Manager `:8104`, Agent Manager `:8105`).
> Never define `MOCK_CXUS`, `MOCK_ITEMS`, or similar hardcoded data arrays in a demo dashboard. Never override or stub `window.LibraryApiClient`. If services are offline, the dashboard should degrade gracefully (show connection errors) — not fall back to fake data.

These components ship with every demo via the `pyrana-playground-shared` submodule and are served by the bridge at `/components/`:

| Component | Path | What It Does |
|-----------|------|-------------|
| `CxuPill` | `/components/cxu-pill.js` | Renders clickable CxU citation pills. Call `CxuPill.render(cxuId, alias)` |
| `OutputViewer` | `/components/output-viewer.js` | Renders markdown with CxU pill integration |
| `OutputViewerPanel` | `/components/output-viewer/index.js` | Full output panel with metadata tray (model, tokens, CxU refs, agent info) |
| `PyranaLibrary` | `/components/pyrana-library/index.js` | Side tray for browsing CxUs, agents, prompts, scripts via the Services API |
| `Flatten` | `/components/utils/flatten.js` | Normalizes nested API responses |
| `AgentExecutor` | `/components/agent-executor/index.js` | Shared LLM execution engine (Anthropic + Gemini). Enables interactive re-run from dashboards. |

**Always use these.** Don't rebuild what already exists. Load them in `<head>` as `<script src="/components/...">`.

### Design Guide CSS

The Pyrana Design Guide is served at `/design-guide/` from the submodule. See the **Design System (Required)** section above for mandatory usage rules. Load all three CSS files in `<head>` — never hardcode theme colors in inline styles.

### Interactive Re-Run Capability

Dashboards should include a **Settings modal** (gear button in header) for configuring API keys, model selection, temperature, and max tokens. When keys are configured, each agent in the Agent Output tab gets a "Re-run" button that:
1. Fetches fresh CxUs from the CxU Manager (picks up any edits made in the Library tray)
2. Loads test data from `/data/test-data/`
3. Calls the LLM via `AgentExecutor.execute()`
4. Merges the result back into orchestration data and re-renders all tabs

API keys are persisted to `localStorage` so users only configure once per browser.

## Pyrana Design Guide

### Dark Theme (mandatory)
All Pyrana dashboards use the dark theme. **Do NOT inline theme CSS variables** — they are provided by `/design-guide/pyrana-theme.css`. See the **Design System (Required)** section for the full set of rules. Dashboard `<style>` blocks should only contain layout-specific CSS, not theme colors.

### Single-File HTML Pattern
Dashboards are single `.html` files with embedded CSS and JavaScript. External dependencies (Chart.js, Marked) load from CDN.

### Standard Dashboard Anatomy
```
<head>
  CDN libs (Chart.js, Marked)
  Design guide CSS (/design-guide/...)   ← MANDATORY, provides all theme variables
  Shared components (/components/...)
  <style> Layout-specific CSS only (no theme variables) </style>
</head>
<body>
  <header> Project name, connection status, Library button, settings button </header>
  Settings modal (API keys, model, temperature)
  <nav> Tab bar </nav>
  <main>
    Tab: Overview — KPI cards, charts, benchmarks
    Tab: Insights — Filterable insight cards with CxU citations
    Tab: Actions — Kanban board or action list
    Tab: Agent Output — Per-agent output with OutputViewerPanel + Re-run buttons
    (additional custom tabs as needed)
  </main>
  <aside> Library side tray — PyranaLibrary, slides in from right </aside>
  <script> State management, polling, rendering, re-run logic </script>
</body>
```

### Mandatory Tabs
Every demo MUST include these tabs (additional tabs are welcome):
- **Agent Output** — uses `OutputViewerPanel.create()` to show raw agent responses

### Library Side Tray (mandatory)
Every dashboard MUST include a **Library side tray** (NOT a tab) for browsing Pyrana platform objects:
- A **toggle button** in the header right side (book icon + "Library" label) shows/hides the tray
- The tray is an `<aside>` that slides in from the right, overlaying the main content
- Uses `PyranaLibrary.init()` configured for the current project's services
- The tray has a close button in its header and a click-away overlay

### Insight Cards Must Support Citations
Any card showing an agent-derived insight MUST render CxU citation pills. Use `CxuPill.render(cxuId, alias)` or process markdown citations with `CxuPill.processMarkdownCitations()`.

## Three Demo Modes

| Mode | Services Required | LLM Keys | Re-run |
|------|------------------|----------|--------|
| Static | No | No | No — loads saved exports, re-run buttons hidden |
| Interactive | Yes | Yes | Yes — edit CxUs, re-run agents, see changes |
| Production Export | Yes | No | No — package objects for import |

## project.json Schema

The project manifest is the **single source of truth** for the project. See `CLAUDE.md` in the demo repo for the full schema.

## Output Contracts

Agents must produce JSON matching these standard shapes:

### EnhancedInsight
```json
{
  "type": "positive|negative|warning|info",
  "category": "string",
  "title": "string",
  "description": "string",
  "signal": "string",
  "hypothesis": "string",
  "dataPoints": ["string"],
  "priority": "high|medium|low",
  "comparison": "string",
  "citations": [{ "cxu_id": "string", "alias": "string" }]
}
```

### ActionItem
```json
{
  "title": "string",
  "description": "string",
  "priority": "high|medium|low",
  "status": "recommended|assigned|in_progress|closed",
  "rationale": "string",
  "estimatedImpact": "string",
  "assignedTo": { "name": "string", "role": "string" }
}
```

## File Checklist

When complete, the demo repo should have:

- [ ] `shared/` — `pyrana-playground-shared` submodule (design guide + components + starters)
- [ ] `bridge_server.py` — Copied from `shared/starters/`, configured for project
- [ ] `start.py` — Copied from `shared/starters/`
- [ ] `dashboard.html` — Working single-file dashboard with design guide CSS, library side tray
- [ ] `project.json` — Complete manifest with all sections
- [ ] `data/sample-output.json` — Realistic sample for development
- [ ] `pyrana_objects/` — Platform artifacts directory with subdirs (cxus/, agents/, prompts/, scripts/, skills/)
- [ ] `requirements/problem-statement.md` — Domain, audience, MVP
- [ ] `requirements/output-contract.md` — Exact JSON shapes agents must produce
- [ ] Playground registration — PROJECTS entry + dropdown + dashboard.bridgeUrl

## Rules

- ALWAYS use the Pyrana Design Guide CSS files — never hardcode theme colors
- ALWAYS load shared components — never rebuild CxU pills, output viewers, or resource browsers
- ALWAYS include Agent Output tab and Library side tray (NOT a Resources tab)
- ALWAYS support CxU citation pills on insight-like content
- ALWAYS configure `project.json` outputMappings
- ALWAYS create sample data for development
- ALWAYS include `pyrana_objects/` directory for platform artifacts
- NEVER use mock data or hardcoded arrays for CxUs, Prompts, Scripts, or Agents in a demo dashboard — always fetch from the pyrana-playground-services APIs via the real `LibraryApiClient`
- NEVER stub, override, or replace `window.LibraryApiClient` — use the real implementation from `/components/pyrana-library/api-client.js`
- NEVER copy data patterns from `_example/index.html` — that file is a component showcase with intentional mock data, not a demo template
- Single-file HTML dashboards only — no build tools, no React, no npm
- Chart.js for charts, Marked for markdown — load from CDN
- The bridge server pattern is standard — don't reinvent it
- `project.json` is the single source of truth
- For retrofits (Mode 2), always create a `pyrana-demo` branch first
