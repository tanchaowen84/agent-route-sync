"""Run the optional sing-box template with synthetic DNS and loopback-only test endpoints."""
import argparse
from contextlib import closing, contextmanager
import http.client
import http.server
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time

from public_formats import outside_networks


TEMPLATE = Path(__file__).resolve().parents[1] / 'examples/full/sing-box.json'
LOOPBACK = '127.0.0.1'
CN4, OTHER4 = '203.0.113.10', '198.51.100.10'
CN6, OTHER6 = '2001:db8:cc::10', '2001:db8:ff::10'
CN = [ipaddress.ip_network(value) for value in ('203.0.113.0/24', '2001:db8:cc::/48')]
CASES = {
    'china': [CN4, CN6],
    'other': [OTHER4, OTHER6],
    'mixed-a': [CN4, OTHER4],
    'mixed-aaaa': [CN6, OTHER6],
    'mixed-a-other-first': [OTHER4, CN4],
    'mixed-aaaa-other-first': [OTHER6, CN6],
    'split-cn-a': [CN4, OTHER6],
    'split-cn-aaaa': [OTHER4, CN6],
}


class Marker(http.server.BaseHTTPRequestHandler):
    """Terminate the CONNECT request here and return its outbound tag and destination."""

    timeout = 3

    def do_CONNECT(self):
        self.send_response(200)
        self.end_headers()
        if self.rfile.readline(8) == b'probe\n':
            self.wfile.write(f'{self.server.tag} {self.path}\n'.encode('ascii'))

    def log_message(self, *args):
        pass


@contextmanager
def marker(tag):
    with http.server.HTTPServer((LOOPBACK, 0), Marker) as server:
        server.tag = tag
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_port
        finally:
            server.shutdown()
            thread.join()


def config_for(work, ports, hosts):
    template = json.loads(TEMPLATE.read_text(encoding='utf-8'))
    # Only these policy sections enter the isolated process. Listeners, transports,
    # cache location and every dial target belong to the test.
    config = {
        'log': {'level': 'info'},
        'dns': template['dns'],
        'route': {key: template['route'][key] for key in ('rules', 'final', 'rule_set', 'default_domain_resolver')},
        'experimental': {'cache_file': {'enabled': True, 'store_fakeip': True, 'path': str(work / 'cache.db')}},
    }
    config['dns']['servers'] = [
        server if server['type'] == 'fakeip' else
        {'type': 'hosts', 'tag': server['tag'], 'path': os.devnull, 'predefined': hosts}
        for server in config['dns']['servers']
    ]
    for ruleset in config['route']['rule_set']:
        tag = ruleset['tag']
        rules = [{'domain': ['unused.invalid']}]
        if tag == 'sr-cn-ip':
            rules = [{'ip_cidr': list(map(str, CN))}]
        elif tag == 'sr-non-cn-ip':
            rules = [{'ip_cidr': list(map(str, outside_networks(CN)))}]
        ruleset.clear()
        ruleset.update(type='inline', tag=tag, rules=rules)
    config['outbounds'] = [
        {'type': 'http', 'tag': tag, 'server': LOOPBACK, 'server_port': port}
        for tag, port in ports.items()
    ]
    config['inbounds'] = [
        {'type': 'direct', 'tag': 'dns-test', 'listen': LOOPBACK, 'listen_port': 0,
         'override_address': LOOPBACK, 'override_port': 53, 'network': 'tcp'},
        {'type': 'http', 'tag': 'route-test', 'listen': LOOPBACK, 'listen_port': 0},
    ]
    return config


@contextmanager
def running_core(binary, work, config):
    (work / 'config.json').write_text(json.dumps(config), encoding='utf-8')
    logfile = work / 'core.log'
    # An independent parent bounds the core even if this test runner is terminated.
    watchdog = """
import signal, subprocess, sys
child = subprocess.Popen(sys.argv[1:])
signal.signal(signal.SIGTERM, lambda *_: child.terminate())
try:
    sys.exit(child.wait(timeout=60))
finally:
    if child.poll() is None:
        child.kill()
        child.wait()
"""
    with logfile.open('wb') as log:
        proc = subprocess.Popen(
            [sys.executable, '-c', watchdog, binary, '--disable-color', 'run', '-c', 'config.json'],
            cwd=work, stdout=log, stderr=log, start_new_session=True)
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                logs = logfile.read_text(errors='replace')
                if proc.poll() is not None:
                    raise RuntimeError('sing-box exited during startup: ' + logs[-2000:])
                if 'sing-box started' in logs:
                    listeners = dict(re.findall(
                        r'inbound/\w+\[([\w-]+)\]: tcp server started at 127\.0\.0\.1:(\d+)', logs))
                    yield int(listeners['dns-test']), int(listeners['route-test']), logfile
                    return
                time.sleep(0.05)
            raise RuntimeError('sing-box startup timed out')
        finally:
            if proc.poll() is None:
                proc.terminate()  # The watchdog terminates and reaps its child.
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
            # A crashed watchdog may already be reaped while its core still lives.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            else:
                proc.wait(timeout=2)
                for _ in range(40):
                    try:
                        os.killpg(proc.pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.05)
                else:
                    raise RuntimeError('test process group did not exit')


