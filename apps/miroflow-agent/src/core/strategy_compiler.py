# Copyright 2026 EvoAgent Contributors
# SPDX-License-Identifier: MIT
"""
Strategy Compiler — 策略编译器，将 8 维 StrategyDefinition 编译为 prompt_suffix。

实现 StrategyCompiler 类 (QP-211)、compile_strategy() 便捷函数 (QP-209)
和所有 8 维 TEMPLATES 字典 (QP-202~208)。
"""

from typing import Dict, Any
from .strategy_definition import StrategyDefinition


# ──── QP-202: hypothesis_framing 维度模板 ────

FRAMING_TEMPLATES: Dict[str, str] = {
    "news_tracking": (
        "[视角: 信息追踪]\n"
        "你是一个信息追踪专家。关注最新的新闻事件进展、官方声明和权威媒体报道。"
        "追踪事件的时间线，识别关键转折点和最新动态。"
    ),
    "mechanism_analysis": (
        "[视角: 机制分析]\n"
        "你是一个结构性分析专家。关注驱动事件的底层机制、制度约束、利益格局和决策流程。"
        "分析因果链条，识别关键变量和约束条件。"
    ),
    "historical_analogy": (
        "[视角: 历史类比]\n"
        "你是一个历史类比专家。寻找历史上的类似案例和基准率。"
        "分析过去相似情境的结果分布，用历史数据修正直觉判断。"
    ),
    "market_signal": (
        "[视角: 市场信号]\n"
        "你是一个市场信号专家。关注预测市场赔率、金融指标、博彩盘口等市场定价信息。"
        "市场价格反映了大量参与者的集体判断，是强信号来源。"
    ),
    "counterfactual": (
        "[视角: 对抗验证]\n"
        "你是一个对抗验证专家。专门挑战主流观点和表面证据。"
        "主动寻找反面证据，构建反事实场景，检验主流判断的脆弱点。"
    ),
}


# ──── QP-203: query_policy 维度模板 ────

QUERY_TEMPLATES: Dict[str, str] = {
    "broad_diverse": (
        "[搜索策略: 广泛多样]\n"
        "使用多种不同的搜索词和角度进行搜索，最大化信息覆盖面。"
        "同一个问题至少用 3 种不同表述搜索。"
    ),
    "targeted_authoritative": (
        "[搜索策略: 精准权威]\n"
        "直接搜索最权威的一手信息来源。优先查找官方网站、数据库和权威机构发布。"
        "宁可少搜但要搜到最可靠的。"
    ),
    "trend_based": (
        "[搜索策略: 趋势追踪]\n"
        "按时间线搜索事件发展趋势。从早期到最近，追踪关键指标的变化方向。"
        "注意趋势的加速、减速和拐点。"
    ),
    "contrarian": (
        "[搜索策略: 逆向搜索]\n"
        "主动搜索与主流观点相反的信息。使用 'why X won't happen'、'against'、"
        "'criticism' 等关键词。寻找被忽视的反面证据。"
    ),
    "temporal_sequence": (
        "[搜索策略: 时序递进]\n"
        "按时间顺序搜索，从最早的相关事件开始，逐步推进到最新状态。"
        "构建完整的事件时间线，不遗漏关键节点。"
    ),
}


# ──── QP-204: evidence_source 维度模板 ────

EVIDENCE_TEMPLATES: Dict[str, str] = {
    "news_wire": (
        "[证据来源: 新闻通讯社]\n"
        "优先信任 Reuters、AP、AFP 等通讯社报道。"
        "主流媒体 (NYT, BBC, 新华社) 作为补充。谨慎对待自媒体和社交平台。"
    ),
    "official_data": (
        "[证据来源: 官方数据]\n"
        "优先查找政府公报、央行数据、统计局发布、上市公司公告等一手官方数据。"
        "新闻报道作为索引找到原始数据源。"
    ),
    "academic": (
        "[证据来源: 学术研究]\n"
        "优先查找学术论文、研究报告、专家分析和智库报告。"
        "注意方法论质量和样本量。"
    ),
    "market_data": (
        "[证据来源: 市场数据]\n"
        "优先查找预测市场 (Polymarket, Metaculus)、金融市场数据、博彩赔率。"
        "市场价格是高密度信息信号。"
    ),
    "social_signal": (
        "[证据来源: 社会信号]\n"
        "关注社交媒体趋势、公众舆论、民调数据和情绪指标。"
        "注意区分噪音和真实信号。"
    ),
}


# ──── QP-205: retrieval_depth 维度模板 ────

RETRIEVAL_TEMPLATES: Dict[str, str] = {
    "shallow": (
        "[搜索深度: 浅层]\n"
        "快速扫描多个来源的标题和摘要，获取全局图景。"
        "不深入阅读长文，效率优先。"
    ),
    "medium": (
        "[搜索深度: 中等]\n"
        "对关键来源深入阅读，次要来源快速浏览。"
        "在效率和深度之间平衡。"
    ),
    "deep": (
        "[搜索深度: 深层]\n"
        "对每个关键来源进行深入阅读和分析。"
        "追溯引用链，检查原始数据。宁可慢但要彻底。"
    ),
}


