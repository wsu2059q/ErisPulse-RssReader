from __future__ import annotations

import asyncio
from typing import Dict

from ErisPulse import sdk
from ErisPulse.Core.Bases import BaseModule
from ErisPulse.Core.Event import command
from fastapi import Request
from fastapi.responses import JSONResponse

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
    "9": "export", "导出": "export", "导出订阅": "export", "一键导出": "export",
    "10": "interval", "修改间隔": "interval", "修改时间": "interval", "间隔": "interval",
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
        self._register_routes()
        self._register_dashboard_view()
        if self.config.get("auto_start", True):
            await self.scheduler.start()
        self.logger.info("RssReader 模块已加载")

    async def on_unload(self, event):
        await self.scheduler.stop()
        self._unregister_routes()
        self._unregister_dashboard_view()
        self.logger.info("RssReader 模块已卸载")

    def _register_commands(self):
        @command("RSS", help="查看管理订阅器")
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
            await event.reply("未知操作，请重新 /RSS")
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
            "export": self._menu_export,
            "interval": self._menu_interval,
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

    async def _menu_export(self, event):
        target_type, target_id = self._target_info(event)
        subs = self.store.list_subscriptions(target_type=target_type, target_id=target_id)
        if not subs:
            await event.reply("当前没有订阅可导出")
            return
        lines = []
        for sub in subs:
            name = sub.get("name") or sub.get("url", "")
            url = sub.get("url", "")
            lines.append(f"{name} | {url}")
        await event.reply("订阅导出:\n" + "\n".join(lines))

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
        await self._send_templates(event, FeedTemplates.build_status_msg(name, action))

    async def _menu_interval(self, event):
        target_type, target_id = self._target_info(event)
        subs = self.store.list_subscriptions(target_type=target_type, target_id=target_id)
        if not subs:
            await event.reply("没有订阅")
            return

        options = []
        for s in subs:
            status = "运行中" if s.get("enabled") else "已暂停"
            minutes = s.get("interval_minutes", 30)
            label = f"{minutes}分钟" if minutes < 60 else (f"{minutes // 60}小时" if minutes % 60 == 0 else f"{minutes}分钟")
            options.append(f"#{s['id']} {s.get('name') or s.get('url', '')} [{status}] 间隔:{label}")

        choice = await event.choose("选择要修改间隔的订阅:", options)
        if choice is None:
            return

        sub = subs[choice]
        sub_id = sub["id"]

        interval_choice = await event.choose(
            "选择新的推送间隔:",
            ["5分钟", "15分钟", "30分钟", "1小时", "3小时"]
        )
        if interval_choice is None:
            await event.reply("已取消")
            return

        new_interval = [5, 15, 30, 60, 180][interval_choice]
        self.store.update_subscription(sub_id, {"interval_minutes": new_interval})

        if sub.get("enabled"):
            self.scheduler.cancel_for(sub_id)
            updated_sub = self.store.get_subscription(sub_id)
            if updated_sub:
                self.scheduler.spawn_for(updated_sub)

        name = sub.get("name") or sub.get("url", "")
        new_label = f"{new_interval}分钟" if new_interval < 60 else (f"{new_interval // 60}小时" if new_interval % 60 == 0 else f"{new_interval}分钟")
        await event.reply(f"已将「{name}」的推送间隔修改为 {new_label}")

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
                url=url,
                name=probe.get("name", url),
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
                msg = f"正则表达式无效: {e}"
                if "global flags" in str(e):
                    msg += "\n提示: 行内标志如 (?i) 必须放在表达式最开头，例如 (?i)(词1|词2|词3)"
                await conv.say(msg)
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

    async def _send_to_target(self, platform: str, target_type: str, target_id: str, templates: Dict[str, str], image_url: str = None, bot_id: str = None):
        try:
            adapter = sdk.adapter.get(platform)
            if not adapter:
                return
            send = adapter.Send
            if bot_id:
                send = send.Using(bot_id)
            send = send.To(target_type, target_id)
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

    def _verify_request(self, request) -> bool:
        if hasattr(self.sdk, 'Dashboard') and self.sdk.Dashboard:
            return self.sdk.Dashboard.verify_request(request)
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        return bool(token)

    def _register_routes(self):
        r = self.sdk.router
        r.register_http_route("RssReader", "/api/stats", handler=self._api_stats, methods=["GET"])
        r.register_http_route("RssReader", "/api/subscriptions", handler=self._api_list_subs, methods=["GET"])
        r.register_http_route("RssReader", "/api/subscriptions", handler=self._api_add_sub, methods=["POST"])
        r.register_http_route("RssReader", "/api/subscriptions/export", handler=self._api_export_subs, methods=["GET"])
        r.register_http_route("RssReader", "/api/subscriptions/{sub_id}", handler=self._api_update_sub, methods=["PUT"])
        r.register_http_route("RssReader", "/api/subscriptions/{sub_id}", handler=self._api_delete_sub, methods=["DELETE"])
        r.register_http_route("RssReader", "/api/subscriptions/{sub_id}/toggle", handler=self._api_toggle_sub, methods=["POST"])
        r.register_http_route("RssReader", "/api/filters", handler=self._api_list_filters, methods=["GET"])
        r.register_http_route("RssReader", "/api/filters", handler=self._api_add_filter, methods=["POST"])
        r.register_http_route("RssReader", "/api/filters/{filter_id}", handler=self._api_delete_filter, methods=["DELETE"])

    def _unregister_routes(self):
        r = self.sdk.router
        for path in ["/api/stats", "/api/subscriptions", "/api/subscriptions/export"]:
            try:
                r.unregister_http_route("RssReader", path)
            except Exception:
                pass
        for suffix in ["/api/subscriptions/0", "/api/subscriptions/0/toggle", "/api/filters/0"]:
            try:
                r.unregister_http_route("RssReader", "/api/subscriptions/{sub_id}")
                r.unregister_http_route("RssReader", "/api/subscriptions/{sub_id}/toggle")
                r.unregister_http_route("RssReader", "/api/filters/{filter_id}")
            except Exception:
                pass

    async def _api_stats(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return JSONResponse(self.store.get_stats())

    async def _api_list_subs(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        target_type = request.query_params.get("target_type")
        target_id = request.query_params.get("target_id")
        if target_type and target_id:
            subs = self.store.list_subscriptions(target_type=target_type, target_id=target_id)
        else:
            subs = self.store.get_all_subscriptions()
        return JSONResponse({"subscriptions": subs})

    async def _api_add_sub(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        url = body.get("url", "").strip()
        if not url:
            return JSONResponse({"error": "URL is required"}, status_code=400)
        interval = int(body.get("interval_minutes", 30))
        platform = body.get("platform", "unknown")
        bot_id = body.get("bot_id", "")
        target_type = body.get("target_type", "global")
        target_id = body.get("target_id", "global")
        keywords = body.get("keywords_include", "")
        probe = await probe_rss(url)
        if not probe:
            return JSONResponse({"error": "Cannot parse RSS source"}, status_code=400)
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
            return JSONResponse({"error": "Already subscribed"}, status_code=409)
        self.scheduler.spawn_for(self.store.get_subscription(sub_id))
        for item in await fetch_rss(url, count=3):
            self.store.record_item(sub_id, item.to_dict())
        return JSONResponse({"success": True, "id": sub_id, "name": probe.get("name", url)})

    async def _api_update_sub(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        sub_id = int(request.path_params.get("sub_id", 0))
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        if not self.store.update_subscription(sub_id, body):
            return JSONResponse({"error": "Subscription not found"}, status_code=404)
        sub = self.store.get_subscription(sub_id)
        if sub and sub.get("enabled"):
            self.scheduler.spawn_for(sub)
        return JSONResponse({"success": True})

    async def _api_delete_sub(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        sub_id = int(request.path_params.get("sub_id", 0))
        self.scheduler.cancel_for(sub_id)
        if not self.store.remove_subscription(sub_id):
            return JSONResponse({"error": "Subscription not found"}, status_code=404)
        return JSONResponse({"success": True})

    async def _api_toggle_sub(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        sub_id = int(request.path_params.get("sub_id", 0))
        sub = self.store.get_subscription(sub_id)
        if not sub:
            return JSONResponse({"error": "Subscription not found"}, status_code=404)
        new_enabled = not sub.get("enabled", True)
        self.store.set_enabled(sub_id, new_enabled)
        if new_enabled:
            self.scheduler.spawn_for(self.store.get_subscription(sub_id))
        else:
            self.scheduler.cancel_for(sub_id)
        return JSONResponse({"success": True, "enabled": new_enabled})

    async def _api_export_subs(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        subs = self.store.get_all_subscriptions()
        lines = []
        for sub in subs:
            name = sub.get("name") or sub.get("url", "")
            url = sub.get("url", "")
            lines.append(f"{name} | {url}")
        return JSONResponse({"export": "\n".join(lines), "count": len(subs)})

    async def _api_list_filters(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return JSONResponse({"filters": self.store.get_all_filters()})

    async def _api_add_filter(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        pattern = body.get("pattern", "").strip()
        rule_type = body.get("rule_type", "blacklist")
        is_regex = bool(body.get("is_regex", False))
        target_type = body.get("target_type", "global")
        target_id = body.get("target_id", "global")
        if not pattern:
            return JSONResponse({"error": "Pattern is required"}, status_code=400)
        if rule_type not in ("blacklist", "whitelist"):
            return JSONResponse({"error": "Invalid rule_type"}, status_code=400)
        if is_regex:
            import re
            try:
                re.compile(pattern)
            except re.error as e:
                return JSONResponse({"error": f"Invalid regex: {e}"}, status_code=400)
        fid = self.store.add_filter(
            target_type=target_type,
            target_id=target_id,
            pattern=pattern,
            rule_type=rule_type,
            is_regex=is_regex,
        )
        return JSONResponse({"success": True, "id": fid})

    async def _api_delete_filter(self, request: Request) -> JSONResponse:
        if not self._verify_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        filter_id = int(request.path_params.get("filter_id", 0))
        if not self.store.remove_filter(filter_id):
            return JSONResponse({"error": "Filter not found"}, status_code=404)
        return JSONResponse({"success": True})

    def _register_dashboard_view(self):
        try:
            if not (hasattr(self.sdk, 'Dashboard') and self.sdk.Dashboard):
                return
            self.sdk.Dashboard.register_view(
                id="RssReader",
                title="RSS 订阅管理", title_en="RSS Reader",
                icon_svg='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1"/></svg>',
                html_content=self._dashboard_html(),
                js_content=self._dashboard_js(),
                css_content=self._dashboard_css(),
                loader="loadRssReaderView",
                group="group_tools",
            )
        except Exception as e:
            self.logger.warning(f"Dashboard view registration failed: {e}")

    def _unregister_dashboard_view(self):
        try:
            if hasattr(self.sdk, 'Dashboard') and self.sdk.Dashboard:
                self.sdk.Dashboard.unregister_view("RssReader")
        except Exception:
            pass

    @staticmethod
    def _dashboard_css():
        return '''
.rs-table{width:100%;border-collapse:collapse;font-size:13px}
.rs-table th{text-align:left;padding:8px 6px;color:var(--tx-s);font-weight:600;border-bottom:1px solid var(--bd)}
.rs-table td{padding:8px 6px;border-bottom:1px solid var(--bd);color:var(--tx-p)}
.rs-table tr:hover{background:var(--bg-s)}
.rs-badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
.rs-badge-on{background:rgba(46,204,113,.12);color:var(--ok-c)}
.rs-badge-off{background:rgba(231,76,60,.1);color:var(--er-c)}
.rs-badge-bl{background:rgba(231,76,60,.1);color:var(--er-c)}
.rs-badge-wl{background:rgba(46,204,113,.12);color:var(--ok-c)}
.rs-badge-rx{background:rgba(155,89,182,.1);color:#9b59b6}
.rs-url{font-size:11px;color:var(--tx-t);word-break:break-all;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rs-btn-sm{padding:3px 10px;font-size:12px;border:none;border-radius:4px;cursor:pointer;margin-right:4px}
.rs-btn-sm:hover{opacity:.8}
.rs-modal-bg{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.4);z-index:100}
.rs-modal{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:var(--bg-p);border-radius:8px;padding:24px;z-index:101;min-width:400px;max-width:90vw;box-shadow:0 4px 24px rgba(0,0,0,.2)}
.rs-modal h3{margin:0 0 16px;color:var(--tx-p)}
.rs-field{margin-bottom:12px}
.rs-field label{display:block;font-size:12px;color:var(--tx-s);margin-bottom:4px}
.rs-field input,.rs-field select,.rs-field textarea{width:100%;padding:8px;border:1px solid var(--bd);border-radius:4px;background:var(--bg-s);color:var(--tx-p);font-size:13px;box-sizing:border-box}
.rs-stat{display:flex;gap:16px;margin-bottom:16px;flex-wrap:wrap}
.rs-stat-item{background:var(--bg-t);padding:12px 20px;border-radius:6px;text-align:center}
.rs-stat-item .num{font-size:24px;font-weight:700;color:var(--accent)}
.rs-stat-item .lbl{font-size:12px;color:var(--tx-s)}
'''

    @staticmethod
    def _dashboard_html():
        return '''
<h1 class="page-title">RSS 订阅管理</h1>
<div id="rs-stats" class="rs-stat"></div>
<div class="card" style="margin-bottom:16px">
    <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
        <span>订阅列表</span>
        <div>
            <button class="btn btn-primary" onclick="rsShowAddSub()">添加订阅</button>
            <button class="btn btn-secondary" onclick="rsExportSubs()">导出</button>
            <button class="btn btn-icon" onclick="loadRssReaderView()">⟳</button>
        </div>
    </div>
    <div class="card-body" style="overflow-x:auto">
        <table class="rs-table">
            <thead><tr><th>ID</th><th>名称</th><th>URL</th><th>平台</th><th>目标</th><th>状态</th><th>间隔</th><th>操作</th></tr></thead>
            <tbody id="rs-sub-tbody"></tbody>
        </table>
    </div>
</div>
<div class="card">
    <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
        <span>过滤规则</span>
        <div>
            <button class="btn btn-primary" onclick="rsShowAddFilter()">添加规则</button>
            <button class="btn btn-icon" onclick="rsLoadFilters()">⟳</button>
        </div>
    </div>
    <div class="card-body" style="overflow-x:auto">
        <table class="rs-table">
            <thead><tr><th>ID</th><th>类型</th><th>规则</th><th>作用域</th><th>操作</th></tr></thead>
            <tbody id="rs-filter-tbody"></tbody>
        </table>
    </div>
</div>
<div id="rs-sub-modal-bg" class="rs-modal-bg" onclick="rsHideAddSub()"></div>
<div id="rs-sub-modal" class="rs-modal" style="display:none">
    <h3>添加订阅</h3>
    <div class="rs-field"><label>RSS 地址</label><input id="rs-sub-url" placeholder="https://example.com/feed.xml"></div>
    <div class="rs-field"><label>推送间隔(分钟)</label>
        <select id="rs-sub-interval"><option value="5">5分钟</option><option value="15">15分钟</option><option value="30" selected>30分钟</option><option value="60">1小时</option><option value="180">3小时</option></select>
    </div>
    <div class="rs-field"><label>推送平台</label>
        <select id="rs-sub-platform"></select>
    </div>
    <div class="rs-field"><label>推送账号(可选)</label>
        <select id="rs-sub-bot"><option value="">默认</option></select>
    </div>
    <div class="rs-field"><label>关键词过滤(逗号分隔,可选)</label><input id="rs-sub-kw" placeholder="关键词1,关键词2"></div>
    <div class="rs-field"><label>目标类型</label>
        <select id="rs-sub-tt"><option value="global">全局</option><option value="user">私聊 (user)</option><option value="group">群组 (group)</option><option value="channel">频道 (channel)</option><option value="guild">服务器 (guild)</option><option value="thread">话题 (thread)</option></select>
    </div>
    <div class="rs-field"><label>目标ID(非全局时填写)</label><input id="rs-sub-tid" placeholder="留空则全局"></div>
    <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="btn btn-secondary" onclick="rsHideAddSub()">取消</button>
        <button class="btn btn-primary" onclick="rsSubmitSub()">添加</button>
    </div>
</div>
<div id="rs-filter-modal-bg" class="rs-modal-bg" onclick="rsHideAddFilter()"></div>
<div id="rs-filter-modal" class="rs-modal" style="display:none">
    <h3>添加过滤规则</h3>
    <div class="rs-field"><label>规则内容</label><input id="rs-fl-pattern" placeholder="关键词或正则表达式"></div>
    <div class="rs-field"><label>规则类型</label>
        <select id="rs-fl-type"><option value="blacklist">黑名单</option><option value="whitelist">白名单</option></select>
    </div>
    <div class="rs-field"><label>匹配方式</label>
        <select id="rs-fl-regex"><option value="0">普通关键词</option><option value="1">正则表达式</option></select>
    </div>
    <div class="rs-field"><label>作用域类型</label>
        <select id="rs-fl-tt"><option value="global">全局</option><option value="user">私聊 (user)</option><option value="group">群组 (group)</option><option value="channel">频道 (channel)</option><option value="guild">服务器 (guild)</option><option value="thread">话题 (thread)</option></select>
    </div>
    <div class="rs-field"><label>作用域ID(非全局时填写)</label><input id="rs-fl-tid" placeholder="留空则全局"></div>
    <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="btn btn-secondary" onclick="rsHideAddFilter()">取消</button>
        <button class="btn btn-primary" onclick="rsSubmitFilter()">添加</button>
    </div>
</div>
'''

    @staticmethod
    def _dashboard_js():
        return '''
function rsApi(method,path,body){
    var h={'Authorization':'Bearer '+(localStorage.getItem('__ep_tk__')||'')};
    var opts={method:method,headers:h};
    if(body){opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(body);}
    return fetch('/RssReader'+path,opts).then(function(r){return r.json();});
}
function rsShowAddSub(){
    document.getElementById('rs-sub-modal-bg').style.display='block';
    document.getElementById('rs-sub-modal').style.display='block';
}
function rsHideAddSub(){
    document.getElementById('rs-sub-modal-bg').style.display='none';
    document.getElementById('rs-sub-modal').style.display='none';
}
function rsShowAddFilter(){
    document.getElementById('rs-filter-modal-bg').style.display='block';
    document.getElementById('rs-filter-modal').style.display='block';
}
function rsHideAddFilter(){
    document.getElementById('rs-filter-modal-bg').style.display='none';
    document.getElementById('rs-filter-modal').style.display='none';
}
function loadRssReaderView(){
    rsApi('GET','/api/stats').then(function(d){
        var el=document.getElementById('rs-stats');
        if(!el)return;
        el.innerHTML='<div class="rs-stat-item"><div class="num">'+(d.total||0)+'</div><div class="lbl">总订阅</div></div>'
            +'<div class="rs-stat-item"><div class="num">'+(d.enabled||0)+'</div><div class="lbl">运行中</div></div>'
            +'<div class="rs-stat-item"><div class="num">'+(d.disabled||0)+'</div><div class="lbl">已暂停</div></div>'
            +'<div class="rs-stat-item"><div class="num">'+(d.filters||0)+'</div><div class="lbl">过滤规则</div></div>';
    });
    rsLoadSubs();
    rsLoadFilters();
    rsLoadPlatforms();
}
function rsLoadPlatforms(){
    fetch('/Dashboard/api/adapters',{
        headers:{'Authorization':'Bearer '+(localStorage.getItem('__ep_tk__')||'')}
    }).then(function(r){return r.json();}).then(function(d){
        var sel=document.getElementById('rs-sub-platform');
        var bsel=document.getElementById('rs-sub-bot');
        if(!sel)return;
        var ps=d.adapters||[];
        sel.innerHTML='<option value="">-- 请选择平台 --</option>';
        for(var i=0;i<ps.length;i++){
            var opt=document.createElement('option');
            opt.value=ps[i].platform;
            opt.textContent=ps[i].platform+(ps[i].running?'':' (未运行)');
            sel.appendChild(opt);
        }
        if(!ps.length){
            sel.innerHTML='<option value="unknown">unknown</option>';
        }
        if(bsel){
            bsel.innerHTML='<option value="">默认</option>';
            for(var i=0;i<ps.length;i++){
                var bots=ps[i].bots||[];
                for(var j=0;j<bots.length;j++){
                    var opt=document.createElement('option');
                    opt.value=ps[i].platform+':'+bots[j].bot_id;
                    opt.textContent=ps[i].platform+' / '+bots[j].bot_id;
                    bsel.appendChild(opt);
                }
            }
        }
    }).catch(function(){});
}
function rsLoadSubs(){
    rsApi('GET','/api/subscriptions').then(function(d){
        var tb=document.getElementById('rs-sub-tbody');
        if(!tb)return;
        var subs=d.subscriptions||[];
        if(!subs.length){tb.innerHTML='<tr><td colspan="8" style="color:var(--tx-t);text-align:center">暂无订阅</td></tr>';return;}
        var html='';
        for(var i=0;i<subs.length;i++){
            var s=subs[i];
            var status=s.enabled?'<span class="rs-badge rs-badge-on">运行中</span>':'<span class="rs-badge rs-badge-off">已暂停</span>';
            var act=s.enabled?'<button class="rs-btn-sm" style="background:var(--bg-s);color:var(--tx-p)" onclick="rsToggleSub('+s.id+')">暂停</button>'
                :'<button class="rs-btn-sm" style="background:var(--ok-c);color:#fff" onclick="rsToggleSub('+s.id+')">恢复</button>';
            act+='<button class="rs-btn-sm" style="background:var(--er-c);color:#fff" onclick="rsDeleteSub('+s.id+')">删除</button>';
            var tgt=s.target_type==='global'?'全局':s.target_type+':'+s.target_id;
            html+='<tr><td>'+s.id+'</td><td>'+esc(s.name||s.url)+'</td><td class="rs-url" title="'+esc(s.url)+'">'+esc(s.url)+'</td><td>'+esc(s.platform||'')+'</td><td>'+esc(tgt)+'</td><td>'+status+'</td><td>'+s.interval_minutes+'m</td><td>'+act+'</td></tr>';
        }
        tb.innerHTML=html;
    });
}
function rsLoadFilters(){
    rsApi('GET','/api/filters').then(function(d){
        var tb=document.getElementById('rs-filter-tbody');
        if(!tb)return;
        var fs=d.filters||[];
        if(!fs.length){tb.innerHTML='<tr><td colspan="5" style="color:var(--tx-t);text-align:center">暂无规则</td></tr>';return;}
        var html='';
        for(var i=0;i<fs.length;i++){
            var f=fs[i];
            var typeBadge=f.rule_type==='blacklist'?'<span class="rs-badge rs-badge-bl">黑名单</span>':'<span class="rs-badge rs-badge-wl">白名单</span>';
            if(f.is_regex)typeBadge+=' <span class="rs-badge rs-badge-rx">正则</span>';
            var scope=f.target_type==='global'?'全局':f.target_type+':'+f.target_id;
            html+='<tr><td>'+f.id+'</td><td>'+typeBadge+'</td><td style="word-break:break-all">'+esc(f.pattern)+'</td><td>'+esc(scope)+'</td><td><button class="rs-btn-sm" style="background:var(--er-c);color:#fff" onclick="rsDeleteFilter('+f.id+')">删除</button></td></tr>';
        }
        tb.innerHTML=html;
    });
}
function esc(s){if(!s)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function rsToggleSub(id){rsApi('POST','/api/subscriptions/'+id+'/toggle').then(function(){loadRssReaderView();});}
function rsDeleteSub(id){
    if(!confirm('确定删除该订阅?'))return;
    rsApi('DELETE','/api/subscriptions/'+id).then(function(){loadRssReaderView();});
}
function rsDeleteFilter(id){
    if(!confirm('确定删除该规则?'))return;
    rsApi('DELETE','/api/filters/'+id).then(function(){rsLoadFilters();});
}
function rsSubmitSub(){
    var url=document.getElementById('rs-sub-url').value.trim();
    if(!url){alert('请输入RSS地址');return;}
    var botVal=document.getElementById('rs-sub-bot').value;
    var botId=botVal?botVal.split(':')[1]:'';
    var body={url:url,interval_minutes:parseInt(document.getElementById('rs-sub-interval').value),keywords_include:document.getElementById('rs-sub-kw').value,platform:document.getElementById('rs-sub-platform').value||'unknown',bot_id:botId,target_type:document.getElementById('rs-sub-tt').value,target_id:document.getElementById('rs-sub-tid').value||'global'};
    rsApi('POST','/api/subscriptions',body).then(function(d){
        if(d.error){alert(d.error);return;}
        rsHideAddSub();
        document.getElementById('rs-sub-url').value='';
        document.getElementById('rs-sub-kw').value='';
        document.getElementById('rs-sub-tid').value='';
        loadRssReaderView();
    });
}
function rsSubmitFilter(){
    var pattern=document.getElementById('rs-fl-pattern').value.trim();
    if(!pattern){alert('请输入规则内容');return;}
    var body={pattern:pattern,rule_type:document.getElementById('rs-fl-type').value,is_regex:document.getElementById('rs-fl-regex').value==='1',target_type:document.getElementById('rs-fl-tt').value,target_id:document.getElementById('rs-fl-tid').value||'global'};
    rsApi('POST','/api/filters',body).then(function(d){
        if(d.error){alert(d.error);return;}
        rsHideAddFilter();
        document.getElementById('rs-fl-pattern').value='';
        document.getElementById('rs-fl-tid').value='';
        rsLoadFilters();
        rsApi('GET','/api/stats').then(function(s){
            var el=document.getElementById('rs-stats');
            if(el){
                el.innerHTML='<div class="rs-stat-item"><div class="num">'+(s.total||0)+'</div><div class="lbl">总订阅</div></div>'
                    +'<div class="rs-stat-item"><div class="num">'+(s.enabled||0)+'</div><div class="lbl">运行中</div></div>'
                    +'<div class="rs-stat-item"><div class="num">'+(s.disabled||0)+'</div><div class="lbl">已暂停</div></div>'
                    +'<div class="rs-stat-item"><div class="num">'+(s.filters||0)+'</div><div class="lbl">过滤规则</div></div>';
            }
        });
    });
}
function rsExportSubs(){
    rsApi('GET','/api/subscriptions/export').then(function(d){
        if(d.export){
            var w=window.open('','_blank');
            w.document.write('<pre>'+esc(d.export)+'</pre>');
            w.document.title='RSS订阅导出';
        }
    });
}
'''
