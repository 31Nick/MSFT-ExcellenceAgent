"""Application registry — manages known applications in applications.yaml.

Provides CRUD operations for the application list, plus auto-detection
from batch assessment directory structures.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_DIR = Path(__file__).parent.parent  # repo root


@dataclass
class AppEntry:
    """A registered application."""

    name: str
    description: str = ""
    environments: List[str] = field(default_factory=list)
    subscriptions: List[str] = field(default_factory=list)


@dataclass
class AppRegistry:
    """In-memory representation of applications.yaml."""

    apps: Dict[str, AppEntry] = field(default_factory=dict)
    config_path: Optional[Path] = None

    def list_apps(self) -> List[AppEntry]:
        """Return all registered apps sorted by name."""
        return sorted(self.apps.values(), key=lambda a: a.name.lower())

    def get_app(self, name: str) -> Optional[AppEntry]:
        """Get an app by name (case-insensitive)."""
        return self.apps.get(name.lower())

    def add_app(
        self,
        name: str,
        *,
        description: str = "",
        environments: Optional[List[str]] = None,
        subscriptions: Optional[List[str]] = None,
    ) -> AppEntry:
        """Add or update an application. Returns the entry."""
        key = name.lower()
        if key in self.apps:
            entry = self.apps[key]
            if description:
                entry.description = description
            if environments:
                entry.environments = list(set(entry.environments + environments))
            if subscriptions:
                entry.subscriptions = list(set(entry.subscriptions + subscriptions))
        else:
            entry = AppEntry(
                name=name,
                description=description,
                environments=environments or [],
                subscriptions=subscriptions or [],
            )
            self.apps[key] = entry
            logger.info("Registered new application: %s", name)
        return entry

    def remove_app(self, name: str) -> bool:
        """Remove an app by name. Returns True if removed."""
        key = name.lower()
        if key in self.apps:
            del self.apps[key]
            logger.info("Removed application: %s", name)
            return True
        return False

    def has_app(self, name: str) -> bool:
        """Check if an app is registered."""
        return name.lower() in self.apps

    def save(self, path: Optional[Path] = None) -> None:
        """Save the registry to YAML."""
        save_path = path or self.config_path
        if save_path is None:
            raise ValueError("No config path specified for saving")

        data = {
            "applications": [
                _entry_to_dict(entry)
                for entry in sorted(self.apps.values(), key=lambda a: a.name.lower())
            ]
        }

        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        logger.info("Saved application registry to %s", save_path)


def _entry_to_dict(entry: AppEntry) -> dict:
    """Convert an AppEntry to a YAML-serializable dict."""
    d: dict = {"name": entry.name}
    if entry.description:
        d["description"] = entry.description
    if entry.environments:
        d["environments"] = sorted(entry.environments)
    if entry.subscriptions:
        d["subscriptions"] = sorted(entry.subscriptions)
    return d


def load_app_registry(config_path: Optional[str | Path] = None) -> AppRegistry:
    """Load the application registry from YAML.

    If the file doesn't exist, returns an empty registry that will create
    the file on first save.
    """
    if config_path is None:
        config_path = _DEFAULT_CONFIG_DIR / "applications.yaml"
    else:
        config_path = Path(config_path)

    registry = AppRegistry(config_path=config_path)

    if not config_path.is_file():
        logger.info("No applications.yaml found at %s — starting with empty registry", config_path)
        return registry

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    apps_list = data.get("applications", [])
    for app_data in apps_list:
        if isinstance(app_data, str):
            registry.add_app(app_data)
        elif isinstance(app_data, dict):
            registry.add_app(
                name=app_data.get("name", ""),
                description=app_data.get("description", ""),
                environments=app_data.get("environments", []),
                subscriptions=app_data.get("subscriptions", []),
            )

    logger.info("Loaded %d application(s) from %s", len(registry.apps), config_path)
    return registry


def auto_detect_apps_from_directory(
    input_dir: str | Path,
    registry: AppRegistry,
    *,
    save: bool = True,
) -> List[str]:
    """Detect application names from batch assessment directory structure.

    Scans immediate subdirectories of input_dir as app names. Auto-registers
    any that aren't already in the registry.

    Returns list of newly added app names.
    """
    input_path = Path(input_dir)
    if not input_path.is_dir():
        return []

    new_apps: List[str] = []
    for child in sorted(input_path.iterdir()):
        if not child.is_dir():
            continue
        # Skip hidden/system directories
        if child.name.startswith(".") or child.name.startswith("_"):
            continue

        app_name = child.name
        if not registry.has_app(app_name):
            # Detect environments from subfolders
            envs = []
            for env_folder in child.iterdir():
                if env_folder.is_dir():
                    envs.append(env_folder.name)

            registry.add_app(app_name, environments=envs)
            new_apps.append(app_name)

    if new_apps and save:
        registry.save()
        logger.info("Auto-detected and registered %d new app(s): %s", len(new_apps), new_apps)

    return new_apps
