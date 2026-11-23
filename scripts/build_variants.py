"""Add optional native formats to a verified text generation in a new directory."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from build_rules import DOMAIN
from release_files import regular_files, verify_manifest_files
from rule_catalog import BASE_URL, LEGACY_FILES, RESOURCE_BY_ID, VARIANT_SOURCE_FORMAT, format_variants
from validate_native import checked


def verified_snapshot(directory):
    actual = regular_files(directory)
    manifest = json.loads(actual['manifest.json'].read_bytes())
    verify_manifest_files(actual, manifest['files'])
    index = json.loads(actual['index.json'].read_bytes())
    if index['base_url'] != BASE_URL or index['generated_at_utc'] != manifest['generated_at_utc']:
        raise ValueError('Expected one public generation')
    return index, manifest


def domain_set(source, target, entries, reuse):
    expected = []
    for line in source.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith(('#', '//')):
            continue
        kind, _, name = line.partition(',')
        if kind not in ('DOMAIN', 'DOMAIN-SUFFIX') or not DOMAIN.fullmatch(name):
            raise ValueError(f'Unsupported domain rule in {source.name}')
        expected.append(('.' if kind == 'DOMAIN-SUFFIX' else '') + name.lower())
    if len(expected) != entries:
        raise ValueError(f'Domain rule count differs from index: {source.name}')
    encoded = ('\n'.join(expected) + '\n').encode('utf-8')
    if not reuse:
        target.write_bytes(encoded)
        return
    original = target.read_bytes()
    if original != encoded:
        # DOMAIN-SET is case insensitive. Order and comments do not change membership.
        lines = (line.strip().lower() for line in original.decode('utf-8').splitlines())
        actual = Counter(line for line in lines if line and not line.startswith(('#', '//')))
        if actual != Counter(expected):
            raise ValueError(f'Existing DOMAIN-SET differs from source rules: {target.name}')


def add_variants(directory, mihomo, sing_box):
    index, manifest = verified_snapshot(directory)
    if 'format_variants' in index:
        raise ValueError('Expected a text generation without format variants')
    files = manifest['files']
    sources = {group['id']: group['resources'] for group in index['datasets'] + index['protections']}
    sources.update({helper['id']: {'sing-box': helper} for helper in index['helpers']})
    if (sources.keys() != RESOURCE_BY_ID.keys()
            or len(sources) != sum(len(index[key]) for key in ('datasets', 'protections', 'helpers'))):
        raise ValueError('Expected all business rules, protection and DNS helper exactly once')
    variants = []
    for name, fmt, path in format_variants():
        rule = RESOURCE_BY_ID[name]
        source_format = VARIANT_SOURCE_FORMAT[fmt]
        resource = sources[name][source_format]
        source_path = rule.path(source_format)
        count = resource['entries']
        if (resource['path'] != source_path or resource['sha256'] != files[source_path]
                or resource['url'] != BASE_URL + source_path or type(count) is not int or count < 1):
            raise ValueError(f'Invalid source resource for {path}')
        source, target = directory / source_path, directory / path
        if target.exists() and path not in LEGACY_FILES:
            raise ValueError(f'Variant output already exists in text generation: {path}')
        if fmt == 'mrs':
            checked([mihomo, 'convert-ruleset', rule.mihomo_behavior, 'yaml', source, target])
        elif fmt == 'srs':
            checked([sing_box, 'rule-set', 'compile', '--output', target, source])
        else:
            domain_set(source, target, count, path in LEGACY_FILES)
        if target.is_symlink() or not target.is_file() or target.stat().st_size == 0:
            raise ValueError(f'No regular, nonempty variant produced: {path}')
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if path in LEGACY_FILES and files[path] != digest:
            raise ValueError(f'Existing resource changed during compilation: {path}')
        files[path] = digest
        variants.append({'id': name, 'format': fmt, 'path': path, 'url': BASE_URL + path,
                         'sha256': files[path], 'entries': count})
    index['format_variants'] = variants
    index_bytes = (json.dumps(index, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    (directory / 'index.json').write_bytes(index_bytes)
    files['index.json'] = hashlib.sha256(index_bytes).hexdigest()
    (directory / 'manifest.json').write_bytes((json.dumps(manifest, indent=2) + '\n').encode('utf-8'))
    verified_snapshot(directory)
    return len(variants)


def build_variants(source, output, mihomo, sing_box):
    if source.is_symlink() or not source.is_dir():
        raise ValueError('Expected a regular source directory')
    if os.path.lexists(output):
        raise FileExistsError(f'Output must be a new directory: {output}')
    source, output = source.resolve(), output.resolve()
    if source in output.parents:
        raise ValueError('Output must be outside the source directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.agentroute-variants-', dir=output.parent) as temp:
        candidate = Path(temp) / 'candidate'
        candidate.mkdir()
        # Copy bytes only. A read-only published snapshot can still be compiled in our own directory.
        for name, path in regular_files(source).items():
            target = candidate / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        count = add_variants(candidate, mihomo, sing_box)
        if os.path.lexists(output):
            raise FileExistsError(f'Output already exists: {output}')
        candidate.rename(output)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--mihomo', required=True)
    parser.add_argument('--sing-box', required=True)
    args = parser.parse_args()
    count = build_variants(args.source, args.output, args.mihomo, args.sing_box)
    print(json.dumps({'format_variants': count, 'output': str(args.output)}))


if __name__ == '__main__':
    main()
