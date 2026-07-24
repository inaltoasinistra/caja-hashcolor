# caja-hashcolor

Caja (MATE file manager) extension: colors each file's icon with an emblem
derived from its content hash, so identical/near-identical files are easy to
spot at a glance. Read `README.md` first for the full design - this file is
just orientation and gotchas for picking the project back up.

## Commands

- Run all tests: `python3 -m unittest discover -p "test_*.py"`
- Run one test file: `python3 -m unittest test_hashing`
- Run one test case/method: `python3 -m unittest test_hashing.TestComputeDigest.test_fast_mode_small_file`
- Regenerate emblems after any `palette.py` change: `python3 generate_emblems.py`
- Install/link the extension: see `README.md`'s Install section (symlinks the
  `.py` files and `emblems/` into `~/.local/share/caja-python/extensions/`).
- Reload after any code or emblem change: `caja -q` (auto-restarts on next
  `caja` open or folder navigation).

## Files

- `hash_color.py` - the actual Caja extension (`HashColorExtension`, a
  `Caja.InfoProvider` + `Caja.PropertyPageProvider`). Most of the real
  complexity lives here.
- `hashing.py` - pure hashing/caching logic: `compute_digest()` (Fast/Precise
  modes), `AsyncFullHash` (GIO async file reading), `SerialQueue` (one hash at
  a time), `HashCache` (SQLite, self-healing if the cache file is deleted).
- `palette.py` - the color palette and `hash_to_emblem_name()`: maps a digest
  to one of ~470 pre-rendered emblem names (2/3/4/5/6-color combinations in
  band/pie layouts).
- `generate_emblems.py` - dev-time script that renders every reachable emblem
  name from `palette.py` to `emblems/*.png`. Run it after *any* change to
  `palette.py`.
- `config.py` - per-directory Fast/Precise/off setting, stored as two path
  lists in `~/.config/caja-hashcolor/config.json`.
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
  restart: `Gtk.IconTheme.get_default().append_search_path(...)` is called
  once at extension load, and Caja doesn't notice new files added to that
  directory afterward. Run `generate_emblems.py`, *then* restart Caja, or new
  emblem names will render as broken/missing icons. (`TODO.md` has more.)
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
per-directory Fast/Precise/off toggle via the Properties dialog, ~470-emblem
palette, and a queueing/display model where only the file actively being
hashed shows the "synchronizing" placeholder). Not yet done: the two items in
`TODO.md` (cache algorithm-versioning before any real release; nothing else
known-broken at this point).
