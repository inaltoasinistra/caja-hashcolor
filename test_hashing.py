#!/usr/bin/env python3
import hashlib
import os
import tempfile
import unittest

import gi

gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib  # noqa: E402

from hashing import (
    ASYNC_READ_CHUNK_BYTES,
    FAST_MODE_FULL_HASH_THRESHOLD_BYTES,
    HEAD_ANCHOR_BYTES,
    TAIL_ANCHOR_BYTES,
    AsyncFullHash,
    HashCache,
    SerialQueue,
    compute_digest,
    compute_file_hash,
    is_cancelled_error,
)


def write_file(path: str, data: bytes) -> None:
    with open(path, 'wb') as f:
        f.write(data)


def run_async_hash(path: str, cancellable: Gio.Cancellable | None = None) -> tuple[bytes | None, GLib.Error | None]:
    """Drives an AsyncFullHash to completion inside a bounded GLib main loop.
    Returns (digest, None) on success or (None, error) on failure/cancellation."""
    if cancellable is None:
        cancellable = Gio.Cancellable()
    loop = GLib.MainLoop()
    outcome: dict[str, object] = {}

    def on_complete(digest: bytes) -> None:
        outcome['digest'] = digest
        loop.quit()

    def on_error(exc: GLib.Error) -> None:
        outcome['error'] = exc
        loop.quit()

    AsyncFullHash(path, cancellable, on_complete, on_error)
    GLib.timeout_add_seconds(5, loop.quit)  # safety net: fail the test, don't hang, on a real bug
    loop.run()
    return outcome.get('digest'), outcome.get('error')


class TestComputeDigest(unittest.TestCase):
    tmp_dir: str

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()

    def test_small_file_matches_hashlib_regardless_of_mode(self):
        """Files at or below the threshold get a plain full hash in both modes."""
        data = b'small file contents'
        path = os.path.join(self.tmp_dir, 'small.bin')
        write_file(path, data)
        expected = hashlib.sha256(data).digest()
        self.assertEqual(compute_digest(path, len(data), 'fast'), expected)
        self.assertEqual(compute_digest(path, len(data), 'precise'), expected)

    def test_precise_mode_hashes_full_large_file(self):
        size = FAST_MODE_FULL_HASH_THRESHOLD_BYTES + 1
        data = os.urandom(size)
        path = os.path.join(self.tmp_dir, 'large.bin')
        write_file(path, data)
        self.assertEqual(compute_digest(path, size, 'precise'), hashlib.sha256(data).digest())

    def test_fast_and_precise_disagree_on_files_differing_only_in_the_untouched_middle(self):
        """Two large files sharing the same head/tail anchors but differing only in
        the untouched middle must collide under fast mode (the documented
        trade-off) but not under precise."""
        size = FAST_MODE_FULL_HASH_THRESHOLD_BYTES + 50_000  # above threshold: triggers the sampled path
        base = bytearray(os.urandom(size))
        variant = bytearray(base)
        middle_offset = HEAD_ANCHOR_BYTES + 25_000  # strictly inside the untouched middle
        variant[middle_offset] ^= 0xFF

        path_a = os.path.join(self.tmp_dir, 'a.bin')
        path_b = os.path.join(self.tmp_dir, 'b.bin')
        write_file(path_a, bytes(base))
        write_file(path_b, bytes(variant))

        self.assertEqual(compute_digest(path_a, size, 'fast'), compute_digest(path_b, size, 'fast'))
        self.assertNotEqual(compute_digest(path_a, size, 'precise'), compute_digest(path_b, size, 'precise'))

    def test_fast_mode_catches_change_in_true_head(self):
        size = FAST_MODE_FULL_HASH_THRESHOLD_BYTES + 50_000  # above threshold: triggers the sampled path
        base = bytearray(os.urandom(size))
        variant = bytearray(base)
        variant[0] ^= 0xFF  # the very first byte of the file

        path_a = os.path.join(self.tmp_dir, 'a.bin')
        path_b = os.path.join(self.tmp_dir, 'b.bin')
        write_file(path_a, bytes(base))
        write_file(path_b, bytes(variant))

        self.assertNotEqual(compute_digest(path_a, size, 'fast'), compute_digest(path_b, size, 'fast'))

    def test_fast_mode_catches_change_in_true_tail(self):
        """Regression test: the previous uniform-sampling scheme's last sample point
        was at the 90% mark, reading forward - it never actually reached the true
        end of the file, so a change to the very last byte went undetected."""
        size = FAST_MODE_FULL_HASH_THRESHOLD_BYTES + 50_000  # above threshold: triggers the sampled path
        base = bytearray(os.urandom(size))
        variant = bytearray(base)
        variant[-1] ^= 0xFF  # the very last byte of the file

        path_a = os.path.join(self.tmp_dir, 'a.bin')
        path_b = os.path.join(self.tmp_dir, 'b.bin')
        write_file(path_a, bytes(base))
        write_file(path_b, bytes(variant))

        self.assertNotEqual(compute_digest(path_a, size, 'fast'), compute_digest(path_b, size, 'fast'))


