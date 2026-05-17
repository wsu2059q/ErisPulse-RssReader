from __future__ import annotations

import asyncio
from typing import Dict

from ErisPulse import sdk
from ErisPulse.Core.Bases import BaseModule
from ErisPulse.Core.Event import command

from .store import FeedStore
from .scheduler import FeedScheduler
from .rss import fetch_rss, probe_rss
from .templates import FeedTemplates


_MENU_MAP = {
    "1": "add", "添加": "add", "添加订阅": "add",
    "2": "list", "查看": "list", "列表": "list",
    "3": "del", "删除": "del", "移除": "del",
    "4": "toggle", "暂停": "toggle", "恢复": "toggle",
    "5": "test", "测试": "test",
    "6": "now", "推送": "now", "立即推送": "now",
    "7": "batch_add", "批量添加": "batch_add", "批量": "batch_add",
    "8": "filter", "过滤规则": "filter", "过滤": "filter", "黑白名单": "filter",
}

_FILTER_MENU_MAP = {
    "1": "add_black", "黑名单": "add_black", "添加黑名单": "add_black",
    "2": "add_white", "白名单": "add_white", "添加白名单": "add_white",
    "3": "list_rules", "查看规则": "list_rules", "列表": "list_rules",
    "4": "del_rule", "删除规则": "del_rule", "删除": "del_rule",
    "5": "add_global_black", "全局黑名单": "add_global_black", "添加全局黑名单": "add_global_black",
    "6": "add_global_white", "全局白名单": "add_global_white", "添加全局白名单": "add_global_white",
}


