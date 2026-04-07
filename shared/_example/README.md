# _example/ — Component Showcase Only

**This directory is a standalone visual test page for shared Pyrana components.**
**It is NOT a template for building demos.**

## DO NOT copy patterns from this directory into demo projects

The `index.html` in this folder uses **hardcoded mock data** and **stubs out the
`LibraryApiClient`** with a fake implementation. This is intentional — the example
page needs to render without running pyrana-playground-services.

### What this example does (and why)

- Defines `MOCK_CXUS`, `MOCK_SCRIPTS`, `MOCK_PROMPTS`, etc. inline
- Replaces `window.LibraryApiClient` with a fake that returns local data
- Hardcodes `MOCK_ITEMS` with fabricated CxU details, schemas, and procedures

This lets us verify that all components (CxuPill, PyranaLibrary, OutputViewer, etc.)
render correctly in isolation.

### What demo projects must do instead

Real demos built with `/demo-builder` must:

1. **Use the real `LibraryApiClient`** from `/components/pyrana-library/api-client.js`
   — never stub or replace it
2. **Connect to pyrana-playground-services APIs** (CxU Manager `:8101`,
   Prompt Manager `:8102`, Script Manager `:8103`, Skill Manager `:8104`,
   Agent Manager `:8105`)
3. **Load CxU data from the API** — not from hardcoded arrays
4. **Get orchestration output from the bridge server** (`/api/output`) or from
   live agent execution via `AgentExecutor`
5. **Use `data/sample-output.json`** only as a fallback when services are offline
   (Static mode), not as the primary data source

### Quick reference: data flow in a real demo

```
pyrana-playground-services (ports 8101-8105)
    ↓ real API calls
LibraryApiClient (from shared/components/pyrana-library/api-client.js)
    ↓ fetched data
PyranaLibrary side tray + CxuPill citations + OutputViewer
```

Never short-circuit this flow with mock data in a demo project.