# ──── QP-206: update_policy 维度模板 ────

UPDATE_TEMPLATES: Dict[str, str] = {
    "fast": (
        "[更新策略: 快速更新]\n"
        "每获得一条新证据就立即更新判断。对新信息敏感，快速调整。"
    ),
    "moderate": (
        "[更新策略: 适度更新]\n"
        "积累 2-3 条一致证据后更新判断。避免被单条信息过度影响。"
    ),
    "conservative": (
        "[更新策略: 保守更新]\n"
        "保持初始判断的锚定效应，只有强力反面证据才修正。"
        "避免频繁摇摆。"
    ),
}


# ──── QP-207: audit_policy 维度模板 ────

AUDIT_TEMPLATES: Dict[str, str] = {
    "devil_advocate": (
        "[自审策略: 魔鬼代言人]\n"
        "在给出判断前，主动为相反结论辩护。"
        "如果反面论证足够有力，降低置信度。"
    ),
    "source_triangulation": (
        "[自审策略: 来源三角验证]\n"
        "关键事实必须由至少 2 个独立来源确认。"
        "单一来源的信息标记为未验证。"
    ),
    "base_rate_check": (
        "[自审策略: 基准率检查]\n"
        "检查类似事件的历史基准率。"
        "如果你的判断与基准率偏差很大，需要额外强力证据支撑。"
    ),
    "assumption_audit": (
        "[自审策略: 假设审计]\n"
        "列出你推理中的所有隐含假设，逐一检验。"
        "如果某个假设不成立，结论是否会改变？"
    ),
    "none": (
        "[自审策略: 无]\n"
        "不做额外的自我审查，直接给出判断。"
    ),
}


# ──── QP-208: termination_policy 维度模板 ────

TERMINATION_TEMPLATES: Dict[str, str] = {
    "confidence_threshold": (
        "[停止条件: 置信度阈值]\n"
        "当你对答案的置信度达到 high 时停止搜索。"
        "如果长时间无法达到高置信度，在中等置信度时也可以停止。"
    ),
    "evidence_saturation": (
        "[停止条件: 证据饱和]\n"
        "当新搜索不再带来新信息时停止。"
        "连续 2-3 次搜索结果重复则视为饱和。"
    ),
    "time_budget": (
        "[停止条件: 时间预算]\n"
        "在分配的轮次内尽可能多搜索，时间到就给出当前最佳判断。"
        "不追求完美，追求时间内最优。"
    ),
    "adversarial_stable": (
        "[停止条件: 对抗稳定]\n"
        "当你尝试了反面搜索仍无法推翻当前判断时停止。"
        "判断经过了对抗验证才算稳定。"
    ),
}


# ──── QP-201: 8 维 TEMPLATES 主字典 ────
# 单一字典，将维度名映射到对应的模板字典

# ──── Evolved dimension value templates (auto-generated from c3 evolution) ────

FRAMING_TEMPLATES.update({
    "origin_causal_graph": (
        "[视角: 因果溯源图]\n"
        "你是一个因果推理专家。从结果事件出发，向上游追溯所有可能的因果路径，构建完整的因果图谱。"
        "识别根因节点和关键传导链条，区分直接原因与间接原因。"
    ),
    "closed-loop perturbation mapping": (
        "[视角: 闭环扰动映射]\n"
        "你是一个系统动力学专家。识别事件中的反馈回路和闭环结构，"
        "分析关键变量被扰动后如何通过回路放大或衰减。重点关注正反馈（加速）和负反馈（稳定）机制。"
    ),
    "mechanism_archetype_recombination": (
        "[视角: 机制原型重组]\n"
        "你是一个跨领域类比专家。将当前事件拆解为基本机制原型（如博弈、传染、阈值触发等），"
        "然后搜索历史上相同机制组合在不同领域的表现，借此推断可能结果。"
    ),
    "liquidity_regime_shift": (
        "[视角: 流动性体制转换]\n"
        "你是一个市场体制分析专家。关注流动性条件（资金、注意力、参与度）是否正在发生结构性转换。"
        "识别体制切换的前兆信号，区分正常波动与体制跃迁。"
    ),
    "falsificationist_multi_model": (
        "[视角: 多模型证伪]\n"
        "你是一个证伪主义分析师。同时构建多个竞争性解释模型，为每个模型寻找最具杀伤力的反面证据。"
        "优先淘汰无法存活的模型，保留尚未被证伪的候选。"
    ),
})

