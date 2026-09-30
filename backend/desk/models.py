from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        MACHINIST = "machinist", "操作员"
        AUDITOR = "auditor", "复核员"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MACHINIST,
    )

    @property
    def can_write(self) -> bool:
        return self.role == self.Role.MACHINIST


class OffsetSubmission(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待复核"
        PROCESSING = "processing", "复核中"
        DONE = "done", "已完成"

    class Verdict(models.TextChoices):
        PASS = "合格", "合格"
        FAIL = "超差", "超差"

    class Priority(models.TextChoices):
        NORMAL = "normal", "普通"
        URGENT = "urgent", "急补"

    tool_code = models.CharField(max_length=32, db_index=True)
    offset_um = models.IntegerField()
    priority = models.CharField(
        max_length=8,
        choices=Priority.choices,
        default=Priority.NORMAL,
        db_index=True,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    verdict = models.CharField(
        max_length=8,
        choices=Verdict.choices,
        blank=True,
        default="",
    )
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submissions",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.tool_code} {self.offset_um}µm"


class HoldConfig(models.Model):
    """缓领配置（全台单例）：连续超差达阈值条即进入缓领。"""

    fail_threshold = models.PositiveIntegerField(default=2)
    hold_seconds = models.PositiveIntegerField(default=30)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "缓领配置"
        verbose_name_plural = verbose_name

    @classmethod
    def load(cls) -> "HoldConfig":
        obj = cls.objects.filter(pk=1).first()
        if obj is None:
            obj = cls.objects.create(pk=1)
        return obj

    def __str__(self) -> str:
        return f"阈值{self.fail_threshold}条/缓领{self.hold_seconds}秒"


class HoldJournal(models.Model):
    """缓领起止流水，追加写。配置快照在写入时固化，事后改阈值不追溯。"""

    class Kind(models.TextChoices):
        START = "start", "开始"
        END = "end", "解除"

    kind = models.CharField(max_length=8, choices=Kind.choices)
    threshold_snapshot = models.PositiveIntegerField()
    hold_seconds_snapshot = models.PositiveIntegerField()
    streak_snapshot = models.PositiveIntegerField()
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # 开始流水的计划解除时刻；与 end 行 created_at 互为印证
    planned_end_at = models.DateTimeField(null=True, blank=True)
    trigger_submission = models.ForeignKey(
        OffsetSubmission,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.created_at:%Y-%m-%d %H:%M:%S}"
