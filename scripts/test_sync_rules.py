import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from sync_rules import operate, selected, locked, main, validate_manifest, get, HELPER
from unittest.mock import patch, MagicMock

class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)/'cache'
        self.sha = 'a'*40; self.bad = None; self.age = 0
    def tearDown(self): self.temp.cleanup()
    def fetch(self, url):
        if self.bad == 'offline': raise OSError('offline')
        if url.endswith('/commits/release'): return json.dumps({'sha':self.sha}).encode()
        date=(datetime.now(timezone.utc)-timedelta(hours=self.age)).isoformat()
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
    def test_optimized_parser_rejects_invalid_input(self):
        code="from build_rules import domains; domains('not a domain')"
        p=subprocess.run([sys.executable,'-O','-B','-c',code],cwd=Path(__file__).parent,capture_output=True)
        self.assertNotEqual(p.returncode,0)

if __name__=='__main__':unittest.main()
