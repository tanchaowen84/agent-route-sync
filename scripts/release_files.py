"""Inspect the regular files and manifest of an unpacked release using the standard library."""
import hashlib


def regular_files(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Expected a regular artifact directory')
    paths = {}
    for path in directory.rglob('*'):
        name = path.relative_to(directory).as_posix()
        if path.name.startswith('.'):
            raise ValueError(f'Hidden artifact entry: {name}')
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError(f'Non-regular artifact entry: {name}')
        if path.is_file():
            paths[name] = path
    return paths


def verify_manifest_files(paths, files):
    actual = set(paths) - {'manifest.json'}
    if actual != files.keys():
        raise ValueError(f'Artifact inventory differs from manifest: {sorted(actual ^ files.keys())}')
    for name, digest in files.items():
        if hashlib.sha256(paths[name].read_bytes()).hexdigest() != digest:
            raise ValueError(f'Artifact bytes do not match manifest digest: {name}')
