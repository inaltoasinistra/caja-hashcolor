#!/usr/bin/env python3
import os
import tempfile
import unittest
from pathlib import Path

import gi

gi.require_version('Caja', '2.0')
gi.require_version('Gio', '2.0')
gi.require_version('Gtk', '3.0')

import config as config_module  # noqa: E402
import hash_color  # noqa: E402
import hashing  # noqa: E402
import palette  # noqa: E402


class FakeAsyncFullHash:
    """Stand-in for hashing.AsyncFullHash: lets tests control exactly when a file's
    hash "completes" (via .complete()), instead of needing a real GLib main loop to
    pump real (or even fake) async I/O - keeping these tests fast and deterministic."""

    instances: list['FakeAsyncFullHash'] = []

    def __init__(self, path: str, cancellable: object, on_complete: object, on_error: object) -> None:
        self.path = path
        self.on_complete = on_complete
        self.on_error = on_error
        FakeAsyncFullHash.instances.append(self)

    def complete(self, digest: bytes) -> None:
        self.on_complete(digest)


class MockLocation:
    def __init__(self, path: str) -> None:
        self._path = path

    def get_path(self) -> str:
        return self._path


class MockFile:
    def __init__(self, path: str) -> None:
        self._path = path
        self.emblems: list[str] = []

    def get_location(self) -> MockLocation:
        return MockLocation(self._path)

    def add_emblem(self, name: str) -> None:
        self.emblems.append(name)

    def invalidate_extension_info(self) -> None:
        pass


class TestUpdateFileInfoFull(unittest.TestCase):
    tmpdir: str
    test_dir: str
    ext: hash_color.HashColorExtension
    real_async_full_hash: type

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.test_dir = os.path.join(self.tmpdir, 'testdir')
        os.makedirs(self.test_dir)

        self.real_async_full_hash = hashing.AsyncFullHash
        hashing.AsyncFullHash = FakeAsyncFullHash
        FakeAsyncFullHash.instances = []

        # Fresh module-level state per test: these are shared globals in hash_color,
        # not per-instance, so a prior test's leftover queue/cache/handles must never
        # leak into the next one.
        hash_color._cache = hashing.HashCache(os.path.join(self.tmpdir, 'cache.db'))
        hash_color._known_files.clear()
        hash_color._operations.clear()
        hash_color._queued_handles.clear()
        hash_color._skip_handles.clear()
        hash_color._handle_paths.clear()
        hash_color._path_handles.clear()
        hash_color._queue = hashing.SerialQueue()

        config_module.CONFIG_DIR = Path(self.tmpdir)
        config_module.CONFIG_PATH = config_module.CONFIG_DIR / 'config.json'

        self.ext = hash_color.HashColorExtension()

    def tearDown(self) -> None:
        hashing.AsyncFullHash = self.real_async_full_hash
        hash_color._cache.close()

    def _make_file(self, name: str, size: int = 1024) -> MockFile:
        path = os.path.join(self.test_dir, name)
        with open(path, 'wb') as f:
            f.write(os.urandom(size))
        return MockFile(path)

    def _dispatch(self, file: MockFile) -> object:
        return self.ext.update_file_info_full(object(), object(), object(), file)

    def test_only_the_active_file_shows_computing_emblem(self):
        """Regression test: switching a directory's mode with several files needing
        rehashing must show the computing placeholder only for the one file whose
        hash is genuinely running right now - not for every file that needs it."""
        config_module.set_mode_for_directory(self.test_dir, 'precise')
        files = [self._make_file(f'file{i}.bin') for i in range(3)]
        for f in files:
            self._dispatch(f)

        self.assertEqual(files[0].emblems[-1], hash_color.COMPUTING_EMBLEM_NAME)
        self.assertEqual(files[1].emblems[-1], palette.CLEAR_EMBLEM_NAME)
        self.assertEqual(files[2].emblems[-1], palette.CLEAR_EMBLEM_NAME)
        self.assertEqual(len(FakeAsyncFullHash.instances), 1)

    def test_queued_file_never_shows_the_stale_color(self):
        """Regression test: a file with a cached hash under a different mode must
        never keep showing that stale color while its own new-mode hash is merely
        queued behind another file, not yet started."""
        stale_digest = b'\x00' * 32
        f = self._make_file('file0.bin')
        st = os.stat(f._path)
        hash_color._cache.put(f._path, 'fast', st.st_size, st.st_mtime, stale_digest)
        stale_emblem = palette.hash_to_emblem_name(stale_digest)

        config_module.set_mode_for_directory(self.test_dir, 'precise')
        blocker = self._make_file('blocker.bin')
        self._dispatch(blocker)  # occupies the queue so file0 below is merely queued

        self._dispatch(f)
        self.assertNotIn(stale_emblem, f.emblems)
        self.assertEqual(f.emblems[-1], palette.CLEAR_EMBLEM_NAME)

    def test_sequential_handoff_shows_computing_for_the_new_active_file(self):
        """The queue really does hand off one at a time: once the active file's hash
        finishes, the next queued file (and only that one) becomes active and shows
        computing."""
        config_module.set_mode_for_directory(self.test_dir, 'precise')
        files = [self._make_file(f'file{i}.bin') for i in range(3)]
        for f in files:
            self._dispatch(f)

        FakeAsyncFullHash.instances[0].complete(b'\x01' * 32)
        for f in files:
            self._dispatch(f)

        self.assertNotEqual(files[0].emblems[-1], hash_color.COMPUTING_EMBLEM_NAME)
        self.assertNotEqual(files[0].emblems[-1], palette.CLEAR_EMBLEM_NAME)
        self.assertEqual(files[1].emblems[-1], hash_color.COMPUTING_EMBLEM_NAME)
        self.assertEqual(files[2].emblems[-1], palette.CLEAR_EMBLEM_NAME)

    def test_repeated_dispatch_of_an_in_flight_file_does_not_start_a_second_hash(self):
        """The dedup guard (_path_handles): re-querying a file that's already queued
        or running (e.g. an unrelated Caja refresh, or job() calling
        invalidate_extension_info() when it starts) must not queue a redundant
        second hash job for the same path.

        Checks the queue's own pending count, not just how many hashes have started:
        a weaker version of this test that only checked
        len(FakeAsyncFullHash.instances) passed even with the dedup guard removed,
        because the redundant jobs it allowed just sat in _queue._pending without
        starting (the queue was still busy with the first, genuine job) - they were
        real duplicate work waiting to run, just not yet visible in that count."""
        config_module.set_mode_for_directory(self.test_dir, 'precise')
        f = self._make_file('file0.bin')
        self._dispatch(f)
        self.assertEqual(len(FakeAsyncFullHash.instances), 1)
        self.assertEqual(len(hash_color._queue._pending), 0)

        self._dispatch(f)
        self._dispatch(f)
        self.assertEqual(len(FakeAsyncFullHash.instances), 1)
        self.assertEqual(len(hash_color._queue._pending), 0)


if __name__ == '__main__':
    unittest.main()
