from guild_runtime import runtime_root, usable_faction
"""Local progress snapshots and real engine completion counts; no network server."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from atomic_files import write_text

STATUS = runtime_root() / 'output/progress.json'
_state = {}
_last_warning = 0


def update(stage, detail='', completed=None, total=None, state='running'):
    global _state, _last_warning
    now = time.time()
    if not _state or _state.get('state') != 'running':
        _state = {'started': now}
    _state.update(stage=stage, detail=detail, completed=completed, total=total,
                  state=state, updated=now, pid=os.getpid())
    try:
        write_text(STATUS,json.dumps(_state))
        return True
    except OSError as error:
        # A progress display is observational; it must never terminate the native
        # simulator, prevent valid result publication, or crash error handling.
        if now-_last_warning>=30:
            print('Progress display temporarily unavailable; simulation continues: '+str(error),file=sys.stderr,flush=True)
            _last_warning=now
        return False


def stat_count(log):
    # The engine emits a final 0/0; retain the last meaningful count until publish.
    counts = [(int(a), int(b)) for a, b in re.findall(r'Stat sims: (\d+) / (\d+)', log) if int(b) > 0]
    return counts[-1] if counts else (None, None)


def completed_rows(path):
    count = 0
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
                if isinstance(row, dict) and 'label' in row:
                    count += 1
            except json.JSONDecodeError:
                pass  # A native worker can still be writing the final line.
    except FileNotFoundError:
        pass
    return count


def engine(command, *, cwd, log_path, stage, results_path=None, total=None, offset=0, overall_total=None, bulk_progress=False, adaptive=False):
    """Poll native flushed results without blocking either pipe or changing priority."""
    if adaptive and results_path is not None and '--batch' in command:
        import smart_batch
        return smart_batch.engine(command,cwd=cwd,log_path=log_path,stage=stage,results_path=results_path,
                                  total=total,offset=offset,overall_total=overall_total)
    from smart_concurrency import Controller
    controller = Controller() if adaptive else None
    if results_path is not None:
        results_path.write_text('', encoding='utf-8')
    update(stage, 'Starting native simulator', offset if total else None, overall_total or total)
    with log_path.open('w', encoding='utf-8') as log:
        proc = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=(getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0)|getattr(subprocess,'CREATE_NO_WINDOW',0)))
        try:
            while True:
                pause=STATUS.parent/'pause.request.json'
                if pause.exists():
                    proc.terminate();proc.wait();raise InterruptedError('Paused by the guild helper; completed batches are cached.')
                if controller:
                    controller.refresh();controller.constrain(proc)
                    _state['resources']=controller.status(1)
                code = proc.poll()
                content = log_path.read_text(encoding='utf-8', errors='replace')
                if results_path is not None:
                    done = min(completed_rows(results_path), total)
                    finished=done+offset;count=overall_total or total
                    update(stage, f'{finished} of {count} item comparisons finished', finished, count)
                elif bulk_progress:
                    counts = re.findall(r'Bulk progress: (\d+) / (\d+); stage (\w+)', content)
                    meaningful = [(int(a), int(b), label) for a, b, label in counts if int(b) > 0]
                    done, count, native_stage = meaningful[-1] if meaningful else (None, None, 'Starting')
                    update(stage, f'{native_stage}: {done} of {count} native iterations' if count else 'WoWSims is preparing comparisons', done, count)
                else:
                    done, count = stat_count(content)
                    detail = f'{done} of {count} stat simulations finished' if count else 'Computing baseline DPS'
                    update(stage, detail, done, count)
                if code is not None:
                    break
                time.sleep(.5)
        except BaseException:
            proc.terminate()
            proc.wait()
            raise
    content = log_path.read_text(encoding='utf-8', errors='replace')
    return subprocess.CompletedProcess(command, code, '', content)
