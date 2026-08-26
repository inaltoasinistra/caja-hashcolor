# Developer documentation

Everything about working on caja-hashcolor: where an install puts each piece,
how to build and test it, and why the non-obvious parts are the way they are.
[README.md](README.md) is the documentation for people *using* the extension.

## Where things live

| What                | User install (`make install`)            | System install (`sudo make install`) |
|---------------------|------------------------------------------|--------------------------------------|
| Extension           | `~/.local/share/caja-python/extensions/` | `/usr/share/caja-python/extensions/` |
| Emblems             | `~/.local/share/caja-hashcolor/emblems/` | `/usr/share/caja-hashcolor/emblems/` |
| Per-folder settings | `~/.config/caja-hashcolor/config.json`   | same (per user)                      |
| Color cache         | `~/.cache/caja-hashcolor/cache.db`       | same (per user)                      |

The paths above are the XDG defaults. `caja_hashcolor/xdg.py` is the single
place any of them is resolved, so `XDG_DATA_HOME`, `XDG_DATA_DIRS`,
`XDG_CONFIG_HOME` and `XDG_CACHE_HOME` all move the corresponding location - a
value that is set but not absolute is ignored, as the basedir spec requires.

## Building and testing

```
make test      # unit tests, no Caja process needed
make link      # symlink install, so edits are live after `caja -q`
make emblems   # re-render emblems/ after changing palette.py (needs Pillow)
caja -q        # Caja does not hot-reload; restart it after *any* change
```

After `make emblems`, run `make install-emblems` to copy the new files into the
installed emblem directory (`make link` does that too), then restart Caja - a
running Caja keeps serving icons from the listing it scanned at startup, so a
freshly added emblem would otherwise show up as a missing icon.

## Module layout

`hash_color.py` is the only module Caja loads as an extension; everything else
lives in the `caja_hashcolor` package next to it. That matters because
caja-python inserts the extensions directory at `sys.path[0]` and imports every
top-level `.py` it finds there — flat modules named `config` or `hashing` would
be visible to, and could shadow imports in, every other extension on the
system.

`caja_hashcolor/xdg.py` resolves every path outside the install prefix - the
settings file, the digest cache and the installed emblems. Keeping the three in
one module is what stops them drifting apart on how much of the basedir spec
they honour, which is exactly what had happened before it existed.

## Where the emblems are installed

The emblems deliberately go in a private directory rather than into
`share/icons/hicolor/32x32/emblems/`. Caja's manual emblem chooser (the
**Emblems** tab of the Properties dialog) lists the icon theme's `Emblems`
context, so installing there would add all 480 emblem files to a list of
about thirty — and a hash color means nothing when you pick it by hand. Registering
the directory with `Gtk.IconTheme.append_search_path()` instead makes the
emblems *unthemed*: resolvable by name, invisible to that list.

## Hash modes

- **Fast** (default): files ≤ 1MB get a full SHA-256 hash; larger files are
  hashed from their first 250KB, last 250KB, and the file size - no middle
  sampling. Two large files differing only somewhere in between will collide
  to the same color (the documented trade-off). Deliberately head/tail-only,
  not scattered small samples across the whole file: a fixed byte budget
  becomes a vanishing fraction of a large file, so scattered sampling is a
  weak bet, while real formats concentrate the content most likely to change
  at the boundaries - archive/container indices at the end, EXIF/XMP/thumbnail
  metadata at the start, interrupted-write corruption typically hitting the
  tail.
- **Precise**: always hashes the entire file, regardless of size. No sampling
  collisions, but reading a large file - especially over a network mount -
  takes real time no matter how it's read; the async design keeps Caja's UI
  responsive while that happens, it doesn't make the read itself faster.

## Caching and settings

Digests are cached in `~/.cache/caja-hashcolor/cache.db` (SQLite), keyed by
`(path, mode)` and invalidated on size/mtime change, since Fast and Precise
disagree on large files and must never share a cached digest. If that file
gets deleted (e.g. to reset the cache) the extension transparently reconnects
and recreates it on the next hash - no restart needed.

Per-directory settings live in `~/.config/caja-hashcolor/config.json` as two
plain path lists, `fast_dirs` and `precise_dirs` (a directory is in at most
one of the two). Directories that no longer exist are pruned from both lists
once per Caja session, alongside the equivalent cache cleanup for deleted
files, so the lists don't grow forever as directories come and go.

## Runtime behaviour

- **GIO async I/O, not a background thread.** Caja's documented way to avoid
  blocking its UI on slow work is `update_file_info_full()` returning
  `Caja.OperationResult.IN_PROGRESS` and completing later from a background
  thread. In practice, spawning a real OS thread from inside a live Caja
  process hangs after its first blocking call (reproduced with a trivial
  sleep loop that made no Caja API calls at all, while the same thread ran
  fine standalone and inside a bare `Gtk.main()` loop) - `caja-python`'s C
  bridge doesn't appear to keep the GIL available to threads it didn't spawn
  itself. Reading the whole file in one plain synchronous call avoided the
  hang but blocked Caja's UI, badly so on a network mount where a single
  `read()` can itself take real time. `hashing.AsyncFullHash` reads the file
  using `Gio.File.read_async()` / `GFileInputStream.read_bytes_async()`
  instead: the actual I/O happens inside GIO's own machinery, never inside a
  thread this extension spawns, and every chunk's completion is delivered as
  a normal main-loop callback - so Caja's UI is never blocked, without a
  second thread ever existing.
