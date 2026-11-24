from guild_runtime import runtime_root, usable_faction
"""Translate cached single-swap jobs to the unmodified WoWSims bulk API."""
import copy
import hashlib
import json
import math
from pathlib import Path

import run
import sim_progress

BASE = runtime_root()
CHUNK = 8


def backend_identity(config):
    if config.get('comparison_backend') != 'wowsims-bulk':
        return 'legacy'
    binary = BASE / 'retbulk.exe'
    if not binary.is_file():
        raise ValueError('WoWSims bulk bridge is missing; installed results preserved.')
    return hashlib.sha256(binary.read_bytes()).hexdigest()


def make_request(result, character, scenario, jobs, reference_pair=None, fight_profile=None):
    source=run.reference_character(result['export'],reference_pair) if reference_pair else result['export']
    if run.model_identity(source, 'current') != run.model_identity(character, 'current'):
        raise ValueError('Stat request and current capture differ; refusing mixed-model bulk results.')
    request = copy.deepcopy(result['request'])
    player = request['raid']['parties'][0]['players'][0]
    player['equipment'] = copy.deepcopy(scenario['target_gear'])
    if scenario.get('target_talents'):
        player['talentsString'] = scenario['target_talents']
    # Settings stay attached to the prepared, validated stat-weight request.
    if request['encounter']['duration'] != scenario['duration'] or int(request['encounter']['targets'][0]['level']) != scenario['target_level']:
        raise ValueError('Encounter and prepared WoWSims request differ.')
    request['simOptions']['saveAllValues'] = True
    if fight_profile:
        import fight_profiles
        fight_profiles.apply(request,fight_profile,BASE)
    return {'baseRequest': request, 'allResults': True,
            'candidates': [{'index': i, 'gear': job['equipment']} for i, job in enumerate(jobs)]}


def decode_result(raw, jobs):
    if (raw.get('error') or {}).get('message'):
        raise ValueError(raw['error']['message'])
    baseline = raw.get('baseline', {}).get('dpsMetrics', {})
    if not math.isfinite(baseline.get('avg', 0)) or baseline.get('avg', 0) <= 0:
        raise ValueError('Invalid WoWSims bulk baseline.')
    seen = set(); rows = {}
    for result in raw.get('topResults', []):
        index = int(result.get('candidateIndex', 0))
        if index in seen or not 0 <= index < len(jobs):
            raise ValueError('Duplicate or unexpected WoWSims bulk candidate index.')
        seen.add(index)
        if result.get('gear') != jobs[index]['equipment']:
            # Proto JSON emits empty/default fields absent from input specs.
            def canonical(gear):
                return [{k: int(item.get(k, 0)) for k in ('id', 'randomSuffix', 'enchant')} for item in gear['items']]
            if canonical(result['gear']) != canonical(jobs[index]['equipment']):
                raise ValueError('WoWSims returned a different equipment set.')
        metrics = result['dpsMetrics']
        count = int(metrics.get('aggregatorData', {}).get('n', 0))
        avg = metrics.get('avg', 0); stdev = metrics.get('stdev', -1)
        paired = result.get('pairedErrorToBaseline', 0)
        if count < 10000 or not all(math.isfinite(v) for v in (avg, stdev, paired)) or avg <= 0 or stdev < 0 or paired < 0:
            raise ValueError('Invalid WoWSims bulk metrics or iteration count.')
        # Paired error is valid only for the baseline from this same native run.
        rows[jobs[index]['label']] = {'label': jobs[index]['label'], 'dps': avg, 'stdev': stdev,
            'iterations': count, 'comparisonBaselineDps': baseline['avg'], 'pairedError95': 1.96 * paired,
            'backend': 'wowsims-bulk'}
    if len(seen) != len(jobs):
        raise ValueError('Incomplete WoWSims bulk results; previous results preserved.')
    return rows


def refine(config, character, scenario, jobs, work, before_batch=None):
    result = json.loads((BASE / 'output/result.json').read_text(encoding='utf-8'))
    identity = backend_identity(config)
    rows = {}
    chunk_size=max(1,min(CHUNK,config.get('bulk_chunk_size',CHUNK)))
    for offset in range(0, len(jobs), chunk_size):
        if before_batch:
            before_batch()
        chunk = jobs[offset:offset + chunk_size]
        request = make_request(result, character, scenario, chunk,
            config.get('catalog_reference_trinkets') if config.get('_catalog_reference') else None,
            config.get('_fight_profile'))
        digest = hashlib.sha256((json.dumps(request, sort_keys=True) + identity).encode()).hexdigest()
        directory = work / 'native-bulk' / digest[:24]
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / 'result.json'
        if output.exists():
            decoded = decode_result(json.loads(output.read_text(encoding='utf-8')), chunk)
        else:
            run.atomic(directory / 'request.json', json.dumps(request))
            pending = directory / 'pending.json'
            process = sim_progress.engine([str(BASE / 'retbulk.exe'), '--request', str(directory / 'request.json'),
                '--out', str(pending), '--workers', str(config.get('weapon_workers', 4))], cwd=BASE,
                log_path=directory / 'engine.log', stage=f'{config.get("bulk_stage_label","WoWSims bulk comparisons")} - batch {offset // chunk_size + 1}/{math.ceil(len(jobs) / chunk_size)}',
                bulk_progress=True,adaptive=config.get('smart_concurrency',False))
            if process.returncode:
                raise ValueError('Native WoWSims bulk failed; completed batches and installed comparisons preserved. See ' + str(directory / 'engine.log'))
            decoded = decode_result(json.loads(pending.read_text(encoding='utf-8')), chunk)
            pending.replace(output)
        rows.update(decoded)
        print(f'WoWSims native bulk: {offset + len(chunk)}/{len(jobs)} final comparisons cached.', flush=True)
    return rows
