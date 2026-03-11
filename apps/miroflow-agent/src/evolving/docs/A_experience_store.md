# 子模块 A：Experience Store（经验存储层）

## 1. 目标

提供统一的经验数据读写与检索接口，替代当前 `reflector.py` 中分散的 JSONL 直接操作。所有其他子模块（B/C/D）都通过本模块访问经验数据。

## 2. 需求

### 2.1 经验 Schema 扩展

当前 schema 只有 `question_type` + `level`，需扩展为：

```python
@dataclass
class Experience:
    # === 基础字段（已有） ===
    task_id: str                  # 任务唯一标识
    question_type: str            # 题目类型: "finance_market", "sports_event", "politics", "logistics", "science", ...
    level: int                    # 难度等级: 1-4
    question_summary: str         # 一句话题目摘要
    was_correct: bool             # 是否答对
    lesson: str                   # 可复用的经验教训（1-2 句）
    failure_pattern: Optional[str]  # 错误模式: "outdated_info", "wrong_reasoning", "insufficient_search", ...
    search_strategy: str          # agent 使用的搜索/推理策略描述

    # === 新增结构化标签 ===
    reasoning_type: str           # 推理类型: "numerical_computation", "logical_reasoning", "info_retrieval", "multi_step", "planning"
    knowledge_domain: str         # 知识领域: "finance", "sports", "geopolitics", "tech", "entertainment", "science", "other"
    tools_used: List[str]         # 使用的工具: ["web_search", "code_execution", "solver", "browsing"]
    strategy_name: str            # 所用策略/pipeline 名称（与子模块 C 对接）

    # === 元数据 ===
    created_at: str               # 创建时间（ISO 格式）
    source_run_id: str            # 来源运行批次 ID（用于溯源）
```

### 2.2 存储与去重

- 底层仍用 JSONL 文件存储（简单可靠，不引入外部依赖）
- 写入时按 `task_id` 去重：同一 `task_id` 只保留最新一条
- 支持追加写入和全量重写两种模式

### 2.3 多维检索

- 支持按任意标签组合过滤：`question_type`, `reasoning_type`, `knowledge_domain`, `level`, `was_correct`
- 支持限制返回数量 `max_count`，默认返回最近的记录
- 返回结果按时间倒序（最新优先）

### 2.4 格式化输出

- 保留现有 `format_experiences_for_prompt()` 的能力，但移入本模块
- 支持多种格式化模式：给 agent prompt 的文本格式 / 给策略聚合的结构化格式

## 3. 接口设计

```python
class ExperienceStore:
    """统一的经验存储与检索接口"""

    def __init__(self, file_path: str):
        """
        Args:
            file_path: experiences.jsonl 文件路径
        """

    def add(self, experience: dict) -> None:
        """
        写入一条经验。按 task_id 去重，已存在则覆盖。

        Args:
            experience: 符合 Experience schema 的 dict
        """

    def add_batch(self, experiences: List[dict]) -> int:
        """
        批量写入经验。返回实际新增/更新的条数。

        Args:
            experiences: Experience dict 列表
        Returns:
            写入条数
        """

    def query(
        self,
        question_type: Optional[str] = None,
        reasoning_type: Optional[str] = None,
        knowledge_domain: Optional[str] = None,
        level: Optional[int] = None,
        was_correct: Optional[bool] = None,
        max_count: int = 10,
    ) -> List[dict]:
        """
        多维过滤检索经验。所有条件为 AND 关系，None 表示不过滤。

        Returns:
            匹配的经验列表，按时间倒序
        """

    def get_all(self) -> List[dict]:
        """返回所有经验（供子模块 C 聚合用）"""

    def format_for_prompt(
        self,
        experiences: List[dict],
        max_tokens: int = 1500,
    ) -> str:
        """
        将经验列表格式化为可注入 system prompt 的文本。
        控制总 token 数不超过 max_tokens。

        Args:
            experiences: 要格式化的经验列表
            max_tokens: 近似 token 上限（按字符数 / 4 估算）
        Returns:
            格式化文本，为空时返回 ""
        """

    def stats(self) -> dict:
        """
        返回经验库统计信息。

        Returns:
            {
                "total": int,
                "correct": int,
                "incorrect": int,
                "by_question_type": {"finance_market": 12, ...},
                "by_reasoning_type": {"numerical_computation": 5, ...},
            }
        """
```

## 4. 接入点（改动位置）

| 位置 | 改动 |
|------|------|
| `src/evolving/experience_store.py` | **新建**本文件 |
| `src/evolving/reflector.py:186-191` | 写入部分改为调用 `ExperienceStore.add()` |
| `src/evolving/reflector.py:203-252` | `load_experiences()` 改为调用 `ExperienceStore.query()` |
| `src/evolving/reflector.py:255-273` | `format_experiences_for_prompt()` 迁移到 `ExperienceStore.format_for_prompt()` |
| `conf/config.yaml:17-20` | 扩展 evolving 配置段 |

## 5. 配置扩展

```yaml
# conf/config.yaml
evolving:
  enabled: false
  experience_file: "../../data/experiences.jsonl"
  max_experiences: 5
  # 新增
  strategy_preferences_file: "../../data/strategy_preferences.json"   # 供子模块 C
  prompt_overrides_file: "../../data/prompt_overrides.jsonl"           # 供子模块 C
```

## 6. 测试要点

- 写入 + 读取往返一致性
- task_id 去重：写入两条相同 task_id，只保留后者
- 多维过滤组合正确性
- format_for_prompt 的 token 截断逻辑
- 空文件 / 文件不存在时的安全处理
