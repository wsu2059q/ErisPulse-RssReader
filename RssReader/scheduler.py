from __future__ import annotations

import asyncio
import re
import time
from typing import Dict, List, Optional, Callable, Awaitable

from ErisPulse import sdk

from .rss import fetch_rss, probe_rss
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
        self._health_task: Optional[asyncio.Task] = None
        self._last_health_notify: Dict[int, float] = {}

    def set_send_function(self, fn: Callable[..., Awaitable]):
        self._send_fn = fn

    async def start(self):
        if self._running:
            return
        self._running = True
        for sub in self.store.get_all_enabled():
            self._spawn(sub)
        self.logger.info(f"Scheduler started, {len(self._tasks)} subscriptions")
        self._spawn_health()

    async def stop(self):
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
        self._health_task = None

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
                self.store.update_health(sub_id, ok=True)
                new = self._filter_new(sub_id, items, sub)
                if new:
                    await self._push(sub, new)
            except asyncio.CancelledError:
                return
            except Exception as e:
                self.logger.error(f"Poll sub#{sub_id} error: {e}")
                try:
                    self.store.update_health(sub_id, ok=False, error=str(e))
                except Exception:
                    pass
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

    def _spawn_health(self):
        if self._health_task and not self._health_task.done():
            return
        self._health_task = asyncio.create_task(self._health_loop())

    def get_fail_threshold(self) -> int:
        try:
            return int(self.config.get("health_check_fail_threshold", 3))
        except Exception:
            return 3

    def get_health_interval(self) -> int:
        try:
            return max(60, int(self.config.get("health_check_interval", 1440)) * 60)
        except Exception:
            return 86400

    def update_config(self, config: dict):
        self.config = config or {}

    async def _health_loop(self):
        while self._running:
            try:
                await asyncio.sleep(self.get_health_interval())
            except asyncio.CancelledError:
                return
            if not self._running:
                return
            try:
                await self._run_health_check()
            except asyncio.CancelledError:
                return
            except Exception as e:
                self.logger.error(f"Health check loop error: {e}")

    def get_probe_timeout(self) -> int:
        try:
            return max(3, int(self.config.get("health_check_probe_timeout", 10)))
        except Exception:
            return 10

    async def _run_health_check(self):
        subs = self.store.get_all_enabled()
        if not subs:
            return
        self.logger.info(f"Health check start, {len(subs)} subscriptions")
        threshold = self.get_fail_threshold()
        probe_timeout = self.get_probe_timeout()

        probe_tasks = [probe_rss(s.get("url", ""), timeout=probe_timeout) for s in subs]
        results = await asyncio.gather(*probe_tasks, return_exceptions=True)

        ok_count = 0
        for sub, res in zip(subs, results):
            sub_id = sub["id"]
            if isinstance(res, Exception):
                new_fail = self.store.update_health(sub_id, ok=False, error=f"{type(res).__name__}: {res}")
            elif res:
                new_fail = self.store.update_health(sub_id, ok=True)
                ok_count += 1
            else:
                new_fail = self.store.update_health(sub_id, ok=False, error="无法解析或HTTP错误")
            if new_fail == threshold:
                fresh = self.store.get_subscription(sub_id) or sub
                await self._notify_unhealthy(fresh, new_fail)
        self.logger.info(f"Health check done, {ok_count}/{len(subs)} ok")
        return {"total": len(subs), "ok": ok_count, "fail": len(subs) - ok_count}

    async def _notify_unhealthy(self, sub: dict, fail_count: int):
        if not self._send_fn:
            return
        if sub.get("target_type") == "global":
            return
        now = time.time()
        last = self._last_health_notify.get(sub["id"], 0)
        if now - last < 6 * 3600:
            return
        self._last_health_notify[sub["id"]] = now
        templates = FeedTemplates.build_health_alert(sub, fail_count)
        try:
            await self._send_fn(
                sub["platform"], sub["target_type"], sub["target_id"], templates,
            )
        except Exception as e:
            self.logger.error(f"Notify unhealthy sub#{sub['id']} error: {e}")
