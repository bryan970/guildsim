from guild_runtime import runtime_root, usable_faction
"""Whole-character armor, jewelry and relic comparisons for captured items."""
import copy
import hashlib
import json
import math
from pathlib import Path
import time

from build_prebis import database, WOW_SLOTS
from lua_data import loads
import run
import sim_progress
from weapon_sims import full_gear, lua_value, contexts

BASE = runtime_root()
ITERATIONS = 12500
SEEDS = [12927, 16705, 16724, 13162, 12103, 270126, 15867]
SLOTS = {**{n: [n-1] for n in range(1, 11)}, 11: [10, 11], 12: [12, 13], 14: [16]}


def item_key(spec):
    return ':'.join(str(int(spec.get(k, 0))) for k in ('id', 'randomSuffix', 'enchant'))


def planning_candidates():
    path=BASE/'prebis-targets.json'
    if not path.exists():return []
    specs=[]
    for target in json.loads(path.read_text(encoding='utf-8')).get('items',[]):
        for row in [target]+target.get('alternatives',[])[:2]:
            if row.get('id'):
                specs.append({'id':row['id'],'randomSuffix':row.get('random_suffix',0)})
    return specs


def validate(spec, db, professions):
    item = db.get(int(spec.get('id', 0)))
    if not item or item.get('type') not in SLOTS:
        return None, 'Not supported armor, jewelry or a Paladin relic'
    if item.get('classAllowlist') and 2 not in item['classAllowlist']:
        return None, 'Not usable by a Paladin'
    if item.get('reqLvl', 0) > 60:
        return None, 'Requires a level above 60'
    if not usable_faction(item.get('factionRestriction',0)):
        return None, 'Other faction only'
    if item.get('requiredProfession') and item['requiredProfession'] not in professions:
        return None, 'Requires a different profession'
    if spec.get('unsupportedVariant'):
        return None, 'Bonus-list or gem variant is not represented by this export format'
    suffix = int(spec.get('randomSuffix', 0))
    options = {x.get('id') if isinstance(x, dict) else x for x in item.get('randomSuffixOptions', [])}
    if (suffix and suffix not in options) or (not suffix and options):
        return None, 'Random-stat variant is not verified by this engine'
    if not suffix and spec.get('name') and spec['name'] != item['name']:
        return None, 'Displayed item differs from the engine item'
    return item, None


def choices_for(spec, item, gear, db):
    slots = SLOTS[item['type']]
    # An item already worn in either paired slot is the unchanged baseline.
    for slot in slots:
        if item_key(gear['items'][slot]) == item_key(spec):
            return [(slot, copy.deepcopy(gear), True)]
    choices = []
    for slot in slots:
        equipment = copy.deepcopy(gear)
        equipment['items'][slot] = {k: int(spec.get(k, 0)) for k in ('id', 'randomSuffix', 'enchant')}
        equipped = [db.get(x.get('id'), {}) for x in equipment['items'] if x.get('id')]
        if item.get('unique') and sum(x.get('id') == item['id'] for x in equipped) > 1:
            continue
        category = item.get('limitCategory', 0)
        if category and sum(x.get('limitCategory') == category for x in equipped) > item.get('limitCategoryLimit', 1):
            continue
        choices.append((slot, equipment, False))
    return choices


