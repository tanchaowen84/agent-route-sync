"""Check or regenerate checked-in views of the public rule catalog using the standard library."""
import argparse
import json
from pathlib import Path
import re

from rule_catalog import (BASE_URL, BUSINESS, CLIENT_FORMATS, DATASETS, DNS_HELPER, FORMATS,
                          GUARD, GUARD_SCOPE, ORDER, REPOSITORY, format_variants)


def subscription(client):
    return {
        'schema_version': 1, 'kind': 'agentroute_rule_subscription', 'client': client,
        'format': CLIENT_FORMATS[client], 'index_url': BASE_URL + 'index.json',
        'adapter_url': f'https://github.com/{REPOSITORY}/blob/master/docs/CLIENTS.md#{client}',
        'routing_mode': 'replace', 'final_action': 'PROXY', 'protections': [GUARD.id],
    }


def readme_table(protection=False):
    heading = '| Mihomo | Surge / 小火箭 | sing-box |'
    if protection:
        rows = ['| 防护 | 动作 ' + heading, '| --- | --- | --- | --- | --- |']
    else:
        rows = ['| 顺序 | 业务规则 | 动作 ' + heading, '| --- | --- | --- | --- | --- | --- |']
    for position, rule in enumerate((GUARD,) if protection else BUSINESS, 1):
        label = rule.label if protection else f'**{position:02}** | {rule.label} `{rule.id}`'
        links = [f'[{title}]({BASE_URL}{rule.path(fmt)})' for title, fmt in
                 (('YAML¹' if protection else 'YAML', 'mihomo'), ('LIST', 'surge'), ('JSON', 'sing-box'))]
        rows.append(f'| {label} | `{rule.action}` | ' + ' | '.join(links) + ' |')
    return '\n' + '\n'.join(rows) + '\n'


def standalone_catalog():
    lines = ['# Regenerate with scripts/update_rule_catalog.py --write.',
             f'REPO = {REPOSITORY!r}', f'FORMATS = {FORMATS!r}', f'NAMES = {DATASETS!r}',
             f'HELPER = {DNS_HELPER.path("sing-box")!r}']
    for table, rules in (('REQUIRED_FILES', BUSINESS), ('OPTIONAL_FILES', (GUARD, DNS_HELPER))):
        lines.append(table + ' = {')
        for fmt in FORMATS:
            names = tuple(rule.path(fmt) for rule in rules if fmt in rule.formats)
            lines.append(f'    {fmt!r}: {names!r},')
        lines.append('}')
    variants = {}
    for name, fmt, path in format_variants():
        variants.setdefault(fmt, {})[name] = path
    lines.append('VARIANT_FILES = {')
    for fmt, resources in variants.items():
        lines.append(f'    {fmt!r}: {{')
        lines.extend(f'        {name!r}: {path!r},' for name, path in resources.items())
        lines.append('    },')
    lines.append('}')
    # The Surge example still references these LISTs for DNS, extended matching, IP and ports.
    surge = tuple(rule.path('surge') for rule in (*BUSINESS, GUARD) if rule.id != 'reject')
    lines.extend(['COMPANION_FILES = {', f"    'mrs': ({GUARD.path('mihomo')!r},),",
                  "    'srs': (),", f"    'domain-set': {surge!r},", '}'])
    return '\n'.join(lines)


def replace_section(text, begin, end, body):
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError(f'Missing or duplicate catalog markers: {begin}')
    before, middle = text.split(begin + '\n')
    _, after = middle.split(end)
    return before + begin + '\n' + body + '\n' + end + after


def project_schema(schema, name):
    props = schema['properties']
    groups = props['datasets']
    groups['minItems'] = groups['maxItems'] = len(BUSINESS)
    if name == 'manifest':
        return schema
    # The first two v1 orderings describe historical releases. Rebuild only the
    # current alternative, even when it has accidentally been deleted.
    orders = props['order']['enum']
    if len(orders) not in (2, 3) or any(GUARD.id in order for order in orders[:2]):
        raise ValueError('Restore the two historical v1 orderings before regenerating the current schema')
    orders[2:] = [list(ORDER)]
    groups['allOf'][0]['prefixItems'] = [
        {'properties': {key: {'const': getattr(rule, key)} for key in ('id', 'action', 'mihomo_behavior')}}
        for rule in BUSINESS]
    protection = props['protections']['items']['properties']
    for key in ('id', 'action', 'mihomo_behavior'):
        protection[key] = {'const': getattr(GUARD, key)}
    protection['scope'] = {'const': GUARD_SCOPE}
    formats = schema['$defs']['resources']
    formats['required'] = list(FORMATS)
    formats['properties'] = {
        fmt: {'$ref': '#/$defs/resource', 'properties': {'path': {'pattern': f'^{fmt}/[a-z-]+{re.escape(ext)}$'}}}
        for fmt, ext in FORMATS.items()}
    return schema


def sync_catalog_files(root, *, write=False):
    expected = {}
    directory = root / 'subscriptions'
    if {p.stem for p in directory.glob('*.json')} - CLIENT_FORMATS.keys():
        raise ValueError('Unrecognized subscription outside the client catalog')
    for client in CLIENT_FORMATS:
        expected[directory / (client + '.json')] = json.dumps(subscription(client), indent=2) + '\n'

    readme = root / 'README.md'
    content = readme.read_text(encoding='utf-8')
    for section in ('business', 'protection'):
        content = replace_section(content, f'<!-- rule-catalog:{section} -->', f'<!-- /rule-catalog:{section} -->',
                                  readme_table(protection=section == 'protection'))
    expected[readme] = content
    sync = root / 'scripts/sync_rules.py'
    expected[sync] = replace_section(sync.read_text(encoding='utf-8'), '# BEGIN GENERATED RULE CATALOG',
                                     '# END GENERATED RULE CATALOG', standalone_catalog())

    for name in ('index', 'manifest'):
        schema = root / 'schemas' / (name + '.schema.json')
        source = schema.read_text(encoding='utf-8')
        projected = project_schema(json.loads(source), name)
        if json.loads(source) != projected:
            expected[schema] = json.dumps(projected, indent=2, ensure_ascii=False) + '\n'

    for path, content in expected.items():
        # Read as text to support CRLF checkouts. Published JSON stays generated with LF.
        if path.is_file() and path.read_text(encoding='utf-8') == content:
            continue
        if not write:
            raise ValueError(f'{path.relative_to(root)} differs from rule_catalog.py; run update_rule_catalog.py --write')
        path.write_bytes(content.encode('utf-8'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='update derived files instead of checking them')
    sync_catalog_files(Path(__file__).resolve().parents[1], write=parser.parse_args().write)