def resolve(dns_port, host, rrtype):
    result = subprocess.run(
        ['dig', '-4', '+nosearch', '+tcp', '+short', '+time=2', '+tries=1',
         '@' + LOOPBACK, '-p', str(dns_port), host + '.', rrtype],
        check=True, capture_output=True, text=True, timeout=5)
    return [ipaddress.ip_address(line) for line in result.stdout.splitlines()]


def http_host(address):
    return f'[{address}]' if address.version == 6 else str(address)


def routed(route_port, logfile, address, expected_tag, expected_host):
    offset = logfile.stat().st_size
    with closing(http.client.HTTPConnection(LOOPBACK, route_port, timeout=3)) as conn:
        conn.set_tunnel(http_host(address), 9000)
        conn.connect()
        conn.sock.sendall(b'probe\n')
        with conn.sock.makefile('rb') as reader:
            marker_tag, destination = reader.readline(256).decode('ascii').split()
    with logfile.open('rb') as f:
        f.seek(offset)
        matches = re.findall(rb'outbound/http\[([^]]+)\]: outbound connection to ', f.read())
    if matches != [marker_tag.encode('ascii')]:
        raise ValueError(f'outbound log disagrees with receiving marker for {address}: {matches!r}, {marker_tag}')
    if (marker_tag, destination) != (expected_tag, f'{expected_host}:9000'):
        raise ValueError(f'{address} reached {marker_tag} {destination}, expected {expected_tag} {expected_host}:9000')
    return {'outbound': marker_tag, 'marker_destination': destination}


def verify(binary):
    # Repeat split-answer cases in the reverse query order using a fresh hostname.
    # This records the per-response behavior of the template, including its cross-family limitation.
    queries = [(case, f'{case}.example', ('A', 'AAAA')) for case in CASES]
    queries += [(case, f'{case}-reverse.example', ('AAAA', 'A')) for case in CASES if case.startswith('split-')]
    hosts = {host: CASES[case] for case, host, _ in queries}
    reports = []
    with tempfile.TemporaryDirectory(prefix='agentroute-dns-') as tmp, marker('DIRECT') as direct, marker('PROXY') as proxy:
        work = Path(tmp)
        config = config_for(work, {'DIRECT': direct, 'PROXY': proxy}, hosts)
        fake = next(s for s in config['dns']['servers'] if s['type'] == 'fakeip')
        fake_ranges = [ipaddress.ip_network(fake[k]) for k in ('inet4_range', 'inet6_range')]
        with running_core(binary, work, config) as (dns_port, route_port, logfile):
            for case, host, order in queries:
                for rrtype in order:
                    version = 4 if rrtype == 'A' else 6
                    original = {a for a in map(ipaddress.ip_address, CASES[case]) if a.version == version}
                    if not original:
                        continue
                    expected_real = all(any(addr in network for network in CN) for addr in original)
                    received = resolve(dns_port, host, rrtype)
                    if expected_real:
                        valid = set(received) == original
                    else:
                        valid = bool(received) and all(any(addr in net for net in fake_ranges) and addr.version == version
                                                       for addr in received)
                    if not valid:
                        raise ValueError(f'{host} {rrtype} unexpected DNS response: {received!r}')
                    for addr in received:
                        expected = 'DIRECT' if expected_real else 'PROXY'
                        target = http_host(addr) if expected_real else host
                        evidence = routed(route_port, logfile, addr, expected, target)
                        reports.append({'host': host, 'type': rrtype, 'answer': str(addr), **evidence})
            for address, expected in ((CN4, 'DIRECT'), (CN6, 'DIRECT'), (OTHER4, 'PROXY'), (OTHER6, 'PROXY')):
                addr = ipaddress.ip_address(address)
                evidence = routed(route_port, logfile, addr, expected, http_host(addr))
                reports.append({'literal': address, **evidence})
    return reports


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sing-box', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(str(args.sing_box.resolve())), indent=2))
