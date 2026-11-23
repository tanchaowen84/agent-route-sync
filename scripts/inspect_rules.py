"""Explain the managed records in complete local AgentRoute v1 snapshots."""
import sys

# Inspection does not need to write bytecode into the source checkout.
if __name__ == '__main__':
    sys.dont_write_bytecode = True

import argparse
from dataclasses import dataclass
import hashlib
import ipaddress
import json
from pathlib import Path

from jsonschema import ValidationError

from build_rules import DOMAIN
from check_contracts import validate_generated
from rule_catalog import CLIENT_FORMATS, GUARD, VALIDATION_SCOPE


SCOPE = 'published_static_datasets_and_protections'
EVIDENCE_DOC = 'docs/CLIENT-EVIDENCE.md'
# Dated observations have narrower coverage than the project's declared validation scope.
OBSERVATIONS = {
    'mihomo': ('1.19.32', 'native_parser', 'MRS compilation, inline classical guard and example configuration'),
    'sing-box': ('1.14.4', 'isolated_runtime', 'synthetic DNS and loopback connections using the example'),
    'surge': ('Mac 6.12.0', 'native_parser', 'inline guard via the official profile validation service'),
    'shadowrocket': ('2.2.62', 'release_notes', 'DEST-PORT parser fix mentioned by the publisher'),
}


class UnsupportedCondition(ValueError):
    """The snapshot is readable, but its rule language falls outside our subset."""


@dataclass
class Snapshot:
    directory: Path
    index: dict
    identity: dict

    @classmethod
    def open(cls, directory):
        path = directory / 'manifest.json'
        if directory.is_symlink() or not directory.is_dir() or path.is_symlink() or not path.is_file():
            raise ValueError('Expected a regular snapshot directory and manifest')
        manifest = path.read_bytes()
        try:
            index, checked = validate_generated(directory, historical=True)
        except ValidationError as exc:
            if list(exc.absolute_path) == ['schema_version'] and exc.validator == 'const':
                raise ValueError('Only v1 index and manifest schemas are supported') from exc
            raise
        if path.read_bytes() != manifest:
            raise ValueError('Snapshot manifest changed during validation')
        return cls(directory, index, {
            'manifest_sha256': hashlib.sha256(manifest).hexdigest(),
            'schema_version': index['schema_version'], 'generated_at_utc': index['generated_at_utc'],
            'verified_files': checked['verified_files'],
        })

    def groups(self):
        by_id = {group['id']: group for group in self.index['datasets'] + self.index.get('protections', [])}
        return {name: by_id[name] for name in self.index['order'] if name in by_id}

    def formats(self, name, groups):
        resources = dict(groups.get(name, {}).get('resources', {}))
        for variant in self.index.get('format_variants', []):
            if variant['id'] == name:
                resources[variant['format']] = variant
        return resources

    def records(self, group):
        resource = group['resources']['sing-box']
        path = self.directory / resource['path']
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            raise ValueError('Rule source changed since snapshot validation')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != resource['sha256']:
            raise ValueError('Rule source changed since snapshot validation')
        source = json.loads(raw)
        if not isinstance(source, dict) or type(source.get('version')) is not int:
            raise ValueError('Invalid rule source version')
        if set(source) != {'version', 'rules'} or source['version'] != 3:
            raise UnsupportedCondition('Expected sing-box source version 3')
        if not isinstance(source['rules'], list):
            raise ValueError('Invalid rule source')
        if group['id'] == GUARD.id:
            allowed = {'port', 'domain_keyword'}
        elif group['mihomo_behavior'] == 'ipcidr':
            allowed = {'ip_cidr'}
        else:
            allowed = {'domain', 'domain_suffix'}
        records = []
        for rule in source['rules']:
            if not isinstance(rule, dict) or len(rule) != 1 or not rule.keys() <= allowed:
                raise UnsupportedCondition('Unsupported or compound condition in ' + resource['path'])
            kind, values = next(iter(rule.items()))
            if not isinstance(values, list) or not values:
                raise ValueError('Invalid record list in ' + resource['path'])
            records.extend((kind, canonical_value(kind, value)) for value in values)
        if len(records) != resource['entries'] or len(set(records)) != len(records):
            raise ValueError('Rule source count or uniqueness differs from the index')
        if group['id'] == GUARD.id:
            declared = {('port', port) for port in group['ports']}
            declared.update(('domain_keyword', word.lower()) for word in group['domain_keywords'])
            if set(records) != declared:
                raise ValueError('Protection conditions differ from the index')
        return records


def canonical_value(kind, value):
    if kind == 'port':
        if type(value) is not int or not 1 <= value <= 65535:
            raise ValueError('Invalid destination port')
        return value
    if not isinstance(value, str) or not value:
        raise ValueError('Invalid rule value')
    if kind == 'ip_cidr':
        return str(ipaddress.ip_network(value))
    if kind in ('domain', 'domain_suffix') and not DOMAIN.fullmatch(value):
        raise UnsupportedCondition('Expected a literal ASCII domain or suffix')
    return value.lower()


def scope(snapshot):
    groups = snapshot.groups()
    return {'records': SCOPE, 'order': list(groups),
            'outside_scope': [step for step in snapshot.index['order'] if step not in groups],
            'source': 'sing-box/source-v3', 'device_action': 'unknown'}


def as_record(pair):
    kind, value = pair
    return {'kind': kind, 'value': value}


