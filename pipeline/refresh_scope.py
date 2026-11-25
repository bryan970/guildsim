from guild_runtime import runtime_root, usable_faction
"""Separate everyday comparisons from explicitly requested catalog runs."""
import copy
import hashlib
import json
from pathlib import Path
import time

import run
from lua_data import loads

BASE=runtime_root()


def catalog_config(config):
    return dict(config,_catalog_reference=True) if config.get('catalog_reference_trinkets') else config


def reference_metadata(config):
    if not config.get('_catalog_reference'):return {}
    return {'referenceTrinkets':config['catalog_reference_trinkets'],
            'comparisonLabel':'Reference trinkets: '+config.get('catalog_reference_label','fixed catalog pair')}


def is_quick(config):
    return config.get('refresh_scope')=='quick'


def combat_model(character,scenario,root=None):
    data=json.dumps([run.model_identity(character,'current'),scenario,12500,1],sort_keys=True).encode()
    return hashlib.sha256(data+((root or BASE)/'retlocal.exe').read_bytes()).hexdigest()


def inventory(config,character):
    saved=Path(config['saved_variables']).with_name('GuildSimBeta.lua')
    if not saved.exists():return []
    db=loads(saved.read_text(encoding='utf-8-sig')).get('GuildSimBetaDB',{})
    rows=db.get('quickItems',{}).get(character['id'],{})
    return list(rows.values()) if isinstance(rows,dict) else list(rows)


def candidates(config,character):
    from item_sims import planning_candidates
    saved=Path(config['saved_variables']).with_name('GuildSimBeta.lua')
    pins=[]
    if saved.exists():
        data=loads(saved.read_text(encoding='utf-8-sig')).get('GuildSimBetaDB',{})
        for group in ('manualItems','inspectedItems','weaponQueue'):
            rows=data.get(group,{}).get(character['id'],{})
            pins.extend(list(rows.values()) if isinstance(rows,dict) else list(rows))
    requested=[{'id':int(item_id)} for item_id in config.get('quick_item_ids',[])[-20:]]
    return character['gear']['items']+inventory(config,character)+planning_candidates()+pins+requested


def archive(kind,payload):
    if payload.get('scope')=='quick' or not payload.get('complete',True):return
    if not payload.get('catalogMode'):return
    saved=copy.deepcopy(payload)
    if not saved.get('modelIdentity') or not saved.get('combatModel'):
        try:
            weapon=payload if kind=='weapons' else json.loads((BASE/'output/weapons.json').read_text(encoding='utf-8'))
            if weapon['sourceExport']!=payload['sourceExport']:
                weapon=snapshot('weapons') or weapon
            if weapon['sourceExport']==payload['sourceExport']:
                path=BASE/'output'/weapon['artifactDirectory']/'equipped-scenario.json'
                scenario=json.loads(path.read_text(encoding='utf-8'));character=json.loads(payload['sourceExport'])
                character['gear']=scenario['target_gear'];character['talents']=scenario['target_talents']
                saved['modelIdentity']=run.model_identity(character,'current')
                saved['combatModel']=combat_model(character,scenario)
        except (OSError,KeyError,ValueError):pass
    path=BASE/'output/catalog-snapshots'/f'{kind}.json';path.parent.mkdir(parents=True,exist_ok=True)
    run.atomic(path,json.dumps(saved))


def snapshot(kind):
    path=BASE/'output/catalog-snapshots'/f'{kind}.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def matching(snapshot,character,payload):
    return snapshot and payload.get('combatModel') and snapshot.get('combatModel')==payload['combatModel'] and snapshot.get('modelIdentity')==run.model_identity(character,'current') and all(
        snapshot.get(key)==payload.get(key) for key in ('engineCommit','duration','targetLevel'))


def merge_items(payload,character):
    old=snapshot('items')
    if not matching(old,character,payload):return payload
    rows={}
    for key,row in old['items'].items():
        row=dict(row);row['dps']=payload['baselineDps']+row['delta'];row['percent']=100*row['delta']/payload['baselineDps']
        if 'alternatives' in row:row['alternatives']=[dict(option,dps=option['dps']+payload['baselineDps']-old['baselineDps']) for option in row['alternatives']]
        rows[key]=row
    rows.update(payload['items']);payload=dict(payload,items=rows)
    payload['completedVariants']=len(rows);payload['catalogVariants']=len(rows)
    return payload


