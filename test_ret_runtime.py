import copy
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch,Mock

import helper as h
import ret_runtime as r

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.state=self.root/'state';self.game=self.root/'game';(self.game/'Interface/AddOns/GuildSimBeta').mkdir(parents=True);(self.game/'WTF/Account/PUBLIC/SavedVariables').mkdir(parents=True)
        p=h.read_json(h.BASE/'defaults.json')['ret']['player']
        self.char={'id':'Player-PUBLIC','name':'Public Fixture','race':'Human','class':'paladin','flavor':'forever','level':60,'talents':p['talentsString'],'gear':copy.deepcopy(p['equipment'])};self.char['gear']['items'][12:14]=[{'id':13965},{'id':19812}]
        self.sv=self.game/'WTF/Account/PUBLIC/SavedVariables/WowSimsExporter.lua';self.sv.write_text('WSEDB={}',encoding='utf-8')
        self.entry={'character':self.char,'account':'PUBLIC','path':str(self.sv),'timestamp':time.time()};self.settings={'root':str(self.game)}
    def tearDown(self):self.tmp.cleanup()
    def test_progress_lock_does_not_abandon_running_worker(self):
        for fault in (PermissionError(13,'Permission denied'),json.JSONDecodeError('partial snapshot','{',1)):
            with self.subTest(fault=type(fault).__name__):
                work=self.root/'worker';(work/'output').mkdir(parents=True,exist_ok=True)
                process=Mock(returncode=0);process.poll.side_effect=[None,None,0]
                notices=[]
                with patch('ret_runtime.bootstrap',return_value=work),patch('ret_runtime.subprocess.Popen',return_value=process),patch('ret_runtime.h.read_json',side_effect=[{'stage':'Native work','detail':'Still running'},fault]),patch('ret_runtime.publish_profiles'),patch('ret_runtime.time.sleep'):
                    r.RetRunner(h.BASE,self.state).run(self.entry,self.settings,notices.append)
                self.assertEqual(process.poll.call_count,3)
                self.assertIn('Ready:',notices[-1]);self.assertFalse(any('Permission denied' in n for n in notices))
    def test_repeated_progress_locks_still_wait_for_worker_completion(self):
        work=self.root/'worker';(work/'output').mkdir(parents=True)
        process=Mock(returncode=0);process.poll.side_effect=[None,None,None,0]
        with patch('ret_runtime.bootstrap',return_value=work),patch('ret_runtime.subprocess.Popen',return_value=process),patch('ret_runtime.h.read_json',side_effect=PermissionError(13,'Permission denied')),patch('ret_runtime.publish_profiles'),patch('ret_runtime.time.sleep'):
            r.RetRunner(h.BASE,self.state).run(self.entry,self.settings)
        self.assertEqual(process.poll.call_count,4)
    def test_character_workspaces_isolate_accounts_and_guids(self):
        a=r.workspace_for(self.entry,self.state);b=r.workspace_for({**self.entry,'account':'OTHER'},self.state)
        self.assertNotEqual(a,b)
    def test_bootstrap_uses_selected_character_not_personal_paths(self):
        work=r.bootstrap(self.entry,self.settings,h.BASE,self.state);config=h.read_json(work/'config.json')
        self.assertEqual(config['character_guid'],self.char['id']);self.assertEqual(config['character_race'],'Human');self.assertEqual(config['catalog_reference_trinkets'][1]['id'],19812)
        self.assertTrue(Path(config['combat_trinket_cache']).is_relative_to(self.state));self.assertEqual(config['saved_variables'],str(self.sv))
        self.assertFalse(config['wowsims_updates']['enabled'])
    def test_personal_farming_target_and_fixed_pair_preserved_on_upgrade(self):
        work=r.bootstrap(self.entry,self.settings,h.BASE,self.state);h.save(work/'prebis-targets.json',{'name':'My target','items':[]})
        config=h.read_json(work/'config.json');config['catalog_reference_trinkets']=[{'id':22321},{'id':13965}];h.save(work/'config.json',config)
        h.save(work/'runtime-version.json',{'version':'older'})
        r.bootstrap(self.entry,self.settings,h.BASE,self.state)
        self.assertEqual(h.read_json(work/'prebis-targets.json')['name'],'My target');self.assertEqual(h.read_json(work/'config.json')['catalog_reference_trinkets'][0]['id'],22321)
    def test_migration_preserves_source_and_copies_library_with_sqlite_backup(self):
        old=self.root/'legacy';(old/'output').mkdir(parents=True)
        h.save(old/'config.json',{'character_name':self.char['name'],'catalog_reference_trinkets':[{'id':13965},{'id':22321}]})
        h.save(old/'scenario.json',{'name':'Custom raid'});h.save(old/'prebis-targets.json',{'name':'Custom farm','items':[]})
        with closing(sqlite3.connect(old/'output/fight-library.sqlite')) as db:db.execute('CREATE TABLE sample(value TEXT)');db.execute('INSERT INTO sample VALUES (?)',('history',));db.commit()
        self.sv.with_name('RetSimBridge.lua').write_text('RetSimBridgeDB='+h.lua({'trinketPool':{self.char['id']:{'19812:0:0':{'id':19812}}}}),encoding='utf-8')
        work=r.migrate_personal(old,self.entry,self.settings,h.BASE,self.state)
        self.assertEqual(h.read_json(work/'scenario.json')['name'],'Custom raid');self.assertTrue((old/'config.json').exists())
        with closing(sqlite3.connect(work/'output/fight-library.sqlite')) as db:self.assertEqual(db.execute('SELECT value FROM sample').fetchone()[0],'history')
        result=h.loads(self.sv.with_name('GuildSimBeta.lua').read_text(encoding='utf-8'))['GuildSimBetaDB'];self.assertEqual(result['trinketPool'][self.char['id']]['19812:0:0']['id'],19812)
    def test_profile_lua_uses_guid_and_function_boundaries(self):
        work=r.bootstrap(self.entry,self.settings,h.BASE,self.state)
        (work/'addon/Weights.lua').write_text('local _,ns=...\nns.payload={guid="Player-PUBLIC"}\n',encoding='utf-8')
        addon=self.game/'Interface/AddOns/GuildSimBeta';r.publish_profiles(work,self.entry,h.BASE,self.state,addon)
        text=(addon/'Profiles.lua').read_text(encoding='utf-8');self.assertIn('function load(...)',text);self.assertIn('UnitGUID("player")=="Player-PUBLIC"',text)
    def test_empty_profile_template_cannot_clear_loaded_weights(self):
        work=r.bootstrap(self.entry,self.settings,h.BASE,self.state)
        (work/'addon/Weights.lua').write_text('local _,ns=...\nns.payload = nil\n',encoding='utf-8')
        (work/'addon/WeaponResults.lua').write_text('local _,ns=...\nns.weaponResults={guid="Player-PUBLIC"}\n',encoding='utf-8')
        addon=self.game/'Interface/AddOns/GuildSimBeta';r.publish_profiles(work,self.entry,h.BASE,self.state,addon)
        text=(addon/'Profiles.lua').read_text(encoding='utf-8')
        self.assertNotIn('ns.payload = nil',text);self.assertIn('ns.weaponResults=',text)
    def test_handoff_does_not_interrupt_open_game(self):
        with patch('helper.game_running',return_value=True):
            ok,message=r.finish_migration(self.root/'legacy',self.game,self.state)
        self.assertFalse(ok);self.assertIn('close WoW',message)
    def test_handoff_waits_for_active_legacy_worker(self):
        old=self.root/'legacy';(old/'output').mkdir(parents=True);(old/'output/watch.pid').write_text('1234');h.save(old/'output/progress.json',{'state':'running'})
        observation={'process':{'CommandLine':str(old.resolve()/'run.py')+' --watch'},'children':[{'ProcessId':2}]}
        with patch('helper.game_running',return_value=False),patch('ret_runtime.subprocess.run',return_value=type('R',(),{'stdout':json.dumps(observation)})()) as command:
            ok,message=r.finish_migration(old,self.game,self.state)
        self.assertFalse(ok);self.assertEqual(command.call_count,1);self.assertIn('not been interrupted',message)

if __name__=='__main__':unittest.main(verbosity=2)
