#!/usr/bin/env python3
# Caja extension: colors each file's icon with an emblem deterministically derived
# from its content hash. Off by default in every directory; each directory has its
# own independent Fast/Precise/off setting, toggled from the "Visual hash" tab in a
# file or folder's Properties dialog (Off/Fast/Precise radio buttons).
#
# Install (this file, config.py, hashing.py and palette.py must sit together):
#   1. python3 generate_emblems.py            # renders emblems/hashcolor-NN.png once
#   2. mkdir -p ~/.local/share/caja-python/extensions
#      ln -sfn "$PWD"/*.py "$PWD"/emblems ~/.local/share/caja-python/extensions/
#   3. caja -q && caja                        # restart Caja to load the extension
#
# Caja's Python bindings have no single "refresh everything" call, but
# Caja.FileInfo.invalidate_extension_info() asks Caja to re-query providers for one
# specific file. Toggling a directory's setting calls it for every file from that
# directory this extension has seen so far in this session (tracked in _known_files
# below), so visible icons in that directory update immediately; files never yet
# viewed just pick up the current setting the first time they're displayed.
#
# Hashing uses GIO's async I/O (hashing.AsyncFullHash), not a background OS thread:
# spawning a real thread from inside a live Caja process was found to hang after
# its first blocking call (reproduced with a trivial sleep loop with no Caja API
# calls involved at all, while the identical thread ran fine standalone and inside
# a bare Gtk.main() loop) - caja-python's C bridge does not appear to keep the GIL
# available to threads it didn't itself create. A plain synchronous read avoided
# that hang but blocked Caja's UI on large/many files, which matters a lot on a
# network mount where a single read() can itself take real time. GIO's async I/O
# does the actual work without blocking the main loop and without a second thread.
#
# Files are hashed one at a time (hashing.SerialQueue), not all at once: many
# concurrent async reads (e.g. opening a directory full of large network files)
# would otherwise all compete for the main loop's attention together, which is
# just as capable of making the UI feel sluggish as a single blocking call, only
# spread out. Only one file's hash is ever in flight; the rest wait their turn.
#
# update_file_info_full() always resolves synchronously (Caja.OperationResult never
# returns IN_PROGRESS): rather than holding the Caja-given handle open until the hash
# finishes, it shows whatever's true *right now* - the real color (cache hit), a
# computing placeholder (a hash for this file is genuinely running right now), or a
# neutral placeholder (queued behind another file, not yet its turn) - and queues the
# actual hash in the background. When that background hash's state changes (starts
# running, or finishes), it calls file.invalidate_extension_info() to prompt Caja to
# ask again, and the fresh call reflects the new state. _path_handles is the dedup
# guard that stops a fresh call for a file already in flight from queuing a second,
# redundant hash for the same path. This also means Caja never calls cancel_update()
# on us in practice (it only ever sees already-resolved queries) - in-flight hashes
# are instead cancelled by our own bookkeeping, when a directory's setting changes
# mid-hash (_cancel_pending_for_directory()) or after ASYNC_HASH_TIMEOUT_MS.

import os
from typing import Callable

import gi

gi.require_version('Caja', '2.0')
gi.require_version('Gio', '2.0')
gi.require_version('Gtk', '3.0')

from gi.repository import Caja, Gio, GLib, GObject, Gtk  # noqa: E402

import config
import hashing
import palette

EMBLEM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emblems')
CACHE_PATH = hashing.DEFAULT_CACHE_PATH
COMPUTING_EMBLEM_NAME = 'emblem-synchronizing'  # stock icon, already shipped with the icon theme
# A full hash (Precise mode, or Fast mode on a small file) has no built-in size cap,
# unlike Fast mode's sampled hash on large files (always <= 500KB read). Since
# SerialQueue only ever runs one hash at a time, one huge file over a slow (e.g.
# network-mounted) connection taking minutes would block every other file in the
# same directory from updating at all for that whole time - looking like the
# directory is frozen. Cancelling it after a generous timeout, the same way
# disabling the directory's mode already does, keeps the queue moving.
ASYNC_HASH_TIMEOUT_MS = 30_000

