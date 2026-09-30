"""Background worker: claim pending rows with SKIP LOCKED and apply verdict.

缓领语义见 desk/services.py：在缓期间普通刀补不被认领（急补照常），
连续超差达阈值自动开启缓领，秒数尽后落解除流水并恢复普通认领。
"""

import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import django


def setup_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()


def process_once():
    """先补到期解除，再认领一笔并结清；返回是否认领并处理了一笔。"""
    from desk.services import (
        claim_next_pending,
        expire_due_slowdowns,
        settle_and_maybe_trigger,
    )

    expire_due_slowdowns()
    submission = claim_next_pending()
    if submission is None:
        return False
    settle_and_maybe_trigger(submission)
    return True


def run_loop(poll_seconds: float = 0.5) -> None:
    setup_django()
    print("cnc-offset worker started", flush=True)
    while True:
        processed = process_once()
        if not processed:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    setup_django()
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        process_once()
    else:
        run_loop()
