# Reflector → Experience → Evolve 闭环设计

> 基于 meta-evolve-plan 中的专家系统方案
> 回答核心问题：reflector 怎么落成经验，经验怎么影响 evolve
> 
> **设计原则：经验不注入 prompt，只改结构性决策（选专家、改权重）**

---

## 一、设计哲学

~~经验注入 prompt（告诉 agent "上次这类题要注意…"）~~ — **砍掉**。

原因：
- Prompt patch 是最弱的进化方式——agent 可能忽略、误读、或被其他 prompt 内容冲掉
- 真正的进化应该是**结构性的**：改搜索策略、改专家组合、改投票权重
- Reflector 的经验是给 **Controller 和 Aggregator** 看的，不是给 agent 看的

进化的唯一两个作用面：
1. **选什么专家**（哪类专家在哪类题上表现好）
2. **怎么投票**（置信度校准、分裂时的策略）

---

## 二、Reflector 产出两种经验

```
┌─────────────────────────────────────────────────┐
│              Reflector（每批题后执行）              │
│                                                   │
│  输入：本批所有题的 path 日志 + ground truth         │
│                                                   │
│  输出两种经验：                                     │
│                                                   │
│  ① Expert Performance（专家表现）                  │
│     → 影响：Controller 选专家组合                   │
│     → "News Expert 在政治题上胜率 80%，             │
│        Market Expert 在政治题上胜率 20%"            │
│                                                   │
│  ② System Calibration（系统校准）                  │
│     → 影响：Aggregator 投票权重 + 分裂策略          │
│     → "置信度 high 的专家准确率 85%，               │
│        Judge 在三方分裂时准确率只有 50%"            │
└─────────────────────────────────────────────────┘
```

### ① Expert Performance（专家表现经验）

```json
{
  "type": "expert_performance",
  "batch_id": "R6_cat10",
  "question_type": "entertainment_award",
  "expert_stats": {
    "news_expert": {
      "tasks_attempted": 3,
      "tasks_correct": 2,
      "times_selected_by_vote": 1,
      "avg_confidence": "high",
      "typical_failure": "recency bias"
    },
    "mechanism_expert": {
      "tasks_attempted": 3,
      "tasks_correct": 1,
      "times_selected_by_vote": 0,
      "avg_confidence": "medium",
      "typical_failure": "too slow to capture event outcomes"
    },
    "counterfactual_expert": {
      "tasks_attempted": 3,
      "tasks_correct": 2,
      "times_selected_by_vote": 2,
      "avg_confidence": "medium",
      "typical_failure": null
    }
  },
  "recommended_combo": ["news_expert", "counterfactual_expert", "historical_expert"],
  "avoid": ["market_expert"]
}
```

**存储**：写入 OpenViking Memory，按题型语义索引。

**影响 evolve**：Controller 收到新题 → 语义检索匹配的 expert_performance → 用推荐组合开专家。

### ② System Calibration（系统校准经验）

```json
{
  "type": "system_calibration",
  "batch_id": "R6_cat10",
  "confidence_calibration": {
    "high_accuracy": 0.85,
    "medium_accuracy": 0.60,
    "low_accuracy": 0.40
  },
  "vote_pattern_accuracy": {
    "unanimous": 0.95,
    "majority": 0.75,
    "split": 0.50
  },
  "recommended_split_strategy": "highest_confidence",
  "before_date_gap_impact": {
    "gap_le_1day": 0.30,
    "gap_le_7day": 0.65,
    "gap_gt_7day": 0.80
  }
}
```

**存储**：写入 OpenViking Memory 或配置文件（每批覆盖更新）。

**影响 evolve**：
- Aggregator 用 `confidence_calibration` 算投票权重
- 三方分裂时，如果 `split` 准确率 < 0.55，不用 Judge，直接选最高置信度的
- Controller 根据 `before_date_gap_impact` 调整专家权重（gap 小 → 加重 mechanism/historical）

---

## 三、完整闭环流程

