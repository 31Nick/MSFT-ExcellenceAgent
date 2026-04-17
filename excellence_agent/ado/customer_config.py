"""Per-customer YAML configuration for ADO MCP sync.

Each customer config is a YAML file in the ``customers/`` directory.
The filename stem (e.g. ``contoso`` from ``contoso.yaml``) is the
canonical **slug** used for state-store scoping, env-var lookup, and
CLI references.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

_CUSTOMERS_DIR = Path(__file__).parent.parent.parent / "customers"


@dataclass
class WorkItemTypeMapping:
    """Maps hierarchy levels to ADO work-item type names."""

    epic: str = "Epic"
    feature: str = "Feature"
    story: str = "User Story"
    task: str = "Task"


@dataclass
class CustomerConfig:
    """Fully-resolved configuration for a single customer."""

    slug: str
    customer_name: str
    organization: str
    project: str
    pat: str
    team: str = ""
    area_path: str = ""
    iteration_path: str = ""
    type_mapping: WorkItemTypeMapping = field(default_factory=WorkItemTypeMapping)

    @property
    def organization_url(self) -> str:
        return f"https://dev.azure.com/{self.organization}"


class CustomerConfigError(Exception):
    """Raised when a customer config is invalid or missing."""


def _resolve_pat(slug: str) -> str:
    """Look up PAT: customer-specific env var first, then global fallback."""
    specific = os.getenv(f"ADO_PAT_{slug.upper()}")
    if specific:
        return specific
    generic = os.getenv("ADO_PAT")
    if generic:
        return generic
    raise CustomerConfigError(
        f"No PAT found for customer '{slug}'. "
        f"Set ADO_PAT_{slug.upper()} or ADO_PAT environment variable."
    )


def load_customer_config(
    slug: str,
    *,
    customers_dir: Optional[Path] = None,
) -> CustomerConfig:
    """Load and validate a customer config from ``customers/{slug}.yaml``."""
    base = customers_dir or _CUSTOMERS_DIR
    path = base / f"{slug}.yaml"
    if not path.is_file():
        raise CustomerConfigError(f"Customer config not found: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        raw: dict = yaml.safe_load(fh) or {}

    customer_name = raw.get("customer_name", slug)
    ado = raw.get("ado", {})
    organization = ado.get("organization", "")
    project = ado.get("project", "")

    if not organization:
        raise CustomerConfigError(f"[{slug}] Missing required field: ado.organization")
    if not project:
        raise CustomerConfigError(f"[{slug}] Missing required field: ado.project")

    wi = raw.get("work_items", {}).get("type_mapping", {})
    type_mapping = WorkItemTypeMapping(
        epic=wi.get("epic", "Epic"),
        feature=wi.get("feature", "Feature"),
        story=wi.get("story", "User Story"),
        task=wi.get("task", "Task"),
    )

    pat = _resolve_pat(slug)

    return CustomerConfig(
        slug=slug,
        customer_name=customer_name,
        organization=organization,
        project=project,
        pat=pat,
        team=ado.get("team", ""),
        area_path=ado.get("area_path", ""),
        iteration_path=ado.get("iteration_path", ""),
        type_mapping=type_mapping,
    )


def list_customer_configs(
    *,
    customers_dir: Optional[Path] = None,
) -> List[Dict[str, str]]:
    """List available customer config slugs.

    Returns a list of dicts with ``slug`` and ``customer_name`` keys.
    The ``example`` template is excluded.
    """
    base = customers_dir or _CUSTOMERS_DIR
    if not base.is_dir():
        return []
    results = []
    for p in sorted(base.glob("*.yaml")):
        slug = p.stem
        if slug == "example":
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            results.append({
                "slug": slug,
                "customer_name": raw.get("customer_name", slug),
            })
        except Exception:
            continue
    return results
