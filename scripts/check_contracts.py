"""Validate the public release contracts and repository documentation offline."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sysconfig
import tempfile

from jsonschema import Draft202012Validator, FormatChecker

from build_rules import DOMAIN, REGISTRY, ROOT, build
from public_formats import WEBRTC_KEYWORDS, WEBRTC_PORTS
from release_files import regular_files, verify_manifest_files
from rule_catalog import (BASE_URL, DNS_HELPER, FORMATS, GUARD, LEGACY_FILES, RESOURCE_BY_ID,
                          VALIDATION_SCOPE, VARIANT_SOURCE_FORMAT, format_variants)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def format_checker():
    checker = FormatChecker()
    missing = {'date-time', 'uri'} - checker.checkers.keys()
    if missing:
        raise ValueError(f'Missing JSON Schema formats {sorted(missing)}. Install requirements-dev.txt.')
    return checker


def check_resource(resource, files, base_url, expected_path=None):
    path = resource['path']
    if expected_path is not None and path != expected_path:
        raise ValueError(f'Expected resource {expected_path}, got {path}')
    if resource['url'] != base_url + path:
        raise ValueError(f'Resource URL does not match its published path: {path}')
    if files.get(path) != resource['sha256']:
        raise ValueError(f'Resource digest does not match manifest: {path}')


def rule_count(path):
    with path.open('rb') as lines:
        rules = (line.strip() for line in lines)
        return sum(1 for rule in rules if rule and not rule.startswith((b'#', b'//', b';')))


def verified_metadata(directory):
    paths = regular_files(directory)
    checker = format_checker()
    metadata = {}
    for name in ('manifest', 'index'):
        filename = name + '.json'
        if filename not in paths:
            raise ValueError(f'Missing artifact file: {filename}')
        schema = read_json(ROOT / 'schemas' / (name + '.schema.json'))
        Draft202012Validator.check_schema(schema)
        metadata[name] = read_json(paths[filename])
        Draft202012Validator(schema, format_checker=checker).validate(metadata[name])

    index, manifest = metadata['index'], metadata['manifest']
    files = manifest['files']
    verify_manifest_files(paths, files)
    if index['generated_at_utc'] != manifest['generated_at_utc']:
        raise ValueError('Index and manifest belong to different generations')
    return paths, index, files


def compatibility_and_license_files(paths, files, historical):
    published = set(LEGACY_FILES) | {'index.json', 'LICENSE', 'sources.json', 'NOTICE.md'}
    if not published <= files.keys():
        raise ValueError(f'Missing public files: {sorted(published - files.keys())}')
    if not historical:
        for name in ('LICENSE', 'NOTICE.md', 'sources.json'):
            if files[name] != hashlib.sha256((ROOT / name).read_bytes()).hexdigest():
                raise ValueError(f'Attribution file differs from this source tree: {name}')
    # A historical generation can have a different set of attributed sources.
    registry = read_json(paths['sources.json']) if historical else REGISTRY
    for project in registry['projects']:
        for license_copy in project.get('license_copies', []):
            published.add(license_copy['path'])
            if files.get(license_copy['path']) != license_copy['sha256']:
                raise ValueError(f'License copy differs from source registry: {license_copy["path"]}')
    return published


def check_domain_set(list_path, domain_path):
    # The leading dot in a Surge DOMAIN-SET covers the name and all descendants.
    expected = Counter()
    with list_path.open(encoding='utf-8') as rules:
        for number, line in enumerate(rules, 1):
            line = line.strip()
            if not line or line.startswith(('#', '//')):
                continue
            kind, _, name = line.partition(',')
            if kind not in ('DOMAIN', 'DOMAIN-SUFFIX') or not DOMAIN.fullmatch(name):
                raise ValueError(f'Unsupported domain rule: {list_path.name}:{number}')
            expected[name.lower() if kind == 'DOMAIN' else '.' + name.lower()] += 1
    with domain_path.open(encoding='utf-8') as domains:
        for number, line in enumerate(domains, 1):
            item = line.strip().lower()
            if not item or item.startswith(('#', '//')):
                continue
            if not expected[item]:
                raise ValueError(f'DOMAIN-SET differs from {list_path.name}: {domain_path.name}:{number}')
            expected[item] -= 1
    if any(expected.values()):
        raise ValueError(f'DOMAIN-SET is missing rules from {list_path.name}: {domain_path.name}')


def check_format_variants(index, files, paths, base_url, required):
    catalog = {(identity, fmt): path for identity, fmt, path in format_variants()}
    if 'format_variants' not in index:
        if required or (set(catalog.values()) - set(LEGACY_FILES)) & files.keys():
            raise ValueError('Missing format_variants index for this publication')
        return set()
    records = index['format_variants']
    keys = {(item['id'], item['format']) for item in records}
    if len(keys) != len(records) or keys != catalog.keys():
        raise ValueError('Incomplete, duplicate or unsupported format variant identity')
    sources = {group['id']: group['resources'] for group in index['datasets'] + index.get('protections', [])}
    sources.update({helper['id']: {'sing-box': helper} for helper in index.get('helpers', [])
                    if helper['id'] == DNS_HELPER.id})
    for item in records:
        identity, fmt = item['id'], item['format']
        path = catalog[(identity, fmt)]
        check_resource(item, files, base_url, path)
        if not paths[path].stat().st_size:
            raise ValueError(f'Empty variant: {path}')
        source = sources.get(identity, {}).get(VARIANT_SOURCE_FORMAT[fmt])
        if not source or item['entries'] != source['entries']:
            raise ValueError(f'Variant count differs from its indexed source: {path}')
        if fmt == 'domain-set':
            check_domain_set(paths[source['path']], paths[path])
    return set(catalog.values())


def validate_generated(directory, *, historical=False, require_variants=False):
    paths, index, files = verified_metadata(directory)
    published = compatibility_and_license_files(paths, files, historical)
    base_url = index.get('base_url', '')
    if not base_url.endswith('/') or (not historical and base_url != BASE_URL):
        raise ValueError('Invalid publication base URL')
    if index.get('manifest_url') != base_url + 'manifest.json':
        raise ValueError('Invalid manifest URL')

    guards = index.get('protections', [])
    for group in index['datasets'] + guards:
        resources = group['resources']
        rule = RESOURCE_BY_ID[group['id']]
        if not historical and set(resources) != set(rule.formats):
            raise ValueError(f'Resource formats differ from catalog: {rule.id}')
        if len({resources[fmt]['entries'] for fmt in FORMATS}) != 1:
            raise ValueError(f'Resource counts disagree for {group["id"]}')
        for fmt, resource in resources.items():
            path = rule.path(fmt) if fmt in FORMATS else None
            check_resource(resource, files, base_url, path)
            published.add(resource['path'])
        surge = resources['surge']
        if rule_count(paths[surge['path']]) != surge['entries']:
            raise ValueError(f'Resource count differs from actual Surge LIST: {surge["path"]}')
    if bool(guards) != (GUARD.id in index['order']):
        raise ValueError('Protection and index order disagree')
    guard_paths = {GUARD.path(fmt) for fmt in GUARD.formats}
    if not guards and guard_paths & files.keys():
        raise ValueError('Published protection is missing from the index')
    if guards:
        guard = guards[0]
        entries = len(guard['ports']) + len(guard['domain_keywords'])
        if guard['resources']['surge']['entries'] != entries:
            raise ValueError('Protection count disagrees with declared conditions')
        if not historical and (set(guard['ports']) != set(WEBRTC_PORTS)
                               or set(guard['domain_keywords']) != set(WEBRTC_KEYWORDS)):
            raise ValueError('Protection conditions differ from this release contract')

    helpers = index.get('helpers', [])
    helper_ids = {helper['id'] for helper in helpers}
    if len(helper_ids) != len(helpers):
        raise ValueError('Duplicate helper identity')
    for helper in helpers:
        expected = DNS_HELPER.path('sing-box') if helper['id'] == DNS_HELPER.id else None
        if not historical and (not expected or helper.get('purpose') != DNS_HELPER.label):
            raise ValueError('DNS helper identity or purpose differs from catalog')
        check_resource(helper, files, base_url, expected)
        published.add(helper['path'])
        if expected:
            source = read_json(paths[expected])
            if sum(len(rule['ip_cidr']) for rule in source['rules']) != helper['entries']:
                raise ValueError('DNS helper count differs from actual prefixes')
    if (DNS_HELPER.id in helper_ids) != (DNS_HELPER.path('sing-box') in files):
        raise ValueError('Non-China IP helper and manifest disagree')
    if not historical and (not guards or DNS_HELPER.id not in helper_ids):
        raise ValueError('Current publication requires the protection and DNS helper')
    if not historical and index.get('validation_scope') != VALIDATION_SCOPE:
        raise ValueError('Current client validation scope differs from the catalog')
    variant_paths = check_format_variants(index, files, paths, base_url, require_variants)
    published.update(variant_paths)
    if published != files.keys():
        raise ValueError(f'Unrecognized public files: {sorted(files.keys() - published)}')

    return index, {'schemas': 2, 'verified_files': len(files),
                   'datasets': len(index['datasets']), 'protections': len(guards), 'helpers': len(helpers),
                   'format_variants': len(variant_paths)}


def check_local_links(docs):
    # A virtual environment can be used without activating its bin directory.
    lychee = shutil.which('lychee', path=sysconfig.get_path('scripts')) or shutil.which('lychee')
    if not lychee:
        raise ValueError('Missing lychee. Install requirements-dev.txt.')
    result = subprocess.run(
        [lychee, '--offline', '--no-progress', '--include-fragments=anchor-only', *map(str, docs)],
        capture_output=True, encoding='utf-8', errors='replace', timeout=60,
    )
    if result.returncode:
        raise ValueError('Local documentation link check failed:\n' + result.stdout + result.stderr)


def check_documentation(index):
    from update_rule_catalog import sync_catalog_files

    sync_catalog_files(ROOT)
    # Compare the rendered table with the built index independently of the catalog renderer.
    rule_urls = [group['resources'][fmt]['url'] for group in index['datasets'] + index['protections']
                 for fmt in ('mihomo', 'surge', 'sing-box')]
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    table = '\n'.join(line for line in readme.splitlines() if line.startswith('|'))
    table_urls = re.findall(r'\]\(([^)]+)\)', table)
    if [url for url in table_urls if url.startswith(index['base_url'])] != rule_urls:
        raise ValueError('readme_rule_table_does_not_match_index')
    projects = {project['id'] for project in REGISTRY['projects']}
    if any(entry['repository'] not in projects for entry in REGISTRY['inputs'].values()):
        raise ValueError('source_not_attributed')
    notice = (ROOT / 'NOTICE.md').read_text(encoding='utf-8')
    if any(project['url'] not in notice for project in REGISTRY['projects']):
        raise ValueError('notice_source_missing')
    docs = [ROOT / 'README.md', ROOT / 'AGENTS.md', ROOT / 'NOTICE.md',
            *(ROOT / 'docs').glob('*.md'), ROOT / 'examples/README.md']
    check_local_links(docs)
    return {'sources': len(projects), 'readme_rule_links': len(rule_urls), 'documentation_links': 'passed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated', type=Path, help='Check these built files without rebuilding them.')
    parser.add_argument('--historical', action='store_true', help='Accept earlier v1 generations without later optional resources.')
    parser.add_argument('--require-variants', action='store_true', help='Require the complete parallel format catalog.')
    args = parser.parse_args()
    if args.generated is not None:
        _, result = validate_generated(args.generated, historical=args.historical, require_variants=args.require_variants)
    else:
        if args.historical or args.require_variants:
            parser.error('--historical and --require-variants require --generated')
        from rule_fixtures import source_inputs
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            build(source_inputs(), output)
            index, result = validate_generated(output)
            result.update(check_documentation(index))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
