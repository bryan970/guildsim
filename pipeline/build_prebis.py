from guild_runtime import runtime_root, usable_faction
"""Compare documented pre-raid candidates as complete level-60 Ret sets."""
import json
import math
from pathlib import Path
import subprocess
import time

BASE=runtime_root()
SOURCES={
 'uw':'https://wowforeverbislist.com/preraid/paladin/retribution/',
 'tools':'https://www.60.tools/bis/paladin/retribution',
 'spec':'https://foreverspec.com/pre-raid-bis/paladin/retribution/'
}
SLOTS=['Head','Neck','Shoulders','Back','Chest','Wrists','Hands','Waist','Legs','Feet','Ring 1','Ring 2','Trinket 1','Trinket 2','Two-hand','Off-hand','Libram']
WOW_SLOTS=[1,2,3,15,5,9,10,6,7,8,11,12,13,14,16,17,18]
ENCHANTS={1:8218,3:7667,4:1891,5:7665,6:7646,9:1887,14:7662}

def database():
    items={}
    for name in ['db.json','leftover_db.json']:
        for item in json.loads((BASE/'vendor/forever-master/assets/database'/name).read_text(encoding='utf-8'))['items']:
            items[item['id']]=item
    return items

def main():
    items=database(); by_name={v['name']:k for k,v in items.items()}
    candidates={}
    def add(slot,name,source,where,order=2,note=''):
        item_id=by_name[name]
        candidates.setdefault(slot,[]).append({'id':item_id,'name':name,'source':SOURCES[source],
          'where':where,'priority':order,'note':note,'slot':SLOTS[slot],'wow_slot':WOW_SLOTS[slot],
          'required_level':items[item_id].get('reqLvl',60)})
    add(0,'Lionheart Helm','uw','Commission a Blacksmith; farm crafting materials.',1)
    add(1,'Nacreous Shell Necklace','uw','Cannon Master Willey — Stratholme.',2)
    add(1,'Beads of Ogre Might','uw',"Falrin's Vendetta — Dire Maul quest.",1)
    add(2,'Truestrike Shoulders','spec','Pyroguard Emberseer — Upper Blackrock Spire.',2)
    add(2,'Mantle of the Timbermaw','uw','Commission a Tailor who knows the Timbermaw recipe.',2)
    add(2,'Lightforge Spaulders','tools','The Beast — Upper Blackrock Spire; check current drop table.',3)
    add(3,'Arcanoweave Cloak','uw','Pix Xizzix — Booty Bay; Tarnished Undermine Real vendor.',1)
    add(3,"Howler's Furs",'tools','Pix Xizzix — Booty Bay; Tarnished Undermine Real vendor.',1)
    add(4,'Timbermaw Tunic','uw','Commission a Leatherworker who knows the Timbermaw recipe.',1)
    add(4,'Soulforge Breastplate','uw','Mokvar — Orgrimmar; Soulforge upgrade/vendor requirements.',3)
    add(5,'Battleborn Armbraces','uw','Warchief Rend Blackhand — Upper Blackrock Spire.',2)
    add(5,'Spitfire Bracers','tools','Commission a Leatherworker; recipe/material availability must be checked.',2)
    add(6,'Heartflame Gauntlets','uw',"Cinder — The Shaper's Terrace.",2)
    add(6,'Soulforge Gauntlets','tools','Mokvar — Orgrimmar; Soulforge upgrade/vendor requirements.',3)
    add(7,'Belt of the Archmage','uw','Commission a Tailor; compare material cost before buying.',3)
    add(7,'Might of the Timbermaw','spec','Commission a Leatherworker with the Timbermaw recipe.',1)
    add(7,"Justicar's Waistguard",'tools','Commission a Blacksmith.',2)
    add(8,'Pristine Scorpid Leggings','uw','Commission a Leatherworker.',2)
    add(8,'Titanic Leggings','tools','Commission a Blacksmith; compare material cost before buying.',3)
    add(9,"Furbolg Berserker's Boots",'uw','Blackmaw Devotee — Blackmaw Hold.',2)
    add(9,'Soulforge Warboots','tools','Mokvar — Orgrimmar; Soulforge upgrade/vendor requirements.',3)
    for slot in [10,11]:
        add(slot,"Don Mauricio's Band of Domination",'uw','Darkmaster Gandling — Scholomance.',2)
        add(slot,"Channeler's Ring",'uw','Pix Xizzix — Booty Bay; Tarnished Undermine Real vendor.',1)
        add(slot,"Cutthroat's Signet",'tools','Pix Xizzix — Booty Bay; Tarnished Undermine Real vendor.',1)
        add(slot,'Blackstone Ring','tools','Princess Theradras — Maraudon.',1)
    for slot in [12,13]:
        add(slot,'Hand of Justice','uw','Emperor Dagran Thaurissan — Blackrock Depths.',2)
        add(slot,'Adaptive Combat Assistant','uw','Pix Xizzix — Booty Bay; Tarnished Undermine Real vendor.',1)
        add(slot,"Blackhand's Breadth",'spec','For The Horde! — Horde Blackrock Spire quest reward.',1)
    add(14,'Destiny','uw','Hearthsinger Forresten — Stratholme; source reported by the current list.',3,'Proc-dependent; ranking depends on the simulator proc model.')
    add(14,'Stormcarver','tools','Commission a Blacksmith; usable at level 58.',2)
    add(14,"Forest Defender's Axe",'spec','Commission a Blacksmith; requires level 60.',3)
    add(14,'Arcanite Reaper','tools','Commission a Blacksmith; compare material cost before buying.',3)
    add(14,'Tuskblade Halberd','uw','Bonesnout the Unbroken — Blackmaw Hold.',2)
    add(16,'Libram of Law','uw','Pix Xizzix — Booty Bay; Tarnished Undermine Real vendor.',1)
    # A published alternate is a candidate pool entry, not a claim that it is best.
    exclusions=[
      {'id':227808,'name':'Rugged Mantle of the Timbermaw','reason':'Requires Tailoring 290; your export has Mining and Enchanting.'},
      {'id':228190,'name':'Knowledge of the Timbermaw','reason':'Requires Tailoring 290; your export has Mining and Enchanting.'},
      {'name':"Magni's Will",'reason':'Alliance quest reward; excluded for your Horde character.'},
      {'name':"Don Julio's Band / PvP reputation rewards",'reason':'Excluded from the starter plan to avoid an exalted PvP reputation requirement.'}
    ]
    work=BASE/'output/prebis-comparisons';work.mkdir(parents=True,exist_ok=True)
    scenario=json.loads((BASE/'scenario.json').read_text(encoding='utf-8'));scenario['target_talents']='050250002-501-05233011201301351'
    gear=[12640,22403,12927,272411,252484,12936,280028,18405,252606,287033,22433,272406,11815,272437,647,0,272435]
    def spec(ids):return {'items':[dict(id=i,**({'enchant':ENCHANTS[n]} if n in ENCHANTS and i else {})) for n,i in enumerate(ids)]}
    results=[]
    def sim(ids,label,iterations=1000):
        cfg=dict(scenario,target_gear=spec(ids),name='Pre-raid candidate comparison — 180s boss, no external buffs')
        path=work/'trial.json';path.write_text(json.dumps(cfg))
        output=work/'trial-result.json'
        p=subprocess.run([str(BASE/'retlocal.exe'),'--root',str(BASE/'vendor/forever-master'),
            '--character',str(BASE/'output/character.json'),'--scenario',str(path),'--mode','planning',
            '--iterations',str(iterations),'--no-weights','--out',str(output)],capture_output=True,text=True)
        if p.returncode:raise RuntimeError(p.stderr)
        r=json.loads(output.read_text(encoding='utf-8'));m=r['baseline']['raidMetrics']['dps']; mean=m['avg']; se=m['stdev']/math.sqrt(iterations)
        results.append({'label':label,'dps':mean,'standard_error':se,'iterations':iterations,'gear':ids[:]})
        return mean
    score=sim(gear,'Adapted Unsealed Wrath list')
    # Two deterministic coordinate passes compare whole equipped sets, including proc/set effects.
    # This searches a documented pool; it is not an exhaustive global BiS claim.
    for pass_no in range(2):
        changed=False
        for slot,pool in candidates.items():
            if len(pool)<2:continue
            best=gear[slot];best_score=score
            for c in pool:
                if c['id']==gear[slot]:continue
                if slot in [10,11] and c['id']==gear[21-slot]:continue
                if slot in [12,13] and c['id']==gear[25-slot]:continue
                trial=gear[:];trial[slot]=c['id']
                value=sim(trial,f'Pass {pass_no+1}: {SLOTS[slot]} — {c["name"]}')
                if value>best_score+0.75:best=c['id'];best_score=value
            if best!=gear[slot]:gear[slot]=best;score=best_score;changed=True
        print(f'Pass {pass_no+1}: {score:.2f} DPS',flush=True)
        if not changed:break
    final=sim(gear,'Final selected set — confirmation',5000)
    target=[]
    for slot,item_id in enumerate(gear):
        if not item_id:continue
        row=dict(next(x for x in candidates[slot] if x['id']==item_id))
        row['enchant']=ENCHANTS.get(slot,0)
        row['alternatives']=[x for x in candidates[slot] if x['id']!=item_id]
        target.append(row)
    hit=sum(items[i].get('scalingOptions',{}).get('0',{}).get('stats',{}).get('17',0) for i in gear if i)/10
    exp=sum(items[i].get('scalingOptions',{}).get('0',{}).get('stats',{}).get('21',0) for i in gear if i)/10
    (BASE/'prebis-targets.json').write_text(json.dumps({'name':'Ret60 UW Pre-raid Target','checked':'2026-11-18',
        'talents':'14/6/31 Unsealed Wrath','talents_string':scenario['target_talents'],
        'assumptions':'180 seconds, level-63 boss from behind, no external buffs or consumables; listed stat enchants.',
        'method':'Two coordinate passes over documented candidates, fixed seed; final 5000-iteration baseline. Not exhaustive BiS optimization.',
        'sources':SOURCES,'exclusions':exclusions,'items':target,'baseline_dps':final,
        'caps':{'gear_hit_percent':hit,'precision_hit_percent':1.0,'total_melee_hit_percent':hit+1,'expertise_percent':exp}},indent=2))
    (work/'comparisons.json').write_text(json.dumps(results,indent=2))
    scenario['target_gear']=spec(gear)
    scenario['name']='Horde Unsealed Wrath pre-raid target — 180s boss, no external buffs'
    (BASE/'scenario.json').write_text(json.dumps(scenario,indent=2))
    print('Selected:',[(x['slot'],x['name']) for x in target],flush=True)
    print('Confirmation DPS:',round(final,2),flush=True)
if __name__=='__main__':main()
