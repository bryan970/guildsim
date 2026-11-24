from guild_runtime import runtime_root, usable_faction
"""Compact item presentation metadata; no score or DPS estimates."""
import json
from pathlib import Path


def suffix_names(root):
    path=Path(root)/'vendor/forever-master/assets/database/db.json'
    data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return {row['id']:row.get('name','') for row in data.get('randomSuffixes',[])}


def metadata(db,root):
    path=Path(root)/'vendor/forever-master/assets/database/db.json'
    data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    zones={row['id']:row['name'] for row in data.get('zones',[])}
    npcs={row['id']:row['name'] for row in data.get('npcs',[])}
    professions={1:'Alchemy',2:'Blacksmithing',3:'Enchanting',4:'Engineering',7:'Jewelcrafting',8:'Leatherworking',11:'Tailoring'}
    rows={}
    for item_id,item in db.items():
        if item.get('type') not in set(range(1,13))|{13,14}:continue
        if item.get('reqLvl',0)>60 or not usable_faction(item.get('factionRestriction',0)):continue
        if item.get('classAllowlist') and 2 not in item['classAllowlist']:continue
        if item.get('phase',1)>1:continue
        if item.get('type')==14 and item.get('rangedWeaponType')!=7:continue
        if item.get('type')==13 and (item.get('handType')!=4 or item.get('weaponType') not in (1,4,6,9)):continue
        group='Other';sources=[]
        for source in item.get('sources',[]):
            if 'quest' in source:
                row=source['quest']
                if not usable_faction(row.get('faction',0)):continue
                group='Quest';sources.append(row.get('name','Quest'))
            elif 'drop' in source:
                row=source['drop'];group='Drop'
                sources.append(' — '.join(filter(None,[npcs.get(row.get('npcId'),row.get('otherName','')),zones.get(row.get('zoneId'), '')])) or 'Drop; location unverified')
            elif 'crafted' in source:
                group='Crafted';sources.append(professions.get(source['crafted'].get('profession'),'Crafting'))
            elif 'soldBy' in source:
                row=source['soldBy'];group='Vendor'
                sources.append(' — '.join(filter(None,[row.get('npcName',npcs.get(row.get('npcId'),'')),zones.get(row.get('zoneId'),'')])) or 'Vendor')
        rows[item_id]=[item.get('type'),item.get('quality',1),item.get('icon',''),group,
            '; '.join(dict.fromkeys(sources)) or 'Acquisition source unverified',item.get('reqLvl',0),item.get('setName',''),
            [s.get('id',0) if isinstance(s,dict) else s for s in item.get('randomSuffixOptions',[])] or [0]]
    return rows
