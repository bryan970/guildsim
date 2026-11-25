import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import helper as h
from prepare_bundle import manifest

class BetaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.game=self.root/'wow';(self.game/'Interface/AddOns').mkdir(parents=True);(self.game/'WTF').mkdir()
        self.bundle=self.root/'bundle';(self.bundle/'addons/GuildSimBeta').mkdir(parents=True);(self.bundle/'addons/WowSimsExporter').mkdir()
        (self.bundle/'addons/GuildSimBeta/.guildsim-owned').write_text('owned')
        (self.bundle/'addons/GuildSimBeta/Results.lua').write_text('clean')
        (self.bundle/'addons/GuildSimBeta/GuildSim.lua').write_text('beta v1')
        (self.bundle/'addons/WowSimsExporter/WowSimsExporter.toc').write_text('public exporter')
        manifest(self.bundle)
        self.db=h.read_json(h.BASE/'items.json')
        presets=h.read_json(h.BASE/'defaults.json')
        p=presets['ret']['player']
        self.char={'id':'Player-TEST-0001','name':'Public Fixture','race':'Human','class':'paladin','flavor':'forever','level':60,'talents':p['talentsString'],'gear':p['equipment']}
    def tearDown(self): self.tmp.cleanup()

    def test_install_preserves_personal_setup_and_exporter(self):
        addons=self.game/'Interface/AddOns';personal=addons/'RetSimBridge';personal.mkdir();(personal/'Weights.lua').write_text('my weights')
        exporter=addons/'WowSimsExporter';exporter.mkdir();(exporter/'custom.lua').write_text('keep me')
        saved=self.game/'WTF/Account/EXISTING/SavedVariables';saved.mkdir(parents=True);(saved/'RetSimBridge.lua').write_text('keep private SV')
        h.install(self.game,self.bundle,False)
        self.assertEqual((personal/'Weights.lua').read_text(),'my weights');self.assertEqual((exporter/'custom.lua').read_text(),'keep me')
        self.assertFalse((exporter/'WowSimsExporter.toc').exists());self.assertEqual((saved/'RetSimBridge.lua').read_text(),'keep private SV')
    def test_upgrade_backs_up_and_preserves_generated_results(self):
        h.install(self.game,self.bundle,False);addon=self.game/'Interface/AddOns/GuildSimBeta';(addon/'Results.lua').write_text('real results')
        h.install(self.game,self.bundle,False)
        self.assertEqual((addon/'Results.lua').read_text(),'real results')
        self.assertEqual(len(list((self.game/'GuildSimBetaBackups').iterdir())),1)
    def test_upgrade_preserves_json_results_for_alts(self):
        h.install(self.game,self.bundle,False);addon=self.game/'Interface/AddOns/GuildSimBeta';h.save(addon/'GuildResults.json',{'alt':{'result':1}})
        h.install(self.game,self.bundle,False)
        self.assertEqual(h.read_json(addon/'GuildResults.json'),{'alt':{'result':1}})
    def test_install_failure_restores_previous_beta(self):
        h.install(self.game,self.bundle,False)
        shutil=__import__('shutil');real=shutil.copytree
        shutil.rmtree(self.game/'Interface/AddOns/WowSimsExporter')
        def fail(src,dest,*args,**kwargs):
            if Path(src).name=='WowSimsExporter':raise OSError('disk fixture failure')
            return real(src,dest,*args,**kwargs)
        with patch('helper.shutil.copytree',side_effect=fail):
            with self.assertRaisesRegex(OSError,'disk fixture'):h.install(self.game,self.bundle,False)
        self.assertEqual((self.game/'Interface/AddOns/GuildSimBeta/GuildSim.lua').read_text(),'beta v1')
        self.assertFalse(list((self.game/'Interface/AddOns').glob('.*-stage-*')))
    def test_unowned_folder_refused(self):
        (self.game/'Interface/AddOns/GuildSimBeta').mkdir()
        with self.assertRaisesRegex(ValueError,'ownership'):h.install(self.game,self.bundle,False)
    def test_open_game_refused(self):
        with patch('helper.game_running',return_value=True):
            with self.assertRaisesRegex(ValueError,'Close WoW'):h.install(self.game,self.bundle)
    def test_manifest_tampering_and_traversal_refused(self):
        (self.bundle/'addons/GuildSimBeta/GuildSim.lua').write_text('modified')
        with self.assertRaisesRegex(ValueError,'verification'):h.install(self.game,self.bundle,False)
        manifest(self.bundle);data=h.read_json(self.bundle/'manifest.json');data['files']['../outside']='no';h.save(self.bundle/'manifest.json',data)
        with self.assertRaisesRegex(ValueError,'verification'):h.verify_bundle(self.bundle)
    def test_discovery_keeps_duplicate_names_and_newest_export(self):
        for account,ident in [('A','Player-A'),('B','Player-B')]:
            folder=self.game/'WTF/Account'/account/'SavedVariables';folder.mkdir(parents=True)
            char={**self.char,'id':ident};entry={'data':json.dumps(char),'timestamp':time.time()}
            (folder/'WowSimsExporter.lua').write_text('WSEDB='+h.lua({'one':entry,'old':{**entry,'timestamp':1}}),encoding='utf-8')
        rows=h.discover(self.game);self.assertEqual(len(rows),2);self.assertEqual({r['character']['id'] for r in rows},{'Player-A','Player-B'})
    def test_saved_lua_never_executes(self):
        with self.assertRaises(ValueError):h.loads('WSEDB = os.execute("anything")')
    def test_eligibility_for_all_ret_races_and_priest_weapons(self):
        ring={'id':10,'type':11};horde_ring={**ring,'factionRestriction':2};alliance_ring={**ring,'factionRestriction':1}
        for race in ('Human','Dwarf','Undead'):
            char={**self.char,'race':race}
            self.assertEqual(h.eligible(horde_ring,char,'ret'),race=='Undead');self.assertEqual(h.eligible(alliance_ring,char,'ret'),race!='Undead')
        priest={**self.char,'class':'priest'}
        self.assertTrue(h.eligible({'type':14,'rangedWeaponType':5},priest,'disc-raid'))
        self.assertFalse(h.eligible({'type':14,'rangedWeaponType':4},priest,'disc-raid'))
        self.assertTrue(h.eligible({'type':13,'weaponType':2,'handType':2},priest,'disc-raid'))
        self.assertFalse(h.eligible({'type':13,'weaponType':7,'handType':3},priest,'disc-raid'))
    def test_slots_are_native_not_wow_inventory_slots(self):
        self.assertEqual(h.TYPES[4],[3]);self.assertEqual(h.TYPES[5],[4]);self.assertEqual(h.TYPES[11],[10,11]);self.assertEqual(h.TYPES[12],[12,13])
    def test_pool_rune_and_both_slot_orders(self):
        char=copy.deepcopy(self.char);char['gear']['items'][12:14]=[{'id':13965},{'id':19812}]
        rows=h.candidates({'character':char},'ret',{'pool':{11122:True,12846:True,22321:True}},self.db,h.normalize_gear(char['gear']))
        pairs=[r for r in rows if r['kind']=='pair'];self.assertEqual(len(pairs),6)
        self.assertTrue(any(r['items'][0]['id']==19812 for r in pairs));self.assertFalse(any(i['id'] in h.UTILITY for r in pairs for i in r['items']))
        excluded=h.candidates({'character':char},'ret',{'excluded':{19812:True}},self.db,h.normalize_gear(char['gear']))
        self.assertFalse([r for r in excluded if r['kind']=='pair'])
    def test_uniques_and_limit_categories(self):
        self.assertFalse(h.legal({'items':[{'id':1},{'id':1}]},{'1':{'unique':True}}))
        self.assertFalse(h.legal({'items':[{'id':1},{'id':2}]},{'1':{'limitCategory':5},'2':{'limitCategory':5}}))
    def test_lua_serialization_escapes_untrusted_item_names(self):
        data={'x':'"} os.execute("bad") --\n\\','number':3.0}
        self.assertEqual(h.loads('Test='+h.lua(data))['Test'],data)
    def test_item_links_keep_suffix_and_reject_bonus(self):
        self.assertEqual(h.item_spec('item:123:5:0:0:0:0:-17:0'),{'id':123,'enchant':5,'randomSuffix':-17})
        with self.assertRaises(ValueError):h.item_spec('item:123:0:0:0:0:0:0:0:0:0:0:0:1')
        self.assertEqual(h.item_spec('item:123:0:0:0:0:0:0'),{'id':123})
    def test_catalog_reference_does_not_change_on_equipped_pair_swap(self):
        entry={'character':copy.deepcopy(self.char),'account':'A','path':str(self.game/'WTF/Account/A/SavedVariables/WowSimsExporter.lua'),'timestamp':time.time()}
        h.install(self.game,self.bundle,False);entry['character']['gear']['items'][12:14]=[{'id':13965},{'id':19812}]
        runner=h.Runner(h.BASE,self.root/'state');seen=[]
        def fake(req,base):
            seen.append(copy.deepcopy(req))
            return {'baseline':{'dps':100},'reference':{'dps':100},'rows':[{'key':c['key'],'dps':101} for c in req['candidates']],'request':req,'objective':'native DPS'}
        with patch('helper.native',side_effect=fake),patch('helper.sv_request',return_value={}):
            runner.run(entry,{'root':str(self.game)})
            first=len(seen);entry['character']['gear']['items'][12:14]=[{'id':22321},{'id':13965}]
            runner.run(entry,{'root':str(self.game)})
        # Previously observed Rune stays in the pool. Only the equipped baseline
        # and four newly possible pair orders rerun; old pairs and catalog hit cache.
        self.assertEqual(len(seen)-first,5)
    def test_native_rejects_wrong_class_and_unsupported_race(self):
        req={'profile':'ret','character':{**self.char,'race':'Orc'},'duration':30,'iterations':20}
        with self.assertRaisesRegex(ValueError,'race/class'):h.native(req)
        req['character']={**self.char,'class':'priest'}
        with self.assertRaisesRegex(ValueError,'character class'):h.native(req)
    def test_native_disc_requires_disc_build(self):
        char={**self.char,'class':'priest','talents':'00520101133-33505003030121531'}
        with self.assertRaisesRegex(ValueError,'31 Discipline'):h.native({'profile':'disc-raid','character':char,'duration':30,'iterations':20})
    def test_native_rune_changes_damage_only_against_matching_target(self):
        char=copy.deepcopy(self.char);char['gear']['items'][12:14]=[{'id':13965},{'id':19812}]
        req={'profile':'ret','character':char,'iterations':100,'duration':30,'candidates':[]}
        scores={}
        for mob in (0,8):
            for rune in (False,True):
                req['mobType']=mob;char['gear']['items'][13]={'id':19812} if rune else {}
                response=h.native(req);scores[mob,rune]=response['baseline']['dps']
                target=response['request']['encounter']['targets'][0]
                self.assertEqual(target.get('mobType','MobTypeUnknown'),'MobTypeUndead' if mob==8 else 'MobTypeUnknown')
        self.assertAlmostEqual(scores[0,True],scores[0,False]);self.assertGreater(scores[8,True],scores[8,False])

if __name__=='__main__':unittest.main(verbosity=2)