```
批次 N（10 题）
    │
    ▼
┌───────────────────────────────────┐
│  1. Controller 选专家组合           │
│     - 新题 → OpenViking 语义检索    │
│       匹配的 expert_performance    │
│     - 有经验 → 用推荐组合           │
│     - 无经验 → 用默认组合           │
│       [news, mechanism, counter]   │
└──────────────┬────────────────────┘
               │
               ▼
┌───────────────────────────────────┐
│  2. 专家并行执行                    │
│     每个专家输出：                   │
│     answer + confidence(h/m/l)     │
└──────────────┬────────────────────┘
               │
               ▼
┌───────────────────────────────────┐
│  3. 加权投票                        │
│     权重 = confidence              │
│     (由 system_calibration 校准)    │
│                                    │
│     一致 → 直接采用                  │
│     多数 → 加权采用                  │
│     分裂 → 看校准数据决定策略         │
└──────────────┬────────────────────┘
               │
               ▼
┌───────────────────────────────────┐
│  4. Reflector 批次反思               │
│    （不注入 prompt，只改结构）         │
│                                    │
│  4a. 跨路径对比 → Expert Perf       │
│      统计每种专家在每类题上的表现      │
│                                    │
│  4b. 全局统计 → System Calibration  │
│      置信度校准、投票模式分析          │
└──────────────┬────────────────────┘
               │
               ▼
┌───────────────────────────────────┐
│  5. 写入 OpenViking                 │
│     Expert perf → Memory/experts   │
│     System cal → Memory/system     │
└──────────────┬────────────────────┘
               │
               ▼
         批次 N+1（10 题）
         Controller 读取更新后的经验
         → 选更优的专家组合
         → 用更准的投票权重
```

---

## 四、Reflector 具体改什么

### 4.1 砍掉的

- ~~`reflect_on_task()` 的 lesson/failure_pattern 注入 prompt~~ — 不再注入 agent prompt
- ~~`ExperienceInjector` 整个模块~~ — 不再需要。经验不走 prompt，走结构

### 4.2 保留并改造的

#### `_reflect_comparison()` — 改为产出结构化专家表现数据

现在只输出 `winning_strategy`, `losing_strategies`, `comparison_lesson`（给人看的文本）。

改为输出**给 Controller 看的结构化数据**：

```python
# _reflect_comparison() 的输出不再需要 LLM 生成
# 纯代码统计就够了

def _collect_path_stats(path_results, ground_truth) -> dict:
    """从一道题的多路径结果中提取专家表现。纯计算。"""
    stats = {}
    answers = {}
    
    for result in path_results:
        expert = result["strategy_name"]  # e.g. "news_expert"
        answer = result["answer"]
        confidence = result["confidence"]  # h/m/l
        is_correct = _normalize(answer) == _normalize(ground_truth)
        
        stats[expert] = {
            "correct": is_correct,
            "confidence": confidence,
            "answer": answer,
        }
        answers[answer] = answers.get(answer, []) + [expert]
    
    # 投票模式
    unique_answers = len(set(r["answer"] for r in path_results))
    if unique_answers == 1:
        vote_pattern = "unanimous"
    elif any(len(v) >= 2 for v in answers.values()):
        vote_pattern = "majority"
    else:
        vote_pattern = "split"
    
    return {
        "expert_stats": stats,
        "vote_pattern": vote_pattern,
    }
```

### 4.3 新增的

#### `reflect_batch()` — 批次汇总，产出两种经验

```python
def reflect_batch(
    batch_results: list,  # 每道题的 path_stats
    batch_id: str,
) -> tuple[dict, dict]:
    """
    一批题结束后调用。纯计算，不需要 LLM。
    
    Returns:
        (expert_performance, system_calibration)
    """
    
    # ---- Expert Performance ----
    # 按题型分组统计每种专家的胜率
    by_type = defaultdict(lambda: defaultdict(
        lambda: {"correct": 0, "total": 0, "selected": 0}
    ))
    
    for item in batch_results:
        qt = item["question_type"]  # 题型（可以用 LLM 分类一次）
        for expert, stat in item["expert_stats"].items():
            by_type[qt][expert]["total"] += 1
            if stat["correct"]:
                by_type[qt][expert]["correct"] += 1
    
    expert_perf = {}
    for qt, experts in by_type.items():
        ranked = sorted(
            experts.items(),
            key=lambda x: x[1]["correct"] / max(x[1]["total"], 1),
            reverse=True,
        )
        expert_perf[qt] = {
            "recommended": [e[0] for e in ranked[:3]],
            "avoid": [
                e[0] for e in ranked
                if e[1]["correct"] / max(e[1]["total"], 1) < 0.3
            ],
            "stats": {e[0]: e[1] for e in ranked},
        }
    
    # ---- System Calibration ----
    # 置信度 vs 准确率
    conf_buckets = {"high": [], "medium": [], "low": []}
    for item in batch_results:
        for expert, stat in item["expert_stats"].items():
            conf = stat["confidence"]
            conf_buckets.setdefault(conf, []).append(stat["correct"])
    
    conf_cal = {
        level: sum(v) / len(v) if v else 0.5
        for level, v in conf_buckets.items()
    }
    
    # 投票模式 vs 准确率
    vote_buckets = {"unanimous": [], "majority": [], "split": []}
    for item in batch_results:
        pattern = item["vote_pattern"]
        final_correct = item["final_correct"]
        vote_buckets.setdefault(pattern, []).append(final_correct)
    
    vote_acc = {
        pattern: sum(v) / len(v) if v else 0.5
        for pattern, v in vote_buckets.items()
    }
    
    return (
        {
            "type": "expert_performance",
            "batch_id": batch_id,
            "by_question_type": expert_perf,
        },
        {
            "type": "system_calibration",
            "batch_id": batch_id,
            "confidence_accuracy": conf_cal,
            "vote_pattern_accuracy": vote_acc,
            "split_strategy": (
                "highest_confidence"
                if vote_acc.get("split", 0.5) < 0.55
                else "judge_tiebreak"
            ),
        },
    )
```

