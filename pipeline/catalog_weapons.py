from guild_runtime import runtime_root, usable_faction
"""Resumable combat simulations for the compatible weapon catalog."""
import copy
import hashlib
import json
import math
from pathlib import Path
import time

import run
import sim_progress
import weapon_sims as w
import bulk_bridge
import refresh_scope

BASE=runtime_root()
CHUNK=64
class SupersededCapture(ValueError):pass


def payload_bundle(payload):
    import effect_coverage
    from build_prebis import database
    payload=dict(payload,**effect_coverage.catalog_metadata(database()))
    payload=copy.deepcopy(payload)
    for context in payload.get('contexts',[]):
        baseline_proc=any(row.get('baseline') and row.get('provisionalProc') for row in context.get('weapons',[]))
        for row in context.get('weapons',[]):
            row['provisional']=bool(baseline_proc or row.get('provisionalProc') or effect_coverage.row_coverage(row,{'id':context['baselineId']},payload['missingItemEffects']))
    text='local _, ns = ...\nns.weaponResults = '+w.lua_value(payload)+'\n'
    old=refresh_scope.snapshot('weapons') if payload.get('scope')=='quick' else None
    if old:text+='ns.weaponSnapshot = '+w.lua_value(old)+'\n'
    return text


def context_fingerprint(character,scenario,engine_hash,catalog_hash):
    model=copy.deepcopy(scenario)
    base=model['target_gear']['items'][14]
    model['target_gear']['items'][14]={'enchant':base.get('enchant',0)}
    identity=[run.model_identity(character,'planning'),model,engine_hash,w.REFINE_ITERATIONS,2]
    return hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()


def refine_keys(screen, baseline_key):
    baseline=screen[baseline_key]['dps']
    ordered=sorted((k for k,r in screen.items() if r.get('dps',0)>0),key=lambda k:screen[k]['dps'],reverse=True)
    def close(k):
        row=screen[k];base=screen[baseline_key]
        error=math.sqrt(row.get('stdev',0)**2/max(1,row.get('iterations',w.SCREEN_ITERATIONS))
                        +base.get('stdev',0)**2/max(1,base.get('iterations',w.SCREEN_ITERATIONS)))
        return row['dps']>=baseline-max(baseline*.01,4*error)
    return {baseline_key} | set(ordered[:25]) | {k for k in ordered if close(k)}


def run_missing(work, key, jobs, cache, path, iterations, config):
    missing=[j for j in jobs if j['label'] not in cache or cache[j['label']].get('iterations',0)<iterations]
    total=len(jobs);done=total-len(missing)
    for index in range(0,len(missing),CHUNK):
        if config.get('_captureIdentity'):
            _,latest=run.latest(config)
            if run.model_identity(latest,'current')!=config['_captureIdentity']:
                raise SupersededCapture('Newer character capture received; switching to the latest gear and keeping completed cache chunks.')
        chunk=missing[index:index+CHUNK]
        jobfile=work/f'{key}-pending-jobs.json';results=work/f'{key}-pending.jsonl'
        run.atomic(jobfile,json.dumps(chunk))
        command=[str(BASE/'retlocal.exe'),'--root',str(BASE/'vendor/forever-master'),
                 '--character',str(work/'character.json'),'--scenario',str(work/f'{key}-scenario.json'),
                 '--mode','planning','--iterations',str(iterations),'--workers',str(config.get('weapon_workers',4)),
                 '--batch',str(jobfile),'--out',str(results)]
        proc=sim_progress.engine(command,cwd=BASE,log_path=work/f'{key}-engine.log',
            stage=f'Weapon catalog — {key} — {iterations:,} iterations',results_path=results,
            total=len(chunk),offset=done,overall_total=total,adaptive=config.get('smart_concurrency',False))
        if proc.returncode:raise ValueError('Weapon catalog batch failed; completed chunks are cached and installed results preserved.')
        rows=[json.loads(line) for line in results.read_text(encoding='utf-8').splitlines() if line.strip()]
        if {r['label'] for r in rows}!={j['label'] for j in chunk}:raise ValueError('Incomplete weapon catalog batch; installed results preserved.')
        cache.update({r['label']:r for r in rows});run.atomic(path,json.dumps(cache))
        done+=len(chunk)
        print(f'Catalog {key}: {done}/{total} at {iterations:,} iterations.',flush=True)


