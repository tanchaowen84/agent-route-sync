"""Credential-free, native rule-set exports from one validated source generation."""
import hashlib
import ipaddress
import json

from rule_catalog import (BASE_URL, BUSINESS, DATASETS, DNS_HELPER, FORMATS as EXTENSIONS,
                          GUARD, GUARD_SCOPE, INDEX_FORMAT_ORDER, ORDER, VALIDATION_SCOPE)

# Keep the original public_formats exports and iteration order for existing callers.
FORMATS = {fmt: EXTENSIONS[fmt] for fmt in INDEX_FORMAT_ORDER}

# Common probe mitigation, not protocol detection or a complete WebRTC block.
# Adapted from Niklaus88/Clash-Config; see sources.json and the preserved MIT licence.
WEBRTC_PORTS = (3478, 5349, *range(19302, 19310))
WEBRTC_KEYWORDS = ('stun',)
LOCAL = tuple(map(ipaddress.ip_network, (
    '0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
    '169.254.0.0/16', '172.16.0.0/12', '192.168.0.0/16', '224.0.0.0/4',
    '::/128', '::1/128', 'fc00::/7', 'fe80::/10', 'ff00::/8')))
SYNTHETIC = tuple(map(ipaddress.ip_network, ('198.18.0.0/15', 'fc00::/18', 'fd00:6152::/64')))
# Real data is never close to this wide. A wider prefix means a damaged source line,
# and publishing it would send a large part of the internet DIRECT for every client.
BROADEST_CHINA_PREFIX = {4: 8, 6: 16}


def public_china_networks(networks, minimum=1000):
    """Filter public China IP prefixes while excluding local and synthetic ranges."""
    result = []
    for value in networks:
        network = ipaddress.ip_network(value, strict=True)
        if network in LOCAL:
            continue
        if any(network.version == item.version and network.overlaps(item)
               for item in LOCAL + SYNTHETIC):
            raise ValueError('china_ip_overlaps_local_or_synthetic_range')
        if network.prefixlen < BROADEST_CHINA_PREFIX[network.version]:
            raise ValueError('china_ip_prefix_too_broad')
        result.append(network)
    if any(sum(n.version == version for n in result) < minimum for version in (4, 6)):
        raise ValueError('china_ip_address_family_empty_or_truncated')
    return sorted(result, key=lambda n: (n.version, int(n.network_address), n.prefixlen))


def outside_networks(networks):
    """IP ranges used to detect an address outside China in a single DNS response."""
    result = []
    for version, cls, bits in ((4, ipaddress.IPv4Address, 32), (6, ipaddress.IPv6Address, 128)):
        cursor = 0
        for network in ipaddress.collapse_addresses(n for n in networks if n.version == version):
            begin, end = int(network.network_address), int(network.broadcast_address)
            if cursor < begin:
                result.extend(ipaddress.summarize_address_range(cls(cursor), cls(begin - 1)))
            cursor = max(cursor, end + 1)
        if cursor < 2 ** bits:
            result.extend(ipaddress.summarize_address_range(cls(cursor), cls(2 ** bits - 1)))
    return sorted(result, key=lambda n: (n.version, int(n.network_address), n.prefixlen))


def write_file(output, name, content):
    data = content.encode('utf-8')
    path = output / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def write_resource(output, files, rule, fmt, content, count):
    name = rule.path(fmt)
    files[name] = write_file(output, name, content)
    return {'path': name, 'url': BASE_URL + name, 'sha256': files[name], 'entries': count}


def sing_box_source(conditions):
    return json.dumps({'version': 3, 'rules': conditions}, separators=(',', ':')) + '\n'


def write_rule_set(output, files, rule, surge_lines, mihomo_payload, conditions):
    contents = {
        'surge': '\n'.join(surge_lines) + '\n',
        'mihomo': 'payload:\n' + ''.join('  - ' + json.dumps(value) + '\n' for value in mihomo_payload),
        'sing-box': sing_box_source(conditions),
    }
    return {fmt: write_resource(output, files, rule, fmt, contents[fmt], len(mihomo_payload))
            for fmt in rule.formats}