class TestAsyncFullHash(unittest.TestCase):
    tmp_dir: str

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()

    def test_matches_hashlib_for_small_file(self):
        data = b'small file contents'
        path = os.path.join(self.tmp_dir, 'small.bin')
        write_file(path, data)
        digest, error = run_async_hash(path)
        self.assertIsNone(error)
        self.assertEqual(digest, hashlib.sha256(data).digest())

    def test_matches_hashlib_across_multiple_async_reads(self):
        """A file spanning several ASYNC_READ_CHUNK_BYTES reads must still match a
        single-shot hash - proves the async read-and-append chain doesn't corrupt
        the digest by splitting/rejoining incorrectly at chunk boundaries."""
        size = ASYNC_READ_CHUNK_BYTES * 2 + 12345
        data = os.urandom(size)
        path = os.path.join(self.tmp_dir, 'multi_chunk.bin')
        write_file(path, data)
        digest, error = run_async_hash(path)
        self.assertIsNone(error)
        self.assertEqual(digest, hashlib.sha256(data).digest())

    def test_missing_file_reports_error_not_digest(self):
        digest, error = run_async_hash(os.path.join(self.tmp_dir, 'does_not_exist.bin'))
        self.assertIsNone(digest)
        self.assertIsNotNone(error)

    def test_cancelled_read_reports_cancelled_error(self):
        data = os.urandom(ASYNC_READ_CHUNK_BYTES * 4)
        path = os.path.join(self.tmp_dir, 'cancel_me.bin')
        write_file(path, data)
        cancellable = Gio.Cancellable()
        cancellable.cancel()  # pre-cancelled: aborts even the initial open

        digest, error = run_async_hash(path, cancellable)

        self.assertIsNone(digest)
        self.assertIsNotNone(error)
        self.assertTrue(is_cancelled_error(error))


class TestSerialQueue(unittest.TestCase):
    def test_single_job_runs_immediately(self):
        queue = SerialQueue()
        ran = []
        queue.submit(lambda done: (ran.append('a'), done()))
        self.assertEqual(ran, ['a'])

    def test_second_job_does_not_start_until_first_calls_done(self):
        """Proves jobs are strictly serialized: a second file's hashing must not
        begin while the first one is still in flight."""
        queue = SerialQueue()
        order = []
        held_done = {}

        def first(done):
            order.append('first-start')
            held_done['done'] = done  # deliberately not called yet

        def second(done):
            order.append('second-start')
            done()

        queue.submit(first)
        queue.submit(second)
        self.assertEqual(order, ['first-start'])

        held_done['done']()
        self.assertEqual(order, ['first-start', 'second-start'])

    def test_jobs_run_in_fifo_order(self):
        queue = SerialQueue()
        order = []
        for label in ('a', 'b', 'c'):
            queue.submit(lambda done, label=label: (order.append(label), done()))
        self.assertEqual(order, ['a', 'b', 'c'])


