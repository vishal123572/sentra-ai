"""Shared parsing helpers for offline statistics."""
from datetime import datetime, timezone


def timestamp(value):
    dt = datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def truth(value):
    return str(value).strip().lower() in {'true', '1', 'yes', 'y'}