- **One file hashed at a time (`hashing.SerialQueue`).** Even with async I/O,
  opening a directory full of large network files would otherwise start many
  concurrent read chains at once, all competing for the main loop's attention
  together - which can feel just as sluggish as a single blocking call, only
  spread out. Every hash job is submitted to a `SerialQueue` instead: only one
  file's read is ever in flight, the rest wait their turn. Known trade-off:
  switching a directory with many large files (e.g. a media library) to
  Precise mode queues a full-content hash of every file, one at a time - for
  a genuinely huge directory this can take a long time to fully recolor,
  since nothing speeds that up beyond how fast one file at a time can be read.
- **Cancellation.** An in-progress or queued hash is aborted, not left to run
  to completion uselessly, when either Caja says it's no longer needed
  (`cancel_update()` - e.g. the user navigated to a different directory) or
  that directory's setting changes mid-hash (`_cancel_pending_for_directory()`
  - scoped to just that directory's in-flight/queued handles, tracked via
  `_handle_paths`, so changing one directory's setting doesn't touch hashing
  in progress for any other). A hash that finishes anyway before its
  cancellation is noticed re-checks the directory's live setting before
  adding an emblem, so a stale completion can't sneak a color back on after
  that directory's setting has changed.
- **"Synchronizing" progress emblem, and never showing it for the wrong
  file.** Caja's extension API has no way to *remove* an emblem, only add
  one, and `update_file_info_full()` always resolves synchronously (never
  returns `IN_PROGRESS`) - every call shows whatever's true *right now* and
  queues the real hash in the background. `_path_handles` (path -> the one
  handle currently queued or running for it) is what makes that safe: a file
  shows the "synchronizing" emblem only while its own hash is the one
  actually running (`handle in _operations`), a neutral cleared placeholder
  while merely queued behind another file, and the real color once cached -
  never the *previous* mode's stale color, and never "synchronizing" for a
  file that isn't genuinely being worked on. When the background hash
  changes state (starts running, or finishes), it calls
  `file.invalidate_extension_info()` to prompt Caja to ask again; the dedup
  check against `_path_handles` stops that fresh call from queuing a second,
  redundant hash for the same path. Two earlier, narrower bugs led here: first,
  adding both the computing emblem and the real color within the same
  still-open cycle left the computing emblem stuck forever (Caja has no way
  to know the cycle should be superseded); fixed by never doing that, always
  resolving a cycle with exactly one emblem. Second, showing the computing
  emblem synchronously for *every* file needing a rehash (regardless of
  whether the queue had actually reached it yet) meant switching a directory
  with many files to Precise mode showed "synchronizing" on all of them at
  once, even though only one hash was really running - fixed by the
  `_path_handles` active/queued distinction above.
- **Clearing emblems on disable.** For the same reason - no "remove emblem"
  call - a cycle that adds nothing at all leaves a previous color exactly
  where it was, so simply skipping `add_emblem()` when a directory is
  disabled doesn't clear the stale color. `palette.CLEAR_EMBLEM_NAME` is a
  fully transparent image added explicitly whenever a directory's mode is
  `None`: the cycle still adds *something*, which replaces the prior state,
  but nothing visible actually renders.
- **Directory path normalization.** The directory string used for config
  lookups gets derived three different ways depending on which Caja callback
  is asking - a folder's own location, a file's parent location, or
  `os.path.dirname()` of a file's path. Without normalizing all three with
  `os.path.normpath()`, a trailing slash or redundant path segment could make
  what's logically the same directory compare unequal between them, silently
  losing/hiding a setting written under one form when looked up under
  another (the intermittent "checkmark sometimes lost" symptom).
- **Config write robustness.** `config.save_config()` writes to a temp file
  and atomically renames it into place, so a crash or kill mid-write (e.g.
  during Caja restart cycles while developing/testing) can never leave
  `config.json` truncated. `load_config()` also treats a corrupt/unreadable
  file as "no settings" rather than raising, in case corruption ever happens
  anyway.
- **Palette**: 7 explicit (not evenly-spaced) hues at full saturation/mid
  lightness - no need to bias toward light colors, unlike a text background,
  since nothing is drawn on top of an emblem. Hues are hand-placed, not a
  uniform wheel, because raw hue-degree distance doesn't track perceived
  difference (an earlier evenly-spaced attempt put chartreuse/green next to
  cyan, which read as near-identical despite clearing the angular threshold).
  Combinations are filtered by a minimum hue-distance rule, with an
  adjacency-only relaxation for the two 4-slice pie styles (only slices that
  actually touch need to contrast). See `palette.py`'s module docstring-style
  comments and `test_palette.py` for the exact rules and their regression
  tests.
