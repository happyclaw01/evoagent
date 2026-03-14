# Copyright (c) 2025 MiroMind
# EA-304: Cost Tracker
#
# Tracks token consumption and API costs for each path,
# enabling cost optimization decisions.

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any


# Model pricing (per 1M tokens) - Claude Max direct API
# Claude Max has quota limits, not per-token billing
# Prices listed here are Anthropic's standard API rates for reference/tracking
MODEL_PRICING = {
    # Anthropic Claude models (direct API)
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-haiku-3-5": {"input": 0.80, "output": 4.00},
    "claude-3-7-sonnet-20250219": {"input": 3.00, "output": 15.00},
    # Default fallback pricing
    "default": {"input": 3.00, "output": 15.00},
}


@dataclass
class PathCost:
    """Cost data for a single path."""
    path_id: str
    strategy_name: str
    model_name: str
    input_tokens: int = 0
    output_tokens: int = 0
    num_turns: int = 0
    num_tool_calls: int = 0
    duration_seconds: float = 0.0
    cost_usd: float = 0.0
    status: str = "unknown"
    
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CostSummary:
    """Summary of costs across all paths."""
    total_paths: int
    successful_paths: int
    failed_paths: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: float
    avg_cost_per_path: float
    avg_cost_per_successful_path: float
    total_duration_seconds: float
    path_costs: List[Dict[str, Any]]
    recommendations: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CostTracker:
    """
    Tracks and calculates costs for multi-path execution.
    
    Usage:
        tracker = CostTracker()
        
        # Record cost for each path
        tracker.record_path_cost(
            path_id="path_0_breadth_first",
            strategy_name="breadth_first",
            model_name="claude-sonnet-4-20250514",
            input_tokens=5000,
            output_tokens=2000,
            num_turns=5,
            num_tool_calls=10,
            duration_seconds=45.0,
            status="success"
        )
        
        # Get summary
        summary = tracker.get_summary()
        print(f"Total cost: ${summary.total_cost_usd:.4f}")
    """
    
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.path_costs: List[PathCost] = []
    
    def _get_model_price(self, model_name: str) -> Dict[str, float]:
        """Get pricing for a model, fallback to default if not found."""
        # Try exact match first
        if model_name in MODEL_PRICING:
            return MODEL_PRICING[model_name]
        
        # Try partial match (e.g., "claude-sonnet-4-20250514" should match)
        for key in MODEL_PRICING:
            if key != "default" and key.lower() in model_name.lower():
                return MODEL_PRICING[key]
        
        return MODEL_PRICING["default"]
    
    def _calculate_cost(
        self, 
        model_name: str, 
        input_tokens: int, 
        output_tokens: int
    ) -> float:
        """Calculate cost in USD based on token usage and model pricing."""
        price = self._get_model_price(model_name)
        
        input_cost = (input_tokens / 1_000_000) * price["input"]
        output_cost = (output_tokens / 1_000_000) * price["output"]
        
        return input_cost + output_cost
    
    def record_path_cost(
        self,
        path_id: str,
        strategy_name: str,
        model_name: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        num_turns: int = 0,
        num_tool_calls: int = 0,
        duration_seconds: float = 0.0,
        status: str = "unknown",
    ) -> PathCost:
        """Record cost data for a single path."""
        cost_usd = self._calculate_cost(model_name, input_tokens, output_tokens)
        
        path_cost = PathCost(
            path_id=path_id,
            strategy_name=strategy_name,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            num_turns=num_turns,
            num_tool_calls=num_tool_calls,
            duration_seconds=duration_seconds,
            cost_usd=cost_usd,
            status=status,
        )
        
        self.path_costs.append(path_cost)
        
        return path_cost
    
    def get_summary(self) -> CostSummary:
        """Get cost summary across all recorded paths."""
        if not self.path_costs:
            return CostSummary(
                total_paths=0,
                successful_paths=0,
                failed_paths=0,
                total_input_tokens=0,
                total_output_tokens=0,
                total_tokens=0,
                total_cost_usd=0.0,
                avg_cost_per_path=0.0,
                avg_cost_per_successful_path=0.0,
                total_duration_seconds=0.0,
                path_costs=[],
                recommendations=["No path data available"],
            )
        
        successful_paths = [p for p in self.path_costs if p.status == "success"]
        failed_paths = [p for p in self.path_costs if p.status in ("failed", "cancelled")]
        
        total_input = sum(p.input_tokens for p in self.path_costs)
        total_output = sum(p.output_tokens for p in self.path_costs)
        total_cost = sum(p.cost_usd for p in self.path_costs)
        total_duration = sum(p.duration_seconds for p in self.path_costs)
        
        num_paths = len(self.path_costs)
        num_successful = len(successful_paths)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            num_paths, num_successful, total_cost, 
            [p.cost_usd for p in self.path_costs]
        )
        
        return CostSummary(
            total_paths=num_paths,
            successful_paths=num_successful,
            failed_paths=len(failed_paths),
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_tokens=total_input + total_output,
            total_cost_usd=total_cost,
            avg_cost_per_path=total_cost / num_paths if num_paths > 0 else 0,
            avg_cost_per_successful_path=(
                total_cost / num_successful if num_successful > 0 else 0
            ),
            total_duration_seconds=total_duration,
            path_costs=[p.to_dict() for p in self.path_costs],
            recommendations=recommendations,
        )
    
    def _generate_recommendations(
        self,
        total_paths: int,
        successful_paths: int,
        total_cost: float,
        path_costs: List[float],
    ) -> List[str]:
        """Generate cost optimization recommendations."""
        recs = []
        
        # Check success rate
        if total_paths > 0:
            success_rate = successful_paths / total_paths
            if success_rate < 0.5:
                recs.append(
                    f"Low success rate ({success_rate*100:.0f}%). "
                    "Consider simplifying strategies or reducing path count."
                )
        
        # Check cost efficiency
        if path_costs:
            avg_cost = sum(path_costs) / len(path_costs)
            max_cost = max(path_costs)
            min_cost = min(path_costs)
            
            if max_cost > avg_cost * 3:
                expensive_paths = [
                    p.path_id for p in self.path_costs 
                    if p.cost_usd > avg_cost * 2
                ]
                recs.append(
                    f"High cost variance detected. Paths {expensive_paths} "
                    "cost significantly more. Review their execution."
                )
        
        # Check if early stopping would help
        if total_paths >= 3 and successful_paths == 1:
            recs.append(
                "Only 1 path succeeded. Consider enabling early stopping "
                "to cancel remaining paths earlier."
            )
        
        # Cost warning
        if total_cost > 1.0:
            recs.append(
                f"High total cost (${total_cost:.2f}). "
                "Consider using smaller models or reducing path count."
            )
        
        if not recs:
            recs.append("Cost efficiency looks good.")
        
        return recs
    
    def save_to_file(self, filepath: Optional[str] = None) -> str:
        """Save cost data to JSON file."""
        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = self.log_dir / f"cost_tracking_{timestamp}.json"
        else:
            filepath = Path(filepath)
        
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        summary = self.get_summary()
        
        with open(filepath, "w") as f:
            json.dump(summary.to_dict(), f, indent=2)
        
        return str(filepath)
    
    def load_from_results(self, result_paths: List[str]) -> None:
        """Load cost data from existing task log files."""
        for log_path in result_paths:
            try:
                with open(log_path) as f:
                    log_data = json.load(f)
                
                # Extract cost-relevant data from log
                path_id = log_data.get("task_id", "unknown")
                strategy = "unknown"
                
                # Try to extract strategy from path_id
                if "breadth" in path_id:
                    strategy = "breadth_first"
                elif "depth" in path_id:
                    strategy = "depth_first"
                elif "lateral" in path_id:
                    strategy = "lateral_thinking"
                
                # Extract usage data
                usage = log_data.get("usage_log", {})
                if isinstance(usage, dict):
                    # Handle different usage log formats
                    input_tokens = 0
                    output_tokens = 0
                    
                    if "input_tokens" in usage:
                        input_tokens = usage.get("input_tokens", 0)
                        output_tokens = usage.get("output_tokens", 0)
                    elif "total" in usage:
                        # Another format: total, input, output
                        input_tokens = usage.get("input", 0)
                        output_tokens = usage.get("output", 0)
                    
                    # Get model name
                    model_name = usage.get("model", "claude-sonnet-4-20250514")
                    
                    # Get status
                    status = log_data.get("status", "unknown")
                    
                    # Get duration if available
                    start_time = log_data.get("start_time", "")
                    end_time = log_data.get("end_time", "")
                    duration = 0.0
                    if start_time and end_time:
                        try:
                            start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                            end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                            duration = (end - start).total_seconds()
                        except:
                            pass
                    
                    self.record_path_cost(
                        path_id=path_id,
                        strategy_name=strategy,
                        model_name=model_name,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        num_turns=log_data.get("turn_count", 0),
                        num_tool_calls=log_data.get("tool_call_count", 0),
                        duration_seconds=duration,
                        status=status,
                    )
            except Exception as e:
                # Skip invalid log files
                pass


def format_cost_report(summary: CostSummary) -> str:
    """Format cost summary as human-readable report."""
    lines = [
        "=" * 50,
        "EvoAgent Cost Report",
        "=" * 50,
        "",
        f"Total Paths: {summary.total_paths}",
        f"  - Successful: {summary.successful_paths}",
        f"  - Failed: {summary.failed_paths}",
        "",
        "Token Usage:",
        f"  - Input:  {summary.total_input_tokens:,}",
        f"  - Output: {summary.total_output_tokens:,}",
        f"  - Total:  {summary.total_tokens:,}",
        "",
        f"Total Cost: ${summary.total_cost_usd:.4f}",
        f"  - Avg per path: ${summary.avg_cost_per_path:.4f}",
        f"  - Avg per success: ${summary.avg_cost_per_successful_path:.4f}",
        "",
        f"Total Duration: {summary.total_duration_seconds:.1f}s",
        "",
        "Recommendations:",
    ]
    
    for i, rec in enumerate(summary.recommendations, 1):
        lines.append(f"  {i}. {rec}")
    
    lines.append("")
    lines.append("=" * 50)
    
    return "\n".join(lines)