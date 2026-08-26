"""XDG base directory resolution.

Every path the extension reads or writes outside its install prefix - the
settings file, the digest cache, the installed emblems - is resolved here, so
the three of them cannot drift apart on how much of the spec they honour.

Deliberately stdlib-only, no gi import: GLib offers g_get_user_config_dir() and
friends, but pulling a typelib into the one module that just joins strings would
mean the tests need a working GObject introspection stack to check a default.
"""
import os

DATA_HOME_DEFAULT = '~/.local/share'
CONFIG_HOME_DEFAULT = '~/.config'
CACHE_HOME_DEFAULT = '~/.cache'
DATA_DIRS_DEFAULT = '/usr/local/share:/usr/share'


def _is_usable(path: str) -> bool:
    """The basedir spec: a value that is not an absolute path "is invalid and
    must be ignored", which covers the empty string too. Silently falling back
    beats writing a config file to some path relative to wherever Caja happened
    to be started from."""
    return os.path.isabs(path)


def _base_dir(env_var: str, default: str) -> str:
    value = os.environ.get(env_var, '')
    return value if _is_usable(value) else os.path.expanduser(default)


def data_home() -> str:
    return _base_dir('XDG_DATA_HOME', DATA_HOME_DEFAULT)


def config_home() -> str:
    return _base_dir('XDG_CONFIG_HOME', CONFIG_HOME_DEFAULT)


def cache_home() -> str:
    return _base_dir('XDG_CACHE_HOME', CACHE_HOME_DEFAULT)


def data_dirs() -> list[str]:
    """Every data directory to search, most specific first: the user's own,
    then the system ones. This is the order caja-python uses to find extensions,
    so a user install shadows a system one for our files the same way."""
    system_dirs = os.environ.get('XDG_DATA_DIRS', '') or DATA_DIRS_DEFAULT
    return [data_home()] + [directory for directory in system_dirs.split(':') if _is_usable(directory)]
