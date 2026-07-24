#!/usr/bin/env python3
import json
import os
from pathlib import Path
from typing import Literal, TypedDict

CONFIG_DIR = Path(os.path.expanduser('~/.config/caja-hashcolor'))
CONFIG_PATH = CONFIG_DIR / 'config.json'

Mode = Literal['fast', 'precise']


class Config(TypedDict):
    fast_dirs: list[str]
    precise_dirs: list[str]


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        return {'fast_dirs': [], 'precise_dirs': []}
    try:
        with open(CONFIG_PATH) as config_file:
            stored = json.load(config_file)
    except (json.JSONDecodeError, OSError):
        # A corrupt file (e.g. from a crash/kill mid-write, before save_config()
        # wrote atomically) shouldn't crash every properties-page/hash decision
        # that reads config - treat it as "no settings" rather than raising.
        return {'fast_dirs': [], 'precise_dirs': []}
    return {
        'fast_dirs': list(stored.get('fast_dirs', [])),
        'precise_dirs': list(stored.get('precise_dirs', [])),
    }


def save_config(config: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Write to a temp file and atomically rename it into place, so a crash or kill
    # mid-write can never leave config.json truncated/corrupt - readers always see
    # either the fully-old or fully-new version, never a partial one.
    temp_path = CONFIG_PATH.with_suffix('.json.tmp')
    with open(temp_path, 'w') as config_file:
        json.dump(config, config_file)
    os.replace(temp_path, CONFIG_PATH)


def get_mode_for_directory(directory: str, config: Config) -> Mode | None:
    if directory in config['fast_dirs']:
        return 'fast'
    if directory in config['precise_dirs']:
        return 'precise'
    return None


def set_mode_for_directory(directory: str, mode: Mode | None) -> None:
    """mode='fast'/'precise' enables that mode for this directory (and disables the
    other, if it was set); mode=None disables visual hash for this directory."""
    config = load_config()
    config['fast_dirs'] = [d for d in config['fast_dirs'] if d != directory]
    config['precise_dirs'] = [d for d in config['precise_dirs'] if d != directory]
    if mode == 'fast':
        config['fast_dirs'].append(directory)
    elif mode == 'precise':
        config['precise_dirs'].append(directory)
    save_config(config)


def prune_missing_dirs() -> int:
    config = load_config()
    before = len(config['fast_dirs']) + len(config['precise_dirs'])
    config['fast_dirs'] = [d for d in config['fast_dirs'] if os.path.isdir(d)]
    config['precise_dirs'] = [d for d in config['precise_dirs'] if os.path.isdir(d)]
    removed = before - (len(config['fast_dirs']) + len(config['precise_dirs']))
    if removed:
        save_config(config)
    return removed
