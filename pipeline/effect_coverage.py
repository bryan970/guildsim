from guild_runtime import runtime_root, usable_faction
"""Read WoWSims' own effect gaps and conditional item metadata."""
import json
from pathlib import Path
import re

BASE=runtime_root()


def parse_missing(text):
    section=text.split('export const MISSING_ITEM_EFFECTS',1)[1].split(']);',1)[0]
    result={}
    starts=list(re.finditer(r'^\s*(\d+), // ([^\n]+)',section,re.M))
    for index,match in enumerate(starts):
        end=starts[index+1].start() if index+1<len(starts) else len(section)
        body=section[match.end():end]
        effects=[]
        for value in re.findall(r'("(?:[^"\\]|\\.)*")\s*,?\s*//',body):
            effects.append(json.loads(value))
        result[int(match.group(1))]=effects or ['Effect listed as missing by WoWSims.']
    return result


def gaps(root=None):
    root=root or BASE/'vendor/forever-master'
    path=root/'ui/sim/constants/missing_effects_auto_gen.ts'
    return parse_missing(path.read_text(encoding='utf-8-sig'))


def row_coverage(item,replaced,missing):
    affected={}
    for candidate in (item,replaced):
        if candidate.get('id') in missing:affected[candidate['id']]=missing[candidate['id']]
    return affected


def catalog_metadata(db,root=None):
    root=root or BASE/'vendor/forever-master'
    missing=gaps(root)
    registrations=(root/'sim/common/forever/stat_bonus_cds_auto_gen.go').read_text(encoding='utf-8')
    absorbs={int(value) for value in re.findall(r'NewSpellDataAbsorbOnUse\((\d+)\)',registrations)}
    conditions={}
    for item_id,item in db.items():
        notes=[]
        if item.get('creatureFamilies'):notes.append('Some effects depend on the target creature family; this setup uses an unspecified family.')
        scaling=item.get('scalingOptions',{}).get('0',{})
        if scaling.get('areaStats'):notes.append('Area-specific bonuses apply only in matching areas; this raid setup has no area bonus.')
        if scaling.get('mobTypeStats') or item.get('mobTypes'):notes.append('Creature-type bonuses require the matching target; this setup uses an unspecified creature type.')
        if item.get('itemEffects') and any(effect.get('onUse') for effect in item['itemEffects']):
            notes.append('On-use effects follow WoWSims cooldown scheduling; shared trinket cooldowns are enforced.')
        if item_id in absorbs:
            notes.append('No incoming damage is configured: survival shields are not activated and shield-break damage is not credited.')
        if notes:conditions[item_id]=notes
    return {'missingItemEffects':missing,'itemConditions':conditions}
