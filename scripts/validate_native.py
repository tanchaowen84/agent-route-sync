"""Offline native format checks. Never start a proxy or change an active profile."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from rule_catalog import (BASE_URL, BUSINESS, DNS_HELPER, GUARD, LEGACY_FILES, RESOURCE_BY_ID,
                          VARIANT_SOURCE_FORMAT, format_variants)


def checked(command):
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=90)
    output = result.stdout + result.stderr
    if result.returncode or re.search(r'\b(WARN(?:ING)?|ERROR|FATAL|deprecated)\b', output, re.I):
        raise RuntimeError('native validation failed: ' + output[:3000])


def localized_mihomo(source, generated, work, replacements=None):
    import yaml
    config = yaml.safe_load(source.read_text(encoding='utf-8'))
    config.update({'mode': 'rule', 'proxies': [{'name': 'PROXY', 'type': 'socks5', 'server': '127.0.0.1', 'port': 9}]})
    for provider in config['rule-providers'].values():
        source_path = provider['url'].removeprefix(BASE_URL)
        if replacements and source_path in replacements:
            source_path = replacements[source_path]
            provider['format'] = 'mrs'
            provider['path'] = str(Path(provider['path']).with_suffix('.mrs'))
        destination = work / provider['path']
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(generated / source_path, destination)
        provider['type'] = 'file'
        provider.pop('url'); provider.pop('proxy'); provider.pop('interval')
    return config


def check_mihomo_guard(mihomo, generated, work):
    import yaml

    # -t checks a file provider's declaration. An inline provider also parses
    # each classical rule during -t and reports unsupported rules as warnings.
    source = generated / GUARD.path('mihomo')
    guard = yaml.safe_load(source.read_text(encoding='utf-8'))
    payload = guard.get('payload') if isinstance(guard, dict) else None
    if not (isinstance(payload, list) and payload
            and all(isinstance(rule, str) and rule.strip() for rule in payload)):
        raise ValueError('mihomo_classical_payload_invalid')
    config = {
        'rule-providers': {'guard': {'type': 'inline', 'behavior': GUARD.mihomo_behavior, 'payload': payload}},
        'rules': [f'RULE-SET,guard,{GUARD.action}', 'MATCH,DIRECT'],
    }
    path = work / 'mihomo-guard.yaml'
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    checked([mihomo, '-t', '-d', work, '-f', path])


def localized_sing_box(source, generated, work):
    config = json.loads(source.read_text(encoding='utf-8'))
    config['outbounds'] += [{'type': 'socks', 'tag': 'PROXY', 'server': '127.0.0.1', 'server_port': 9}]
    config['experimental']['cache_file']['path'] = str(work / 'cache.db')
    return config


def to_local_rule_sets(config, generated, replacements=None):
    for rule_set in config['route']['rule_set']:
        source_path = rule_set.pop('url').removeprefix(BASE_URL)
        if replacements and source_path in replacements:
            source_path = replacements[source_path]
            rule_set['format'] = 'binary'
        rule_set['path'] = str(generated / source_path)
        rule_set['type'] = 'local'
        rule_set.pop('http_client'); rule_set.pop('update_interval')
    return config


def check_sing_box_membership(sing_box, generated, binaries):
    # These expectations already apply to source selection and are independent of the exporter.
    cases = [
        ('reject', 'ad.doubleclick.net', True), ('reject', 'github.com', False),
        ('private', 'www.google.com', False), ('proxy', 'www.google.com', True),
        ('direct', 'www.google.com', False), ('direct', 'www.baidu.com', True),
        ('direct', 'localhost', True), ('direct', 'router.home.arpa', True),
        ('webrtc-guard', 'stun.example', True), ('webrtc-guard', 'mail.example', False),
    ]
    china = json.loads((generated / RESOURCE_BY_ID['cn-ip'].path('sing-box')).read_bytes())
    prefixes = [ipaddress.ip_network(value) for rule in china['rules'] for value in rule['ip_cidr']]
    for version, local in ((4, '127.0.0.1'), (6, '::1')):
        address = str(next(net.network_address for net in prefixes if net.version == version))
        for sample, inside in ((address, True), (local, False)):
            cases.extend([('cn-ip', sample, inside), ('non-cn-ip', sample, not inside)])
    for dataset, sample, expected in cases:
        result = subprocess.run(
            [sing_box, '--disable-color', 'rule-set', 'match', '--format', 'binary',
             binaries[dataset], sample],
            check=True, capture_output=True, text=True, timeout=90,
        )
        # v1.14.4 exits successfully for both outcomes and emits one line per matching rule.
        lines = (result.stdout + result.stderr).splitlines()
        recognized = all(re.fullmatch(r'match rules\.\[\d+\]: .+', line) for line in lines)
        if not recognized or bool(lines) != expected:
            raise ValueError(f'sing-box membership mismatch for {dataset}, {sample}: {(result.stdout + result.stderr)[:300]}')
    return len(cases)


def decoded_mrs(mihomo, rule, binary, output):
    checked([mihomo, 'convert-ruleset', rule.mihomo_behavior, 'mrs', binary, output])
    return sorted(output.read_bytes().splitlines())


def decoded_srs(sing_box, binary, output):
    checked([sing_box, 'rule-set', 'decompile', '--output', output, binary])
    contents = json.loads(output.read_bytes())
    for rule in contents['rules']:
        # These leaf matchers represent sets. The compiled tries may enumerate
        # atoms in a different order, while the rule structure must agree.
        for key in ('domain', 'domain_suffix', 'ip_cidr', 'port', 'domain_keyword'):
            values = rule.get(key)
            if isinstance(values, list):
                values.sort()
    return contents


def candidate_replacements(generated):
    expected = {(identity, fmt): path for identity, fmt, path in format_variants()}
    index = json.loads((generated / 'index.json').read_bytes())
    if 'format_variants' not in index:
        if any((generated / path).exists() for path in expected.values() if path not in LEGACY_FILES):
            raise ValueError('Candidate variants missing from format_variants index')
        return {}
    records = index['format_variants']
    if len(records) != len(expected) or {(r['id'], r['format']): r['path'] for r in records} != expected:
        raise ValueError('Candidate variant paths differ from the catalog')
    replacements = {}
    for (identity, fmt), path in expected.items():
        if not (generated / path).is_file():
            raise ValueError(f'Missing candidate variant: {path}')
        replacements[RESOURCE_BY_ID[identity].path(VARIANT_SOURCE_FORMAT[fmt])] = path
    return replacements


def check_binaries(generated, work, mihomo, sing_box, replacements):
    # Compiling and decoding both sides lets the core normalize redundant
    # domains and IP prefixes. Compressed bytes are not a stable rule identity.
    for rule in BUSINESS:
        text = rule.path('mihomo')
        reference = work / (rule.id + '.mrs')
        checked([mihomo, 'convert-ruleset', rule.mihomo_behavior, 'yaml', generated / text, reference])
        if replacements:
            actual = generated / replacements[text]
            if decoded_mrs(mihomo, rule, reference, work / 'reference.txt') != decoded_mrs(mihomo, rule, actual, work / 'actual.txt'):
                raise ValueError(f'MRS contents differ from the same-generation source: {actual.name}')
    binaries = {}
    for rule in (*BUSINESS, DNS_HELPER, GUARD):
        text = rule.path('sing-box')
        reference = work / (rule.id + '.srs')
        checked([sing_box, 'rule-set', 'compile', '--output', reference, generated / text])
        binary = generated / replacements[text] if replacements else reference
        if replacements:
            if decoded_srs(sing_box, reference, work / 'reference.json') != decoded_srs(sing_box, binary, work / 'actual.json'):
                raise ValueError(f'SRS contents differ from the same-generation source: {binary.name}')
        binaries[rule.id] = binary
    return check_sing_box_membership(sing_box, generated, binaries)


def validate(generated, mihomo, sing_box, surge=None):
    import yaml  # Validation only; the data builder has no third-party dependencies.
    examples = Path(__file__).resolve().parents[1] / 'examples/full'
    with tempfile.TemporaryDirectory(prefix='routing-native-') as folder:
        work = Path(folder)
        replacements = candidate_replacements(generated)
        membership_cases = check_binaries(generated, work, mihomo, sing_box, replacements)
        check_mihomo_guard(mihomo, generated, work)

        path = work / 'mihomo.yaml'
        path.write_text(yaml.safe_dump(localized_mihomo(examples / 'mihomo.yaml', generated, work), sort_keys=False))
        checked([mihomo, '-t', '-d', work, '-f', path])

        config = localized_sing_box(examples / 'sing-box.json', generated, work)
        remote = work / 'sing-box-remote.json'
        remote.write_text(json.dumps(config))
        checked([sing_box, 'check', '-c', remote])
        path = work / 'sing-box-local.json'
        path.write_text(json.dumps(to_local_rule_sets(config, generated)))
        checked([sing_box, 'check', '-c', path])

        if replacements:
            path = work / 'mihomo-mrs.yaml'
            config = localized_mihomo(examples / 'mihomo.yaml', generated, work, replacements)
            path.write_text(yaml.safe_dump(config, sort_keys=False))
            checked([mihomo, '-t', '-d', work, '-f', path])
            path = work / 'sing-box-srs.json'
            config = localized_sing_box(examples / 'sing-box.json', generated, work)
            path.write_text(json.dumps(to_local_rule_sets(config, generated, replacements)))
            checked([sing_box, 'check', '-c', path])
        if surge:
            content = (examples / 'surge.conf').read_text(encoding='utf-8').replace(BASE_URL, str(generated) + '/')
            path = work / 'surge.conf'
            path.write_text('[Proxy]\nPROXY = socks5, 127.0.0.1, 9\n' + content)
            checked([surge, '--check', path])
            if replacements:
                # Only top-level routing DOMAIN-SETs are under test. Host/DNS and
                # nested extended-matching uses retain their existing RULE-SETs.
                for rule in BUSINESS:
                    source_path = rule.path('surge')
                    if source_path in replacements:
                        content = content.replace('\nRULE-SET,' + str(generated / source_path) + ',',
                                                  '\nDOMAIN-SET,' + str(generated / replacements[source_path]) + ',')
                path.write_text('[Proxy]\nPROXY = socks5, 127.0.0.1, 9\n' + content)
                checked([surge, '--check', path])
    return {'mihomo_datasets': len(BUSINESS), 'mihomo_classical_guards': 1, 'sing_box_datasets': len(BUSINESS) + 2,
            'verified_mrs': len(BUSINESS) if replacements else 0, 'verified_srs': len(BUSINESS) + 2 if replacements else 0,
            'full_template_checks': 3 + bool(surge) + (2 + bool(surge) if replacements else 0),
            'sing_box_membership_cases': membership_cases, 'surge_checked': bool(surge),
            'shadowrocket': 'structure_only', 'live_client_changed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated', type=Path, default=Path('generated'))
    parser.add_argument('--mihomo', required=True)
    parser.add_argument('--sing-box', required=True)
    parser.add_argument('--surge')
    args = parser.parse_args()
    print(json.dumps(validate(args.generated.resolve(), args.mihomo, args.sing_box, args.surge)))


if __name__ == '__main__':
    main()
