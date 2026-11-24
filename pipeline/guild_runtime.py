"""Per-character writable state, separate from immutable installed release files."""
import os
from pathlib import Path

def runtime_root():
    value=os.environ.get('GUILDSIM_WORKSPACE')
    return Path(value).resolve() if value else Path(__file__).resolve().parent

def usable_faction(restriction):
    race=os.environ.get('GUILDSIM_RACE','Undead')
    return int(restriction or 0) not in ({1} if race=='Undead' else {2})
