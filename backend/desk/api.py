from datetime import datetime
from typing import Optional

from django.http import HttpRequest
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError

from desk.auth_utils import bearer_auth, create_access_token, verify_password
from desk.models import HoldConfig, HoldJournal, OffsetSubmission, User
from desk.services import sync_hold_state

api = NinjaAPI(title="数控刀补复核台", version="1.0")


class HealthOut(Schema):
    status: str


class LoginIn(Schema):
    username: str
    password: str


class LoginOut(Schema):
    token: str
    username: str
    role: str
    can_write: bool


class SubmissionIn(Schema):
    tool_code: str
    offset_um: int
    priority: str = OffsetSubmission.Priority.NORMAL


class SubmissionOut(Schema):
    id: int
    tool_code: str
    offset_um: int
    priority: str
    status: str
    verdict: str
    created_at: datetime
    reviewed_at: Optional[datetime]


class HoldConfigIn(Schema):
    fail_threshold: int
    hold_seconds: int


class HoldJournalOut(Schema):
    id: int
    kind: str
    kind_label: str
    threshold_snapshot: int
    hold_seconds_snapshot: int
    streak_snapshot: int
    created_at: datetime
    planned_end_at: Optional[datetime]
    trigger_tool_code: Optional[str]


class HoldStateOut(Schema):
    active: bool
    remain_seconds: int
    fail_threshold: int
    hold_seconds: int
    streak: int
    started_at: Optional[datetime]
    planned_end_at: Optional[datetime]
    config_updated_at: datetime
    journals: list[HoldJournalOut]


def _to_out(row: OffsetSubmission) -> SubmissionOut:
    return SubmissionOut(
        id=row.id,
        tool_code=row.tool_code,
        offset_um=row.offset_um,
        priority=row.priority,
        status=row.status,
        verdict=row.verdict or "",
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


def _journal_out(row: HoldJournal) -> HoldJournalOut:
    trigger = row.trigger_submission
    return HoldJournalOut(
        id=row.id,
        kind=row.kind,
        kind_label=row.get_kind_display(),
        threshold_snapshot=row.threshold_snapshot,
        hold_seconds_snapshot=row.hold_seconds_snapshot,
        streak_snapshot=row.streak_snapshot,
        created_at=row.created_at,
        planned_end_at=row.planned_end_at,
        trigger_tool_code=trigger.tool_code if trigger else None,
    )


def _hold_payload(snapshot: dict) -> dict:
    journals = (
        HoldJournal.objects.select_related("trigger_submission")
        .order_by("-created_at", "-id")[:100]
    )
    return {
        **snapshot,
        "journals": [_journal_out(j) for j in journals],
    }


@api.get("/health", response=HealthOut)
def health(request: HttpRequest):
    return {"status": "ok"}


@api.post("/auth/login", response=LoginOut)
def login(request: HttpRequest, body: LoginIn):
    try:
        user = User.objects.get(username=body.username)
    except User.DoesNotExist:
        raise HttpError(401, "用户名或密码错误")
    if not verify_password(body.password, user.password):
        raise HttpError(401, "用户名或密码错误")
    token = create_access_token(user)
    return {
        "token": token,
        "username": user.username,
        "role": user.role,
        "can_write": user.can_write,
    }


@api.get("/submissions", response=list[SubmissionOut], auth=bearer_auth)
def list_submissions(request: HttpRequest):
    rows = OffsetSubmission.objects.all()[:200]
    return [_to_out(r) for r in rows]


@api.get("/submissions/{submission_id}", response=SubmissionOut, auth=bearer_auth)
def get_submission(request: HttpRequest, submission_id: int):
    try:
        row = OffsetSubmission.objects.get(pk=submission_id)
    except OffsetSubmission.DoesNotExist:
        raise HttpError(404, "刀补记录不存在")
    return _to_out(row)


@api.post("/submissions", response=SubmissionOut, auth=bearer_auth)
def create_submission(request: HttpRequest, body: SubmissionIn):
    user: User = request.auth
    if not user.can_write:
        raise HttpError(403, "当前账号只读，不能提交刀补")
    tool_code = body.tool_code.strip()
    if not tool_code:
        raise HttpError(400, "刀具编号不能为空")
    if body.priority not in OffsetSubmission.Priority.values:
        raise HttpError(400, "优先级只能是普通或急补")
    row = OffsetSubmission.objects.create(
        tool_code=tool_code,
        offset_um=body.offset_um,
        priority=body.priority,
        submitted_by=user,
        status=OffsetSubmission.Status.PENDING,
    )
    return _to_out(row)


@api.get("/hold", response=HoldStateOut, auth=bearer_auth)
def get_hold(request: HttpRequest):
    """缓领台状态：操作员与复核员均可看；与 worker 认领跳过同一判定来源。"""
    snapshot = sync_hold_state()
    return _hold_payload(snapshot)


@api.put("/hold/config", response=HoldStateOut, auth=bearer_auth)
def update_hold_config(request: HttpRequest, body: HoldConfigIn):
    """改阈值/秒数：仅操作员。流水只追加，旧流水保留旧快照、不追溯。"""
    user: User = request.auth
    if not user.can_write:
        raise HttpError(403, "复核员只读，不能修改缓领阈值或秒数")
    if body.fail_threshold < 1:
        raise HttpError(400, "连续超差阈值至少为 1 条")
    if body.hold_seconds < 1:
        raise HttpError(400, "缓领秒数至少为 1 秒")
    cfg = HoldConfig.load()
    cfg.fail_threshold = body.fail_threshold
    cfg.hold_seconds = body.hold_seconds
    cfg.updated_by = user
    cfg.save(update_fields=["fail_threshold", "hold_seconds", "updated_by", "updated_at"])
    snapshot = sync_hold_state()
    return _hold_payload(snapshot)
