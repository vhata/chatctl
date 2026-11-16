"""Synthetic local POSIX storage, races, permissions and publication failures."""

import copy
import os
import stat
from pathlib import Path
from typing import Any, NoReturn

import pytest

from chatctl import manifest as m
from chatctl.manifest_store import ManifestStore, StoreError
from tests.test_manifest import BINDING, begin, document, outcome


@pytest.fixture
def home(tmp_path, monkeypatch):
    # Linux CI puts pytest under world-writable /tmp. Treat only the
    # system temporary directory as a trusted harness root, never any
    # component inside our test home. Production has no such exemption.
    original = ManifestStore._directory
    import tempfile

    system_temp = Path(tempfile.gettempdir()).resolve()
    temp_identity = system_temp.stat()

    def directory(fd: int, private: bool) -> None:
        info = os.fstat(fd)
        if (
            not private
            and (info.st_dev, info.st_ino)
            == (temp_identity.st_dev, temp_identity.st_ino)
            and info.st_mode & 0o022
        ):
            return
        original(fd, private)

    monkeypatch.setattr(ManifestStore, "_directory", staticmethod(directory))
    root = tmp_path.resolve() / "home"
    root.mkdir(mode=0o700)
    return root


def publish(home: Path, d: m.Document | None = None) -> Path:
    with ManifestStore(home=home, create=True) as store, store.locked():
        return store.publish(document() if d is None else d)


def test_private_atomic_store_and_read_only_open(home):
    old_umask = os.umask(0)
    try:
        path = publish(home)
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.parent.parent.stat().st_mode) == 0o700
    lock = path.parent.parent / "mutation.lock"
    assert stat.S_IMODE(lock.stat().st_mode) == 0o600
    original_inode = path.stat().st_ino
    lock_inode = lock.stat().st_ino
    with ManifestStore(home=home) as store:
        assert store.load(path.name) == document()
        before = path.stat()
        assert store.scan() == (document(),)
        assert path.stat().st_mtime_ns == before.st_mtime_ns
        with pytest.raises(StoreError):
            store.publish(document())
    with ManifestStore(home=home) as store, store.locked():
        store.checkpoint(path.name, begin(document()), expected_revision=0)
        assert store.load(path.name)["revision"] == 1
    assert path.stat().st_ino != original_inode
    assert lock.stat().st_ino == lock_inode
    assert not list(path.parent.glob(".tmp-*"))


def test_missing_read_only_store_does_not_create(home):
    with pytest.raises(StoreError), ManifestStore(home=home):
        pass
    assert not (home / ".local").exists()


def test_lock_contention_and_release(home):
    publish(home)
    with ManifestStore(home=home) as first, ManifestStore(home=home) as second:
        with first.locked():
            with pytest.raises(StoreError), second.locked():
                pass
        with ManifestStore(home=home) as fresh, fresh.locked():
            assert fresh.scan()


def test_initial_collision_preserves_existing_and_poisoned_instance(home):
    path = publish(home)
    before = path.read_bytes()
    with ManifestStore(home=home) as store, store.locked():
        with pytest.raises(StoreError):
            store.publish(document())
        with pytest.raises(StoreError):
            store.dispatch_allowed(BINDING, "synthetic-0")
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "permissive", "fifo"])
def test_unsafe_manifest_rejected_without_blocking(home, kind):
    path = publish(home)
    if kind == "permissive":
        path.chmod(0o644)
    elif kind == "hardlink":
        os.link(path, path.with_suffix(".copy"))
    else:
        path.unlink()
        if kind == "symlink":
            path.symlink_to(home / "missing")
        else:
            os.mkfifo(path, 0o600)
    with ManifestStore(home=home) as store:
        with pytest.raises(StoreError):
            store.load(path.name)


@pytest.mark.parametrize(
    "component",
    [
        ".local",
        ".local/state",
        ".local/state/chatctl",
        ".local/state/chatctl/manifests",
    ],
)
def test_symlink_components_rejected(home, component):
    publish(home)
    path = home / component
    moved = path.with_name(path.name + "-moved")
    path.rename(moved)
    path.symlink_to(moved, target_is_directory=True)
    with pytest.raises(StoreError), ManifestStore(home=home):
        pass


