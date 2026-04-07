"""
CxU Store — Read/write Context Units from pyrana_objects/cxus/

The agent's knowledge base. Loads CxU JSON files from disk,
categorizes by tier, and supports create/update for the reflection loop.
"""

import json
import hashlib
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


CXUS_DIR = Path(__file__).parent / "pyrana_objects" / "cxus"


class CxU:
    """Lightweight wrapper around a CxU dict."""

    def __init__(self, data: dict):
        self._data = data

    @property
    def cxu_id(self) -> str:
        return self._data.get("cxu_id", "")

    @property
    def alias(self) -> str:
        return self._data.get("alias", "")

    @property
    def claim(self) -> str:
        return self._data.get("cxu_object", {}).get("claim", "")

    @property
    def tier(self) -> str:
        tags = self._data.get("mutable_metadata", {}).get("tags", [])
        for t in tags:
            if t.startswith("tier:"):
                return t.replace("tier:", "")
        return "unknown"

    @property
    def approval(self) -> str:
        tags = self._data.get("mutable_metadata", {}).get("tags", [])
        for t in tags:
            if t.startswith("approval:"):
                return t.replace("approval:", "")
        return "unknown"

    @property
    def is_human_locked(self) -> bool:
        return self.approval == "human"

    @property
    def parameters(self) -> Dict[str, Any]:
        return self._data.get("cxu_object", {}).get("parameters", {})

    @property
    def metadata(self) -> Dict[str, Any]:
        return self._data.get("cxu_object", {}).get("metadata", {})

    @property
    def version(self) -> Dict[str, Any]:
        return self._data.get("version", {})

    @property
    def status(self) -> str:
        return self._data.get("mutable_metadata", {}).get("status", "Active")

    @property
    def supporting_contexts(self) -> List[Dict[str, Any]]:
        return self._data.get("cxu_object", {}).get("supporting_contexts", [])

    def to_dict(self) -> dict:
        return self._data

    def to_citation(self) -> dict:
        return {"cxu_id": self.cxu_id, "alias": self.alias}

    def param_value(self, key: str, default=None):
        """Get a parameter value by key."""
        p = self.parameters.get(key)
        return p.get("value", default) if p else default

    def to_prompt_context(self) -> str:
        """Format CxU for inclusion in an LLM prompt."""
        lines = [f"[CxU: {self.alias}]"]
        lines.append(f"Claim: {self.claim}")
        if self.parameters:
            params = ", ".join(
                f"{k}={v.get('value')}" for k, v in self.parameters.items()
            )
            lines.append(f"Parameters: {params}")
        return "\n".join(lines)