QUERY_TEMPLATES.update({
    "upstream_first_graph_expansion": (
        "[搜索策略: 上游优先扩展]\n"
        "从事件的上游原因开始搜索，逐层向下游展开。先搜根因和前置条件，再搜传导路径和下游影响。"
        "确保因果链完整，不跳过中间环节。"
    ),
    "contradiction-seeking triangulation across adversarial, edge-case, and cross-context probes": (
        "[搜索策略: 矛盾三角交叉验证]\n"
        "三管齐下搜索矛盾信息：(1) 搜索对立方的强论点；(2) 搜索极端边界条件下的例外情况；"
        "(3) 搜索不同领域/地区的类似事件是否出现不同结果。三条线索交叉验证。"
    ),
    "contrastive_case_expansion": (
        "[搜索策略: 对比案例扩展]\n"
        "搜索与当前事件高度相似但结果不同的对比案例。"
        "使用 'similar but different outcome'、'为什么A成功B失败' 等思路。通过对比找出决定结果的关键差异变量。"
    ),
    "microstructure_state_scan": (
        "[搜索策略: 微观结构扫描]\n"
        "深入搜索事件的微观结构状态：市场的订单流、社交媒体的情绪分布、投票的逐区数据等底层颗粒度信息。"
        "从微观信号中捕捉宏观趋势的早期迹象。"
    ),
    "uncertainty_maximizing_refutation_first": (
        "[搜索策略: 最大不确定性优先证伪]\n"
        "优先搜索能最大程度动摇当前判断的信息。找出你最不确定的关键假设，针对性搜索能证伪该假设的证据。"
        "先破后立，用证伪来收窄不确定性。"
    ),
})

EVIDENCE_TEMPLATES.update({
    "news_wire+official_feeds": (
        "[证据来源: 通讯社+官方信源]\n"
        "优先查找主要通讯社（路透、美联、新华社）快讯和官方机构发布的声明、公报、新闻稿。"
        "以速度和权威性为第一优先级。"
    ),
    "primary_documents+protocol_telemetry+registry_logs": (
        "[证据来源: 原始文件+协议遥测+注册日志]\n"
        "优先查找第一手原始文件（法律文本、合同、会议记录）、协议层面的技术遥测数据（链上数据、API日志）、"
        "以及公开注册记录（专利、域名、企业登记）。"
    ),
    "official_data + real_time_feeds": (
        "[证据来源: 官方数据+实时信源]\n"
        "结合官方统计数据（政府公报、央行数据、监管文件）和实时信息流（新闻快讯、社交媒体、实时市场数据）。"
        "官方数据定基调，实时信源捕动态。"
    ),
    "micro-interventions/AB tests + process trace logs + open sensor telemetry + ethnographic micro-observations + high-fidelity simulations": (
        "[证据来源: 多层实证数据]\n"
        "搜集五类证据：(1) 小规模实验/AB测试结果；(2) 过程追踪日志；(3) 公开传感器和遥测数据；"
        "(4) 实地观察和微观民族志记录；(5) 高保真模拟/仿真结果。多层数据交叉印证。"
    ),
    "authoritative_real_time": (
        "[证据来源: 权威实时信源]\n"
        "优先查找具有权威性的实时信息源：官方新闻发布会、央行声明、监管机构公告、权威媒体突发报道。"
        "兼顾权威性和时效性，拒绝未经验证的小道消息。"
    ),
    "archival_primary_plus_structured_datasets": (
        "[证据来源: 档案原始文献+结构化数据集]\n"
        "优先查找历史档案、原始文献（政策文件、历史记录、原始报告）"
        "以及公开结构化数据集（政府统计、学术数据库、国际组织数据）。用历史深度支撑判断。"
    ),
    "order_book, order_flow, options_skew, funding_basis, dark_pool_prints": (
        "[证据来源: 市场微观结构数据]\n"
        "优先查找订单簿深度、资金流向、期权偏度（skew）、资金费率/基差、暗池成交数据。"
        "这些微观结构信号反映知情交易者的真实头寸方向。"
    ),
    "official_sources": (
        "[证据来源: 官方信源]\n"
        "优先查找政府、监管机构、国际组织的官方发布。"
        "包括法规文件、政策声明、统计公报、官方新闻稿。以一手官方信息为最高优先级。"
    ),
    "primary_documents_and_raw_datasets": (
        "[证据来源: 一手文件与原始数据]\n"
        "优先查找原始文件（法案文本、合同、财报原文、会议纪要）和原始数据集（统计原始表、调查微数据）。"
        "拒绝二手解读，直接从源头获取信息。"
    ),
})

RETRIEVAL_TEMPLATES.update({
    "moderate": (
        "[搜索深度: 适中]\n"
        "对每个来源进行中等深度的阅读。抓取关键结论和核心论据，但不必追溯每一条引用链。"
        "在效率和深度之间取平衡。"
    ),
    "deep_trace": (
        "[搜索深度: 深度追溯]\n"
        "对关键证据链进行全链条追溯。从结论追到论据，从论据追到原始数据，从引用追到原文。"
        "验证每个环节是否成立，不放过任何跳跃推理。"
    ),
    "breadth-first loop sweep followed by leverage-focused drilldown on high-sensitivity arcs": (
        "[搜索深度: 先广扫后深钻]\n"
        "第一阶段：广度优先，快速扫描所有相关反馈回路和因果弧线。"
        "第二阶段：识别出对结果最敏感的关键弧线，对其进行杠杆点聚焦式深度钻探。"
    ),
    "progressive_deepening": (
        "[搜索深度: 逐步加深]\n"
        "分轮次搜索，每轮加深一层。第一轮抓概览和关键事实；第二轮深入核心争议点；"
        "第三轮追溯原始数据和边缘证据。每轮根据上轮结果调整方向。"
    ),
    "adaptive_deep": (
        "[搜索深度: 自适应深度]\n"
        "根据信息价值动态调整搜索深度。对高不确定性、高影响力的关键节点深入挖掘；"
        "对已有共识的低争议点快速略过。把精力集中在边际信息价值最高的地方。"
    ),
    "breadth_first_wide": (
        "[搜索深度: 广度优先宽扫]\n"
        "最大化覆盖面，广泛搜索所有相关维度和信息源。每个来源快速提取关键信号，不在单一来源上过度停留。"
        "目标是构建全景视图，不遗漏重要方向。"
    ),
})

