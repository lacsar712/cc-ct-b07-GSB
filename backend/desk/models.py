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


class SlowdownConfig(models.Model):
    """缓领参数，单行配置：连续超差条数阈值与缓领秒数。"""

    threshold = models.PositiveIntegerField(default=2)
    cooldown_seconds = models.PositiveIntegerField(default=10)
    created_at = models.DateTimeField(auto_now_add=True)
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

    def __str__(self) -> str:
        return f"阈值{self.threshold}条 / 缓领{self.cooldown_seconds}秒"

    @classmethod
    def load(cls) -> "SlowdownConfig":
        config = cls.objects.order_by("id").first()
        if config is None:
            config = cls.objects.create(threshold=2, cooldown_seconds=10)
        return config


class SlowdownEvent(models.Model):
    """缓领起止流水。episode 相同的 start/end 为同一轮缓领。"""

    class Kind(models.TextChoices):
        START = "start", "开始"
        END = "end", "解除"

    kind = models.CharField(max_length=8, choices=Kind.choices, db_index=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    threshold_snapshot = models.PositiveIntegerField()
    cooldown_seconds_snapshot = models.PositiveIntegerField()
    until_at = models.DateTimeField(null=True, blank=True)
    episode = models.PositiveIntegerField(db_index=True)
    pair = models.OneToOneField(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paired_end",
    )
    trigger_submissions = models.ManyToManyField(
        OffsetSubmission,
        blank=True,
        related_name="slowdown_starts",
    )
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-occurred_at", "-id"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}缓领 #{self.episode}"
