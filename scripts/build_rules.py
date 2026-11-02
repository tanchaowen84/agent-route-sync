#!/usr/bin/env python3
"""Build one verified routing-data generation; never copy upstream templates."""
import datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import time
import urllib.request
from public_formats import LOCAL, export

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / 'sources.json').read_text(encoding='utf-8'))
SOURCES = {key: 'https://raw.githubusercontent.com/' + value['repository'] + '/' + value['ref'] + '/' + value['path'] for key, value in REGISTRY['inputs'].items()}

DOMAIN = re.compile(r'^[-_a-zA-Z0-9]+(?:\.[-_a-zA-Z0-9]+)*$')


def fetch(url):
    for attempt in range(3):
        try:
            headers = {'User-Agent': 'agentroute-rules-builder'}
            # Anonymous API calls share the CI runner's rate limit. The token never goes to raw downloads.
            if url.startswith('https://api.github.com/') and os.environ.get('GITHUB_TOKEN'):
                headers['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                limit = 16 * 1024 * 1024
                data = response.read(limit + 1)
                if not (response.status == 200 and data):
                    raise ValueError('download_invalid')
                if len(data) > limit:
                    raise ValueError('rule_source_too_large')
                # A sized read does not raise when the connection drops early, and a
                # line cut short can still parse: /32 becomes /3.
                declared = response.headers.get('Content-Length')
                if declared and len(data) != int(declared):
                    raise ValueError('download_truncated')
                return data.decode('utf-8')
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def domains(text):
    exact, suffix = set(), set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(('#', '//')):
            continue
        if line.startswith(('regexp:', 'keyword:')):
            continue
        target = exact if line.startswith('full:') else suffix
        if line.startswith(('full:', 'domain:')):
            line = line.split(':', 1)[1]
        if line.startswith('.'):
            line = line[1:]
            target = suffix
        if not (DOMAIN.fullmatch(line)):
            raise ValueError('invalid_domain_source_line')
        target.add(line.lower())
    return exact, suffix


def parents(domain):
    parts = domain.split('.')
    return ['.'.join(parts[index:]) for index in range(len(parts))]


def exclude_foreign(exact, suffix, foreign_exact, foreign_suffix):
    foreign_parents = {parent for domain in foreign_exact | foreign_suffix for parent in parents(domain)}
    exact = {domain for domain in exact if domain not in foreign_exact
             and not any(parent in foreign_suffix for parent in parents(domain))}
    # A positive suffix cannot express a foreign child exception. Remove such
    # broad entries (including the .cn umbrella); specific domestic domains and
    # China IPs still match the same DIRECT dataset, with proxy DNS for IP lookup.
    suffix = {domain for domain in suffix if domain not in foreign_parents
              and not any(parent in foreign_suffix for parent in parents(domain))}
    return exact, suffix


def matches(domain, exact, suffix):
    return domain in exact or any(parent in suffix for parent in parents(domain))


def advertising_domains(text):
    exact, suffix = domains(text)
    if not 1000 <= len(exact) + len(suffix) <= 500000:
        raise ValueError('advertising_dataset_empty_or_oversized')
    for name in exact | suffix:
        if '.' not in name or name in {'com.cn', 'net.cn', 'org.cn', 'co.uk', 'com.au', 'co.jp'}:
            raise ValueError('advertising_domain_too_broad')
        try:
            ipaddress.ip_address(name)
        except ValueError:
            pass
        else:
            raise ValueError('advertising_ip_forbidden')
    for host in ('www.baidu.com', 'www.qq.com', 'login.weixin.qq.com', 'www.taobao.com', 'www.jd.com',
                 'www.google.com', 'api.github.com', 'www.apple.com', 'login.microsoftonline.com',
                 'claude.ai', 'anthropic.com', 'claude.com'):
        if matches(host, exact, suffix):
            raise ValueError('advertising_blocks_protected_site')
    if not matches('ad.doubleclick.net', exact, suffix):
        raise ValueError('advertising_coverage_lost')
    return sorted(exact), sorted(suffix)


def private_domains(text):
    exact, suffix = domains(text)
    local_tlds = {'internal', 'localdomain', 'example', 'invalid', 'localhost', 'test', 'local', 'lan'}
    if not 1 <= len(exact) + len(suffix) <= 10000:
        raise ValueError('private_dataset_empty_or_oversized')
    for name in exact | suffix:
        if ('.' not in name and name not in local_tlds) or name in {'com.cn', 'net.cn', 'org.cn', 'co.uk', 'com.au', 'co.jp'}:
            raise ValueError('private_domain_too_broad')
    for host in ('www.google.com', 'api.github.com', 'www.apple.com', 'icloud.com',
                 'claude.ai', 'anthropic.com', 'claude.com'):
        if matches(host, exact, suffix):
            raise ValueError('private_overrides_public_service')
    return exact, suffix


def build(raw, output, versions=None):
    ad_exact, ad_suffix = advertising_domains(raw['advertising_domains'])
    exact, suffix = domains(raw['china_domains'])
    if len(exact) + len(suffix) <= 1000:
        raise ValueError('china_domain_dataset_empty_or_truncated')
    foreign_exact, foreign_suffix = domains(raw['foreign_domains'])
    if len(foreign_exact) + len(foreign_suffix) <= 1000:
        raise ValueError('foreign_domain_dataset_empty_or_truncated')
    before_domain_count = len(exact) + len(suffix)
    exact, suffix = exclude_foreign(exact, suffix, foreign_exact, foreign_suffix)
    excluded_count = before_domain_count - len(exact) - len(suffix)
    if any(matches(domain, exact, suffix) for domain in
           ('www.gstatic.com', 'www.google.com', 'www.wikipedia.org', 'api.github.com')):
        raise ValueError('foreign_domain_would_be_direct')
    if not all(matches(domain, exact, suffix) for domain in
               ('www.baidu.com', 'www.qq.com', 'www.taobao.com', 'www.jd.com')):
        raise ValueError('domestic_domain_would_be_proxied')
    private_exact, private_suffix = private_domains(raw['private_domains'])
    exact.update(private_exact)
    suffix.update(private_suffix | {'local', 'lan', 'home.arpa'})
    exact.add('localhost')
    networks = set(map(str, LOCAL))
    china_network_count = 0
    for line in raw['china_ip'].splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        network = ipaddress.ip_network(line, strict=False)
        if network.prefixlen == 0:
            raise ValueError('universal_direct_route_forbidden')
        networks.add(str(network))
        china_network_count += 1
    if china_network_count <= 1000:
        raise ValueError('china_ip_dataset_empty_or_truncated')
    ordered_networks = sorted(networks, key=lambda n: (ipaddress.ip_network(n).version,
                                                      int(ipaddress.ip_network(n).network_address),
                                                      ipaddress.ip_network(n).prefixlen))
    output = Path(output)
    output.mkdir(exist_ok=True)
    rules = ['# Domestic and local DIRECT dataset. Other traffic uses the client proxy.']
    rules += ['DOMAIN,' + name for name in sorted(exact)]
    rules += ['DOMAIN-SUFFIX,' + name for name in sorted(suffix)]
    rules += [('IP-CIDR6' if ':' in network else 'IP-CIDR') + ',' + network
              for network in ordered_networks]
    (output / 'direct.list').write_bytes(('\n'.join(rules) + '\n').encode("utf-8"))
    (output / 'direct.domains').write_bytes(('\n'.join(sorted(exact) + ['.' + name for name in sorted(suffix)]) + '\n').encode("utf-8"))
    (output / 'private.domains').write_bytes(('\n'.join(sorted(private_exact) + ['.' + name for name in sorted(private_suffix)]) + '\n').encode("utf-8"))
    # Preserve the exact foreign input used for conflict removal in this build.
    # Consumers must not combine this generation with a moving upstream branch.
    (output / 'proxy-source.txt').write_bytes((raw['foreign_domains']).encode("utf-8"))
    (output / 'direct.ipcidr').write_bytes(('\n'.join(
        ('IP-CIDR6' if ':' in network else 'IP-CIDR') + ',' + network for network in ordered_networks) + '\n').encode("utf-8"))
    source = {'version': 3, 'rules': [{'domain': sorted(exact)},
                                     {'domain_suffix': sorted(suffix)},
                                     {'ip_cidr': ordered_networks}]}
    (output / 'direct.json').write_bytes((json.dumps(source, separators=(',', ':')) + '\n').encode("utf-8"))
    (output / 'reject.domains').write_bytes(('\n'.join(ad_exact + ['.' + name for name in ad_suffix]) + '\n').encode("utf-8"))
    (output / 'reject.list').write_bytes(('\n'.join(['DOMAIN,' + name for name in ad_exact] +
                                                ['DOMAIN-SUFFIX,' + name for name in ad_suffix]) + '\n').encode("utf-8"))
    ad_conditions = ([{'domain': ad_exact}] if ad_exact else []) + ([{'domain_suffix': ad_suffix}] if ad_suffix else [])
    (output / 'reject.json').write_bytes((json.dumps({'version': 3, 'rules': ad_conditions}, separators=(',', ':')) + '\n').encode("utf-8"))
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    public_files = export(output, {
        'direct': (exact, suffix), 'proxy': (foreign_exact, foreign_suffix),
        'private': (private_exact, private_suffix), 'reject': (ad_exact, ad_suffix),
    }, ordered_networks, generated_at)
    manifest = {
        'generated_at_utc': generated_at,
        'scope': 'domestic_direct_and_adblock', 'sources': SOURCES,
        'source_sha256': {name: hashlib.sha256(text.encode()).hexdigest() for name, text in raw.items()},
        'counts': {'exact_domains': len(exact), 'suffix_domains': len(suffix), 'ip_prefixes': len(networks),
                   'adblock_domains': len(ad_exact) + len(ad_suffix),
                   'private_domains': len(private_exact) + len(private_suffix)},
        'excluded_overseas_domain_entries': excluded_count,
        'files': {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                  for name in ['direct.list', 'direct.json', 'direct.domains', 'direct.ipcidr',
                               'reject.domains', 'reject.list', 'reject.json', 'private.domains', 'proxy-source.txt']},
        'application_or_country_groups_generated': False,
        'public_formats_version': 1,
    }
    manifest['files'].update(public_files)
    manifest['schema_version'] = 1
    manifest['source_versions'] = versions or {}
    manifest['skipped_syntax'] = {key: {kind: sum(line.strip().startswith(kind + ':') for line in text.splitlines()) for kind in ('regexp', 'keyword')} for key, text in raw.items() if key != 'china_ip'}
    manifest['freshness_scope'] = 'this_publication_not_upstream_commit_age'
    for name in ['LICENSE', 'sources.json', 'NOTICE.md'] + [copy['path'] for p in REGISTRY['projects'] for copy in p.get('license_copies', [])]:
        data = (ROOT / name).read_bytes()
        (output / name).parent.mkdir(parents=True, exist_ok=True)
        (output / name).write_bytes(data)
        manifest['files'][name] = hashlib.sha256(data).hexdigest()
    (output / 'manifest.json').write_bytes((json.dumps(manifest, indent=2) + '\n').encode("utf-8"))
    if {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()} != set(manifest['files']) | {'manifest.json'}:
        raise ValueError('generation_inventory_invalid')
    return manifest


def main():
    heads, raw, versions = {}, {}, {}
    for key, entry in REGISTRY['inputs'].items():
        repo, ref = entry['repository'], entry['ref']
        if (repo, ref) not in heads:
            sha = json.loads(fetch('https://api.github.com/repos/' + repo + '/commits/' + ref))['sha']
            if not re.fullmatch(r'[a-f0-9]{40}', sha): raise ValueError('invalid_upstream_sha')
            heads[repo, ref] = sha
        sha = heads[repo, ref]
        url = 'https://raw.githubusercontent.com/' + repo + '/' + sha + '/' + entry['path']
        raw[key] = fetch(url)
        versions[key] = {'repository': repo, 'commit': sha, 'path': entry['path'], 'url': url}
    manifest = build(raw, Path('generated'), versions)
    print(json.dumps(manifest['counts']))


if __name__ == '__main__':
    main()
