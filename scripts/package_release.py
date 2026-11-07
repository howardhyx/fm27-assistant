"""Create a source release without local paths, saves, or generated output."""
from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_FILES = {'SKILL.md', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', '.gitignore', '.gitattributes'}
PUBLIC_DIRS = {'agents', 'references', 'scripts', 'tests'}
PRIVATE_DIRS = {'.git', '__pycache__', '.venv', 'local', 'work', 'dist'}


def release_files(root=ROOT):
    root = Path(root).resolve()
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in PRIVATE_DIRS for part in relative.parts):
            continue
        if relative.parts[0] not in PUBLIC_DIRS and str(relative) not in PUBLIC_FILES:
            continue
        if path.suffix.lower() in {'.fm', '.pyc', '.pyo', '.zip'} or path.name.lower() == 'game_plugin.dll':
            continue
        yield path


def package(destination, root=ROOT):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination.suffix.lower() != '.zip' or destination.is_relative_to(root):
        raise ValueError('Choose a .zip destination outside the skill source directory.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in release_files(root):
            archive.write(path, (Path(root.name) / path.relative_to(root)).as_posix())
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(package(args.out))


if __name__ == '__main__':
    main()
