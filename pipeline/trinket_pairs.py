from guild_runtime import runtime_root, usable_faction
"""Independent native two-trinket comparisons; the general catalog stays fixed."""
import copy
import hashlib
import itertools
import json
from pathlib import Path
import time
import re

import bulk_bridge
import effect_coverage
import fight_profiles
import fight_library
import item_sims
from lua_data import loads
import refresh_scope
import run
import sim_progress
from build_prebis import database
from weapon_sims import contexts, lua_value

BASE=runtime_root()


def saved_pool(config,guid):
    path=Path(config['saved_variables']).with_name('GuildSimBeta.lua')
    db=loads(path.read_text(encoding='utf-8-sig')).get('GuildSimBetaDB',{}) if path.exists() else {}
    rows=db.get('trinketPool',{}).get(guid,{})
    excluded=db.get('trinketExclusions',{}).get(guid,{})
    return list(rows.values()) if isinstance(rows,dict) else list(rows),{int(k) for k,v in excluded.items() if v}


def pool(config,record,character,db):
    guid=character['id'];manual,excluded=saved_pool(config,guid)
    path=BASE/'output/trinket-pool.json'
    memory=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    remembered=memory.setdefault(guid,{})
    # Remember observed combat trinkets even when they later move to the bank.
    raw=json.loads(record['data'])
    observed=raw['gear']['items'][12:14]+refresh_scope.inventory(config,character)
    professions={'Alchemy':1,'Blacksmithing':2,'Enchanting':3,'Engineering':4,'Leatherworking':8,'Mining':9,'Tailoring':11}
    known={professions.get(p['name']) for p in character.get('professions',[])}
    errors={};utility=set(config.get('mount_trinket_ids',[]))
    for spec in observed:
        if spec and db.get(spec.get('id'),{}).get('type')==12 and spec['id'] not in utility:
            remembered[item_sims.item_key(spec)]=spec
    run.atomic(path,json.dumps(memory))
    specs={}
    requested=[{'id':int(i)} for i in config.get('trinket_pool_ids',[])]
    for spec in list(remembered.values())+manual+requested+character['gear']['items'][12:14]:
        if not spec or not spec.get('id') or spec['id'] in utility or spec['id'] in excluded:continue
        key=item_sims.item_key(spec)
        item,why=item_sims.validate(spec,db,known)
        if not item or item.get('type')!=12 or why:
            errors[key]=why or 'Not a supported trinket';continue
        specs[key]={k:int(spec.get(k,0)) for k in ('id','randomSuffix','enchant')}
    return dict(sorted(specs.items())),errors


def legal(equipment,db):
    equipped=[db.get(item.get('id'),{}) for item in equipment['items'] if item and item.get('id')]
    for item in equipped:
        if item.get('unique') and sum(other.get('id')==item['id'] for other in equipped)>1:return False
        category=item.get('limitCategory')
        if category and sum(other.get('limitCategory')==category for other in equipped)>item.get('limitCategoryLimit',1):return False
    return True


def jobs_for(specs,gear,db):
    jobs=[{'label':'baseline','equipment':copy.deepcopy(gear)}];pairs={};excluded={}
    for a,b in itertools.combinations(specs,2):
        pair=a+'+'+b;orders=[]
        for first,second in ((a,b),(b,a)):
            equipment=copy.deepcopy(gear)
            equipment['items'][12:14]=[specs[first],specs[second]]
            if not legal(equipment,db):continue
            label=first+'>'+second
            jobs.append({'label':label,'equipment':equipment});orders.append(label)
        if orders:pairs[pair]=orders
        else:excluded[pair]='Unique-equipped or shared item-category restriction'
    return jobs,pairs,excluded


def lua_payload(root=None):
    root=root or BASE;path=root/'output/trinket-pairs.json'
    if not path.exists():return ''
    text='\nns.trinketPairs = '+lua_value(json.loads(path.read_text(encoding='utf-8')))+'\nns.trinketPairProfiles={default=ns.trinketPairs}\n'
    config_path=root/'config.json';config=json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    profiles=fight_profiles.registry(config,root)
    text+='ns.fightProfiles='+lua_value(list(profiles.values()))+'\n'
    for key in profiles:
        if key=='default':continue
        path=root/'output'/('trinket-pairs-'+key+'.json')
        if path.exists():text+='ns.trinketPairProfiles['+lua_value(key)+']='+lua_value(json.loads(path.read_text(encoding='utf-8')))+'\n'
    return text


def result_path(config):
    profile=config.get('_fight_profile',{}).get('key','default')
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',profile):raise ValueError('Invalid trinket pair profile')
    return BASE/'output'/('trinket-pairs.json' if profile=='default' else 'trinket-pairs-undead.json')


def publish_payload(config,payload,publish):
    def changed(path,text):
        if not path.exists() or path.read_text(encoding='utf-8-sig')!=text:run.atomic(path,text)
    changed(result_path(config),json.dumps(payload,indent=2))
    # Reuse an existing generated file, avoiding a TOC change or game restart.
    path=BASE/'output/items.json'
    if path.exists():
        import catalog_items
        text=catalog_items.payload_bundle(json.loads(path.read_text(encoding='utf-8')))
        changed(BASE/'addon/ItemResults.lua',text)
        if publish:changed(Path(config['bridge_directory'])/'ItemResults.lua',text)


def refresh(config,publish=True):
    changed=False
    profiles=fight_profiles.registry(config,BASE)
    engine=json.loads((BASE/'provenance.json').read_text(encoding='utf-8'))['upstream_commit']
    fight_library.register_profiles(BASE,profiles,engine,['default']+list(config.get('fight_profiles_enabled',[])))
    for profile in fight_profiles.selected(config,BASE):
        changed=refresh_profile(dict(config,_fight_profile=profile),publish) or changed
    return changed


