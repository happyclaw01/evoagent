# 子模块 C：Strategy Evolver（策略进化器）

## 1. 目标

从 ExperienceStore 中积累的经验中提炼出跨题目的**元知识**——"哪类题用哪种策略效果好"，并在连续失败时自动生成 prompt 优化建议。实现文档中描述的"不训练参数，通过外部 memory 实现类似 RL policy improvement 的效果"。

## 2. 需求

### 2.1 策略偏好聚合（C1）

从 ExperienceStore 读取所有经验，按 `question_type × strategy_name` 交叉统计成功率，输出策略偏好表：

```json
{
  "version": "2026-03-11T10:00:00",
  "stats": {
    "finance_market": {
      "search_heavy":     {"total": 20, "correct": 16, "accuracy": 0.80},
      "code_compute":     {"total": 8,  "correct": 2,  "accuracy": 0.25},
      "multi_source_verify": {"total": 5, "correct": 4, "accuracy": 0.80}
    },
    "logistics_planning": {
      "code_compute":     {"total": 12, "correct": 9,  "accuracy": 0.75},
      "search_heavy":     {"total": 6,  "correct": 1,  "accuracy": 0.17}
    }
  },
  "recommendations": {
    "finance_market": ["search_heavy", "multi_source_verify"],
    "logistics_planning": ["code_compute"]
  }
}
```

**规则：**
- 每种 question_type 下，按 accuracy 降序排列策略
- `recommendations` 只保留 accuracy ≥ 0.5 且样本数 ≥ 3 的策略
- 样本数不足时标记为 `"insufficient_data"`，不做推荐

### 2.2 失败模式聚合

按 `question_type × failure_pattern` 聚合，找出每类题目最常见的失败模式：

```json
{
  "finance_market": {
    "top_failures": [
      {"pattern": "outdated_info", "count": 8, "typical_lesson": "Always verify data recency..."},
      {"pattern": "wrong_reasoning", "count": 3, "typical_lesson": "Cross-check with multiple sources..."}
    ]
  }
}
```

### 2.3 Prompt 自优化（C2）

针对高频失败题型，调用 LLM 生成 prompt patch：

**触发条件：**
- 某 question_type 近 N 次（默认 5 次）accuracy < 0.4
- 或某 failure_pattern 出现次数 ≥ 3 次

**输出格式（prompt_overrides.jsonl）：**
```json
{
  "question_type": "finance_market",
  "trigger": "accuracy < 0.4 in last 5 attempts",
  "patch_type": "append",
  "content": "For financial prediction questions, always: 1) Check the event date vs. current date, 2) Search for the latest market data within 24h, 3) Consider contrarian signals if consensus is strong.",
  "created_at": "2026-03-11T10:00:00",
  "auto_approved": false,
  "applied": false
}
```

**关键约束：**
- `auto_approved: false` — 默认不自动生效，需人工 review
- 支持 `--auto-approve` 命令行参数跳过人工 review（用于全自动实验）
- patch 有版本记录，支持回滚（按 created_at 排序，取最新生效的）

## 3. 接口设计