def compare(before, after, *, summary_only=False):
    left, right = before.groups(), after.groups()
    changes = {}
    total = {'added': 0, 'removed': 0}
    for name in dict.fromkeys([*right, *left]):
        old = set(before.records(left[name])) if name in left else set()
        new = set(after.records(right[name])) if name in right else set()
        added, removed = new - old, old - new
        total['added'] += len(added)
        total['removed'] += len(removed)
        old_resources = before.formats(name, left)
        new_resources = after.formats(name, right)
        changed_formats = [fmt for fmt in sorted(old_resources.keys() | new_resources.keys())
                           if old_resources.get(fmt, {}).get('sha256') != new_resources.get(fmt, {}).get('sha256')]
        row = {'added': len(added), 'removed': len(removed), 'changed_resource_formats': changed_formats}
        if not summary_only:
            row['added_records'] = list(map(as_record, sorted(added)))
            row['removed_records'] = list(map(as_record, sorted(removed)))
        changes[name] = row
    return {'status': 'compared', 'before': before.identity, 'after': after.identity,
            'scope': SCOPE, 'canonical_source': 'sing-box/source-v3',
            'before_order': list(left), 'after_order': list(right), 'totals': total, 'groups': changes}


def domain_sample(domain):
    if domain is None:
        return None
    domain = domain.removesuffix('.').lower()
    if not DOMAIN.fullmatch(domain) or len(domain) > 253 or any(len(s) > 63 for s in domain.split('.')):
        raise ValueError('Expected an ASCII hostname (use punycode for an internationalized name)')
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        return domain
    raise ValueError('Use --ip for a literal address')


def matches(kind, value, domain, address, port):
    if kind == 'port':
        return port == value
    if kind == 'ip_cidr':
        return address is not None and address in ipaddress.ip_network(value)
    if domain is None:
        return False
    if kind == 'domain_suffix':
        return domain == value or domain.endswith('.' + value)
    if kind == 'domain_keyword':
        return value in domain
    return domain == value


def explain(snapshot, *, domain=None, ip=None, port=None, device=False):
    domain = domain_sample(domain)
    address = ipaddress.ip_address(ip) if ip is not None else None
    if domain is None and address is None:
        raise ValueError('Provide --domain, --ip or both')
    if port is not None:
        canonical_value('port', port)
    result = {'snapshot': snapshot.identity, 'scope': scope(snapshot),
              'sample': {'domain': domain, 'ip': str(address) if address is not None else None, 'port': port},
              'status': 'unknown', 'match': None, 'action': None}
    if device:
        return {**result, 'reason': 'device_configuration_and_runtime_not_observed'}
    for name, group in snapshot.groups().items():
        try:
            records = snapshot.records(group)
        except UnsupportedCondition as exc:
            return {**result, 'reason': str(exc)}
        for kind, value in records:
            if matches(kind, value, domain, address, port):
                return {**result, 'status': 'matched', 'action': group['action'],
                        'match': {'group': name, **as_record((kind, value))}}
        if name == GUARD.id and port is None:
            return {**result, 'reason': 'destination_port_needed_to_rule_out_guard'}
        if group['mihomo_behavior'] == 'ipcidr' and address is None:
            return {**result, 'reason': 'no_domain_match_and_destination_ip_unspecified'}
    return {**result, 'status': 'no_match', 'reason': 'no_record_in_managed_static_lists'}


def evidence(snapshot, client=None):
    declared = snapshot.index.get('validation_scope', {})
    if not isinstance(declared, dict):
        declared = {}
    items = {}
    for name in [client] if client else CLIENT_FORMATS:
        version, layer, coverage = OBSERVATIONS[name]
        items[name] = {'format': CLIENT_FORMATS[name],
                       'snapshot_declared_scope': declared.get(name, 'unknown'),
                       'declaration_recognized': declared.get(name) == VALIDATION_SCOPE[name],
                       'current_project_scope': VALIDATION_SCOPE[name],
                       'separate_observation': {'documented_on': '2026-11-21', 'version': version,
                                                'layer': layer, 'coverage': coverage},
                       'snapshot_verified_here': 'file_integrity_and_v1_contract',
                       'client_run_for_this_snapshot': 'unverified',
                       'target_device_loading_and_route': 'unverified'}
    return {'status': 'evidence', 'snapshot': snapshot.identity, 'clients': items,
            'references': ['docs/INSPECT.md#各客户端验证到哪一层', EVIDENCE_DOC]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    diff = commands.add_parser('diff', help='Compare static membership and resource digests.')
    diff.add_argument('before', type=Path)
    diff.add_argument('after', type=Path)
    diff.add_argument('--summary-only', action='store_true')
    sample = commands.add_parser('explain', help='Find the first matching managed static record.')
    sample.add_argument('snapshot', type=Path)
    sample.add_argument('--domain')
    sample.add_argument('--ip')
    sample.add_argument('--port', type=int)
    sample.add_argument('--device', action='store_true', help='Ask about a real device route (unknown offline).')
    clients = commands.add_parser('evidence', help='Report declared client checks and unverified layers.')
    clients.add_argument('snapshot', type=Path)
    clients.add_argument('--client', choices=tuple(CLIENT_FORMATS))
    args = parser.parse_args(argv)
    context = {}
    try:
        if args.command == 'diff':
            before, after = Snapshot.open(args.before), Snapshot.open(args.after)
            context = {'before': before.identity, 'after': after.identity}
            result = compare(before, after, summary_only=args.summary_only)
        else:
            snapshot = Snapshot.open(args.snapshot)
            context = {'snapshot': snapshot.identity}
            if args.command == 'explain':
                result = explain(snapshot, domain=args.domain, ip=args.ip, port=args.port, device=args.device)
            else:
                result = evidence(snapshot, args.client)
    except UnsupportedCondition as exc:
        result = {**context, 'status': 'unknown', 'reason': str(exc), 'scope': SCOPE}
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, ValidationError) as exc:
        print(json.dumps({'status': 'invalid', 'error': exc.message if isinstance(exc, ValidationError) else str(exc)}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
