"""缓领领域服务。

「是否在缓」只有一个判定入口（hold_snapshot / sync_hold_state）：
worker 认领前与专页状态灯读的是同一段逻辑、同一份流水，不允许各算各的。

规则：
- 连续超差 = 锚点之后最近结清（DONE）序列末尾、中间未夹合格的超差条数；
  锚点取最近一次「解除」流水（无解除则取最近一次「开始」，再无则为系统起点），
  即一次缓领结清旧账，解除后计数从零重新累计；
- 一笔超差结清且当前不在缓、连续数达到阈值 -> 写「开始」流水并进入缓领；
- 在缓期间 worker 只认领急补，普通跳过；
- 到达开始流水上的计划解除时刻 -> 惰性补写「解除」流水（worker 轮询或专页读取时），
  普通随即恢复认领；
- 流水只追加，并快照当时的阈值/秒数，事后改配置不追溯旧流水。
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from desk.models import HoldConfig, HoldJournal, OffsetSubmission


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


def _streak_anchor():
    """计数窗口起点：最近解除流水优先，否则最近开始流水，都没有则 None（全量）。"""
    end = HoldJournal.objects.filter(kind=HoldJournal.Kind.END).order_by(
        "-created_at", "-id"
    ).values("created_at", "id").first()
    if end is not None:
        return end
    start = HoldJournal.objects.filter(kind=HoldJournal.Kind.START).order_by(
        "-created_at", "-id"
    ).values("created_at", "id").first()
    return start


def consecutive_fail_count() -> int:
    """锚点之后、结清序列末尾的连续超差条数（按结清时刻 reviewed_at, id 排序）。

    锚点之后夹过一条合格即断开；锚点之前的旧超差由上一次缓领结清，不再计数。
    """
    from django.db.models import Q

    fails = OffsetSubmission.objects.filter(
        status=OffsetSubmission.Status.DONE,
        verdict=OffsetSubmission.Verdict.FAIL,
    )
    anchor = _streak_anchor()
    if anchor is not None:
        # 锚点流水时刻之后结清的记录才计入
        fails = fails.filter(reviewed_at__gt=anchor["created_at"])
    last_pass = (
        OffsetSubmission.objects.filter(
            status=OffsetSubmission.Status.DONE,
            verdict=OffsetSubmission.Verdict.PASS,
        )
        .order_by("-reviewed_at", "-id")
        .values("reviewed_at", "id")
        .first()
    )
    if last_pass is not None:
        # 只保留严格晚于窗口内最近一条合格的超差，保证「连续」
        fails = fails.filter(
            Q(reviewed_at__gt=last_pass["reviewed_at"])
            | Q(reviewed_at=last_pass["reviewed_at"], id__gt=last_pass["id"])
        )
    return fails.count()


def _latest_journal() -> HoldJournal | None:
    return HoldJournal.objects.order_by("-created_at", "-id").first()


def _build_snapshot(cfg: HoldConfig, now) -> dict:
    last = (
        HoldJournal.objects.select_related("trigger_submission")
        .order_by("-created_at", "-id")
        .first()
    )
    active = bool(
        last
        and last.kind == HoldJournal.Kind.START
        and last.planned_end_at is not None
        and now < last.planned_end_at
    )
    remain_seconds = 0
    if active:
        remain_seconds = max(
            0, int((last.planned_end_at - now).total_seconds() + 0.999999)
        )
    return {
        "active": active,
        "started_at": last.created_at if active else None,
        "planned_end_at": last.planned_end_at if active else None,
        "remain_seconds": remain_seconds,
        "fail_threshold": cfg.fail_threshold,
        "hold_seconds": cfg.hold_seconds,
        "config_updated_at": cfg.updated_at,
        "streak": consecutive_fail_count(),
        "latest_kind": last.kind if last else "",
    }


def sync_hold_state(now=None) -> dict:
    """同源对账：到期则在同一把锁内补写「解除」流水，再返回最新快照。

    worker 每轮认领前与专页 GET /hold 都调这里，保证
    「认领跳过普通」与「状态灯显示在缓」永不分叉。
    配置单例行充当全局串行锁，避免多 worker 重复写解除流水。
    """
    now = now or timezone.now()
    with transaction.atomic():
        cfg = HoldConfig.load()
        HoldConfig.objects.select_for_update().get(pk=cfg.pk)
        last = _latest_journal()
        if (
            last is not None
            and last.kind == HoldJournal.Kind.START
            and last.planned_end_at is not None
            and now >= last.planned_end_at
        ):
            HoldJournal.objects.create(
                kind=HoldJournal.Kind.END,
                threshold_snapshot=last.threshold_snapshot,
                hold_seconds_snapshot=last.hold_seconds_snapshot,
                streak_snapshot=last.streak_snapshot,
            )
        cfg = HoldConfig.objects.get(pk=cfg.pk)
        return _build_snapshot(cfg, now)


def maybe_start_hold(
    submission: OffsetSubmission, *, now=None
) -> HoldJournal | None:
    """一笔记录结清后调用：若它是超差、当前不在缓且连续超差达阈值，则开始缓领。"""
    if submission.verdict != OffsetSubmission.Verdict.FAIL:
        return None
    now = now or timezone.now()
    with transaction.atomic():
        cfg = HoldConfig.load()
        HoldConfig.objects.select_for_update().get(pk=cfg.pk)
        last = _latest_journal()
        if last is not None and last.kind == HoldJournal.Kind.START:
            # 已在缓（含已到期但尚未对账）：不嵌套、不重开
            return None
        streak = consecutive_fail_count()
        if streak < cfg.fail_threshold:
            return None
        return HoldJournal.objects.create(
            kind=HoldJournal.Kind.START,
            threshold_snapshot=cfg.fail_threshold,
            hold_seconds_snapshot=cfg.hold_seconds,
            streak_snapshot=streak,
            planned_end_at=now + timedelta(seconds=cfg.hold_seconds),
            trigger_submission=submission,
        )
