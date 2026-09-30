from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from desk.auth_utils import hash_password
from desk.models import OffsetSubmission, SlowdownConfig, User


class Command(BaseCommand):
    help = "创建默认账号与种子刀补记录"

    def handle(self, *args, **options):
        machinist, _ = User.objects.update_or_create(
            username="machinist",
            defaults={
                "role": User.Role.MACHINIST,
                "password": hash_password("machine123456"),
                "is_active": True,
            },
        )
        User.objects.update_or_create(
            username="auditor",
            defaults={
                "role": User.Role.AUDITOR,
                "password": hash_password("audit123456"),
                "is_active": True,
            },
        )

        # 缓领机制先启用，再放置种子记录，并将其复核时间置于启用之前，
        # 使历史种子数据（T09 超差）不预置连续超差计数。
        config = SlowdownConfig.load()
        seed_time = config.created_at - timedelta(minutes=1)
        seeds = [
            ("T01", 5, OffsetSubmission.Verdict.PASS),
            ("T09", 20, OffsetSubmission.Verdict.FAIL),
        ]
        for tool_code, offset_um, verdict in seeds:
            OffsetSubmission.objects.update_or_create(
                tool_code=tool_code,
                offset_um=offset_um,
                defaults={
                    "status": OffsetSubmission.Status.DONE,
                    "verdict": verdict,
                    "submitted_by": machinist,
                    "reviewed_at": seed_time,
                },
            )

        self.stdout.write(self.style.SUCCESS("seed_offset_desk 完成"))
