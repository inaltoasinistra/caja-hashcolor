#!/usr/bin/env python3
import hashlib
import os
import sqlite3
from typing import Callable, Literal

import gi

gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib  # noqa: E402

Mode = Literal['fast', 'precise']

FAST_MODE_FULL_HASH_THRESHOLD_BYTES = 1024 * 1024
HEAD_ANCHOR_BYTES = 250 * 1024
TAIL_ANCHOR_BYTES = 250 * 1024
READ_CHUNK_SIZE_BYTES = 1024 * 1024
ASYNC_READ_CHUNK_BYTES = 1024 * 1024

DEFAULT_CACHE_PATH = os.path.expanduser('~/.cache/caja-hashcolor/cache.db')


def _full_hash(path: str) -> bytes:
    hasher = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(READ_CHUNK_SIZE_BYTES), b''):
            hasher.update(chunk)
    return hasher.digest()


def _sampled_hash(path: str, size: int) -> bytes:
    # Head+tail only, no middle: uniformly-scattered small samples are a weak bet
    # in a large file (a fixed byte budget becomes a vanishing fraction as size
    # grows), while many real formats concentrate the content most likely to change
    # at the boundaries - archive/container indices at the end, EXIF/XMP/thumbnail
    # metadata at the start, and interrupted-write corruption typically hitting the
    # tail since writes are usually sequential. Only called for files above
    # FAST_MODE_FULL_HASH_THRESHOLD_BYTES, which is comfortably larger than
    # HEAD_ANCHOR_BYTES + TAIL_ANCHOR_BYTES, so the two anchors never overlap.
    # Include size in the digest so two files sharing both anchors but differing
    # only in the untouched middle don't collide to the same color.
    hasher = hashlib.sha256()
    hasher.update(size.to_bytes(8, 'big'))
    with open(path, 'rb') as f:
        hasher.update(f.read(HEAD_ANCHOR_BYTES))
        f.seek(size - TAIL_ANCHOR_BYTES)
        hasher.update(f.read(TAIL_ANCHOR_BYTES))
    return hasher.digest()


def compute_digest(path: str, size: int, mode: Mode) -> bytes:
    if mode == 'precise' or size <= FAST_MODE_FULL_HASH_THRESHOLD_BYTES:
        return _full_hash(path)
    return _sampled_hash(path, size)


class AsyncFullHash:
    """Hashes an entire file using GIO's async I/O (Gio.File.read_async +
    GFileInputStream.read_bytes_async) instead of a plain synchronous read(), so a
    large or slow (e.g. network-mounted) file never blocks the caller's main loop.
    A spawned OS thread was tried instead and confirmed to hang inside a live Caja
    process (see hash_color.py) - GIO's own async machinery does the actual I/O
    without our code ever creating a thread, sidestepping that problem entirely.

    on_complete(digest) or on_error(exc) is called exactly once, from the main
    loop. Pass a Gio.Cancellable to allow aborting a read in progress (e.g. Caja's
    cancel_update, or the extension being disabled) - a cancelled read calls
    on_error with a Gio.IOErrorEnum.CANCELLED GLib.Error."""

    def __init__(self, path: str, cancellable: Gio.Cancellable, on_complete: Callable[[bytes], None],
                 on_error: Callable[[GLib.Error], None]) -> None:
        self._hasher = hashlib.sha256()
        self._cancellable = cancellable
        self._on_complete = on_complete
        self._on_error = on_error
        gfile = Gio.File.new_for_path(path)
        gfile.read_async(GLib.PRIORITY_DEFAULT, cancellable, self._on_opened)

    def _on_opened(self, gfile: Gio.File, result: Gio.AsyncResult) -> None:
        try:
            stream = gfile.read_finish(result)
        except GLib.Error as exc:
            self._on_error(exc)
            return
        self._read_next(stream)

    def _read_next(self, stream: Gio.FileInputStream) -> None:
        stream.read_bytes_async(ASYNC_READ_CHUNK_BYTES, GLib.PRIORITY_DEFAULT, self._cancellable, self._on_read)

    def _on_read(self, stream: Gio.FileInputStream, result: Gio.AsyncResult) -> None:
        try:
            data = stream.read_bytes_finish(result)
        except GLib.Error as exc:
            self._on_error(exc)
            return
        chunk = data.get_data()
        if not chunk:
            stream.close_async(GLib.PRIORITY_DEFAULT, None, lambda *_args: None)
            self._on_complete(self._hasher.digest())
            return
        self._hasher.update(chunk)
        self._read_next(stream)