def requested(config):
    path=BASE/'output/full-catalog.request.json'
    if not path.exists():return None
    request=json.loads(path.read_text(encoding='utf-8'));state=BASE/'output/full-catalog.state.json'
    if state.exists() and json.loads(state.read_text(encoding='utf-8')).get('request')==request['requested']:return None
    _,character=run.latest(catalog_config(config))
    if request.get('model')!=run.model_identity(character,'current'):
        finish_request(request,'cancelled: combat gear changed; quick results take priority')
        return None
    return request


def finish_request(request,status):
    run.atomic(BASE/'output/full-catalog.state.json',json.dumps({'request':request['requested'],'status':status}))


def run_requested(config,publish=True):
    request=requested(config)
    if not request:return False
    full=dict(catalog_config(config),refresh_scope='all',item_catalog_mode='all')
    try:
        import catalog_weapons,catalog_items,sim_progress
        sim_progress.update('Full catalog requested','Quick updates are complete. Running the optional catalog for this captured loadout.')
        catalog_items.refresh(full,publish=publish)
        catalog_weapons.refresh(full,publish=publish)
        for kind in ('weapons','items'):archive(kind,json.loads((BASE/f'output/{kind}.json').read_text(encoding='utf-8')))
        finish_request(request,'complete')
        sim_progress.update('Ready to reload','Quick results and the requested full catalog are ready.',state='ready')
        return True
    except Exception:
        finish_request(request,'interrupted; quick update takes priority; request a catalog run again when ready')
        raise


def catalog_status(config):
    """A historical completion is not coverage for a different combat setup."""
    from weapon_sims import contexts
    _,character=run.latest(catalog_config(config))
    scenario=contexts(character,json.loads((BASE/'scenario.json').read_text(encoding='utf-8')))[0][1]
    model=combat_model(character,scenario);identity=run.model_identity(character,'current')
    complete=True
    for kind in ('items','weapons'):
        saved=snapshot(kind)
        complete=bool(complete and saved and saved.get('combatModel')==model and
            saved.get('modelIdentity')==identity and saved.get('scope')=='all' and saved.get('complete',True))
    return character,model,complete


def schedule_catalog(config):
    """Queue once per settled reference model; retain caches and never loop failed jobs."""
    if not config.get('auto_full_catalog'):return None
    character,model,covered=catalog_status(config)
    path=BASE/'output/auto-catalog.json'
    previous=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    now=time.time();delay=max(0,int(config.get('catalog_settle_seconds',120)))
    status=previous if previous.get('model')==model else {'model':model,'observed':now}
    if covered:
        status.update(state='current',message='Full catalog matches the current reference setup.')
    else:
        request_path=BASE/'output/full-catalog.request.json';state_path=BASE/'output/full-catalog.state.json'
        request=json.loads(request_path.read_text(encoding='utf-8')) if request_path.exists() else {}
        finished=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
        pending=request.get('requested') and finished.get('request')!=request['requested']
        if pending:
            status.update(state='queued',message='Full catalog queued or running; quick results remain available.')
        elif status.get('attempt'):
            status.update(state='attention',message='Previous full-catalog attempt stopped. Completed batches are cached; use the desktop catalog button to resume.')
        elif now-status['observed']<delay:
            remaining=max(0,int(delay-(now-status['observed'])))
            status.update(state='settling',message=f'Full catalog refresh queued after {remaining}s of stable reference gear; quick results are ready.')
        else:
            stamp=time.time_ns()
            run.atomic(request_path,json.dumps({'requested':stamp,'model':run.model_identity(character,'current'),'combatModel':model,'automatic':True}))
            status.update(state='queued',attempt=stamp,message='Full catalog queued automatically for the current reference setup.')
    text=json.dumps(status,indent=2)
    if not path.exists() or path.read_text(encoding='utf-8')!=text:run.atomic(path,text)
    return status
