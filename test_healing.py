"""Native Priest assignments through the helper, publication and per-fight cache."""
import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import helper as h

class HealingIntegrationTests(unittest.TestCase):
    def test_full_catalog_keeps_screened_rows_refines_leaders_and_survives_quick_refresh(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);game=root/'game';addon=game/'Interface/AddOns/GuildSimBeta'
            addon.mkdir(parents=True);(game/'WTF').mkdir()
            p=h.read_json(h.BASE/'defaults.json')['disc']
            char={'id':'Player-PUBLIC-CATALOG','name':'Public catalog fixture','class':'priest','race':'Dwarf','talents':p['talentsString'],'gear':copy.deepcopy(p['equipment'])}
            runner=h.Runner(h.BASE,root/'state');ref=h.normalize_gear(char['gear'])['items'][12:14]
            heads=sorted(int(k) for k,v in runner.db.items() if v.get('type')==1 and not v.get('randomSuffixOptions') and h.eligible(v,{**char,'level':60},'disc-raid'))[:30]
            self.assertEqual(len(heads),30)
            jobs=[]
            for item in heads:
                gear=h.normalize_gear(char['gear']);gear['items'][0]={'id':item}
                jobs.append({'key':str(item),'kind':'gear','slot':0,'gear':gear,'items':[{'id':item}]})
            scenario={'assignment':'group','duration':180}
            baseline={
                'baseline':{'stats':{},'usefulHps':100,'healingScenario':scenario},
                'reference':{'stats':{},'usefulHps':100},
                'request':{'raid':{'parties':[{'players':[{'equipment':char['gear']}]}]}},
                'objective':'native useful healing',
            }
            calls=[]
            def simulate(req,base):
                calls.append(req)
                return {'rows':[{'key':c['key'],'stats':{},'usefulHps':c['gear']['items'][0]['id']/100,'survival':1,'iterations':req['iterations'],'meanError95':1,'healingModel':'guildsim-disc-assignment-1','healingScenario':scenario} for c in req['candidates']]}
            request={'profile':'disc-raid','character':char,'reference':char['gear'],'healing':scenario,'duration':180,'iterations':256}
            with patch('helper.native',side_effect=simulate):
                rows=runner.healing_comparisons(addon,char,baseline,jobs,ref,0,0,request,True,lambda _:None)
                self.assertEqual(len(rows),30);self.assertEqual(sum(not r['screening'] for r in rows),12)
                self.assertEqual({c['iterations'] for c in calls},{32,256});self.assertTrue(all(c['skipBaseline'] for c in calls))
                runner.healing_comparisons(addon,char,baseline,[jobs[0]],ref,0,0,request,False,lambda _:None)
            saved=h.read_json(addon/'GuildResults.json')[char['id']]
            self.assertEqual(len(saved['rows']),30);self.assertEqual(sum(not r['screening'] for r in saved['rows']),13)

    def test_native_assignments_publish_hps_and_keep_distinct_fight_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);game=root/'game';addon=game/'Interface/AddOns/GuildSimBeta'
            addon.mkdir(parents=True);(game/'WTF').mkdir();(addon/'.guildsim-owned').write_text('GuildSim')
            p=h.read_json(h.BASE/'defaults.json')['disc']
            char={'id':'Player-PUBLIC-HEALER','name':'Public healing fixture','flavor':'forever','class':'priest','race':'Dwarf','level':60,'talents':p['talentsString'],'gear':copy.deepcopy(p['equipment'])}
            entry={'character':char,'account':'PUBLIC','path':str(game/'WTF/WowSimsExporter.lua'),'timestamp':time.time()}
            runner=h.Runner(h.BASE,root/'state');settings={'root':str(game),'healing_iterations':20}
            jobs=h.candidates(entry,'disc-raid',{},runner.db,h.normalize_gear(char['gear']))
            pair_jobs=[j for j in jobs if j['kind']=='pair']
            self.assertGreaterEqual(len(pair_jobs),2)
            selected=pair_jobs[:2]+[next(j for j in jobs if j['kind']=='gear')]
            for assignment in ('group','tank','burst'):
                with patch('helper.sv_request',return_value={'healingAssignment':assignment,'healingDuration':180}),patch('helper.candidates',return_value=selected):
                    base,rows=runner.run(entry,settings)
                self.assertGreater(base['baseline']['usefulHps'],0)
                self.assertEqual(len(rows),3)
                self.assertTrue(all('usefulHps' in r and 'dps' not in r and 'survival' in r for r in rows))
                payload=h.read_json(addon/'GuildResults.json')[char['id']]
                self.assertEqual(payload['healingScenario']['assignment'],assignment)
                self.assertIn('consumed absorbs',payload['objective'])
            self.assertEqual(len(list((runner.state/'fights').glob('*.json'))),3)
            with patch('helper.sv_request',return_value={'healingAssignment':'group','healingDuration':180}),patch('helper.candidates',return_value=selected),patch('helper.native',side_effect=AssertionError('Exact prior assignment should use cache')):
                runner.run(entry,settings)

if __name__=='__main__':unittest.main(verbosity=2)