def export_webrtc_guard(output):
    keywords = ['DOMAIN-KEYWORD,' + word for word in WEBRTC_KEYWORDS]
    surge = [f'DEST-PORT,{port}' for port in WEBRTC_PORTS] + keywords
    mihomo = [f'DST-PORT,{port}' for port in WEBRTC_PORTS] + keywords
    # Separate rules are OR'ed. Combining both fields would miss IP literals
    # and custom ports with a known hostname.
    conditions = [{'port': list(WEBRTC_PORTS)}, {'domain_keyword': list(WEBRTC_KEYWORDS)}]
    files = {}
    resources = write_rule_set(output, files, GUARD, surge, mihomo, conditions)
    return files, {'id': GUARD.id, 'action': GUARD.action, 'mihomo_behavior': GUARD.mihomo_behavior,
                   'scope': GUARD_SCOPE,
                   'ports': list(WEBRTC_PORTS), 'domain_keywords': list(WEBRTC_KEYWORDS),
                   'requires': ['traffic_captured_by_client', 'before_business_rules'],
                   'limitations': ['not_all_webrtc', 'may_affect_calls_and_p2p',
                                   'ipv6_capture_requires_device_validation'],
                   'resources': resources}


def export(output, domain_groups, networks, generated_at):
    files, entries = {}, []
    public_networks = public_china_networks(networks)
    for rule in BUSINESS:
        if rule.kind == 'ip_cidr':
            payload = list(map(str, public_networks))
            lines = [('IP-CIDR6,' if ':' in value else 'IP-CIDR,') + value for value in payload]
            conditions = [{'ip_cidr': payload}]
        else:
            exact, suffix = [sorted(set(values)) for values in domain_groups[rule.id]]
            payload = exact + ['+.' + value for value in suffix]
            lines = ['DOMAIN,' + value for value in exact] + ['DOMAIN-SUFFIX,' + value for value in suffix]
            conditions = ([{'domain': exact}] if exact else []) + ([{'domain_suffix': suffix}] if suffix else [])
        resources = write_rule_set(output, files, rule, lines, payload, conditions)
        entries.append({'id': rule.id, 'action': rule.action,
                        'mihomo_behavior': rule.mihomo_behavior, 'resources': resources})
    protection_files, protection = export_webrtc_guard(output)
    files.update(protection_files)
    outside = list(map(str, outside_networks(public_networks)))
    helper = write_resource(output, files, DNS_HELPER, 'sing-box', sing_box_source([{'ip_cidr': outside}]), len(outside))
    index = {
        'schema_version': 1, 'scope': 'public_routing_data_only',
        'generated_at_utc': generated_at, 'base_url': BASE_URL,
        'manifest_url': BASE_URL + 'manifest.json',
        'agent_guide_url': 'https://raw.githubusercontent.com/ryuu-restart/agent-route/master/AGENTS.md',
        'privacy_guide_url': 'https://github.com/ryuu-restart/agent-route/blob/master/docs/DNS-WEBRTC.md',
        'update_interval_seconds': 86400, 'max_source_age_seconds': 172800,
        'order': list(ORDER),
        'datasets': entries,
        'protections': [protection],
        'helpers': [{'id': DNS_HELPER.id, 'purpose': DNS_HELPER.label, **helper}],
        'credentials_required': False, 'contains_nodes': False,
        'schemas': {'index': 'https://raw.githubusercontent.com/ryuu-restart/agent-route/master/schemas/index.schema.json', 'manifest': 'https://raw.githubusercontent.com/ryuu-restart/agent-route/master/schemas/manifest.schema.json'},
        'sync_tool': {'path': 'scripts/sync_rules.py', 'minimum_python': '3.11', 'commands': ['sync', 'verify', 'status', 'rollback'], 'edits_client_configuration': False},
        'validation_scope': VALIDATION_SCOPE,
    }
    files['index.json'] = write_file(output, 'index.json', json.dumps(index, ensure_ascii=False, indent=2) + '\n')
    return files
