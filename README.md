# caja-hashcolor

A Caja (MATE file manager) extension that colors each file's icon with a small
emblem derived from the file's content hash — so identical and near-identical
files are obvious at a glance, without opening, comparing or checksumming
anything by hand.

![Caja showing two identical .deb files with the same hash emblem, next to the Visual hash tab of the Properties dialog](docs/screenshot.png)

In the shot above, the two `.deb` files are byte-identical copies and get the
same emblem; the two text files differ and get their own. The emblem is picked
purely from the file's content, so the same file always produces the same
picture, in any folder, on any machine.

## Features

- **Off everywhere by default.** Each folder has its own independent setting;
  turning it on in one folder affects nothing else, not even its subfolders.
- **Two modes.** *Fast* samples large files, *Precise* always reads them whole.
- **479 distinct emblems, 0.21% chance of collision between two files** —
  solid colors plus 2/3/4/5/6-color band and pie layouts, from a hand-tuned
  7-hue palette, every one equally likely.
- **Never freezes the file manager.** Hashing happens in the background, one
  file at a time, and stops as soon as you leave the folder.
- **Colors are remembered** between sessions and recomputed when a file
  changes, so a folder is only slow the first time you open it.

Sample emblems: ![](emblems/hashcolor-1-0.png) ![](emblems/hashcolor-2-0-4-45.png) ![](emblems/hashcolor-3b-2-4-6-90.png) ![](emblems/hashcolor-3p-0-2-4.png) ![](emblems/hashcolor-4p-0-2.png) ![](emblems/hashcolor-5p-2-4-6.png) ![](emblems/hashcolor-6p-0-3.png)

## Requirements

- Caja itself, plus the package that lets it run Python extensions - usually
  `python3-caja` on Debian, Ubuntu and Mint, `caja-python` or `python-caja`
  elsewhere.
- `python3-gi` and `gir1.2-gtk-3.0` (Debian/Ubuntu names).
- Python 3.10 or newer.

Nothing else: the emblems ship with the repository, already drawn.

## Install

```
git clone https://github.com/inaltoasinistra/caja-hashcolor.git
cd caja-hashcolor
make install     # for the current user, into ~/.local
caja -q          # Caja restarts on its own the next time you open a folder
```

Use `sudo make install` instead to install system-wide into `/usr` for every
user on the machine. `make install PREFIX=/opt/somewhere` overrides the prefix,
and `make install DESTDIR=/build/root` stages the files without touching the
live system, for building a distro package.

`caja -q` quits every Caja window and process — it's a single process serving
all of them — and the extension is only picked up on the next start.

## Uninstall

```
make uninstall       # or `sudo make uninstall` if you installed system-wide
caja -q
```

That removes the extension and its emblems. Your settings and the remembered
colors are left alone; delete them by hand if you want them gone too:

```
rm -rf ~/.config/caja-hashcolor ~/.cache/caja-hashcolor
```

## Usage

Right-click any single file or folder and choose **Properties**. The dialog has
a **Visual hash** tab (see the screenshot above) with three radio buttons:

- **Off** / **Fast** / **Precise** — see below for the difference between the
  two active modes. Selecting one applies it *to that folder only*, and the
  tab always opens on whichever setting is currently in force.

Every folder remembers its own setting, so turning it on somewhere has no
effect on any other folder, including its own subfolders. Changing a folder's
setting re-colors the files in it straight away - no manual refresh needed.

Colors don't all appear at once. Files are hashed one at a time: whichever file
is being worked on shows a "synchronizing" emblem, files still waiting their
turn show no emblem at all, and each gets its color as its own turn finishes. A
folder of large files switched to Precise mode can take a while to fully color
in.

## Hash modes

- **Fast** (default): files up to 1MB are hashed whole; for anything larger,
  only the first 250KB, the last 250KB and the file size are used. Quick even
  on slow or network drives, with one blind spot - two large files that differ
  *only* somewhere in the untouched middle get the same color.
- **Precise**: always reads the entire file. No blind spot, but a large file,
  especially on a network drive, takes as long as it takes to read.

Both keep the file manager responsive while they work.

Colors are remembered between sessions in `~/.cache/caja-hashcolor/cache.db`
by default, and recomputed whenever a file changes. Deleting that file simply
makes the extension work them out again. Your per-folder settings live in
`~/.config/caja-hashcolor/config.json`; folders you delete are dropped from it
automatically. Both locations follow `XDG_CACHE_HOME` and `XDG_CONFIG_HOME` if
you have set them.

## License

MIT - see [LICENSE](LICENSE).

## Development

[DEVELOPMENT.md](DEVELOPMENT.md) is the developer documentation: where an
install puts each file, the `make` targets for testing and working from a
checkout, and the reasoning behind the parts that aren't obvious - why hashing
runs in the background one file at a time, why the emblems are installed
outside the icon theme, and how the palette is put together.
