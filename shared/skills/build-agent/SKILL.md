---
name: build-agent
description: Build a Pyrana platform agent through a guided 6-step conversational workflow. Creates agents that analyze data, apply context/guardrails, and produce structured outputs with mandatory CxU citations. Use when the user wants to create a new agent, configure data sources, or set up agent guardrails.
allowed-tools: Bash, Read, Write, Edit, WebFetch
argument-hint: [agent-name]
---

# Pyrana Agent Builder

You are helping the user build Pyrana platform agents through a guided workflow.

## Starting the Conversation — Single vs. Multi-Agent

**Before anything else, determine the scope:**

If $ARGUMENTS is provided, check if it looks like a project name (multi-agent) or a single agent name. Then ask:

> "Are we building a **single agent** or a **multi-agent project** (with orchestration phases)?"
>
> 1. **Single Agent** — I'll guide you through the 6-step agent build workflow.
> 2. **Multi-Agent Project** — I'll set up a project with execution phases, then build each agent in sequence.

### If Single Agent
Proceed directly to the 6-step workflow below with the provided name.

### If Multi-Agent Project
Before building agents, you must first:

1. **Define the project** — Collect:
   - Project name (human-readable)
   - Project ID / tag (slug, e.g., `phc-portfolio`)
   - Project description
   - List of agents with their execution phase assignments
   - Phase configuration (which phases run in parallel vs. sequential)
   - Test data file mappings (if known)
   - Output format preference (JSON or Markdown)

2. **Register the project in pyrana_playground.html** — Add the project to:
   - The `PROJECTS` constant (JavaScript object with name, tag, testDataPath, testDataFiles, executionPhases, output)
   - The `<select id="projectSelector">` dropdown

   **Project structure in PROJECTS constant:**
   ```javascript
   'project-id': {
     name: 'Human-Readable Project Name',
     tag: 'project-tag',  // Used to filter agents by tag
     testDataPath: '/test-data/project-id/',
     testDataFiles: [
       { name: 'Display Name', file: 'filename.json', agent: 'agent-id' }
     ],
     executionPhases: [
       { phase: 1, name: 'Phase Name', parallel: true, agents: ['agent-1', 'agent-2'] },
       { phase: 2, name: 'Phase Name', parallel: false, agents: ['agent-3'] }
     ],
     output: { format: 'markdown', filename: 'project-output' }
   }
   ```

3. **Tag all agents** with the project tag so the playground can filter them.

4. **Build each agent** using the 6-step workflow below, in the recommended build order (typically: data analyzers first, then correlators, then synthesizers).

## Service Endpoints

| Service | Port | Health Check |
|---------|------|--------------|
| CxU Manager | 8101 | `curl http://localhost:8101/health` |
| Prompt Manager | 8102 | `curl http://localhost:8102/health` |
| Script Manager | 8103 | `curl http://localhost:8103/health` |
| Skill Manager | 8104 | `curl http://localhost:8104/health` |
| Agent Manager | 8105 | `curl http://localhost:8105/health` |

## CRITICAL: Citation Requirements

**Every agent output MUST include CxU citations.** The format depends on the output type:

### For JSON Output (structured agents)
Every object in the output MUST include a `citations` array of objects with both `alias` and `cxu_id`. This format is required for the CxU pill component (`cxu-pill.js`) to render interactive reference pills:

```json
{
  "id": "ei-001",
  "title": "Labor costs exceed benchmark",
  "description": "Select-service properties averaging 38% labor-to-revenue...",
  "citations": [
    {"alias": "ind-024", "cxu_id": "1220abc123...full_hash"},
    {"alias": "h012-003", "cxu_id": "1220def456...full_hash"}
  ]
}
```

**When building JSON output schemas, ALWAYS include this field:**
```json
"citations": [{"alias": "string - CxU alias", "cxu_id": "string - full CxU ID hash"}]
```

The `alias` + `cxu_id` pair maps to the `(alias:cxu_id)` format that `cxu-pill.js` processes into clickable pills.

### For Markdown Output (report-style agents)
Use inline citations in the format `(cxu_alias:cxu_id)` immediately after each derived statement:

