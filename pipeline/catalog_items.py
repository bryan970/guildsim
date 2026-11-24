from guild_runtime import runtime_root, usable_faction
"""Complete compatible equipment catalog, cached by actual combat inputs."""
import copy
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time

import run
import sim_progress
import item_sims as items
import bulk_bridge
import refresh_scope
from build_prebis import database, WOW_SLOTS
from weapon_sims import full_gear, contexts, lua_value

BASE=runtime_root()
SCREEN=100
REFINE=1000
FINAL=12500
CHUNK=128
REFINEMENT_VERSION=3


def refinement_shortlist(native, jobs, per_slot=24, variants_per_item=2):
    by_slot={}
    for label,row in native.items():
        if label=='baseline' or label not in jobs or row.get('dps',0)<=0:continue
        item_key,slot=label.split('@');item_id=int(item_key.split(':')[0])
        # Native bulk means are comparable through their paired-baseline deltas.
        score=row['dps']-row.get('comparisonBaselineDps',0)
        if 'comparisonBaselineDps' not in row:score-=native['baseline']['dps']
        by_slot.setdefault(slot,[]).append((score,item_id,label))
    selected=set()
    for rows in by_slot.values():
        counts={}
        for _,item_id,label in sorted(rows,reverse=True):
            if item_id not in counts and len(counts)>=per_slot:continue
            if counts.get(item_id,0)>=variants_per_item:continue
            counts[item_id]=counts.get(item_id,0)+1;selected.add(label)
    return sorted(selected)


def candidates(db,professions):
    specs={};excluded={}
    for item_id,item in db.items():
        if item.get('type') not in items.SLOTS:continue
        if item.get('type')==14 and item.get('rangedWeaponType')!=7:continue
        for option in item.get('randomSuffixOptions') or [0]:
            suffix=option.get('id',0) if isinstance(option,dict) else option
            spec={'id':item_id,'randomSuffix':suffix,'enchant':0}
            if item.get('phase',1)!=1:
                excluded[items.item_key(spec)]='Outside the current verified Forever phase catalog';continue
            _,why=items.validate(spec,db,professions)
            if why:excluded[str(item_id)+':'+str(suffix)+':0']=why
            else:specs[items.item_key(spec)]=spec
    return specs,excluded


def source_zones(item):
    return {source.get('drop',{}).get('zoneId') for source in item.get('sources',[])} - {None}


def catalog_order(label,db,priority_zones):
    if label=='baseline':return (-1,0,0,0,label)
    item_id,suffix,_=map(int,label.split('@')[0].split(':'));item=db[item_id]
    level=item.get('reqLvl',0);quality=item.get('quality',0)
    group=(0 if source_zones(item)&priority_zones else
           1 if level>=50 and quality>=3 and source_zones(item) else
           2 if level>=50 and quality>=3 else 3 if suffix==0 else 4)
    return (group,-level,-quality,item_id,label)


def payload_text(payload,target='itemResults'):
    # Separate functions bound the Lua compiler's constants and temporary tables.
    metadata={k:v for k,v in payload.items() if k not in ('items','errors','names')}
    import effect_coverage
    metadata.update(effect_coverage.catalog_metadata(database()))
    import browser_data
    browser_items=browser_data.metadata(database(),BASE)
    metadata['browserSuffixNames']=browser_data.suffix_names(BASE)
    metadata['classRestrictions']={item_id:True for item_id,item in database().items()
                                   if item.get('classAllowlist') and 2 not in item['classAllowlist']}
    text=['local _, ns = ...','ns.'+target+' = '+lua_value(metadata),
          'local p=ns.'+target,'p.compact={};p.errors={}',
          'p.names='+lua_value({int(item_id):name for item_id,name in payload.get('names',{}).items()}), 'p.browserItems={}']
    browser_entries=list(browser_items.items())
    for start in range(0,len(browser_entries),500):
        text.append('do local function add() local rows='+lua_value(dict(browser_entries[start:start+500]))+';for k,v in pairs(rows) do p.browserItems[k]=v end end;add() end')
    entries=list(payload['items'].items())
    for start in range(0,len(entries),500):
        part={}
        for key,row in entries[start:start+500]:
            part[key]=[row['id'],row.get('randomSuffix',0),row.get('enchant',0),row['dps'],row['inventorySlot'],
                       row['replacedId'],row['iterations'],row['meanError95'],bool(row['provisional'] or effect_coverage.row_coverage(row,{'id':row['replacedId']},metadata['missingItemEffects'])),bool(row.get('uncertain')),
                       row.get('pairedError95'),row.get('backend'),row.get('nativeDps'),row.get('comparisonBaselineDps'),bool(row['provisional'])]
        text.append('do local function add() local rows='+lua_value(part)+';for k,v in pairs(rows) do p.compact[k]=v end end;add() end')
    errors=list(payload.get('errors',{}).items())
    for start in range(0,len(errors),500):
        text.append('do local function add() local rows='+lua_value(dict(errors[start:start+500]))+';for k,v in pairs(rows) do p.errors[k]=v end end;add() end')
    text.append('''p.items=setmetatable({}, {__index=function(_,key)
local v=p.compact[key];if not v then return nil end
return {id=v[1],randomSuffix=v[2],enchant=v[3],name=p.names[v[1]] or p.names[tostring(v[1])],dps=v[4],
delta=v[4]-p.baselineDps,percent=100*(v[4]/p.baselineDps-1),inventorySlot=v[5],
replacedId=v[6],replacedName=p.names[v[6]] or p.names[tostring(v[6])] or "empty slot",iterations=v[7],meanError95=v[8],provisional=v[9],uncertain=v[10],
pairedError95=v[11],backend=v[12],nativeDps=v[13],comparisonBaselineDps=v[14],procProvisional=v[15]}
end})
''')
    return '\n'.join(text)


