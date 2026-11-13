"""Offline invariants of the published templates. Native loading lives in validate_native.py."""
import ipaddress
import json
import os
from pathlib import Path
import re
import unittest

import yaml

from public_formats import BASE_URL, DATASETS, SYNTHETIC

ROOT = Path(__file__).resolve().parents[1]
FULL = ROOT / 'examples/full'
TEXT_SUFFIXES = {'.md', '.py', '.json', '.yaml', '.yml', '.conf', '.txt', '.svg'}


def published_text():
    """Every text file this repository publishes, except upstream licences and this file."""
    top = [path for path in ROOT.iterdir() if path.is_file()]
    nested = [path for folder in ('.github', 'assets', 'docs', 'examples', 'schemas', 'scripts', 'subscriptions')
              for path in (ROOT / folder).rglob('*') if path.is_file()]
    for path in sorted(top + nested):
        if path.suffix in TEXT_SUFFIXES and path != Path(__file__).resolve():
            yield path.relative_to(ROOT).as_posix(), path.read_text(encoding='utf-8')


def rules_of(name):
    lines = [line.strip() for line in (FULL / name).read_text(encoding='utf-8').splitlines()]
    begin, end = lines.index('# >>> AgentRoute managed begin'), lines.index('# <<< AgentRoute managed end')
    return [line.removeprefix('- ') for line in lines[begin + 1:end] if line and not line.startswith('#')]


def position(rules, needle):
    return next(i for i, rule in enumerate(rules) if needle in rule)


# Mihomo v1.19.32 (config/config.go) takes the TUN IPv4 address from fake-ip-range with a
# /30, but its IPv6 default is a fixed prefix outside the usual FakeIP pool. The template
# leaves `tun` to the user, so this default applies unless the profile sets another one.
MIHOMO_DEFAULT_TUN_INET6 = ipaddress.ip_network('fdfe:dcba:9876::/126')
# Real local destinations must keep their DIRECT route.
REAL_LAN = tuple(map(ipaddress.ip_address, ('10.1.2.3', '172.16.5.4', '192.168.1.1', '::1',
                                            'fd12:3456:789a::1', 'fe80::1')))


