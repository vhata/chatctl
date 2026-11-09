"""Private POSIX manifest storage, independent of browser and command code.

A store context opens and checks every ancestor using directory descriptors.
The mutation lock context covers the whole caller operation, not one write.
Any persistence failure poisons the instance: callers must stop dispatch.
"""

import fcntl
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from uuid import uuid4

from chatctl.manifest import (
    Document,
    ManifestError,
    dumps,
    holds,
    loads,
    validate,
    validate_transition,
)


class StoreError(OSError):
    """Storage unavailable or unsafe; contains no private OS error details."""


class ManifestStore:
    """Use the fixed state path below a home directory (injectable for tests).

    ``create=False`` opens an existing store without writing or acquiring a
    lock. ``create=True`` may create private directories. Apply integration
    must enter ``locked()`` and keep it open until the entire run ends.
    """

    def __init__(self, *, home: Path | None = None, create: bool = False):
        self.home = Path.home() if home is None else home
        self.path = self.home / ".local" / "state" / "chatctl" / "manifests"
        self.create_directories = create
        self._chain: list[tuple[int, str | None, bool]] = []
        self._lock_fd: int | None = None
        self._poisoned = False

    @staticmethod
    def _directory(fd: int, private: bool) -> None:
        info = os.fstat(fd)
        allowed_owners = {os.getuid()} if private else {0, os.getuid()}
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in allowed_owners
            or info.st_mode & (0o077 if private else 0o022)
        ):
            raise StoreError("unsafe store directory")
        try:
            os.stat(".git", dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise StoreError("manifest store cannot be inside a Git checkout")

    @staticmethod
    def _file(fd: int) -> os.stat_result:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
        ):
            raise StoreError("unsafe store file")
        return info

    def __enter__(self) -> "ManifestStore":
        if self._chain or not self.path.is_absolute() or ".." in self.path.parts:
            raise StoreError("invalid store path or already open")
        try:
            fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self._chain.append((fd, None, False))
            self._directory(fd, False)
            parts = self.path.parts[1:]
            for index, name in enumerate(parts):
                private = index >= len(parts) - 2
                created = False
                try:
                    child = os.open(
                        name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                    )
                except FileNotFoundError:
                    # Never manufacture a missing home or its ancestors.
                    if not self.create_directories or index < len(self.home.parts) - 1:
                        raise
                    os.mkdir(name, 0o700, dir_fd=fd)
                    created = True
                    child = os.open(
                        name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                    )
                self._chain.append((child, name, private))
                self._directory(child, private)
                if created:
                    os.fchmod(child, 0o700)
                    os.fsync(child)
                    os.fsync(fd)
                fd = child
            self._check_chain()
            return self
        except (OSError, AttributeError):
            self.close()
            raise StoreError("cannot open a secure local manifest store") from None

    def close(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
        for fd, _, _ in reversed(self._chain):
            os.close(fd)
        self._chain.clear()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def _dir_fd(self) -> int:
        if not self._chain:
            raise StoreError("store is closed")
        return self._chain[-1][0]

    @property
    def _state_fd(self) -> int:
        if not self._chain:
            raise StoreError("store is closed")
        return self._chain[-2][0]

    def _check_chain(self) -> None:
        if self._poisoned or not self._chain:
            raise StoreError("store is closed or unusable after a failure")
        previous: int | None = None
        for fd, name, private in self._chain:
            self._directory(fd, private)
            if previous is not None and name is not None:
                actual = os.stat(name, dir_fd=previous, follow_symlinks=False)
                opened = os.fstat(fd)
                if (actual.st_dev, actual.st_ino) != (opened.st_dev, opened.st_ino):
                    raise StoreError("store directory was replaced")
            previous = fd
        if self._lock_fd is not None:
            self._same_file(self._state_fd, "mutation.lock", self._lock_fd)

    def _same_file(self, directory: int, name: str, fd: int) -> None:
        opened = self._file(fd)
        current = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise StoreError("store file was replaced")

    @contextmanager
    def locked(self) -> Iterator["ManifestStore"]:
        """Acquire the persistent global lock without waiting; never unlink it."""
        if self._lock_fd is not None:
            raise StoreError("lock already held")
        fd: int | None = None
        try:
            self._check_chain()
            created = False
            try:
                fd = os.open(
                    "mutation.lock",
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=self._state_fd,
                )
                created = True
            except FileExistsError:
                fd = os.open(
                    "mutation.lock",
                    os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=self._state_fd,
                )
            self._file(fd)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_fd = fd
            self._check_chain()
            if created:
                os.fchmod(fd, 0o600)
                os.fsync(fd)
                os.fsync(self._state_fd)
        except OSError:
            if fd is not None:
                os.close(fd)
            self._lock_fd = None
            self._poisoned = True
            raise StoreError("manifest lock unavailable or unsafe") from None
        try:
            yield self
        finally:
            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None

    @staticmethod
    def filename(document: Document) -> str:
        validate(document)
        stamp = document["created_at"].replace(":", "-")
        return f"archive-run-{stamp}-{document['run_id']}.json"

    @staticmethod
    def _name(name: str) -> None:
        if (
            not isinstance(name, str)
            or not name.startswith("archive-run-")
            or not name.endswith(".json")
            or "/" in name
            or "\\" in name
            or "\x00" in name
        ):
            raise StoreError("invalid manifest filename")

    def _read(self, name: str) -> tuple[Document, tuple[int, int]]:
        self._name(name)
        self._check_chain()
        fd = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._dir_fd
        )
        try:
            info = self._file(fd)
            with os.fdopen(os.dup(fd), "r", encoding="utf-8") as stream:
                document = loads(stream.read())
            self._same_file(self._dir_fd, name, fd)
            self._check_chain()
            if name != self.filename(document):
                raise StoreError("manifest filename does not match identity")
            return document, (info.st_dev, info.st_ino)
        finally:
            os.close(fd)

    def load(self, name: str) -> Document:
        """Read without mutation; in-flight remains stored but holds as unknown."""
        try:
            return self._read(name)[0]
        except (OSError, ValueError, UnicodeError):
            self._poisoned = True
            raise StoreError("cannot read a valid private manifest") from None

    def scan(self) -> tuple[Document, ...]:
        """Inspect every published manifest; invalid or unexpected files stop use."""
        try:
            self._check_chain()
            documents = []
            for name in sorted(os.listdir(self._dir_fd)):
                if name.startswith(".tmp-"):
                    # Private unpublished temporaries cannot authorize dispatch.
                    continue
                documents.append(self.load(name))
            return tuple(documents)
        except (OSError, ValueError):
            self._poisoned = True
            raise StoreError("manifest scan failed closed") from None

    def dispatch_allowed(self, binding: str, conversation_id: str) -> bool:
        """Check all run holds under the mutation lock before a future intent.

        The caller still needs account comparison and fresh preflight. Call
        before persisting the new intent, since that intent itself holds.
        """
        self._writable()
        global_hold, id_holds = holds(self.scan())
        return not global_hold and (binding, conversation_id) not in id_holds

    def _writable(self) -> None:
        self._check_chain()
        if self._lock_fd is None:
            raise StoreError("mutation lock required")

    def publish(self, document: Document) -> Path:
        """Durably publish a complete initial selection without clobbering."""
        validate(document)
        if (
            document["revision"] != 0
            or document["undo_started_at"] is not None
            or any(
                row["archive"]["status"] != "pending"
                for row in document["conversations"]
            )
        ):
            raise ManifestError("initial publication needs a fresh selection")
        name = self.filename(document)
        self._write(name, document, old=None, identity=None)
        return self.path / name

    def checkpoint(
        self, name: str, document: Document, *, expected_revision: int
    ) -> None:
        """Replace only the matching on-disk revision with a legal transition."""
        try:
            self._writable()
            old, identity = self._read(name)
            validate_transition(old, document, expected_revision)
            self._write(name, document, old=old, identity=identity)
        except (OSError, ValueError):
            self._poisoned = True
            raise StoreError("manifest checkpoint failed; stop dispatch") from None

    def _write(
        self,
        name: str,
        document: Document,
        *,
        old: Document | None,
        identity: tuple[int, int] | None,
    ) -> None:
        temporary = f".tmp-{uuid4()}"
        created = False
        published = False
        try:
            self._writable()
            encoded = dumps(document).encode("utf-8")
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=self._dir_fd,
            )
            created = True
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                self._file(stream.fileno())
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            self._writable()
            if old is None:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=self._dir_fd,
                    dst_dir_fd=self._dir_fd,
                    follow_symlinks=False,
                )
                published = True
                os.unlink(temporary, dir_fd=self._dir_fd)
                created = False
            else:
                current, current_identity = self._read(name)
                if current != old or current_identity != identity:
                    raise StoreError("manifest changed before replacement")
                os.replace(
                    temporary, name, src_dir_fd=self._dir_fd, dst_dir_fd=self._dir_fd
                )
                published = True
                created = False
            os.fsync(self._dir_fd)
            self._check_chain()
        except (OSError, ValueError):
            self._poisoned = True
            message = "manifest publication failed; stop dispatch"
            if published:
                message = "manifest publication durability uncertain; either revision may survive a crash; stop dispatch"
            raise StoreError(message) from None
        finally:
            if created:
                try:
                    os.unlink(temporary, dir_fd=self._dir_fd)
                except OSError:
                    pass
