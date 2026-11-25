"""Build public data only. Never copy account exports or personal config."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

HERE=Path(__file__).parent
ENGINE=HERE/'engine/upstream'
DEST=HERE/'bundle'

def run():
    if not (DEST/'addons/WowSimsExporter').exists():
        exporter=os.environ.get('GUILDSIM_EXPORTER_SOURCE')
        if not exporter:raise ValueError('Provide the official exporter package through GUILDSIM_EXPORTER_SOURCE.')
        shutil.copytree(Path(exporter), DEST/'addons/WowSimsExporter',ignore=shutil.ignore_patterns('.git','.github','node_modules','__pycache__'))
    sys.path.insert(0,str(HERE/'pipeline'))
    spec=importlib.util.spec_from_file_location('coverage_source',HERE/'pipeline/effect_coverage.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    missing=module.gaps(ENGINE)
    data=json.loads((ENGINE/'assets/database/db.json').read_text(encoding='utf-8'))
    npcs={i['id']:i['name'] for i in data.get('npcs',[])};zones={i['id']:i['name'] for i in data.get('zones',[])}
    professions={1:'Alchemy',2:'Blacksmithing',3:'Enchanting',4:'Engineering',8:'Leatherworking',11:'Tailoring'}
    items={}
    keys=('id','name','icon','type','armorType','weaponType','handType','rangedWeaponType','quality','phase','reqLvl','factionRestriction','classAllowlist','requiredProfession','unique','limitCategory','setName','randomSuffixOptions','mobTypes','creatureFamilies')
    for item in data['items']:
        if item.get('type',0) not in range(1,15):continue
        sources=[]
        for source in item.get('sources',[]):
            for key,row in source.items():
                if key=='quest':sources.append(row.get('name','Quest'))
                elif key=='crafted':sources.append(professions.get(row.get('profession'),'Crafting'))
                elif key=='drop':sources.append(' — '.join(filter(None,[npcs.get(row.get('npcId'),row.get('otherName','')),zones.get(row.get('zoneId'),'')])) or 'Drop; source unverified')
                elif key=='soldBy':sources.append(' — '.join(filter(None,[row.get('npcName',npcs.get(row.get('npcId'),'')),zones.get(row.get('zoneId'),'')])) or 'Vendor')
        items[str(item['id'])]={k:item[k] for k in keys if k in item}
        items[str(item['id'])]['source']='; '.join(dict.fromkeys(sources)) or 'Acquisition source unverified'
        if item['id'] in missing:items[str(item['id'])]['missingEffects']=missing[item['id']]
    (DEST/'items.json').write_text(json.dumps(items,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (DEST/'suffixes.json').write_text(json.dumps({r['id']:r['name'] for r in data.get('randomSuffixes',[])},ensure_ascii=False),encoding='utf-8')
    licenses=DEST/'licenses';licenses.mkdir(exist_ok=True)
    shutil.copy2(ENGINE/'LICENSE',licenses/'WoWSims-Forever-MIT.txt')
    shutil.copy2(DEST/'addons/WowSimsExporter/LICENSE',licenses/'WowSimsExporter-MIT.txt')
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.exists():shutil.copy2(python_license,licenses/'Python.txt')
    print(f'Prepared {len(items)} public item records; no character exports copied.')

def manifest(base):
    files={p.relative_to(base).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in base.rglob('*') if p.is_file() and p.name!='manifest.json' and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    (base/'manifest.json').write_text(json.dumps({'version':'0.2.0-beta.2','engineVersion':'v1.0.4','engineCommit':'a8bd7fd83a3a7c5102012ed87d86a71d175b3a89','files':files},indent=2),encoding='utf-8')

if __name__=='__main__':run();manifest(DEST)