@pytest.mark.parametrize("mode", [0o755, 0o770, 0o777])
def test_insecure_managed_directory_not_repaired(home, mode):
    path = publish(home).parent
    path.chmod(mode)
    with pytest.raises(StoreError), ManifestStore(home=home):
        pass
    assert stat.S_IMODE(path.stat().st_mode) == mode


def test_unsafe_ancestor_and_git_checkout_rejected(home):
    home.chmod(0o777)
    with pytest.raises(StoreError), ManifestStore(home=home, create=True):
        pass
    home.chmod(0o700)
    (home / ".git").write_text("gitdir: synthetic\n")
    with pytest.raises(StoreError), ManifestStore(home=home, create=True):
        pass
    (home / ".git").unlink()
    (home / ".git").mkdir()
    with pytest.raises(StoreError), ManifestStore(home=home, create=True):
        pass


def test_lock_replacement_and_directory_replacement_stop_writes(home):
    path = publish(home)
    with ManifestStore(home=home) as store, store.locked():
        lock = path.parent.parent / "mutation.lock"
        lock.rename(lock.with_suffix(".old"))
        lock.touch(mode=0o600)
        with pytest.raises(StoreError):
            store.checkpoint(path.name, begin(document()), expected_revision=0)
    with ManifestStore(home=home) as store, store.locked():
        path.parent.rename(path.parent.with_name("moved"))
        path.parent.mkdir(mode=0o700)
        with pytest.raises(StoreError):
            store.publish(document())


def test_stale_revision_and_forged_transition_fail_closed(home):
    path = publish(home)
    with ManifestStore(home=home) as store, store.locked():
        store.checkpoint(path.name, begin(document()), expected_revision=0)
        with pytest.raises(StoreError):
            store.checkpoint(path.name, begin(document()), expected_revision=0)
    with ManifestStore(home=home) as store, store.locked():
        forged = copy.deepcopy(store.load(path.name))
        forged["revision"] += 1
        forged["conversations"][0]["archive"] = {
            "status": "pending",
            "reason": None,
            "attempts": [],
        }
        with pytest.raises(StoreError):
            store.checkpoint(path.name, forged, expected_revision=1)


def test_cross_manifest_holds_and_invalid_scan(home):
    path = publish(home)
    with ManifestStore(home=home) as store, store.locked():
        assert store.dispatch_allowed(BINDING, "synthetic-0")
        inflight = begin(document())
        store.checkpoint(path.name, inflight, expected_revision=0)
        assert not store.dispatch_allowed("b" * 64, "unrelated")
        unknown = outcome(
            inflight,
            outcome="unknown",
            error_code="transport_unknown",
            quiescent_basis="execution_stopped",
        )
        store.checkpoint(path.name, unknown, expected_revision=1)
        assert not store.dispatch_allowed(BINDING, "synthetic-0")
        assert store.dispatch_allowed(BINDING, "unrelated")
        assert store.dispatch_allowed("b" * 64, "synthetic-0")
        (path.parent / "archive-run-invalid.json").write_text("{}")
        with pytest.raises(StoreError):
            store.dispatch_allowed(BINDING, "unrelated")


@pytest.mark.parametrize(
    "operation", ["open", "write", "flush", "file_sync", "replace", "directory_sync"]
)
def test_checkpoint_fault_keeps_complete_revision_and_stops_dispatch(
    home, monkeypatch, operation
):
    path = publish(home)
    with ManifestStore(home=home) as store, store.locked():
        original_open, original_fsync, original_replace, original_fdopen = (
            os.open,
            os.fsync,
            os.replace,
            os.fdopen,
        )

        def fail(*args: Any, **kwargs: Any) -> NoReturn:
            raise OSError("synthetic secret must not escape")

        if operation == "open":

            def failing_open(name, flags, *args, **kwargs):
                if str(name).startswith(".tmp-"):
                    return fail()
                return original_open(name, flags, *args, **kwargs)

            monkeypatch.setattr(os, "open", failing_open)
        elif operation == "replace":
            monkeypatch.setattr(os, "replace", fail)
        elif operation in {"file_sync", "directory_sync"}:

            def failing_sync(fd):
                is_dir = stat.S_ISDIR(os.fstat(fd).st_mode)
                if is_dir == (operation == "directory_sync"):
                    fail()
                return original_fsync(fd)

            monkeypatch.setattr(os, "fsync", failing_sync)
        elif operation in {"write", "flush"}:

            class BrokenWriter:
                def __init__(self, fd: int) -> None:
                    self.fd = fd

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    os.close(self.fd)

                def fileno(self):
                    return self.fd

                def write(self, data):
                    os.write(self.fd, data[:10] if operation == "write" else data)
                    if operation == "write":
                        fail()

                def flush(self) -> None:
                    fail()

            def failing_fdopen(fd, mode, *args, **kwargs):
                return (
                    BrokenWriter(fd)
                    if mode == "wb"
                    else original_fdopen(fd, mode, *args, **kwargs)
                )

            monkeypatch.setattr(os, "fdopen", failing_fdopen)
        with pytest.raises(StoreError) as error:
            store.checkpoint(path.name, begin(document()), expected_revision=0)
        assert "synthetic secret" not in str(error.value)
        with pytest.raises(StoreError):
            store.dispatch_allowed(BINDING, "unrelated")
        monkeypatch.setattr(os, "open", original_open)
        monkeypatch.setattr(os, "fsync", original_fsync)
        monkeypatch.setattr(os, "replace", original_replace)
        monkeypatch.setattr(os, "fdopen", original_fdopen)
    loaded = m.loads(path.read_text())
    assert loaded["revision"] == (1 if operation == "directory_sync" else 0)
    assert not list(path.parent.glob(".tmp-*"))


