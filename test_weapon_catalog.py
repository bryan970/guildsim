import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent/'pipeline'))
import catalog_weapons as catalog
import refresh_scope
import weapon_sims

class WeaponCatalogTests(unittest.TestCase):
    def test_requested_weapon_reaches_catalog_selection_outside_default_phase(self):
        class Selected(Exception):pass
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'scenario.json').write_text('{}')
            gear={'items':[{} for _ in range(17)]};gear['items'][14]={'id':1}
            db={1:{'id':1,'handType':4,'weaponType':9,'phase':1},2:{'id':2,'handType':4,'weaponType':9,'phase':2}}
            def choose(database,equipment,requested):
                self.assertEqual(requested,[{'id':2}]);raise Selected()
            with patch.object(catalog,'BASE',root),patch('run.latest',return_value=({}, {'gear':gear})),patch.object(refresh_scope,'candidates',return_value=[{'id':2}]),patch.object(weapon_sims,'database',return_value=db),patch.object(weapon_sims,'candidates',side_effect=choose):
                with self.assertRaises(Selected):catalog.refresh({})
    def test_saved_weapon_queue_is_part_of_focused_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'GuildSimBeta.lua').write_text('GuildSimBetaDB={weaponQueue={PUBLIC={["2:0"]={id=2,randomSuffix=0}}}}')
            with patch('item_sims.planning_candidates',return_value=[]):
                selected=refresh_scope.candidates({'saved_variables':str(root/'WowSimsExporter.lua')},{'id':'PUBLIC','gear':{'items':[]}})
            self.assertIn({'id':2,'randomSuffix':0},selected)