```
Sigma Health exceeded the overtime threshold at 15.7% (exec-009:1220208e62e23991e32a0e64a7fa269ac67eb07ff915021dea22da9f17798e26706d)
```

### Citation Rules
- EVERY conclusion, finding, or factual claim derived from context MUST have a citation
- If a statement draws from multiple CxUs, cite ALL relevant sources
- Only statements that are pure reasoning (not derived from CxUs) may omit citations
- For JSON: use CxU **aliases** (short names like `ind-024`) in the citations array
- For Markdown: use the full format `(alias:cxu_id)` with the 68-character hash
- **Downstream agents depend on citations for traceability** — an uncited insight cannot be validated

## Quality Validation

Before completing agent setup, validate against canonical Pyrana schemas:

### CxU Quality Checklist
| Field | Requirement | Validation |
|-------|-------------|------------|
| `alias` | 1-100 characters | Required, used for citations |
| `claim` | 10-5000 characters | Required, substantive assertion |
| `knowledge_type` | axiom \| derived \| prescribed | Required enum |
| `claim_type` | definition \| hypothesis \| requirement \| constraint \| relationship \| observation \| specification | Required enum |
| `cxu_id` | Pattern: `1220[a-f0-9]{64}` | Content-addressed hash |
| `supporting_contexts` | Array of {text, line?} | Must be array format |
| `version.number` | Format: "X.Y" | e.g., "1.0" |

### Prompt Quality Checklist
| Field | Requirement | Validation |
|-------|-------------|------------|
| `name` | 1-200 characters | Required |
| `objective.intent` | Non-empty string | Required, primary purpose |
| `objective.success_criteria` | String | Recommended |
| `output_contract.output_type` | report \| recommendation \| alert \| data_extract \| summary \| other | Enum |
| `output_contract.format` | json \| text \| markdown \| table | Enum |
| `cxu_context[].cxu_id` | Full hash ID | For audit trail |
| `cxu_context[].alias` | Short name | For citations |
| `cxu_context[].claim` | Full claim text | Sent to LLM |
| `citation_requirements` | Standard text | MUST require citations (JSON: `citations` array, Markdown: `[alias:cxu_id]`) |

### Quality Score Calculation
If quality_metrics are present:
```
overall_score = (confidence × 0.3) + (specificity × 0.25) + (completeness × 0.25) + (standalone × 0.2)
```

## The 6-Step Workflow (Per Agent)

### Step 1: Define Objective
Collect:
- Agent name (human-readable)
- Agent ID (slug, auto-generate from name if not provided)
- Objective (what the agent does)
- Primary use case
- Success criteria

API calls:
```bash
# Create agent (include project tag for multi-agent projects)
curl -X POST http://localhost:8105/api/agents \
  -H "Content-Type: application/json" \
  -d '{"name": "...", "description": "...", "tags": ["project-tag", "phase-N"]}'
```

**IMPORTANT:** Do NOT create the prompt yet. The Prompt Manager requires `cxu_context` at creation time (it is immutable after). Create the prompt in Step 4b after CxU curation is complete, then link it to the agent via PUT.

### Step 2: Describe Output
Collect:
- Output type (Report, Summary, Data Extract, Recommendation, Alert)
- Output format (Markdown, JSON, HTML, Plain Text, CSV)
- Output details (structure, sections, requirements)

### Step 3: Connect Data
1. Connect to Data API endpoint
2. List available data views
3. Generate Schema and Profile CxUs for views
4. Run relevance analysis
5. Tag relevant CxUs with agent ID

**Important:** Capture full CxU IDs for citation in agent output.

### Step 4: Provide Context & Curate CxUs

**4a. Add Context Sources**
Add background knowledge via:
- Document upload (extract to CxUs)
- Text paste (create CxU from text)
- Manual CxU creation

For **guardrails**: Use keyword `mandatory-guardrail` and `knowledge_type: prescribed`, `claim_type: requirement`.

**4b. Curate CxU Selection (CRITICAL — do NOT skip)**

