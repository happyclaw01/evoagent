# 子模块 D：Experience Injector（经验注入层）

## 1. 目标

在 Agent 开始解题前，智能检索相关经验、策略偏好和 prompt patch，统一注入到 system prompt 中。替代当前 `orchestrator.py:928-950` 中简陋的注入逻辑。

## 2. 需求

### 2.1 当前题目标签提取

解题前先对 `task_description` 做轻量分类，提取结构化标签用于经验检索：

```python
# 输出示例
{
    "question_type": "finance_market",
    "reasoning_type": "numerical_computation",
    "knowledge_domain": "finance",
    "level": 3
}
```

**实现方式（二选一，按成本选择）：**
- **方式 A（轻量）：** 基于关键词规则匹配（零 API 成本，覆盖率有限）
- **方式 B（精准）：** 调用 LLM 做一次轻量分类（消耗少量 token，更准确）

建议默认用方式 A，配置项可切换为方式 B。

### 2.2 经验检索与注入

基于提取的标签，从 ExperienceStore 检索相关经验：

- **失败经验注入**：检索同类题目的失败 lesson（避免重复犯错）
- **成功经验注入**：检索同类题目的成功 lesson（复用好的策略）
- 检索逻辑：先精确匹配 `question_type + reasoning_type`，匹配不足时放宽到只匹配 `question_type`

### 2.3 策略偏好注入

从子模块 C 的策略偏好表中读取当前题型的推荐策略：

```
注入示例（追加到 system prompt）：

# Strategy Recommendations for This Question Type
Based on past performance on similar "finance_market" questions:
- Recommended strategies: search_heavy (80% accuracy), multi_source_verify (80% accuracy)
- Avoid: code_compute (25% accuracy on this type)
```

### 2.4 Prompt Patch 注入

从子模块 C 的 prompt_overrides 中读取已生效的 patch，追加到 system prompt：

```
注入示例：

# Special Instructions for finance_market Questions
For financial prediction questions, always:
1) Check the event date vs. current date
2) Search for the latest market data within 24h
3) Consider contrarian signals if consensus is strong
```

### 2.5 注入量控制

所有注入内容的总 token 数不能过大，否则挤占正常 prompt 空间：

- 设定总上限（默认 2000 tokens，约 8000 字符）
- 优先级：prompt patch > 失败经验 > 策略偏好 > 成功经验
- 超出上限时按优先级截断

## 3. 接口设计

```python
class ExperienceInjector:
    """
    经验注入器：在 Agent 解题前检索并注入相关经验。
    替代 orchestrator.py 中现有的注入逻辑。
    """

    def __init__(
        self,
        experience_store: ExperienceStore,
        strategy_evolver: Optional[StrategyEvolver] = None,
        cfg: Optional[DictConfig] = None,
    ):
        """
        Args:
            experience_store: 经验存储实例
            strategy_evolver: 策略进化器实例（可选，用于读取偏好和 patch）
            cfg: evolving 配置段
        """

    def classify_task(
        self,
        task_description: str,
        llm_client: Any = None,
    ) -> dict:
        """
        对当前题目做轻量分类，提取结构化标签。

        Args:
            task_description: 题目描述文本
            llm_client: 可选，传入时使用 LLM 分类（方式 B），否则用规则（方式 A）

        Returns:
            {
                "question_type": str,
                "reasoning_type": str,
                "knowledge_domain": str,
                "level": Optional[int],
            }
        """

    def inject(
        self,
        task_description: str,
        llm_client: Any = None,
        max_tokens: int = 2000,
    ) -> str:
        """
        核心方法：检索相关经验 + 策略偏好 + prompt patch，
        格式化为可直接追加到 system prompt 的文本。

        Args:
            task_description: 当前题目描述
            llm_client: 可选，用于 LLM 分类
            max_tokens: 注入内容总 token 上限

        Returns:
            注入文本（为空时返回 ""）。
            调用方直接拼接到 system prompt 末尾即可。
        """

    def _retrieve_experiences(
        self,
        task_labels: dict,
        max_failures: int = 3,
        max_successes: int = 2,
    ) -> tuple[List[dict], List[dict]]:
        """
        基于题目标签检索相关经验。

        Returns:
            (failure_experiences, success_experiences)
        """

    def _retrieve_strategy_recommendations(
        self,
        question_type: str,
    ) -> Optional[str]:
        """
        从策略偏好表中读取推荐策略，格式化为文本。

        Returns:
            格式化文本，或 None
        """

    def _retrieve_prompt_patches(
        self,
        question_type: str,
    ) -> Optional[str]:
        """
        从 prompt_overrides 中读取生效的 patch。

        Returns:
            patch 文本，或 None
        """

    def _assemble_and_truncate(
        self,
        prompt_patch: Optional[str],
        failure_text: str,
        strategy_text: Optional[str],
        success_text: str,
        max_tokens: int,
    ) -> str:
        """
        按优先级组装所有注入内容，超出 max_tokens 时截断低优先级部分。

        优先级：prompt_patch > failure_text > strategy_text > success_text
        """
```

