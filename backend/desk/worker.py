"""Background worker: claim pending rows with SKIP LOCKED and apply verdict.

缓领规则下的认领顺序（与专页状态灯同源，均走 desk.services）：
- 每轮先 sync_hold_state() 对账，到期的缓领在此刻补写「解除」流水；
- 在缓期间只认领急补（urgent），普通（normal）保留待复核；
- 不在缓时急补、普通均可认领（急补优先）；
- 每笔结清后调用 maybe_start_hold，连续超差达阈值即开始缓领。
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


def claim_one_pending():
    from django.db import transaction

    from desk.models import OffsetSubmission
    from desk.services import (
        apply_verdict,
        maybe_start_hold,
        sync_hold_state,
    )

    # 同源对账：认领跳过与状态灯用的是同一个在缓判定。
    hold = sync_hold_state()

    with transaction.atomic():
        qs = (
            OffsetSubmission.objects.select_for_update(skip_locked=True)
            .filter(status=OffsetSubmission.Status.PENDING)
        )
        if hold["active"]:
            # 缓领中：普通停领，急补仍可领
            qs = qs.filter(priority=OffsetSubmission.Priority.URGENT)
        # 急补（urgent）字典序在普通（normal）前，始终优先认领
        submission = qs.order_by("-priority", "created_at", "id").first()
        if submission is None:
            return False

        submission.status = OffsetSubmission.Status.PROCESSING
        submission.save(update_fields=["status"])

    apply_verdict(submission)
    maybe_start_hold(submission)
    return True


def run_loop(poll_seconds: float = 0.5) -> None:
    setup_django()
    print("cnc-offset worker started", flush=True)
    while True:
        claimed = claim_one_pending()
        if not claimed:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    setup_django()
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        claim_one_pending()
    else:
        run_loop()