UPDATE_TEMPLATES.update({
    "event_driven_checkpointing": (
        "[更新策略: 事件驱动检查点]\n"
        "不按固定节奏更新，而是在关键事件发生时触发更新。"
        "定义关键事件清单（如政策发布、数据公布、突发事件），每次触发时重新评估判断并记录检查点。"
    ),
    "invariance-weighted structural revision (topology-first, then parameters; prioritize interventional outcomes over observational signals)": (
        "[更新策略: 不变量加权结构修正]\n"
        "优先修正因果结构（哪些因素影响哪些），再调整参数权重。"
        "当观测数据与干预实验结果矛盾时，以干预结果为准。保持已验证的不变关系，只修正被新证据打破的部分。"
    ),
    "bayesian_regime_switching": (
        "[更新策略: 贝叶斯体制切换]\n"
        "维护多个体制假设（如'正常态'与'危机态'），用贝叶斯方式更新各体制的概率权重。"
        "当体制切换概率超过阈值时，整体切换预测框架，而非渐进微调。"
    ),
    "state_triggered_streaming": (
        "[更新策略: 状态触发流式更新]\n"
        "持续监控关键状态变量，当变量越过预设阈值时立即触发更新。"
        "更新幅度与状态变化幅度成正比。在阈值之间保持判断稳定，避免噪声驱动的频繁修正。"
    ),
    "sequential_probability_ratio": (
        "[更新策略: 序贯概率比更新]\n"
        "每获取一条新证据，计算该证据在正反假设下的似然比，累积更新。"
        "当累积似然比突破预设上下界时做出明确判断，否则继续收集证据。避免过早下结论。"
    ),
})

AUDIT_TEMPLATES.update({
    "provenance_chain_verification": (
        "[自审策略: 来源链验证]\n"
        "对每条关键证据追溯完整的来源链：谁说的→基于什么数据→数据从哪来→原始测量是否可靠。"
        "任何断链或不可追溯的环节都要标记为可信度折扣。"
    ),
    "assumption_audit + timestamp_verification": (
        "[自审策略: 假设审计+时间戳校验]\n"
        "逐一列出你的隐含假设并检查其是否成立。"
        "同时验证所有引用信息的时间戳——过时的信息可能导致错误判断。标记所有超过合理时效的证据。"
    ),
    "loop-integrity audit: conservation/delay closure checks + do-calculus consistency + counterfactual stress tests": (
        "[自审策略: 回路完整性审计]\n"
        "三重检查：(1) 因果回路是否守恒、延迟是否闭合；"
        "(2) 因果推断是否符合 do-演算一致性；(3) 用反事实压力测试——如果关键变量不存在，结论是否仍成立。"
    ),
    "unit_scale_check": (
        "[自审策略: 量纲与量级检查]\n"
        "检查所有数字的单位和数量级是否合理。百万与十亿是否搞混？百分比与基点是否弄错？"
        "时间单位（日/月/年）是否对齐？数量级错误是预测中最常见的低级失误。"
    ),
    "retrodictive_backtest_with_synthetic_controls": (
        "[自审策略: 回溯测试+合成对照]\n"
        "用你的预测逻辑去'预测'已知的历史事件，检验是否能命中。"
        "构建合成对照组（相似但未发生该事件的情境），验证你的因果逻辑是否真正有区分力。"
    ),
    "counterfactual_lob_replay + cross_venue_leadlag + signal_orthogonality": (
        "[自审策略: 反事实回放+跨场所验证+信号正交性]\n"
        "三维自审：(1) 回放历史数据，检验你的信号在反事实场景下是否仍有效；"
        "(2) 检查信号在不同场所的领先滞后关系是否一致；(3) 确认多个信号之间是正交的而非重复计算同一信息。"
    ),
    "blinded_rotating_red_team": (
        "[自审策略: 盲审轮换红队]\n"
        "假设有一个不知道你结论的红队在审查你的推理。轮换审查角度：第一轮审证据质量，"
        "第二轮审逻辑链条，第三轮审替代解释。每轮都尝试推翻你的结论。"
    ),
})