def test_initial_link_failure_and_new_directory_sync_failure(home, monkeypatch):
    with ManifestStore(home=home, create=True) as store, store.locked():

        def fail(*args: Any, **kwargs: Any) -> NoReturn:
            raise OSError("injected")

        with monkeypatch.context() as patch:
            patch.setattr(os, "link", fail)
            with pytest.raises(StoreError):
                store.publish(document())
        assert not list(store.path.glob("*.json"))
    second_home = home / "another-home"
    second_home.mkdir(mode=0o700)
    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(StoreError), ManifestStore(home=second_home, create=True):
        pass


def test_initial_unlink_failure_preserves_complete_published_file(home, monkeypatch):
    with ManifestStore(home=home, create=True) as store, store.locked():
        original = os.unlink
        calls = 0

        def fail_once(name, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("injected unlink error")
            return original(name, *args, **kwargs)

        monkeypatch.setattr(os, "unlink", fail_once)
        with pytest.raises(StoreError, match="durability uncertain"):
            store.publish(document())
        with pytest.raises(StoreError):
            store.dispatch_allowed(BINDING, "synthetic-0")
        path = store.path / store.filename(document())
        assert m.loads(path.read_text()) == document()
        assert path.stat().st_nlink == 1
        assert not list(store.path.glob(".tmp-*"))


def test_restrictive_umask_fails_before_publication(home):
    old = os.umask(0o777)
    try:
        with pytest.raises(StoreError), ManifestStore(home=home, create=True):
            pass
    finally:
        os.umask(old)
        # The fail-closed directory has no owner permissions; test cleanup
        # is explicit, never a production repair of an existing store.
        (home / ".local").chmod(0o700)
    assert not (home / ".local" / "state").exists()


def test_lock_released_when_owner_process_dies(home):
    import signal

    publish(home)
    reader, writer = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(reader)
        try:
            with ManifestStore(home=home) as store, store.locked():
                os.write(writer, b"locked")
                signal.pause()
        finally:
            os._exit(1)
    os.close(writer)
    try:
        assert os.read(reader, 6) == b"locked"
        with ManifestStore(home=home) as store:
            with pytest.raises(StoreError), store.locked():
                pass
    finally:
        os.close(reader)
        os.kill(child, signal.SIGKILL)
        os.waitpid(child, 0)
    with ManifestStore(home=home) as store, store.locked():
        assert store.scan()


def test_reader_observes_only_complete_documents_during_replace(home):
    import threading

    path = publish(home)
    stop = threading.Event()
    started = threading.Event()
    revisions: list[int] = []
    failures: list[Exception] = []

    def read() -> None:
        while not stop.is_set():
            try:
                revisions.append(m.loads(path.read_text())["revision"])
                started.set()
            except Exception as exc:
                failures.append(exc)
                started.set()
                return

    thread = threading.Thread(target=read)
    thread.start()
    try:
        assert started.wait(5)
        with ManifestStore(home=home) as store, store.locked():
            store.checkpoint(path.name, begin(document()), expected_revision=0)
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive()
    assert revisions and set(revisions) <= {0, 1}
    assert not failures
