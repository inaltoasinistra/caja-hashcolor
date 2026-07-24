# TODO

## Cache invalidation on hashing algorithm changes

`hashing.HashCache` keys entries by `(path, mode, size, mtime)` - there's no
algorithm-version marker in that key. Whenever `compute_digest()`'s actual
byte-selection logic changes (e.g. the Fast-mode sampling redesign from
uniform 10x10KB samples to head/tail anchors), old digests cached under the
previous algorithm remain in the cache and get served as valid hits for any
file whose size/mtime hasn't changed since - silently mixing digests from two
different algorithms, for however long it takes each file's mtime to change.

Not a problem during development (just delete `~/.cache/caja-hashcolor/cache.db`
by hand after an algorithm change, which is what's being done locally for the
current sampling redesign). Before any real release this needs an actual fix -
e.g. an algorithm-version number stored in the cache (its own column, or
folded into the `mode` string used as part of the key) that gets bumped
whenever `compute_digest()`'s byte-selection logic changes, so old entries are
automatically treated as cache misses instead of requiring a manual wipe.

## Caja needs a restart after regenerating emblems

`hash_color.py` registers the `emblems/` directory with
`Gtk.IconTheme.get_default().append_search_path(...)` once, when the
extension loads. If `generate_emblems.py` adds or renames files afterward
while Caja is still running, Caja doesn't notice - it keeps using whatever
file listing it saw at startup, so any digest that resolves to a newer emblem
name shows as a missing/broken icon. Confirmed during development: after
several rounds of adding new emblem styles, every currently-cached file's
emblem had been generated after Caja's last startup, and all appeared broken
until `caja -q` + relaunch.

Not a problem for a real install (the emblem set is finished before the
extension is ever loaded), but during development, always restart Caja after
running `generate_emblems.py`, not just refresh (Ctrl+R) the window.
