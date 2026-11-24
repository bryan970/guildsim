"""Run the existing full Ret workflow in one isolated character process."""
import json
import os
from pathlib import Path

def execute(workspace,full=False,target=False):
    os.environ['GUILDSIM_WORKSPACE']=str(Path(workspace).resolve())
    config=json.loads((Path(workspace)/'config.json').read_text(encoding='utf-8'))
    os.environ['GUILDSIM_RACE']=config['character_race']
    import run,sim_progress,weapon_sims,item_sims,trinket_pairs,target_weights,refresh_scope
    import addon_maintenance
    addon_maintenance.reconcile(config)
    sim_progress.update('Checking character','Loading saved capture and native caches')
    run.run(config)
    weapon_sims.refresh(config)
    item_sims.refresh(config)
    trinket_pairs.refresh(config)
    target_weights.refresh()
    if full:
        complete=dict(config,refresh_scope='all')
        weapon_sims.refresh(complete);item_sims.refresh(complete);trinket_pairs.refresh(complete)
    sim_progress.update('Ready to reload','All results saved. Use /reload to load them.',state='ready')
    return 0
