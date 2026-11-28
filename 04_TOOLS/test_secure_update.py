import hashlib,json,tempfile,unittest,zipfile
from pathlib import Path
from release_signature import generate,sign
from secure_update import stage

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name); generate(self.p/'priv',self.p/'pub')
    def make(self, ver='013.2', extra=None, bad=False):
        a=self.p/'a.zip'; s=self.p/'sig'
        files={'RELEASE_VERSION.json':json.dumps({'version':ver}).encode(),'bot.py':b'pass\n'}
        manifest={k:hashlib.sha256(v).hexdigest() for k,v in files.items()}
        if bad: manifest['bot.py']='0'*64
        with zipfile.ZipFile(a,'w') as z:
            for k,v in files.items(): z.writestr('release/'+k,v)
            z.writestr('release/RELEASE_MANIFEST.json',json.dumps(manifest))
            if extra: z.writestr(extra,b'x')
        sign(a,self.p/'priv',s); return a,s
    def run_stage(self,a,s): return stage(a,self.p/'pub',s,'013.1',self.p/'dest')
    def test_valid(self):
        self.assertEqual(self.run_stage(*self.make()),'013.2'); self.assertTrue((self.p/'dest/bot.py').exists())
    def test_old(self):
        with self.assertRaises(ValueError): self.run_stage(*self.make('013.0'))
    def test_same(self):
        with self.assertRaises(ValueError): self.run_stage(*self.make('013.1'))
    def test_traversal(self):
        with self.assertRaises(ValueError): self.run_stage(*self.make(extra='release/../escape'))
    def test_manifest(self):
        with self.assertRaises(ValueError): self.run_stage(*self.make(bad=True))
    def test_existing(self):
        (self.p/'dest').mkdir()
        with self.assertRaises(ValueError): self.run_stage(*self.make())
    def test_tamper(self):
        a,s=self.make(); a.write_bytes(a.read_bytes()+b'x')
        with self.assertRaises(Exception): self.run_stage(a,s)
