# ErisPulse-RssReader

ErisPulse RSS 订阅器模块——在聊天中订阅任意 RSS/Atom 源，自动推送更新。

## 功能

- 订阅任意 RSS/Atom 源，自动定时抓取并推送新内容
- 富文本卡片展示（Html > Markdown > Text 自动降级）
- 交互式菜单管理（`/rss` 即可进入）
- 快捷订阅（`/rss <URL>`）
- 关键词过滤（包含/排除）
- 多群/多用户独立订阅
- 智能去重，不重复推送
- 订阅暂停/恢复

## 安装

```bash
epsdk install ErisPulse-RssReader
```

或本地开发：

```bash
epsdk install -e /path/to/ErisPulse-RssReader
```

依赖：`feedparser>=6.0`、`beautifulsoup4>=4.12`（自动安装）

## 使用

### 交互式菜单

```
/rss
```

发送后显示菜单，回复编号即可操作：

1. 添加订阅
2. 查看订阅列表
3. 删除订阅
4. 暂停 / 恢复订阅
5. 测试 RSS 源
6. 立即推送

### 快捷订阅

```
/rss https://sspai.com/feed
```

### 添加订阅流程（对话式）

```
/rss
→ 回复 1
→ 输入 RSS 地址
→ 选择推送间隔（5分钟/15分钟/30分钟/1小时/3小时）
→ 设置关键词过滤（可选）
→ 完成
```

## 配置

配置文件位于 `config/config.toml`，首次加载自动生成：

```toml
[RssReader]
default_interval = 30       # 默认推送间隔（分钟）
max_items_per_push = 5      # 每次推送最大条数
auto_start = true            # 启动时自动开始抓取
max_subs_per_chat = 20      # 每个聊天最大订阅数
```

## 命令一览

| 命令 | 说明 |
|------|------|
| `/rss` | 打开交互式菜单 |
| `/rss <URL>` | 快速订阅 RSS 源 |

菜单内通过编号选择：查看列表、删除、暂停/恢复、测试源、立即推送。

## 推送效果

推送时自动检测平台能力，按 **Html > Markdown > Text** 优先级降级展示：

- 单条更新 → 详细卡片（标题、作者、时间、摘要、链接）
- 多条更新 → 摘要列表（标题 + 时间）

