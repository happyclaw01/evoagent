# EvoAgent 变更记录

## [0.1.0] - 2026-03-13

### 新增
- **EA-001** 多路径调度器：支持 N 条并行 Agent 路径
- **EA-002** 策略变体：breadth_first / depth_first / lateral_thinking
- **EA-003** LLM 投票评选：答案分歧时用 LLM Judge 裁决
- **EA-004** 多数投票快速路径：答案一致时跳过 Judge
- **EA-005** 独立工具管理器：每路径独立 ToolManager
- **EA-006** 路径级日志隔离
- **EA-007** 主控日志聚合
- **EA-008** 路径数动态配置 (`NUM_PATHS` 环境变量)
- **EA-301** 本地 Python 沙箱（替代 E2B）
- **EA-302** DuckDuckGo 搜索（替代 Serper）
- **EA-303** OpenRouter LLM 配置

### 测试
- 2路径对比测试通过：depth_first 成功找到 arxiv 论文标题，breadth_first 未找到
- LLM Judge 正确选择 depth_first 答案
