import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import helper as h
import updates as u

HERE=Path(__file__).parent

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.state=self.root/'state';self.state.mkdir()
    def tearDown(self):self.tmp.cleanup()
    def sign(self,data):
        source=self.root/'manifest.json';signature=self.root/'manifest.sig';source.write_bytes(data)
        subprocess.run([str(HERE/'signing/signrelease.exe'),'--key',str(HERE/'signing/release.ed25519'),'--file',str(source),'--out',str(signature)],check=True,capture_output=True)
        return signature.read_bytes()
    def package(self,extra=None):
        files={name:b'fixture' for name in ('GuildSim Helper.exe','GuildSim Launcher.exe','guildsim-engine.exe','addons/GuildSimBeta/GuildSimBeta.toc','ret-engine/retlocal.exe','ret-engine/retbulk.exe')}
        manifest={'version':'0.2.1-beta.1','files':{name:hashlib.sha256(value).hexdigest() for name,value in files.items()}}
        files['manifest.json']=json.dumps(manifest).encode()
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            for name,value in files.items():z.writestr('GuildSimBeta-0.2.1-beta.1/'+name,value)
            if extra:z.writestr(extra,b'unsafe')
        content=out.getvalue();data={'schemaVersion':1,'channel':'beta','version':'0.2.1-beta.1','sequence':3,'sha256':hashlib.sha256(content).hexdigest(),'size':len(content),'url':'https://github.com/bryan970/guildsim/releases/download/v0.2.1-beta.1/bundle.zip'}
        raw=json.dumps(data).encode();return content,data,raw,self.sign(raw)
    def test_installed_native_verifier_accepts_signature(self):
        _,_,raw,sig=self.package();u.verify_signature(raw,sig,h.BASE)
    def test_modified_manifest_rejected_before_download(self):
        _,_,raw,sig=self.package()
        with self.assertRaisesRegex(ValueError,'signature'):u.metadata(raw+b' ',sig,h.BASE,self.state)
    def test_invalid_signature_rejected(self):
        _,_,raw,_=self.package()
        with self.assertRaisesRegex(ValueError,'signature'):u.metadata(raw,b'00'*64,h.BASE,self.state)
    def test_valid_release_committed_and_pending_marker_written(self):
        content,data,raw,sig=self.package()
        target=u.stage(data,raw,sig,h.BASE,self.state,lambda url,limit:content,False)
        self.assertEqual(h.read_json(target/'manifest.json')['version'],data['version'])
        self.assertEqual(h.read_json(self.state/'pending-update.json')['sequence'],3)
    def test_corrupt_download_preserves_current_version(self):
        content,data,raw,sig=self.package();h.save(self.state/'active.json',{'version':h.VERSION})
        with self.assertRaisesRegex(ValueError,'checksum'):u.stage(data,raw,sig,h.BASE,self.state,lambda url,limit:content+b'bad',False)
        self.assertEqual(h.read_json(self.state/'active.json')['version'],h.VERSION)
        self.assertFalse((self.state/'pending-update.json').exists())
    def test_authenticated_archive_still_cannot_traverse(self):
        content,data,raw,sig=self.package('GuildSimBeta-0.2.1-beta.1/../../escape.exe')
        with self.assertRaisesRegex(ValueError,'Unsafe'):u.stage(data,raw,sig,h.BASE,self.state,lambda url,limit:content,False)
        self.assertFalse((self.root/'escape.exe').exists())
    def test_wrong_root_rejected(self):
        content,data,raw,sig=self.package('another-root/file')
        with self.assertRaisesRegex(ValueError,'root'):u.stage(data,raw,sig,h.BASE,self.state,lambda url,limit:content,False)
    def test_rollback_metadata_rejected(self):
        _,_,raw,sig=self.package();h.save(self.state/'update-state.json',{'highestSequence':4})
        with self.assertRaisesRegex(ValueError,'Older release'):u.metadata(raw,sig,h.BASE,self.state)
    def test_wrong_repository_rejected(self):
        _,data,_,_=self.package();data['url']='https://example.org/untrusted.zip';raw=json.dumps(data).encode()
        with self.assertRaisesRegex(ValueError,'repository'):u.metadata(raw,self.sign(raw),h.BASE,self.state)
    def test_link_and_windows_special_paths_rejected(self):
        class Archive:
            def __init__(self,rows):self.rows=rows
            def infolist(self):return self.rows
        for name in ('/absolute','../escape','a\\escape','a:stream','CON.txt','a/trailing.','a/trailing '):
            with self.subTest(path=name),self.assertRaises(ValueError):u.safe_members(Archive([zipfile.ZipInfo(name)]))
        linked=zipfile.ZipInfo('a/link');linked.external_attr=(stat.S_IFLNK|0o777)<<16
        with self.assertRaisesRegex(ValueError,'Linked'):u.safe_members(Archive([linked]))
    def test_case_duplicate_rejected(self):
        archive=type('A',(),{'infolist':lambda self:[zipfile.ZipInfo('A/File'),zipfile.ZipInfo('a/file')]})()
        with self.assertRaisesRegex(ValueError,'Duplicate'):u.safe_members(archive)
    def test_incomplete_release_rejected(self):
        h.save(self.root/'manifest.json',{'version':'0.2.1-beta.1','files':{}})
        with self.assertRaisesRegex(ValueError,'Incomplete'):u.verify_directory(self.root,'0.2.1-beta.1')
    def test_activation_waits_for_wow_to_close(self):
        target=self.state/'releases/0.2.1-beta.1';target.mkdir(parents=True)
        with patch('updates.verify_directory'),patch('updates.process_alive',return_value=False),patch('helper.game_running',return_value=True):
            with self.assertRaisesRegex(ValueError,'WoW started'):u.activate(target,100,'fake',self.state)
        self.assertFalse((self.state/'active.json').exists())

if __name__=='__main__':unittest.main(verbosity=2)