def refresh_profile(config,publish=True):
    config=refresh_scope.catalog_config(config)
    record,character=run.latest(config)
    db=database();specs,errors=pool(config,record,character,db)
    scenario=contexts(character,json.loads((BASE/'scenario.json').read_text(encoding='utf-8')))[0][1]
    base_model=refresh_scope.combat_model(character,scenario,BASE)
    profile=config.get('_fight_profile',{'key':'default','label':'Raid setup','target':{},'encounter':{}})
    if profile.get('target') or profile.get('encounter'):scenario['_fight_profile']=profile
    gear=scenario['target_gear'];identity=run.model_identity(character,'current')
    model=hashlib.sha256(json.dumps([identity,scenario,bulk_bridge.backend_identity(config),1],sort_keys=True).encode()+(BASE/'retlocal.exe').read_bytes()).hexdigest()
    signature=hashlib.sha256(json.dumps([model,specs,errors],sort_keys=True).encode()).hexdigest()
    path=result_path(config)
    if path.exists():
        previous=json.loads(path.read_text(encoding='utf-8'))
        if previous.get('runId')==signature and previous.get('complete'):
            previous['sourceExport']=record['data']
            previous.update(profileKey=profile['key'],targetLabel=profile['label'],fightProfile=profile,baseCombatModel=base_model)
            record_library(config,previous,profile,character,scenario)
            publish_payload(config,previous,publish)
            return False
    jobs,pairs,excluded=jobs_for(specs,gear,db)
    work=BASE/'output/trinket-pairs'/model[:24];work.mkdir(parents=True,exist_ok=True)
    def current():
        _,latest=run.latest(config)
        if run.model_identity(latest,'current')!=identity:
            from catalog_weapons import SupersededCapture
            raise SupersededCapture('Non-trinket gear changed; completed trinket-pair simulations are cached.')
    target_label=profile['label']
    sim_progress.update('Trinket pairs — '+target_label,f'{len(specs)} pool items; {len(pairs)} legal pairs, both slot orders; unchanged pairs reuse cached results.')
    if config.get('comparison_backend')!='wowsims-bulk':raise ValueError('Trinket pairs require the native WoWSims bulk backend.')
    # One request per order makes each completed pair reusable when the pool grows.
    rows=bulk_bridge.refine(dict(config,bulk_chunk_size=1,bulk_stage_label='Trinket pairs — '+target_label),character,scenario,jobs,work,current) if pairs else {}
    current();missing=effect_coverage.gaps();ranked=[]
    for key,orders in pairs.items():
        best=max(orders,key=lambda label:rows[label]['dps']);first,second=best.split('>');row=rows[best]
        equipment=next(job['equipment'] for job in jobs if job['label']==best)
        gaps={};provisional=False
        for spec in equipment['items']+gear['items']:
            item=db.get((spec or {}).get('id'),{})
            if item.get('id') in missing:gaps[str(item['id'])]=[v or 'Effect not implemented by WoWSims' for v in missing[item['id']]]
            if item.get('procRate') and item['procRate'].get('status')!=1:provisional=True
        delta=row['dps']-row['comparisonBaselineDps']
        ranked.append({'key':key,'first':specs[first],'second':specs[second],
            'firstName':db[specs[first]['id']]['name'],'secondName':db[specs[second]['id']]['name'],
            'dps':row['dps'],'delta':delta,'percent':100*delta/row['comparisonBaselineDps'],
            'pairedError95':row['pairedError95'],'iterations':row['iterations'],
            'uncertain':abs(delta)<=row['pairedError95'],'provisional':provisional or bool(gaps),
            'missingEffects':gaps,'orders':[dict(rows[label],first=label.split('>')[0],second=label.split('>')[1]) for label in orders]})
    ranked.sort(key=lambda row:row['dps'],reverse=True)
    payload={'guid':character['id'],'sourceExport':record['data'],'generated':int(time.time()),'runId':signature,
        'complete':True,'referenceTrinkets':character['gear']['items'][12:14],
        'profileKey':profile['key'],'targetLabel':target_label,'fightProfile':profile,'baseCombatModel':base_model,
        'comparisonLabel':refresh_scope.reference_metadata(config).get('comparisonLabel','Captured combat pair'),
        'pool':{key:dict(spec,name=db[spec['id']]['name'],icon=db[spec['id']].get('icon','')) for key,spec in specs.items()},
        'rows':ranked,'poolErrors':errors,'excludedPairs':excluded,'testedOrders':len(jobs)-1 if pairs else 0,
        'baselineDps':rows['baseline']['dps'] if rows else None,'duration':scenario['duration'],'targetLevel':scenario['target_level'],
        'engineCommit':json.loads((BASE/'provenance.json').read_text(encoding='utf-8'))['upstream_commit']}
    record_library(config,payload,profile,character,scenario)
    publish_payload(config,payload,publish)
    print(f'Trinket pairs ready: {len(specs)} pool items, {len(pairs)} legal combinations, {payload["testedOrders"]} slot orders.',flush=True)
    return True


def record_library(config,payload,profile,character,scenario):
    if not payload.get('rows'):return
    result=json.loads((BASE/'output/result.json').read_text(encoding='utf-8'))
    request=bulk_bridge.make_request(result,character,scenario,[],
        config.get('catalog_reference_trinkets') if config.get('_catalog_reference') else None,
        profile if profile.get('target') or profile.get('encounter') else None)['baseRequest']
    fight_library.record(BASE,payload,profile,request)
