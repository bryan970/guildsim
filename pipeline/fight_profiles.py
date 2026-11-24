from guild_runtime import runtime_root, usable_faction
"""Named encounter variants grounded in the installed engine's enums."""
import copy
import json
from pathlib import Path
import re

BASE=runtime_root()


def enums(root=BASE):
    path=Path(root)/'vendor/forever-master/proto/common.proto'
    text=path.read_text(encoding='utf-8') if path.exists() else ''
    result={}
    for name in ('MobType','CreatureFamily','AreaType'):
        match=re.search(r'enum '+name+r'\s*\{(.*?)\}',text,re.S)
        result[name]={label:int(value) for label,value in re.findall(name+r'(\w+)\s*=\s*(\d+)',match.group(1) if match else '')}
    return result


def available(root=BASE):
    result={'default':{'key':'default','label':'Raid setup','target':{},'encounter':{},'group':'Default'}}
    for group,field in (('MobType','mobType'),('CreatureFamily','creatureFamily')):
        for label,value in enums(root)[group].items():
            if not value:continue
            slug=re.sub(r'(?<!^)([A-Z])',r'-\1',label).lower()
            key='undead' if group=='MobType' and label=='Undead' else ('type-' if group=='MobType' else 'family-')+slug
            pretty=re.sub(r'(?<!^)([A-Z])',r' \1',label)
            result[key]={'key':key,'label':pretty+(' family' if group=='CreatureFamily' else ''),
                'target':{field:value},'encounter':{},'group':'Creature family' if group=='CreatureFamily' else 'Creature type'}
    return result


def validate(profile,root=BASE):
    if not isinstance(profile,dict) or not isinstance(profile.get('target',{}),dict) or not isinstance(profile.get('encounter',{}),dict):
        raise ValueError('Fight profiles require target and encounter objects')
    key=profile.get('key','')
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',key):raise ValueError('Invalid fight profile key')
    known=enums(root)
    for field,value in profile.get('target',{}).items():
        enum={'mobType':'MobType','creatureFamily':'CreatureFamily'}.get(field)
        if not enum or not isinstance(value,int) or isinstance(value,bool) or value not in known[enum].values():
            raise ValueError('Unsupported fight target override: '+field)
    for field,value in profile.get('encounter',{}).items():
        if field!='areaTypes' or not isinstance(value,list) or any(not isinstance(v,int) or isinstance(v,bool) or v not in known['AreaType'].values() for v in value):
            raise ValueError('Unsupported fight encounter override: '+field)
    return copy.deepcopy(profile)


def registry(config,root=BASE):
    result=available(root)
    for profile in config.get('fight_profiles',[]):
        profile=validate(profile,root)
        if profile['key']=='default':raise ValueError('The default fight profile cannot be replaced')
        result[profile['key']]=profile
    return result


def apply(request,profile,root=BASE):
    profile=validate(profile,root)
    encounter=request['encounter']
    for target in encounter['targets']:target.update(profile.get('target',{}))
    encounter.update(profile.get('encounter',{}))
    return request


def selected(config,root=BASE):
    keys=['default']+list(config.get('fight_profiles_enabled',[]))
    path=Path(config['saved_variables']).with_name('GuildSimBeta.lua')
    if path.exists():
        from lua_data import loads
        import run,refresh_scope
        _,character=run.latest(refresh_scope.catalog_config(config))
        db=loads(path.read_text(encoding='utf-8-sig')).get('GuildSimBetaDB',{})
        keys.extend(key for key,value in db.get('fightProfileRequests',{}).get(character['id'],{}).items() if value)
    profiles=registry(config,root)
    for key in dict.fromkeys(keys):
        if key not in profiles:raise ValueError('Fight profile is not supported by this engine: '+str(key))
        yield profiles[key]
