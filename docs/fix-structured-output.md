# Fix: Agent 结构化输出遵从率极低

## 问题

`COMBINED_TRACE_AND_OUTPUT_INSTRUCTION` 要求 agent 在最终答案中输出置信度/关键证据/主要风险，但 GPT-5 遵从率 <3%。导致：
- `parse_structured_output()` 几乎全部返回默认值 confidence="medium"
- 投票权重机制形同虚设（所有 path 等权）
- Judge 看不到证据质量，靠"答案看起来合不合理"选择，容易选错

## 数据

| 字段 | R3 (212 paths) | R1NEW (245 paths) |
|------|----------------|-------------------|
| Confidence | 2.8% | 0.8% |
| Risk | 2.4% | 3.7% |
| Summary | 88% | 84% |

与上下文长度无关。

## 方案 2：在 Final Summary prompt 里强制格式 + few-shot

### 改动位置

`apps/miroflow-agent/src/core/multi_path.py` — Final Summary 的 LLM 调用 prompt

### 改动内容

在 Final Summary 的 system prompt 或 user prompt 末尾追加强制格式要求 + few-shot 示例：

```
你的最终输出必须严格遵循以下格式，每个字段都不能省略：

Summary: （一段话总结搜索过程和发现）
置信度：high / medium / low
关键证据：[来源1: 一句话摘要, 来源2: 一句话摘要]
主要风险：（这个答案可能错在哪里，一句话）
\boxed{你的答案}

=== 示例 ===

Summary: 通过搜索豆瓣存档找到了2026-03-02更新的综艺口碑榜数据，榜单显示#2单身即地狱第五季、#3天机试炼场、#4黑白厨师第二季。基于周榜稳定性预测不变。
置信度：high
关键证据：[豆瓣doulist存档(2026-03-02): 综艺口碑榜#2-#4排名, Box Office Pro预测(2026-02-27): Scream 7首周末预估]
主要风险：榜单可能在截止日后因新节目上线而变动
\boxed{单身即地狱 第五季, 天机试炼场, 黑白厨师：料理阶级战争 第二季}

=== 再次提醒 ===
- Summary、置信度、关键证据、主要风险、\boxed{} 五个字段缺一不可
- 置信度只能是 high / medium / low 三选一
- 关键证据用方括号包裹，每条用逗号分隔
```

### 后续优化（备选方案）

1. **方案 1**：拆独立 LLM 调用，用 JSON mode 强制提取结构化字段（100% 保证输出）
2. **方案 3**：把 IST 的 `<conclusion>` 搜索轨迹喂给 Judge，让 Judge 看到证据质量

### 相关代码

- `apps/miroflow-agent/src/core/weighted_voting.py:431` — `COMBINED_TRACE_AND_OUTPUT_INSTRUCTION` 定义
- `apps/miroflow-agent/src/core/weighted_voting.py:462` — `parse_structured_output()` 解析
- `apps/miroflow-agent/src/core/multi_path.py:591` — IST suffix 注入
- `apps/miroflow-agent/src/core/multi_path.py:1228-1244` — 投票时提取 confidence