def refresh_queued(config, force=False, publish=True):
    record, character = run.latest(config)
    scenario = json.loads((BASE / 'scenario.json').read_text(encoding='utf-8'))
    sc = contexts(character, scenario)[0][1]
    gear = full_gear(sc['target_gear'])
    sc['target_gear'] = gear
    saved_path = Path(config['saved_variables']).with_name('GuildSimBeta.lua')
    saved = loads(saved_path.read_text(encoding='utf-8-sig')).get('GuildSimBetaDB', {}) if saved_path.exists() else {}
    queue = saved.get('itemQueue', {}).get(character['id'], {})
    queue = list(queue.values()) if isinstance(queue, dict) else list(queue)
    queue.sort(key=lambda x: x.get('lastSeen', 0), reverse=True)
    specs = queue[:160] + [{'id': i} for i in SEEDS] + planning_candidates() + gear['items']
    db = database()
    # Profession enum values match the exported names in the native request.
    profession_ids = {'Alchemy': 1, 'Blacksmithing': 2, 'Enchanting': 3, 'Engineering': 4,
                      'Herbalism': 5, 'Leatherworking': 8, 'Mining': 9, 'Skinning': 10, 'Tailoring': 11}
    professions = {profession_ids.get(x['name']) for x in character.get('professions', [])}
    candidates, errors = {}, {}
    for spec in specs:
        if not spec or not spec.get('id'):
            continue
        item, problem = validate(spec, db, professions)
        if problem:
            if int(spec.get('id', 0)) in db and db[int(spec['id'])].get('type') in SLOTS:
                errors[item_key(spec)] = problem
            continue
        candidates[item_key(spec)] = {k: int(spec.get(k, 0)) for k in ('id', 'randomSuffix', 'enchant')}
    model = json.dumps([run.model_identity(character, 'current'), sc, ITERATIONS, 1], sort_keys=True).encode()
    model += (BASE / 'retlocal.exe').read_bytes()
    fingerprint = hashlib.sha256(model).hexdigest()
    queue_fingerprint = hashlib.sha256(json.dumps([candidates, errors], sort_keys=True).encode()).hexdigest()
    state_path = BASE / 'output/items.json'
    if state_path.exists() and not force:
        previous = json.loads(state_path.read_text(encoding='utf-8'))
        if (previous.get('runId') == fingerprint and previous.get('queueFingerprint') == queue_fingerprint
                and previous.get('sourceExport') == record['data'] and (not publish or previous.get('published'))):
            text = 'local _, ns = ...\nns.itemResults = ' + lua_value(previous) + '\n'
            if publish:
                destination = Path(config['bridge_directory']) / 'ItemResults.lua'
                if not destination.exists() or destination.read_text(encoding='utf-8-sig') != text:
                    run.atomic(destination, text)
            print('Armor and jewelry unchanged; full comparisons are current.', flush=True)
            return False
    work = BASE / 'output/items' / fingerprint[:16]
    work.mkdir(parents=True, exist_ok=True)
    cache_path = work / 'cache.json'
    cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() and not force else {}
    pending=work/'pending.jsonl';previous_jobs=work/'jobs.json'
    if not force and pending.exists() and previous_jobs.exists():
        allowed={j['label'] for j in json.loads(previous_jobs.read_text(encoding='utf-8'))}
        for line in pending.read_text(encoding='utf-8').splitlines():
            try:row=json.loads(line)
            except json.JSONDecodeError:continue
            if row.get('label') in allowed and row.get('iterations',0)>=ITERATIONS:
                cache[row['label']]=row
        run.atomic(cache_path,json.dumps(cache,indent=2))
    jobs = []
    if 'baseline' not in cache:
        jobs.append({'label': 'baseline', 'equipment': gear})
    variants = {}
    for key, spec in candidates.items():
        item = db[spec['id']]
        variants[key] = choices_for(spec, item, gear, db)
        if not variants[key]:
            errors[key] = 'No legal replacement slot (unique-equipped restriction)'
        for slot, equipment, baseline in variants[key]:
            label = f'{key}@{slot}'
            if not baseline and label not in cache:
                jobs.append({'label': label, 'equipment': equipment})
    if jobs:
        run.atomic(work / 'character.json', json.dumps(run.native_character(character)))
        run.atomic(work / 'scenario.json', json.dumps(sc))
        output = work / 'pending.jsonl'
        command = [str(BASE / 'retlocal.exe'), '--root', str(BASE / 'vendor/forever-master'),
                   '--character', str(work / 'character.json'), '--scenario', str(work / 'scenario.json'),
                   '--mode', 'planning', '--iterations', str(ITERATIONS), '--workers', str(config.get('weapon_workers',4)),
                   '--batch', str(work / 'jobs.json'), '--out', str(output)]
        for index in range(0,len(jobs),32):
            _,latest=run.latest(config)
            if run.model_identity(latest,'current')!=run.model_identity(character,'current'):
                from catalog_weapons import SupersededCapture
                raise SupersededCapture('New combat capture received; switching gear and preserving completed item comparisons.')
            chunk=jobs[index:index+32]
            run.atomic(work/'jobs.json',json.dumps(chunk))
            proc = sim_progress.engine(command, cwd=BASE, log_path=work / 'engine.log',
                                       stage='Armor and jewelry — full item swaps', results_path=output,
                                       total=len(chunk),offset=index,overall_total=len(jobs))
            if proc.returncode:
                raise ValueError('Item simulations failed; previous item results preserved.')
            fresh = [json.loads(line) for line in output.read_text(encoding='utf-8').splitlines() if line.strip()]
            if {x['label'] for x in fresh} != {x['label'] for x in chunk}:
                raise ValueError('Incomplete item simulations; previous results preserved.')
            cache.update({x['label']: x for x in fresh})
            run.atomic(cache_path, json.dumps(cache, indent=2))
    baseline = cache['baseline']
    if not math.isfinite(baseline.get('dps', 0)) or baseline.get('dps', 0) <= 0:
        raise ValueError('Invalid item baseline; results not published.')
    rows = {}
    for key, spec in candidates.items():
        options = []
        for slot, _, same in variants[key]:
            result = baseline if same else cache[f'{key}@{slot}']
            if 'dps' not in result or not math.isfinite(result['dps']):
                errors[key] = result.get('error', 'Item simulation failed')
                continue
            old = gear['items'][slot]
            old_item = db.get(old.get('id'), {})
            item = db[spec['id']]
            provisional = any(x.get('procRate') and x['procRate'].get('status') != 1 for x in (item, old_item))
            options.append(dict(spec, name=item['name'], dps=result['dps'], delta=result['dps']-baseline['dps'],
                                percent=100*(result['dps']/baseline['dps']-1), inventorySlot=WOW_SLOTS[slot],
                                replacedId=old.get('id', 0), replacedName=old_item.get('name', 'empty slot'),
                                provisional=bool(provisional), secondsOom=result.get('secondsOom', 0),
                                meanError95=1.96*result['stdev']/math.sqrt(ITERATIONS)))
        # If one paired-slot run failed, don't claim the other is the best choice.
        if options and len(options) == len(variants[key]):
            best = max(options, key=lambda x: x['dps'])
            best['alternatives'] = [{'inventorySlot': x['inventorySlot'], 'dps': x['dps'], 'replacedName': x['replacedName']} for x in options]
            rows[key] = best
    payload = {'guid': character['id'], 'sourceExport': record['data'], 'generated': int(time.time()),
               'runId': fingerprint, 'queueFingerprint': queue_fingerprint, 'published': publish,
               'iterations': ITERATIONS, 'duration': sc['duration'], 'targetLevel': sc['target_level'],
               'baselineDps': baseline['dps'], 'items': rows, 'errors': errors, 'engineCommit': json.loads((BASE/'provenance.json').read_text(encoding='utf-8'))['upstream_commit']}
    text = 'local _, ns = ...\nns.itemResults = ' + lua_value(payload) + '\n'
    if publish:
        run.atomic(Path(config['bridge_directory']) / 'ItemResults.lua', text)
    run.atomic(BASE / 'addon/ItemResults.lua', text)
    run.atomic(state_path, json.dumps(payload, indent=2))
    print(f'Full item comparisons ready: {len(rows)} items, {len(jobs)} new sets; unchanged sets reused.', flush=True)
    return bool(jobs)


def refresh(config,force=False,publish=True):
    if config.get('item_catalog_mode')=='all':
        import catalog_items
        return catalog_items.refresh(config,force,publish)
    return refresh_queued(config,force,publish)


if __name__ == '__main__':
    refresh(json.loads((BASE / 'config.json').read_text(encoding='utf-8')))