def payload_bundle(payload):
    text=payload_text(payload)
    old=refresh_scope.snapshot('items') if payload.get('scope')=='quick' else None
    if old:text+='\n'+payload_text(old,'itemSnapshot')
    import trinket_pairs
    text+=trinket_pairs.lua_payload(BASE)
    return text


def refresh(config,force=False,publish=True):
    config=refresh_scope.catalog_config(config)
    record,character=run.latest(config)
    scenario=json.loads((BASE/'scenario.json').read_text(encoding='utf-8'))
    sc=contexts(character,scenario)[0][1];gear=full_gear(sc['target_gear']);sc['target_gear']=gear
    db=database();profession_ids={'Enchanting':3,'Mining':9,'Blacksmithing':2,'Engineering':4,'Leatherworking':8,'Tailoring':11,'Alchemy':1}
    professions={profession_ids.get(p['name']) for p in character.get('professions',[])}
    specs,errors=candidates(db,professions)
    quick=refresh_scope.is_quick(config)
    if quick:
        selected={};problems={};ignored=set(config.get('mount_trinket_ids',[]))
        for spec in refresh_scope.candidates(config,character):
            if not spec or not spec.get('id') or spec['id'] in ignored:continue
            item,why=items.validate(spec,db,professions)
            key=items.item_key(spec)
            if not item:
                if spec['id'] in db and db[spec['id']].get('type') in items.SLOTS:problems[key]=why
                continue
            if why:problems[key]=why
            elif key in specs:selected[key]={k:int(spec.get(k,0)) for k in ('id','randomSuffix','enchant')}
            elif spec.get('enchant') and not spec.get('unsupportedVariant'):selected[key]={k:int(spec.get(k,0)) for k in ('id','randomSuffix','enchant')}
            else:problems[key]=errors.get(key,'Variant is not supported')
        specs,errors=selected,problems
        previous=BASE/'output/items.json'
        if previous.exists():refresh_scope.archive('items',json.loads(previous.read_text(encoding='utf-8')))
    # Owned enchants are extra instances; base catalog entries never need inspection.
    for spec in gear['items']:
        if spec.get('id') and not items.validate(spec,db,professions)[1]:
            specs[items.item_key(spec)]={k:int(spec.get(k,0)) for k in ('id','randomSuffix','enchant')}
    catalog_hash=hashlib.sha256(json.dumps(specs,sort_keys=True).encode()).hexdigest()
    model=json.dumps([run.model_identity(character,'current'),sc,12500,1],sort_keys=True).encode()+(BASE/'retlocal.exe').read_bytes()
    model_hash=hashlib.sha256(model).hexdigest()
    priority_zones=set(config.get('item_priority_zone_ids',[]))
    backend=bulk_bridge.backend_identity(config)
    signature=hashlib.sha256((model_hash+catalog_hash+str([SCREEN,REFINE,FINAL,sorted(priority_zones),backend,REFINEMENT_VERSION,quick])).encode()).hexdigest()
    state=BASE/'output/items.json'
    if state.exists() and not force:
        old=json.loads(state.read_text(encoding='utf-8'))
        if old.get('catalogMode') and old.get('runId')==signature and old.get('complete') and (not publish or old.get('published')):
            old.update(refresh_scope.reference_metadata(config))
            if old['sourceExport']!=record['data']:old['sourceExport']=record['data'];run.atomic(state,json.dumps(old))
            run.atomic(state,json.dumps(old))
            text=payload_bundle(old)
            if publish:
                dest=Path(config['bridge_directory'])/'ItemResults.lua'
                if not dest.exists() or dest.read_text(encoding='utf-8-sig')!=text:run.atomic(dest,text)
            return False
    work=BASE/'output/items'/model_hash[:16];work.mkdir(parents=True,exist_ok=True)
    run.atomic(work/'character.json',json.dumps(run.native_character(character)));run.atomic(work/'scenario.json',json.dumps(sc))
    store=sqlite3.connect(work/'catalog.sqlite')
    try:
        store.execute('CREATE TABLE IF NOT EXISTS results (label TEXT PRIMARY KEY, iterations INTEGER, payload TEXT)')
        if force:store.execute('DELETE FROM results');store.commit()
        previous=work/'cache.json'
        if previous.exists() and not force:
            for label,row in json.loads(previous.read_text(encoding='utf-8')).items():
                store.execute('INSERT OR IGNORE INTO results VALUES (?,?,?)',(label,row.get('iterations',FINAL),json.dumps(row)))
            store.commit()
        native={label:json.loads(row) for label,row in store.execute('SELECT label,payload FROM results')}
        jobs={'baseline':gear};variants={}
        for key,spec in specs.items():
            choices=items.choices_for(spec,db[spec['id']],gear,db);variants[key]=choices
            if not choices:errors[key]='No legal unique-equipped replacement slot'
            for slot,equipment,same in choices:
                if not same:jobs[key+'@'+str(slot)]=equipment
        identity=run.model_identity(character,'current')

        def compute(labels,iterations,stage,progress_offset=0,progress_total=None):
            todo=[label for label in labels if label not in native or native[label].get('iterations',0)<iterations]
            already=len(labels)-len(todo)
            for start in range(0,len(todo),CHUNK):
                _,latest=run.latest(config)
                if run.model_identity(latest,'current')!=identity:
                    store.close();from catalog_weapons import SupersededCapture
                    raise SupersededCapture('New combat loadout captured; completed equipment catalog batches are preserved.')
                batch=todo[start:start+CHUNK]
                run.atomic(work/'catalog-jobs.json',json.dumps([{'label':label,'equipment':jobs[label]} for label in batch]))
                output=work/'catalog-pending.jsonl'
                cmd=[str(BASE/'retlocal.exe'),'--root',str(BASE/'vendor/forever-master'),'--character',str(work/'character.json'),
                     '--scenario',str(work/'scenario.json'),'--mode','planning','--iterations',str(iterations),'--workers',str(config.get('weapon_workers',4)),
                     '--batch',str(work/'catalog-jobs.json'),'--out',str(output)]
                result=sim_progress.engine(cmd,cwd=BASE,log_path=work/'catalog-engine.log',stage=stage,results_path=output,
                    total=len(batch),offset=progress_offset+already+start,overall_total=progress_total or len(labels),adaptive=config.get('smart_concurrency',False))
                if result.returncode:store.close();raise ValueError('Equipment catalog batch failed; completed batches and installed data preserved.')
                rows=[json.loads(line) for line in output.read_text(encoding='utf-8').splitlines() if line.strip()]
                if {r['label'] for r in rows}!=set(batch):store.close();raise ValueError('Incomplete equipment catalog batch')
                for row in rows:
                    native[row['label']]=row
                    store.execute('INSERT OR REPLACE INTO results VALUES (?,?,?)',(row['label'],iterations,json.dumps(row)))
                store.commit()
                print(f'Equipment catalog: {stage}: {start+len(batch)}/{len(todo)}',flush=True)
            return bool(todo)

        compute(['baseline'],FINAL,'Equipment catalog — baseline')
        baseline=native['baseline']
        if baseline.get('dps',0)<=0:store.close();raise ValueError('Equipment catalog baseline failed')

        def publish_rows(complete=False):
            rows={};problems=dict(errors)
            for key,spec in specs.items():
                choices=variants[key];options=[]
                for slot,_,same in choices:
                    r=baseline if same else native.get(key+'@'+str(slot))
                    if not r:continue
                    if 'dps' not in r:problems[key]=r.get('error','Unsupported simulation');continue
                    old=gear['items'][slot];item=db[spec['id']];old_item=db.get(old.get('id'),{})
                    delta=r['dps']-r.get('comparisonBaselineDps',baseline['dps'])
                    effective_dps=baseline['dps']+delta
                    difference_error=r.get('pairedError95',1.96*math.sqrt(r['stdev']**2/r['iterations']+baseline['stdev']**2/baseline['iterations']))
                    options.append(dict(spec,name=item['name'],dps=effective_dps,delta=delta,percent=100*delta/baseline['dps'],
                        inventorySlot=WOW_SLOTS[slot],replacedId=old.get('id',0),replacedName=old_item.get('name','empty slot'),
                        iterations=r['iterations'],meanError95=1.96*r['stdev']/math.sqrt(r['iterations']),
                        uncertain=abs(delta)<=difference_error,pairedError95=r.get('pairedError95'),backend=r.get('backend','wowsims-screen'),
                        nativeDps=r['dps'],comparisonBaselineDps=r.get('comparisonBaselineDps',baseline['dps']),
                        provisional=any(x.get('procRate') and x['procRate'].get('status')!=1 for x in (item,old_item))))
                if options and len(options)==len(choices):
                    best=max(options,key=lambda r:r['dps']);best['alternatives']=[{'inventorySlot':r['inventorySlot'],'dps':r['dps'],'replacedName':r['replacedName']} for r in options]
                    rows[key]=best
            payload={'guid':character['id'],'sourceExport':record['data'],'generated':int(time.time()),'runId':signature,'published':publish,
                'catalogMode':True,'complete':complete,'iterations':FINAL,'screenIterations':SCREEN,'duration':sc['duration'],'targetLevel':sc['target_level'],
                'baselineDps':baseline['dps'],'items':rows,'errors':problems,'catalogVariants':len(specs),'completedVariants':len(rows),
                'names':{i:item['name'] for i,item in db.items()},'engineCommit':json.loads((BASE/'provenance.json').read_text(encoding='utf-8'))['upstream_commit']}
            payload['scope']='quick' if quick else 'all';payload['modelIdentity']=identity
            payload['combatModel']=model_hash
            payload.update(refresh_scope.reference_metadata(config))
            payload['quickVariants']=len(specs) if quick else None
            if quick:payload=refresh_scope.merge_items(payload,character)
            text=payload_bundle(payload)
            if publish:run.atomic(Path(config['bridge_directory'])/'ItemResults.lua',text)
            run.atomic(BASE/'addon/ItemResults.lua',text);run.atomic(state,json.dumps(payload))
            return payload

        # Publish complete batches as they become available; no item hover is required.
        labels=sorted(jobs,key=lambda label:catalog_order(label,db,priority_zones))
        priority=[label for label in labels if label!='baseline' and source_zones(db[int(label.split(':')[0])])&priority_zones] if not quick else []
        if priority:
            compute(priority,REFINE,'Equipment catalog - priority dungeon loot')
            publish_rows()
        for offset in range(0,len(labels),2048):
            changed=compute(labels[offset:offset+2048],REFINE if quick else SCREEN,'Quick comparisons - equipped, bags and farming targets' if quick else 'Equipment catalog — every compatible item',offset,len(labels))
            if changed or offset==0:publish_rows()
        near=refinement_shortlist(native,jobs)
        print(f'Streamlined refinement: {len(near)} item-slot candidates; every catalog variant retains its screening result.',flush=True)
        compute(near,REFINE,'Equipment catalog — refine possible upgrades')
        publish_rows()
        best={}
        for key,choices in variants.items():
            for slot,_,same in choices:
                label='baseline' if same else key+'@'+str(slot);r=native.get(label,{})
                if 'dps' in r and (label=='baseline' or label in near):
                    score=r['dps']-r.get('comparisonBaselineDps',baseline['dps'])
                    best.setdefault(slot,[]).append((score,label))
        finalists={'baseline'}
        for rows in best.values():finalists.update(label for _,label in sorted(rows,reverse=True)[:(1 if quick else 3)])
        if backend!='legacy':
            def check_capture():
                _,latest=run.latest(config)
                if run.model_identity(latest,'current')!=identity:
                    from catalog_weapons import SupersededCapture
                    raise SupersededCapture('Combat gear changed; native bulk chunks preserved for this setup.')
            selected=[{'label':label,'equipment':jobs[label]} for label in sorted(finalists) if label!='baseline' and not (quick and native[label].get('backend')=='wowsims-bulk')]
            bulk_config=dict(config,bulk_chunk_size=1) if quick else config
            for label,row in bulk_bridge.refine(bulk_config,character,sc,selected,work,check_capture).items():
                native[label]=row
                store.execute('INSERT OR REPLACE INTO results VALUES (?,?,?)',(label,row['iterations'],json.dumps(row)))
            store.commit()
        else:
            compute(sorted(finalists),FINAL,'Equipment catalog — final slot leaders')
        payload=publish_rows(True);store.close()
        print((f'Quick comparisons published: {len(specs)} requested variants; {len(payload["items"])} current rows including matching catalog snapshots.'
               if quick else f'Complete equipment catalog published: {len(payload["items"])} variants; {len(jobs)} legal item-slot swaps.'),flush=True)
        return True
    finally:
        store.close()
