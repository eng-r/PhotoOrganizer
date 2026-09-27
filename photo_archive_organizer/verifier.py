import hashlib


CHUNK_SIZE = 1024 * 1024


def sha256(path, stop=None):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            if stop and stop.is_set():
                raise InterruptedError("verification interrupted")
            digest.update(chunk)
    return digest.hexdigest()


class CopyVerifier:
    def verify(self, staged, source_size, source_hash, stop):
        size = staged.stat().st_size
        digest = sha256(staged, stop)
        return size == source_size and digest == source_hash, size, digest
