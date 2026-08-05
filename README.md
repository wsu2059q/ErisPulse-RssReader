<div align="center">

<img src=".github/assets/RssReaderIcon.svg" width="120" alt="RssReader" />
<span style="font-size:44px;color:#c8c8c8;margin:0 18px;vertical-align:middle;">×</span>
<img src=".github/assets/ErisPulseLogo.png" height="120" alt="ErisPulse" />

# ErisPulse-RssReader

**RSS 订阅器 · Subscribe any RSS/Atom feed and get push notifications in chat**

<p>
  <a href="https://pypi.org/project/ErisPulse-RssReader/"><img src="https://img.shields.io/pypi/v/ErisPulse-RssReader?style=for-the-badge&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="https://pypi.org/project/ErisPulse-RssReader/"><img src="https://img.shields.io/badge/Python-3.10+-FFD43B?style=for-the-badge&logo=python&logoColor=blue" alt="Python"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue?style=for-the-badge" alt="License"></a>
  <a href="https://github.com/wsu2059q/ErisPulse-RssReader"><img src="https://img.shields.io/github/stars/wsu2059q/ErisPulse-RssReader?style=for-the-badge&logo=github&color=brightgreen" alt="Stars"></a>
  <a href="https://pepy.tech/project/ErisPulse-RssReader"><img src="https://img.shields.io/pepy/dt/ErisPulse-RssReader?style=for-the-badge&color=blue" alt="Downloads"></a>
  <a href="https://github.com/ErisPulse/ErisPulse"><img src="https://img.shields.io/badge/Powered_by-ErisPulse-FF6B9D?style=for-the-badge&logo=bookstack&logoColor=white" alt="ErisPulse"></a>
</p>

</div>

---

