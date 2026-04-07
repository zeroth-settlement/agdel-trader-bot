"""
Pyrana Bridge Server

A FastAPI server that serves the project dashboard and provides an API
for receiving orchestration output from the Pyrana Playground.

Port: 9002
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Paths
BASE_DIR = Path(__file__).parent
SHARED_DIR = BASE_DIR / "shared"
DATA_DIR = BASE_DIR / "data"
EXPORTS_DIR = DATA_DIR / "exports"
PYRANA_OBJECTS_DIR = BASE_DIR / "pyrana_objects"

# Ensure exports directory exists
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Load project name from project.json
PROJECT_NAME = "Pyrana Demo"
try:
    with open(BASE_DIR / "project.json") as f:
        _config = json.load(f)
        PROJECT_NAME = _config.get("name", PROJECT_NAME)
        PROJECT_TAG = _config.get("tag", "unknown")
except Exception:
    PROJECT_TAG = "unknown"

app = FastAPI(title="Pyrana Bridge Server", version="1.0.0")

# CORS for playground (9000) and dashboard (9002)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:9000",
        "http://localhost:9002",
        "http://127.0.0.1:9000",
        "http://127.0.0.1:9002",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Static file mounts ---

# Serve shared components from submodule
if (SHARED_DIR / "components").exists():
    app.mount("/components", StaticFiles(directory=str(SHARED_DIR / "components")), name="components")

# Serve design guide from submodule
if (SHARED_DIR / "design-guide").exists():
    app.mount("/design-guide", StaticFiles(directory=str(SHARED_DIR / "design-guide")), name="design-guide")

# Serve Pyrana platform objects (CxUs, agents, prompts, scripts, skills)
if PYRANA_OBJECTS_DIR.exists():
    app.mount("/pyrana-objects", StaticFiles(directory=str(PYRANA_OBJECTS_DIR)), name="pyrana-objects")

# Serve data directory
if DATA_DIR.exists():
    app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")


# --- In-memory store ---

class OutputStore:
    """Stores the latest orchestration output in memory with file persistence."""

    def __init__(self):
        self.latest: Optional[Dict[str, Any]] = None
        self.received_at: Optional[str] = None
        self._load_most_recent()

    def _load_most_recent(self):
        """Load the most recent export file on startup."""
        try:
            exports = sorted(EXPORTS_DIR.glob("*.json"), key=os.path.getmtime, reverse=True)
            if exports:
                with open(exports[0]) as f:
                    self.latest = json.load(f)
                self.received_at = datetime.fromtimestamp(
                    os.path.getmtime(exports[0])
                ).isoformat()
                print(f"Loaded most recent export: {exports[0].name}")
        except Exception as e:
            print(f"Could not load recent export: {e}")

    def store(self, data: Dict[str, Any]) -> str:
        """Store output in memory and persist to file. Returns filename."""
        self.latest = data
        self.received_at = datetime.now().isoformat()

        # Persist to exports directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        project = data.get("project", PROJECT_TAG)
        filename = f"{project}_{timestamp}.json"
        filepath = EXPORTS_DIR / filename

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)

        print(f"Saved export: {filename}")
        return filename

    def get_latest(self) -> Optional[Dict[str, Any]]:
        """Return latest output data."""
        return self.latest

    def list_exports(self) -> List[Dict[str, str]]:
        """List all saved exports."""
        exports = []
        for f in sorted(EXPORTS_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
            exports.append({
                "filename": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
        return exports


store = OutputStore()


# --- Pydantic models ---

class AgentResult(BaseModel):
    agentId: str
    agentName: Optional[str] = None
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    cxuList: Optional[List[Dict[str, Any]]] = None
    promptId: Optional[str] = None

class PhaseResult(BaseModel):
    phase: int
    name: str
    parallel: Optional[bool] = None
    agents: List[AgentResult]
    executionTimeMs: Optional[float] = None

class OrchestrationOutput(BaseModel):
    project: str
    timestamp: str
    model: Optional[str] = None
    phases: List[PhaseResult]
    summary: Optional[Dict[str, Any]] = None
    totalExecutionTimeMs: Optional[float] = None

    class Config:
        extra = "allow"


# --- API endpoints ---

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the dashboard HTML file."""
    dashboard_path = BASE_DIR / "dashboard.html"
    if not dashboard_path.exists():
        raise HTTPException(status_code=404, detail="dashboard.html not found")
    return FileResponse(str(dashboard_path), media_type="text/html")


@app.get("/project.json")
async def serve_project_config():
    """Serve the project configuration."""
    config_path = BASE_DIR / "project.json"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="project.json not found")
    with open(config_path) as f:
        return json.load(f)


@app.post("/api/output")
async def receive_output(data: Dict[str, Any]):
    """
    Receive orchestration results from the playground.
    Stores in memory and persists to data/exports/.
    """
    filename = store.store(data)
    return {
        "status": "ok",
        "message": "Output received and stored",
        "filename": filename,
        "receivedAt": store.received_at,
    }


@app.get("/api/output")
async def get_latest_output():
    """Return the latest orchestration results for the dashboard."""
    latest = store.get_latest()
    if not latest:
        return {"status": "empty", "data": None, "receivedAt": None}
    return {
        "status": "ok",
        "data": latest,
        "receivedAt": store.received_at,
    }


@app.get("/api/output/history")
async def list_output_history():
    """List all saved export files."""
    return {
        "status": "ok",
        "exports": store.list_exports(),
    }


@app.get("/api/output/history/{filename}")
async def get_export_file(filename: str):
    """Load a specific export file."""
    filepath = EXPORTS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Export {filename} not found")
    with open(filepath) as f:
        data = json.load(f)
    return {"status": "ok", "data": data, "filename": filename}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "pyrana-bridge",
        "project": PROJECT_TAG,
        "hasOutput": store.latest is not None,
        "exportCount": len(list(EXPORTS_DIR.glob("*.json"))),
    }


if __name__ == "__main__":
    import uvicorn

    print("=" * 50)
    print(f"  Pyrana Bridge Server — {PROJECT_NAME}")
    print("=" * 50)
    print()
    print("Dashboard:  http://localhost:9002/")
    print("Health:     http://localhost:9002/health")
    print("API:")
    print("  POST /api/output        — Receive orchestration results")
    print("  GET  /api/output        — Get latest results")
    print("  GET  /api/output/history — List saved exports")
    print()
    print("Static mounts:")
    print(f"  /components/     -> {SHARED_DIR / 'components'}")
    print(f"  /design-guide/   -> {SHARED_DIR / 'design-guide'}")
    print(f"  /pyrana-objects/  -> {PYRANA_OBJECTS_DIR}")
    print(f"  /data/           -> {DATA_DIR}")
    print()

    uvicorn.run(app, host="0.0.0.0", port=9002)
