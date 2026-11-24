from guild_runtime import runtime_root, usable_faction
"""Compare the full compatible catalog, then refine complete equipment sets."""
import copy
import hashlib
import itertools
import json
import math
from pathlib import Path
import subprocess
from build_prebis import BASE, SLOTS, WOW_SLOTS, ENCHANTS, database

WORK=BASE/'output/all-sources'
RAIDS={1977,2159,2677,2717,3428,3429,3456,16076,16004}
WORLD_BOSSES={6109,12397,14887,14888,14889,14890}
RAID_REPS={270,749,910}
ALLIANCE_PREFIXES=('Knight-', 'Lieutenant Commander', 'Commander\'s', 'Marshal\'s', 'Field Marshal', 'Grand Marshal', 'Premier Knight-', 'Premier Lieutenant Commander', 'Premier Commander', 'Premier Marshal', 'Premier Field Marshal', 'Premier Grand Marshal', 'Highlander\'s', 'Silverwing ')

def write(path,value):
    path.write_text(json.dumps(value,indent=2),encoding='utf-8')

def slot(item):
    t=item.get('type',0)
    if 1<=t<=10:return t-1
    if t==11:return 10
    if t==12:return 12
    if t==13 and item.get('handType')==4 and item.get('weaponType') in (1,4,6,9):return 14
    if t==14 and item.get('rangedWeaponType')==7:return 16

