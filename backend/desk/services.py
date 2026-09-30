"""缓领领域服务。

唯一判定口径：`get_active_slowdown()` —— worker 认领是否跳过普通刀补、
API 专页状态灯是否点亮，都必须调用它，不得各写一份判断。

触发规则：最近结清（已完成）的刀补若构成「连续超差」且条数达到当前阈值，
开启一轮缓领，记录开始流水；缓领秒数内普通刀补不被认领，急补照常认领。
秒数尽后由 worker 认领事务写入解除流水。阈值/秒数在流水上留存快照，
事后修改不追溯旧流水；连续超差的统计区间为上一轮解除之后（首轮为缓领机制
启用、即配置建立之后），中间出现合格即打断计数。
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from desk.models import OffsetSubmission, SlowdownConfig, SlowdownEvent


def evaluate_verdict(offset_um: int) -> str:
    if abs(offset_um) <= settings.OFFSET_TOLERANCE_UM:
        return OffsetSubmission.Verdict.PASS
    return OffsetSubmission.Verdict.FAIL


def apply_verdict(submission: OffsetSubmission) -> None:
    submission.verdict = evaluate_verdict(submission.offset_um)
    submission.status = OffsetSubmission.Status.DONE
    submission.reviewed_at = timezone.now()
    submission.save(
        update_fields=["verdict", "status", "reviewed_at"],
    )


def _lock_config() -> SlowdownConfig:
    """锁定配置单例行，串行化认领与触发判定（多行锁顺序固定为 配置→开始流水）。"""
    config = SlowdownConfig.objects.select_for_update().order_by("id").first()
    if config is None:
        config = SlowdownConfig.objects.create(threshold=2, cooldown_seconds=10)
    return config


def get_active_slowdown(now=None):
    """返回当前生效中的缓领开始流水；未在缓（含已到期但解除流水未落库的瞬间）返回 None。

    这是「是否在缓」的唯一口径：认领跳过普通刀补与专页状态灯同源。
    """
    now = now or timezone.now()
    start = (
        SlowdownEvent.objects.filter(
            kind=SlowdownEvent.Kind.START,
            paired_end__isnull=True,
        )
        .order_by("-episode", "-id")
        .first()
    )
    if start is None:
        return None
    if start.until_at is not None and start.until_at <= now:
        return None
    return start


def _expire_due_slowdown(now) -> SlowdownEvent | None:
    """秒数已尽则补写解除流水（调用方须持有事务与配置行锁）。"""
    start = (
        SlowdownEvent.objects.select_for_update()
        .filter(kind=SlowdownEvent.Kind.START, paired_end__isnull=True)
        .order_by("-episode", "-id")
        .first()
    )
    if start is None:
        return None
    if start.until_at is None or start.until_at > now:
        return None
    return SlowdownEvent.objects.create(
        kind=SlowdownEvent.Kind.END,
        episode=start.episode,
        threshold_snapshot=start.threshold_snapshot,
        cooldown_seconds_snapshot=start.cooldown_seconds_snapshot,
        until_at=None,
        pair=start,
        note="缓领秒数到期，自动解除",
    )


def _window_start():
    """连续超差统计起点：最近一轮解除时间；从未解除过则为缓领机制启用（配置建立）时间。

    这样机制启用前已结清的历史/种子记录不会预置连续超差计数。
    """
    end = (
        SlowdownEvent.objects.filter(kind=SlowdownEvent.Kind.END)
        .order_by("-occurred_at", "-id")
        .first()
    )
    if end is not None:
        return end.occurred_at
    return SlowdownConfig.load().created_at


def consecutive_fail_run(now=None) -> list[int]:
    """最近结清流水中末尾连续超差的记录 id（时间范围：统计起点之后）。"""
    qs = OffsetSubmission.objects.filter(
        status=OffsetSubmission.Status.DONE,
        reviewed_at__gt=_window_start(),
    ).order_by("-reviewed_at", "-id")
    ids: list[int] = []
    for row in qs.only("id", "verdict"):
        if row.verdict == OffsetSubmission.Verdict.FAIL:
            ids.append(row.id)
        elif row.verdict == OffsetSubmission.Verdict.PASS:
            break
    return ids


def expire_due_slowdowns(now=None) -> SlowdownEvent | None:
    """无认领动作时单独推进到期解除（worker 空转轮次调用）。"""
    now = now or timezone.now()
    with transaction.atomic():
        _lock_config()
        return _expire_due_slowdown(now)


def claim_next_pending(now=None):
    """认领一笔待复核：在缓期间只领急补，普通刀补跳过。

    同一事务内先做到期解除（保证秒数一到即落解除流水），再按同源口径认领。
    返回被认领（已置复核中）的记录；无可认领返回 None。
    """
    now = now or timezone.now()
    with transaction.atomic():
        _lock_config()
        _expire_due_slowdown(now)
        active = get_active_slowdown(now)

        candidates = (
            OffsetSubmission.objects.select_for_update(skip_locked=True)
            .filter(status=OffsetSubmission.Status.PENDING)
        )
        if active is not None:
            candidates = candidates.filter(priority=OffsetSubmission.Priority.URGENT)
        submission = candidates.order_by("created_at", "id").first()
        if submission is None:
            return None
        submission.status = OffsetSubmission.Status.PROCESSING
        submission.save(update_fields=["status"])
        return submission


def settle_and_maybe_trigger(submission: OffsetSubmission, now=None):
    """结清一笔刀补；若因此达到连续超差阈值则开启缓领。返回开始流水（未触发为 None）。"""
    apply_verdict(submission)
    now = now or timezone.now()
    with transaction.atomic():
        config = _lock_config()
        # 结清瞬间也可能恰逢到期，先补齐解除流水再做判定。
        _expire_due_slowdown(now)
        if get_active_slowdown(now) is not None:
            return None
        fail_ids = consecutive_fail_run(now)
        if len(fail_ids) < config.threshold or config.threshold <= 0:
            return None
        episode = SlowdownEvent.objects.aggregate(value=Max("episode"))["value"] or 0
        next_episode = episode + 1
        until_at = now + timedelta(seconds=config.cooldown_seconds)
        start = SlowdownEvent.objects.create(
            kind=SlowdownEvent.Kind.START,
            episode=next_episode,
            threshold_snapshot=config.threshold,
            cooldown_seconds_snapshot=config.cooldown_seconds,
            until_at=until_at,
            note="最近结清连续超差达到阈值，自动缓领",
        )
        start.trigger_submissions.set(fail_ids[: config.threshold])
        return start
