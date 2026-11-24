from guild_runtime import runtime_root, usable_faction
"""Summarize native item coverage without treating database presence as effect support."""
import json
from pathlib import Path
import time

from atomic_files import write_text
from build_prebis import database
import effect_coverage

BASE=runtime_root()


def report():
    db=database();metadata=effect_coverage.catalog_metadata(db)
    provenance=json.loads((BASE/'provenance.json').read_text(encoding='utf-8'))
    coverage_path=BASE/'output/equipment-catalog-coverage.json'
    coverage=json.loads(coverage_path.read_text(encoding='utf-8')) if coverage_path.exists() else {}
    missing=[]
    for row in coverage.get('sourceIdsMissingFromEngine',[]):
        missing.append(dict(row,sameNameEngineIds=[key for key,item in db.items() if item['name']==row['name']]))
    trinkets=[]
    for key,item in sorted(db.items()):
        if item.get('type')!=12:continue
        proc=item.get('procRate')
        trinkets.append({'id':key,'name':item['name'],'missingEffects':metadata['missingItemEffects'].get(key,[]),
                        'procRate':proc,'provisionalProc':bool(proc and proc.get('status')!=1),
                        'conditions':metadata['itemConditions'].get(key,[])})
    result={'generated':int(time.time()),'wowsims':provenance,'compatibleEquipmentBaseItems':coverage.get('compatibleEngineBaseItems'),
            'compatibleEquipmentVariants':coverage.get('engineVariants'),
            'upstreamMissingEffectItems':len(metadata['missingItemEffects']),
            'upstreamMissingEffectTrinkets':sum(bool(row['missingEffects']) for row in trinkets),
            'sourceIdsMissingFromEngine':missing,'trinkets':trinkets,
            'limits':['Database presence does not prove every effect is implemented.',
                      'Tooltips and rankings suppress confident upgrade arrows for upstream missing effects or provisional proc rates.',
                      'Current raid setup has an unspecified creature type/family, no area bonus, and no incoming damage.',
                      'Comparisons replace one item and test both legal trinket slots; they do not optimize all trinket pairs.',
                      'Historical farming-set optimization predates the current engine. A refreshed target weight is not a new global set optimization.',
                      'Quick refresh updates equipped, bag, pinned, and farming-target comparisons. Full catalog requires its explicit desktop action.']}
    write_text(BASE/'output/catalog-health.json',json.dumps(result,indent=2))
    return result


if __name__=='__main__':
    result=report()
    print(json.dumps({key:value for key,value in result.items() if key not in ('trinkets','sourceIdsMissingFromEngine','wowsims')},indent=2))
