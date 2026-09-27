import errno
import hashlib
import os
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from .models import CopyResult
from .safety import SafetyError, check_chain, same_file_state
from .verifier import CHUNK_SIZE, CopyVerifier


def publish_no_replace(staged, final):
    if os.name == "nt":
        os.rename(staged, final)  # Windows rename fails if final exists.
    else:
        # Same-volume hard link creation is exclusive. No replacing rename fallback.
        os.link(staged, final)
        staged.unlink()


class CopyEngine:
    def __init__(self, config, claim, stop, progress, verifier=None, publisher=None):
        self.config, self.claim, self.stop, self.progress = config, claim, stop, progress
        self.verifier, self.publisher = verifier or CopyVerifier(), publisher or publish_no_replace
        self.abort = threading.Event()

    def _cancelled(self):
        return self.stop.is_set() or self.abort.is_set()

    def copy_one(self, entry):
        result = CopyResult(entry.media.relative_path, entry.destination, source_size=entry.media.size)
        final = self.claim.destination / entry.destination
        for attempt in range(self.config["retry_count"] + 1):
            staged = None
            result.attempt_count = attempt + 1
            try:
                if self._cancelled():
                    raise InterruptedError("copy scheduling stopped")
                self.claim.assert_owned()
                result.stage = "SOURCE"
                check_chain(entry.media.path)
                if not same_file_state(entry.media, entry.media.path.stat()):
                    result.reason = "SOURCE_CHANGED"
                    raise SafetyError("source differs from planned inventory")
                with entry.media.path.open("rb") as source:
                    if not same_file_state(entry.media, os.fstat(source.fileno())):
                        result.reason = "SOURCE_CHANGED"
                        raise SafetyError("opened source differs from planned inventory")
                    result.stage = "COPY"
                    fd, name = tempfile.mkstemp(prefix="copy-", suffix=".partial", dir=self.claim.process / "tmp")
                    from pathlib import Path
                    staged = Path(name)
                    digest = hashlib.sha256()
                    with os.fdopen(fd, "wb") as output:
                        while True:
                            if self._cancelled():
                                raise InterruptedError("copy interrupted")
                            result.stage = "SOURCE"
                            chunk = source.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            result.stage = "COPY"
                            output.write(chunk)
                            digest.update(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    if not same_file_state(entry.media, os.fstat(source.fileno())) or not same_file_state(entry.media, entry.media.path.stat()):
                        result.reason = "SOURCE_CHANGED"
                        raise SafetyError("source changed during copy")
                result.source_sha256 = digest.hexdigest()
                result.stage = "VERIFY"
                ok, result.destination_size, result.destination_sha256 = self.verifier.verify(staged, entry.media.size, result.source_sha256, self.stop)
                if not ok:
                    result.reason = "VERIFICATION_FAILED"
                    raise OSError("size or SHA-256 mismatch")
                os.utime(staged, ns=(entry.media.mtime_ns, entry.media.mtime_ns))
                result.stage = "PUBLISH"
                if self._cancelled():
                    raise InterruptedError("publication interrupted")
                self.claim.assert_owned()
                check_chain(final.parent)
                final.parent.mkdir(parents=True, exist_ok=True)
                check_chain(final.parent)
                self.publisher(staged, final)
                staged = None
                result.success, result.reason, result.error = True, "", ""
                return result
            except InterruptedError as exc:
                result.reason, result.error = "INTERRUPTED" if self.stop.is_set() else "NOT_ATTEMPTED_RUN_ABORTED", str(exc)
                return result
            except (OSError, SafetyError) as exc:
                result.error = str(exc)
                if not result.reason:
                    result.reason = ("SOURCE_DISAPPEARED" if isinstance(exc, FileNotFoundError) and result.stage == "SOURCE" else
                                     "SOURCE_READ_FAILED" if result.stage == "SOURCE" else
                                     "VERIFICATION_FAILED" if result.stage == "VERIFY" else
                                     "PUBLICATION_FAILED" if result.stage == "PUBLISH" else "COPY_FAILED")
                permanent = isinstance(exc, (SafetyError, FileExistsError))
                if isinstance(exc, OSError) and (exc.errno == errno.ENOSPC or (exc.errno in (errno.EACCES, errno.EROFS) and result.stage != "SOURCE")):
                    self.abort.set()
                    permanent = True
                self.progress.emit(f"ERROR {entry.media.relative_path}: {result.reason}: {exc}")
                if permanent or attempt == self.config["retry_count"]:
                    return result
                if self.stop.wait(self.config["retry_delays_seconds"][attempt]):
                    result.reason = "INTERRUPTED"
                    return result
                result.reason = ""
            finally:
                if staged is not None:
                    try:
                        staged.unlink(missing_ok=True)
                    except OSError as exc:
                        self.abort.set()
                        self.progress.emit(f"ERROR could not clean owned partial: {exc}")
        return result

    def run(self, plan, results, on_result):
        iterator = iter(plan)
        started = time.monotonic()
        completed_bytes = 0
        with ThreadPoolExecutor(max_workers=self.config["copy_workers"]) as pool:
            pending = {}
            while True:
                while len(pending) < self.config["copy_workers"] and not self._cancelled():
                    entry = next(iterator, None)
                    if entry is None:
                        break
                    pending[pool.submit(self.copy_one, entry)] = entry
                if not pending:
                    break
                done, _ = wait(pending, timeout=.2, return_when=FIRST_COMPLETED)
                for future in done:
                    entry = pending.pop(future)
                    result = future.result()
                    results[entry.media.relative_path] = result
                    completed_bytes += result.source_size if result.success else 0
                    on_result(result)
                    self.progress.update(f"{len(results)}/{len(plan)} processed; {completed_bytes} verified bytes; {completed_bytes / max(time.monotonic() - started, .001) / 1e6:.1f} MB/s")
        for entry in plan:
            if entry.media.relative_path not in results:
                result = CopyResult(entry.media.relative_path, entry.destination,
                                    reason="INTERRUPTED" if self.stop.is_set() else "NOT_ATTEMPTED_RUN_ABORTED",
                                    error="not scheduled after run stopped")
                results[entry.media.relative_path] = result
                on_result(result)
