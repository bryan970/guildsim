"""Exercise addon loading, character-pane hooks, stale results and role metrics in Lua 5.1."""
import sys
import os
import copy
import unittest
from pathlib import Path
if os.environ.get('GUILDSIM_QA_LIBS'):sys.path.insert(0,os.environ['GUILDSIM_QA_LIBS'])
from lupa.lua51 import LuaRuntime
import helper as h

SCRIPT=(Path(__file__).parent/'bundle/addons/GuildSimBeta/GuildSim.lua').read_text(encoding='utf-8')

class AddonTests(unittest.TestCase):
    def fixture(self, priest=True):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
          nodes={};SlashCmdList={};UISpecialFrames={};links={};testClass="PALADIN"
          function node()
            local n={scripts={},hooks={},value="",shown=false}
            setmetatable(n,{__index=function(_,key)
              if key=="CreateFontString" or key=="CreateTexture" then return function()return node()end end
              if key=="SetScript" then return function(self,k,fn)self.scripts[k]=fn end end
              if key=="HookScript" then return function(self,k,fn)self.hooks[k]=fn end end
              if key=="GetFont" then return function()return "font.ttf",12 end end
              if key=="SetText" then return function(self,v)self.value=v end end
              if key=="GetText" then return function(self)return self.value end end
              if key=="Show" then return function(self)self.shown=true end end
              if key=="Hide" then return function(self)self.shown=false end end
              if key=="IsShown" then return function(self)return self.shown end end
              if key=="SetSize" then return function(self,w,h)self.width=w;self.height=h end end
              return function()end
            end});table.insert(nodes,n);return n
          end
          function CreateFrame(_,name)local f=node();if name then _G[name]=f end;return f end
          function UnitGUID()return "Player-TEST" end
          function UnitClass()return testClass,testClass end
          function GetInventoryItemLink(_,slot)return links[slot]end
          function GetItemInfo(id)return "Item "..tostring(id),nil,3,nil,nil,nil,nil,nil,nil,"INV_Icon" end
          function time()return 100 end
          function print()end
          UIParent=node();CharacterFrame=node()
          ITEM_QUALITY_COLORS={[3]={r=.1,g=.4,b=1}}
          WowSimsExporter={BuildExport=function()return "export"end}
        ''')
        if priest:lua.globals().testClass='PRIEST'
        ns=lua.table();lua.execute(SCRIPT,'GuildSimBeta',ns)
        lua.execute('nodes[#nodes].scripts.OnEvent(nil,"PLAYER_LOGIN")')
        return lua,ns

    def payload(self, lua, priest=False):
        row={'kind':'gear','key':'fixture','slot':0,'items':[{'id':1,'name':'Example helm','quality':3,'icon':'INV_Helm','source':'Fixture source'}],'missingEffects':{}}
        base={'stats':{'HealingPower':500,'Mana':6000}}
        if priest:row['stats']={'HealingPower':510,'Mana':6200}
        else:row['dps']=601;base['dps']=600
        return lua.table_from({'Player-TEST':{'version':h.VERSION,'guid':'Player-TEST','profile':'disc-raid' if priest else 'ret','equipped':[{}]*17,'generated':100,'baseline':base,'reference':copy.deepcopy(base),'rows':[row],'complete':True}},recursive=True)
    def healing_payload(self,lua):
        result=self.payload(lua,True);p=result['Player-TEST']
        scenario={'assignment':'group','duration':180}
        p.healingScenario=lua.table_from(scenario)
        for base in (p.baseline,p.reference):
            for key,value in {'healingModel':'guildsim-disc-assignment-1','usefulHps':400,'survival':1,'manaRemaining':500,'meanError95':2}.items():base[key]=value
        row=p.rows[1]
        for key,value in {'healingModel':'guildsim-disc-assignment-1','usefulHps':420,'survival':1,'manaRemaining':600,'effectiveHps':300,'absorbHps':120,'overhealHps':30,'meanError95':2,'iterations':256}.items():row[key]=value
        return result

    def test_personal_panel_keeps_automatic_character_hook(self):
        lua,_=self.fixture();lua.execute('RetSimBridgeDB={};CharacterFrame.hooks.OnShow()')
        self.assertFalse(lua.globals().GuildSimBetaCharacterPanel.shown)
        lua.execute('SlashCmdList.GUILDSIMBETA("")');self.assertTrue(lua.globals().GuildSimBetaCharacterPanel.shown)
    def test_stale_target_hides_old_dps(self):
        lua,ns=self.fixture();ns.results=self.healing_payload(lua)
        lua.execute('SlashCmdList.GUILDSIMBETA("")');browser=lua.globals().GuildSimBetaBrowser
        self.assertTrue(browser.rows[1].shown)
        browser.mob.scripts.OnClick()
        self.assertFalse(browser.rows[1].shown);self.assertIn('Healing assignment changed',browser.empty.value)
    def test_stale_gear_hides_old_dps(self):
        lua,ns=self.fixture();ns.results=self.payload(lua,True)
        lua.execute('links[1]="item:999:0:0:0:0:0:0";SlashCmdList.GUILDSIMBETA("")')
        browser=lua.globals().GuildSimBetaBrowser;self.assertFalse(browser.rows[1].shown);self.assertIn('Gear changed',browser.empty.value)
    def test_legacy_disc_stats_are_labelled_for_resimulation(self):
        lua,ns=self.fixture(True);ns.results=self.payload(lua,True)
        lua.execute('SlashCmdList.GUILDSIMBETA("")');browser=lua.globals().GuildSimBetaBrowser
        self.assertEqual(browser.rows[1].value.value,'510 / 6200');self.assertEqual(browser.rows[1].gain.value,'+10 HP')
        self.assertIn('Update sims',browser.subtitle.value)
    def test_disc_displays_real_useful_hps_and_survival(self):
        lua,ns=self.fixture(True);ns.results=self.healing_payload(lua)
        lua.execute('SlashCmdList.GUILDSIMBETA("")');browser=lua.globals().GuildSimBetaBrowser
        self.assertEqual(browser.rows[1].value.value,'420.0 / 100%');self.assertEqual(browser.rows[1].gain.value,'+20.0 HPS')
        self.assertIn('consumed shields',browser.subtitle.value)
        browser.family.scripts.OnClick();self.assertIn('Healing assignment changed',browser.empty.value)
    def test_disc_prioritizes_survival_and_labels_sampling_ties(self):
        lua,ns=self.fixture(True);ns.results=self.healing_payload(lua);p=ns.results['Player-TEST']
        p.rows[1].usefulHps=401
        other={'kind':'gear','key':'fails','slot':0,'items':[{'id':2,'name':'Fails assignment','quality':3}],'healingModel':'guildsim-disc-assignment-1','usefulHps':900,'survival':.8,'stats':{},'missingEffects':{}}
        p.rows[2]=lua.table_from(other,recursive=True)
        lua.execute('SlashCmdList.GUILDSIMBETA("")');browser=lua.globals().GuildSimBetaBrowser
        self.assertEqual(browser.rows[1].data.key,'fixture');self.assertEqual(browser.rows[1].gain.value,'≈ tied')
    def test_pool_and_capture_are_separate_from_personal_savedvariables(self):
        lua,_=self.fixture();lua.execute('RetSimBridgeDB={untouched=true};SlashCmdList.GUILDSIMBETA("pool 19812");SlashCmdList.GUILDSIMBETA("update")')
        self.assertTrue(lua.globals().GuildSimBetaDB.characters['Player-TEST'].pool[19812])
        self.assertTrue(lua.globals().RetSimBridgeDB.untouched)
        self.assertEqual(lua.globals().GuildSimBetaDB.characters['Player-TEST'].requestedAt,100)

if __name__=='__main__':unittest.main(verbosity=2)
