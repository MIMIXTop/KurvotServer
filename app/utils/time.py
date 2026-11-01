from datetime import datetime, timedelta, timezone

class Time:
    def get_current_time_after_minutes(self, minutes: int) -> str:
        target_time = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        target_time_sec = target_time.replace(microsecond=0)
        return target_time_sec.strftime("%Y-%m-%dT%H:%M:%SZ")

    def get_current_time(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

time = Time()