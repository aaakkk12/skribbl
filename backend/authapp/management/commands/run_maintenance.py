from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
import shutil

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Count, Q
from django.utils import timezone
import redis

from realtime.models import Room
from realtime.lifecycle import cleanup_inactive_rooms


User = get_user_model()


class Command(BaseCommand):
    help = (
        "Runs periodic maintenance: delete inactive accounts, cleanup stale rooms, "
        "and keep runtime storage under budget."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--inactive-days",
            type=int,
            default=getattr(settings, "INACTIVE_ACCOUNT_DAYS", 7),
            help="Delete users inactive for N days (default from settings).",
        )
        parser.add_argument(
            "--room-retention-days",
            type=int,
            default=getattr(settings, "INACTIVE_ROOM_RETENTION_DAYS", 14),
            help="Delete empty stale rooms older than N days.",
        )
        parser.add_argument(
            "--empty-room-minutes",
            type=int,
            default=getattr(settings, "EMPTY_ROOM_DELETE_MINUTES", 10),
            help="Delete rooms that stayed empty for N minutes.",
        )
        parser.add_argument(
            "--max-storage-gb",
            type=float,
            default=float(getattr(settings, "STORAGE_MAX_GB", 20)),
            help="Hard limit where aggressive cleanup starts.",
        )
        parser.add_argument(
            "--target-storage-gb",
            type=float,
            default=float(getattr(settings, "STORAGE_TARGET_GB", 15)),
            help="Target storage after cleanup.",
        )
        parser.add_argument(
            "--log-retention-days",
            type=int,
            default=int(getattr(settings, "LOG_RETENTION_DAYS", 7)),
            help="Delete log files older than N days.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show actions without deleting data.",
        )

    def handle(self, *args, **options):
        inactive_days = max(1, int(options["inactive_days"]))
        room_retention_days = max(1, int(options["room_retention_days"]))
        empty_room_minutes = max(1, int(options["empty_room_minutes"]))
        max_storage_gb = max(1.0, float(options["max_storage_gb"]))
        target_storage_gb = max(1.0, float(options["target_storage_gb"]))
        log_retention_days = max(1, int(options["log_retention_days"]))
        dry_run = bool(options["dry_run"])

        if target_storage_gb > max_storage_gb:
            target_storage_gb = max_storage_gb

        affected_room_codes: set[str] = set()
        deleted_users, user_room_codes = self._cleanup_inactive_accounts(
            inactive_days=inactive_days,
            dry_run=dry_run,
        )
        affected_room_codes.update(user_room_codes)

        deleted_rooms, stale_room_codes = self._cleanup_stale_rooms(
            room_retention_days=room_retention_days,
            dry_run=dry_run,
        )
        affected_room_codes.update(stale_room_codes)
        deleted_empty_rooms = self._cleanup_empty_rooms(
            empty_room_minutes=empty_room_minutes,
            dry_run=dry_run,
        )

        redis_deleted = self._cleanup_redis_room_keys(
            room_codes=affected_room_codes,
            dry_run=dry_run,
        )

        storage_before = self._runtime_storage_bytes()
        self._enforce_storage_budget(
            max_storage_gb=max_storage_gb,
            target_storage_gb=target_storage_gb,
            log_retention_days=log_retention_days,
            dry_run=dry_run,
        )
        storage_after = self._runtime_storage_bytes()

        self.stdout.write(
            self.style.SUCCESS(
                (
                    f"Maintenance complete | dry_run={dry_run} | "
                    f"deleted_users={deleted_users} | deleted_rooms={deleted_rooms} | "
                    f"deleted_empty_rooms={deleted_empty_rooms} | "
                    f"redis_keys_deleted={redis_deleted} | "
                    f"runtime_storage_before={self._bytes_to_gb(storage_before):.2f}GB | "
                    f"runtime_storage_after={self._bytes_to_gb(storage_after):.2f}GB"
                )
            )
        )

    def _cleanup_empty_rooms(self, empty_room_minutes: int, dry_run: bool) -> int:
        if dry_run:
            # For dry run, estimate count without deleting.
            cutoff = timezone.now() - timedelta(minutes=empty_room_minutes)
            return int(
                Room.objects.filter(is_active=True, empty_since__isnull=False, empty_since__lte=cutoff)
                .annotate(active_count=Count("members", filter=Q(members__is_active=True)))
                .filter(active_count=0)
                .count()
            )
        return cleanup_inactive_rooms(empty_minutes=empty_room_minutes)

    def _cleanup_inactive_accounts(self, inactive_days: int, dry_run: bool) -> tuple[int, set[str]]:
        cutoff = timezone.now() - timedelta(days=inactive_days)
        inactive_qs = User.objects.filter(is_superuser=False, is_staff=False).filter(
            Q(last_login__lt=cutoff) | Q(last_login__isnull=True, date_joined__lt=cutoff)
        )
        user_ids = list(inactive_qs.values_list("id", flat=True))
        if not user_ids:
            return 0, set()

        room_codes = set(
            Room.objects.filter(
                Q(owner_id__in=user_ids) | Q(members__user_id__in=user_ids)
            )
            .distinct()
            .values_list("code", flat=True)
        )

        if dry_run:
            return len(user_ids), room_codes

        deleted_count, _ = inactive_qs.delete()
        # deleted_count includes cascaded rows. We return users count for clarity.
        _ = deleted_count
        return len(user_ids), room_codes

    def _cleanup_stale_rooms(self, room_retention_days: int, dry_run: bool) -> tuple[int, set[str]]:
        cutoff = timezone.now() - timedelta(days=room_retention_days)
        stale_rooms = (
            Room.objects.annotate(
                active_count=Count("members", filter=Q(members__is_active=True))
            )
            .filter(created_at__lt=cutoff, active_count=0)
            .distinct()
        )
        room_codes = set(stale_rooms.values_list("code", flat=True))
        if not room_codes:
            return 0, set()

        if dry_run:
            return len(room_codes), room_codes

        stale_rooms.delete()
        return len(room_codes), room_codes

    def _cleanup_redis_room_keys(self, room_codes: set[str], dry_run: bool) -> int:
        if not room_codes:
            return 0
        try:
            client = redis.from_url(settings.REDIS_URL, decode_responses=True)
            # quick check to avoid long exception chains
            client.ping()
        except Exception:
            return 0

        keys_to_delete: set[str] = set()
        for code in room_codes:
            keys_to_delete.add(f"room:{code}:chat")
            keys_to_delete.add(f"room:{code}:draw")
            keys_to_delete.add(f"room:{code}:game_state")
            keys_to_delete.add(f"room:{code}:timer_owner")
            pattern = f"room:{code}:connections:*"
            for key in client.scan_iter(match=pattern):
                keys_to_delete.add(key)

        if dry_run:
            return len(keys_to_delete)
        if not keys_to_delete:
            return 0

        return int(client.delete(*list(keys_to_delete)))

    def _runtime_storage_paths(self) -> list[Path]:
        project_root = settings.BASE_DIR.parent
        return [
            project_root / "logs",
            settings.BASE_DIR / "db.sqlite3",
            settings.BASE_DIR / "staticfiles",
            project_root / "frontend" / ".next",
        ]

    def _runtime_storage_bytes(self) -> int:
        return sum(self._path_size(path) for path in self._runtime_storage_paths())

    def _path_size(self, path: Path) -> int:
        if not path.exists():
            return 0
        if path.is_file():
            return path.stat().st_size

        total = 0
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    continue
        return total

    def _bytes_to_gb(self, size_bytes: int) -> float:
        return size_bytes / (1024 ** 3)

    def _enforce_storage_budget(
        self,
        max_storage_gb: float,
        target_storage_gb: float,
        log_retention_days: int,
        dry_run: bool,
    ) -> None:
        max_bytes = int(max_storage_gb * (1024 ** 3))
        target_bytes = int(target_storage_gb * (1024 ** 3))

        # Always prune old logs first.
        self._cleanup_logs(log_retention_days=log_retention_days, dry_run=dry_run)
        after_log_bytes = self._runtime_storage_bytes()
        if after_log_bytes <= target_bytes:
            return

        # If above target, trim build cache first.
        self._cleanup_next_cache(dry_run=dry_run)
        after_cache_bytes = self._runtime_storage_bytes()
        if after_cache_bytes <= target_bytes:
            return

        # If still above target or above hard limit, compact database.
        if after_cache_bytes > target_bytes or after_cache_bytes > max_bytes:
            self._vacuum_sqlite(dry_run=dry_run)

    def _cleanup_logs(self, log_retention_days: int, dry_run: bool) -> None:
        logs_dir = settings.BASE_DIR.parent / "logs"
        if not logs_dir.exists():
            return

        cutoff = timezone.now() - timedelta(days=log_retention_days)
        log_files = [path for path in logs_dir.rglob("*.log") if path.is_file()]

        for log_path in log_files:
            modified_at = datetime.fromtimestamp(log_path.stat().st_mtime, tz=dt_timezone.utc)
            if modified_at < cutoff:
                if dry_run:
                    continue
                try:
                    log_path.unlink(missing_ok=True)
                except OSError:
                    continue

    def _cleanup_next_cache(self, dry_run: bool) -> None:
        cache_dir = settings.BASE_DIR.parent / "frontend" / ".next" / "cache"
        if not cache_dir.exists():
            return
        if dry_run:
            return
        shutil.rmtree(cache_dir, ignore_errors=True)

    def _vacuum_sqlite(self, dry_run: bool) -> None:
        if connection.vendor != "sqlite":
            return
        if dry_run:
            return
        with connection.cursor() as cursor:
            cursor.execute("VACUUM")
