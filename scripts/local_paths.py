"""Portable path discovery and opt-in, machine-local path persistence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / 'local' / 'paths.json'
DLL_RELATIVE = Path('fm_Data/Plugins/x86_64/game_plugin.dll')


def _path(value):
    return Path(os.path.expandvars(str(value))).expanduser().resolve()


def _registry_value(root_name, key, value):
    try:
        import winreg
        with winreg.OpenKey(getattr(winreg, root_name), key) as handle:
            return winreg.QueryValueEx(handle, value)[0]
    except (ImportError, OSError):
        return None


def document_directories():
    redirected = _registry_value(
        'HKEY_CURRENT_USER',
        r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders',
        'Personal',
    )
    candidates = [redirected, Path.home() / 'Documents']
    for key in ('OneDrive', 'OneDriveConsumer', 'OneDriveCommercial'):
        if os.environ.get(key):
            candidates.append(Path(os.environ[key]) / 'Documents')
    return list(dict.fromkeys(_path(p) for p in candidates if p))


def discover_saves():
    files = {
        p.resolve()
        for doc in document_directories()
        for p in (doc / 'Sports Interactive/Football Manager 27/games').glob('*.fm')
        if p.is_file()
    }
    return sorted(files, key=lambda p: (p.stat().st_mtime_ns, str(p)), reverse=True)


def steam_roots():
    candidates = [
        _registry_value('HKEY_CURRENT_USER', r'Software\Valve\Steam', 'SteamPath'),
        _registry_value('HKEY_LOCAL_MACHINE', r'SOFTWARE\Valve\Steam', 'InstallPath'),
        _registry_value('HKEY_LOCAL_MACHINE', r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
    ]
    for key in ('ProgramFiles(x86)', 'ProgramFiles'):
        if os.environ.get(key):
            candidates.append(Path(os.environ[key]) / 'Steam')
    return list(dict.fromkeys(_path(p) for p in candidates if p and _path(p).is_dir()))


def discover_dll():
    libraries = []
    for root in steam_roots():
        libraries.append(root)
        vdf = root / 'steamapps/libraryfolders.vdf'
        if vdf.is_file():
            content = vdf.read_text(encoding='utf8', errors='replace')
            libraries.extend(
                _path(p.replace('\\\\', '\\'))
                for p in re.findall(r'"path"\s+"([^"]+)"', content)
            )
    for library in dict.fromkeys(libraries):
        candidate = library / 'steamapps/common/Football Manager 27' / DLL_RELATIVE
        if candidate.is_file():
            return candidate.resolve()
    raise ValueError('Game installation not found. Supply --game-dir with the Football Manager 27 folder or game_plugin.dll.')


def load_config(path=DEFAULT_CONFIG):
    path = _path(path)
    if not path.exists():
        return {}
    try:
        config = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error:
        raise ValueError(f'Cannot read local path configuration {path}: {error}') from error
    if not isinstance(config, dict) or config.get('schema_version') != 1:
        raise ValueError(f'Unsupported local path configuration: {path}')
    for field in ('save_path', 'game_dll'):
        value = config.get(field)
        if not isinstance(value, str) or not value.strip() or not Path(value).is_absolute():
            raise ValueError(f'Local configuration {field} must be an absolute path: {path}')
    return config


def resolve_save(explicit=None, config=None):
    config = config or {}
    if explicit is not None:
        value, source = explicit, '--save'
    elif os.environ.get('FM27_SAVE_PATH'):
        value, source = os.environ['FM27_SAVE_PATH'], 'FM27_SAVE_PATH'
    elif config.get('save_path'):
        value, source = config['save_path'], 'local_config'
    else:
        saves = discover_saves()
        if not saves:
            raise ValueError('Save not found in Documents. Supply --save with a .fm file (custom/cloud folders require an explicit path).')
        value, source = saves[0], 'newest_discovered_save'
    path = _path(value)
    if not path.is_file() or path.suffix.lower() != '.fm':
        raise ValueError(f'Save not found or not a .fm file ({source}): {path}. Supply --save; do not silently switch careers.')
    return path, source


def resolve_dll(explicit=None, config=None):
    config = config or {}
    if explicit is not None:
        path, source = _path(explicit), '--game-dir'
        if path.name.lower() != 'game_plugin.dll':
            path = path / DLL_RELATIVE
    elif os.environ.get('FM27_GAME_DLL'):
        path, source = _path(os.environ['FM27_GAME_DLL']), 'FM27_GAME_DLL'
    elif config.get('game_dll'):
        path, source = _path(config['game_dll']), 'local_config'
    else:
        path, source = discover_dll(), 'steam_discovery'
    if not path.is_file():
        raise ValueError(f'Game DLL not found ({source}): {path}. Supply --game-dir to update its location.')
    return path.resolve(), source


def remember_paths(config_path, save_path, game_dll):
    """Call only after doctor has successfully validated the real save and DLL."""
    destination, save, dll = map(_path, (config_path, save_path, game_dll))
    game_root = dll.parents[3]
    if destination.suffix.lower() != '.json' or destination.is_relative_to(save.parent) or destination.is_relative_to(game_root):
        raise ValueError('Local configuration must be a JSON file outside the save directory and game installation.')
    config = {'schema_version': 1, 'save_path': str(save), 'game_dll': str(dll)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.tmp')
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    temporary.replace(destination)
    return destination