def main():
    WORK.mkdir(parents=True,exist_ok=True)
    full=database()
    catalog=json.loads((BASE/'vendor/forever-master/assets/database/db.json').read_text(encoding='utf-8'))
    db={x['id']:x for x in catalog['items']}
    factions={x['id']:x['name'] for x in catalog['factions']}
    zones={x['id']:x['name'] for x in catalog['zones']}
    npcs={x['id']:x for x in catalog['npcs']}
    suffixes={x['id']:x for x in catalog['randomSuffixes']}
    scenario=json.loads((BASE/'scenario.json').read_text(encoding='utf-8'))
    previous=json.loads((BASE/'prebis-targets.json').read_text(encoding='utf-8'))
    # Prior raid-dependency checks and explicit user availability evidence.
    overrides=json.loads((BASE/'source-overrides.json').read_text(encoding='utf-8'))
    exclusion_map={int(k):v for k,v in overrides['excluded_raid_dependencies'].items()}
    allowed_map={int(k):v for k,v in overrides['verified_routes'].items()}
    coverage=[];pool={};rows={};conditional=[]
    for i,item in full.items():
        reason=None;s=slot(item)
        if s is None:reason='Not a compatible equipment slot or two-handed weapon type'
        elif item.get('reqLvl',0)>60:reason='Requires level above 60'
        elif item.get('classAllowlist') and 2 not in item['classAllowlist']:reason='Class restriction excludes Paladin'
        elif not usable_faction(item.get('factionRestriction',0)):reason='Faction restriction'
        elif not item.get('scalingOptions',{}).get('0'):reason='No stat record in this catalog'
        elif i not in db:reason='Outside the simulator supported-item database; retained as a coverage gap'
        elif i in exclusion_map:reason=exclusion_map[i]['reason']
        sources=item.get('sources',[])
        side_sources=[x for x in sources if 'quest'in x or 'soldBy'in x or 'rep'in x]
        def side(source):
            if 'rep'in source:return source['rep'].get('factionId',0)
            return next(iter(source.values())).get('faction',0)
        if reason is None and side_sources and all(side(x)==1 for x in side_sources) and not any('crafted'in x or 'drop'in x for x in sources):
            reason='Only Alliance acquisition routes recorded'
        drops=[x['drop'] for x in sources if 'drop'in x]
        raid_drops=[x for x in drops if (x.get('zoneId') or npcs.get(x.get('npcId'),{}).get('zoneId')) in RAIDS or x.get('npcId') in WORLD_BOSSES]
        nonraid_other=any('crafted'in x or 'quest'in x or 'pvp'in x or 'soldBy'in x for x in sources)
        if reason is None and raid_drops and len(raid_drops)==len(drops) and not nonraid_other:reason='Raid/world-boss drop only'
        reps=[x['rep'] for x in sources if 'rep'in x]
        if reason is None and reps and all(x.get('repFactionId') in RAID_REPS for x in reps):reason='Raid-dependent reputation reward'
        if reason:
            coverage.append(dict(id=i,name=item['name'],status='excluded',reason=reason));continue
        routes=[];categories=set();notes=[];verified=i in allowed_map
        for source in sources:
            if 'crafted'in source:
                categories.add('crafted');c=source['crafted']
                routes.append('Craft spell '+str(c['spellId'])+'; commission a crafter where tradable')
                if not verified:notes.append('Recipe and reagent route must be checked before farming')
            if 'drop'in source:
                d=source['drop'];npc=npcs.get(d.get('npcId'),{});zone=d.get('zoneId') or npc.get('zoneId')
                if zone in RAIDS or d.get('npcId') in WORLD_BOSSES:continue
                categories.add('drop');routes.append(npc.get('name',d.get('otherName','World/unknown drop'))+' — '+zones.get(zone,'source details need checking'))
            if 'quest'in source and source['quest'].get('faction')!=1:
                categories.add('quest');routes.append(source['quest']['name']+' (quest '+str(source['quest']['id'])+')')
            if 'soldBy'in source and source['soldBy'].get('faction')!=1:
                categories.add('vendor');v=source['soldBy'];routes.append(v.get('npcName','Vendor')+' — '+zones.get(v.get('zoneId'),'check location'))
            if 'rep'in source and source['rep'].get('factionId')!=1:
                categories.add('reputation');r=source['rep'];standing={4:'Neutral',5:'Friendly',6:'Honored',7:'Revered',8:'Exalted'}.get(r.get('repLevel'),'check standing')
                routes.append(factions.get(r['repFactionId'],str(r['repFactionId']))+' — '+standing)
            if 'pvp'in source:categories.add('PvP');routes.append('PvP vendor; check current honor/rank requirements')
        if i in allowed_map:
            routes=[allowed_map[i]['where']];notes.append(allowed_map[i].get('note',''));categories.update(allowed_map[i].get('categories',[]))
        if not routes:routes=['Acquisition source missing from catalog; verification required'];notes.append('Source missing')
        required=item.get('requiredProfession',0)
        if required and required not in (3,9):notes.append('Requires a profession change to use');conditional.append(i)
        unknown_phase=item.get('phase',1)!=1 and not verified
        if unknown_phase:notes.append('Legacy/unknown-availability record; verify a current Forever source')
        base=dict(id=i,name=item['name'],slot=SLOTS[s],wow_slot=WOW_SLOTS[s],where='; '.join(dict.fromkeys(routes)),source='https://www.wowhead.com/forever/item='+str(i),
                  priority=2,note='; '.join(dict.fromkeys(n for n in notes if n)),required_level=item.get('reqLvl',0),categories=sorted(categories),
                  verified_route=verified,required_profession=required,phase_metadata=item.get('phase',1),set_id=item.get('setId',0),proc_rate=item.get('procRate'),
                  target_eligible=not unknown_phase and (not required or required in (3,9)))
        qs=[x['quest']['id'] for x in sources if 'quest'in x and x['quest'].get('faction')!=1]
        base['quest_groups']=qs if qs and not any(k in categories for k in ('drop','crafted','vendor','PvP')) else []
        variants=item.get('randomSuffixOptions') or [0]
        coverage.append(dict(id=i,name=item['name'],status='included',variants=len(variants),categories=base['categories'],note=base['note']))
        for suffix in variants:
            row=copy.deepcopy(base);row['random_suffix']=suffix
            if suffix:row['name']+=' '+suffixes[suffix]['name']
            key=f'{i}:{suffix}';row['key']=key;rows[key]=row;pool.setdefault(s,[]).append(key)
    # Slot pairs use the same full pool and retain unique and reward-choice checks.
    pool[11]=pool[10][:];pool[13]=pool[12][:]
    write(WORK/'coverage.json',dict(catalog_items=len(full),supported_items=len(db),items=coverage,
        policy='No grind/cost/rank ceiling; all supported compatible item and random-suffix variants are initially simulated. Raid-only drops and recorded raid dependencies remain excluded.',
        limits='Missing acquisition/craft routes are recorded, not silently discarded. A catalog is not proof of every live item or of a globally optimal combination.'))
    write(WORK/'candidate-pool.json',{SLOTS[s]:[rows[k] for k in keys] for s,keys in pool.items()})
    gear=[f'{x.get("id",0)}:{x.get("randomSuffix",0)}' if x.get('id') else '' for x in scenario['target_gear']['items']]
    assert all(k in rows for k in gear if k),'Current set no longer eligible; inspect explicit source overrides'
    def equipment(keys):
        return {'items':[dict(id=rows[k]['id'],randomSuffix=rows[k]['random_suffix'],**({'enchant':ENCHANTS[s]} if s in ENCHANTS else {})) if k else {} for s,k in enumerate(keys)]}
    blocked=set(exclusion_map);strict_target=False
    def valid(keys):
        used=set();quests=set();limits=set()
        for k in keys:
            if not k:continue
            row=rows[k];item=db[row['id']]
            if row['id'] in blocked:return False
            if strict_target and not row['target_eligible']:return False
            if row['id'] in used and item.get('unique',False):return False
            used.add(row['id'])
            limit=item.get('limitCategory',0)
            if limit and limit in limits:return False
            if limit:limits.add(limit)
            for q in row['quest_groups']:
                if q in quests:return False
                quests.add(q)
        return True
    history=[];cache={}
    context=hashlib.sha256((BASE/'retlocal.exe').read_bytes()+(BASE/'scenario.json').read_bytes()+(BASE/'output/character.json').read_bytes()).hexdigest()
    context_file=WORK/'cache-context.txt'
    seen_history=set()
    if context_file.exists() and context_file.read_text(encoding='utf-8')==context:
        for prior in (WORK/'initial-cache.json',WORK/'comparisons.json'):
            if not prior.exists():continue
            for r in json.loads(prior.read_text(encoding='utf-8')):
                if 'error'in r or r['iterations']<20:continue
                identity=(tuple(r['gear']),r['iterations'])
                cache[identity]=r
                if r['stage']=='all-items':cache[(tuple(r['gear']),20)]=r
                if identity not in seen_history:history.append(r);seen_history.add(identity)
    def batch(candidates,n,stage):
        jobs=[];lookup={};answers={}
        for label,keys in candidates:
            ident=(tuple(keys),n)
            if ident in cache:answers[label]=cache[ident];continue
            token=hashlib.sha256(json.dumps(ident).encode()).hexdigest()[:24]
            if token in lookup:lookup[token]['labels'].append(label);continue
            lookup[token]=dict(labels=[label],gear=keys[:]);jobs.append(dict(label=token,equipment=equipment(keys)))
        job_path=WORK/(stage+'.jobs.json');output=WORK/(stage+'.jsonl')
        write(job_path,jobs)
        if jobs:
            print(stage+': '+str(len(jobs))+' sets x '+str(n)+' iterations',flush=True)
            with (WORK/(stage+'.log')).open('w') as log:
                proc=subprocess.run([str(BASE/'retlocal.exe'),'--root',str(BASE/'vendor/forever-master'),'--character',str(BASE/'output/character.json'),
                    '--scenario',str(BASE/'scenario.json'),'--mode','planning','--iterations',str(n),'--batch',str(job_path),'--out',str(output)],stdout=log,stderr=log)
            if proc.returncode:raise RuntimeError('Batch failed; see '+stage+'.log')
            for line in output.read_text(encoding='utf-8').splitlines():
                result=json.loads(line);details=lookup[result['label']];keys=details['gear']
                result.update(gear=keys,stage=stage,labels=details['labels'])
                history.append(result)
                if 'dps' not in result:continue
                cache[(tuple(keys),n)]=result
                for label in details['labels']:answers[label]=result
        write(WORK/'comparisons.json',history)
        return answers
    initial=[('baseline',gear[:])]
    for s,keys in pool.items():
        for k in keys:
            trial=gear[:];trial[s]=k
            if valid(trial):initial.append((f'{s}|{k}',trial))
    initial_results=batch(initial,20,'all-items')
    blocked.update(int(i) for i in json.loads((BASE/'source-overrides.json').read_text(encoding='utf-8'))['excluded_raid_dependencies'])
    strict_target=True
    failed=sum('error'in x for x in history)
    if failed:print('Unsupported/failed variants:',failed,flush=True)
    # Every item enters the initial stage. Higher precision focuses on survivors and sets.
    survivors={}
    for s,keys in pool.items():
        ranked=sorted((k for k in keys if f'{s}|{k}' in initial_results and rows[k]['id'] not in blocked and rows[k]['target_eligible']),key=lambda k:initial_results[f'{s}|{k}']['dps'],reverse=True)
        keep=set(ranked[:40])
        keep.update(k for k in keys if rows[k]['set_id'])
        keep.update(k for k in keys if rows[k]['id'] in (12640,19044,19050,250617,19325,11726,12784,22385))
        survivors[s]=[k for k in keys if k in keep and rows[k]['id'] not in blocked and rows[k]['target_eligible']]
    score=batch([('baseline',gear)],1500,'reference')['baseline']['dps']
    all_sets=sorted({r['set_id'] for r in rows.values() if r['set_id']})
    for pass_no in range(4):
        blocked.update(int(i) for i in json.loads((BASE/'source-overrides.json').read_text(encoding='utf-8'))['excluded_raid_dependencies'])
        changed=False
        for s,keys in survivors.items():
            trials=[]
            for k in keys:
                t=gear[:];t[s]=k
                if valid(t):trials.append((k,t))
            results=batch(trials,1500,f'pass{pass_no+1}-slot{s}')
            if not results:continue
            k,best=max(results.items(),key=lambda x:x[1]['dps'])
            if best['dps']>score+1:
                gear=best['gear'][:];score=best['dps'];changed=True
        for first,second in ((10,11),(12,13)):
            trials=[]
            for a,b in itertools.combinations_with_replacement(survivors[first],2):
                t=gear[:];t[first]=a;t[second]=b
                if valid(t):trials.append((a+'|'+b,t))
            pair_screen=batch(trials,100,f'pass{pass_no+1}-pair{first}-screen')
            leaders=sorted(pair_screen.items(),key=lambda x:x[1]['dps'],reverse=True)[:30]
            pairs=batch([(label,r['gear']) for label,r in leaders],1500,f'pass{pass_no+1}-pair{first}-refine')
            if pairs:
                _,best=max(pairs.items(),key=lambda x:x[1]['dps'])
                if best['dps']>score+1:gear=best['gear'][:];score=best['dps'];changed=True
        trials=[]
        for set_id in all_sets:
            choices={s:[k for k in keys if rows[k]['set_id']==set_id] for s,keys in survivors.items()}
            choices={s:ks for s,ks in choices.items() if ks}
            if len(choices)<2:continue
            t=gear[:]
            chosen=set()
            for s,ks in choices.items():
                available=[k for k in ks if rows[k]['id'] not in chosen]
                if not available:continue
                k=max(available,key=lambda k:initial_results.get(f'{s}|{k}',{}).get('dps',0));t[s]=k;chosen.add(rows[k]['id'])
            if valid(t):trials.append(('set'+str(set_id),t))
            # Test partial set thresholds against the current equipment, including 2/3/4/6 pieces.
            ordered=list(choices)
            for count in (2,3,4,6):
                if count>=len(ordered):continue
                for subset in itertools.combinations(ordered,count):
                    partial=gear[:]
                    for s in subset:partial[s]=t[s]
                    if valid(partial):trials.append(('set'+str(set_id)+'-'+','.join(map(str,subset)),partial))
        set_results=batch(trials,400,f'pass{pass_no+1}-sets-screen')
        finalists=sorted(set_results.items(),key=lambda x:x[1]['dps'],reverse=True)[:30]
        refined=batch([(label,r['gear']) for label,r in finalists],1500,f'pass{pass_no+1}-sets-refine')
        if refined:
            _,best=max(refined.items(),key=lambda x:x[1]['dps'])
            if best['dps']>score+1:gear=best['gear'][:];score=best['dps'];changed=True
        print('Pass',pass_no+1,'best',round(score,2),[(SLOTS[s],rows[k]['name']) for s,k in enumerate(gear) if k],flush=True)
        if not changed:break
    final=batch([('final',gear)],10000,'final-confirmation')['final']
    # Compare the named alternatives in the final context at higher precision.
    named=[]
    for s,ids in [(0,[12640]),(4,[11726,226973]),(7,[19044]),(10,[19325]),(14,[250617,12784,279260])]:
        for i in ids:
            k=f'{i}:0'
            if k not in rows:continue
            t=gear[:];t[s]=k
            if valid(t):named.append((rows[k]['name'],t))
    named_results=batch(named,5000,'named-final-comparisons')
    selected=[]
    for s,k in enumerate(gear):
        if not k:continue
        r=copy.deepcopy(rows[k]);r.update(slot=SLOTS[s],wow_slot=WOW_SLOTS[s],enchant=ENCHANTS.get(s,0))
        ranked=sorted((other for other in survivors[s] if other!=k),key=lambda other:initial_results.get(f'{s}|{other}',{}).get('dps',0),reverse=True)
        r['alternatives']=[copy.deepcopy(rows[other]) for other in ranked[:10]]
        selected.append(r)
    plan=copy.deepcopy(previous)
    plan.update(checked='2026-11-19',items=selected,baseline_dps=final['dps'],
        method='Every compatible supported item/random-suffix variant enters a 20-or-more-iteration screen; survivors, full sets and partial set thresholds are refined at 400/1,500 iterations, with 10,000-iteration final confirmation. No grind, reputation or PvP-rank ceiling. Not exhaustive combinations.',
        exclusions=[dict(id=int(i),name=full[int(i)]['name'] if int(i)in full else str(i),reason=r['reason']) for i,r in overrides['excluded_raid_dependencies'].items()],
        caps=dict(gear_hit_percent=None,precision_hit_percent=1.0,total_melee_hit_percent=None,expertise_percent=None),
        audit_summary=dict(simulated_sets=len(history),catalog_items=len(full),included_base_items=sum(x['status']=='included' for x in coverage),
            included_variants=len(rows),initial_simulated_sets=sum(x['stage']=='all-items' for x in history),failed_variants=failed,
            candidate_counts={SLOTS[s]:len(keys) for s,keys in pool.items()},coverage_file='output/all-sources/coverage.json',
            craft_audit='source-overrides.json',comparison_file='output/all-sources/comparisons.json',
            limits='All means the compatible supported catalog, not a guarantee of every live item. Recipe/source gaps and profession changes are flagged. Raid dependence is checked for selected targets.'),
        named_comparisons=[dict(name=name,dps=r['dps'],iterations=r['iterations']) for name,r in named_results.items()],
        source_policy='Include all reputation standings and PvP ranks. Retain prior no-raid-item/no-raid-material requirement. Lionheart availability confirmed by user.')
    plan.pop('chest_audit',None);plan.pop('active_sets',None)
    write(WORK/'proposed-plan.json',plan)
    write(WORK/'proposed-scenario.json',dict(scenario,target_gear=equipment(gear),name='All-source Horde pre-raid target — 180s boss, no external buffs'))
    print('Proposed targets written; source verification required before publishing.',flush=True)

if __name__=='__main__':main()