TERMINATION_TEMPLATES.update({
    "root_path_closure+propagation_plateau": (
        "[停止条件: 根路径闭合+传播平台期]\n"
        "当所有因果根路径都已追溯到源头（闭合），且新的信息传播不再改变下游判断（进入平台期）时停止。"
        "两个条件同时满足才终止搜索。"
    ),
    "intervention-stability plateau: stop when successive novel perturbations no longer shift loop rankings or predictions beyond a small epsilon": (
        "[停止条件: 干预稳定性平台期]\n"
        "持续引入新的扰动假设来测试你的判断。"
        "当连续多次引入新扰动后，预测结果的变化都小于一个很小的阈值时，判定已达到稳定，停止搜索。"
    ),
    "evidence_saturation_and_posterior_stability": (
        "[停止条件: 证据饱和+后验稳定]\n"
        "双重停止条件：(1) 新搜索不再带来新信息（证据饱和）；"
        "(2) 概率判断在连续多轮更新后变化极小（后验分布稳定）。两者同时满足才停止。"
    ),
    "regime_stability_plateau": (
        "[停止条件: 体制稳定平台期]\n"
        "当对当前所处体制（正常/转换/危机等）的判断在连续多轮搜索后保持稳定，"
        "且没有新的体制切换信号出现时停止。如果出现体制切换迹象，重新激活搜索。"
    ),
    "sprt_bounds_or_counterevidence_exhausted": (
        "[停止条件: 序贯检验边界或反证穷尽]\n"
        "两个停止条件取先到者：(1) 累积似然比突破序贯概率比检验的上界或下界，可以做出明确判断；"
        "(2) 已穷尽所有可能的反面证据来源，无法找到更多反证。"
    ),
})


# ──── EE-patch: 补全进化生成的维度值模板 (45 entries) ────

FRAMING_TEMPLATES.update({
    "auction_intent_mapping": (
        "[视角: 拍卖意图映射]\n"
        "你是一个市场微观结构专家。通过分析买卖双方的出价模式、挂单分布和成交节奏，"
        "推断参与者的真实意图和信息优势。从价格发现机制反推事件走向。"
    ),
    "downstream_impact_backprop": (
        "[视角: 下游影响反向传播]\n"
        "你是一个影响链分析专家。从事件的下游后果出发，反向推导上游原因和传导路径。"
        "关注谁会受到影响、影响有多大、传导延迟是多久，据此反推事件本身的性质和规模。"
    ),
    "failure_mode_inversion": (
        "[视角: 失效模式反演]\n"
        "你是一个风险分析专家。列出事件可能失效的所有模式（不发生、部分发生、延迟发生、反转等），"
        "分析每种失效模式的前提条件是否成立。通过排除不可能的失效模式来收窄预测。"
    ),
    "interface-contract causal ledger": (
        "[视角: 接口-契约因果账本]\n"
        "你是一个系统接口分析专家。将事件拆解为多个参与方之间的'契约'关系，"
        "追踪每个接口的承诺、交付和违约情况。通过契约履行状态推断事件走向。"
    ),
    "path_dependence_microhistory_mapping": (
        "[视角: 路径依赖微观历史映射]\n"
        "你是一个路径依赖分析专家。追踪事件的微观历史轨迹，识别关键分叉点和锁定效应。"
        "分析当前状态是如何被历史路径约束的，哪些选择空间已被关闭，哪些仍然开放。"
    ),
})

QUERY_TEMPLATES.update({
    "assumption_attack_surface": (
        "[搜索策略: 假设攻击面]\n"
        "识别你当前判断中最脆弱的假设，针对性搜索能击破该假设的证据。"
        "每轮搜索瞄准一个假设的薄弱点，优先攻击最关键的假设。"
    ),
    "contradiction-seeking triangulation across adversarial, edge-case, and cross-context probes, "
    "with provenance-locked timestamped multi-source retrieval (official + independent captures) "
    "and explicit unit/order probes": (
        "[搜索策略: 带溯源锁定的矛盾三角交叉验证]\n"
        "三管齐下搜索矛盾信息：(1) 对立方论点；(2) 边界条件例外；(3) 跨领域对比。"
        "所有证据必须锁定时间戳和来源出处，并显式验证单位和数量级。"
    ),
    "contrastive_case_expansion_with_timestamped_multisource_captures": (
        "[搜索策略: 带时间戳的对比案例扩展]\n"
        "搜索高度相似但结果不同的对比案例，每条证据记录精确时间戳和多个独立来源。"
        "通过时间线对比找出导致不同结果的关键差异变量。"
    ),
    "eventless_signal_pivoting": (
        "[搜索策略: 无事件信号枢轴]\n"
        "不只搜索已发生的事件，也搜索'应该发生但没发生'的信号。"
        "缺席的信号（如未发布的声明、未出现的反应）可能比已发生的事件更有信息量。"
    ),
    "feature_signature_neighbor_hunt": (
        "[搜索策略: 特征签名邻近搜索]\n"
        "提取当前事件的关键特征签名（数值指标、参与者组合、时间模式），"
        "搜索历史上具有最相似特征签名的案例，分析其结果分布。"
    ),
    "interface-first dependency elicitation with progressive disclosure and contract probing": (
        "[搜索策略: 接口优先依赖挖掘]\n"
        "从系统接口和依赖关系出发搜索。先找出关键参与方之间的接口点，"
        "逐步深入挖掘每个接口的约束条件和契约状态。渐进式披露，由浅入深。"
    ),
    "perturbation_guided_active_probing": (
        "[搜索策略: 扰动引导主动探测]\n"
        "通过假设性扰动来引导搜索方向。问自己'如果X发生变化，结果会怎样？'"
        "然后搜索X是否真的在变化。用假设驱动搜索，而非被动收集信息。"
    ),
    "time_gated_snapshot_series": (
        "[搜索策略: 时间门控快照序列]\n"
        "按固定时间间隔搜索事件的状态快照，构建完整的时间序列。"
        "每个时间点获取多个来源的快照，对比不同时间点的变化趋势。"
    ),
    "timestamped_multisource_snapshot_scan": (
        "[搜索策略: 带时间戳的多源快照扫描]\n"
        "对每个关键信息点，同时搜索多个独立来源并记录精确时间戳。"
        "对比同一时间不同来源的描述差异，以及同一来源不同时间的变化。"
    ),
    "triangulate": (
        "[搜索策略: 三角验证]\n"
        "对每个关键判断，从至少三个不同角度搜索验证：官方来源、独立媒体、市场/数据。"
        "三个方向一致才确认，有分歧则深入调查分歧原因。"
    ),
})

