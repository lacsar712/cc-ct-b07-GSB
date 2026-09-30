from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("desk", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="offsetsubmission",
            name="priority",
            field=models.CharField(
                choices=[("normal", "普通"), ("urgent", "急补")],
                db_index=True,
                default="normal",
                max_length=8,
            ),
        ),
        migrations.CreateModel(
            name="SlowdownConfig",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("threshold", models.PositiveIntegerField(default=2)),
                ("cooldown_seconds", models.PositiveIntegerField(default=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="desk.user",
                    ),
                ),
            ],
            options={"verbose_name": "缓领配置"},
        ),
        migrations.CreateModel(
            name="SlowdownEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[("start", "开始"), ("end", "解除")],
                        db_index=True,
                        max_length=8,
                    ),
                ),
                ("occurred_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("threshold_snapshot", models.PositiveIntegerField()),
                ("cooldown_seconds_snapshot", models.PositiveIntegerField()),
                ("until_at", models.DateTimeField(blank=True, null=True)),
                ("episode", models.PositiveIntegerField(db_index=True)),
                (
                    "note",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "pair",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="paired_end",
                        to="desk.slowdownevent",
                    ),
                ),
                (
                    "trigger_submissions",
                    models.ManyToManyField(
                        blank=True,
                        related_name="slowdown_starts",
                        to="desk.offsetsubmission",
                    ),
                ),
            ],
            options={"ordering": ["-occurred_at", "-id"]},
        ),
    ]
