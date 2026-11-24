from guild_runtime import runtime_root, usable_faction
"""Screen the local item catalog, then simulate an expanded pre-raid pool."""
import copy
import itertools
import json
import math
from pathlib import Path
import re
import subprocess
from build_prebis import BASE,SLOTS,WOW_SLOTS,ENCHANTS,database

def main():
    db=database()
    catalog=json.loads((BASE/'vendor/forever-master/assets/database/db.json').read_text(encoding='utf-8'))
    zones={x['id']:x['name'] for x in catalog['zones']}
    npcs={x['id']:x for x in catalog['npcs']}
    dungeons={1583,1584,2017,2057,2100,2557,16550,16554,16611,16667,16919,1477}
    audit=json.loads((BASE/'craft-audit.json').read_text(encoding='utf-8'))
    allowed=set(audit['allowed_crafts'])
    old=json.loads((BASE/'prebis-targets.json').read_text(encoding='utf-8'))
    scenario=json.loads((BASE/'scenario.json').read_text(encoding='utf-8'))
    weights=json.loads((BASE/'output/result.json').read_text(encoding='utf-8'))['weights']['dps']['epValues']['stats']
    pool={}; all_rows={}; discarded=[]
    def slot_for(item):
        t=item.get('type',0)
        if t in range(1,11):return t-1
        if t==11:return 10
        if t==12:return 12
        if t==13 and item.get('handType')==4 and item.get('weaponType') in [1,4,6,9]:return 14
        if t==14 and item.get('rangedWeaponType')==7:return 16
    def usable(item):
        return (item.get('reqLvl',0)<=60 and item.get('phase',1)<=1 and item.get('quality',0)>=2
                and usable_faction(item.get('factionRestriction',0)) and (not item.get('classAllowlist') or 2 in item['classAllowlist'])
                and bool(item.get('scalingOptions',{}).get('0')))
    def crafted(item):return any('crafted' in x for x in item.get('sources',[]))
    def quest_groups(item):
        qs=[x['quest']['id'] for x in item.get('sources',[]) if 'quest' in x and x['quest'].get('faction',0)!=1]
        other=any('drop' in x or 'soldBy' in x or 'crafted' in x for x in item.get('sources',[]))
        return qs if not other else []
    def row(item,where=None,source=None,priority=2):
        slot=slot_for(item)
        return dict(id=item['id'],name=item['name'],slot=SLOTS[slot],wow_slot=WOW_SLOTS[slot],
             where=where or 'See the item source.',source=source or 'https://www.wowhead.com/forever/item='+str(item['id']),
             priority=priority,note='',required_level=item.get('reqLvl',60),quest_groups=quest_groups(item))
    def insert(r):
        i=r['id'];item=db.get(i)
        if not item or not usable(item):return
        if crafted(item) and i not in allowed:
            discarded.append({'id':i,'name':item['name'],'reason':'Craft not allowed by recipe/material audit'});return
        slot=slot_for(item)
        if slot is None:return
        all_rows[i]=r;pool.setdefault(slot,{})[i]=r
    for r in old['items']:
        insert(row(db[r['id']],r['where'],r['source'],r['priority']))
        for a in r.get('alternatives',[]):insert(row(db[a['id']],a['where'],a['source'],a['priority']))
    # Recipe availability is deliberately stricter than a stat-only pre-BiS list.
    for slot in list(pool):pool[slot].pop(12640,None)
    all_rows.pop(12640,None)
    raw={}
    for item in db.values():
        if not usable(item) or slot_for(item) is None or crafted(item):continue
        routes=[]
        for source in item.get('sources',[]):
            if 'drop' in source:
                d=source['drop'];npc=npcs.get(d.get('npcId'),{});zone=d.get('zoneId') or npc.get('zoneId')
                if zone in dungeons:routes.append((npc.get('name','NPC '+str(d.get('npcId')))+' — '+zones.get(zone,str(zone))+'.'))
            if 'soldBy' in source:
                v=source['soldBy']
                if v.get('npcId') in [227853,230317] and v.get('faction',0)!=1:
                    routes.append(v.get('npcName','Vendor')+' — '+zones.get(v.get('zoneId'),'check vendor requirements')+'.')
        if routes:
            r=row(item,' / '.join(dict.fromkeys(routes))[:220]);raw[item['id']]=r
    def static_score(item,precap=False):
        st=item.get('scalingOptions',{}).get('0',{}).get('stats',{})
        w={i:float(weights[i]) for i in range(min(len(weights),39))}
        if precap:w.update({0:2.4,1:2.23,3:2.06,5:2.36,9:2.36,17:6.83,18:3.08,21:5.1})
        score=sum(v*w.get(int(k),0) for k,v in st.items())
        ps=item.get('pseudoStats',[])
        def v(i):return ps[i] if i<len(ps) else 0
        score+=max(v(12),v(13),v(24))*10*w.get(17,0)
        score+=max(v(14),v(15),v(25))*14*w.get(18,0)
        score+=v(27)*10*w.get(21,0)
        if item.get('weaponSpeed',0):
            z=item['scalingOptions']['0']
            score+=(z.get('weaponDamageMin',0)+z.get('weaponDamageMax',0))/2/item['weaponSpeed']*14.2
        return score
    screened={}
    for slot in [0,1,2,3,4,5,6,7,8,9,10,12,14,16]:
        choices=[r for i,r in raw.items() if slot_for(db[i])==slot]
        selected={}
        for pre in [False,True]:
            for r in sorted(choices,key=lambda r:static_score(db[r['id']],pre),reverse=True)[:6]:selected[r['id']]=r
        for r in selected.values():insert(r)
        screened[slot]=len(choices)
    manual={
      11726:'Gorosh the Dervish — Ring of Law arena, Blackrock Depths.',
      11926:'Chest of The Seven — Blackrock Depths.',
      14637:'Scholomance mini-boss drops; check the current loot table.',
      12587:'Warchief Rend Blackhand — Upper Blackrock Spire.',
      13404:'The Unforgiven — Stratholme.',
      13340:'Baron Rivendare — Stratholme.',
      13098:'General Drakkisath — Upper Blackrock Spire.',
      15411:'In Dreams — Tirion Fordring quest chain, Eastern Plaguelands.',
      12583:'Warchief Rend Blackhand — Upper Blackrock Spire.',
      13348:'Balnazzar — Stratholme.',
      15062:"Commission a Tribal Leatherworker; outdoor Un'Goro recipe/material route.",
      15063:"Commission a Tribal Leatherworker; Nergal's Un'Goro pattern and outdoor materials."
    }
    for i,where in manual.items():insert(row(db[i],where))
    # Include every usable dungeon/vendor piece of the relevant sets for grouped trials.
    set_ids={1,123,121,188,1673,143}
    for i,r in raw.items():
        if db[i].get('setId') in set_ids:insert(r)
    for base,other in [(10,11),(12,13)]:pool[other]={i:dict(r,slot=SLOTS[other],wow_slot=WOW_SLOTS[other]) for i,r in pool[base].items()}
    work=BASE/'output/expanded-audit';work.mkdir(exist_ok=True)
    candidate_dump={SLOTS[s]:list(v.values()) for s,v in pool.items()}
    (work/'candidate-pool.json').write_text(json.dumps(candidate_dump,indent=2))
    (work/'screening.json').write_text(json.dumps({'catalog_items':len(db),'eligible_source_counts':screened,'discarded':discarded,
       'screen':'Union of the top six raw-stat candidates under each of capped and below-cap scales, plus prior/manual and relevant set pieces. Not every catalog item is simulated.',
       'source_limits':'Drop/vendor routes come from the pinned simulator database and current source lists; some loot data inherits legacy records.'},indent=2))
    print('Candidate counts:',{SLOTS[s]:len(v) for s,v in pool.items()},flush=True)
    gear=[x.get('id',0) for x in scenario['target_gear']['items']]
    gear[0]=13404
    def spec(ids):return {'items':[dict(id=i,**({'enchant':ENCHANTS[s]} if i and s in ENCHANTS else {})) for s,i in enumerate(ids)]}
    def valid(ids):
        if len({i for i in ids if i})!=len([i for i in ids if i]):return False
        used=set()
        for i in ids:
            for q in quest_groups(db[i]) if i else []:
                if q in used:return False
                used.add(q)
        return True
    results=[];cache={}
    def sim(ids,label,n=1000):
        key=(tuple(ids),n)
        if key in cache:return cache[key]
        c=dict(scenario,target_gear=spec(ids),name='Expanded strict pre-raid audit — 180s boss, no external buffs')
        p=work/'trial.json';p.write_text(json.dumps(c));out=work/'trial-result.json'
        proc=subprocess.run([str(BASE/'retlocal.exe'),'--root',str(BASE/'vendor/forever-master'),'--character',str(BASE/'output/character.json'),
            '--scenario',str(p),'--mode','planning','--iterations',str(n),'--no-weights','--out',str(out)],capture_output=True,text=True)
        if proc.returncode:raise RuntimeError(proc.stderr)
        r=json.loads(out.read_text(encoding='utf-8'));m=r['baseline']['raidMetrics']['dps'];v=m['avg'];cache[key]=v
        results.append(dict(label=label,iterations=n,dps=v,standard_error=m['stdev']/math.sqrt(n),gear=ids[:]))
        (work/'comparisons.json').write_text(json.dumps(results,indent=2))
        return v
    score=sim(gear,'Previous set with non-crafted head')
    chest_original=gear[:]
    for i in [226973,11726,14637,11926,252484]:
        t=chest_original[:];t[4]=i;sim(t,'Controlled chest comparison: '+db[i]['name'],5000)
    for pass_no in range(3):
        changed=False
        for slot,choices in pool.items():
            best=gear[slot];best_score=score
            for i in choices:
                if i==gear[slot]:continue
                trial=gear[:];trial[slot]=i
                if not valid(trial):continue
                value=sim(trial,f'Pass {pass_no+1}: {SLOTS[slot]} — {db[i]["name"]}')
                if value>best_score+1:best=i;best_score=value
            if best!=gear[slot]:gear[slot]=best;score=best_score;changed=True
        # Explicitly test whole sets, including the Devilsaur 2-piece.
        for set_id in set_ids:
            trial=gear[:];replaced=0
            for slot,choices in pool.items():
                if slot in [11,13]:continue
                choices=[i for i in choices if db[i].get('setId')==set_id]
                if choices:
                    trial[slot]=max(choices,key=lambda i:static_score(db[i]));replaced+=1
            if replaced<2 or not valid(trial):continue
            value=sim(trial,f'Pass {pass_no+1}: grouped set {set_id}')
            if value>score+1:gear=trial;score=value;changed=True
        print(f'Pass {pass_no+1}: {score:.2f} DPS; {len(results)} distinct sims',flush=True)
        if not changed:break
    final=sim(gear,'Expanded final confirmation',5000)
    # Repeat the chest swap in the final set to separate chest effects from other swaps.
    for i in [226973,11726,14637,11926,252484]:
        t=gear[:];t[4]=i;sim(t,'Final-set chest comparison: '+db[i]['name'],5000)
    # Recreate final result after the diagnostic swaps.
    final_scenario=dict(scenario,target_gear=spec(gear),name='Audited Horde pre-raid target — 180s boss, no external buffs')
    (BASE/'scenario.json').write_text(json.dumps(final_scenario,indent=2))
    target=[]
    for slot,i in enumerate(gear):
        if not i:continue
        r=copy.deepcopy(pool[slot][i]);r['enchant']=ENCHANTS.get(slot,0)
        r['alternatives']=[copy.deepcopy(a) for x,a in pool[slot].items() if x!=i][:8]
        target.append(r)
    old.update(items=target,baseline_dps=final,method='Expanded dungeon/vendor catalog screening plus named quest/craft candidates; whole-set coordinate search and grouped set trials. Not exhaustive global BiS.',
       audit_summary={'simulated_sets':len(results),'candidate_counts':{SLOTS[s]:len(v) for s,v in pool.items()},'craft_audit':'craft-audit.json','comparison_file':'output/expanded-audit/comparisons.json'},
       exclusions=[x for x in old['exclusions'] if x.get('id')!=12640]+[{'id':12640,'name':'Lionheart Helm','reason':'Materials are non-raid; the live recipe drop source is not verified. Optional if a crafter is available, excluded from the required strict plan.'}])
    # The production run supplies computed hit/expertise, including set bonuses.
    old['caps']={'gear_hit_percent':None,'precision_hit_percent':1.0,'total_melee_hit_percent':None,'expertise_percent':None}
    (BASE/'prebis-targets.json').write_text(json.dumps(old,indent=2))
    print('Final:',[(r['slot'],r['name']) for r in target],flush=True)
    print('Final confirmation:',final,flush=True)
if __name__=='__main__':main()
