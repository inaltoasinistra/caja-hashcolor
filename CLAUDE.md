# caja-hashcolor

Caja (MATE file manager) extension: colors each file's icon with an emblem
derived from its content hash, so identical/near-identical files are easy to
spot at a glance. Read `README.md` first for the full design - this file is
just orientation and gotchas for picking the project back up.

## Commands

- Run all tests: `make test` (= `python3 -m unittest discover -p "test_*.py"`)
- Run one test file: `python3 -m unittest test_hashing`
- Run one test case/method: `python3 -m unittest test_hashing.TestComputeDigest.test_fast_mode_small_file`
- Regenerate emblems after any `palette.py` change: `make emblems`, then
  `make install-emblems` to copy them into the icon theme.
- Install: `make install` (user, `~/.local`) or `sudo make install` (system,
  `/usr`). `make link` is the development install - it symlinks `hash_color.py`
  and the `caja_hashcolor/` package so edits are live after a Caja restart.
  `make uninstall` removes everything. See `README.md` for the full story.
- Reload after any code or emblem change: `caja -q` (auto-restarts on next
  `caja` open or folder navigation).

## Files

- `hash_color.py` - the actual Caja extension (`HashColorExtension`, a
  `Caja.InfoProvider` + `Caja.PropertyPageProvider`). Most of the real
  complexity lives here. It is deliberately the *only* top-level module:
  caja-python inserts the extensions directory at `sys.path[0]` and imports
  every top-level `.py` in it, so everything else lives in the
  `caja_hashcolor/` package beside it (flat `config`/`hashing`/`palette`
  modules would shadow those names for every other extension on the system).
- `caja_hashcolor/hashing.py` - pure hashing/caching logic: `compute_digest()`
  (Fast/Precise modes), `AsyncFullHash` (GIO async file reading), `SerialQueue`
  (one hash at a time), `HashCache` (SQLite, self-healing if the cache file is
  deleted).
- `caja_hashcolor/palette.py` - the color palette and `hash_to_emblem_name()`:
  maps a digest to one of ~480 pre-rendered emblem names (solid, and
  2/3/4/5/6-color combinations in band/pie layouts), all listed in
  `ALL_EMBLEMS`/`ALL_EMBLEM_NAMES` and indexed by `int.from_bytes(digest,
  'big') % len(ALL_EMBLEM_NAMES)` so every emblem has equal selection odds
  regardless of which color-count family it belongs to.
- `caja_hashcolor/config.py` - per-directory Fast/Precise/off setting, stored
  as two path lists in `~/.config/caja-hashcolor/config.json`.
- `Makefile` - the whole install story (see Commands above).
- `generate_emblems.py` - dev-time script (the only thing needing Pillow) that
  renders every reachable emblem name from `palette.py` to `emblems/*.png`. Run
  it after *any* change to `palette.py`. `test_emblems.py` guards the result:
  the shipped PNGs must match `ALL_EMBLEM_NAMES` exactly, since `make install`
  copies them into the icon theme by glob with no build step.
- `test_*.py` - real unit tests for everything except the Caja-glue parts of
  `hash_color.py` that need a live Caja process to matter (menu/property-page
  wiring). The queueing/display logic in `hash_color.py` itself *is* unit
  tested (`test_hash_color.py`), using a `FakeAsyncFullHash` to control hash
  completion deterministically without a real GLib main loop - see that
  file's docstring for the pattern.
- `TODO.md` - known follow-ups, read it before assuming something's finished.

## Things that will bite you if you forget them

- **Caja does not hot-reload.** After *any* code change, `caja -q` then
  reopen Caja (or just open a folder - it restarts automatically). It's a
  single process serving every Caja window for the user, so this affects all
  of them, not just a test one.
- **Regenerating emblems also needs a Caja restart**, separately from a code
  restart, *and* a `make install-emblems`: the emblems are installed into
  `share/icons/hicolor/32x32/emblems/` and resolved by bare name through
  `GtkIconTheme`, so a PNG that only exists in the repo's `emblems/` directory
  is invisible to Caja, and one added while Caja is running may still render as
  a broken icon until it restarts. (The extension used to
  `append_search_path()` the repo directory instead; that is gone.)
- **`Caja.PropertyPageProvider`'s real method name is `get_property_pages`,
  not `get_pages`.** `dir(Caja.PropertyPageProvider)` via GObject
  Introspection reports `get_pages` as the interface's virtual function, but
  `caja-python`'s hand-written C glue actually looks up `get_property_pages`
  by name - confirmed against the shipped
  `/usr/share/doc/python-caja/examples/md5sum-property-page.py`. Naming it
  `get_pages` compiles fine, the extension loads with no error, and the
  method silently never gets called. This one cost a long debugging session -
  if a Properties-page tab isn't showing up and there's no exception anywhere,
  check the method name first.
- **A real OS thread spawned from inside a live Caja process hangs after its
  first blocking call** (reproduced with a trivial sleep loop making zero
  Caja API calls, while the identical thread ran fine standalone and inside a
  bare `Gtk.main()`). This is why hashing uses GIO's async I/O
  (`hashing.AsyncFullHash`) instead of a background thread - don't
  reintroduce threading to "simplify" something without re-confirming this
  isn't still true.
- **No screenshot tooling has been reliably verified on this machine** (i3wm,
  multi-monitor). Prefer non-visual verification: call the actual production
  code directly with mock objects (see `test_hash_color.py` and the
  `get_property_pages` mock pattern used during development), check process
  state/logs, or inspect emblem PNGs directly with the Read tool rather than
  taking a live screenshot of Caja.

## Development loop

1. Edit code.
2. `python3 -m unittest discover -p "test_*.py"` - fast, no Caja needed.
3. If you touched `palette.py`: `python3 generate_emblems.py`.
4. `caja -q` (it auto-restarts on next open).
5. If you need to verify UI behavior and can't/shouldn't screenshot: write a
   throwaway script that imports `hash_color`, instantiates
   `HashColorExtension()` directly, and calls its methods with minimal mock
   objects (a `MockFile`/`MockLocation` with just the attributes that method
   touches) - this exercises the real code without needing Caja's process at
   all. `test_hash_color.py` has a fuller version of this pattern
   (`FakeAsyncFullHash`) for anything that needs to control async hash timing.

## Where things stand

Check `TODO.md` for what's explicitly still open. As of this file being
written: the extension is functionally complete (hashing, caching,
per-directory Fast/Precise/off toggle via the Properties dialog, ~480-emblem
palette, and a queueing/display model where only the file actively being
hashed shows the "synchronizing" placeholder). Not yet done: the two items in
`TODO.md` (cache algorithm-versioning before any real release; nothing else
known-broken at this point).
