from __future__ import annotations

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
            }
            sdk.config.setConfig("RssReader", default, immediate=True)
            self.logger.info("已创建默认配置")
            return default
        return config

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
