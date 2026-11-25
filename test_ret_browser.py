import json
from pathlib import Path
import sys
import os
import unittest

BASE=Path(__file__).resolve().parent/'bundle/ret-engine'
if os.environ.get('GUILDSIM_QA_LIBS'):sys.path.insert(0,os.environ['GUILDSIM_QA_LIBS'])
from lupa.lua51 import LuaRuntime


class GearBrowserTests(unittest.TestCase):
    def test_engine_upgrade_rejects_older_weapon_and_projection_results(self):
        lua,ns=self.fixture();ns.engineCommit='new-engine'
        ns.weaponResults=lua.table_from({'guid':'TEST','engineCommit':'old-engine'},recursive=True)
        context,why=ns.WeaponData('equipped');self.assertIsNone(context);self.assertIn('engine updated',why)
        ns.payload=lua.table_from({'mode':'current','wowsims':{'upstream_commit':'old-engine'}},recursive=True)
        fresh,why=ns.ProjectionWeightsFresh();self.assertFalse(fresh);self.assertIn('engine updated',why)
    def test_stale_weapon_results_preserve_catalog_without_claiming_current_dps(self):
        lua,ns=self.fixture()
        ns.WeaponData=lua.eval('function()return nil,"Gear changed; update needed"end')
        ns.weaponResults=lua.table_from({'guid':'TEST','contexts':[{'key':'equipped','enchant':1900,'weapons':[{'id':99,'name':'Saved weapon','dps':650,'delta':10,'iterations':12500}]}]},recursive=True)
        rows,why=ns.GearBrowserRows(13,False)
        row=next(r for r in rows.values() if r.id==99)
        self.assertTrue(row.stale);self.assertIsNone(row.dps);self.assertEqual(why,'Gear changed; update needed')
        ns.ShowGearBrowser('gear',15)
        self.assertIn('need update',lua.globals().GuildSimBetaGearBrowser.pageText.value)
    def test_unsimulated_suffix_variants_remain_visible_beside_a_simulated_variant(self):
        lua,ns=self.fixture()
        ns.itemResults=lua.table_from({'names':{1:'Random helm'},'items':{'1:10:0':{'id':1,'name':'Random helm','randomSuffix':10,'dps':600,'delta':1}},
            'browserSuffixNames':{10:'of the Bear',20:'of the Eagle'},
            'browserItems':{1:[1,3,'','Drop','Boss',60,'',[10,20]]}},recursive=True)
        rows,why=ns.GearBrowserRows(1,False)
        by_suffix={row.first.randomSuffix:row for row in rows.values()}
        self.assertEqual(len(by_suffix),2)
        self.assertEqual(by_suffix[10].name,'Random helm of the Bear')
        self.assertEqual(by_suffix[10].dps,600)
        self.assertEqual(by_suffix[20].name,'Random helm of the Eagle')
        self.assertIsNone(by_suffix[20].dps)

    def fixture(self):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
          nodes={}
          function node()
            local n={scripts={},hooks={},value="",shown=false}
            setmetatable(n,{__index=function(_,key)
              if key=="CreateFontString" or key=="CreateTexture" then return function()return node()end end
              if key=="SetScript" then return function(self,k,fn)self.scripts[k]=fn end end
              if key=="HookScript" then return function(self,k,fn)self.hooks=self.hooks or {};self.hooks[k]=self.hooks[k] or {};table.insert(self.hooks[k],fn)end end
              if key=="SetWidth" then return function(self,w)self.width=w end end
              if key=="SetPoint" then return function(self,...)self.anchor={...} end end
              if key=="GetFont" then return function()return "Fonts/FRIZQT__.TTF",12,""end end
              if key=="SetFont" then return function(self,face,size)self.fontSize=size end end
              if key=="SetBackdropColor" then return function(self,r,g,b,a)self.backdropAlpha=a end end
              if key=="SetHeight" then return function(self,h)self.height=h end end
              if key=="SetSize" then return function(self,w,h)self.width=w;self.height=h end end
              if key=="GetWidth" then return function(self)return rawget(self,"width") or 1180 end end
              if key=="GetHeight" then return function(self)return rawget(self,"height") or 600 end end
              if key=="GetRight" then return function(self)return rawget(self,"right") or 0 end end
              if key=="GetEffectiveScale" then return function()return 1 end end
              if key=="IsShown" then return function(self)return self.shown end end
              if key=="Hide" then return function(self)self.shown=false end end
              if key=="SetShown" then return function(self,v)self.shown=v end end
              if key=="SetText" then return function(self,text)self.value=text end end
              if key=="GetText" then return function(self)return self.value end end
              if key=="GetChecked" then return function(self)return rawget(self,"checked") or false end end
              if key=="SetChecked" then return function(self,value)self.checked=value end end
              if key=="Show" then return function(self)self.shown=true end end
              return function()end
            end})
            table.insert(nodes,n);return n
          end
          function CreateFrame(_,name)local n=node();if name then _G[name]=n end;return n end
          function UnitGUID()return "TEST" end
          function UnitClass()return "Paladin","PALADIN" end
          function time()return 100 end
          function GetInventoryItemLink()return nil end
          function GetItemInfoInstant(value)return tonumber(value),nil,nil,"INVTYPE_TRINKET" end
          function print()end
          UIParent=node();UISpecialFrames={}
        ''')
        ns=lua.table()
        lua.execute((BASE/'addon/WeaponViewer.lua').read_text(encoding='utf-8'),'GuildSimBeta',ns)
        lua.execute((BASE/'addon/ItemViewer.lua').read_text(encoding='utf-8'),'GuildSimBeta',ns)
        ns.ItemComparisonsFresh=lua.eval('function()return true end')
        ns.itemResults=lua.table_from({'names':{1:'Simulated helm',2:'Unsimulated helm'},'items':{'1:0:0':{'id':1,'name':'Simulated helm','dps':600,'delta':20}},
            'browserItems':{1:[1,3,'','Drop','Boss'],2:[1,4,'','Crafted','Blacksmithing']},'comparisonLabel':'Fixed pair'},recursive=True)
        return lua,ns

    def test_browser_keeps_unknown_items_without_inventing_dps_and_constructs_window(self):
        lua,ns=self.fixture();rows,why=ns.GearBrowserRows(1,False)
        by_id={row.id:row for row in rows.values()}
        self.assertEqual(by_id[1].dps,600);self.assertIsNone(by_id[2].dps)
        self.assertEqual(by_id[2].source,'Blacksmithing')
        ns.ShowGearBrowser('gear')
        self.assertTrue(lua.globals().GuildSimBetaGearBrowser.shown)
        self.assertEqual(len(lua.globals().GuildSimBetaGearBrowser.rows),14)
        self.assertIn('Fixed pair',lua.globals().GuildSimBetaGearBrowser.setup.value)
        ns.ItemComparisonsFresh=lua.eval('function()return false,"Needs sync"end')
        rows,why=ns.GearBrowserRows(1,False)
        self.assertEqual(why,'Needs sync');self.assertTrue(all(row.dps is None for row in rows.values()))

    def test_character_panel_opens_with_paper_doll_links_slots_and_hides_attached_browser(self):
        lua,ns=self.fixture()
        lua.execute('CharacterFrame=node();CharacterFrame.shown=true;CharacterFrame.height=620;CharacterFrame.right=700;UIParent.width=2300;UIParent.height=1000')
        ns.AttachCharacterPanel()
        panel=lua.globals().GuildSimBetaCharacterPanel
        self.assertTrue(panel.shown);self.assertEqual(len(panel.rows),16)
        panel.rows[1].scripts.OnClick()
        browser=lua.globals().GuildSimBetaGearBrowser
        self.assertTrue(browser.shown);self.assertTrue(browser.docked);self.assertEqual(browser.width,934)
        self.assertFalse(browser.slots[1].shown)
        lua.globals().CharacterFrame.hooks.OnHide[1]()
        self.assertFalse(browser.shown);self.assertFalse(panel.shown)
        lua.globals().CharacterFrame.hooks.OnShow[1]()
        self.assertTrue(panel.shown)
        ns.AttachCharacterPanel()
        self.assertEqual(len(lua.globals().CharacterFrame.hooks.OnShow),1)
        ns.ShowGearBrowser('gear',None,False)
        self.assertFalse(browser.docked);self.assertEqual(browser.width,1180)

    def test_readability_and_small_pane_rows_leave_space_for_footer(self):
        lua,ns=self.fixture()
        lua.execute('CharacterFrame=node();CharacterFrame.shown=true;CharacterFrame.right=700;UIParent.width=2300;UIParent.height=1000')
        ns.AttachCharacterPanel();panel=lua.globals().GuildSimBetaCharacterPanel
        for height in (400,480,620,800):
            panel.height=height;ns.UpdateCharacterPanel()
            last=panel.rows[16]
            bottom=-last.anchor[3]+last.height
            self.assertLessEqual(bottom,panel.height-48)
        panel.rows[1].scripts.OnClick();browser=lua.globals().GuildSimBetaGearBrowser
        self.assertEqual(browser.backdropAlpha,1)
        self.assertEqual(panel.backdropAlpha,1)
        self.assertGreaterEqual(browser.rows[1].item.fontSize,13)
        self.assertLessEqual(-browser.rows[14].anchor[3]+browser.rows[14].height,680)

    def test_pool_controls_do_not_clutter_gear_and_empty_state_can_clear_filters(self):
        lua,ns=self.fixture();ns.ShowGearBrowser('gear');browser=lua.globals().GuildSimBetaGearBrowser
        self.assertFalse(browser.poolButton.shown);self.assertFalse(browser.poolEditor.shown)
        self.assertTrue(browser.sourceButton.shown)
        browser.search.SetText(browser.search,'no matching item');ns.ShowGearBrowser('gear')
        self.assertTrue(browser.empty.shown);self.assertTrue(browser.clearFilters.shown)
        browser.clearFilters.scripts.OnClick()
        self.assertFalse(browser.empty.shown)
        self.assertEqual(browser.search.value,'')

    def test_pool_add_exclude_and_automatic_remember_preserve_exclusion(self):
        lua,ns=self.fixture()
        self.assertTrue(ns.EditTrinketPool('13965',False))
        self.assertEqual(lua.globals().GuildSimBetaDB.trinketPool.TEST['13965:0:0'].id,13965)
        self.assertTrue(ns.EditTrinketPool('13965',True))
        ns.RememberTrinket('13965')
        self.assertTrue(lua.globals().GuildSimBetaDB.trinketExclusions.TEST[13965])
        ns.RememberTrinket('11122')
        self.assertIsNone(lua.globals().GuildSimBetaDB.trinketPool.TEST['11122:0:0'])
        ns.payload=lua.table_from({'mountTrinketIds':[11122,12846,19812]},recursive=True)
        self.assertTrue(ns.EditTrinketPool('19812',False))
        self.assertEqual(lua.globals().GuildSimBetaDB.trinketPool.TEST['19812:0:0'].id,19812)

    def test_uncomputed_matchup_does_not_fall_back_to_raid_results_and_can_be_requested(self):
        lua,ns=self.fixture()
        ns.fightProfiles=lua.table_from([{'key':'default','label':'Raid setup'},{'key':'undead','label':'Undead'}],recursive=True)
        ns.trinketPairProfiles=lua.table_from({'default':{'rows':[]}},recursive=True)
        ns.trinketPairTarget='undead'
        rows,why=ns.GearBrowserRows(12,True)
        self.assertEqual(len(rows),0);self.assertIn('not simulated',why)
        self.assertTrue(ns.RequestFightProfile('undead'))
        self.assertTrue(lua.globals().GuildSimBetaDB.fightProfileRequests.TEST.undead)
        self.assertFalse(ns.RequestFightProfile('unsupported'))

    def test_fresh_pairs_have_separate_numbers_and_window_is_constructed(self):
        lua,ns=self.fixture()
        ns.LiveSimExport=lua.eval('function()return "source"end')
        ns.SameCatalogExport=lua.eval('function()return true end')
        ns.trinketPairs=lua.table_from({'guid':'TEST','generated':90,'sourceExport':'source','comparisonLabel':'Pair baseline',
            'baselineDps':600,'rows':[{'first':{'id':13965},'second':{'id':22321},'firstName':'First',
                'secondName':'Second','dps':625,'delta':25,'iterations':12500,'pairedError95':.5}]},recursive=True)
        rows=ns.GearBrowserRows(12,True)
        self.assertEqual(rows[1].dps,625)
        ns.ShowTrinketPairs()
        self.assertEqual(lua.globals().GuildSimBetaGearBrowser.mode,'pairs')
        self.assertEqual(lua.globals().GuildSimBetaGearBrowser.rows[1].data.delta,25)
        self.assertNotIn('need a saved capture',lua.globals().GuildSimBetaGearBrowser.status.value)


if __name__=='__main__':unittest.main()