EVIDENCE_TEMPLATES.update({
    "anomaly_reports_and_field_traces": (
        "[证据来源: 异常报告与现场痕迹]\n"
        "优先查找异常事件报告、现场调查记录、故障日志和异常检测数据。"
        "异常信号往往是趋势变化的最早指标。"
    ),
    "auction_imbalance_and_volume_profile + volatility_surface_shape + positioning_flows + relative_value_spreads": (
        "[证据来源: 市场深层结构数据]\n"
        "查找拍卖不平衡度、成交量分布、波动率曲面形态、持仓流向和相对价值利差。"
        "这些深层结构数据反映机构投资者的真实判断和头寸方向。"
    ),
    "declassified_archives_oral_histories_and_procurement_records": (
        "[证据来源: 解密档案与采购记录]\n"
        "查找已解密的政府档案、口述历史记录和采购/招标记录。"
        "这些非常规来源经常包含公开报道中缺失的关键细节。"
    ),
    "network_edge_measurements+diffusion_graphs+cache_headers+broadcast_metadata": (
        "[证据来源: 网络边缘测量与传播图谱]\n"
        "查找网络传播路径数据、信息扩散图谱、缓存时间戳和广播元数据。"
        "从信息传播的技术痕迹中推断事件的真实时序和影响范围。"
    ),
    "official_plus_market": (
        "[证据来源: 官方+市场双信源]\n"
        "同时查找官方发布（政府公报、监管文件）和市场定价信息（预测市场、赔率、期货）。"
        "官方信源定方向，市场信源定概率。两者交叉验证。"
    ),
    "system-artifact corpus (specs/standards, design docs, code/config diffs, runbooks, "
    "incident postmortems, maintenance tickets) + structured expert elicitation": (
        "[证据来源: 系统工件语料+专家访谈]\n"
        "查找系统相关的技术文档（规格、设计文档、变更记录、故障复盘、运维工单）"
        "以及结构化的专家意见。技术工件中隐藏着决策者的真实约束和优先级。"
    ),
})

RETRIEVAL_TEMPLATES.update({
    "adaptive_bandit_zoom": (
        "[搜索深度: 自适应多臂老虎机缩放]\n"
        "像多臂老虎机一样分配搜索深度：先对所有方向浅层探索，"
        "然后把更多深度预算分配给回报最高的方向。动态平衡探索与利用。"
    ),
    "breadth_first_shallow_then_targeted_punctures": (
        "[搜索深度: 先广扫后定点穿透]\n"
        "第一阶段：广度优先浅层扫描所有相关方向。"
        "第二阶段：选择 2-3 个最有价值的点进行定点深度穿透，获取关键细节。"
    ),
    "deep_baseline": (
        "[搜索深度: 深度基线]\n"
        "对所有来源统一进行深度阅读和分析。不做浅层扫描，每个来源都完整阅读。"
        "追求理解的深度而非覆盖的广度。"
    ),
    "funnel_wide_to_micro_confirm": (
        "[搜索深度: 漏斗式从广到微确认]\n"
        "漏斗型搜索：最上层广泛撒网→中层筛选关键信息→最底层对核心事实进行微观确认。"
        "每一层淘汰不相关的信息，最终聚焦到最关键的几个事实点。"
    ),
    "just-in-time frontier sampling with an uncertainty budget "
    "(thin slices across many interfaces, then deepen only where contracts conflict)": (
        "[搜索深度: 即时前沿采样+不确定性预算]\n"
        "在多个接口方向上做薄层采样，只在发现矛盾/冲突的地方投入深度预算。"
        "不确定性最大的点获得最多搜索资源。"
    ),
    "progressive_stratified_sampling": (
        "[搜索深度: 渐进分层采样]\n"
        "将信息源分层（核心层、辅助层、边缘层），从核心层开始逐层加深。"
        "每层采样后评估是否需要进入下一层，避免在低价值层浪费深度。"
    ),
})

