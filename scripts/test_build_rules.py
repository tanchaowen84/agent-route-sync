"""Verify the public generation contract without network access or credentials."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from build_rules import build, fetch, private_domains


class SourceGenerationTests(unittest.TestCase):
    def fixture(self):
        base = int(ipaddress.ip_address('1.0.0.0'))
        ipv6 = int(ipaddress.ip_address('2400::'))
        return {
            'china_domains': '\n'.join(['domain:' + name for name in
                ('baidu.com', 'qq.com', 'taobao.com', 'jd.com', 'asus.com')]
                + ['domain:domestic' + str(i) + '.example' for i in range(1001)]) + '\n',
            'foreign_domains': '\n'.join(['domain:' + name for name in
                ('google.com', 'gstatic.com', 'wikipedia.org', 'github.com', 'asus.com', 'ts.net')]
                + ['full:foreign' + str(i) + '.example' for i in range(1001)]) + '\n',
            'private_domains': 'full:router.asus.com\ndomain:ts.net\ndomain:lan\n',
            'china_ip': '\n'.join([str(ipaddress.ip_address(base + i)) + '/32' for i in range(1001)]
                                  + [str(ipaddress.ip_address(ipv6 + i)) + '/128' for i in range(1001)]) + '\n',
            'advertising_domains': '\n'.join(['domain:doubleclick.net']
                + ['domain:ad' + str(i) + '.example' for i in range(1001)]) + '\n',
        }

    def test_token_is_sent_only_to_the_api(self):
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        response.read.return_value = b'data'
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'token'}), patch('urllib.request.urlopen', return_value=response) as opened:
            fetch('https://api.github.com/repos/a/b/commits/c')
            self.assertEqual(opened.call_args[0][0].get_header('Authorization'), 'Bearer token')
            fetch('https://raw.githubusercontent.com/a/b/c/d')
            self.assertIsNone(opened.call_args[0][0].get_header('Authorization'))

    def test_generation_preserves_foreign_input_and_private_matching_semantics(self):
        raw = self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            manifest = build(raw, output)
            self.assertEqual((output / 'proxy-source.txt').read_bytes(), raw['foreign_domains'].encode())
            self.assertEqual((output / 'private.domains').read_text(), 'router.asus.com\n.lan\n.ts.net\n')
            self.assertNotIn('.asus.com', (output / 'direct.domains').read_text().splitlines())
            self.assertIn('router.asus.com', (output / 'direct.domains').read_text().splitlines())
            self.assertEqual(set(manifest['files']),
                             {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()} - {'manifest.json'})
            for name, digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), digest)
            self.assertEqual(manifest['source_sha256']['foreign_domains'], manifest['files']['proxy-source.txt'])
            self.assertEqual(manifest['counts']['private_domains'], 3)
            self.assertEqual(json.loads((output / 'manifest.json').read_text()), manifest)

    def test_private_source_cannot_empty_or_override_public_and_forced_routes(self):
        for source in ('', 'domain:com', 'domain:com.cn', 'domain:google.com',
                       'domain:apple.com', 'domain:icloud.com', 'domain:claude.ai'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                private_domains(source)


if __name__ == '__main__':
    unittest.main()
