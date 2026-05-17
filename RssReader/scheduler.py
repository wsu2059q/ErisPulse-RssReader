from __future__ import annotations

import asyncio
import re
from typing import Dict, List, Optional, Callable, Awaitable

from ErisPulse import sdk

from .rss import fetch_rss
from .store import FeedStore
from .templates import FeedTemplates


class FeedScheduler:
    def __init__(self, store: FeedStore, logger, config: dict = None):
        self.store = store
        self.logger = logger
        self.config = config or {}
        self._tasks: Dict[int, asyncio.Task] = {}
        self._send_fn: Optional[Callable[..., Awaitable]] = None
        self._running = False

    def set_send_function(self, fn: Callable[..., Awaitable]):
        self._send_fn = fn

    async def start(self):
        if self._running:
            return
        self._running = True
        for sub in self.store.get_all_enabled():
            self._spawn(sub)
        self.logger.info(f"Scheduler started, {len(self._tasks)} subscriptions")

    async def stop(self):
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()

    def spawn_for(self, sub: dict):
        if sub["id"] in self._tasks:
            self._tasks[sub["id"]].cancel()
        self._spawn(sub)

    def cancel_for(self, sub_id: int):
        task = self._tasks.pop(sub_id, None)
        if task:
            task.cancel()

    def _spawn(self, sub: dict):
        self._tasks[sub["id"]] = asyncio.create_task(self._poll(sub))

    async def _poll(self, sub: dict):
        sub_id = sub["id"]
        interval = sub.get("interval_minutes", 30) * 60
        url = sub.get("url", "")

        while self._running:
            try:
                items = await fetch_rss(url, count=sub.get("max_items_per_push", 5))
                new = self._filter_new(sub_id, items, sub)
                if new:
                    await self._push(sub, new)
            except asyncio.CancelledError:
                return
            except Exception as e:
                self.logger.error(f"Poll sub#{sub_id} error: {e}")
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                return

    def _filter_new(self, sub_id: int, items, sub: dict) -> list:
        result = []
        target_type = sub.get("target_type", "")
        target_id = sub.get("target_id", "")
        filters = self.store.get_applicable_filters(target_type, target_id)

        global_black = [f for f in filters if f["target_type"] == "global" and f["rule_type"] == "blacklist"]
        global_white = [f for f in filters if f["target_type"] == "global" and f["rule_type"] == "whitelist"]
        chat_black = [f for f in filters if f["target_type"] != "global" and f["rule_type"] == "blacklist"]
        chat_white = [f for f in filters if f["target_type"] != "global" and f["rule_type"] == "whitelist"]

        kw_in = sub.get("keywords_include", "")
        kw_out = sub.get("keywords_exclude", "")

        for item in items:
            if self.store.is_item_seen(sub_id, item.item_hash):
                continue
            text = f"{item.title} {item.summary}".lower()

            if self._matches_any_rule(text, global_black):
                continue
            if global_white and not self._matches_any_rule(text, global_white):
                continue
            if self._matches_any_rule(text, chat_black):
                continue
            if chat_white and not self._matches_any_rule(text, chat_white):
                continue

            if kw_in:
                kws = [k.strip().lower() for k in kw_in.split(",") if k.strip()]
                if kws and not any(k in text for k in kws):
                    continue
            if kw_out:
                kws = [k.strip().lower() for k in kw_out.split(",") if k.strip()]
                if any(k in text for k in kws):
                    continue

            self.store.record_item(sub_id, item.to_dict())
            result.append(item)
        return result

    @staticmethod
    def _matches_any_rule(text: str, rules: list) -> bool:
        for rule in rules:
            pattern = rule["pattern"]
            if rule.get("is_regex"):
                try:
                    if re.search(pattern, text, re.IGNORECASE):
                        return True
                except re.error:
                    if pattern.lower() in text:
                        return True
            else:
                if pattern.lower() in text:
                    return True
        return False

    async def _push(self, sub: dict, items: list):
        if not self._send_fn:
            return
        if len(items) == 1:
            templates = FeedTemplates.build_feed_card(items[0])
            await self._send_fn(sub["platform"], sub["target_type"], sub["target_id"], templates, image_url=items[0].image)
        else:
            templates = FeedTemplates.build_digest(items)
            await self._send_fn(sub["platform"], sub["target_type"], sub["target_id"], templates)
