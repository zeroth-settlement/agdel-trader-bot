# pyrana-playground-shared

Shared assets for Pyrana Playground demo projects. Added as a git submodule at `shared/` in every demo repo.

## Contents

```
├── design-guide/        CSS theme, component styles, utility classes, logos
├── components/          Reusable JS components (CxU pill, output viewer, library, agent executor)
├── starters/            Boilerplate files copied into new demo repos
├── skills/              Reference copies of Claude Code skills
└── PYRANA_PLAYGROUND_ARCHITECTURE.md
```

## Usage

### In a new demo (via `/demo-builder`)

The `/demo-builder` skill handles setup automatically. It adds this repo as a submodule, copies starters, and generates project-specific files.

### Manual setup

```bash
# Add as submodule
git submodule add https://github.com/zeroth-tech/pyrana-playground-shared.git shared

# Copy starter files
cp shared/starters/bridge_server.py .
cp shared/starters/start.py .
cp shared/starters/requirements.txt .
cp shared/starters/.gitignore .
cp shared/starters/setup.sh .
chmod +x setup.sh
```

### Updating in an existing demo

```bash
cd shared
git fetch origin
git log HEAD..origin/main --oneline   # review changes
git pull origin main                   # import updates
cd ..
git add shared
git commit -m "Update shared assets"
```

## Design Guide

Three CSS files provide the Pyrana dark theme, component styles, and utility classes:

```html
<link rel="stylesheet" href="/design-guide/pyrana-theme.css">
<link rel="stylesheet" href="/design-guide/pyrana-components.css">
<link rel="stylesheet" href="/design-guide/pyrana-utilities.css">
```

Use CSS custom properties — never hardcode colors. See `PYRANA_PLAYGROUND_ARCHITECTURE.md` for full documentation.

## Components

| Component | Path | Purpose |
|-----------|------|---------|
| CxU Pill | `components/cxu-pill.js` | Clickable citation pills |
| Output Viewer | `components/output-viewer.js` | Markdown rendering with CxU integration |
| Output Panel | `components/output-viewer/` | Full output panel with metadata tray |
| Pyrana Library | `components/pyrana-library/` | Side tray for browsing platform objects |
| Agent Executor | `components/agent-executor/` | Shared LLM execution engine |
| Flatten | `components/utils/flatten.js` | API response normalization |

## Skills

Reference copies of the two Claude Code skills used in the Pyrana workflow:

- **`/demo-builder`** (`skills/demo-builder/SKILL.md`) — Scaffolds demo repos, designs dashboards, defines output contracts
- **`/build-agent`** (`skills/build-agent/SKILL.md`) — Creates agents with CxUs, scripts, prompts, and guardrails