class Main(BaseModule):
    def __init__(self):
        self.sdk = sdk
        self.logger = sdk.logger.get_child("RssReader")
        self.config = self._load_config()
        self.store = FeedStore()
        self.scheduler = FeedScheduler(self.store, self.logger)

    @staticmethod
    def get_load_strategy():
        from ErisPulse.loaders import ModuleLoadStrategy
        return ModuleLoadStrategy(lazy_load=False, priority=50)

    def _load_config(self) -> dict:
        config = sdk.config.getConfig("RssReader")
        if not config:
            default = {
                "default_interval": 30,
                "max_items_per_push": 5,
                "auto_start": True,
                "max_subs_per_chat": 20,
                "admins": [],
            }
            sdk.config.setConfig("RssReader", default, immediate=True)
            self.logger.info("已创建默认配置")
            return default
        if "admins" not in config:
            config["admins"] = []
        return config

    def _is_admin(self, event) -> bool:
        user_id = event.get_user_id()
        admins = self.config.get("admins", [])
        return str(user_id) in [str(a) for a in admins]

    async def on_load(self, event):
        self.scheduler.set_send_function(self._send_to_target)
        self._register_commands()
        if self.config.get("auto_start", True):
            await self.scheduler.start()
        self.logger.info("RssReader 模块已加载")

    async def on_unload(self, event):
        await self.scheduler.stop()
        self.logger.info("RssReader 模块已卸载")

    def _register_commands(self):
        @command("rss", help="RSS订阅器")
        async def rss_cmd(event):
            args = event.get_command_args()
            if args and len(args) > 0 and args[0].startswith("http"):
                await self._quick_add(event, args[0])
                return
            await self._interactive_menu(event)

    async def _interactive_menu(self, event):
        await self._send_templates(event, FeedTemplates.build_main_menu())
        reply = await event.wait_reply(timeout=60)
        if not reply:
            return

        text = reply.get_text().strip().lower()
        action = _MENU_MAP.get(text)
        if not action:
            await event.reply("未知操作，请重新 /rss")
            return

        handler = {
            "add": self._menu_add,
            "list": self._menu_list,
            "del": self._menu_del,
            "toggle": self._menu_toggle,
            "test": self._menu_test,
            "now": self._menu_now,
            "batch_add": self._menu_batch_add,
            "filter": self._menu_filter,
        }.get(action)
        if handler:
            await handler(event)

    async def _menu_add(self, event):
        conv = event.conversation(timeout=120)
        platform = event.get_platform()
        target_type, target_id = self._target_info(event)

        await conv.say("请输入 RSS 源地址:")
        resp = await conv.wait()
        if not resp:
            return
        url = resp.get_text().strip()
        if not url:
            await conv.say("URL不能为空，已取消")
            return

        await conv.say(f"正在检测: {url}")
        probe = await probe_rss(url)
        if not probe:
            await conv.say("无法解析该RSS源，请检查URL")
            return

        await self._send_templates_conv(conv, event, FeedTemplates.build_probe_result(probe))

        choice = await conv.choose("推送间隔?", ["5分钟", "15分钟", "30分钟", "1小时", "3小时"])
        if choice is None:
            await conv.say("超时，已取消")
            return
        interval = [5, 15, 30, 60, 180][choice]

        await conv.say('关键词过滤（逗号分隔，回复"跳过"不设置）:')
        resp = await conv.wait()
        keywords = ""
        if resp and resp.get_text().strip() not in ("跳过", "skip", ""):
            keywords = resp.get_text().strip()

        if self._check_limit(conv, target_type, target_id):
            return

        sub_id = self.store.add_subscription(
            url=url,
            name=probe.get("name", url),
            target_type=target_type,
            target_id=target_id,
            platform=platform,
            keywords_include=keywords,
            interval_minutes=interval,
            max_items_per_push=self.config.get("max_items_per_push", 5),
        )
        if sub_id is None:
            await conv.say("该源已订阅")
            return

        self.scheduler.spawn_for(self.store.get_subscription(sub_id))
        await self._send_templates_conv(conv, event, FeedTemplates.build_add_confirm(probe, interval, keywords))

        for item in await fetch_rss(url, count=3):
            self.store.record_item(sub_id, item.to_dict())

    async def _menu_list(self, event):
        target_type, target_id = self._target_info(event)
        subs = self.store.list_subscriptions(target_type=target_type, target_id=target_id)
        await self._send_templates(event, FeedTemplates.build_sub_list(subs))

    async def _menu_del(self, event):
        target_type, target_id = self._target_info(event)
        subs = self.store.list_subscriptions(target_type=target_type, target_id=target_id)
        if not subs:
            await event.reply("没有可删除的订阅")
            return

        options = [f"#{s['id']} {s.get('name') or s.get('url', '')}" for s in subs]
        choice = await event.choose("选择要删除的订阅:", options)
        if choice is None:
            return

        sub = subs[choice]
        self.scheduler.cancel_for(sub["id"])
        self.store.remove_subscription(sub["id"])
        await event.reply(f"已删除: {sub.get('name', sub.get('url', ''))}")

    async def _menu_toggle(self, event):
        target_type, target_id = self._target_info(event)
        subs = self.store.list_subscriptions(target_type=target_type, target_id=target_id)
        if not subs:
            await event.reply("没有订阅")
            return

        options = []
        for s in subs:
            status = "运行中" if s.get("enabled") else "已暂停"
            options.append(f"#{s['id']} {s.get('name') or s.get('url', '')} [{status}]")

        choice = await event.choose("选择要操作的订阅:", options)
        if choice is None:
            return

        sub = subs[choice]
        new_enabled = not sub.get("enabled", True)
        self.store.set_enabled(sub["id"], new_enabled)

        if new_enabled:
            self.scheduler.spawn_for(self.store.get_subscription(sub["id"]))
            action = "已恢复"
        else:
            self.scheduler.cancel_for(sub["id"])
            action = "已暂停"

        name = sub.get("name") or sub.get("url", "")
        await self._send_templates(event, FeedTemplates.build_status_msg(name, action, True))

    async def _menu_test(self, event):
        await event.reply("请输入要测试的 RSS 源地址:")
        reply = await event.wait_reply(timeout=60)
        if not reply:
            return
        url = reply.get_text().strip()
        if not url:
            return

        await event.reply(f"正在检测: {url}")
        probe = await probe_rss(url)
        if not probe:
            await event.reply("无法解析该RSS源")
            return

        await self._send_templates(event, FeedTemplates.build_probe_result(probe))
        items = await fetch_rss(url, count=3)
        if items:
            await event.reply(f"最近 {len(items)} 条:")
            for item in items:
                await self._send_templates(event, FeedTemplates.build_feed_card(item), image_url=item.image)

    async def _menu_now(self, event):
        target_type, target_id = self._target_info(event)
        subs = self.store.list_subscriptions(target_type=target_type, target_id=target_id, enabled_only=True)
        if not subs:
            await event.reply("没有启用的订阅")
            return

        await event.reply(f"正在抓取 {len(subs)} 个订阅...")
        total = 0
        for sub in subs:
            try:
                items = await fetch_rss(sub["url"], count=sub.get("max_items_per_push", 5))
                new = self.scheduler._filter_new(sub["id"], items, sub)
                if new:
                    total += len(new)
                    if len(new) == 1:
                        await self._send_templates(event, FeedTemplates.build_feed_card(new[0]), image_url=new[0].image)
                    else:
                        await self._send_templates(event, FeedTemplates.build_digest(new))
            except Exception as e:
                self.logger.error(f"Manual fetch sub#{sub['id']}: {e}")
        if total == 0:
            await event.reply("暂无新内容")

    async def _menu_batch_add(self, event):
        conv = event.conversation(timeout=180)
        platform = event.get_platform()
        target_type, target_id = self._target_info(event)

        await conv.say("请粘贴 RSS 源地址，每行一个:\nhttps://...\nhttps://...\nhttps://...")
        resp = await conv.wait()
        if not resp:
            return
        raw = resp.get_text().strip()
        urls = [u.strip() for u in raw.replace("\r\n", "\n").split("\n") if u.strip()]
        if not urls:
            await conv.say("未检测到有效地址，已取消")
            return

        await conv.say(f"正在检测 {len(urls)} 个源...")

        probe_tasks = [probe_rss(u) for u in urls]
        probe_results = await asyncio.gather(*probe_tasks, return_exceptions=True)

        results = []
        valid = []
        for url, probe in zip(urls, probe_results):
            if isinstance(probe, Exception) or not probe:
                results.append({"url": url, "ok": False, "reason": "无法解析该RSS源"})
            else:
                results.append({"url": url, "ok": True, "probe": probe})
                valid.append({"url": url, "probe": probe})

        if not valid:
            await self._send_templates_conv(conv, event, FeedTemplates.build_batch_result(results))
            return

        choice = await conv.choose("推送间隔?", ["5分钟", "15分钟", "30分钟", "1小时", "3小时"])
        if choice is None:
            await conv.say("超时，已取消")
            return
        interval = [5, 15, 30, 60, 180][choice]

        await conv.say('关键词过滤（逗号分隔，回复"跳过"不设置）:')
        resp = await conv.wait()
        keywords = ""
        if resp and resp.get_text().strip() not in ("跳过", "skip", ""):
            keywords = resp.get_text().strip()

        if self._check_limit(conv, target_type, target_id):
            return

        for v in valid:
            sub_id = self.store.add_subscription(
                url=v["url"],
                name=v["probe"].get("name", v["url"]),
                target_type=target_type,
                target_id=target_id,
                platform=platform,
                keywords_include=keywords,
                interval_minutes=interval,
                max_items_per_push=self.config.get("max_items_per_push", 5),
            )
            if sub_id is not None:
                self.scheduler.spawn_for(self.store.get_subscription(sub_id))
                for item in await fetch_rss(v["url"], count=3):
                    self.store.record_item(sub_id, item.to_dict())
                results = [r if r["url"] != v["url"] else {**r, "ok": True, "name": v["probe"].get("name", v["url"])} for r in results]
            else:
                results = [r if r["url"] != v["url"] else {**r, "ok": False, "reason": "该源已订阅"} for r in results]

        await self._send_templates_conv(conv, event, FeedTemplates.build_batch_result(results))

    async def _menu_filter(self, event):
        conv = event.conversation(timeout=120)

        await self._send_templates_conv(conv, event, FeedTemplates.build_filter_menu(self._is_admin(event)))
        resp = await conv.wait()
        if not resp:
            return

        text = resp.get_text().strip().lower()
        action = _FILTER_MENU_MAP.get(text)
        if not action:
            await conv.say("未知操作，已取消")
            return

        if action.startswith("add_global") and not self._is_admin(event):
            await conv.say("仅管理员可操作全局规则")
            return

        handler = {
            "add_black": lambda: self._filter_add(conv, event, "blacklist"),
            "add_white": lambda: self._filter_add(conv, event, "whitelist"),
            "list_rules": lambda: self._filter_list(conv, event),
            "del_rule": lambda: self._filter_del(conv, event),
            "add_global_black": lambda: self._filter_add(conv, event, "blacklist", global_scope=True),
            "add_global_white": lambda: self._filter_add(conv, event, "whitelist", global_scope=True),
        }.get(action)
        if handler:
            await handler()

    async def _filter_add(self, conv, event, rule_type: str, global_scope: bool = False):
        rt_name = "黑名单" if rule_type == "blacklist" else "白名单"
        scope_label = "全局" if global_scope else "本会话"
        await conv.say(f"请输入{scope_label}{rt_name}规则（关键词或正则表达式）:")
        resp = await conv.wait()
        if not resp:
            return
        pattern = resp.get_text().strip()
        if not pattern:
            await conv.say("规则不能为空，已取消")
            return

        choice = await conv.choose("规则类型?", ["普通关键词", "正则表达式"])
        if choice is None:
            await conv.say("超时，已取消")
            return
        is_regex = choice == 1

        if is_regex:
            import re
            try:
                re.compile(pattern)
            except re.error as e:
                await conv.say(f"正则表达式无效: {e}")
                return

        if global_scope:
            target_type, target_id = "global", "global"
        else:
            target_type, target_id = self._target_info(event)

        self.store.add_filter(
            target_type=target_type,
            target_id=target_id,
            pattern=pattern,
            rule_type=rule_type,
            is_regex=is_regex,
        )
        await self._send_templates_conv(conv, event, FeedTemplates.build_filter_add_confirm({
            "rule_type": rule_type,
            "pattern": pattern,
            "is_regex": is_regex,
            "target_type": target_type,
            "target_id": target_id,
        }))

    async def _filter_list(self, conv, event):
        target_type, target_id = self._target_info(event)
        chat_filters = self.store.list_filters(target_type=target_type, target_id=target_id)
        global_filters = self.store.list_filters(target_type="global", target_id="global")
        all_filters = global_filters + chat_filters
        await self._send_templates_conv(conv, event, FeedTemplates.build_filter_list(all_filters))

    async def _filter_del(self, conv, event):
        target_type, target_id = self._target_info(event)
        is_admin = self._is_admin(event)
        chat_filters = self.store.list_filters(target_type=target_type, target_id=target_id)
        global_filters = self.store.list_filters(target_type="global", target_id="global") if is_admin else []
        all_filters = global_filters + chat_filters
        if not all_filters:
            await conv.say("没有可删除的规则")
            return

        options = []
        for f in all_filters:
            rt = "黑名单" if f["rule_type"] == "blacklist" else "白名单"
            regex_tag = " [正则]" if f.get("is_regex") else ""
            scope = "全局" if f["target_type"] == "global" else "本会话"
            options.append(f"#{f['id']} [{rt}{regex_tag}] {f['pattern']} ({scope})")

        choice = await conv.choose("选择要删除的规则:", options)
        if choice is None:
            return

        f = all_filters[choice]
        if f["target_type"] == "global" and not is_admin:
            await conv.say("仅管理员可删除全局规则")
            return
        self.store.remove_filter(f["id"])
        await conv.say(f"已删除规则: {f['pattern']}")

    async def _quick_add(self, event, url: str):
        target_type, target_id = self._target_info(event)
        platform = event.get_platform()

        await event.reply(f"正在检测: {url}")
        probe = await probe_rss(url)
        if not probe:
            await event.reply("无法解析该RSS源，请检查URL")
            return

        if self._check_limit(event, target_type, target_id):
            return

        interval = self.config.get("default_interval", 30)
        sub_id = self.store.add_subscription(
            url=url,
            name=probe.get("name", url),
            target_type=target_type,
            target_id=target_id,
            platform=platform,
            interval_minutes=interval,
            max_items_per_push=self.config.get("max_items_per_push", 5),
        )
        if sub_id is None:
            await event.reply("该源已订阅")
            return

        self.scheduler.spawn_for(self.store.get_subscription(sub_id))
        await self._send_templates(event, FeedTemplates.build_add_confirm(probe, interval, ""))

        for item in await fetch_rss(url, count=3):
            self.store.record_item(sub_id, item.to_dict())

    def _target_info(self, event) -> tuple:
        if event.is_private_message():
            return "user", event.get_user_id()
        return "group", event.get_group_id()

    def _check_limit(self, target, target_type: str, target_id: str) -> bool:
        max_subs = self.config.get("max_subs_per_chat", 20)
        current = self.store.list_subscriptions(target_type=target_type, target_id=target_id, enabled_only=False)
        if len(current) >= max_subs:
            msg = f"已达订阅上限 ({max_subs})"
            if hasattr(target, "reply"):
                target.reply(msg)
            elif hasattr(target, "say"):
                target.say(msg)
            return True
        return False

    @staticmethod
    def _select_best_format(platform: str, templates: Dict[str, str]) -> tuple:
        try:
            methods = sdk.adapter.list_sends(platform)
            if "Html" in methods:
                return ("Html", templates["html"])
            if "Markdown" in methods:
                return ("Markdown", templates["markdown"])
            return ("Text", templates["text"])
        except Exception:
            return ("Text", templates["text"])

    async def _send_templates(self, target, templates: Dict[str, str], image_url: str = None):
        if not templates:
            return
        platform = target.get_platform() if hasattr(target, "get_platform") else "sandbox"

        if image_url:
            try:
                await target.reply(image_url, method="Image")
            except Exception:
                pass

        fmt, content = self._select_best_format(platform, templates)
        try:
            await target.reply(content, method=fmt)
        except Exception:
            await target.reply(templates.get("text", ""))

    async def _send_templates_conv(self, conv, event, templates: Dict[str, str]):
        fmt, content = self._select_best_format(event.get_platform(), templates)
        try:
            await conv.say(content, method=fmt)
        except Exception:
            await conv.say(templates.get("text", ""))

    async def _send_to_target(self, platform: str, target_type: str, target_id: str, templates: Dict[str, str], image_url: str = None):
        try:
            adapter = sdk.adapter.get(platform)
            if not adapter:
                return
            send = adapter.Send.To(target_type, target_id)
            if image_url:
                try:
                    await send.Image(image_url)
                except Exception:
                    pass
            fmt, content = self._select_best_format(platform, templates)
            try:
                await getattr(send, fmt)(content)
            except Exception:
                await send.Text(templates.get("text", ""))
        except Exception as e:
            self.logger.error(f"Send to {platform}/{target_type}/{target_id}: {e}")