class CxUStore:
    """File-based CxU storage backed by pyrana_objects/cxus/."""

    def __init__(self, cxus_dir: Optional[Path] = None):
        self.cxus_dir = cxus_dir or CXUS_DIR
        self.cxus_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, CxU] = {}
        self.reload()

    def reload(self):
        """Reload all CxUs from disk."""
        self._cache.clear()
        for f in self.cxus_dir.glob("*.json"):
            try:
                with open(f) as fp:
                    data = json.load(fp)
                cxu = CxU(data)
                if cxu.status == "Active":
                    self._cache[cxu.alias] = cxu
            except Exception as e:
                print(f"  Warning: could not load CxU {f.name}: {e}")
        print(f"  CxU Store: loaded {len(self._cache)} active CxUs")

    def all(self) -> List[CxU]:
        return list(self._cache.values())

    def by_tier(self, tier: str) -> List[CxU]:
        return [c for c in self._cache.values() if c.tier == tier]

    def by_alias(self, alias: str) -> Optional[CxU]:
        return self._cache.get(alias)

    def by_id(self, cxu_id: str) -> Optional[CxU]:
        for c in self._cache.values():
            if c.cxu_id == cxu_id:
                return c
        return None

    @property
    def axioms(self) -> List[CxU]:
        return self.by_tier("axiom")

    @property
    def regime_models(self) -> List[CxU]:
        return self.by_tier("regime-model")

    @property
    def playbooks(self) -> List[CxU]:
        return self.by_tier("playbook")

    @property
    def learnings(self) -> List[CxU]:
        return self.by_tier("learning")

    def get_playbook_for_regime(self, regime: str) -> Optional[CxU]:
        """Get the playbook CxU matching a regime name."""
        alias = f"playbook-{regime.lower().replace('_', '-').split('_')[0]}"
        # Handle "trending_up" / "trending_down" -> "playbook-trending"
        for suffix in [regime.lower(), regime.split("_")[0].lower()]:
            cxu = self.by_alias(f"playbook-{suffix}")
            if cxu:
                return cxu
        return None

    def create_cxu(
        self,
        alias: str,
        claim: str,
        supporting_contexts: List[Dict[str, Any]],
        knowledge_type: str = "derived",
        claim_type: str = "finding",
        tier: str = "learning",
        approval: str = "agent",
        parameters: Optional[Dict[str, Any]] = None,
        keywords: Optional[List[str]] = None,
        created_by: str = "reflector-agent",
    ) -> CxU:
        """Create a new CxU and write to disk."""
        cxu_object = {
            "claim": claim,
            "supporting_contexts": supporting_contexts,
            "metadata": {
                "knowledge_type": knowledge_type,
                "claim_type": claim_type,
                "keywords": keywords or [],
                "tags": [
                    "hl-trading",
                    f"tier:{tier}",
                    f"cxu_class:{'hypothesis' if approval == 'human' else 'parameter'}",
                    f"approval:{approval}",
                    "agdel-trader-bot",
                ],
            },
        }
        if parameters:
            cxu_object["parameters"] = parameters

        # Generate content-addressed ID
        canonical = json.dumps(cxu_object, sort_keys=True)
        hash_hex = hashlib.sha256(canonical.encode()).hexdigest()
        cxu_id = f"1220{hash_hex}"

        data = {
            "alias": alias,
            "cxu_id": cxu_id,
            "cxu_object": cxu_object,
            "version": {
                "number": "1.0",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": created_by,
                "modified_at": None,
                "modified_by": None,
                "change_description": f"Created by {created_by}",
                "prior_cxu_id": None,
                "source": None,
            },
            "mutable_metadata": {
                "status": "Active",
                "tags": cxu_object["metadata"]["tags"],
            },
        }

        cxu = CxU(data)
        self._save(cxu)
        self._cache[alias] = cxu
        return cxu

    def update_cxu(
        self,
        alias: str,
        param_updates: Optional[Dict[str, Any]] = None,
        change_description: str = "",
        modified_by: str = "reflector-agent",
    ) -> Optional[CxU]:
        """Update a CxU's parameters (only for agent-adjustable CxUs)."""
        existing = self.by_alias(alias)
        if not existing:
            print(f"  CxU Store: cannot update '{alias}' — not found")
            return None
        if existing.is_human_locked:
            print(f"  CxU Store: cannot update '{alias}' — human-locked")
            return None

        data = copy.deepcopy(existing.to_dict())

        # Update parameters
        if param_updates:
            params = data.get("cxu_object", {}).get("parameters", {})
            for key, new_value in param_updates.items():
                if key in params:
                    p = params[key]
                    # Enforce bounds
                    if isinstance(new_value, (int, float)):
                        if p.get("min") is not None:
                            new_value = max(new_value, p["min"])
                        if p.get("max") is not None:
                            new_value = min(new_value, p["max"])
                    p["value"] = new_value
            data["cxu_object"]["parameters"] = params

        # Bump version
        old_version = data.get("version", {})
        old_num = float(old_version.get("number", "1.0"))
        data["version"] = {
            **old_version,
            "number": str(round(old_num + 0.1, 1)),
            "modified_at": datetime.now(timezone.utc).isoformat(),
            "modified_by": modified_by,
            "change_description": change_description,
            "prior_cxu_id": data.get("cxu_id"),
        }

        # Recompute content-addressed ID
        canonical = json.dumps(data["cxu_object"], sort_keys=True)
        hash_hex = hashlib.sha256(canonical.encode()).hexdigest()
        data["cxu_id"] = f"1220{hash_hex}"

        cxu = CxU(data)
        self._save(cxu)
        self._cache[alias] = cxu
        return cxu

    def _save(self, cxu: CxU):
        """Write CxU to disk."""
        filename = f"{cxu.alias}.json"
        filepath = self.cxus_dir / filename
        with open(filepath, "w") as f:
            json.dump(cxu.to_dict(), f, indent=2)
