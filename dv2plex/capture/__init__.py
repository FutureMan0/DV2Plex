"""
Capture of MiniDV tapes over FireWire with dvgrab.

- engine.py       CaptureEngine: one capture from start to the queued merge
- dvgrab.py       device detection, command lines, the dvgrab processes, sudo
- preview.py      live preview from the clips being written
- merge_queue.py  merges captured tapes one after another in the background
- processes.py    stopping and reading child processes on every platform
"""

from .engine import CaptureEngine
from .merge_queue import MergeJob, MergeQueue
from .processes import default_use_sudo, interrupt_process

__all__ = ["CaptureEngine", "MergeJob", "MergeQueue", "default_use_sudo", "interrupt_process"]
