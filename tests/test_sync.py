import datetime as dt
import hashlib
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('sync', Path(__file__).parents[1] / 'tools/sync_upstream.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class ReleaseValidation(unittest.TestCase):
    def payload(self):
        generated = dt.datetime.now(dt.timezone.utc).isoformat()
        data = {f'surge/{name}.list': b'DOMAIN,example.org,DIRECT\n'
                for name in ['private', 'reject', 'proxy', 'direct', 'cn-ip']}
        datasets = [{'id': name, 'resources': {'surge': {'path': path, 'entries': 1,
                    'sha256': hashlib.sha256(data[path]).hexdigest()}}}
                    for name, path in zip(['private', 'reject', 'proxy', 'direct', 'cn-ip'], data)]
        index = {'schema_version': 1, 'generated_at_utc': generated, 'datasets': datasets, 'helpers': []}
        data['index.json'] = json.dumps(index).encode()
        manifest = {'schema_version': 1, 'generated_at_utc': generated,
                    'files': {p: hashlib.sha256(b).hexdigest() for p, b in data.items()}}
        data['manifest.json'] = json.dumps(manifest).encode()
        return data

    def test_accepts_matching_generation(self):
        data = self.payload()
        with patch.object(sync, 'read_blob', side_effect=lambda _, p: data[p]):
            sync.verify_release('commit')

    def test_rejects_tampered_rule(self):
        data = self.payload()
        data['surge/proxy.list'] = b'CORRUPT\n'
        with patch.object(sync, 'read_blob', side_effect=lambda _, p: data[p]):
            with self.assertRaises(ValueError):
                sync.verify_release('commit')


class GitPublishing(unittest.TestCase):
    def test_publish_noop_rewritten_upstream_and_failure_preserves_refs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            upstream, origin, local = [root / n for n in ['upstream', 'origin.git', 'local']]

            def command(directory, *args):
                return subprocess.run(['git', '-C', str(directory), '-c', 'user.name=Fixture',
                    '-c', 'user.email=fixture@example.invalid', *args], check=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()

            upstream.mkdir()
            command(upstream, 'init', '-b', 'master')
            (upstream / 'README.md').write_text('Public upstream docs\n')
            (upstream / '.github/workflows').mkdir(parents=True)
            (upstream / '.github/workflows/trap.yml').write_text('untrusted workflow data\n')
            command(upstream, 'add', '.')
            command(upstream, 'commit', '-m', 'Source')
            command(upstream, 'checkout', '--orphan', 'release')
            command(upstream, 'rm', '-rf', '.')

            def write_release(corrupt=False):
                data = ReleaseValidation().payload()
                if corrupt:
                    data['surge/proxy.list'] = b'TAMPERED\n'
                for path, content in data.items():
                    destination = upstream / path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(content)
                command(upstream, 'add', '.')
                command(upstream, 'commit', '-m', 'Release data')

            write_release()
            command(root, 'init', '--bare', str(origin))
            command(root, 'clone', str(origin), str(local))
            command(local, 'checkout', '-b', 'main')
            (local / 'README.md').write_text('Local control docs\n')
            command(local, 'add', '.')
            command(local, 'commit', '-m', 'Control')
            command(local, 'push', 'origin', 'main')

            def run_sync(**kwargs):
                previous = os.getcwd()
                try:
                    os.chdir(local)
                    with contextlib.redirect_stdout(io.StringIO()):
                        sync.synchronize(upstream=str(upstream), **kwargs)
                finally:
                    os.chdir(previous)

            initial_refs = command(origin, 'show-ref')
            run_sync(dry_run=True)
            self.assertEqual(initial_refs, command(origin, 'show-ref'))
            run_sync()
            published = command(origin, 'show-ref')
            self.assertEqual(command(origin, 'show', 'release:surge/proxy.list'), 'DOMAIN,example.org,DIRECT')
            self.assertNotIn('.github', command(origin, 'ls-tree', '-r', '--name-only', 'source'))
            self.assertEqual(command(origin, 'show', 'main:README.md'), 'Local control docs')
            run_sync()
            self.assertEqual(published, command(origin, 'show-ref'))
            old_release = command(origin, 'rev-parse', 'release')
            command(upstream, 'checkout', '--orphan', 'replacement')
            command(upstream, 'rm', '-rf', '.')
            write_release()
            command(upstream, 'branch', '-f', 'release', 'HEAD')
            run_sync()
            self.assertNotEqual(old_release, command(origin, 'rev-parse', 'release'))
            self.assertEqual(old_release, command(origin, 'rev-parse', 'release^'))
            valid_refs = command(origin, 'show-ref')
            write_release(corrupt=True)
            command(upstream, 'branch', '-f', 'release', 'HEAD')
            with self.assertRaises(ValueError):
                run_sync()
            self.assertEqual(valid_refs, command(origin, 'show-ref'))


if __name__ == '__main__':
    unittest.main()
