"""Load the domain configuration (crash codes, methodology, target definitions)."""
from __future__ import annotations

import copy
import os
from typing import Any

import yaml

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "config", "ncdot_defaults.yaml")


class Config:
    """Thin wrapper over the YAML config with convenience accessors."""

    def __init__(self, data: dict[str, Any]):
        self.data = data

    # ---- loading -----------------------------------------------------------
    @classmethod
    def load(cls, path: str | None = None, overrides: dict | None = None) -> "Config":
        with open(_DEFAULT_PATH) as fh:
            data = yaml.safe_load(fh)
        if path:
            with open(path) as fh:
                user = yaml.safe_load(fh) or {}
            data = _deep_merge(data, user)
        if overrides:
            data = _deep_merge(data, overrides)
        return cls(data)

    # ---- column roles ------------------------------------------------------
    def role_letter(self, role: str) -> str:
        """e.g. role_letter('crash_type') -> 'T'."""
        return self.data["column_roles"][role]

    # ---- severity ----------------------------------------------------------
    @property
    def severity_order(self) -> list[str]:
        return self.data["severity"]["order"]

    @property
    def injury_letters(self) -> set[str]:
        return set(self.data["severity"]["injury_letters"])

    def epdo_weight(self, letter: str) -> float:
        return float(self.data["severity"]["epdo_weights"].get(letter, 1))

    # ---- code sets ---------------------------------------------------------
    def crash_type_group(self, name: str) -> set[int]:
        return set(self.data["crash_type_groups"].get(name, []))

    @property
    def wet_codes(self) -> set[int]:
        return set(self.data["road_surface"]["wet"])

    @property
    def night_codes(self) -> set[int]:
        return set(self.data["light"]["night"])

    @property
    def truck_codes(self) -> set[int]:
        return set(self.data["truck"]["codes"])

    # ---- targets -----------------------------------------------------------
    @property
    def target_definitions(self) -> dict[str, dict]:
        return self.data["target_crash_types"]

    # ---- methodology -------------------------------------------------------
    @property
    def methodology(self) -> dict:
        return self.data["methodology"]

    @property
    def mp_sentinel(self) -> float:
        return float(self.methodology["mp_sentinel"])


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out
