"""Global configuration loading and defaults."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 12):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]


DEFAULT_CONFIG_NAME = "clias.toml"


@dataclass
class LLMConfig:
    model: str = "gpt-4o"
    vision_model: str = "gpt-4o"
    temperature: float = 0.2
    max_tokens: int = 4096


@dataclass
class ObserverConfig:
    screenshot_interval: float = 2.0
    change_threshold: float = 0.05
    shell_record_command: str = "script"


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    observer: ObserverConfig = field(default_factory=ObserverConfig)
    output_dir: str = "./clias_output"

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        if path is None:
            path = Path.cwd() / DEFAULT_CONFIG_NAME
        if not path.exists():
            return cls()
        with open(path, "rb") as f:
            data = tomllib.load(f)
        cfg = cls()
        if "llm" in data:
            cfg.llm = LLMConfig(**data["llm"])
        if "observer" in data:
            cfg.observer = ObserverConfig(**data["observer"])
        if "output_dir" in data:
            cfg.output_dir = data["output_dir"]
        return cfg