def refresh(config,force=False,publish=True):
    config=refresh_scope.catalog_config(config)
    record,character=run.latest(config)
    scenario=json.loads((BASE/'scenario.json').read_text(encoding='utf-8'))
    selected=refresh_scope.candidates(config,character)
    db=w.database()
    requested=[spec for spec in selected if spec and db.get(spec.get('id'),{}).get('handType')==4]
    choices,selection_errors=w.candidates(db,w.full_gear(character['gear']),requested)
    full_catalog_hash=hashlib.sha256(json.dumps(choices,sort_keys=True).encode()).hexdigest()
    quick=refresh_scope.is_quick(config)
    state=BASE/'output/weapons.json'
    if quick:
        if state.exists():refresh_scope.archive('weapons',json.loads(state.read_text(encoding='utf-8')))
        selected_keys={f'{item_id}:0' for item_id in w.SEEDS} | {f"{s.get('id')}:{s.get('randomSuffix',0)}" for s in selected if s}
        choices={key:spec for key,spec in choices.items() if key in selected_keys}
        selection_errors=[]
    catalog_hash=hashlib.sha256(json.dumps(choices,sort_keys=True).encode()).hexdigest()
    engine_hash=hashlib.sha256((BASE/'retlocal.exe').read_bytes()).hexdigest()
    backend=bulk_bridge.backend_identity(config)
    identity=[run.model_identity(character,'current'),scenario,catalog_hash,engine_hash,w.SCREEN_ITERATIONS,w.REFINE_ITERATIONS,2,config.get('mount_trinket_ids',[]),backend,quick,3]
    fingerprint=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    state=BASE/'output/weapons.json'
    if state.exists() and not force:
        old=json.loads(state.read_text(encoding='utf-8'))
        if old.get('runId')==fingerprint and (not publish or old.get('published',True)):
            old.update(refresh_scope.reference_metadata(config))
            run.atomic(state,json.dumps(old))
            if old.get('sourceExport')!=record['data']:
                old['sourceExport']=record['data'];old['generated']=int(time.time())
                run.atomic(state,json.dumps(old,indent=2))
                run.atomic(BASE/'addon/WeaponResults.lua','local _, ns = ...\nns.weaponResults = '+w.lua_value(old)+'\n')
            if publish:
                expected=payload_bundle(old)
                target=Path(config['bridge_directory'])/'WeaponResults.lua'
                if not target.exists() or target.read_text(encoding='utf-8-sig')!=expected:run.atomic(target,expected)
            print(('Quick weapon comparisons' if quick else 'Complete weapon catalog')+' match the character and engine; cached results reused.',flush=True)
            return False
    work=BASE/'output/weapons'/fingerprint[:16];work.mkdir(parents=True,exist_ok=True)
    run.atomic(work/'character.json',json.dumps(run.native_character(character)))
    catalog=json.loads((BASE/'vendor/forever-master/assets/database/db.json').read_text(encoding='utf-8'))
    suffix_names={x['id']:x.get('name','') for x in catalog.get('randomSuffixes',[])}
    verified_routes=json.loads((BASE/'source-overrides.json').read_text(encoding='utf-8')).get('verified_routes',{})
    output={'guid':character['id'],'sourceExport':record['data'],'generated':int(time.time()),'runId':fingerprint,'published':publish,
        'artifactDirectory':'weapons/'+fingerprint[:16],'exportedLevel':character['level'],'catalogMode':True,
        'iterations':w.REFINE_ITERATIONS,'screenIterations':w.SCREEN_ITERATIONS,'catalogVariants':len(choices),
        'catalogWeapons':len({s['id'] for s in choices.values()}),'duration':scenario['duration'],'targetLevel':scenario['target_level'],
        'engineCommit':json.loads((BASE/'provenance.json').read_text(encoding='utf-8'))['upstream_commit'],'contexts':[]}
    output['scope']='quick' if quick else 'all';output['modelIdentity']=run.model_identity(character,'current')
    output['combatModel']=refresh_scope.combat_model(character,w.contexts(character,scenario)[0][1])
    output['combatTrinkets']={str(slot):character['gear']['items'][index] for index,slot in ((12,13),(13,14))}
    output['mountTrinketIds']=config.get('mount_trinket_ids',[])
    output.update(refresh_scope.reference_metadata(config))
    for key,sc in w.contexts(character,scenario):
        gear=w.full_gear(sc['target_gear']);sc['target_gear']=gear
        base=gear['items'][14];basekey=f"{base['id']}:{base.get('randomSuffix',0)}"
        context_choices=dict(choices);context_choices.setdefault(basekey,{'id':base['id'],'randomSuffix':base.get('randomSuffix',0)})
        jobs=[]
        for label,spec in context_choices.items():
            equipment=copy.deepcopy(gear);equipment['items'][14]=dict(spec,enchant=base.get('enchant',0));equipment['items'][15]={}
            jobs.append({'label':label,'equipment':equipment})
        # A different baseline weapon with the same enchant uses the same per-weapon simulations.
        digest=context_fingerprint(character,sc,engine_hash,full_catalog_hash)
        cache_dir=BASE/'output/weapons/catalog-cache'/digest[:24];cache_dir.mkdir(parents=True,exist_ok=True)
        screen_path=cache_dir/'screen.json';refined_path=cache_dir/'refined.json'
        screen=json.loads(screen_path.read_text(encoding='utf-8')) if screen_path.exists() and not force else {}
        refined=json.loads(refined_path.read_text(encoding='utf-8')) if refined_path.exists() and not force else {}
        run.atomic(work/f'{key}-scenario.json',json.dumps(sc));run.atomic(work/f'{key}-jobs.json',json.dumps(jobs))
        current_config=dict(config,_captureIdentity=run.model_identity(character,'current'))
        run_missing(work,key,jobs,screen,screen_path,w.SCREEN_ITERATIONS,current_config)
        if screen.get(basekey,{}).get('dps',0)<=0:raise ValueError('Weapon catalog baseline failed; installed results preserved.')
        active_screen={label:screen[label] for label in context_choices}
        selected=refine_keys(active_screen,basekey) | {label for label,spec in context_choices.items() if spec['id'] in w.SEEDS and screen.get(label,{}).get('dps',0)>0}
        run_missing(work,key,[j for j in jobs if j['label'] in selected],refined,refined_path,w.REFINE_ITERATIONS,current_config)
        results={label:refined.get(label,screen[label]) for label in context_choices}
        if backend!='legacy' and not quick:
            leaders=sorted((label for label,row in results.items() if row.get('dps',0)>0),key=lambda label:results[label]['dps'],reverse=True)[:10]
            final_labels=set(leaders) | {label for label,spec in context_choices.items() if spec['id'] in w.SEEDS or spec['id'] in (12583,12969,13163)}
            final_labels.discard(basekey)
            def check_capture():
                _,latest=run.latest(config)
                if run.model_identity(latest,'current')!=current_config['_captureIdentity']:
                    raise SupersededCapture('Combat gear changed; native bulk weapon batches preserved.')
            native_jobs=sorted((job for job in jobs if job['label'] in final_labels and results[job['label']].get('dps',0)>0),key=lambda job:job['label'])
            results.update(bulk_bridge.refine(config,character,sc,native_jobs,cache_dir,check_capture))
        # Keep raw final native rows alongside jobs for reproducible tooltip checks.
        run.atomic(work/f'{key}-results.jsonl','\n'.join(json.dumps(r) for r in results.values())+'\n')
        baseline=results[basekey];table=[];errors=list(selection_errors)
        if baseline.get('dps',0)<=0:raise ValueError('Refined baseline failed; installed results preserved.')
        for label,spec in context_choices.items():
            row=results[label]
            if not math.isfinite(row.get('dps',float('nan'))) or row.get('dps',0)<=0:
                errors.append(dict(spec,reason=row.get('error','No valid native simulation')));continue
            item=db[spec['id']];stats=item.get('scalingOptions',{}).get('0',{})
            name=item['name']+(' '+suffix_names.get(spec['randomSuffix'],'') if spec['randomSuffix'] else '')
            delta=row['dps']-row.get('comparisonBaselineDps',baseline['dps'])
            table.append(dict(spec,name=name,dps=baseline['dps']+delta,delta=delta,percent=100*delta/baseline['dps'],
                iterations=row['iterations'],secondsOom=row.get('secondsOom',0),meanError95=1.96*row['stdev']/math.sqrt(row['iterations']),
                pairedError95=row.get('pairedError95'),uncertain=abs(delta)<=row['pairedError95'] if 'pairedError95' in row else False,
                backend=row.get('backend','wowsims-screen'),nativeDps=row['dps'],comparisonBaselineDps=row.get('comparisonBaselineDps',baseline['dps']),
                speed=item.get('weaponSpeed',0),damageMin=stats.get('weaponDamageMin',0),damageMax=stats.get('weaponDamageMax',0),
                sourceUnverified=not bool(item.get('sources')) and str(spec['id']) not in verified_routes,
                provisionalProc=bool(item.get('procRate') and item['procRate'].get('status')!=1),baseline=label==basekey))
        table.sort(key=lambda r:r['dps'],reverse=True)
        output['contexts'].append({'key':key,'name':sc['name'],'baselineId':base['id'],'baselineSuffix':base.get('randomSuffix',0),
            'baselineName':db[base['id']]['name'],'baselineDps':baseline['dps'],'secondsOom':baseline.get('secondsOom',0),
            'enchant':base.get('enchant',0),'weapons':table,'errors':errors,'cacheDirectory':str(cache_dir)})
    plan=BASE/'prebis-targets.json'
    output['raidAssumptions']=json.loads(plan.read_text(encoding='utf-8')).get('raid_assumptions',{}) if plan.exists() else {}
    if quick:
        snapshot=refresh_scope.snapshot('weapons')
        if refresh_scope.matching(snapshot,character,output):
            for context in output['contexts']:
                if context['key']!='equipped':continue
                previous=next((c for c in snapshot['contexts'] if c['key']==context['key']),None)
                if not previous:continue
                rows={f"{r['id']}:{r.get('randomSuffix',0)}":dict(r,dps=context['baselineDps']+r['delta'],percent=100*r['delta']/context['baselineDps']) for r in previous['weapons']}
                rows.update({f"{r['id']}:{r.get('randomSuffix',0)}":r for r in context['weapons']})
                context['weapons']=sorted(rows.values(),key=lambda r:r['dps'],reverse=True)
    text=payload_bundle(output)
    if publish:run.atomic(Path(config['bridge_directory'])/'WeaponResults.lua',text)
    run.atomic(BASE/'addon/WeaponResults.lua',text);run.atomic(state,json.dumps(output,indent=2))
    import export_weapon_catalog
    export_weapon_catalog.export(output)
    print(('Quick weapon comparisons' if quick else 'Complete weapon catalog')+f' published: {output["catalogWeapons"]} weapons, {output["catalogVariants"]} variants.',flush=True)
    return True