```python
class StrategyEvolver:
    """策略进化器：从经验中提炼元知识 + 自动优化 prompt"""

    def __init__(
        self,
        experience_store: ExperienceStore,
        preferences_file: str,           # strategy_preferences.json 路径
        prompt_overrides_file: str,       # prompt_overrides.jsonl 路径
    ):
        """
        Args:
            experience_store: 经验存储实例
            preferences_file: 策略偏好表输出路径
            prompt_overrides_file: prompt patch 输出路径
        """

    def aggregate_strategy_preferences(self) -> dict:
        """
        从经验中聚合策略偏好，写入 preferences_file。

        Returns:
            策略偏好表 dict（同时写入文件）
        """

    def aggregate_failure_patterns(self) -> dict:
        """
        从经验中聚合失败模式。

        Returns:
            按 question_type 分组的失败模式统计
        """

    async def generate_prompt_patches(
        self,
        llm_client: Any,
        model: str = "",
        auto_approve: bool = False,
    ) -> List[dict]:
        """
        分析高频失败题型，调用 LLM 生成 prompt 优化建议。
        写入 prompt_overrides_file。

        Args:
            llm_client: LLM 调用客户端
            model: 用于生成 patch 的模型
            auto_approve: 是否自动批准（默认 False）

        Returns:
            生成的 prompt patch 列表
        """

    def load_strategy_preferences(self) -> dict:
        """读取已保存的策略偏好表（供子模块 D 调用）"""

    def load_active_prompt_overrides(
        self,
        question_type: Optional[str] = None,
    ) -> List[dict]:
        """
        读取已生效的 prompt patch（auto_approved=True 或 applied=True）。
        供子模块 D 注入时调用。

        Args:
            question_type: 按题型过滤

        Returns:
            生效的 patch 列表
        """

    def approve_patch(self, index: int) -> None:
        """
        人工批准第 index 条 patch（将 auto_approved 设为 True）。
        供 CLI / notebook 中人工 review 时调用。
        """

    def rollback_patch(self, index: int) -> None:
        """
        回滚第 index 条 patch（将 applied 设为 False）。
        """
```

## 4. 接入点（改动位置）

| 位置 | 改动 |
|------|------|
| `src/evolving/strategy_evolver.py` | **新建**本文件 |
| `conf/config.yaml` | 新增 `evolving.strategy_preferences_file` 和 `evolving.prompt_overrides_file` |
| `scripts/run_reflection.py` | 批量反思完成后可选触发 `aggregate_strategy_preferences()` |
| 新建 `scripts/run_evolve.py` | 独立脚本：聚合策略 + 生成 prompt patch + 人工 review 流程 |

## 5. 触发时机

```
                      ┌──────────────────────────────┐
                      │    什么时候触发策略进化？       │
                      └──────────────────────────────┘

  方式 A（推荐）：批量反思完成后手动触发
    run_reflection.py --evolve  →  reflect_on_batch()  →  aggregate_strategy_preferences()
                                                       →  generate_prompt_patches()

  方式 B：独立脚本
    run_evolve.py  →  直接读 ExperienceStore  →  聚合 + 生成 patch

  方式 C（未来）：pipeline 中每 N 个任务自动触发一次
    pipeline.py  →  每完成 N 个任务  →  aggregate_strategy_preferences()
```

## 6. Prompt Patch 生成 Prompt 模板

```
你是一个 AI 系统的 prompt 优化专家。以下是某类题目的历史失败分析：

题目类型：{question_type}
近期表现：{recent_accuracy}（{total} 题中答对 {correct} 题）
高频失败模式：
{failure_patterns}

典型失败案例的 lesson：
{lessons}

请生成一段简洁的 prompt 补充指令（50-150 字），用于插入到 agent 的 system prompt 中，
帮助 agent 在遇到此类题目时避免上述错误模式。

要求：
- 给出具体、可执行的指令，不要笼统建议
- 针对失败模式逐一给出对策
- 不要重复 system prompt 中已有的通用指令
```

## 7. 配置扩展

```yaml
# conf/config.yaml
evolving:
  enabled: false
  experience_file: "../../data/experiences.jsonl"
  max_experiences: 5
  reflection_model: ""
  auto_reflect: true
  # 新增（子模块 C）
  strategy_preferences_file: "../../data/strategy_preferences.json"
  prompt_overrides_file: "../../data/prompt_overrides.jsonl"
  min_samples_for_recommendation: 3      # 策略推荐最少样本数
  failure_threshold_for_patch: 0.4       # accuracy 低于此值触发 prompt patch
  auto_approve_patches: false            # 是否自动批准 prompt patch
```

## 8. 测试要点

- 聚合正确性：手动构造 10 条经验，验证 accuracy 计算和排序
- 样本不足处理：< min_samples 时不输出推荐
- Prompt patch 生成：验证 LLM 输出被正确解析和存储
- Patch 审批流程：approve / rollback 操作正确修改文件
- 与子模块 D 对接：`load_strategy_preferences()` 和 `load_active_prompt_overrides()` 返回值格式正确
