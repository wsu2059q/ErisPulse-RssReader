from __future__ import annotations

import time
from typing import List, Optional

from ErisPulse import sdk


_SUBS = "rssreader_subscriptions"
_HIST = "rssreader_history"
_FILTERS = "rssreader_filters"

_SUB_COLS = [
    "id", "url", "name", "target_type", "target_id", "platform",
    "keywords_include", "keywords_exclude", "interval_minutes",
    "enabled", "max_items_per_push", "created_at",
]


def _to_dict(row: tuple) -> dict:
    return dict(zip(_SUB_COLS, row))


class FeedStore:
    def __init__(self):
        self._init_tables()

    def _init_tables(self):
        if not sdk.storage.HasTable(_SUBS):
            sdk.storage.CreateTable(_SUBS, {
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "url": "TEXT NOT NULL",
                "name": "TEXT DEFAULT ''",
                "target_type": "TEXT NOT NULL",
                "target_id": "TEXT NOT NULL",
                "platform": "TEXT NOT NULL",
                "keywords_include": "TEXT DEFAULT ''",
                "keywords_exclude": "TEXT DEFAULT ''",
                "interval_minutes": "INTEGER DEFAULT 30",
                "enabled": "INTEGER DEFAULT 1",
                "max_items_per_push": "INTEGER DEFAULT 5",
                "created_at": "REAL DEFAULT 0",
            })
        if not sdk.storage.HasTable(_HIST):
            sdk.storage.CreateTable(_HIST, {
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "subscription_id": "INTEGER NOT NULL",
                "item_hash": "TEXT NOT NULL",
                "title": "TEXT DEFAULT ''",
                "link": "TEXT DEFAULT ''",
                "published_at": "REAL DEFAULT 0",
            })
        if not sdk.storage.HasTable(_FILTERS):
            sdk.storage.CreateTable(_FILTERS, {
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "target_type": "TEXT NOT NULL",
                "target_id": "TEXT NOT NULL",
                "pattern": "TEXT NOT NULL",
                "rule_type": "TEXT NOT NULL",
                "is_regex": "INTEGER DEFAULT 0",
                "created_at": "REAL DEFAULT 0",
            })

    def add_subscription(
        self,
        url: str,
        name: str,
        target_type: str,
        target_id: str,
        platform: str,
        keywords_include: str = "",
        keywords_exclude: str = "",
        interval_minutes: int = 30,
        max_items_per_push: int = 5,
    ) -> Optional[int]:
        exists = (
            sdk.storage.Table(_SUBS).Select("id")
            .Where("url = ? AND target_type = ? AND target_id = ?", url, target_type, target_id)
            .ExecuteOne()
        )
        if exists:
            return None

        sdk.storage.Table(_SUBS).Insert({
            "url": url,
            "name": name,
            "target_type": target_type,
            "target_id": target_id,
            "platform": platform,
            "keywords_include": keywords_include,
            "keywords_exclude": keywords_exclude,
            "interval_minutes": interval_minutes,
            "enabled": 1,
            "max_items_per_push": max_items_per_push,
            "created_at": time.time(),
        }).Execute()

        row = (
            sdk.storage.Table(_SUBS).Select("id")
            .Where("url = ? AND target_type = ? AND target_id = ?", url, target_type, target_id)
            .ExecuteOne()
        )
        return row[0] if row else None

    def remove_subscription(self, sub_id: int) -> bool:
        if not sdk.storage.Table(_SUBS).Select("id").Where("id = ?", sub_id).Exists():
            return False
        sdk.storage.Table(_SUBS).Delete().Where("id = ?", sub_id).Execute()
        sdk.storage.Table(_HIST).Delete().Where("subscription_id = ?", sub_id).Execute()
        return True

    def get_subscription(self, sub_id: int) -> Optional[dict]:
        row = (
            sdk.storage.Table(_SUBS).Select(*_SUB_COLS)
            .Where("id = ?", sub_id)
            .ExecuteOne()
        )
        return _to_dict(row) if row else None

    def list_subscriptions(
        self,
        target_type: str = None,
        target_id: str = None,
        enabled_only: bool = False,
    ) -> List[dict]:
        query = sdk.storage.Table(_SUBS).Select(*_SUB_COLS)
        conds, params = [], []
        if target_type:
            conds.append("target_type = ?"); params.append(target_type)
        if target_id:
            conds.append("target_id = ?"); params.append(target_id)
        if enabled_only:
            conds.append("enabled = 1")
        if conds:
            query = query.Where(" AND ".join(conds), *params)
        return [_to_dict(r) for r in query.OrderBy("id").Execute()]

    def set_enabled(self, sub_id: int, enabled: bool) -> bool:
        if not sdk.storage.Table(_SUBS).Select("id").Where("id = ?", sub_id).Exists():
            return False
        sdk.storage.Table(_SUBS).Update({"enabled": 1 if enabled else 0}).Where("id = ?", sub_id).Execute()
        return True

    def is_item_seen(self, sub_id: int, item_hash: str) -> bool:
        return sdk.storage.Table(_HIST).Select("id").Where("subscription_id = ? AND item_hash = ?", sub_id, item_hash).Exists()

    def record_item(self, sub_id: int, item: dict):
        sdk.storage.Table(_HIST).Insert({
            "subscription_id": sub_id,
            "item_hash": item["item_hash"],
            "title": item["title"],
            "link": item["link"],
            "published_at": time.time(),
        }).Execute()

    def add_filter(
        self,
        target_type: str,
        target_id: str,
        pattern: str,
        rule_type: str,
        is_regex: bool = False,
    ) -> Optional[int]:
        sdk.storage.Table(_FILTERS).Insert({
            "target_type": target_type,
            "target_id": target_id,
            "pattern": pattern,
            "rule_type": rule_type,
            "is_regex": 1 if is_regex else 0,
            "created_at": time.time(),
        }).Execute()
        row = (
            sdk.storage.Table(_FILTERS).Select("id")
            .Where("target_type = ? AND target_id = ? AND pattern = ? AND rule_type = ?",
                   target_type, target_id, pattern, rule_type)
            .OrderBy("id DESC")
            .ExecuteOne()
        )
        return row[0] if row else None

    def remove_filter(self, filter_id: int) -> bool:
        if not sdk.storage.Table(_FILTERS).Select("id").Where("id = ?", filter_id).Exists():
            return False
        sdk.storage.Table(_FILTERS).Delete().Where("id = ?", filter_id).Execute()
        return True

    def list_filters(
        self,
        target_type: str = None,
        target_id: str = None,
    ) -> List[dict]:
        _FILTER_COLS = ["id", "target_type", "target_id", "pattern", "rule_type", "is_regex", "created_at"]
        query = sdk.storage.Table(_FILTERS).Select(*_FILTER_COLS)
        conds, params = [], []
        if target_type:
            conds.append("target_type = ?"); params.append(target_type)
        if target_id:
            conds.append("target_id = ?"); params.append(target_id)
        if conds:
            query = query.Where(" AND ".join(conds), *params)
        return [dict(zip(_FILTER_COLS, r)) for r in query.OrderBy("id").Execute()]

    def get_applicable_filters(self, target_type: str, target_id: str) -> List[dict]:
        _FILTER_COLS = ["id", "target_type", "target_id", "pattern", "rule_type", "is_regex", "created_at"]
        rows = sdk.storage.Table(_FILTERS).Select(*_FILTER_COLS).Where(
            "target_type = ? AND target_id = ?",
            target_type, target_id,
        ).OrderBy("id").Execute()
        return [dict(zip(_FILTER_COLS, r)) for r in rows]

    def get_all_enabled(self) -> List[dict]:
        return [_to_dict(r) for r in sdk.storage.Table(_SUBS).Select(*_SUB_COLS).Where("enabled = 1").Execute()]
