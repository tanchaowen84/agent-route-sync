"""Public rule identities, their published paths and client formats."""
from dataclasses import dataclass
from typing import Optional


REPOSITORY = 'ryuu-restart/agent-route'
BASE_URL = f'https://raw.githubusercontent.com/{REPOSITORY}/release/'
FORMATS = {'mihomo': '.yaml', 'surge': '.list', 'sing-box': '.json'}
# Stable v1 resource order in the index and in public_formats.FORMATS.
INDEX_FORMAT_ORDER = ('surge', 'mihomo', 'sing-box')


@dataclass(frozen=True)
class RuleSet:
    id: str
    label: str
    action: Optional[str]
    kind: str
    formats: tuple[str, ...] = INDEX_FORMAT_ORDER

    @property
    def mihomo_behavior(self):
        if 'mihomo' in self.formats:
            return {'domain': 'domain', 'ip_cidr': 'ipcidr', 'ports_and_keywords': 'classical'}[self.kind]
        return None

    def path(self, fmt):
        if fmt not in self.formats:
            raise ValueError(f'{self.id} is not published for {fmt}')
        return f'{fmt}/{self.id}{FORMATS[fmt]}'


BUSINESS = (
    RuleSet('private', '内网直连', 'DIRECT', 'domain'),
    RuleSet('reject', '广告拦截', 'REJECT', 'domain'),
    RuleSet('proxy', '海外代理', 'PROXY', 'domain'),
    RuleSet('direct', '国内直连', 'DIRECT', 'domain'),
    RuleSet('cn-ip', '中国 IP 兜底', 'DIRECT', 'ip_cidr'),
)
GUARD = RuleSet('webrtc-guard', 'WebRTC 探测拦截', 'REJECT', 'ports_and_keywords')
GUARD_SCOPE = 'common_stun_ports_and_domain_keywords'
DNS_HELPER = RuleSet('non-cn-ip', 'sing-box DNS answer filter only; not a routing dataset',
                     None, 'ip_cidr', ('sing-box',))
RESOURCE_BY_ID = {rule.id: rule for rule in (*BUSINESS, GUARD, DNS_HELPER)}
DATASETS = tuple(rule.id for rule in BUSINESS)
ORDER = ('user-and-node-exceptions', 'lan', GUARD.id, 'dns-server-paths', *DATASETS, 'final-proxy')
LEGACY_FILES = ('direct.list', 'direct.json', 'direct.domains', 'direct.ipcidr',
                'reject.domains', 'reject.list', 'reject.json', 'private.domains', 'proxy-source.txt')

CLIENTS = {'mihomo': ('mihomo', 'native_compile_and_config'), 'sing-box': ('sing-box', 'native_compile_and_config'),
           'surge': ('surge', 'optional_local_check'), 'shadowrocket': ('surge', 'structure_only')}
CLIENT_FORMATS = {client: fmt for client, (fmt, _) in CLIENTS.items()}
VALIDATION_SCOPE = {client: scope for client, (_, scope) in CLIENTS.items()}
VARIANT_SOURCE_FORMAT = {'mrs': 'mihomo', 'srs': 'sing-box', 'domain-set': 'surge'}


def format_variants():
    """Optional public formats, in v1 publication order, independent of a downloaded index."""
    for rule in BUSINESS:
        yield rule.id, 'mrs', f'mihomo/{rule.id}.mrs'
    for rule in (*BUSINESS, GUARD, DNS_HELPER):
        yield rule.id, 'srs', f'sing-box/{rule.id}.srs'
    for rule in BUSINESS:
        if rule.kind == 'domain':
            yield rule.id, 'domain-set', f'{rule.id}.domains'
