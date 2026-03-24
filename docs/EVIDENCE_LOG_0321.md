# Evidence Log — 2026-03-21

## 1. Last Meeting's Actions

### 架构设计（3/20）
- 研究 SkyDiscover 论文，确定策略进化架构（岛模型 + 专家视角分离）
- 开 `feature/strategy-evolve` 分支，写 `STRATEGY_EVOLVE_ARCHITECTURE.md` v2
- 拆成 6 份详细开发文档（总纲 + QP/SI/EE/WV/IST），共 6149 行规划
- 在 `feature/continuous-prediction` 分支写了 QP + PredictionEngine 代码

### 全模块实现（3/21）
- 实现 QP（Question Parser）— 题目解析 + 8 维策略编译 + 种子策略 | +34 测试
- 实现 SI（Strategy Island）— 策略岛管理 + 采样 + 淘汰 + 持久化 | +85 测试
- 实现 EE（Evolution Engine）— Refine/Diverge/Spawn + 环形迁移 | +47 测试
- 实现 WV（Weighted Voting）— 加权投票 + LLM Judge 仲裁 | +57 测试
- 实现 IST（Inline Step Trace）— 运行时追踪 + 97% token 压缩 | +63 测试
- 全部模块串联进 `multi_path.py`，feature flag 统一控制 | +14 集成测试
- 5 份设计文档完成度：233 ✅ / 0 ❌ / 10 ⏭️

### 系统打通（3/21）
- Reflector experience → EE refine prompt（进化有了"为什么输"的上下文）
- OpenViking write-through（后台守护线程）+ 语义搜索读取，全部 Store 接入
- EE 假 LLM 换成真实 OpenRouter/GPT-5 调用
- 做题与进化流程分离（`reflect_and_evolve()` 独立函数）
- 测试覆盖：484 → 820（+336），全绿，零回归

### 实验运行（3/21）
- Run 1：单路径（配置错误未开 multi_path）— 5/10 (50%)
- Run 2：5 路径 max_concurrent=5 — 2/10 (20%)，搜索全崩
- Run 3：5 路径 max_concurrent=1 + 真 Google 搜索 — **7/10 (70%)**

## 2. Blockers

### 搜索基础设施（核心 blocker）
- `google_search` 工具底层实际是 DuckDuckGo，不是 Google — 名字误导
- DuckDuckGo 在 5 路径并发下即被限速，`max_concurrent=5` 时 49/50 路径搜索返回 0 结果
- 已通过加入 `tool-google-search`（Serper/真 Google）+ `tool-serpapi-search` + 降 `max_concurrent=1` 缓解
- Run 3 (7/10) 验证了搜索修复后性能恢复正常

### 未验证的闭环
- 做题→反思→进化→再做题的完整闭环还没跑过
- `reflect_and_evolve()` 写好了但未实际调用
- 不确定进化后策略的存储/加载/下次做题时读取是否通畅

## 3. Decisions / Learnings

### Decisions
1. **策略进化用 SkyDiscover 岛模型** — 每岛一个专家视角（信息追踪/机制分析/历史类比/市场信号/对抗验证），避免策略趋同
2. **做题和进化分离** — 可以攒多轮数据再批量进化，数据更充分效果更好
3. **OpenViking 存储用 write-through + 后台线程** — 保持同步接口兼容，不改现有代码的 sync/async 模式
4. **Reflector → EE 打通（而非 EE 直接读 IST）** — IST digest 已经给 Reflector 看过，Reflector 产出的结构化 experience 更适合进化 prompt
5. **feature flag 统一用 `question_parser.enabled`** — 一个开关控制全部新模块，关闭时行为完全不变

### Learnings
1. **搜索是最脆弱的环节** — 策略/投票/进化都是上层逻辑，搜索崩了一切白搭
2. **工具命名骗人** — `google_search` 底层是 DuckDuckGo，真 Google 是 `tool-google-search`（Serper）
3. **冷启动 ≈ 旧系统** — 无历史数据的策略进化系统性能（70%）和不进化的旧系统持平，进化的价值需要多轮验证
4. **并发是隐形杀手** — `max_concurrent=5` → 25 并发搜索 → DuckDuckGo 全面限速，必须控制总并发路径数
5. **R2 的 9/10 有水分** — before_date 泄漏，修复后真实水平 7/10；葡萄牙总统和 CECOT 两道题是信息死角，四轮都没对

## 4. Next Meeting — New Actions

### 进化实验（优先级 P0）
- [ ] 准备 65 题实验数据（等 ground truth 传入）
- [ ] Phase 1：跑 65 题基线（冷启动，max_concurrent=1，~4-5 小时）
- [ ] Phase 2：触发 `reflect_and_evolve()`，检查进化报告和新策略
- [ ] Phase 3：用进化后的策略再跑一轮，对比 R1 vs R2 准确率
- [ ] 分析：按题型/Level 拆分对比，确认进化是否有效

### 搜索优化（P1）
- [ ] 监控 Serper/SerpAPI 配额消耗
- [ ] 考虑搜索工具选择策略（不同策略用不同搜索引擎？）
- [ ] 评估是否需要增加搜索并发容忍度（比如 max_concurrent=2）

### 系统完善（P2）
- [ ] 验证进化后策略的持久化→加载→使用完整链路
- [ ] Anthropic OAuth 403 修复（飞书会话不稳定）
- [ ] 考虑线上 65 题提交流程
