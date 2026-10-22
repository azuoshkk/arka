import importlib.util, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, Mock

class RemoteAccessTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/'scripts/start-demo.py'
        spec=importlib.util.spec_from_file_location('arka_remote',path)
        self.remote=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.remote)
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.remote.ROOT=Path(tmp.name);self.remote.URL=self.remote.ROOT/'.local/demo-url'
        binary=self.remote.ROOT/'.local/bin/cloudflared';binary.parent.mkdir(parents=True);binary.touch()
    def test_fails_closed_without_login(self):
        response=Mock();response.json.return_value={'login_required':False}
        with patch.object(self.remote.requests,'get',return_value=response),patch.object(self.remote.subprocess,'Popen') as process,patch.object(self.remote.signal,'signal'):
            with self.assertRaisesRegex(SystemExit,'ative o login'):self.remote.main()
        process.assert_not_called()
    def test_targets_existing_tls_backend_only(self):
        response=Mock();response.json.return_value={'login_required':True}
        child=Mock();child.stdout=iter(['https://api.trycloudflare.com/tunnel error\n','https://test-arka-demo-url.trycloudflare.com\n'])
        child.poll.return_value=0
        def launch(args,**kwargs):self.remote.stop.set();return child
        with patch.object(self.remote.requests,'get',return_value=response) as get,patch.object(self.remote.subprocess,'Popen',side_effect=launch) as process,patch.object(self.remote.signal,'signal'):
            self.remote.main()
        args=process.call_args.args[0]
        self.assertIn('https://127.0.0.1:8444',args)
        self.assertIn('--origin-ca-pool',args)
        self.assertNotIn('--no-tls-verify',args)
        self.assertEqual(process.call_count,1)
        self.assertNotEqual(get.call_args.kwargs['verify'],False)
        self.assertFalse(self.remote.URL.exists())
        self.assertEqual((self.remote.ROOT/'.local/demo-url.previous').read_text(),'https://test-arka-demo-url.trycloudflare.com')

if __name__=='__main__':unittest.main()
