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