def samples(network):
    first, last = int(network.network_address), int(network.broadcast_address)
    return {ipaddress.ip_address(value) for value in (first, min(first + 1, last), (first + last) // 2, last)}


def first_ip_action(rules, address):
    """First IP rule that a bare destination address meets; domain and rule-set lines cannot match it."""
    for rule in rules:
        if isinstance(rule, dict):
            if set(rule) - {'ip_cidr', 'action', 'outbound'} or 'ip_cidr' not in rule:
                continue
            networks, action = rule['ip_cidr'], 'REJECT' if rule['action'] == 'reject' else rule['outbound']
        else:
            kind, value, action = rule.split(',')[:3]
            if kind not in ('IP-CIDR', 'IP-CIDR6'):
                continue
            networks = [value]
        if any(address.version == ipaddress.ip_network(n).version and address in ipaddress.ip_network(n)
               for n in networks):
            return action
    return None


def core_owned_networks(name):
    """Addresses the proxy core itself hands out under this template, plus the known synthetic ranges."""
    owned = set(SYNTHETIC)
    if name == 'mihomo.yaml':
        dns = yaml.safe_load((FULL / name).read_text(encoding='utf-8'))['dns']
        pool4 = ipaddress.ip_interface(dns['fake-ip-range'])
        owned |= {pool4.network, ipaddress.ip_network(dns['fake-ip-range6'], strict=False),
                  ipaddress.ip_network((pool4.ip, 30), strict=False), MIHOMO_DEFAULT_TUN_INET6}
    if name == 'sing-box.json':
        servers = json.loads((FULL / name).read_text(encoding='utf-8'))['dns']['servers']
        owned |= {ipaddress.ip_network(server[key], strict=False) for server in servers
                  if server['type'] == 'fakeip' for key in ('inet4_range', 'inet6_range')}
    return owned


def template_rules(name):
    if name == 'sing-box.json':
        return json.loads((FULL / name).read_text(encoding='utf-8'))['route']['rules']
    return rules_of(name)


DOMAIN_MATCHERS = {'domain', 'domain_suffix', 'rule_set'}


def sing_box_matches(rule, sample):
    """A domain-only sing-box rule against an FQDN destination that has no addresses yet."""
    keys = set(rule) - {'action', 'outbound', 'server', 'query_type', 'timeout'}
    if not keys:
        return 'query_type' in rule  # an address query with no domain condition
    if keys - DOMAIN_MATCHERS:
        return False  # port, IP, logical and response conditions cannot match this lookup
    return (sample['name'] in rule.get('domain', ())
            or any(sample['name'] == s or sample['name'].endswith('.' + s) for s in rule.get('domain_suffix', ()))
            or bool(sample['sets'] & set(rule.get('rule_set', ()))))


def sing_box_class_resolver(config, sample):
    """The server dns.rules choose for an internal lookup. sing-box 1.14.4 never answers those
    with FakeIP (dns/router.go lookupWithRulesType), and evaluate/respond need a response first."""
    fake = {s['tag'] for s in config['dns']['servers'] if s['type'] == 'fakeip'}
    for rule in config['dns']['rules']:
        if rule.get('action', 'route') == 'route' and rule['server'] not in fake and sing_box_matches(rule, sample):
            return rule['server']
    return config['dns']['final']


def sing_box_destination_resolver(config, sample):
    """Which resolver turns this FQDN into an address on the way out, following sing-box 1.14.4:
    a route `resolve` action without `server` uses dns.rules and the outbound then dials the
    result (route/route.go actionResolve, route/conn.go); otherwise a direct outbound queries its
    own domain_resolver or route.default_domain_resolver straight, skipping dns.rules
    (common/dialer/dialer.go, dns/router.go Lookup). A proxy outbound hands the name on."""
    resolved, outbound = None, config['route']['final']
    for rule in config['route']['rules']:
        if not sing_box_matches(rule, sample) or 'query_type' in rule:
            continue
        if rule['action'] == 'resolve':
            resolved = resolved or rule.get('server') or sing_box_class_resolver(config, sample)
        elif rule['action'] in ('route', 'reject'):
            outbound = rule.get('outbound')
            break
    target = next((o for o in config['outbounds'] if o['tag'] == outbound), None)
    if resolved or target is None:
        return outbound, resolved or 'remote'
    return outbound, resolver_tag(target.get('domain_resolver') or config['route']['default_domain_resolver'])


def resolver_tag(value):
    return value if isinstance(value, str) else value['server']


def comment_before(name, needle):
    """The comment lines directly above the first line that contains needle."""
    lines = (FULL / name).read_text(encoding='utf-8').splitlines()
    index, comment = next(i for i, line in enumerate(lines) if needle in line), []
    while index > 0 and lines[index - 1].lstrip().startswith('#'):
        index -= 1
        comment.insert(0, lines[index])
    return '\n'.join(comment)


# Documentation ranges stand in for cn-ip, so the China-IP fallback is judged by structure,
# not by whatever today's published data happens to contain.
CHINA = tuple(map(ipaddress.ip_network, ('203.0.113.0/24', '2001:db8:cc::/48')))
CN_A, CN_AAAA, OTHER_A, OTHER_AAAA = map(ipaddress.ip_address, (
    '203.0.113.10', '2001:db8:cc::10', '198.51.100.10', '2001:db8:ff::10'))
# Answers for a domain in no list, in the order the resolver returns them.
ANSWERS = {'China A': [CN_A], 'China A + AAAA': [CN_A, CN_AAAA], 'other A + AAAA': [OTHER_A, OTHER_AAAA],
           'China A + other AAAA': [CN_A, OTHER_AAAA], 'other A + China AAAA': [OTHER_A, CN_AAAA],
           'China A + other A': [CN_A, OTHER_A], 'other A + China A': [OTHER_A, CN_A]}
UNLISTED = 'unlisted.example'


def in_china(address):
    return any(address.version == network.version and address in network for network in CHINA)


def ip_rule_holds(kind, value, address):
    return any(address.version == network.version and address in network
               for network in ([ipaddress.ip_network(value)] if kind.startswith('IP-CIDR') else CHINA))


def mihomo_outbounds(config, answers=(), literal=None):
    """Mihomo v1.19.33 for an unlisted domain over FakeIP (its address is cleared, tunnel.go
    preHandleMetadata), or for a connection to an IP literal. The first IP rule without
    no-resolve resolves one address, any IPv4 before IPv6 (resolver.go ResolveIPWithResolver),
    and IP rule sets test only that address. Returns what every possible pick reaches."""
    ip_sets = {name for name, provider in config['rule-providers'].items() if provider['behavior'] == 'ipcidr'}
    outcomes = set()
    for pick in [literal] if literal else [a for a in answers if a.version == 4] or list(answers):
        address = literal
        for rule in config['rules']:
            kind, value, *rest = rule.split(',')
            if kind == 'MATCH':
                outcomes.add(value)
                break
            if kind in ('DOMAIN', 'DOMAIN-SUFFIX'):
                if not literal and (UNLISTED == value or kind == 'DOMAIN-SUFFIX' and UNLISTED.endswith('.' + value)):
                    outcomes.add(rest[0])
                    break
                continue
            if kind == 'RULE-SET' and value not in ip_sets:
                continue  # a domain list holds no unlisted name and never resolves
            if address is None and 'no-resolve' not in rest[1:]:
                address = pick
            if address is not None and ip_rule_holds(kind, value, address):
                outcomes.add(rest[0])
                break
    return outcomes


def surge_outbounds(rules, answers=(), literal=None):
    """Surge's documented evaluation (manual.nssurge.com/rules/ip.html): the first IP rule
    without no-resolve triggers one lookup; IP-CIDR tests the first IPv4 record and IP-CIDR6
    the first IPv6 one. A RULE-SET line's no-resolve covers every rule in the set."""
    first = {version: next((a for a in answers if a.version == version), None) for version in (4, 6)}
    resolved = literal is not None
    for rule in rules:
        if rule.startswith('AND,'):
            continue  # guarded by HOSTNAME-TYPE IPv4 / IPv6, so a domain hostname never matches
        kind, value, policy, *options = rule.split(',') + ['']
        if kind == 'FINAL':
            return {value}
        if kind in ('DOMAIN', 'DOMAIN-SUFFIX') or kind == 'RULE-SET' and not value.endswith('/cn-ip.list'):
            continue  # the hostname is in no domain list
        if not resolved and 'no-resolve' in options:
            continue
        resolved = True
        if literal is not None:
            candidates = [literal]
        elif kind == 'RULE-SET':
            candidates = [a for a in first.values() if a]  # its IP-CIDR and IP-CIDR6 rules
        else:
            record = first[6 if kind == 'IP-CIDR6' else 4]
            candidates = [record] if record else []
        if any(ip_rule_holds(kind, value, a) for a in candidates):
            return {policy}
    return set()


def sing_box_outbounds(config, answers=(), literal=None):
    """sing-box 1.14.4: dns.rules for an A/AAAA lookup of an unlisted name, where IP sets under
    match_response hold when any answer is inside (route/rule/rule_item_cidr.go). A FakeIP answer
    returns the name to the router, where IP rules cannot match it; real answers can each be dialled."""
    servers = {server['tag']: server for server in config['dns']['servers']}
    holds = {'sr-cn-ip': in_china, 'sr-non-cn-ip': lambda address: not in_china(address)}
    real, response = True, None
    for rule in [] if literal else config['dns']['rules']:
        if rule.get('match_response'):
            if response is None or not any(holds[s](a) for s in rule['rule_set'] for a in response):
                continue
        elif set(rule) & DOMAIN_MATCHERS:
            continue
        if rule.get('action', 'route') == 'evaluate':
            response = answers
            continue
        real = rule.get('action') == 'respond' or servers[rule['server']]['type'] != 'fakeip'
        break
    if not real:
        return {config['route']['final']}
    outcomes = set()
    for address in [literal] if literal else answers:
        for rule in config['route']['rules']:
            if rule.get('action') not in ('route', 'reject') or set(rule) - {'ip_cidr', 'rule_set', 'action', 'outbound'}:
                continue
            if any(address in ipaddress.ip_network(n) for n in rule.get('ip_cidr', ())
                   if ipaddress.ip_network(n).version == address.version) \
                    or any(holds.get(s, lambda _: False)(address) for s in rule.get('rule_set', ())):
                outcomes.add('REJECT' if rule['action'] == 'reject' else rule['outbound'])
                break
        else:
            outcomes.add(config['route']['final'])
    return outcomes


class TemplateTests(unittest.TestCase):
    def assert_order(self, rules, marker):
        positions = [position(rules, marker(dataset)) for dataset in DATASETS]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(position(rules, '198.18.0.0/15'), position(rules, 'fc00::/7'))
        self.assertLess(position(rules, 'fc00::/18'), position(rules, 'fc00::/7'))
        self.assertLess(position(rules, 'fc00::/7'), positions[0])

    def test_ini_templates_order_and_resolver_routes(self):
        for name in ('surge.conf', 'shadowrocket.conf'):
            with self.subTest(name=name):
                rules = rules_of(name)
                self.assert_order(rules, lambda d: 'RULE-SET,' + BASE_URL + 'surge/' + d + '.list,')
                self.assertRegex(rules[position(rules, '223.5.5.5/32')], ',DIRECT,no-resolve$')
                self.assertRegex(rules[position(rules, '1.1.1.1/32')], ',PROXY,no-resolve$')
                self.assertTrue(rules[-1].startswith('FINAL,PROXY'))
                self.assertEqual(sum(rule.startswith('FINAL') for rule in rules), 1)

    def test_shadowrocket_has_no_nested_extended_matching(self):
        self.assertFalse(any('extended-matching' in rule for rule in rules_of('shadowrocket.conf')))

    def test_shadowrocket_dns_paths(self):
        text = (FULL / 'shadowrocket.conf').read_text(encoding='utf-8')
        general = dict(line.split(' = ', 1) for line in text[text.index('[General]'):text.index('[Rule]')].splitlines()
                       if ' = ' in line and not line.startswith('#'))
        for key in ('dns-server', 'fallback-dns-server'):
            self.assertTrue(all(url.endswith('#proxy') for url in general[key].split(', ')), key)
        for key in ('direct-dns-server', 'proxy-dns-server'):
            self.assertNotIn('#proxy', general[key], key)
            self.assertIn('223.5.5.5', general[key], key)
        self.assertNotIn('bypass-system', general)
        # Direct DNS falls back to this shared resolver, so its domestic gap must stay stated.
        self.assertIn('direct-dns-server', comment_before('shadowrocket.conf', 'fallback-dns-server ='))
        host = text[text.index('[Host]'):]
        for name in ('*.lan', '*.local', '*.home.arpa'):
            self.assertIn(name + ' = server:system', host)

    def test_mihomo_template(self):
        config = yaml.safe_load((FULL / 'mihomo.yaml').read_text(encoding='utf-8'))
        rules = config['rules']
        self.assert_order(rules, lambda d: 'RULE-SET,sr-' + d + ',')
        self.assertEqual(rules[-1], 'MATCH,PROXY')
        self.assertEqual(rules, rules_of('mihomo.yaml'))
        for provider, dataset in zip(('sr-' + d for d in DATASETS), DATASETS):
            self.assertEqual(config['rule-providers'][provider]['url'], BASE_URL + 'mihomo/' + dataset + '.yaml')
            self.assertEqual(config['rule-providers'][provider]['interval'], 86400)
        dns = config['dns']
        self.assertTrue(dns['respect-rules'])
        self.assertTrue(dns['proxy-server-nameserver'])
        self.assertTrue(all(url.endswith('#PROXY') for url in dns['nameserver']))
        self.assertTrue(all(url.endswith('#DIRECT') for url in dns['proxy-server-nameserver']))
        self.assertEqual(dns['nameserver-policy']['rule-set:sr-private'], ['system'])
        self.assertIn('rule-set:sr-private', dns['fake-ip-filter'])
        self.assertNotIn('fc00::/7', config['sniffer']['skip-dst-address'])

    def test_sing_box_template(self):
        config = json.loads((FULL / 'sing-box.json').read_text(encoding='utf-8'))
        rules = config['route']['rules']
        tags = {item['tag'] for item in config['route']['rule_set']}
        self.assertEqual(tags, {'sr-' + d for d in DATASETS} | {'sr-non-cn-ip'})
        self.assertEqual(rules[0], {'port': 53, 'action': 'hijack-dns'})
        sniff = [i for i, rule in enumerate(rules) if rule.get('action') == 'sniff']
        self.assertEqual(len(sniff), 2)
        final_domain_rules = [rule['rule_set'][0] for rule in rules[sniff[-1] + 1:]]
        self.assertEqual(final_domain_rules, ['sr-' + d for d in DATASETS])
        first_cn = next(i for i, rule in enumerate(rules) if rule.get('rule_set') == ['sr-cn-ip'])
        self.assertGreater(first_cn, sniff[-1])
        dns_rules = config['dns']['rules']
        evaluate = next(i for i, rule in enumerate(dns_rules) if rule.get('action') == 'evaluate')
        self.assertEqual(dns_rules[evaluate + 1]['rule_set'], ['sr-non-cn-ip'])
        self.assertEqual(dns_rules[evaluate + 2]['action'], 'respond')
        self.assertEqual(dns_rules[evaluate + 3]['server'], 'dns-fake')
        self.assertEqual(config['dns']['rules'][1], {'rule_set': ['sr-private'], 'server': 'dns-local'})

    def test_core_owned_addresses_are_rejected_before_lan(self):
        # FakeIP pools and the core's TUN prefix are not real hosts. Only the evaluated
        # first match proves that, not the order of a few chosen prefixes.
        for name in ('mihomo.yaml', 'sing-box.json', 'surge.conf', 'shadowrocket.conf'):
            rules = template_rules(name)
            for network in sorted(core_owned_networks(name), key=str):
                for address in sorted(samples(network), key=str):
                    with self.subTest(name=name, address=str(address)):
                        self.assertEqual(first_ip_action(rules, address), 'REJECT')
            for address in REAL_LAN:
                with self.subTest(name=name, address=str(address)):
                    self.assertEqual(first_ip_action(rules, address), 'DIRECT')

    def test_sing_box_node_bootstrap_does_not_depend_on_the_proxy(self):
        config = json.loads((FULL / 'sing-box.json').read_text(encoding='utf-8'))
        servers = {server['tag']: server for server in config['dns']['servers']}
        # A node outbound whose server is a domain and that sets no domain_resolver of its own
        # resolves that domain here. Going through PROXY would need the node it is looking up.
        bootstrap = servers[resolver_tag(config['route']['default_domain_resolver'])]
        self.assertNotIn('detour', bootstrap)
        self.assertNotEqual(bootstrap['type'], 'fakeip')
        if 'server' in bootstrap:
            ipaddress.ip_address(bootstrap['server'])  # reaching it needs no lookup of its own

    def test_sing_box_destination_lookups_keep_the_domain_class_resolver(self):
        # The same fault as the Mihomo test below, through another entry: a name sent as a
        # domain (for example through a system-proxy inbound) and routed DIRECT must still be
        # resolved by its own class, so internal names never reach a public resolver.
        config = json.loads((FULL / 'sing-box.json').read_text(encoding='utf-8'))
        servers = {server['tag']: server for server in config['dns']['servers']}
        cases = [('localhost', set()), ('nas.lan', set()), ('printer.local', set()), ('router.home.arpa', set()),
                 ('private.example', {'sr-private'}), ('domestic.example', {'sr-direct'}),
                 ('overseas.example', {'sr-proxy'}), ('unknown.example', set())]
        for name, sets in cases:
            with self.subTest(name=name, sets=sorted(sets)):
                sample = {'name': name, 'sets': sets}
                expected = sing_box_class_resolver(config, sample)
                _, resolver = sing_box_destination_resolver(config, sample)
                if resolver == 'remote':
                    # The proxy server resolves it; only right where this class already uses the proxy.
                    self.assertEqual(servers[expected].get('detour'), 'PROXY')
                else:
                    self.assertEqual(resolver, expected)

    def test_china_ip_fallback_never_sends_a_mixed_answer_direct(self):
        # A core that tests one address cannot tell a mixed answer from a China one. DIRECT is
        # allowed only when every answer is in China; an IP literal must still reach cn-ip.
        mihomo = yaml.safe_load((FULL / 'mihomo.yaml').read_text(encoding='utf-8'))
        sing_box = json.loads((FULL / 'sing-box.json').read_text(encoding='utf-8'))
        evaluate = {'mihomo.yaml': lambda **kw: mihomo_outbounds(mihomo, **kw),
                    'surge.conf': lambda **kw: surge_outbounds(rules_of('surge.conf'), **kw),
                    'sing-box.json': lambda **kw: sing_box_outbounds(sing_box, **kw)}
        for name, outbounds in evaluate.items():
            for label, answers in ANSWERS.items():
                with self.subTest(name=name, answers=label):
                    reached = outbounds(answers=answers)
                    self.assertTrue(reached)
                    self.assertTrue(reached <= ({'DIRECT', 'PROXY'} if all(map(in_china, answers)) else {'PROXY'}))
            for literal, expected in ((CN_A, 'DIRECT'), (CN_AAAA, 'DIRECT'), (OTHER_A, 'PROXY'), (OTHER_AAAA, 'PROXY')):
                with self.subTest(name=name, literal=str(literal)):
                    self.assertEqual(outbounds(literal=literal), {expected})
        # sing-box judges the whole answer in DNS, so it keeps the fallback for China answers.
        self.assertEqual(sing_box_outbounds(sing_box, answers=ANSWERS['China A + AAAA']), {'DIRECT'})
        # Shadowrocket documents neither: the template must say so instead of claiming the goal.
        self.assertIn('Unverified', comment_before('shadowrocket.conf', 'surge/cn-ip.list'))

    def test_mihomo_dns_policy_is_independent_of_business_outbound(self):
        dns = yaml.safe_load((FULL / 'mihomo.yaml').read_text(encoding='utf-8'))['dns']
        # A domain absent from all domain lists may route DIRECT after China-IP
        # lookup. Its later DNS lookups must keep the same default resolver.
        direct = dns.get('direct-nameserver')
        self.assertEqual(direct or dns['nameserver'], dns['nameserver'])
        if direct:
            self.assertTrue(dns.get('direct-nameserver-follow-policy'))

    def test_templates_keep_the_dns_path_of_user_domain_exceptions(self):
        # Clearing the direct resolver, or a [Host] map that only lists the project's sets,
        # silently moves a user's domain-based DIRECT exception to the proxied resolver
        # unless the merge gives it a DNS entry for the same domains.
        self.assertIn('nameserver-policy', comment_before('mihomo.yaml', 'direct-nameserver:'))
        surge = (FULL / 'surge.conf').read_text(encoding='utf-8')
        host = surge[surge.index('[Host]'):]
        self.assertIn('domain-based DIRECT rules', host[host.rindex('RULE-SET:'):])
        readme = (ROOT / 'examples/README.md').read_text(encoding='utf-8')
        self.assertIn('保留用户例外的解析去向', readme)


class AgentGuidanceTests(unittest.TestCase):
    BROWSER_CHECK_LINKS = [
        ('IP 检测', 'https://ippure.com/'),
        ('DNS 检测', 'https://ippure.com/DNS-Leak-Detect.html'),
        ('WebRTC 检测', 'https://ippure.com/Browser-WebRTC-Leak-Detect.html'),
    ]

    def test_subscription_links_select_the_correct_native_format(self):
        master = BASE_URL.replace('/release/', '/master/')
        clients = {'mihomo': 'mihomo', 'surge': 'surge', 'shadowrocket': 'surge', 'sing-box': 'sing-box'}
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        adapters = (ROOT / 'docs/CLIENTS.md').read_text(encoding='utf-8')
        for client, fmt in clients.items():
            with self.subTest(client=client):
                path = f'subscriptions/{client}.json'
                subscription = json.loads((ROOT / path).read_text(encoding='utf-8'))
                self.assertEqual(subscription, {
                    'schema_version': 1,
                    'kind': 'agentroute_rule_subscription',
                    'client': client,
                    'format': fmt,
                    'index_url': BASE_URL + 'index.json',
                    'adapter_url': 'https://github.com/ryuu-restart/agent-route/blob/master/docs/CLIENTS.md#' + client,
                    'routing_mode': 'replace',
                    'final_action': 'PROXY',
                })
                self.assertIn(f']({master}{path})', readme)
                self.assertRegex(adapters, rf'(?im)^### {re.escape(client)}$')

    def test_default_onboarding_replaces_old_business_rules_and_checks_refresh(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        prompt_section = readme.partition('<a id="agent-prompt"></a>')[2]
        prompt = prompt_section.partition('```text\n')[2].partition('\n```')[0]
        guidance = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
        for name, text in (('prompt', prompt), ('guidance', guidance)):
            with self.subTest(name=name):
                self.assertRegex(text, r'替换[^。\n]*业务分流[^。\n]*兜底')
                self.assertIn('停用', text)
                self.assertIn('保留节点订阅', text)
                self.assertIn('旧业务规则', text)
                self.assertIn('旧兜底', text)
                self.assertRegex(text, r'刷新节点订阅后[^。\n]*回读')
                self.assertIn('覆盖未完成', text)

    def test_browser_checks_link_to_the_three_test_pages(self):
        for name in ('README.md', 'AGENTS.md'):
            with self.subTest(name=name):
                text = (ROOT / name).read_text(encoding='utf-8')
                links = re.findall(r'\[((?:IP|DNS|WebRTC) 检测)\]\(([^)]+)\)', text)
                self.assertEqual(links, self.BROWSER_CHECK_LINKS)

    def test_copied_setup_prompt_includes_browser_follow_up(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        prompt_section = readme.partition('<a id="agent-prompt"></a>')[2]
        prompt = prompt_section.partition('```text\n')[2].partition('\n```')[0]
        self.assertIn(BASE_URL.replace('/release/', '/master/') + 'AGENTS.md', prompt)
        self.assertIn(BASE_URL + 'index.json', prompt)
        self.assertEqual(
            re.findall(r'^https://ippure\.com/\S*$', prompt, re.M),
            [url for _, url in self.BROWSER_CHECK_LINKS],
        )
        self.assertIn('未验证', prompt)
        self.assertIn('本机已安装的所有浏览器', prompt)
        self.assertIn('缺扩展就从官方商店安装', prompt)
        self.assertIn('WebRTC Network Limiter', prompt)
        self.assertIn('https://chromewebstore.google.com/detail/webrtc-network-limiter/', prompt)
        self.assertIn('disable_non_proxied_udp', prompt)
        self.assertIn('应用官方支持的等效防护', prompt)
        self.assertRegex(prompt, r'在每个浏览器实际使用的配置档里[^。\n]*完成 IP、DNS 和 WebRTC 检测')
        guidance = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertIn('Agent 从官方商店补装缺失的扩展', guidance)
        self.assertRegex(guidance, r'Agent 在同一实际使用的配置档[^。\n]*执行 IP、DNS 和 WebRTC 检测')
        self.assertIn('docs/DNS-WEBRTC.md#webrtc-methods', guidance)

    def test_acceptance_standard_keeps_every_item_and_its_evidence_rule(self):
        # The advanced acceptance section defines full-device results. An item that loses
        # its evidence requirement lets a configuration screenshot pass as a verified path.
        text = (ROOT / 'docs/DNS-WEBRTC.md').read_text(encoding='utf-8')
        section = text[text.index('<a id="acceptance"></a>'):text.index('<a id="report"></a>')]
        names = re.findall(r'^\*\*(.+?)\*\*$', section, re.M)
        blocks = re.split(r'^\*\*.+?\*\*$', section, flags=re.M)[1:]
        for required in ('TUN 与模式', '规则来源与刷新', '规则加载与分流', '用户例外优先', '核心自有地址',
                         '实际可用性', 'DNS', 'WebRTC', 'IPv6', '持久化', '恢复方法'):
            self.assertIn(required, names)
        self.assertEqual(len(names), len(blocks))
        for name, block in zip(names, blocks):
            with self.subTest(item=name):
                for label in ('通过：', '需要：', '不能单独证明：'):
                    self.assertRegex(block, r'(?m)^- ' + label + r'\S')
        for kind in ('**配置**', '**加载**', '**运行**', '**外部**'):
            self.assertIn(kind, section)

    def test_issue_form_is_well_formed_and_warns_about_secrets(self):
        form = yaml.safe_load((ROOT / '.github/ISSUE_TEMPLATE/agent-report.yml').read_text(encoding='utf-8'))
        self.assertTrue(form['name'] and form['description'])
        body = form['body']
        self.assertEqual(body[0]['type'], 'markdown')
        self.assertIn('订阅', body[0]['attributes']['value'])
        fields = [item for item in body if item['type'] != 'markdown']
        self.assertEqual(len({item['id'] for item in fields}), len(fields))
        self.assertTrue(all(item['attributes']['label'] for item in fields))
        self.assertTrue(any(item.get('validations', {}).get('required') for item in fields))


class PublishedTextTests(unittest.TestCase):
    def test_published_text_has_no_internal_wording(self):
        names = dict(published_text())
        for expected in ('README.md', 'NOTICE.md', 'sources.json', 'docs/SYNC.md', 'examples/full/surge.conf',
                         'schemas/index.schema.json', 'scripts/public_formats.py', '.github/workflows/run.yml'):
            self.assertIn(expected, names)
        for name, text in names.items():
            with self.subTest(name=name):
                self.assertNotRegex(text, '按用户(要求|指定)')
                # A released GitHub name can be registered by anyone, so it must never be read from again.
                self.assertNotIn('heibai0502', text.lower())

    def test_published_text_has_no_private_words(self):
        # The maintainer supplies the word list; it never belongs in this public repository.
        source = os.environ.get('AGENTROUTE_PRIVATE_WORDS_FILE')
        if not source:
            self.skipTest('no private word list supplied')
        words = [line.strip().lower() for line in Path(source).read_text(encoding='utf-8').splitlines() if line.strip()]
        self.assertTrue(words)
        # File names only: test output can end up in public logs.
        self.assertEqual([name for name, text in published_text() if any(word in text.lower() for word in words)], [])


if __name__ == '__main__':
    unittest.main()