[ErisPulse](https://github.com/ErisPulse/ErisPulse) 的全功能 RSS/Atom 订阅器模块。在聊天中订阅任意源，按计划自动轮询抓取并以富文本卡片推送新内容。配备交互式菜单、批量导入、关键词过滤、多群隔离，以及**订阅健康检查**——定时探活全部源，发现失效链接自动通知所在群。

### 功能特性

| 功能 | 说明 |
|------|------|
| 订阅抓取 | 订阅任意 RSS/Atom 源，定时抓取并推送新内容 |
| 富文本卡片 | 自动降级渲染：Html > Markdown > Text |
| 交互式菜单 | `/rss` 进入引导式菜单，回复编号即可操作 |
| 快捷订阅 | `/rss <URL>` 一键订阅 |
| 批量添加 | 一次粘贴多个地址批量导入 |
| 关键词过滤 | 黑名单 / 白名单，普通关键词或正则，会话级或全局级 |
| 多目标独立 | 多群 / 多用户各自独立订阅 |
| 智能去重 | 同一条目绝不重复推送 |
| 暂停 / 恢复 | 随时暂停或恢复任一订阅 |
| 健康检查 | 定时探活全部源，失效源标记并 @订阅人通知到群 |
| 导出订阅 | 一键导出全部订阅列表 |
| 仪表盘 | 网页端完整增删改查 + 改 URL + 一键清理失效源 |

### 安装

```bash
epsdk install RssReader
# 或
pip install ErisPulse-RssReader
```

> 依赖 `feedparser>=6.0`、`beautifulsoup4>=4.12` 已在依赖中声明，安装时自动拉取。

### 使用

模块加载后通过斜杠命令交互：

### 命令列表

| 命令 | 说明 |
|------|------|
| `/rss` | 打开交互式菜单 |
| `/rss <URL>` | 快速订阅 RSS 源 |

菜单内回复编号操作：

| 编号 | 操作 |
|------|------|
| 1 | 添加订阅 |
| 2 | 查看订阅列表 |
| 3 | 删除订阅 |
| 4 | 暂停 / 恢复订阅 |
| 5 | 测试 RSS 源 |
| 6 | 立即推送 |
| 7 | 批量添加订阅 |
| 8 | 过滤规则管理 |
| 9 | 导出订阅 |
| 10 | 修改推送间隔 |
| 11 | 订阅健康检查（管理本人添加的失效源；管理员可管理全部） |

### HTTP API

模块注册以下 HTTP 端点：

| 端点 | 说明 |
|------|------|
| `GET /RssReader/api/stats` | 订阅 / 过滤统计 |
| `GET /RssReader/api/subscriptions` | 查询订阅（可选 `target_type` & `target_id`） |
| `POST /RssReader/api/subscriptions` | 添加订阅 |
| `GET /RssReader/api/subscriptions/export` | 导出全部订阅 |
| `GET /RssReader/api/subscriptions/unhealthy` | 查询失效订阅 |
| `POST /RssReader/api/subscriptions/health-check` | 立即体检 |
| `POST /RssReader/api/subscriptions/purge-unhealthy` | 一键删除全部失效 |
| `PUT /RssReader/api/subscriptions/{id}` | 更新订阅（支持改 `url`） |
| `DELETE /RssReader/api/subscriptions/{id}` | 删除订阅 |
| `POST /RssReader/api/subscriptions/{id}/toggle` | 暂停 / 恢复 |
| `GET /RssReader/api/filters` | 查询过滤规则 |
| `POST /RssReader/api/filters` | 添加过滤规则 |
| `DELETE /RssReader/api/filters/{id}` | 删除过滤规则 |

### 配置

首次加载自动生成默认配置，可在 ErisPulse 配置中修改 `RssReader` 节：

```toml
[RssReader]
default_interval = 30          # 默认推送间隔（分钟）
max_items_per_push = 5         # 每次推送最大条数
auto_start = true              # 启动时自动开始抓取
max_subs_per_chat = 20         # 每个聊天最大订阅数
admins = []                    # 管理员用户 ID（健康检查可管理全部订阅）
health_check_interval = 1440   # 健康检查间隔（分钟）
health_check_fail_threshold = 3 # 连续失败几次判定失效
health_check_probe_timeout = 10 # 体检单个源的最长超时（秒）
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `default_interval` | `30` | 默认推送间隔（分钟） |
| `max_items_per_push` | `5` | 每次推送最大条数 |
| `auto_start` | `true` | 启动时自动开始抓取 |
| `max_subs_per_chat` | `20` | 每个聊天最大订阅数 |
| `admins` | `[]` | 管理员用户 ID（健康检查可管理全部订阅） |
| `health_check_interval` | `1440` | 健康检查间隔（分钟） |
| `health_check_fail_threshold` | `3` | 连续失败几次判定失效 |
| `health_check_probe_timeout` | `10` | 体检单个源最长超时（秒） |

### 推送效果

推送时自动检测平台能力，按 **Html > Markdown > Text** 优先级降级展示：

- 单条更新 → 详细卡片（标题、作者、时间、摘要、链接）
- 多条更新 → 摘要列表（标题 + 时间）

### 架构

```
RssReader/
├── Core.py          模块入口，注册命令、HTTP 路由与仪表盘视图
├── rss.py           RSS/Atom 抓取与解析，FeedItem 数据模型，源探活
├── store.py         存储层，订阅 / 历史 / 过滤规则 CRUD + 健康状态
├── scheduler.py     调度器，逐源轮询 + 健康检查任务 + 失效通知
└── templates.py     Html / Markdown / Text 降级模板
```

> 自 v1.2 起，存储层为每条订阅记录 `added_by / last_status / last_check_at / last_error / fail_count`，支持定时健康检查；添加者可管理自己添加的失效源，管理员可管理全部。

## License

- Code: [MIT License](LICENSE)

---

<div align="center">

**Related** · [ErisPulse](https://github.com/ErisPulse/ErisPulse) · [Documentation](https://www.erisdev.com) · [Issues](https://github.com/wsu2059q/ErisPulse-RssReader/issues)

</div>
