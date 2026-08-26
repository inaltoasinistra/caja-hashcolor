"""Support modules for the caja-hashcolor Caja extension.

These live in a package rather than as top-level modules because caja-python
inserts its extensions directory at sys.path[0] and imports every top-level
.py it finds there: flat modules named `config`, `hashing` and `palette` would
both be loaded as (non-)extensions themselves and shadow those names for every
other Caja extension on the machine. Only hash_color.py stays top-level.
"""