UPDATE_TEMPLATES.update({
    "bayesian_decay_revision": (
        "[更新策略: 贝叶斯衰减修正]\n"
        "用贝叶斯方式更新判断，同时对旧证据施加时间衰减权重。"
        "越新的证据权重越高，越旧的证据权重逐渐衰减。防止过时信息干扰判断。"
    ),
    "case_based_ensemble_with_similarity_decay": (
        "[更新策略: 基于案例的集成+相似度衰减]\n"
        "维护一组历史类似案例，每个案例按与当前事件的相似度加权投票。"
        "随着新证据揭示差异，降低不再相似的案例的权重。"
    ),
    "hypothesis_wager_loop": (
        "[更新策略: 假设押注循环]\n"
        "为每个竞争假设分配'筹码'，每获取一条新证据就根据似然度重新分配筹码。"
        "当某个假设的筹码超过阈值时确认，低于阈值时淘汰。循环直到收敛。"
    ),
    "surprise-triggered contract revision: constraints-first reconciliation, "
    "then causal-link rewire; Bayesian weighting with soft-consistency relaxation": (
        "[更新策略: 惊讶触发的契约修正]\n"
        "当新证据与预期严重不符（惊讶度高）时触发更新。先修正约束条件，再重连因果链条。"
        "用贝叶斯权重更新，允许软一致性放松以适应新信息。"
    ),
    "surprise_weighted_model_averaging": (
        "[更新策略: 惊讶加权模型平均]\n"
        "维护多个预测模型，用惊讶度（预测与实际的偏差）来重新加权。"
        "预测准确的模型权重上升，预测失败的模型权重下降。最终取加权平均。"
    ),
})

AUDIT_TEMPLATES.update({
    "adversarial_path_consistency_testing": (
        "[自审策略: 对抗路径一致性测试]\n"
        "从不同起点出发推理到同一结论，检查路径是否一致。"
        "如果从不同角度得出矛盾结论，说明推理中有隐藏的错误假设。"
    ),
    "causal-ledger reconciliation audit: contract satisfiability checks, "
    "responsibility/blame allocation across interfaces, "
    "and cross-artifact traceability validation": (
        "[自审策略: 因果账本对账审计]\n"
        "三重检查：(1) 因果链条中每个'契约'是否可满足；"
        "(2) 跨接口的责任分配是否合理；(3) 跨文档/来源的可追溯性是否完整。"
    ),
    "loop-integrity audit: conservation/delay closure checks + do-calculus consistency "
    "+ counterfactual stress tests, plus a final provenance/unit/scale/order sanity checklist "
    "(rank-position mapping, currency/units, and time-index alignment)": (
        "[自审策略: 回路完整性审计（增强版）]\n"
        "四重检查：(1) 因果回路守恒与延迟闭合；(2) do-演算一致性；"
        "(3) 反事实压力测试；(4) 最终健全性检查——排名映射、货币/单位、时间索引是否对齐。"
    ),
    "pre_mortem_invariant_breaks": (
        "[自审策略: 事前分析不变量突破]\n"
        "假设你的预测已经错了，回溯分析哪个'不变量'（你认为不会改变的前提）被突破了。"
        "列出所有隐含不变量，逐一评估被突破的可能性。"
    ),
    "premortem_scenario_matrix + analog_episode_backcast + signal_leakage_check": (
        "[自审策略: 事前分析矩阵+类比回测+信号泄漏检查]\n"
        "三重自审：(1) 构建失败场景矩阵，分析每种失败路径的概率；"
        "(2) 用类似历史事件回测你的推理是否能预测已知结果；"
        "(3) 检查是否有信号泄漏（用了不该用的未来信息）。"
    ),
    "retrodictive_backtest_with_synthetic_controls_and_order_invariants": (
        "[自审策略: 回溯测试+合成对照+排序不变量]\n"
        "在历史数据上回测你的预测逻辑，使用合成对照组验证因果关系，"
        "并检查排序不变量——如果A>B>C在历史上始终成立，你的预测是否违反了这个序？"
    ),
    "timeline_coherence_and_actor_capability_stress_test": (
        "[自审策略: 时间线连贯性+参与者能力压力测试]\n"
        "检查你的推理时间线是否连贯（事件顺序是否合理、时间间隔是否够用），"
        "并压力测试关键参与者是否真的有能力做到你假设的行为。"
    ),
    "unit_scale_sanity + rank_order_consistency + counterfactual_lob_replay "
    "+ cross_venue_leadlag + signal_orthogonality": (
        "[自审策略: 多维健全性检查]\n"
        "五重检查：(1) 单位和量级是否合理；(2) 排序一致性；"
        "(3) 反事实回放验证；(4) 跨场所领先滞后关系；"
        "(5) 信号正交性（确认不是重复计算同一信息）。"
    ),
})

