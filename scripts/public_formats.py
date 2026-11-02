"""Credential-free, native rule-set exports from one validated source generation."""
import hashlib
import ipaddress
import json

BASE_URL = 'https://raw.githubusercontent.com/ryuu-restart/agent-route/release/'
DATASETS = ('private', 'reject', 'proxy', 'direct', 'cn-ip')
FORMATS = {'surge': '.list', 'mihomo': '.yaml', 'sing-box': '.json'}
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
    """Everything except the China prefixes, so "every answer is in China" can be expressed."""
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


def export(output, domain_groups, networks, generated_at):
    files, entries = {}, []
    for dataset in DATASETS:
        if dataset == 'cn-ip':
            payload = list(map(str, public_china_networks(networks)))
            lines = [('IP-CIDR6,' if ':' in value else 'IP-CIDR,') + value for value in payload]
            source = {'version': 3, 'rules': [{'ip_cidr': payload}]}
        else:
            exact, suffix = [sorted(set(values)) for values in domain_groups[dataset]]
            payload = exact + ['+.' + value for value in suffix]
            lines = ['DOMAIN,' + value for value in exact] + ['DOMAIN-SUFFIX,' + value for value in suffix]
            source = {'version': 3, 'rules': ([{'domain': exact}] if exact else [])
                      + ([{'domain_suffix': suffix}] if suffix else [])}
        contents = {
            'surge': '\n'.join(lines) + '\n',
            'mihomo': 'payload:\n' + ''.join('  - ' + json.dumps(value) + '\n' for value in payload),
            'sing-box': json.dumps(source, separators=(',', ':')) + '\n',
        }
        resources = {}
        for format_name, content in contents.items():
            name = format_name + '/' + dataset + FORMATS[format_name]
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode('utf-8'))
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            resources[format_name] = {'path': name, 'url': BASE_URL + name,
                                      'sha256': files[name], 'entries': len(payload)}
        entries.append({'id': dataset,
                        'action': 'REJECT' if dataset == 'reject' else 'PROXY' if dataset == 'proxy' else 'DIRECT',
                        'mihomo_behavior': 'ipcidr' if dataset == 'cn-ip' else 'domain',
                        'resources': resources})
    helper = 'sing-box/non-cn-ip.json'
    outside = list(map(str, outside_networks(public_china_networks(networks))))
    (output / helper).write_bytes((json.dumps({'version': 3, 'rules': [{'ip_cidr': outside}]},
                                              separators=(',', ':')) + '\n').encode('utf-8'))
    files[helper] = hashlib.sha256((output / helper).read_bytes()).hexdigest()
    index = {
        'schema_version': 1, 'scope': 'public_routing_data_only',
        'generated_at_utc': generated_at, 'base_url': BASE_URL,
        'manifest_url': BASE_URL + 'manifest.json',
        'agent_guide_url': 'https://raw.githubusercontent.com/ryuu-restart/agent-route/master/AGENTS.md',
        'privacy_guide_url': 'https://github.com/ryuu-restart/agent-route/blob/master/docs/DNS-WEBRTC.md',
        'update_interval_seconds': 86400, 'max_source_age_seconds': 172800,
        'order': ['user-and-node-exceptions', 'lan', *DATASETS, 'final-proxy'],
        'datasets': entries,
        'helpers': [{'id': 'non-cn-ip', 'purpose': 'sing-box DNS answer filter only; not a routing dataset',
                     'path': helper, 'url': BASE_URL + helper, 'sha256': files[helper], 'entries': len(outside)}],
        'credentials_required': False, 'contains_nodes': False,
        'schemas': {'index': 'https://raw.githubusercontent.com/ryuu-restart/agent-route/master/schemas/index.schema.json', 'manifest': 'https://raw.githubusercontent.com/ryuu-restart/agent-route/master/schemas/manifest.schema.json'},
        'sync_tool': {'path': 'scripts/sync_rules.py', 'minimum_python': '3.11', 'commands': ['sync', 'verify', 'status', 'rollback'], 'edits_client_configuration': False},
        'validation_scope': {'mihomo': 'native_compile_and_config', 'sing-box': 'native_compile_and_config', 'surge': 'optional_local_check', 'shadowrocket': 'structure_only'},
    }
    path = output / 'index.json'
    (path).write_bytes((json.dumps(index, ensure_ascii=False, indent=2) + '\n').encode("utf-8"))
    files['index.json'] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files
