import hashlib
import os
import platform
import secrets
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

_PRIVATE_DIR_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600


class CacheLockTimeoutError(TimeoutError):
    """Raised when another process holds a cache lock for too long."""


def get_cache_dir() -> Path:
    """Return the platform-appropriate cache directory for elf.

    Priority:
        1. ELF_CACHE_DIR environment variable
        2. Windows LOCALAPPDATA
        3. XDG_CACHE_HOME
        4. ~/.cache/elf
    """
    if env_cache_dir := os.getenv("ELF_CACHE_DIR"):
        return Path(os.path.expandvars(os.path.expanduser(env_cache_dir))).resolve()

    system = platform.system()

    if system == "Windows":
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))

    return base / "elf"


def _credential_fingerprint(kind: str, credential: str) -> str:
    """Return a stable cache identifier without exposing a credential."""
    value = f"elf-cache-v2\0{kind}\0{credential}".encode()
    return hashlib.sha256(value).hexdigest()[:24]


def get_account_cache_dir(session_token: str) -> Path:
    """Return the private cache namespace for one AoC account."""
    fingerprint = _credential_fingerprint("session", session_token)
    return get_cache_dir() / "accounts" / fingerprint


def get_cache_guess_file(year: int, day: int, session_token: str | None = None) -> Path:
    """Return path to guesses cache CSV."""
    root = get_account_cache_dir(session_token) if session_token else get_cache_dir()
    return root / f"{year:04d}" / f"{day:02d}" / "guesses.csv"


def get_cache_input_file(year: int, day: int, session_token: str | None = None) -> Path:
    """Return path to input cache file."""
    root = get_account_cache_dir(session_token) if session_token else get_cache_dir()
    return root / f"{year:04d}" / f"{day:02d}" / "input.txt"


def get_cache_leaderboard_file(
    year: int,
    board_id: int,
    *,
    session_token: str | None,
    view_key: str | None,
) -> Path:
    """Return a leaderboard path scoped to its authentication mechanism."""
    if view_key:
        scope = "views"
        fingerprint = _credential_fingerprint("view-key", view_key)
    elif session_token:
        scope = "accounts"
        fingerprint = _credential_fingerprint("session", session_token)
    else:
        raise ValueError("A session token or view key is required for caching.")

    return (
        get_cache_dir() / "leaderboards" / scope / fingerprint / f"{year:04d}" / f"{board_id}.json"
    )


def migrate_legacy_cache_file(legacy_file: Path, scoped_file: Path) -> bool:
    """Claim and copy an old unscoped cache file into one private namespace."""
    if not legacy_file.is_file():
        return False
    _make_private(legacy_file, _PRIVATE_FILE_MODE)

    marker_file = legacy_file.with_name(f".{legacy_file.name}.migrated")
    try:
        claim = scoped_file.relative_to(get_cache_dir()).as_posix()
    except ValueError:
        claim = scoped_file.as_posix()

    try:
        _ensure_private_directory(marker_file.parent)
        marker_descriptor = os.open(
            marker_file,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            _PRIVATE_FILE_MODE,
        )
    except FileExistsError:
        try:
            if marker_file.read_text(encoding="utf-8").strip() != claim:
                return False
        except (OSError, UnicodeError):
            return False
    else:
        with os.fdopen(marker_descriptor, "w", encoding="utf-8") as marker:
            marker.write(f"{claim}\n")
            marker.flush()
            os.fsync(marker.fileno())

    if scoped_file.exists():
        return False
    atomic_write_bytes(scoped_file, legacy_file.read_bytes())
    return True


def atomic_write_text(path: Path, content: str) -> None:
    """Atomically replace a UTF-8 text cache file with private permissions."""
    atomic_write_bytes(path, content.encode("utf-8"))


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Atomically replace a cache file, avoiding partial writes on interruption."""
    _ensure_private_directory(path.parent)

    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary_path = Path(temporary_name)
    try:
        _make_private(temporary_path, _PRIVATE_FILE_MODE)
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
        _make_private(path, _PRIVATE_FILE_MODE)
    except BaseException:
        with suppress(OSError):
            os.close(file_descriptor)
        temporary_path.unlink(missing_ok=True)
        raise


@contextmanager
def cache_file_lock(
    cache_file: Path,
    *,
    timeout: float = 30.0,
    stale_after: float = 120.0,
    poll_interval: float = 0.05,
) -> Iterator[None]:
    """Hold a cross-process lease while reading and replacing a cache file."""
    lock_file = cache_file.with_name(f".{cache_file.name}.lock")
    _ensure_private_directory(lock_file.parent)
    deadline = time.monotonic() + timeout
    token = secrets.token_hex(16)
    lock_identity: tuple[int, int] | None = None

    while lock_identity is None:
        try:
            descriptor = os.open(
                lock_file,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                _PRIVATE_FILE_MODE,
            )
        except FileExistsError:
            if _remove_stale_lock(lock_file, stale_after):
                continue
            if time.monotonic() >= deadline:
                raise CacheLockTimeoutError(
                    f"Timed out waiting for cache lock {lock_file}."
                ) from None
            time.sleep(poll_interval)
            continue

        try:
            lock_stat = os.fstat(descriptor)
            lock_identity = (lock_stat.st_dev, lock_stat.st_ino)
            with os.fdopen(descriptor, "w", encoding="utf-8") as lock:
                lock.write(f"{token} {os.getpid()} {time.time()}\n")
                lock.flush()
                os.fsync(lock.fileno())
        except BaseException:
            with suppress(OSError):
                os.close(descriptor)
            lock_file.unlink(missing_ok=True)
            raise

    try:
        yield
    finally:
        try:
            current_stat = lock_file.stat()
            current_identity = (current_stat.st_dev, current_stat.st_ino)
            if current_identity == lock_identity:
                lock_file.unlink(missing_ok=True)
        except OSError:
            pass


def _remove_stale_lock(lock_file: Path, stale_after: float) -> bool:
    try:
        if time.time() - lock_file.stat().st_mtime <= stale_after:
            return False
        lock_file.unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _make_private(path: Path, mode: int) -> None:
    """Apply private POSIX permissions where chmod is supported."""
    with suppress(OSError):
        path.chmod(mode)


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=_PRIVATE_DIR_MODE)
    cache_root = get_cache_dir()
    current = path
    while current == cache_root or cache_root in current.parents:
        _make_private(current, _PRIVATE_DIR_MODE)
        if current == cache_root:
            break
        current = current.parent
