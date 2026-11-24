from guild_runtime import runtime_root, usable_faction
"""Refine the all-source planning pool with a simulator-enforced hit minimum."""
import copy
import itertools
import json
import math
from pathlib import Path
import subprocess
from build_prebis import BASE,SLOTS,WOW_SLOTS,ENCHANTS,database

WORK=BASE/'output/hit-cap'

def write(path,data):path.write_text(json.dumps(data,indent=2),encoding='utf-8')

def main():
    db=database();old=json.loads((BASE/'prebis-targets.json').read_text(encoding='utf-8'));scenario=json.loads((WORK/'raid.json').read_text(encoding='utf-8'))
    scenario['consumables']={'resourcePotId':13444,'conjuredId':12662}
    write(WORK/'raid.json',scenario)
    source_pool=json.loads((BASE/'output/all-sources/candidate-pool.json').read_text(encoding='utf-8'))
    blocked={int(i) for i in json.loads((BASE/'source-overrides.json').read_text(encoding='utf-8'))['excluded_raid_dependencies']}
    rows={r['key']:r for choices in source_pool.values() for r in choices}
    pool={SLOTS.index(s):[r['key'] for r in choices if r['target_eligible'] and r['id'] not in blocked] for s,choices in source_pool.items()}
    ep=json.loads((WORK/'raid-seed.json').read_text(encoding='utf-8'))['weights']['dps']['epValues']['stats']
    pseudo_ep=json.loads((WORK/'raid-seed.json').read_text(encoding='utf-8'))['weights']['dps']['epValues']['pseudoStats']
    catalog=json.loads((BASE/'vendor/forever-master/assets/database/db.json').read_text(encoding='utf-8'));suffix={x['id']:x for x in catalog['randomSuffixes']}
    def score(k):
        r=rows[k];item=db[r['id']];scale=item['scalingOptions']['0'];stats=scale.get('stats',{})
        result=sum(v*ep[int(i)] for i,v in stats.items() if int(i)<len(ep))
        if r['random_suffix']:
            result+=sum(v*ep[i]*scale.get('randPropPoints',0)/10000 for i,v in enumerate(suffix[r['random_suffix']]['stats']) if i<len(ep))
        ps=item.get('pseudoStats',[])
        for indexes,multiplier,stat in [([12,13,24],10,17),([14,15,25],14,18),([27],10,21)]:
            result+=max([ps[i] if i<len(ps) else 0 for i in indexes])*multiplier*ep[stat]
        if item.get('weaponSpeed',0):result+=(scale.get('weaponDamageMin',0)+scale.get('weaponDamageMax',0))/2/item['weaponSpeed']*pseudo_ep[0]
        return result
    # The earlier complete catalog screen contributes proc-sensitive candidates.
    initial_baseline=json.loads((BASE/'backups/all-sources-2026-11-19/scenario.json').read_text(encoding='utf-8'))['target_gear']['items']
    base=[str(x.get('id',0))+':'+str(x.get('randomSuffix',0)) if x.get('id') else '' for x in initial_baseline]
    old_scores={}
    for r in json.loads((BASE/'output/all-sources/comparisons.json').read_text(encoding='utf-8')):
        if r['stage']!='all-items' or 'dps'not in r:continue
        changed=[s for s,(a,b) in enumerate(zip(base,r['gear'])) if a!=b]
        if len(changed)==1:old_scores[(changed[0],r['gear'][changed[0]])]=r['dps']
    current=[str(x.get('id',0))+':'+str(x.get('randomSuffix',0)) if x.get('id') else '' for x in scenario['target_gear']['items']]
    candidates={}
    for s,keys in pool.items():
        selected=set(sorted(keys,key=score,reverse=True)[:22])
        selected.update(sorted(keys,key=lambda k:old_scores.get((s,k),-1),reverse=True)[:14])
        selected.update(k for k in keys if rows[k]['set_id'])
        if s in (12,13):selected.update(keys)
        if s==14:selected.update(k for k in keys if db[rows[k]['id']].get('itemEffects'))
        hit_keys=[k for k in keys if db[rows[k]['id']]['scalingOptions']['0'].get('stats',{}).get('17',0)>=10]
        selected.update(sorted(hit_keys,key=score,reverse=True)[:15])
        selected.update(k for k in keys if rows[k]['id'] in (12640,19044,19050,19325,11726,252486,22676))
        if current[s] in rows:selected.add(current[s])
        candidates[s]=sorted(selected,key=score,reverse=True)
    write(WORK/'candidate-pool.json',{SLOTS[s]:[rows[k] for k in keys] for s,keys in candidates.items()})
    def equipment(keys):return {'items':[dict(id=rows[k]['id'],randomSuffix=rows[k]['random_suffix'],**({'enchant':ENCHANTS[s]} if s in ENCHANTS else {})) if k else {} for s,k in enumerate(keys)]}
    def valid(keys):
        used=set();quests=set();limits=set()
        for k in keys:
            if not k:continue
            r=rows[k];item=db[r['id']]
            if r['id'] in used and item.get('unique'):return False
            used.add(r['id'])
            limit=item.get('limitCategory',0)
            if limit and limit in limits:return False
            if limit:limits.add(limit)
            for q in r.get('quest_groups',[]):
                if q in quests:return False
                quests.add(q)
        return True
    history=[];cache={}
    def batch(trials,n,name):
        jobs=[];lookup={};result={}
        for label,keys in trials:
            identity=(tuple(keys),n)
            if identity in cache:
                if 'dps'in cache[identity]:result[label]=cache[identity]
                continue
            token=str(len(jobs));lookup[token]=(label,keys[:]);jobs.append(dict(label=token,equipment=equipment(keys)))
        job_file=WORK/(name+'.jobs.json');output=WORK/(name+'.jsonl');write(job_file,jobs)
        if jobs:
            print(name+': '+str(len(jobs))+' sets x '+str(n),flush=True)
            with (WORK/(name+'.log')).open('w') as log:
                run=subprocess.run([str(BASE/'retlocal.exe'),'--root',str(BASE/'vendor/forever-master'),'--character',str(BASE/'output/character.json'),
                    '--scenario',str(WORK/'raid.json'),'--mode','planning','--iterations',str(n),'--batch',str(job_file),'--out',str(output)],stdout=log,stderr=log)
            if run.returncode:raise RuntimeError('Batch failed: '+str(output))
            for line in output.read_text(encoding='utf-8').splitlines():
                r=json.loads(line);label,keys=lookup[r['label']];r.update(label=label,gear=keys,stage=name);history.append(r);cache[(tuple(keys),n)]=r
                if 'dps'in r:
                    assert r['meleeHitPercent']>=8-1e-6
                    result[label]=r
                elif 'error'in r:raise RuntimeError(r['error'])
        write(WORK/'comparisons.json',history)
        return result
    best=batch([('seed',current)],2500,'seed')['seed']['dps']
    order=[0,2,1,9,5,14,6,7,4,8,3,10,11,12,13,16]
    def refine(trials,n,name,top=6):
        screen=batch(trials,n,name+'-screen')
        leaders=sorted(screen.items(),key=lambda x:x[1]['dps'],reverse=True)[:top]
        return batch([(label,r['gear']) for label,r in leaders],2500,name+'-refine')
    for pass_no in range(3):
        changed=False
        for s in order:
            trials=[]
            for k in candidates[s]:
                t=current[:];t[s]=k
                if valid(t):trials.append((k,t))
            results=refine(trials,400,f'pass{pass_no+1}-slot{s}')
            if results:
                _,r=max(results.items(),key=lambda x:x[1]['dps'])
                if r['dps']>best+0.6:current=r['gear'][:];best=r['dps'];changed=True
        for a,b in [(10,11),(12,13)]:
            trials=[]
            for ka,kb in itertools.combinations_with_replacement(candidates[a],2):
                t=current[:];t[a]=ka;t[b]=kb
                if valid(t):trials.append((ka+'|'+kb,t))
            results=refine(trials,100,f'pass{pass_no+1}-pair{a}',top=15)
            if results:
                _,r=max(results.items(),key=lambda x:x[1]['dps'])
                if r['dps']>best+0.6:current=r['gear'][:];best=r['dps'];changed=True
        # Joint armor moves can restore a set bonus while moving hit to another slot.
        choices={s:list(dict.fromkeys([current[s]]+candidates[s][:5]+[k for k in candidates[s] if rows[k]['set_id']==1673]+[k for k in candidates[s] if rows[k]['id']==12640])) for s in range(10)}
        trials=[]
        for a,b in itertools.combinations(range(10),2):
            for ka,kb in itertools.product(choices[a],choices[b]):
                t=current[:];t[a]=ka;t[b]=kb
                if valid(t):trials.append((str(a)+ka+'|'+str(b)+kb,t))
        results=refine(trials,100,f'pass{pass_no+1}-armor-pairs',top=20)
        if results:
            _,r=max(results.items(),key=lambda x:x[1]['dps'])
            if r['dps']>best+0.6:current=r['gear'][:];best=r['dps'];changed=True
        print('Pass',pass_no+1,round(best,2),[(SLOTS[s],rows[k]['name']) for s,k in enumerate(current) if k],flush=True)
        if not changed:break
    final=batch([('final',current)],12500,'final')['final']
    plan=copy.deepcopy(old);selected=[]
    for s,k in enumerate(current):
        if not k:continue
        r=copy.deepcopy(rows[k]);r.update(slot=SLOTS[s],wow_slot=WOW_SLOTS[s],enchant=ENCHANTS.get(s,0))
        r['alternatives']=[copy.deepcopy(rows[x]) for x in candidates[s] if x!=k][:10];selected.append(r)
    plan.update(items=selected,baseline_dps=final['dps'],constraints={'minimum_melee_hit_percent':8},
        assumptions='180 seconds, level-63 boss from behind; listed raid buffs, debuffs, Major Mana Potion and Demonic Rune available; no world buffs, Innervate, Mana Tide or offensive consumables.',
        method='All-source catalog retained. Hit-constrained refinement uses raid EP and earlier full-catalog comparisons, direct slot/pair comparisons, set-restoring armor pairs and a 12,500-iteration final confirmation. Every simulated candidate is checked by ComputeStats for at least 8% total melee hit.',
        caps={'gear_hit_percent':None,'precision_hit_percent':1.0,'total_melee_hit_percent':None,'expertise_percent':None},
        mana_metrics={'seconds_oom':final['secondsOom']},named_comparisons=[])
    plan['audit_summary']['hit_cap_refinement']='output/hit-cap/comparisons.json';plan['audit_summary']['hit_cap_comparisons']=len(history)
    plan.pop('active_sets',None)
    scenario['target_gear']=equipment(current)
    write(WORK/'proposed-plan.json',plan);write(WORK/'proposed-scenario.json',scenario)
    print('Final capped target:',final['dps'],'hit',final['meleeHitPercent'],'OOM',final['secondsOom'],flush=True)

if __name__=='__main__':main()