_cache = hashing.HashCache(CACHE_PATH)
_cache.prune_missing()
config.prune_missing_dirs()
_known_files: dict[str, object] = {}
_queue = hashing.SerialQueue()
_operations: dict[object, Gio.Cancellable] = {}  # handle -> cancellable, for actively-running hashes
_queued_handles: set = set()  # handles submitted to _queue but not yet started
_skip_handles: set = set()  # queued handles to discard without hashing once their turn comes
_handle_paths: dict[object, str] = {}  # handle -> path, so cancellation can be scoped to one directory
_path_handles: dict[str, object] = {}  # path -> the one handle currently queued or running for it (dedup guard)

Gtk.IconTheme.get_default().append_search_path(EMBLEM_DIR)


def _resolves_instantly(path: str, mode: str | None) -> bool:
    """Whether update_file_info_full() would resolve this file synchronously (a
    cache hit, or one of its early-return cases) rather than queuing a hash for it.
    Mirrors that method's own early checks, kept separate since this only needs a
    yes/no answer, not the stat/cached values themselves."""
    if mode is None or not os.path.isfile(path):
        return True
    try:
        stat = os.stat(path)
    except OSError:
        return True
    return _cache.get(path, mode, stat.st_size, stat.st_mtime) is not None


def _refresh_known_files(directory: str) -> None:
    mode = config.get_mode_for_directory(directory, config.load_config())
    immediate = []
    deferred = []
    for path, file in _known_files.items():
        if _normalize_directory(os.path.dirname(path)) != directory:
            continue
        # Files that resolve instantly (cache hit, or nothing to hash at all) should
        # visibly update right away instead of being invalidated in arbitrary order
        # alongside files that'll sit in the hash queue for a while.
        (immediate if _resolves_instantly(path, mode) else deferred).append(file)
    for file in immediate + deferred:
        file.invalidate_extension_info()


def _cancel_pending_for_directory(directory: str) -> None:
    for handle, path in list(_handle_paths.items()):
        if _normalize_directory(os.path.dirname(path)) != directory:
            continue
        cancellable = _operations.get(handle)
        if cancellable is not None:
            cancellable.cancel()
        elif handle in _queued_handles:
            _queued_handles.discard(handle)
            _skip_handles.add(handle)


def _set_directory_mode(directory: str, mode: str | None) -> None:
    config.set_mode_for_directory(directory, mode)
    if mode is None:
        _cancel_pending_for_directory(directory)
    _refresh_known_files(directory)


def _normalize_directory(directory: str | None) -> str | None:
    # Directory strings get derived differently depending on which Caja callback is
    # asking (a folder's own location vs. a file's parent location vs.
    # os.path.dirname() of a file's path) - without normalizing, a trailing slash or
    # redundant path segment could make what's logically the same directory compare
    # unequal between them, silently losing a setting written under one form when
    # looked up under another.
    return None if directory is None else os.path.normpath(directory)


def _parent_directory_of(file: object) -> str | None:
    parent_location = file.get_parent_location()
    if parent_location is None:
        return None
    return _normalize_directory(parent_location.get_path())


