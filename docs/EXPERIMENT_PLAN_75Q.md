# 策略进化 75 题实验计划

## 1. 实验目标

验证策略进化系统在多轮迭代后能否提升预测准确率。

## 2. 数据

| 文件 | 题数 | Ground Truth | 用途 |
|------|------|-------------|------|
| `online_data.jsonl` | 65 | ❌ 无 | 线上竞赛提交（不能用于进化） |
| `standardized_data_250924_250930.jsonl` | 141 | ✅ 有 | 进化实验训练+验证 |

**问题：** `online_data.jsonl` 没有 ground truth，跑完无法反思和进化。

**方案选择：**

- **方案 A：用 141 题数据做进化实验**
  - 从 141 题中选 75 题做训练集（进化用），剩余 66 题做测试集（评估用）
  - 好处：能跑完整的进化闭环
  - 坏处：测试集和训练集是同一批数据的不同子集

- **方案 B：用 141 题全部做进化，然后在 65 题线上题做预测**
  - 先用 141 题跑进化（有 GT，能反思）
  - 进化完成后，用训练好的策略跑 65 题线上题提交
  - 好处：最终目标就是线上题
  - 坏处：无法量化进化效果（线上题没有 GT 对比）

- **方案 C：混合**
  - Round 1：用 141 题中的 75 题做第一轮
  - 反思 + 进化
  - Round 2：用同样 75 题再跑一次，对比准确率变化（验证进化有效性）
  - Round 3（可选）：再进化一轮
  - 最终：用进化后的策略跑 65 题线上题提交

## 3. 推荐方案 C 的详细步骤

### Phase 0：准备

```bash
# 从 141 题中选 75 题（按 level 均衡抽样）
# 生成：/home/chenzhewen/futurex/train_75.jsonl
# 剩余 66 题：/home/chenzhewen/futurex/holdout_66.jsonl
```

- [ ] 生成训练集和留出集
- [ ] 确认 API key 余额（OpenRouter, Serper, SerpAPI）
- [ ] 确认 `single_agent_keep5.yaml` 包含三个搜索工具

### Phase 1：Round 1 — 基线测试（冷启动）

```bash
cd apps/miroflow-agent

SUMMARY_LLM_BASE_URL="https://openrouter.ai/api/v1" \
SUMMARY_LLM_MODEL_NAME="openai/gpt-5-2025-08-07" \
SUMMARY_LLM_API_KEY="${OPENAI_API_KEY}" \
uv run python benchmarks/common_benchmark.py \
  benchmark=futurex \
  benchmark.data.metadata_file="train_75.jsonl" \
  benchmark.data.data_dir=/home/chenzhewen/futurex \
  +benchmark.multi_path.enabled=true \
  +benchmark.multi_path.num_paths=5 \
  +benchmark.multi_path.early_stop_k=3 \
  +benchmark.multi_path.early_stop_threshold=1.0 \
  llm=openrouter_gpt5 \
  llm.async_client=true \
  benchmark.execution.max_tasks=75 \
  benchmark.execution.max_concurrent=1 \
  benchmark.execution.pass_at_k=1 \
  agent=single_agent_keep5 \
  question_parser.enabled=true \
  +pipeline.auto_reflect=false \
  hydra.run.dir=../../logs/evolve_exp_r1
```

- **预计时间：** 5-6 小时（75 题 × ~4 min/题）
- **预计成本：** ~$15-25（75 × 5 路径 × ~$0.04/路径）
- **产出：** `logs/evolve_exp_r1/benchmark_results.jsonl`
- [ ] 记录基线准确率

### Phase 2：反思 + 进化

```python
# 在 Python 中调用
from src.core.multi_path import reflect_and_evolve
from omegaconf import OmegaConf

cfg = OmegaConf.load("conf/config.yaml")  # 或用 Hydra 加载
ground_truths = {}  # 从 train_75.jsonl 构建 task_id → answer 映射

result = await reflect_and_evolve(
    cfg=cfg,
    log_dir="../../logs/evolve_exp_r1",
    ground_truths=ground_truths,
)
print(result)  # {num_reflected, num_evolved, refined, diverged, accuracy}
```

- **预计时间：** 10-30 分钟（反思 75 题 + EE 进化一轮）
- **产出：**
  - ExperienceStore 更新（75 条经验）
  - IslandPool 进化（每岛 +1 refine +1 diverge 策略）
  - EvolutionReport
- [ ] 记录进化报告
- [ ] 检查新策略的 8 维定义是否合理

### Phase 3：Round 2 — 进化后测试

```bash
# 同样的命令，只改 hydra.run.dir
hydra.run.dir=../../logs/evolve_exp_r2
```

- **预计时间：** 5-6 小时
- **关键对比：**
  - R1 vs R2 准确率变化
  - 各题型的胜率变化
  - 策略采样是否发生了变化（不再是种子策略而是进化后的策略）
- [ ] 对比 R1 vs R2 结果

### Phase 4（可选）：再进化一轮

如果 R2 有提升，再跑一轮进化 + R3，观察收敛趋势。

### Phase 5：线上竞赛提交

```bash
# 用进化后的策略跑 65 题线上题
benchmark.data.metadata_file="online_data.jsonl"
hydra.run.dir=../../logs/online_submission
```

- [ ] 生成提交文件
- [ ] 提交到 FutureX 平台

## 4. 时间和成本估算

| Phase | 时间 | 成本 | 说明 |
|-------|------|------|------|
| Phase 0 | 5 min | $0 | 数据准备 |
| Phase 1 | 5-6 hr | ~$20 | 75 题 × 5 路径基线 |
| Phase 2 | 30 min | ~$2 | 反思 + 进化 |
| Phase 3 | 5-6 hr | ~$20 | 75 题 × 5 路径验证 |
| Phase 4 | 6 hr | ~$22 | 可选第三轮 |
| Phase 5 | 4-5 hr | ~$15 | 65 题线上提交 |
| **总计** | **~18 hr** | **~$60-80** | |

## 5. 评估指标

| 指标 | 说明 |
|------|------|
| Pass@1 Accuracy | 主指标，题目答对率 |
| F1 Score | 部分匹配得分 |
| 按 Level 分组准确率 | L1/L2/L3/L4 各自的表现 |
| 按题型分组准确率 | politics/sports/finance 等 |
| 进化提升幅度 | R2 - R1 的准确率差 |
| 搜索成功率 | 有效搜索结果 / 总搜索次数 |

## 6. 风险和应对

| 风险 | 概率 | 应对 |
|------|------|------|
| Serper API 配额用完 | 中 | 监控用量，必要时切 SerpAPI |
| OpenRouter 限速 | 低 | max_concurrent=1 已缓解 |
| 进化后性能反而下降 | 中 | 对比 R1/R2，分析是否过拟合 |
| DuckDuckGo 持续不可用 | 高 | 已加 Google 搜索兜底 |
| 75 题跑到一半中断 | 中 | benchmark 支持断点续跑（跳过已完成的 task） |

## 7. 注意事项

1. **不要用 online_data.jsonl 做进化**——没有 ground truth，无法反思
2. **max_concurrent 必须 =1**——防止搜索限速
3. **跑之前检查 SEARCH_BEFORE_DATE 环境变量**——确保不泄漏未来信息
4. **每轮跑完先看搜索成功率**——如果又出现大量 0 结果，需要排查
5. **进化后检查策略合理性**——防止 LLM 生成无意义的策略维度值