After CxUs are available, you MUST curate which ones go into this agent's prompt. **Never bulk-assign all CxUs from a source document.** Most SOPs contain CxUs relevant to multiple agents — only a subset applies to any single agent.

**Curation process:**
1. **Review the agent's objective** — what specific decisions, thresholds, or rules does this agent evaluate?
2. **Fetch candidate CxUs** from the relevant source documents
3. **Score each CxU for relevance** by asking:
   - Does this CxU define a threshold, rule, or constraint that this agent needs to check?
   - Does this CxU provide context the agent needs to interpret its data?
   - Would the agent's output cite this CxU in a finding?
   - If the answer to ALL of these is "no", **exclude it**.
4. **Exclude CxUs that are:**
   - Governance/role definitions (e.g., "The CPO is responsible for...") unless the agent reports on governance
   - Thresholds for metrics this agent doesn't analyze
   - Cross-references to other policies unless this agent enforces that linkage
   - Duplicates (document extraction sometimes creates near-identical CxUs)
5. **Present the curated list to the user** with a brief rationale for each inclusion
6. **Target: 5-20 CxUs per agent** — enough for comprehensive coverage, few enough that each one matters

**Example curation for a cost-proc analyzer:**
- INCLUDE: CRR thresholds, cost escalation alert triggers, off-portal spend limits, margin squeeze conditions
- EXCLUDE: General governance roles, vendor ISO requirements, board reporting procedures, financial margin thresholds handled by a different agent

**Deduplication:** If multiple CxUs have the same alias or nearly identical claims, keep only the most complete version.

### Step 5: Configure Scripts
Generate or select data processing scripts. Scripts prepare data; the LLM interprets it.

**IMPORTANT:** When creating scripts via API, tag them with the agent ID so the Fitness Center and other tools can discover them:

```bash
# Create script with agent ID tag
curl -X POST http://localhost:8103/api/scripts \
  -H "Content-Type: application/json" \
  -d '{
    "name": "agent-id-slug",
    "display_name": "Human-Readable Script Name",
    "description": "What this script does",
    "category": "utility",
    "language": "python",
    "tags": ["agent-id-slug", "project-tag"],
    "script_object": {
      "code": "...python code..."
    }
  }'

# After creation, approve the script to make it Active
curl -X POST http://localhost:8103/api/scripts/{script_id}/approve
```

**Script naming convention:** Use the agent ID as the script `name` (e.g., `lmh-labor-ops`). This enables discovery by name matching even if tags are missing.

**Script tagging:** Include both the agent ID slug AND the project tag in `tags[]`. This enables:
- Fitness Center to find scripts associated with an agent
- Resource Manager to filter scripts by project

### Step 6: Preview & Test
1. Execute scripts to generate data payloads
2. Assemble prompt with CxU context (including full IDs)
3. Test agent with LLM
4. Validate output includes proper citations
5. Approve agent and prompt

### Step 7: Export to Pyrana (Optional)
After testing, use the "Export to Pyrana" button to generate a `ActionAgentConfig` that can run in Pyrana's execution environment.

The export generates:
- `agent_key`: Unique identifier (from agent_id)
- `metadata`: Name, description, category, tags
- `objective`: Agent's task description
- `input_hydration`: Data view mappings
- `toolset`: List of scripts/tools
- `required_artifacts`: Output specifications
- `react`: Execution configuration

**Export Options:**
1. **Copy JSON**: Copy the ActionAgentConfig to clipboard
2. **Download YAML**: Save as `{agent_key}.yaml` for Pyrana's agents directory

**To run in Pyrana:**
```bash
# Option A: Save to Pyrana agents directory
cp exported-agent.yaml /path/to/pyrana/agents/{agent_key}.yaml

# Option B: Register via API
curl -X POST http://pyrana-host/api/agents \
  -H "Content-Type: application/json" \
  -d @exported-agent.json
```

## Agent Output Format

Agent output format depends on the `output_contract.format` specified in the prompt.

### JSON Output (for multi-agent / dashboard projects)
When the agent's output feeds downstream agents or a dashboard, use structured JSON with a `citations` array on every object:

```json
[
  {
    "id": "ei-001",
    "type": "negative",
    "category": "labor",
    "title": "Labor costs exceed benchmark at 3 properties",
    "description": "Properties H012, H027, and H033 show labor-to-revenue ratios above 40%...",
    "signal": "Labor cost ratio 42.1% vs benchmark 30-35%",
    "hypothesis": "Overstaffing during low-occupancy months...",
    "dataPoints": [{"label": "H012 Labor %", "value": "42.1%", "trend": "up"}],
    "priority": "high",
    "citations": ["ind-024", "ind-039", "h012-003"]
  }
]
```

**Every object MUST have a `citations` array.** This enables downstream agents and dashboards to trace findings back to source CxUs.

### Markdown Output (for report-style agents)
When the output is a human-readable report:

```markdown
# [Report Title]

## Executive Summary
[Summary with inline citations after each key finding]
(cxu_alias:full_cxu_id)

## Findings
[Each conclusion MUST have an inline citation]
Statement about finding X (data-schema:1220abc...).
This relates to policy Y (policy-cxu:1220def...).

## Recommendations
[Recommendations with citations to supporting context]
```

## Validation Commands

Run these to validate agent quality:

```bash
# Validate CxU schema compliance
curl -s "http://localhost:8101/cxus/{cxu_id}" | python3 -c "
import json, sys
cxu = json.load(sys.stdin)
obj = cxu.get('cxu_object', {})
errors = []
# Check required fields
if not obj.get('alias') or len(obj.get('alias','')) > 100:
    errors.append('alias: must be 1-100 chars')
claim = obj.get('claim', '')
if len(claim) < 10 or len(claim) > 5000:
    errors.append(f'claim: must be 10-5000 chars (got {len(claim)})')
imm = obj.get('immutable_metadata', {})
if imm.get('knowledge_type') not in ['axiom', 'derived', 'prescribed']:
    errors.append('knowledge_type: invalid enum')
valid_claims = ['definition','hypothesis','requirement','constraint','relationship','observation','specification','procedure','step','reference','summary','finding','statement']
if imm.get('claim_type') not in valid_claims:
    errors.append('claim_type: invalid enum')
if errors:
    print('ERRORS:', errors)
else:
    print('CxU VALID')
"

# Validate Prompt schema compliance
curl -s "http://localhost:8102/api/prompts/{prompt_id}" | python3 -c "
import json, sys
prompt = json.load(sys.stdin)
obj = prompt.get('prompt_object', {})
errors = []
name = obj.get('name', '')
if not name or len(name) > 200:
    errors.append('name: must be 1-200 chars')
intent = obj.get('objective', {}).get('intent', '')
if not intent:
    errors.append('objective.intent: required')
valid_types = ['report','recommendation','alert','data_extract','summary','other']
if obj.get('output_contract',{}).get('output_type') not in valid_types:
    errors.append('output_type: invalid enum')
if errors:
    print('ERRORS:', errors)
else:
    print('PROMPT VALID')
"
```

## Playground Project Reference

The pyrana_playground.html file at `/Users/jamescbury/Code/github/agent-builder-dev/pyrana_playground.html` contains:

- **PROJECTS constant** (~line 2110): Static project definitions
- **Project selector dropdown** (~line 1903): `<select id="projectSelector">`
- **Agent filtering**: Projects filter agents by matching the project `tag` against agent `tags[]`
- **Orchestration**: Runs agents phase-by-phase; parallel phases use `Promise.all()`

When creating a multi-agent project, you MUST update both the PROJECTS constant and the selector dropdown in this file.

## Starting the Conversation

If $ARGUMENTS contains an agent name, use it. Otherwise ask:

> "What kind of agent would you like to build? Tell me:
> 1. What should it analyze or do?
> 2. What outputs should it produce?
> 3. Any specific requirements or constraints?"

Then guide through each step, confirming before making API calls.

**REMEMBER:** All agent outputs MUST include CxU citations. For JSON outputs, every object needs a `citations` array of CxU aliases. For Markdown outputs, use inline `(alias:cxu_id)` after every derived statement. Citations enable traceability across multi-agent pipelines.
