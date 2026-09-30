from datetime import datetime
from typing import Optional

from django.http import HttpRequest
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError

from desk.auth_utils import bearer_auth, create_access_token, verify_password
from desk.models import OffsetSubmission, SlowdownConfig, SlowdownEvent, User
from desk.services import get_active_slowdown

api = NinjaAPI(title="数控刀补复核台", version="1.1")


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


class SlowdownConfigPatch(Schema):
    threshold: Optional[int] = None
    cooldown_seconds: Optional[int] = None


class TriggerRef(Schema):
    id: int
    tool_code: str
    offset_um: int


class SlowdownEventOut(Schema):
    id: int
    kind: str
    occurred_at: datetime
    threshold_snapshot: int
    cooldown_seconds_snapshot: int
    until_at: Optional[datetime]
    episode: int
    note: str
    trigger_submissions: list[TriggerRef]


class SlowdownConfigOut(Schema):
    threshold: int
    cooldown_seconds: int
    updated_at: datetime


class SlowdownOut(Schema):
    config: SlowdownConfigOut
    active: bool
    episode: Optional[int]
    until_at: Optional[datetime]
    remaining_seconds: int
    events: list[SlowdownEventOut]


def _event_to_out(event: SlowdownEvent) -> SlowdownEventOut:
    return SlowdownEventOut(
        id=event.id,
        kind=event.kind,
        occurred_at=event.occurred_at,
        threshold_snapshot=event.threshold_snapshot,
        cooldown_seconds_snapshot=event.cooldown_seconds_snapshot,
        until_at=event.until_at,
        episode=event.episode,
        note=event.note,
        trigger_submissions=[
            TriggerRef(id=s.id, tool_code=s.tool_code, offset_um=s.offset_um)
            for s in event.trigger_submissions.all()
        ],
    )


def _slowdown_payload() -> SlowdownOut:
    # 状态灯与认领跳过共用 get_active_slowdown()，保证同源。
    from django.utils import timezone

    config = SlowdownConfig.load()
    active = get_active_slowdown()
    now = timezone.now()
    remaining = 0
    if active is not None and active.until_at is not None:
        remaining = max(0, int((active.until_at - now).total_seconds()))
    events = SlowdownEvent.objects.prefetch_related("trigger_submissions").all()[:200]
    return SlowdownOut(
        config=SlowdownConfigOut(
            threshold=config.threshold,
            cooldown_seconds=config.cooldown_seconds,
            updated_at=config.updated_at,
        ),
        active=active is not None,
        episode=active.episode if active is not None else None,
        until_at=active.until_at if active is not None else None,
        remaining_seconds=remaining,
        events=[_event_to_out(e) for e in events],
    )


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
        raise HttpError(400, "类型只能是普通或急补")
    row = OffsetSubmission.objects.create(
        tool_code=tool_code,
        offset_um=body.offset_um,
        priority=body.priority,
        submitted_by=user,
        status=OffsetSubmission.Status.PENDING,
    )
    return _to_out(row)


@api.get("/slowdown", response=SlowdownOut, auth=bearer_auth)
def get_slowdown(request: HttpRequest):
    return _slowdown_payload()


@api.patch("/slowdown/config", response=SlowdownConfigOut, auth=bearer_auth)
def update_slowdown_config(request: HttpRequest, body: SlowdownConfigPatch):
    user: User = request.auth
    if not user.can_write:
        raise HttpError(403, "复核员只读，不能修改缓领阈值与秒数")
    if body.threshold is None and body.cooldown_seconds is None:
        raise HttpError(400, "未提供要修改的阈值或秒数")
    if body.threshold is not None and not 1 <= body.threshold <= 999:
        raise HttpError(400, "条数阈值须在 1～999 之间")
    if body.cooldown_seconds is not None and not 1 <= body.cooldown_seconds <= 86400:
        raise HttpError(400, "缓领秒数须在 1～86400 之间")

    config = SlowdownConfig.load()
    if body.threshold is not None:
        config.threshold = body.threshold
    if body.cooldown_seconds is not None:
        config.cooldown_seconds = body.cooldown_seconds
    config.updated_by = user
    config.save()
    return SlowdownConfigOut(
        threshold=config.threshold,
        cooldown_seconds=config.cooldown_seconds,
        updated_at=config.updated_at,
    )
