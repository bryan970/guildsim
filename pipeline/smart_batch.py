from guild_runtime import runtime_root, usable_faction
"""Run small cached-queue segments with adaptive native process concurrency."""
import json
from pathlib import Path
import subprocess
import tempfile
import time

import sim_progress
from smart_concurrency import Controller


def engine(command, *, cwd, log_path, stage, results_path, total, offset=0, overall_total=None, **unused):
    jobs = json.loads(Path(command[command.index('--batch') + 1]).read_text(encoding='utf-8'))
    controller = Controller(); active = []; completed = []; logs = []
    results_path.write_text('', encoding='utf-8')
    chunks = [jobs[i:i + 16] for i in range(0, len(jobs), 16)]
    with tempfile.TemporaryDirectory(prefix='sim-workers-', dir=log_path.parent) as temporary:
        root = Path(temporary); next_chunk = 0
        try:
            while next_chunk < len(chunks) or active:
                budget = controller.refresh()
                while next_chunk < len(chunks) and len(active) < max(1, budget // 4):
                    index = next_chunk; next_chunk += 1
                    job_path = root / f'{index}.json'; output = root / f'{index}.jsonl'; log = root / f'{index}.log'
                    job_path.write_text(json.dumps(chunks[index]), encoding='utf-8')
                    child = list(command)
                    for flag, value in [('--batch', job_path), ('--out', output), ('--workers', min(4, budget))]:
                        child[child.index(flag) + 1] = str(value)
                    stream = log.open('w', encoding='utf-8')
                    process = subprocess.Popen(child, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                        creationflags=(getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0)|getattr(subprocess,'CREATE_NO_WINDOW',0)))
                    active.append((process, output, log, stream, chunks[index]))
                visible = len(completed)
                for task in list(active):
                    process, output, log, stream, chunk = task
                    controller.constrain(process)
                    code = process.poll()
                    if code is None:
                        visible += sim_progress.completed_rows(output)
                        continue
                    stream.close(); content = log.read_text(encoding='utf-8', errors='replace'); logs.append(content)
                    if code:
                        log_path.write_text('\n'.join(logs), encoding='utf-8')
                        return subprocess.CompletedProcess(command, code, '', content)
                    rows = [json.loads(line) for line in output.read_text(encoding='utf-8').splitlines() if line.strip()]
                    if {row['label'] for row in rows} != {job['label'] for job in chunk}:
                        raise ValueError('Incomplete parallel simulator segment; installed results preserved.')
                    completed.extend(rows); visible += len(rows); active.remove(task)
                    # Flush whole rows so the existing progress reader sees real completions.
                    results_path.write_text('\n'.join(json.dumps(row) for row in completed) + '\n', encoding='utf-8')
                sim_progress._state['resources'] = controller.status(len(active))
                sim_progress.update(stage, f'{offset + visible} of {overall_total or total} comparisons; CPU budget {budget}, {len(active)} native processes',
                                    offset + visible, overall_total or total)
                if active:
                    time.sleep(.25)
        finally:
            for process, _, _, stream, _ in active:
                if process.poll() is None:
                    process.terminate(); process.wait()
                stream.close()
    log_path.write_text('\n'.join(logs), encoding='utf-8')
    return subprocess.CompletedProcess(command, 0, '', '\n'.join(logs))
