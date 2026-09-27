from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MediaFile:
    path: Path
    relative_path: str
    size: int
    mtime_ns: int
    identity: tuple[int, int]
    recognized: bool
    eligible: bool
    reason: str = ""
    detail: str = ""
    ctime_ns: int = 0
    media_role: str = "UNSUPPORTED"
    associated_primary: str = ""


@dataclass
class Inventory:
    files: list[MediaFile] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)

    @property
    def eligible(self):
        return [f for f in self.files if f.eligible]

    @property
    def primary_media(self):
        return [f for f in self.files if f.eligible and f.media_role == "PRIMARY_MEDIA"]

    @property
    def associated_sidecars(self):
        return [f for f in self.files if f.eligible and f.media_role == "SIDECAR"]


@dataclass
class MediaMetadata:
    tags: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    attempts: int = 1


@dataclass
class ResolvedTimestamp:
    value: datetime | None = None
    category: str = "UNKNOWN"
    source_field: str = ""
    confidence: str = "UNKNOWN"
    timezone_known: bool = False
    precision: str = "unknown"
    raw_candidates: list[dict] = field(default_factory=list)
    rejected_candidates: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PlannedMediaFile:
    media: MediaFile
    timestamp: ResolvedTimestamp
    destination: str
    day_classification: str
    daily_primary_media_count: int = 0
    month_folder: str = ""
    day_folder: str = ""
    media_role: str = "PRIMARY_MEDIA"
    storage_leaf: str = ""
    associated_primary: str = ""


@dataclass
class CopyResult:
    source_relative_path: str
    destination_relative_path: str
    success: bool = False
    source_size: int = 0
    destination_size: int = 0
    source_sha256: str = ""
    destination_sha256: str = ""
    attempt_count: int = 0
    reason: str = ""
    error: str = ""
    stage: str = "COPY"


@dataclass
class ReconciliationResult:
    status: str = "NOT_RUN"
    source: Inventory = field(default_factory=Inventory)
    destination: dict[str, int] = field(default_factory=dict)
    primary_destination: dict[str, int] = field(default_factory=dict)
    sidecar_destination: dict[str, int] = field(default_factory=dict)
    issues: list[dict] = field(default_factory=list)
    complete: bool = False
    primary_status: str = "NOT_RUN"
    sidecar_status: str = "NOT_RUN"


@dataclass
class RunState:
    command: str
    run_id: str
    started: str
    ended: str = ""
    stage: str = "VALIDATE"
    inventory: Inventory = field(default_factory=Inventory)
    timestamps: dict[str, ResolvedTimestamp] = field(default_factory=dict)
    plan: list[PlannedMediaFile] = field(default_factory=list)
    copies: dict[str, CopyResult] = field(default_factory=dict)
    reconciliation: ReconciliationResult = field(default_factory=ReconciliationResult)
    errors: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    collisions: set[str] = field(default_factory=set)
    space: dict = field(default_factory=dict)
    fatal: str = ""
    interrupted: bool = False
    inventory_complete: bool = False
    metadata_version: str = ""
    completed_stage: str = "VALIDATE"


def jsonable(value):
    if hasattr(value, "__dataclass_fields__"):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if isinstance(value, (Path, datetime)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    return value