**注意：整个 reflector 不需要 LLM 调用。** 所有经验都是从日志里纯计算统计出来的。LLM 只在一个地方用：给新题分类题型（或者也可以用规则/embedding 替代）。

---

## 五、经验怎么影响 evolve — 两条路径

### 5.1 专家选择（Controller 层）

```python
async def _select_experts(
    task_description: str,
    viking_context: OpenVikingContext,
    default_experts: list = ["news", "mechanism", "counterfactual"],
) -> list:
    """根据历史专家表现选择最优组合"""
    
    # 从 OpenViking 语义检索匹配的 expert_performance
    expert_exps = await viking_context.query(
        query=task_description,
        exp_type="expert_performance",
        max_count=3,
    )
    
    if not expert_exps:
        return default_experts
    
    best = expert_exps[0]
    recommended = best.get("recommended", default_experts)
    return recommended[:3]
```

### 5.2 投票权重（Aggregator 层）

```python
def _weighted_vote(
    path_results: list,
    system_cal: dict = None,
) -> str:
    """加权投票，权重 = 置信度，受系统校准调整"""
    
    # 默认权重
    CONF_WEIGHT = {"high": 3, "medium": 2, "low": 1}
    
    # 有校准数据时，用准确率做权重
    if system_cal and "confidence_accuracy" in system_cal:
        cal = system_cal["confidence_accuracy"]
        CONF_WEIGHT = {k: max(0.1, v) for k, v in cal.items()}
    
    # 加权票数
    votes = {}
    for result in path_results:
        answer = result["answer"]
        weight = CONF_WEIGHT.get(result["confidence"], 1)
        votes[answer] = votes.get(answer, 0) + weight
    
    # 分裂时的策略也由校准数据决定
    unique = len(votes)
    if unique == len(path_results):  # 全分裂
        split_strategy = (system_cal or {}).get(
            "split_strategy", "highest_confidence"
        )
        if split_strategy == "highest_confidence":
            # 选置信度最高的那个专家的答案
            best = max(path_results, key=lambda r: CONF_WEIGHT.get(r["confidence"], 0))
            return best["answer"]
    
    return max(votes, key=votes.get)
```

**不再有 5.3 经验注入（Injector）。** ExperienceInjector 模块可以废弃。

---

## 六、落地优先级

| 优先级 | 改什么 | 工作量 | 效果 |
|--------|--------|--------|------|
| P0 | 专家角色差异化（替换 breadth/depth/lateral） | 3-5 天 | 路径多样性从"靠运气"到"靠设计" |
| P0 | 结构化输出（answer + confidence h/m/l） | 1 天 | 投票有据可依 |
| P1 | `_collect_path_stats()` + `reflect_batch()` | 2 天 | 产出两种经验 |
| P1 | 经验写入 OpenViking | 1-2 天 | 经验可被语义检索 |
| P2 | `_select_experts()` 根据经验选专家 | 1 天 | 闭环通路 1 |
| P2 | `_weighted_vote()` 加权投票 + 校准 | 1 天 | 闭环通路 2 |
| P3 | 废弃 ExperienceInjector | 0.5 天 | 清理旧代码 |

**P0 做完就能跑第一批，P1 做完就能开始积累经验，P2 做完闭环就通了。** 

整条链路不需要 LLM 做反思。Reflector 变成纯统计模块。
