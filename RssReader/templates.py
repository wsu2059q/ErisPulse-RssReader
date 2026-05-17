from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict

PRIMARY = "#fb7299"
PRIMARY_BG = "rgba(251, 114, 153, 0.05)"
SECONDARY = "#666"
BORDER = "rgba(0, 0, 0, 0.06)"
TAG_BG = "rgba(0,0,0,0.04)"


class FeedTemplates:

    @classmethod
    def build_main_menu(cls) -> Dict[str, str]:
        items = [
            ("1", "添加订阅"),
            ("2", "查看订阅列表"),
            ("3", "删除订阅"),
            ("4", "暂停 / 恢复订阅"),
            ("5", "测试 RSS 源"),
            ("6", "立即推送"),
            ("7", "批量添加订阅"),
            ("8", "过滤规则管理"),
        ]
        items_html = "".join(
            f'<div style="font-size: 13px; margin-bottom: 4px;">'
            f'<span style="color: {PRIMARY}; font-weight: bold; margin-right: 8px;">{num}.</span>'
            f'{label}</div>'
            for num, label in items
        )

        return {
            "html": (
                f'<div style="padding: 12px; border-radius: 8px;">'
                f'<div style="color: {PRIMARY}; font-size: 15px; font-weight: bold; margin-bottom: 10px;">RSS 订阅管理</div>'
                f'{items_html}'
                f'<div style="font-size: 11px; color: {SECONDARY}; margin-top: 8px;">回复编号或操作名称，也可直接 /rss &lt;URL&gt;</div>'
                f'</div>'
            ),
            "markdown": (
                f"**RSS 订阅管理**\n\n"
                "1. 添加订阅\n2. 查看订阅列表\n3. 删除订阅\n"
                "4. 暂停/恢复订阅\n5. 测试 RSS 源\n6. 立即推送\n"
                "7. 批量添加订阅\n8. 过滤规则管理\n\n"
                "回复编号即可，也可直接 `/rss <URL>`"
            ),
            "text": (
                "RSS 订阅管理\n"
                "1. 添加订阅\n2. 查看订阅列表\n3. 删除订阅\n"
                "4. 暂停/恢复订阅\n5. 测试RSS源\n6. 立即推送\n"
                "7. 批量添加订阅\n8. 过滤规则管理\n"
                "回复编号即可，也可 /rss <URL>"
            ),
        }

    @classmethod
    def build_feed_card(cls, item) -> Dict[str, str]:
        return {
            "html": cls._card_html(item),
            "markdown": cls._card_markdown(item),
            "text": cls._card_text(item),
        }

    @classmethod
    def build_digest(cls, items: list) -> Dict[str, str]:
        if not items:
            return {"html": "", "markdown": "", "text": ""}
        return {
            "html": cls._digest_html(items),
            "markdown": cls._digest_markdown(items),
            "text": cls._digest_text(items),
        }

    @classmethod
    def build_probe_result(cls, info: dict) -> Dict[str, str]:
        return {
            "html": cls._probe_html(info),
            "markdown": cls._probe_markdown(info),
            "text": cls._probe_text(info),
        }

    @classmethod
    def build_sub_list(cls, subs: list) -> Dict[str, str]:
        if not subs:
            nope = "当前没有订阅"
            return {"html": nope, "markdown": nope, "text": nope}
        return {
            "html": cls._sublist_html(subs),
            "markdown": cls._sublist_markdown(subs),
            "text": cls._sublist_text(subs),
        }

    @classmethod
    def build_add_confirm(cls, info: dict, interval: int, keywords: str) -> Dict[str, str]:
        return {
            "html": cls._confirm_html(info, interval, keywords),
            "markdown": cls._confirm_markdown(info, interval, keywords),
            "text": cls._confirm_text(info, interval, keywords),
        }

    @classmethod
    def build_status_msg(cls, sub_name: str, action: str) -> Dict[str, str]:
        return {
            "html": (
                f'<div style="padding: 8px 12px; border-radius: 6px;">'
                f'<span style="font-weight: bold;">{sub_name}</span> '
                f'<span style="color: {PRIMARY};">{action}</span></div>'
            ),
            "markdown": f"**{sub_name}** {action}",
            "text": f"{sub_name} {action}",
        }

    @classmethod
    def _card_html(cls, item) -> str:
        source_badge = (
            f'<span style="font-size: 11px; background: {PRIMARY_BG}; '
            f'color: {PRIMARY}; padding: 1px 5px; border-radius: 3px;">'
            f'{item.source_name}</span>'
        )

        meta_parts = []
        if item.author:
            meta_parts.append(
                f'<span style="margin-right: 12px;">作者: '
                f'<span style="color: {PRIMARY}; font-weight: bold;">{item.author}</span></span>'
            )
        meta_parts.append(f'<span>{cls._fmt_time(item.published)}</span>')
        meta_line = "".join(meta_parts)

        summary_block = ""
        if item.summary:
            summary_block = (
                f'<details style="margin-top: 8px;">'
                f'<summary style="cursor: pointer; font-size: 12px; color: {SECONDARY};">摘要</summary>'
                f'<div style="padding: 6px; font-size: 12px; color: {SECONDARY};">{item.summary}</div>'
                f'</details>'
            )

        link_line = ""
        if item.link:
            link_line = (
                f'<div style="margin-top: 8px;">'
                f'<a href="{item.link}" style="font-size: 12px; color: {PRIMARY};">{item.link}</a></div>'
            )

        return (
            f'<div style="padding: 12px; border-radius: 8px;">'
            f'<div style="margin-bottom: 6px;">{source_badge}</div>'
            f'<div style="color: {PRIMARY}; font-size: 15px; font-weight: bold; margin-bottom: 8px; line-height: 1.4;">{item.title}</div>'
            f'<div style="font-size: 12px; color: {SECONDARY}; margin-bottom: 4px;">{meta_line}</div>'
            f'{summary_block}'
            f'{link_line}'
            f'</div>'
        )

    @classmethod
    def _card_markdown(cls, item) -> str:
        lines = []
        if item.source_name:
            lines.append(f"**{item.source_name}**")
        lines.append(f"**{item.title}**")
        meta = []
        if item.author:
            meta.append(item.author)
        meta.append(cls._fmt_time(item.published))
        lines.append(" | ".join(meta))
        if item.summary:
            lines.append(f"> {item.summary}")
        if item.link:
            lines.append(item.link)
        return "\n".join(lines)

    @classmethod
    def _card_text(cls, item) -> str:
        lines = [item.title]
        meta = []
        if item.source_name:
            meta.append(f"[{item.source_name}]")
        if item.author:
            meta.append(item.author)
        meta.append(cls._fmt_time(item.published))
        if meta:
            lines.append(" | ".join(meta))
        if item.summary:
            lines.append(item.summary)
        if item.link:
            lines.append(item.link)
        return "\n".join(lines)

    @classmethod
    def _digest_html(cls, items: list) -> str:
        source_name = items[0].source_name if items else ""
        entries = []
        for i, item in enumerate(items, 1):
            link_attr = f' href="{item.link}"' if item.link else ""
            entries.append(
                f'<div style="margin-bottom: 4px; font-size: 13px;">'
                f'<span style="font-weight: bold;">{i}. </span>'
                f'<a{link_attr} style="color: #333; text-decoration: none;">{item.title}</a>'
                f' <span style="font-size: 11px; color: {SECONDARY};">{cls._fmt_time(item.published)}</span></div>'
            )
        return (
            f'<div style="padding: 12px; border-radius: 8px;">'
            f'<div style="font-size: 13px; font-weight: bold; color: {PRIMARY}; margin-bottom: 8px;">'
            f'{source_name} - {len(items)} 条更新</div>'
            f'{"".join(entries)}'
            f'</div>'
        )

    @classmethod
    def _digest_markdown(cls, items: list) -> str:
        source_name = items[0].source_name if items else ""
        lines = [f"**{source_name}** - {len(items)} 条更新", ""]
        for i, item in enumerate(items, 1):
            title = f"[{item.title}]({item.link})" if item.link else item.title
            lines.append(f"{i}. {title}  _{cls._fmt_time(item.published)}_")
        return "\n".join(lines)

    @classmethod
    def _digest_text(cls, items: list) -> str:
        source_name = items[0].source_name if items else ""
        lines = [f"{source_name} - {len(items)} 条更新", "----------"]
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. {item.title}")
            lines.append(f"   {cls._fmt_time(item.published)}")
        return "\n".join(lines)

    @classmethod
    def _probe_html(cls, info: dict) -> str:
        desc_section = ""
        if info.get("description"):
            desc = info["description"][:100]
            if len(info.get("description", "")) > 100:
                desc += "..."
            desc_section = (
                f'<details style="margin-top: 6px;">'
                f'<summary style="cursor: pointer; font-size: 12px; color: {SECONDARY};">描述</summary>'
                f'<div style="padding: 6px; font-size: 12px; color: {SECONDARY};">{desc}</div>'
                f'</details>'
            )

        latest_line = ""
        if info.get("latest_title"):
            latest_line = (
                f'<div style="margin-top: 8px; padding: 6px; background: {PRIMARY_BG}; border-radius: 6px;">'
                f'<div style="font-size: 12px; color: {SECONDARY}; margin-bottom: 2px;">最新</div>'
                f'<div style="font-size: 13px;">{info["latest_title"]}</div></div>'
            )

        return (
            f'<div style="padding: 12px; border-radius: 8px;">'
            f'<div style="color: {PRIMARY}; font-size: 15px; font-weight: bold; margin-bottom: 8px;">{info.get("name", "Unknown")}</div>'
            f'<div style="padding: 6px; background: {PRIMARY_BG}; border-radius: 6px; margin-bottom: 8px;">'
            f'<span style="font-size: 13px; margin-right: 12px;">条目数: {info.get("entry_count", 0)}</span>'
            f'</div>'
            f'{desc_section}{latest_line}'
            f'</div>'
        )

    @classmethod
    def _probe_markdown(cls, info: dict) -> str:
        lines = [f"**{info.get('name', 'Unknown')}**", f"条目数: {info.get('entry_count', 0)}"]
        if info.get("description"):
            lines.append(f"> {info['description'][:100]}")
        if info.get("latest_title"):
            lines.append(f"最新: {info['latest_title']}")
        return "\n".join(lines)

    @classmethod
    def _probe_text(cls, info: dict) -> str:
        lines = [info.get("name", "Unknown"), f"条目数: {info.get('entry_count', 0)}"]
        if info.get("description"):
            lines.append(info["description"][:100])
        if info.get("latest_title"):
            lines.append(f"最新: {info['latest_title']}")
        return "\n".join(lines)

    @classmethod
    def _sublist_html(cls, subs: list) -> dict:
        rows = []
        for sub in subs:
            status_color = PRIMARY if sub.get("enabled") else SECONDARY
            status_text = "运行中" if sub.get("enabled") else "已暂停"
            name = sub.get("name") or sub.get("url", "")
            interval = sub.get("interval_minutes", 30)

            rows.append(
                f'<div style="padding: 8px; margin-bottom: 6px; background: {PRIMARY_BG}; border-radius: 6px;">'
                f'<div style="font-size: 14px; margin-bottom: 4px;">'
                f'<span style="color: {PRIMARY}; font-weight: bold; margin-right: 4px;">#{sub["id"]}</span>'
                f'{name}</div>'
                f'<div style="font-size: 12px; color: {SECONDARY};">'
                f'<span style="color: {status_color};">{status_text}</span> | '
                f'每 {interval} 分钟</div></div>'
            )

        return (
            f'<div style="padding: 12px; border-radius: 8px;">'
            f'<div style="color: {PRIMARY}; font-size: 15px; font-weight: bold; margin-bottom: 10px;">'
            f'订阅列表 ({len(subs)})</div>'
            f'{"".join(rows)}'
            f'</div>'
        )

    @classmethod
    def _sublist_markdown(cls, subs: list) -> str:
        lines = [f"**订阅列表** ({len(subs)})", ""]
        for sub in subs:
            status = "运行中" if sub.get("enabled") else "已暂停"
            name = sub.get("name") or sub.get("url", "")
            interval = sub.get("interval_minutes", 30)
            lines.append(f"- `#{sub['id']}` **{name}** - {status} | {interval}min")
        return "\n".join(lines)

    @classmethod
    def _sublist_text(cls, subs: list) -> str:
        lines = [f"订阅列表 ({len(subs)})", "----------"]
        for sub in subs:
            status = "运行中" if sub.get("enabled") else "已暂停"
            name = sub.get("name") or sub.get("url", "")
            interval = sub.get("interval_minutes", 30)
            lines.append(f"#{sub['id']} {name}")
            lines.append(f"   {status} | 每{interval}分钟")
        return "\n".join(lines)

    @classmethod
    def _confirm_html(cls, info: dict, interval: int, keywords: str) -> str:
        kw_line = ""
        if keywords:
            kw_tags = " ".join(
                f'<code style="font-size: 11px; background: {TAG_BG}; padding: 1px 5px; border-radius: 3px;">{kw.strip()}</code>'
                for kw in keywords.split(",") if kw.strip()
            )
            kw_line = (
                f'<div style="font-size: 12px; margin-top: 6px;">'
                f'<span style="color: {SECONDARY};">关键词:</span> {kw_tags}</div>'
            )

        return (
            f'<div style="padding: 12px; border-radius: 8px;">'
            f'<div style="color: {PRIMARY}; font-size: 15px; font-weight: bold; margin-bottom: 8px;">订阅成功</div>'
            f'<div style="padding: 8px; background: {PRIMARY_BG}; border-radius: 6px;">'
            f'<div style="font-size: 14px; font-weight: bold; margin-bottom: 4px;">{info.get("name", "")}</div>'
            f'<div style="font-size: 13px; color: {SECONDARY};">每 {interval} 分钟检查一次</div>'
            f'{kw_line}'
            f'</div></div>'
        )

    @classmethod
    def _confirm_markdown(cls, info: dict, interval: int, keywords: str) -> str:
        lines = [f"**订阅成功**", f"**{info.get('name', '')}**", f"每 {interval} 分钟检查一次"]
        if keywords:
            lines.append(f"关键词: `{keywords}`")
        return "\n".join(lines)

    @classmethod
    def _confirm_text(cls, info: dict, interval: int, keywords: str) -> str:
        lines = ["订阅成功", info.get("name", ""), f"每 {interval} 分钟检查一次"]
        if keywords:
            lines.append(f"关键词: {keywords}")
        return "\n".join(lines)

    @classmethod
    def build_batch_result(cls, results: list) -> Dict[str, str]:
        succeeded = [r for r in results if r["ok"]]
        failed = [r for r in results if not r["ok"]]
        success_names = ", ".join(r.get("name", r["url"]) for r in succeeded) if succeeded else "无"

        fail_lines_html = ""
        fail_lines_plain = []
        for f in failed:
            reason = f.get("reason", "无法解析")
            fail_lines_html += (
                f'<div style="font-size: 12px; color: #e74c3c; margin-bottom: 2px;">'
                f'{f["url"]} - {reason}</div>'
            )
            fail_lines_plain.append(f"  {f['url']} - {reason}")

        ok_count = len(succeeded)
        fail_count = len(failed)

        return {
            "html": (
                f'<div style="padding: 12px; border-radius: 8px;">'
                f'<div style="color: {PRIMARY}; font-size: 15px; font-weight: bold; margin-bottom: 8px;">批量添加结果</div>'
                f'<div style="font-size: 13px; margin-bottom: 4px;">'
                f'<span style="color: #27ae60;">成功 {ok_count} 个</span> | '
                f'<span style="color: #e74c3c;">失败 {fail_count} 个</span></div>'
                f'{fail_lines_html}'
                f'<div style="font-size: 11px; color: {SECONDARY}; margin-top: 6px;">已订阅: {success_names}</div>'
                f'</div>'
            ),
            "markdown": (
                f"**批量添加结果**\n"
                f"成功 {ok_count} 个 | 失败 {fail_count} 个\n"
                + ("\n".join(fail_lines_plain) + "\n" if fail_lines_plain else "")
                + f"已订阅: {success_names}"
            ),
            "text": (
                f"批量添加结果\n"
                f"成功 {ok_count} 个 | 失败 {fail_count} 个\n"
                + ("\n".join(fail_lines_plain) + "\n" if fail_lines_plain else "")
                + f"已订阅: {success_names}"
            ),
        }

    @classmethod
    def build_filter_menu(cls, is_admin: bool = False) -> Dict[str, str]:
        items = [
            ("1", "添加黑名单规则"),
            ("2", "添加白名单规则"),
            ("3", "查看当前规则"),
            ("4", "删除规则"),
        ]
        if is_admin:
            items.append(("5", "添加全局黑名单"))
            items.append(("6", "添加全局白名单"))

        items_html = "".join(
            f'<div style="font-size: 13px; margin-bottom: 4px;">'
            f'<span style="color: {PRIMARY}; font-weight: bold; margin-right: 8px;">{num}.</span>'
            f'{label}</div>'
            for num, label in items
        )
        md_lines = ["**过滤规则管理**\n"]
        for num, label in items:
            md_lines.append(f"{num}. {label}")
        md_lines.append("\n回复编号选择操作")
        text_lines = ["过滤规则管理"]
        for num, label in items:
            text_lines.append(f"{num}. {label}")
        text_lines.append("回复编号选择操作")

        return {
            "html": (
                f'<div style="padding: 12px; border-radius: 8px;">'
                f'<div style="color: {PRIMARY}; font-size: 15px; font-weight: bold; margin-bottom: 10px;">过滤规则管理</div>'
                f'{items_html}'
                f'<div style="font-size: 11px; color: {SECONDARY}; margin-top: 8px;">回复编号选择操作</div>'
                f'</div>'
            ),
            "markdown": "\n".join(md_lines),
            "text": "\n".join(text_lines),
        }

    @classmethod
    def build_filter_list(cls, filters: list) -> Dict[str, str]:
        if not filters:
            nope = "当前没有过滤规则"
            return {"html": nope, "markdown": nope, "text": nope}
        return {
            "html": cls._filter_list_html(filters),
            "markdown": cls._filter_list_markdown(filters),
            "text": cls._filter_list_text(filters),
        }

    @classmethod
    def build_filter_add_confirm(cls, rule: dict) -> Dict[str, str]:
        rt = "黑名单" if rule["rule_type"] == "blacklist" else "白名单"
        regex_tag = " (正则)" if rule.get("is_regex") else ""
        scope = "全局" if rule["target_type"] == "global" else f"{rule['target_type']}:{rule['target_id']}"
        return {
            "html": (
                f'<div style="padding: 12px; border-radius: 8px;">'
                f'<div style="color: {PRIMARY}; font-size: 15px; font-weight: bold; margin-bottom: 8px;">规则已添加</div>'
                f'<div style="padding: 8px; background: {PRIMARY_BG}; border-radius: 6px;">'
                f'<div style="font-size: 13px;"><b>类型:</b> {rt}{regex_tag}</div>'
                f'<div style="font-size: 13px;"><b>规则:</b> {rule["pattern"]}</div>'
                f'<div style="font-size: 12px; color: {SECONDARY};">作用域: {scope}</div>'
                f'</div></div>'
            ),
            "markdown": f"**规则已添加**\n类型: {rt}{regex_tag}\n规则: `{rule['pattern']}`\n作用域: {scope}",
            "text": f"规则已添加\n类型: {rt}{regex_tag}\n规则: {rule['pattern']}\n作用域: {scope}",
        }

    @classmethod
    def _filter_list_html(cls, filters: list) -> str:
        rows = []
        for f in filters:
            rt = "黑名单" if f["rule_type"] == "blacklist" else "白名单"
            rt_color = "#e74c3c" if f["rule_type"] == "blacklist" else "#27ae60"
            regex_tag = " [正则]" if f.get("is_regex") else ""
            scope = "全局" if f["target_type"] == "global" else f["target_type"]
            rows.append(
                f'<div style="padding: 8px; margin-bottom: 6px; background: {PRIMARY_BG}; border-radius: 6px;">'
                f'<div style="font-size: 14px; margin-bottom: 4px;">'
                f'<span style="color: {PRIMARY}; font-weight: bold; margin-right: 4px;">#{f["id"]}</span>'
                f'<span style="color: {rt_color}; font-size: 12px; margin-right: 6px;">[{rt}{regex_tag}]</span>'
                f'{f["pattern"]}</div>'
                f'<div style="font-size: 11px; color: {SECONDARY};">作用域: {scope}</div></div>'
            )
        return (
            f'<div style="padding: 12px; border-radius: 8px;">'
            f'<div style="color: {PRIMARY}; font-size: 15px; font-weight: bold; margin-bottom: 10px;">'
            f'过滤规则 ({len(filters)})</div>'
            f'{"".join(rows)}'
            f'</div>'
        )

    @classmethod
    def _filter_list_markdown(cls, filters: list) -> str:
        lines = [f"**过滤规则** ({len(filters)})", ""]
        for f in filters:
            rt = "黑名单" if f["rule_type"] == "blacklist" else "白名单"
            regex_tag = " [正则]" if f.get("is_regex") else ""
            scope = "全局" if f["target_type"] == "global" else f["target_type"]
            lines.append(f"- `#{f['id']}` [{rt}{regex_tag}] `{f['pattern']}` ({scope})")
        return "\n".join(lines)

    @classmethod
    def _filter_list_text(cls, filters: list) -> str:
        lines = [f"过滤规则 ({len(filters)})", "----------"]
        for f in filters:
            rt = "黑名单" if f["rule_type"] == "blacklist" else "白名单"
            regex_tag = " [正则]" if f.get("is_regex") else ""
            scope = "全局" if f["target_type"] == "global" else f["target_type"]
            lines.append(f"#{f['id']} [{rt}{regex_tag}] {f['pattern']}")
            lines.append(f"   作用域: {scope}")
        return "\n".join(lines)

    @staticmethod
    def _fmt_time(dt) -> str:
        if dt is None:
            return ""
        try:
            now = datetime.now(tz=timezone.utc)
            delta = now - dt
            if delta.days == 0:
                s = int(delta.total_seconds())
                if s < 60:
                    return "刚刚"
                if s < 3600:
                    return f"{s // 60} 分钟前"
                return f"{s // 3600} 小时前"
            if delta.days == 1:
                return "昨天"
            if delta.days < 7:
                return f"{delta.days} 天前"
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(dt)
