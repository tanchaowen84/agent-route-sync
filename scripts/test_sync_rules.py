import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone, timedelta
from sync_rules import operate, selected, locked, main, validate_manifest, get, HELPER
from unittest.mock import patch, MagicMock

class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)/'cache'
        self.sha = 'a'*40; self.bad = None; self.age = 0
        self.published = {}
    def tearDown(self): self.temp.cleanup()
    def fetch(self, url):
        if self.bad == 'offline': raise OSError('offline')
        if url.endswith('/commits/release'): return json.dumps({'sha':self.sha}).encode()
        date=self.published.get(self.sha, datetime.now(timezone.utc)-timedelta(hours=self.age)).isoformat()
        # Stable within a download transaction.
        if url.endswith('/manifest.json'):
            self.data={n:b'payload' for n in selected('all')}
            self.data['index.json']=json.dumps({'schema_version':1,'generated_at_utc':date}).encode()
            self.manifest={'schema_version':1,'scope':'domestic_direct_and_adblock','generated_at_utc':date,'files':{n:hashlib.sha256(v).hexdigest() for n,v in self.data.items()}}
            if self.bad=='path': self.manifest['files']['../escape']='0'*64
            return json.dumps(self.manifest).encode()
        name=url.split('/'+self.sha+'/')[1]
        if self.bad=='interrupt': raise KeyboardInterrupt()
        return b'corrupt' if self.bad=='hash' else self.data[name]
    def sync(self): return operate('sync',self.root,fetch=self.fetch)
    def test_lifecycle_and_local_rollback(self):
        self.assertEqual(self.sync()['status'],'updated')
        self.assertEqual(self.sync()['status'],'unchanged')
        self.sha='b'*40;self.sync();self.bad='offline'
        self.assertEqual(operate('rollback',self.root)['generation'],'a'*40+'-all')
        self.assertEqual(operate('verify',self.root)['status'],'verified')
    def test_failed_updates_preserve_pointer(self):
        self.sync();before=(self.root/'current.json').read_bytes();self.sha='b'*40
        for bad in ('offline','path','hash','interrupt'):
            self.bad=bad
            with self.subTest(bad=bad),self.assertRaises((ValueError,OSError,KeyboardInterrupt)):self.sync()
            self.assertEqual((self.root/'current.json').read_bytes(),before)
        self.bad=None;self.age=49
        with self.assertRaises(ValueError):self.sync()
        self.assertEqual((self.root/'current.json').read_bytes(),before)
    def test_rollback_holds_until_a_newer_release(self):
        self.sync();self.sha='b'*40;self.sync()
        self.assertEqual(operate('rollback',self.root)['generation'],'a'*40+'-all')
        held=self.sync()
        self.assertEqual((held['status'],held['generation'],held['held_generation']),('held','a'*40+'-all','b'*40+'-all'))
        self.assertEqual(operate('verify',self.root)['generation'],'a'*40+'-all')
        self.sha='c'*40;updated=self.sync()
        self.assertEqual((updated['status'],updated['generation']),('updated','c'*40+'-all'))
        self.assertNotIn('held',json.loads((self.root/'current.json').read_text()))
        self.assertEqual(sorted(p.name[0] for p in (self.root/'generations').iterdir()),['a','c'])
    def test_second_rollback_undoes_the_first(self):
        self.sync();self.sha='b'*40;self.sync()
        operate('rollback',self.root)
        self.assertEqual(operate('rollback',self.root)['generation'],'b'*40+'-all')
        self.assertEqual(self.sync()['status'],'unchanged')
        self.assertNotIn('held', json.loads((self.root / 'current.json').read_bytes()))
        result = operate('sync', self.root, 'mihomo', fetch=self.fetch)
        self.assertEqual(result['generation'], self.sha + '-mihomo')
        self.assertEqual(operate('status', self.root)['previous'], self.sha + '-all')
        self.assertEqual({path.name for path in (self.root / 'generations').iterdir()},
                         {self.sha + '-all', self.sha + '-mihomo'})

    def test_legacy_hold_compares_release_sha_and_strict_publication_time(self):
        middle = datetime.now(timezone.utc) - timedelta(hours=4)
        earlier, held_sha, same_time, newer = (letter * 40 for letter in 'bcde')
        self.published = {
            self.sha: middle - timedelta(hours=1),
            earlier: middle - timedelta(minutes=1),
            held_sha: middle,
            same_time: middle.astimezone(timezone(timedelta(hours=8))),
            newer: middle + timedelta(microseconds=1),
        }
        current = self.sync()['generation']
        self.sha = held_sha
        held = operate('sync', self.root, 'surge', fetch=self.fetch)['generation']
        operate('rollback', self.root)
        # Existing users have the old pointer and inventories without ownership fields.
        pointer = self.root / 'current.json'
        before = json.dumps({'current': current, 'previous': held, 'held': held}).encode()
        pointer.write_bytes(before)
        base = self.root / 'generations'
        for path in base.glob('*/cache.json'):
            meta = json.loads(path.read_bytes())
            del meta['generation'], meta['stage']
            path.write_text(json.dumps(meta))
        for sha, fmt, pinned in ((held_sha, 'all', False), (held_sha, 'sing-box', True),
                                 (earlier, 'mihomo', True), (same_time, 'surge', False)):
            with self.subTest(sha=sha, fmt=fmt):
                self.sha = sha
                result = operate('sync', self.root, fmt, fetch=self.fetch, release_sha=sha if pinned else None)
                self.assertEqual((result['status'], result['generation'], result['held_generation']),
                                 ('held', current, held))
                self.assertEqual(pointer.read_bytes(), before)
                self.assertEqual({path.name for path in base.iterdir()}, {current, held})
        self.sha = newer
        with patch('sync_rules.atomic', side_effect=OSError('pointer unavailable')), self.assertRaises(OSError):
            operate('sync', self.root, 'sing-box', fetch=self.fetch)
        self.assertEqual(pointer.read_bytes(), before)
        self.assertEqual({path.name for path in base.iterdir()}, {current, held})
        result = operate('sync', self.root, 'sing-box', fetch=self.fetch)
        self.assertEqual((result['status'], result['generation']), ('updated', newer + '-sing-box'))
        self.assertEqual(json.loads(pointer.read_bytes()), {'current': result['generation'], 'previous': current})
        self.assertEqual({path.name for path in base.iterdir()}, {current, result['generation']})

    def test_missing_held_manifest_preserves_hold_for_another_release(self):
        self.sync()
        self.sha = 'b' * 40
        held = self.sync()
        operate('rollback', self.root)
        (Path(held['directory']) / 'manifest.json').unlink()
        pointer = self.root / 'current.json'
        before = pointer.read_bytes()
        self.sha = 'c' * 40
        with self.assertRaises(FileNotFoundError):
            self.sync()
        self.assertEqual(pointer.read_bytes(), before)
    def test_pointer_written_before_holds_existed_still_works(self):
        self.sync();pointer=self.root/'current.json'
        self.assertNotIn('held',json.loads(pointer.read_text()))
        self.sha='b'*40;self.assertEqual(self.sync()['status'],'updated')
    def test_malformed_documents_are_reported_as_json(self):
        date=datetime.now(timezone.utc).isoformat()
        valid={'schema_version':1,'scope':'domestic_direct_and_adblock','generated_at_utc':date}
        data={n:b'payload' for n in selected('all')};data['index.json']=b'[]'
        with_index={**valid,'files':{n:hashlib.sha256(v).hexdigest() for n,v in data.items()}}
        for manifest,error in (([],'unsupported_manifest'),({**valid,'files':{},'generated_at_utc':5},'invalid_timestamp'),(with_index,'index_generation_mismatch')):
            def fetch(url,manifest=manifest):
                if url.endswith('/commits/release'):return json.dumps({'sha':self.sha}).encode()
                if url.endswith('/manifest.json'):return json.dumps(manifest).encode()
                return data[url.split('/'+self.sha+'/')[1]]
            with self.subTest(error=error):
                with self.assertRaisesRegex(ValueError,error):operate('sync',self.root,fetch=fetch)
                # The real entry point prints JSON and exits 1 instead of a traceback.
                out=MagicMock()
                with patch('sync_rules.operate',lambda command,root,fmt,fetch=fetch:operate(command,root,fmt,fetch=fetch)),patch.object(sys,'argv',['sync_rules.py','sync','--output',str(self.root)]),patch('builtins.print',out):
                    self.assertEqual(main(),1)
                self.assertEqual(json.loads(out.call_args[0][0])['error'],error)
    @unittest.skipIf(os.name=='nt','POSIX file modes')
    def test_cache_follows_the_umask_so_another_user_can_read_it(self):
        for mask,folder,file in ((0o022,0o755,0o644),(0o077,0o700,0o600)):
            root=self.root/oct(mask);old=os.umask(mask)
            try:result=operate('sync',root,fetch=self.fetch)
            finally:os.umask(old)
            with self.subTest(mask=oct(mask)):
                self.assertEqual(stat.S_IMODE(Path(result['directory']).stat().st_mode),folder)
                self.assertEqual(stat.S_IMODE((root/'current.json').stat().st_mode),file)
                self.assertEqual(stat.S_IMODE((Path(result['directory'])/'surge/direct.list').stat().st_mode),file)
    def test_corruption_detected(self):
        result=self.sync();(Path(result['directory'])/'surge/direct.list').write_bytes(b'bad')
        with self.assertRaises(ValueError):operate('verify',self.root)
    def test_missing_cache_and_rollback(self):
        for command in ('verify','status','rollback'):
            with self.assertRaises(ValueError):operate(command,self.root)
    def test_lock_exclusion_and_crash_release(self):
        script="from pathlib import Path; from sync_rules import locked; import sys,time;\nwith locked(Path(sys.argv[1])):\n print('locked',flush=True); time.sleep(30)"
        p=subprocess.Popen([sys.executable,'-B','-c',script,str(self.root)],cwd=Path(__file__).parent,stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(),'locked')
            with self.assertRaises(ValueError):self.sync()
        finally:p.kill();p.wait();p.stdout.close()
        self.assertEqual(self.sync()['status'],'updated')
    def test_two_generations_retained(self):
        for x in 'abc':self.sha=x*40;self.sync()
        self.assertEqual(len(list((self.root/'generations').iterdir())),2)
    def test_corrupt_current_cannot_replace_valid_previous(self):
        self.sync();self.sha='b'*40;second=self.sync()
        (Path(second['directory'])/'index.json').write_bytes(b'corrupt')
        before=(self.root/'current.json').read_bytes();self.sha='c'*40
        with self.assertRaises(ValueError):self.sync()
        self.assertEqual((self.root/'current.json').read_bytes(),before)
        self.assertEqual(operate('rollback',self.root)['generation'],'a'*40+'-all')
    def test_pointer_replace_failure_preserves_current(self):
        self.sync(); before=(self.root/'current.json').read_bytes(); self.sha='b'*40
        with patch('sync_rules.atomic',side_effect=OSError('write denied')):
            with self.assertRaises(OSError): self.sync()
        self.assertEqual((self.root/'current.json').read_bytes(),before)
        self.assertEqual([path.name for path in (self.root / 'generations').iterdir()], ['a' * 40 + '-all'])

    def test_ownership_record_write_error_removes_our_partial_stage(self):
        current = self.sync()['generation']
        pointer = self.root / 'current.json'
        before = pointer.read_bytes()
        self.sha = 'c' * 40
        def partial_write(_meta, record):
            record.write('{')
            raise OSError('cache full')
        with patch('sync_rules.json.dump', side_effect=partial_write), self.assertRaisesRegex(OSError, 'cache full'):
            self.sync()
        self.assertEqual(pointer.read_bytes(), before)
        self.assertEqual({path.name for path in (self.root / 'generations').iterdir()}, {current})

    def test_crash_at_pointer_switch_recovers_under_lock(self):
        first = self.sync()['generation']
        self.sha = 'b' * 40
        current = self.sync()['generation']
        pointer = self.root / 'current.json'
        before = pointer.read_bytes()
        # Abrupt exit bypasses all finally blocks. Use the same sync entry and local fixture.
        script = """
from pathlib import Path
from unittest.mock import patch
import os, sys
from sync_rules import atomic, operate
from test_sync_rules import SyncTests
fixture = SyncTests()
fixture.sha, fixture.bad, fixture.age, fixture.published = 'c' * 40, None, 0, {}
def stop(path, value):
    if sys.argv[2] == 'after':
        atomic(path, value)
    os._exit(92)
with patch('sync_rules.atomic', side_effect=stop):
    operate('sync', Path(sys.argv[1]), fetch=fixture.fetch)
"""
        args = [sys.executable, '-B', '-c', script, str(self.root)]
        p = subprocess.run(args + ['before'], cwd=Path(__file__).parent)
        self.assertEqual(p.returncode, 92)
        self.assertEqual(pointer.read_bytes(), before)
        base = self.root / 'generations'
        orphan = 'c' * 40 + '-all'
        self.assertEqual({path.name for path in base.iterdir()}, {first, current, orphan})
        with locked(self.root):
            with self.assertRaisesRegex(ValueError, 'cache_busy'):
                self.sync()
            self.assertTrue((base / orphan).is_dir())
        self.assertEqual(self.sync()['status'], 'unchanged')
        self.assertEqual({path.name for path in base.iterdir()}, {first, current})
        self.sha = 'd' * 40
        updated = self.sync()['generation']
        self.assertEqual({path.name for path in base.iterdir()}, {current, updated})
        # A crash just after committing leaves the old previous directory to collect instead.
        p = subprocess.run(args + ['after'], cwd=Path(__file__).parent)
        self.assertEqual(p.returncode, 92)
        self.assertEqual(json.loads(pointer.read_bytes()), {'current': orphan, 'previous': updated})
        self.assertEqual({path.name for path in base.iterdir()}, {current, updated, orphan})
        self.sha = 'c' * 40
        self.assertEqual(self.sync()['status'], 'unchanged')
        self.assertEqual({path.name for path in base.iterdir()}, {updated, orphan})

    def test_cleanup_preserves_user_data_and_unmarked_orphans(self):
        result = self.sync()
        original = Path(result['directory'])
        base = original.parent
        meta = json.loads((original / 'cache.json').read_bytes())
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'user.txt').write_text('keep')
        # An unrelated full-SHA directory and an unmarked partial stage belong to the user.
        for name in ('0' * 40 + '-all', '.stage-' + '0' * 16):
            path = base / name
            path.mkdir()
            (path / 'cache.json').write_text(json.dumps({'schema_version': 2, 'files': meta['files']}))
        # Recover our partial stage, leaving stages with foreign entries intact.
        protected = []
        for i, entry in enumerate(('plain', 'file', 'folder', 'link'), start=1):
            stage = base / ('.stage-' + str(i) * 16)
            stage.mkdir()
            (stage / 'cache.json').write_text(json.dumps({**meta, 'stage': stage.name}))
            (stage / 'manifest.json').write_bytes(b'partial')
            (stage / 'surge').mkdir()
            if entry == 'file':
                (stage / 'surge' / 'my-notes.txt').write_text('keep')
            elif entry == 'folder':
                (stage / 'my-project').mkdir()
            elif entry == 'link':
                try:
                    (stage / 'mihomo').symlink_to(outside, target_is_directory=True)
                except OSError:  # Windows may prohibit unprivileged symbolic links.
                    (stage / 'my-project').mkdir()
            if entry != 'plain':
                protected.append(stage)
        (original / 'user.txt').write_text('preserve the whole old generation')
        for sha in ('b' * 40, 'd' * 40):
            self.sha = sha
            self.sync()
        self.assertTrue((original / 'user.txt').is_file())
        self.assertTrue((original / 'index.json').is_file())
        self.assertTrue((outside / 'user.txt').is_file())
        self.assertFalse((base / ('.stage-' + '1' * 16)).exists())
        self.assertTrue(all((p / 'manifest.json').is_file() for p in protected))
        self.assertTrue((base / ('0' * 40 + '-all') / 'cache.json').is_file())
        self.assertTrue((base / ('.stage-' + '0' * 16) / 'cache.json').is_file())
    def test_future_publication_rejected(self):
        self.age=-1
        with self.assertRaises(ValueError):self.sync()
        self.assertFalse((self.root/'current.json').exists())
    def test_truncated_http_response_rejected(self):
        response=MagicMock();response.__enter__.return_value=response
        response.status=200;response.url='https://raw.githubusercontent.com/example/file'
        response.headers={'Content-Length':'100'};response.read.return_value=b'short'
        with patch('urllib.request.urlopen',return_value=response):
            with self.assertRaises(ValueError):get(response.url)
    def test_corrupt_previous_refuses_rollback(self):
        first=self.sync();self.sha='b'*40;self.sync()
        before=(self.root/'current.json').read_bytes()
        (Path(first['directory'])/'index.json').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):operate('rollback',self.root)
        self.assertEqual((self.root/'current.json').read_bytes(),before)
    def helper_fetch(self):
        def fetch(url):
            if url.endswith('/commits/release'):return json.dumps({'sha':self.sha}).encode()
            if url.endswith('/manifest.json'):
                date=datetime.now(timezone.utc).isoformat()
                self.data={**{n:b'payload' for n in selected('all')},HELPER:b'helper'}
                self.data['index.json']=json.dumps({'schema_version':1,'generated_at_utc':date}).encode()
                return json.dumps({'schema_version':1,'scope':'domestic_direct_and_adblock','generated_at_utc':date,'files':{n:hashlib.sha256(v).hexdigest() for n,v in self.data.items()}}).encode()
            return self.data[url.split('/'+self.sha+'/')[1]]
        return fetch
    def test_helper_is_cached_only_for_sing_box(self):
        self.assertIn(HELPER,operate('sync',self.root,'sing-box',fetch=self.helper_fetch())['files'])
        self.assertEqual(operate('verify',self.root)['status'],'verified')
        self.sha='b'*40
        self.assertNotIn(HELPER,operate('sync',self.root,'surge',fetch=self.helper_fetch())['files'])
    def test_cache_without_helper_stays_valid_after_upgrade(self):
        result=self.sync();path=Path(result['directory'])/'cache.json'
        self.assertEqual(json.loads(path.read_text())['files'],selected('all'))
        self.assertEqual(operate('verify',self.root)['status'],'verified')
        self.sha='b'*40;self.assertEqual(operate('sync',self.root,fetch=self.helper_fetch())['status'],'updated')
    def test_tampered_helper_detected(self):
        result=operate('sync',self.root,fetch=self.helper_fetch())
        (Path(result['directory'])/HELPER).write_bytes(b'changed')
        with self.assertRaises(ValueError):operate('verify',self.root)

    def guard_fetch(self, corrupt=False):
        base = self.helper_fetch()
        def fetch(url):
            data = base(url)
            if url.endswith('/manifest.json'):
                manifest = json.loads(data)
                for fmt, ext in (('mihomo', '.yaml'), ('surge', '.list'), ('sing-box', '.json')):
                    name = fmt + '/webrtc-guard' + ext
                    self.data[name] = b'guard'
                    manifest['files'][name] = hashlib.sha256(b'guard').hexdigest()
                return json.dumps(manifest).encode()
            if corrupt and '/webrtc-guard' in url:
                return b'corrupt'
            return data
        return fetch

    def test_guard_downloads_for_each_format_and_rollback_to_old_release(self):
        for fmt, expected in (('mihomo', 1), ('surge', 1), ('sing-box', 1), ('all', 3)):
            with self.subTest(fmt=fmt):
                root = self.root / fmt
                self.sha = 'a' * 40
                operate('sync', root, fmt, fetch=self.fetch)
                self.sha = 'b' * 40
                result = operate('sync', root, fmt, fetch=self.guard_fetch())
                self.assertEqual(sum('/webrtc-guard' in n for n in result['files']), expected)
                self.assertEqual(result['missing_optional_resources'], [])
                self.assertEqual(operate('verify', root)['status'], 'verified')
                self.assertEqual(operate('rollback', root)['generation'], 'a' * 40 + '-' + fmt)

    def test_guard_corruption_preserves_current_generation(self):
        self.sync(); before = (self.root / 'current.json').read_bytes()
        self.sha = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'resource_hash_mismatch'):
            operate('sync', self.root, fetch=self.guard_fetch(corrupt=True))
        self.assertEqual((self.root / 'current.json').read_bytes(), before)

    def test_new_inventory_cannot_silently_omit_guard(self):
        result = operate('sync', self.root, 'mihomo', fetch=self.guard_fetch())
        path = Path(result['directory']) / 'cache.json'
        meta = json.loads(path.read_text())
        meta['files'].remove('mihomo/webrtc-guard.yaml')
        path.write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError, 'cache_inventory_invalid'):
            operate('verify', self.root)
        # An old tool may have downloaded the same release without optional files.
        # Keep its existing cache readable, but expose the missing protection.
        meta.pop('schema_version')
        path.write_text(json.dumps(meta))
        missing = operate('verify', self.root)['missing_optional_resources']
        self.assertEqual(missing, ['mihomo/webrtc-guard.yaml'])
    def test_optimized_parser_rejects_invalid_input(self):
        code="from build_rules import domains; domains('not a domain')"
        p=subprocess.run([sys.executable,'-O','-B','-c',code],cwd=Path(__file__).parent,capture_output=True)
        self.assertNotEqual(p.returncode,0)

    def test_explicit_release_sha_avoids_api_and_downloads_one_generation(self):
        urls = []
        def raw_only(url):
            urls.append(url)
            if 'api.github.com' in url:
                raise urllib.error.HTTPError(url, 403, 'rate limit exceeded', None, None)
            return self.fetch(url)
        result = operate('sync', self.root, 'mihomo', fetch=raw_only, release_sha=self.sha)
        self.assertEqual(result['status'], 'updated')
        self.assertEqual(result['generation'], self.sha + '-mihomo')
        self.assertTrue(all('/' + self.sha + '/' in url for url in urls))
        self.assertEqual(operate('verify', self.root)['status'], 'verified')

    def test_explicit_release_sha_keeps_validation_and_failure_preservation(self):
        for existing in (False, True):
            for bad, age in (('hash', 0), ('path', 0), ('offline', 0), ('interrupt', 0), (None, 49), (None, -1)):
                with self.subTest(existing=existing, bad=bad, age=age), tempfile.TemporaryDirectory() as folder:
                    root = Path(folder) / 'cache'
                    self.bad = None; self.age = 0; self.sha = 'a' * 40
                    if existing:
                        operate('sync', root, fetch=self.fetch)
                    pointer = root / 'current.json'
                    before = pointer.read_bytes() if pointer.exists() else None
                    self.sha = 'b' * 40; self.bad = bad; self.age = age
                    with self.assertRaises((ValueError, OSError, KeyboardInterrupt)):
                        operate('sync', root, fetch=self.fetch, release_sha=self.sha)
                    self.assertEqual(pointer.read_bytes() if pointer.exists() else None, before)

    def test_explicit_release_sha_rejects_invalid_input_before_io(self):
        fetch = MagicMock()
        for sha in ('', 'a' * 39, 'a' * 41, 'g' * 40, '../release', 'A' * 40, 123):
            with self.subTest(sha=sha), self.assertRaisesRegex(ValueError, 'invalid_release_sha'):
                operate('sync', self.root, fetch=fetch, release_sha=sha)
        for command in ('verify', 'status', 'rollback'):
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, 'release_sha_requires_sync'):
                operate(command, self.root, fetch=fetch, release_sha=self.sha)
        fetch.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_explicit_release_sha_respects_rollback_hold(self):
        self.sync(); self.sha = 'b' * 40; self.sync()
        operate('rollback', self.root)
        result = operate('sync', self.root, fetch=self.fetch, release_sha=self.sha)
        self.assertEqual(result['status'], 'held')
        self.assertEqual(result['generation'], 'a' * 40 + '-all')

    def test_cli_forwards_optional_release_sha(self):
        real_operate = operate
        def offline(command, root, fmt, **kwargs):
            return real_operate(command, root, fmt, fetch=self.fetch, **kwargs)
        out = MagicMock()
        args = ['sync_rules.py', 'sync', '--output', str(self.root), '--format', 'mihomo', '--release-sha', self.sha]
        with patch('sync_rules.operate', side_effect=offline), patch.object(sys, 'argv', args), patch('builtins.print', out):
            self.assertEqual(main(), 0)
        self.assertEqual(json.loads(out.call_args[0][0])['generation'], self.sha + '-mihomo')

    def test_optional_formats_are_complete_and_default_stays_text(self):
        from sync_rules import VARIANT_FILES
        file_names = {path for fmt in VARIANT_FILES for path in selected(fmt)} | set(selected('all'))
        file_names.update(('sing-box/webrtc-guard.json', 'sing-box/non-cn-ip.json'))
        files = {path: b'\x00\xff\r\n' for path in file_names}
        date = datetime.now(timezone.utc).isoformat()
        rows = [{'id': name, 'format': fmt, 'path': path, 'sha256': hashlib.sha256(files[path]).hexdigest()}
                for fmt, by_name in VARIANT_FILES.items() for name, path in by_name.items()]

        def fetch(url):
            name = url.split('/' + self.sha + '/')[1]
            if name == 'manifest.json':
                files['index.json'] = json.dumps({'schema_version': 1, 'generated_at_utc': date,
                                                  'format_variants': rows}).encode()
                return json.dumps({'scope': 'domestic_direct_and_adblock', 'generated_at_utc': date,
                                   'files': {n: hashlib.sha256(v).hexdigest() for n, v in files.items()}}).encode()
            return files[name]

        for fmt, count in (('all', 20), ('mrs', 7), ('srs', 8), ('domain-set', 10)):
            result = operate('sync', self.root, fmt, fetch, self.sha)
            self.assertEqual(len(result['files']), count)
            self.assertEqual(operate('verify', self.root)['files'], result['files'])
            if fmt == 'all':
                self.assertFalse(any(path.endswith(('.srs', '.mrs', '.domains')) for path in result['files']))
            if fmt == 'mrs':
                self.assertIn('mihomo/webrtc-guard.yaml', result['files'])
            if fmt == 'domain-set':
                self.assertIn('surge/cn-ip.list', result['files'])
                self.assertIn('private.domains', result['files'])
                self.assertIn('surge/private.list', result['files'])

        before = (self.root / 'current.json').read_bytes()
        rows[0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'format_index_digest_mismatch'):
            operate('sync', self.root, 'mrs', fetch, self.sha)
        self.assertEqual((self.root / 'current.json').read_bytes(), before)

    def test_choosing_a_format_on_a_pre_pilot_generation_preserves_cache(self):
        self.sync()
        before = (self.root / 'current.json').read_bytes()
        for fmt in ('mrs', 'srs', 'domain-set'):
            with self.assertRaisesRegex(ValueError, 'format_files_unavailable:' + fmt):
                operate('sync', self.root, fmt, fetch=self.fetch)
        self.assertEqual((self.root / 'current.json').read_bytes(), before)

    def test_default_api_rate_limit_preserves_existing_or_empty_cache(self):
        def limited(url):
            raise urllib.error.HTTPError(url, 403, 'rate limit exceeded', None, None)
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as folder:
                root = Path(folder) / 'cache'
                if existing:
                    operate('sync', root, fetch=self.fetch)
                pointer = root / 'current.json'
                before = pointer.read_bytes() if pointer.exists() else None
                with self.assertRaises(urllib.error.HTTPError):
                    operate('sync', root, fetch=limited)
                self.assertEqual(pointer.read_bytes() if pointer.exists() else None, before)

if __name__=='__main__':unittest.main()
