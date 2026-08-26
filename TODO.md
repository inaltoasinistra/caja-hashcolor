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

Emblems are installed into `share/caja-hashcolor/emblems/` and registered with
`Gtk.IconTheme.append_search_path()` once, at extension load. A newly rendered
PNG is therefore invisible to Caja twice over: until `make install-emblems`
copies it into that directory, and then until Caja restarts, since the search
path is scanned once and a running process keeps serving lookups from what it
already saw. Any digest resolving to a name it
hasn't seen shows as a missing/broken icon in the meantime. Confirmed during
development: after several rounds of adding new emblem styles, every
currently-cached file's emblem had been generated after Caja's last startup,
and all appeared broken until `caja -q` + relaunch.

Not a problem for a real install (the emblem set is finished and installed
before the extension is ever loaded), but during development, always
`make emblems && make install-emblems && caja -q` - a window refresh (Ctrl+R)
is not enough.
