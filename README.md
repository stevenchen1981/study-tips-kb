# 学习 Tips 资料库（study-tips-kb）

面向家里初中生的 Kindle 每日学习提醒应用的**内容数据层**。
应用形态参考已有的 kindle-daily-panel 架构（109 上 Pillow 渲染 1072×1448 灰度 PNG + server.py 静态页，Kindle 浏览器定时刷新查看），本仓库只负责"内容从哪来"，不负责渲染与调度。

## 设计原则

- **轻提醒，不占用时间**：每次只显示 1 条 tip，早晚各一次，读完即走，不做强制任务。
- **跟学习进度走**：由 `progress.json`（待建）声明当前学到哪个单元，展示层只从当前单元的 tips 池里轮换。
- **数据与展示分离**：本目录纯 JSON，不含任何渲染代码。

## 目录结构

```
study-tips-kb/
├── README.md
├── english/
│   └── yilin2024/          # 牛津译林版 2024 新教材
│       └── grade8/
│           ├── 8a.json     # 上册 8 单元
│           └── 8b.json     # 下册 8 单元
└── tools/
    └── validate.py         # 数据完整性校验
```

后续可按同样结构扩展：`english/yilin2024/grade7/`、`grade9/`、`math/...`、`physics/...` 等。

## 数据格式（schema）

顶层：

```jsonc
{
  "book":  { "subject", "publisher", "edition", "grade", "grade_cn", "term", "term_code", "verified_at", "note" },
  "units": [ /* 8 个单元 */ ]
}
```

每个 unit：

| 字段 | 说明 |
|------|------|
| `unit` | 单元序号 1-8 |
| `title` | 单元英文标题 |
| `topic_cn` | 单元主题（中文） |
| `estimated_weeks` | 预计学习周数（用于 tip 轮换估算） |
| `core_vocab` | 核心词汇 `[{en, cn}]` |
| `key_phrases` | 重点短语 `[{en, cn}]` |
| `grammar` | `{name, key_points[], examples[]}` 本单元核心语法 |
| `sentence_patterns` | 重点句型 |
| `writing_topic` | 单元写作话题 |
| `exam_focus` | 考试高频易错点 |
| `tips` | tip 池，见下 |

每条 tip：

| 字段 | 说明 |
|------|------|
| `id` | 全局唯一，格式 `{term}-u{单元}-{序号}` |
| `slot` | `morning`（仅早间）/ `evening`（仅晚间）/ `any`（通用） |
| `tag` | 词汇 / 语法 / 句型 / 易错 / 自测 / 写作 / 口语 / 方法 |
| `text` | tip 正文，控制在一屏内（建议 ≤ 60 字符） |

## 运行时实现（server.py，已上线）

109 上常驻服务（端口 8001，`./run.sh start|stop|restart|status`，cron @reboot 自启）：

1. 读取 `progress.json` 定位当前单元：`override_unit` 优先；否则按 `term_start + weeks_per_unit` 自动推算（默认 2026-09-01 起每单元 2.5 周，学期结束自动停在 Unit 8）。
2. 时段划分：12 点前取 `morning`+`any` 池，12 点后取 `evening`+`any` 池，每天早晚各一条、互不重复。
3. 随机种子 = `日期|时段|单元`，同一天同时段内容稳定，跨天/跨时段自动换。
4. 页面 5 分钟 meta refresh（`REFRESH_SECONDS = 300`，server.py 内改）——Kindle 固定停在页面上即可。注意：tip 内容本身每天只变两次（早/晚各换一条），刷新频繁但内容按天稳定是设计如此；Kindle 休眠唤醒后等下一次 refresh 即恢复。Kindle 是否在刷新可看 109 日志：`tail ~/study-tips-kb/logs/server.log`。

接口：
- `http://192.168.31.109:8001/study` — Kindle 看板页（满屏大字、白底黑字适配墨水屏）
- `http://192.168.31.109:8001/study.json` — JSON API（给未来其他端用）
- `http://192.168.31.109:8001/health` — 健康检查

## 校验

```bash
python3 tools/validate.py
```

检查：JSON 可解析、单元数=8、tip id 唯一、slot/tag 取值合法、必要字段齐全。

## 内容说明与校准

- 单元目录、语法分布已对照 2024 新教材（8A：Friendship ~ Safe and sound；8B 2026春版：Past and present ~ A green world）核实。8A U6/U7 的语法为课本实际的"动词及基本句型 I/II"（主谓/主谓宾/主系表；双宾语与宾补），已按 Grammar 课件证据修正。
- 内容参考了社区/教师已总结的公开资料：小红书教师向笔记（译林八上知识重难点指南，含四会词、词形变化、易错辨析、中考真题考向）、学科网/21世纪教育网语法精讲、百度文库语法口诀（完成时口诀、被动三步法、情态被动口诀等）。
- **词表**按单元主题与公开知识清单整理，未逐词对照课本 Wordlist；建议拿到课本后核对一遍，直接编辑 JSON 增删即可。
- tip 的早晚时段分配目前是内容视角（早读类/睡前自测类），实际展示时段可由应用层再平衡。

## Roadmap（应用整体）

1. ✅ **第一步**：本地资料库 · 英语 · 译林2024 · 八年级（16 单元 / 176 tips）
2. ✅ **第二步**：社区内容吸收（小红书教师笔记等）修正语法分布、扩充易错点与口诀
3. ✅ **第三步**：资料库部署 109（`/home/steven/study-tips-kb/`，rsync 同步）+ 看板服务（`server.py` :8001，早晚随机、每日轮换，Kindle 固定访问 `/study`）
4. ⬜ 扩展科目：数学、物理等（复用同一 schema 与服务）
5. ⬜ 可选增强：错题/易错点加权出现、周日晚"本周回顾"模式