def is_cancelled_error(exc: GLib.Error) -> bool:
    return exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED)


class SerialQueue:
    """Runs at most one submitted job at a time. Each job is a callable that
    receives a `done` callback and must call it exactly once when finished; the
    next queued job (if any) only starts once the current one calls `done`.

    Used so hashing multiple files in a directory doesn't start a new file's I/O
    until the previous one has fully finished (or been cancelled) - avoiding many
    concurrent async operations competing for the main loop's attention, e.g. when
    a folder full of large network files loads at once."""

    def __init__(self) -> None:
        self._pending: list[Callable[[Callable[[], None]], None]] = []
        self._busy = False

    def submit(self, job: Callable[[Callable[[], None]], None]) -> None:
        self._pending.append(job)
        self._advance()

    def _advance(self) -> None:
        if self._busy or not self._pending:
            return
        self._busy = True
        job = self._pending.pop(0)
        finished = False

        def done() -> None:
            # Idempotent and reachable even if `job` never calls it itself: a job
            # that raises before calling done() (or a buggy job that calls it twice)
            # must never leave the queue permanently stuck on this one job.
            nonlocal finished
            if finished:
                return
            finished = True
            self._busy = False
            self._advance()

        try:
            job(done)
        except Exception:
            done()


class HashCache:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._connect()

    def _connect(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        # Keyed by (path, mode): fast and precise disagree on files above the
        # threshold, so a digest cached under one mode must never be served
        # back under the other.
        self._conn.execute(
            'CREATE TABLE IF NOT EXISTS hash_cache ('
            'path TEXT, mode TEXT, size INTEGER, mtime REAL, digest TEXT, '
            'PRIMARY KEY (path, mode))'
        )
        self._conn.commit()

    def _ensure_connected(self) -> None:
        # On Linux, deleting a file a process still has open doesn't fail - the
        # process keeps writing into the now-unlinked, invisible-on-disk inode until
        # it closes/reopens the connection. If the user deletes the cache file (e.g.
        # to reset it) while Caja keeps running, reconnect so writes go to a real,
        # visible file again instead of a ghost one nothing else can see.
        if not os.path.exists(self.db_path):
            self._conn.close()
            self._connect()

    def get(self, path: str, mode: Mode, size: int, mtime: float) -> bytes | None:
        self._ensure_connected()
        row = self._conn.execute(
            'SELECT size, mtime, digest FROM hash_cache WHERE path = ? AND mode = ?',
            (path, mode),
        ).fetchone()
        if row is None:
            return None
        cached_size, cached_mtime, digest_hex = row
        if cached_size != size or cached_mtime != mtime:
            return None
        return bytes.fromhex(digest_hex)

    def has_any_entry(self, path: str) -> bool:
        # Used to tell "never colored before" from "colored under a different mode
        # or an older version of this file" - the latter means whatever's currently
        # displayed is stale and about to change, which callers use to show a
        # pending indicator immediately instead of waiting to see if it's slow.
        self._ensure_connected()
        row = self._conn.execute('SELECT 1 FROM hash_cache WHERE path = ? LIMIT 1', (path,)).fetchone()
        return row is not None

    def put(self, path: str, mode: Mode, size: int, mtime: float, digest: bytes) -> None:
        self._ensure_connected()
        self._conn.execute(
            'INSERT OR REPLACE INTO hash_cache (path, mode, size, mtime, digest) VALUES (?, ?, ?, ?, ?)',
            (path, mode, size, mtime, digest.hex()),
        )
        self._conn.commit()

    def prune_missing(self) -> int:
        self._ensure_connected()
        paths = {row[0] for row in self._conn.execute('SELECT DISTINCT path FROM hash_cache')}
        missing = [path for path in paths if not os.path.exists(path)]
        if missing:
            self._conn.executemany('DELETE FROM hash_cache WHERE path = ?', [(path,) for path in missing])
            self._conn.commit()
        return len(missing)

    def close(self) -> None:
        self._conn.close()


def compute_file_hash(path: str, size: int, mtime: float, mode: Mode, cache: HashCache) -> bytes:
    cached = cache.get(path, mode, size, mtime)
    if cached is not None:
        return cached
    digest = compute_digest(path, size, mode)
    cache.put(path, mode, size, mtime, digest)
    return digest
