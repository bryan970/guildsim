from guild_runtime import runtime_root, usable_faction
"""Full weapon swaps, published separately from linear stat weights."""
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
from lua_data import loads
import run
import sim_progress
from build_prebis import database

BASE=runtime_root()
SEEDS=[647,11931,12592,12784,13348,13983,18420,19106,19323]
SCREEN_ITERATIONS=500
REFINE_ITERATIONS=12500

def catalog_specs(db):
    out=[]
    overrides=BASE/'source-overrides.json'
    verified={int(i) for i in json.loads(overrides.read_text(encoding='utf-8')).get('verified_routes',{})} if overrides.exists() else set()
    for item_id,item in sorted(db.items()):
        if (item.get('handType')!=4 or item.get('weaponType') not in (1,4,6,9)
            or (item.get('classAllowlist') and 2 not in item['classAllowlist'])
            or item.get('reqLvl',0)>60 or not usable_faction(item.get('factionRestriction',0))):continue
        if item.get('phase',1)!=1 and item_id not in verified:continue
        for suffix in item.get('randomSuffixOptions') or [0]:
            out.append({'id':item_id,'randomSuffix':suffix.get('id',0) if isinstance(suffix,dict) else suffix})
    return out

def lua_value(v):
    if v is None:return 'nil'
    if isinstance(v,bool):return 'true' if v else 'false'
    if isinstance(v,(int,float)):
        if not math.isfinite(v):raise ValueError('Non-finite weapon result')
        return str(v)
    if isinstance(v,str):return json.dumps(v,ensure_ascii=False)
    if isinstance(v,list):return '{'+','.join(lua_value(x) for x in v)+'}'
    return '{'+','.join('['+lua_value(k)+']='+lua_value(x) for k,x in v.items())+'}'

def full_gear(gear):
    items=copy.deepcopy(gear['items'])
    items=[x or {} for x in items]
    return {'items':(items+[{}]*17)[:17]}

def candidates(db,gear,queue):
    specs=catalog_specs(db)+[gear['items'][14]]
    specs += list(queue.values()) if isinstance(queue,dict) else queue
    out={};errors=[]
    for spec in specs:
        item_id=int(spec.get('id',0));suffix=int(spec.get('randomSuffix',0))
        item=db.get(item_id)
        if not item or item.get('handType')!=4 or item.get('weaponType') not in (1,4,6,9) or (item.get('classAllowlist') and 2 not in item['classAllowlist']):
            errors.append({'id':item_id,'reason':'Not a supported two-handed weapon'});continue
        options=item.get('randomSuffixOptions',[])
        if not suffix and (options or (spec.get('name') and spec['name']!=item['name'])):
            errors.append({'id':item_id,'reason':'The displayed random-stat variant is not verified'});continue
        suffixes={x.get('id') if isinstance(x,dict) else x for x in options}
        if suffix and suffix not in suffixes:
            errors.append({'id':item_id,'reason':'Random-stat variant is not verified by this engine'});continue
        out[f'{item_id}:{suffix}']={'id':item_id,'randomSuffix':suffix}
    return out,errors

def contexts(character,scenario):
    projected=copy.deepcopy(scenario)
    projected['target_gear']=full_gear(character['gear'])
    projected['minimum_melee_hit_percent']=0
    projected['name']='Current gear at level 60, planned Unsealed Wrath talents, raid support'
    target=copy.deepcopy(scenario);target['minimum_melee_hit_percent']=0
    if character['level']==60:
        projected['target_talents']=character['talents']
        projected['name']='Exported level-60 gear and talents, raid support'
    return [('equipped',projected),('target',target)]

def refresh(config,force=False,publish=True):
    import catalog_weapons
    return catalog_weapons.refresh(config,force,publish)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--force',action='store_true');args=parser.parse_args()
    refresh(json.loads((BASE/'config.json').read_text(encoding='utf-8')),args.force)
