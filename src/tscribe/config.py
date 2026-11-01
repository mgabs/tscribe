"""Configuration loading, saving, and management."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from tscribe.constants import (
    DEFAULT_CHANNELS,
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_FORMATS,
    DEFAULT_SAMPLE_RATE,
    VALID_MODELS,
    VALID_OUTPUT_FORMATS,
)


@dataclass
class RecordingDefaults:
    sample_rate: int = DEFAULT_SAMPLE_RATE
    channels: int = DEFAULT_CHANNELS
    default_device: str = ""
    auto_transcribe: bool = True


@dataclass
class TranscriptionDefaults:
    model: str = DEFAULT_MODEL
    language: str = DEFAULT_LANGUAGE
    output_formats: list[str] = field(default_factory=lambda: list(DEFAULT_OUTPUT_FORMATS))
    gpu: bool = False
    diarize: bool = True
    diarize_engine: str = "nemotron"


@dataclass
class StorageDefaults:
    data_dir: str = ""


@dataclass
class AppDefaults:
    notifications: bool = True
    recent_limit: int = 5
    show_elapsed_time: bool = True


@dataclass
class CaptionDefaults:
    enabled: bool = True
    model: str = "base"
    audio_source: str = "both"
    output_mode: str = "headphones"
    echo_cancellation: bool = True
    font_size: int = 24
    always_on_top: bool = True


@dataclass
class TscribeConfig:
    recording: RecordingDefaults = field(default_factory=RecordingDefaults)
    transcription: TranscriptionDefaults = field(default_factory=TranscriptionDefaults)
    storage: StorageDefaults = field(default_factory=StorageDefaults)
    app: AppDefaults = field(default_factory=AppDefaults)
    captions: CaptionDefaults = field(default_factory=CaptionDefaults)

    @classmethod
    def load(cls, config_path: Path | None = None) -> TscribeConfig:
        """Load config from TOML file, falling back to defaults for missing keys."""
        config = cls()
        if config_path is None or not config_path.exists():
            return config

        with open(config_path, "rb") as f:
            data = tomllib.load(f)

        for section_field in fields(config):
            section = section_field.name
            values = data.get(section, {})
            if not isinstance(values, dict):
                raise ValueError(f"Config section {section!r} must be a table")
            obj = getattr(config, section)
            known = {f.name for f in fields(obj)}
            for key, value in values.items():
                if key in known:
                    config.set(f"{section}.{key}", value)

        return config

    def save(self, config_path: Path) -> None:
        """Write current config to TOML file."""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data = self._to_dict()
        with open(config_path, "wb") as f:
            tomli_w.dump(data, f)

    def get(self, key: str) -> Any:
        """Get a config value by dotted key (e.g., 'recording.sample_rate')."""
        section, _, name = key.partition(".")
        if not name:
            raise KeyError(f"Invalid key format: {key!r}. Use 'section.key' (e.g., 'recording.sample_rate')")
        obj = getattr(self, section, None)
        if section not in {f.name for f in fields(self)}:
            raise KeyError(f"Unknown config section: {section!r}")
        if name not in {f.name for f in fields(obj)}:
            raise KeyError(f"Unknown config key: {key!r}")
        return getattr(obj, name)

    def set(self, key: str, value: Any) -> None:
        """Set a config value by dotted key."""
        section, _, name = key.partition(".")
        if not name:
            raise KeyError(f"Invalid key format: {key!r}. Use 'section.key' (e.g., 'recording.sample_rate')")
        obj = getattr(self, section, None)
        if section not in {f.name for f in fields(self)}:
            raise KeyError(f"Unknown config section: {section!r}")
        if name not in {f.name for f in fields(obj)}:
            raise KeyError(f"Unknown config key: {key!r}")

        # Coerce value to match the field type
        current = getattr(obj, name)
        coerced = _coerce_value(value, current, key)
        if type(coerced) is not type(current):
            raise ValueError(f"{key} must be {type(current).__name__}")
        _validate_value(key, coerced)
        setattr(obj, name, coerced)

    def _to_dict(self) -> dict:
        """Convert config to a nested dict for TOML serialization."""
        result = {}
        for section_field in fields(self):
            section_obj = getattr(self, section_field.name)
            section_dict = {}
            for f in fields(section_obj):
                section_dict[f.name] = getattr(section_obj, f.name)
            result[section_field.name] = section_dict
        return result


def _coerce_value(value: Any, current: Any, key: str) -> Any:
    """Coerce a string value to match the type of the current value."""
    if isinstance(value, str) and not isinstance(current, str):
        if isinstance(current, bool):
            if value.lower() in ("true", "1", "yes"):
                return True
            elif value.lower() in ("false", "0", "no"):
                return False
            raise ValueError(f"Cannot convert {value!r} to bool for key {key!r}")
        if isinstance(current, int):
            return int(value)
        if isinstance(current, list):
            return [s.strip() for s in value.split(",")]
    return value


def _validate_value(key: str, value: Any) -> None:
    """Validate a config value."""
    if key in ("transcription.model", "captions.model") and value not in VALID_MODELS:
        raise ValueError(f"Invalid model: {value!r}. Choose from: {', '.join(VALID_MODELS)}")
    if key == "transcription.output_formats":
        if not value:
            raise ValueError("output_formats must contain at least one format")
        for fmt in value:
            if fmt not in VALID_OUTPUT_FORMATS:
                raise ValueError(f"Invalid output format: {fmt!r}. Choose from: {', '.join(VALID_OUTPUT_FORMATS)}")
    if key == "transcription.diarize_engine" and value not in ("nemotron", "wespeaker"):
        raise ValueError(f"Invalid diarization engine: {value!r}. Choose from: nemotron, wespeaker")
    if key == "recording.sample_rate" and value <= 0:
        raise ValueError(f"sample_rate must be positive, got {value}")
    if key == "recording.channels" and value <= 0:
        raise ValueError(f"channels must be positive, got {value}")
    if key == "app.recent_limit" and value <= 0:
        raise ValueError(f"recent_limit must be positive, got {value}")

    if key == "captions.audio_source" and value not in ("both", "microphone", "system"):
        raise ValueError("captions.audio_source must be both, microphone, or system")
    if key == "captions.output_mode" and value not in ("headphones", "speakers"):
        raise ValueError("captions.output_mode must be headphones or speakers")
    if key == "captions.font_size" and not 12 <= value <= 72:
        raise ValueError("captions.font_size must be between 12 and 72")