class HashColorExtension(GObject.GObject, Caja.InfoProvider, Caja.PropertyPageProvider):
    def update_file_info_full(self, provider: object, handle: object, closure: object, file: object) -> object:
        path = file.get_location().get_path()
        if path is not None:
            _known_files[path] = file

        if path is None or not os.path.isfile(path):
            return Caja.OperationResult.COMPLETE

        directory = _normalize_directory(os.path.dirname(path))
        mode = config.get_mode_for_directory(directory, config.load_config())
        if mode is None:
            # Explicitly add a transparent emblem rather than nothing: Caja has no
            # "remove emblem" call, and we've confirmed a cycle that adds nothing at
            # all leaves whatever was shown by a previous cycle untouched - a stale
            # color would otherwise linger forever after disabling.
            file.add_emblem(palette.CLEAR_EMBLEM_NAME)
            return Caja.OperationResult.COMPLETE

        try:
            stat = os.stat(path)
        except OSError:
            return Caja.OperationResult.COMPLETE

        cached = _cache.get(path, mode, stat.st_size, stat.st_mtime)
        if cached is not None:
            file.add_emblem(palette.hash_to_emblem_name(cached))
            return Caja.OperationResult.COMPLETE

        # A hash for this exact file may already be queued or actively running - this
        # call could just be Caja re-checking the same pending file (our own
        # invalidate_extension_info() calls below, or an unrelated refresh) rather
        # than a fresh request. Reflect the current state without starting a second,
        # redundant hash for the same path: computing if it's the one actively
        # running right now, or a neutral placeholder if it's merely still queued
        # behind another file - never the stale color from before, and never
        # "computing" for a file that isn't really being worked on yet.
        existing_handle = _path_handles.get(path)
        if existing_handle is not None:
            if existing_handle in _operations:
                file.add_emblem(COMPUTING_EMBLEM_NAME)
            else:
                file.add_emblem(palette.CLEAR_EMBLEM_NAME)
            return Caja.OperationResult.COMPLETE

        _path_handles[path] = handle

        def job(done: Callable[[], None]) -> None:
            _queued_handles.discard(handle)
            if handle in _skip_handles:
                _skip_handles.discard(handle)
                _handle_paths.pop(handle, None)
                _path_handles.pop(path, None)
                done()
                return

            def finish(digest: bytes | None) -> None:
                # `done()` runs in `finally` so the queue always advances, even if
                # something below it raises (e.g. the cache write hitting a read-only
                # or locked database) - one file's unexpected failure must never
                # permanently stall every file queued after it for the rest of the
                # Caja session. Any such exception still propagates after done() runs,
                # so it's not silently swallowed - PyGObject logs it as normal.
                try:
                    _operations.pop(handle, None)
                    _handle_paths.pop(handle, None)
                    _path_handles.pop(path, None)
                    if digest is not None:
                        _cache.put(path, mode, stat.st_size, stat.st_mtime, digest)
                        # A fresh cycle's own checks (cache hit, or the mode==None
                        # branch) correctly pick the right thing to show, even if
                        # this directory's setting changed while the hash was
                        # in flight.
                        file.invalidate_extension_info()
                    # Deliberately not invalidating on failure (digest is None): a
                    # fresh cycle would just retry the same failing hash indefinitely
                    # for a persistently-broken file.
                finally:
                    done()

            def on_error(exc: GLib.Error) -> None:
                _operations.pop(handle, None)
                _handle_paths.pop(handle, None)
                _path_handles.pop(path, None)
                if hashing.is_cancelled_error(exc):
                    # Covers both a directory's setting changing mid-hash (already
                    # followed by _refresh_known_files(), making this a harmless extra
                    # call) and the ASYNC_HASH_TIMEOUT_MS watchdog, which has nothing
                    # else invalidating this file - without this, a file that times out
                    # keeps showing the "synchronizing" emblem forever (nothing ever
                    # asks Caja to re-check it), even once _path_handles no longer
                    # considers its hash to be running.
                    file.invalidate_extension_info()
                    done()  # no completion expected
                    return
                finish(None)

            def cancel_if_still_running() -> bool:
                cancellable = _operations.get(handle)
                if cancellable is not None:
                    cancellable.cancel()
                return False  # one-shot: don't reschedule this timeout

            if mode == 'fast' and stat.st_size > hashing.FAST_MODE_FULL_HASH_THRESHOLD_BYTES:
                try:
                    digest = hashing.compute_digest(path, stat.st_size, mode)
                except OSError:
                    digest = None
                finish(digest)
                return

            try:
                cancellable = Gio.Cancellable()
                _operations[handle] = cancellable
                hashing.AsyncFullHash(path, cancellable, finish, on_error)
                GLib.timeout_add(ASYNC_HASH_TIMEOUT_MS, cancel_if_still_running)
                # This file's hash has now genuinely started (its turn in the serial
                # queue) - ask Caja to re-check it so a fresh cycle shows the
                # computing emblem, replacing whatever neutral placeholder it was
                # showing while merely queued (the dedup check above finds this
                # handle in _operations now and shows computing, without starting a
                # second hash for the same path).
                file.invalidate_extension_info()
            except Exception:
                _operations.pop(handle, None)
                _handle_paths.pop(handle, None)
                _path_handles.pop(path, None)
                finish(None)

        _handle_paths[handle] = path
        _queued_handles.add(handle)
        _queue.submit(job)

        # If the queue was idle, job() already ran synchronously above (including,
        # for a large Fast-mode file, completing entirely and popping _path_handles
        # itself) - reflect whatever's true right now rather than assuming this file
        # is still merely queued.
        if path not in _path_handles:
            return Caja.OperationResult.COMPLETE
        if handle in _operations:
            file.add_emblem(COMPUTING_EMBLEM_NAME)
        else:
            file.add_emblem(palette.CLEAR_EMBLEM_NAME)
        return Caja.OperationResult.COMPLETE

    def cancel_update(self, provider: object, handle: object) -> None:
        # Expected to be unreachable in practice: update_file_info_full() always
        # resolves synchronously now (see its own comment), so Caja never has a
        # reason to think a handle from us is still outstanding. Kept for interface
        # completeness and as a defensive fallback.
        cancellable = _operations.get(handle)
        if cancellable is not None:
            cancellable.cancel()
        else:
            _queued_handles.discard(handle)
            _skip_handles.add(handle)

    def get_property_pages(self, files: list) -> list:
        # A Properties-page tab, not a context menu: Caja's context menu doesn't
        # reliably reflect a just-toggled state until some unrelated refresh happens,
        # while a Properties-page tab is rebuilt from scratch every time the dialog
        # opens, so it can't suffer the same staleness.
        #
        # Named get_property_pages, not get_pages: GObject Introspection's
        # dir(Caja.PropertyPageProvider) reports "get_pages" as the interface's
        # virtual function, but caja-python's hand-written C glue actually looks up
        # a Python method called get_property_pages (confirmed against the shipped
        # /usr/share/doc/python-caja/examples/md5sum-property-page.py) - the two
        # names diverge, and only the second one is ever actually called.
        if len(files) != 1:
            return []
        target = files[0]
        if target.is_directory():
            directory = _normalize_directory(target.get_location().get_path())
        else:
            directory = _parent_directory_of(target)
        if directory is None:
            return []

        active_mode = config.get_mode_for_directory(directory, config.load_config())

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(12)

        explanation = Gtk.Label(
            label=(
                'Colors each file’s icon with an emblem derived from its content, '
                'so identical or near-identical files are easy to spot at a glance.\n\n'
                '• Fast — for large files, hashes only the first and last '
                '250 KB instead of the whole file. Quick even on slow/network drives, '
                'but two different large files could rarely be shown as identical if '
                'they only differ in the untouched middle.\n'
                '• Precise — always hashes the entire file. No blind spot, '
                'but slower, especially over a slow or network connection.'
            )
        )
        explanation.set_line_wrap(True)
        explanation.set_max_width_chars(50)
        explanation.set_xalign(0)
        box.pack_start(explanation, False, False, 0)
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 6)

        off_button = Gtk.RadioButton.new_with_label(None, 'Off')
        fast_button = Gtk.RadioButton.new_with_label_from_widget(off_button, 'Fast')
        precise_button = Gtk.RadioButton.new_with_label_from_widget(off_button, 'Precise')
        buttons_by_mode = {None: off_button, 'fast': fast_button, 'precise': precise_button}
        buttons_by_mode[active_mode].set_active(True)

        def on_toggled(button: Gtk.RadioButton, mode: str | None) -> None:
            if button.get_active():
                _set_directory_mode(directory, mode)

        off_button.connect('toggled', on_toggled, None)
        fast_button.connect('toggled', on_toggled, 'fast')
        precise_button.connect('toggled', on_toggled, 'precise')

        box.pack_start(off_button, False, False, 0)
        box.pack_start(fast_button, False, False, 0)
        box.pack_start(precise_button, False, False, 0)
        box.show_all()

        label = Gtk.Label(label='Visual hash')
        return [Caja.PropertyPage(name='HashColor::property_page', label=label, page=box)]