class TestHashCache(unittest.TestCase):
    tmp_dir: str
    cache: HashCache

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        self.cache = HashCache(os.path.join(self.tmp_dir, 'cache.db'))

    def tearDown(self) -> None:
        self.cache.close()

    def test_cache_miss_returns_none(self):
        self.assertIsNone(self.cache.get('/no/such/path', 'fast', 123, 456.0))

    def test_has_any_entry_false_when_never_cached(self):
        self.assertFalse(self.cache.has_any_entry('/no/such/path'))

    def test_has_any_entry_true_regardless_of_mode(self):
        """A file cached under 'fast' should count as having a previous entry even
        when checking ahead of a switch to 'precise' - it's used to detect "this
        file had some color shown, now stale", not to check a specific mode."""
        digest = hashlib.sha256(b'x').digest()
        self.cache.put('/some/path', 'fast', 10, 1000.0, digest)
        self.assertTrue(self.cache.has_any_entry('/some/path'))

    def test_cache_hit_returns_stored_digest(self):
        digest = hashlib.sha256(b'x').digest()
        self.cache.put('/some/path', 'fast', 10, 1000.0, digest)
        self.assertEqual(self.cache.get('/some/path', 'fast', 10, 1000.0), digest)

    def test_size_or_mtime_mismatch_is_a_miss(self):
        """A stale row (file modified since caching) must not be returned as a hit."""
        digest = hashlib.sha256(b'x').digest()
        self.cache.put('/some/path', 'fast', 10, 1000.0, digest)
        self.assertIsNone(self.cache.get('/some/path', 'fast', 10, 2000.0))
        self.assertIsNone(self.cache.get('/some/path', 'fast', 11, 1000.0))

    def test_fast_and_precise_are_stored_separately(self):
        fast_digest = hashlib.sha256(b'fast').digest()
        precise_digest = hashlib.sha256(b'precise').digest()
        self.cache.put('/some/path', 'fast', 10, 1000.0, fast_digest)
        self.cache.put('/some/path', 'precise', 10, 1000.0, precise_digest)
        self.assertEqual(self.cache.get('/some/path', 'fast', 10, 1000.0), fast_digest)
        self.assertEqual(self.cache.get('/some/path', 'precise', 10, 1000.0), precise_digest)

    def test_put_overwrites_previous_row_for_same_path_and_mode(self):
        old_digest = hashlib.sha256(b'old').digest()
        new_digest = hashlib.sha256(b'new').digest()
        self.cache.put('/some/path', 'fast', 10, 1000.0, old_digest)
        self.cache.put('/some/path', 'fast', 20, 2000.0, new_digest)
        row_count = self.cache._conn.execute(
            'SELECT COUNT(*) FROM hash_cache WHERE path = ? AND mode = ?', ('/some/path', 'fast')
        ).fetchone()[0]
        self.assertEqual(row_count, 1)
        self.assertEqual(self.cache.get('/some/path', 'fast', 20, 2000.0), new_digest)

    def test_survives_db_file_being_deleted_while_open(self):
        """If the user deletes the cache file (e.g. to reset it) while Caja keeps
        running, the next get/put must transparently reconnect to a fresh file on
        disk instead of silently continuing to write into the deleted, invisible
        one until Caja restarts."""
        digest = hashlib.sha256(b'x').digest()
        self.cache.put('/some/path', 'fast', 10, 1000.0, digest)

        os.remove(self.cache.db_path)

        self.assertIsNone(self.cache.get('/some/path', 'fast', 10, 1000.0))
        new_digest = hashlib.sha256(b'y').digest()
        self.cache.put('/some/path', 'fast', 10, 1000.0, new_digest)

        self.assertTrue(os.path.exists(self.cache.db_path))
        self.assertEqual(self.cache.get('/some/path', 'fast', 10, 1000.0), new_digest)

    def test_prune_missing_removes_only_nonexistent_paths(self):
        surviving_path = os.path.join(self.tmp_dir, 'exists.bin')
        write_file(surviving_path, b'data')
        digest = hashlib.sha256(b'x').digest()
        self.cache.put(surviving_path, 'fast', 4, 1000.0, digest)
        self.cache.put('/no/such/path', 'fast', 4, 1000.0, digest)

        removed_count = self.cache.prune_missing()

        self.assertEqual(removed_count, 1)
        self.assertEqual(self.cache.get(surviving_path, 'fast', 4, 1000.0), digest)
        self.assertIsNone(self.cache.get('/no/such/path', 'fast', 4, 1000.0))


class TestComputeFileHash(unittest.TestCase):
    tmp_dir: str
    cache: HashCache

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        self.cache = HashCache(os.path.join(self.tmp_dir, 'cache.db'))

    def tearDown(self) -> None:
        self.cache.close()

    def test_second_call_uses_cache_even_if_file_is_deleted(self):
        """Proves the second call didn't touch the filesystem: the file is gone."""
        path = os.path.join(self.tmp_dir, 'file.bin')
        write_file(path, b'contents')
        stat = os.stat(path)
        first = compute_file_hash(path, stat.st_size, stat.st_mtime, 'fast', self.cache)

        os.remove(path)

        second = compute_file_hash(path, stat.st_size, stat.st_mtime, 'fast', self.cache)
        self.assertEqual(first, second)


if __name__ == '__main__':
    unittest.main()