## 4. 接入点（改动位置）

| 位置 | 改动 |
|------|------|
| `src/evolving/experience_injector.py` | **新建**本文件 |
| `src/core/orchestrator.py:928-950` | **替换**现有注入逻辑为 `ExperienceInjector.inject()` |
| `src/core/orchestrator.py:952-956` | 注入文本拼接方式不变，但数据来源改为 injector |
| `src/utils/prompt_utils.py:266-268` | 接口不变，`experience_text` 参数由 injector 填充 |

## 5. Orchestrator 改造示意

```python
# orchestrator.py 改动前（:928-956）
# ---- 旧代码 ----
experience_text = ""
evolving_cfg = self.cfg.get("evolving", None)
if evolving_cfg and evolving_cfg.get("enabled", False):
    try:
        from ..evolving.reflector import load_experiences, format_experiences_for_prompt
        exp_file = evolving_cfg.get("experience_file", "")
        max_exp = evolving_cfg.get("max_experiences", 5)
        experiences = load_experiences(experience_file=exp_file, max_count=max_exp, only_failures=True)
        experience_text = format_experiences_for_prompt(experiences)
        ...
    except Exception as e:
        logger.warning(f"Failed to load experiences: {e}")

# ---- 新代码 ----
experience_text = ""
evolving_cfg = self.cfg.get("evolving", None)
if evolving_cfg and evolving_cfg.get("enabled", False):
    try:
        from ..evolving.experience_store import ExperienceStore
        from ..evolving.experience_injector import ExperienceInjector
        from ..evolving.strategy_evolver import StrategyEvolver  # 可选

        store = ExperienceStore(evolving_cfg.get("experience_file", ""))

        # 策略进化器（可选，没有配置文件时跳过）
        evolver = None
        prefs_file = evolving_cfg.get("strategy_preferences_file", "")
        overrides_file = evolving_cfg.get("prompt_overrides_file", "")
        if prefs_file or overrides_file:
            evolver = StrategyEvolver(store, prefs_file, overrides_file)

        injector = ExperienceInjector(
            experience_store=store,
            strategy_evolver=evolver,
            cfg=evolving_cfg,
        )
        experience_text = injector.inject(
            task_description=task_description,
            max_tokens=evolving_cfg.get("max_inject_tokens", 2000),
        )
        if experience_text:
            self.task_log.log_step(
                "info",
                "Main Agent | Self-Evolving",
                f"Injected experience context ({len(experience_text)} chars)",
            )
    except Exception as e:
        logger.warning(f"Failed to inject experiences: {e}")
```

## 6. 注入输出格式示例

```
# ===== Self-Evolving Context =====

## Special Instructions for finance_market Questions
For financial prediction questions, always:
1) Check the event date vs. current date
2) Search for the latest market data within 24h
3) Consider contrarian signals if consensus is strong

## Lessons from Past Predictions
- [FAIL] Oil price prediction (error: outdated_info): Always verify the data timestamp. Prices from 48h ago may be stale.
- [FAIL] Stock earnings estimate (error: wrong_reasoning): Cross-check earnings estimates from at least 2 independent sources.
- [OK] Bond yield forecast: Compare current yield curve shape with historical patterns for better directional prediction.

## Strategy Recommendations
Based on past performance on similar "finance_market" questions:
- Recommended: search_heavy (80% acc), multi_source_verify (80% acc)
- Avoid: code_compute (25% acc on this type)
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
  strategy_preferences_file: "../../data/strategy_preferences.json"
  prompt_overrides_file: "../../data/prompt_overrides.jsonl"
  min_samples_for_recommendation: 3
  failure_threshold_for_patch: 0.4
  auto_approve_patches: false
  # 新增（子模块 D）
  max_inject_tokens: 2000              # 注入内容总 token 上限
  classify_method: "rule"              # "rule"（关键词规则）或 "llm"（LLM 分类）
  inject_failures: true                # 是否注入失败经验
  inject_successes: true               # 是否注入成功经验
  inject_strategy_recommendations: true # 是否注入策略偏好
  inject_prompt_patches: true          # 是否注入 prompt patch
```

## 8. 测试要点

- 规则分类：给定 10 种典型 task_description，验证 classify_task 输出正确标签
- 检索降级：精确匹配无结果时自动放宽到只匹配 question_type
- 注入拼装：各部分都有内容时，输出格式正确、优先级正确
- Token 截断：构造超长内容，验证低优先级部分被截断
- 空库安全：ExperienceStore 为空时，inject() 返回 ""
- 与 orchestrator 集成：end-to-end 验证注入内容出现在 system prompt 中