TERMINATION_TEMPLATES.update({
    "actionability_ev_gate": (
        "[停止条件: 可操作性期望值门]\n"
        "当继续搜索的边际信息不再改变你的最终行动建议时停止。"
        "即使不确定性仍在，只要最优行动已经明确就可以停止。"
    ),
    "identifiability_reached+uncertainty_budget_exhausted": (
        "[停止条件: 可识别性达成+不确定性预算耗尽]\n"
        "双重停止条件：(1) 关键变量已可识别（不再混淆）；"
        "(2) 分配的不确定性探索预算已用完。任一条件满足即停止。"
    ),
    "marginal_analogy_gain_plateau": (
        "[停止条件: 边际类比收益平台期]\n"
        "当新找到的历史类比案例不再提供新的洞察或改变概率判断时停止。"
        "连续 2-3 个新类比都指向同一结论，则认为类比搜索已饱和。"
    ),
    "marginal_contradiction_plateau": (
        "[停止条件: 边际矛盾平台期]\n"
        "当新的反面搜索不再发现新的矛盾或反面证据时停止。"
        "已有的反面证据要么已被解释，要么已纳入概率判断。"
    ),
    "value-of-information saturation: stop when marginal expected decision-impact "
    "per additional query falls below a threshold for all top actions": (
        "[停止条件: 信息价值饱和]\n"
        "当每次额外搜索对最终决策的边际期望影响低于阈值时停止。"
        "即搜索更多信息已经不会改变你选择哪个答案。"
    ),
})


# ──── QP-201: 8 维 TEMPLATES 主字典 ────

TEMPLATES: Dict[str, Dict[str, str]] = {
    "hypothesis_framing": FRAMING_TEMPLATES,
    "query_policy": QUERY_TEMPLATES,
    "evidence_source": EVIDENCE_TEMPLATES,
    "retrieval_depth": RETRIEVAL_TEMPLATES,
    "update_policy": UPDATE_TEMPLATES,
    "audit_policy": AUDIT_TEMPLATES,
    "termination_policy": TERMINATION_TEMPLATES,
}


class StrategyCompiler:
    """策略编译器 — QP-209/211

    将 8 维 StrategyDefinition 编译为 multi_path 可用的 dict 格式。
    """

    def __init__(
        self,
        framing_templates: Dict[str, str] = None,
        query_templates: Dict[str, str] = None,
        evidence_templates: Dict[str, str] = None,
        retrieval_templates: Dict[str, str] = None,
        update_templates: Dict[str, str] = None,
        audit_templates: Dict[str, str] = None,
        termination_templates: Dict[str, str] = None,
    ):
        """QP-211: 支持自定义模板覆盖"""
        self._templates = {
            "hypothesis_framing": framing_templates or FRAMING_TEMPLATES,
            "query_policy": query_templates or QUERY_TEMPLATES,
            "evidence_source": evidence_templates or EVIDENCE_TEMPLATES,
            "retrieval_depth": retrieval_templates or RETRIEVAL_TEMPLATES,
            "update_policy": update_templates or UPDATE_TEMPLATES,
            "audit_policy": audit_templates or AUDIT_TEMPLATES,
            "termination_policy": termination_templates or TERMINATION_TEMPLATES,
        }

    def compile(self, strategy: StrategyDefinition) -> Dict[str, Any]:
        """QP-209: 8 维 → prompt_suffix

        Returns:
            兼容 STRATEGY_VARIANTS 格式的 dict:
            {
                "name": str,
                "description": str,
                "max_turns": int,
                "prompt_suffix": str,
                "_strategy_def": StrategyDefinition,
            }
        """
        prompt_parts = []

        # 按维度顺序拼接模板
        dim_template_map = [
            ("hypothesis_framing", strategy.hypothesis_framing),
            ("query_policy", strategy.query_policy),
            ("evidence_source", strategy.evidence_source),
            ("retrieval_depth", strategy.retrieval_depth),
            ("update_policy", strategy.update_policy),
            ("audit_policy", strategy.audit_policy),
            ("termination_policy", strategy.termination_policy),
        ]

        for dim_name, dim_value in dim_template_map:
            templates = self._templates[dim_name]
            if dim_value in templates:
                prompt_parts.append(templates[dim_value])
            else:
                # 未知维度值，跳过并警告
                prompt_parts.append(f"[{dim_name}: {dim_value}]")

        prompt_suffix = (
            f"\n\n[Strategy: {strategy.name}]\n\n"
            + "\n\n".join(prompt_parts)
        )

        return {
            "name": strategy.id,
            "description": strategy.name,
            "max_turns": strategy.max_turns,
            "prompt_suffix": prompt_suffix,
            "_strategy_def": strategy,
        }


# ──── 模块级便捷函数 ────

_default_compiler = StrategyCompiler()


def compile_strategy(strategy: StrategyDefinition) -> Dict[str, Any]:
    """QP-209: 模块级便捷函数"""
    return _default_compiler.compile(strategy)
