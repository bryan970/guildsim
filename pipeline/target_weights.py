from guild_runtime import runtime_root, usable_faction
"""Explicit refresh of the separate final-farming-set reference."""
import hashlib
import json
import subprocess
import time
from pathlib import Path
import run
import sim_progress

def refresh():
    root=runtime_root()
    config=json.loads((root/'config.json').read_text(encoding='utf-8'));record,character=run.latest(config)
    out=root/'output/target-reference';out.mkdir(parents=True,exist_ok=True)
    fingerprint=hashlib.sha256((root/'retlocal.exe').read_bytes()+(root/'scenario.json').read_bytes()
        +json.dumps([character['id'],[x['name'] for x in character.get('professions',[])]],sort_keys=True).encode()).hexdigest()
    state=out/'state.json'
    previous=json.loads(state.read_text(encoding='utf-8')) if state.exists() else {}
    if previous.get('fingerprint')==fingerprint and time.time()-previous.get('created',0)<6*86400:
        source=root/'addon/TargetWeights.lua';dest=Path(config['bridge_directory'])/'TargetWeights.lua'
        if source.exists() and (not dest.exists() or dest.read_bytes()!=source.read_bytes()):run.atomic(dest,source.read_text(encoding='utf-8'))
        print('Final-target reference matches the engine and raid setup.',flush=True)
        return False
    run.atomic(out/'character.json',json.dumps(character))
    command=[str(root/'retlocal.exe'),'--root',str(root/'vendor/forever-master'),'--character',str(out/'character.json'),
        '--scenario',str(root/'scenario.json'),'--mode','planning','--iterations','12500','--out',str(out/'result.json')]
    proc=sim_progress.engine(command,cwd=root,log_path=out/'engine.log',stage='Final farming-set weights')
    if proc.returncode:raise ValueError('Final-target refresh failed; installed reference was preserved.')
    result=json.loads((out/'result.json').read_text(encoding='utf-8'));result['context']='target';result['scaleName']='Ret60 UW Planning'
    run.refresh_plan_stats(result)
    scale,_=run.pawn_scale(result)
    identity=hashlib.sha256((out/'result.json').read_bytes()).hexdigest()
    payload=run.bridge_payload(result,record,character,scale,identity).replace('ns.payload = ','ns.targetWeights = ',1)
    run.atomic(Path(config['bridge_directory'])/'TargetWeights.lua',payload);run.atomic(root/'addon/TargetWeights.lua',payload)
    run.atomic(state,json.dumps({'fingerprint':fingerprint,'created':time.time()}))
    print('Final-target reference updated. /reload, then /guildsim targetweights.')
    return True

if __name__=='__main__':refresh()
