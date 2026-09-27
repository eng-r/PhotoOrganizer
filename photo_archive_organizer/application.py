import signal
import threading
import uuid
from datetime import datetime, timezone

from .copier import CopyEngine
from .discovery import SourceScanner
from .metadata import ExifToolMetadataProvider
from .models import MediaMetadata, RunState
from .planner import ArchivePlanner
from .progress import ProgressReporter
from .reconciler import ArchiveReconciler
from .reporting import AuditWriter, ReportWriter
from .safety import DestinationClaim, PreflightValidator, SafetyError, SpaceEstimator
from .timestamp_resolver import TimestampResolver


class ArchiveOrganizer:
    """Coordinates stages. All placement algorithms and I/O services are separate."""
    def __init__(self, config, provider=None, now=None, copier_factory=CopyEngine):
        self.config = config
        self.now = now or datetime.now(timezone.utc)
        self.stop = threading.Event()
        self.provider = provider or ExifToolMetadataProvider(config.section("runtime")["metadata_timeout_seconds"], stop=self.stop)
        self.copier_factory = copier_factory
        self.state = None
        self.summary = None

    def execute(self, command):
        state = self.state = RunState(command, str(uuid.uuid4()), self.now.isoformat())
        claim = DestinationClaim(self.config.destination_root, state.run_id, state.started)
        progress = None
        previous_signal = None
        if threading.current_thread() is threading.main_thread():
            previous_signal = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, lambda *_: self.stop.set())
        try:
            PreflightValidator().validate_paths(self.config)
            state.metadata_version = self.provider.check()
            if command == "validate":
                print("VALIDATE: PASS — configuration, paths, empty destination, and ExifTool checked")
                return 0
            if self.stop.is_set():
                raise InterruptedError("interrupted before destination claim")
            process = claim.acquire()
            progress = ProgressReporter(self.config.section("runtime")["progress_interval_seconds"], process / "logs/photo_organizer.txt")
            progress.start()
            audit = AuditWriter(process)
            audit.snapshot(self.config, state)
            self._stage(state, progress, "DISCOVERY")
            SourceScanner(self.config.section("media"), progress, self.stop).scan(self.config.source_root, state.inventory)
            state.inventory_complete = not state.inventory.gaps
            if state.inventory.gaps:
                raise SafetyError("source inventory incomplete; see coverage gaps")
            state.completed_stage = "DISCOVERY"
            if not state.inventory.eligible:
                state.warnings.append("no eligible media")
            self._stage(state, progress, "METADATA")
            self._analyze(state, progress)
            audit.analysis(state, include_plan=False)
            state.completed_stage = "ANALYZE"
            if command != "analyze":
                self._stage(state, progress, "PLANNING")
                planner = ArchivePlanner(self.config.section("day_grouping"))
                state.plan = planner.build(state.inventory.eligible, state.timestamps)
                state.collisions = planner.validate(state.plan, state.inventory.eligible)
                audit.analysis(state, include_plan=True)
                if state.collisions:
                    for path in sorted(state.collisions):
                        state.errors.append({"path": path, "stage": "PLANNING", "reason": "PLAN_COLLISION", "detail": "multiple sources target the same path"})
                    raise SafetyError("unresolved filename collisions; no media copied")
                state.completed_stage = "PLANNING"
                self._stage(state, progress, "PREFLIGHT")
                claim.assert_owned(before_copy=True)
                copy_config = self.config.section("copy")
                state.space = SpaceEstimator().estimate(state.plan, self.config.destination_root, copy_config["copy_workers"], copy_config["free_space_margin_percent"])
                if state.space["status"] != "PASS":
                    raise SafetyError("insufficient destination space")
                state.completed_stage = "PREFLIGHT"
                if command == "run":
                    self._stage(state, progress, "COPY")
                    engine = self.copier_factory(copy_config, claim, self.stop, progress)
                    engine.run(state.plan, state.copies, audit.copy_result)
                    state.completed_stage = "COPY"
                    for r in state.copies.values():
                        if not r.success:
                            state.errors.append({"path": r.source_relative_path, "stage": r.stage, "reason": r.reason, "detail": r.error})
                    self._stage(state, progress, "RECONCILE")
                    claim.assert_owned()
                    state.reconciliation = ArchiveReconciler(self.config.section("media"), progress, self.stop).reconcile(
                        self.config.source_root, self.config.destination_root, state.inventory, state.plan, state.copies)
                    state.completed_stage = "RECONCILE"
            if self.stop.is_set():
                raise InterruptedError("run interrupted")
        except (KeyboardInterrupt, InterruptedError):
            self.stop.set()
            state.interrupted = True
            print("INTERRUPTED: stopping safely", flush=True)
        except Exception as exc:
            state.fatal = str(exc)
            state.errors.append({"path": "", "stage": state.stage, "reason": "FATAL", "detail": str(exc)})
            print(f"FATAL: {exc}", flush=True)
        finally:
            if progress:
                progress.close()
                if progress.error:
                    state.fatal = f"required log write failed: {progress.error}"
            if previous_signal is not None:
                signal.signal(signal.SIGINT, previous_signal)
        if self.stop.is_set():
            state.interrupted = True
        state.ended = datetime.now(timezone.utc).isoformat()
        if claim.owned:
            try:
                claim.assert_owned()
                self.summary = ReportWriter(claim.process).write(self.config, state)
                print(f"{self.summary['status']}: reconciliation={state.reconciliation.status}; report={claim.process / 'reports/report.html'}")
                return self.summary["exit_code"]
            except (OSError, SafetyError, ValueError) as exc:
                print(f"FATAL: required report could not be written: {exc}")
                state.fatal = f"required report could not be written: {exc}"
                try:
                    claim.assert_owned()
                    self.summary, _ = ReportWriter(claim.process).record_report_failure(self.config, state)
                except (OSError, SafetyError, ValueError):
                    pass  # Console and exit status remain authoritative if output is unavailable.
                return 3 if state.interrupted else 2
        return 3 if state.interrupted else 2

    def _stage(self, state, progress, name):
        if self.stop.is_set():
            raise InterruptedError()
        if progress.error:
            raise SafetyError(f"required log write failed: {progress.error}")
        state.stage = name
        progress.set_stage(name)

    def _analyze(self, state, progress):
        files = state.inventory.primary_media
        policy = self.config.section("copy")
        resolver = TimestampResolver(self.config.section("timestamp"), self.now)
        for start in range(0, len(files), 128):
            pending = files[start:start + 128]
            results = {}
            for attempt in range(policy["retry_count"] + 1):
                if self.stop.is_set():
                    raise InterruptedError()
                response = self.provider.read_batch([f.path for f in pending])
                failed = []
                for media in pending:
                    metadata = response.get(media.path, MediaMetadata(error="provider omitted file"))
                    metadata.attempts = attempt + 1
                    results[media.relative_path] = metadata
                    if metadata.error:
                        failed.append(media)
                if not failed or attempt == policy["retry_count"]:
                    break
                progress.emit(f"WARNING retrying metadata extraction for {len(failed)} files")
                if self.stop.wait(policy["retry_delays_seconds"][attempt]):
                    raise InterruptedError()
                pending = failed
            for media in files[start:start + 128]:
                metadata = results[media.relative_path]
                if metadata.error:
                    state.errors.append({"path": media.relative_path, "stage": "METADATA", "reason": "METADATA_READ_FAILED", "detail": metadata.error})
                    progress.emit(f"ERROR {media.relative_path}: {metadata.error}")
                state.timestamps[media.relative_path] = resolver.resolve(media, metadata)
            progress.update(f"{len(state.timestamps)}/{len(files)} files analyzed")
