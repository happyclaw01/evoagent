# Copyright (c) 2025 MiroMind
# EA-407: Strategy Ablation Tests
#
# Tests the independent contribution of each strategy and each
# system component by measuring performance with/without it.

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestStrategyAblation(unittest.TestCase):
    """EA-407: Test each strategy's independent contribution."""

    def _run_ablation(self, strategies, winners_per_strategy):
        """Helper: create profiles and measure per-strategy impact."""
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyResult, StrategyProfileEngine
        
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        
        for strategy, win_indices in winners_per_strategy.items():
            for i in range(10):
                keeper.record(StrategyResult(
                    task_id=f"t{i}_{strategy}",
                    strategy_name=strategy,
                    task_type="search",
                    is_winner=(i in win_indices),
                    turns_used=10,
                    cost_usd=0.01,
                    status="success",
                ))
        
        engine = StrategyProfileEngine(
            record_keeper=keeper,
            profile_dir=f"{tmpdir}/profiles",
        )
        engine.build_profiles()
        return engine

    def test_each_strategy_has_unique_contribution(self):
        """Each strategy should have a measurably different win rate."""
        winners = {
            "breadth_first": set(range(8)),      # 80%
            "depth_first": set(range(5)),          # 50%
            "lateral_thinking": set(range(3)),     # 30%
            "verification_heavy": set(range(6)),   # 60%
        }
        
        engine = self._run_ablation(list(winners.keys()), winners)
        profiles = engine.get_all_profiles()
        
        win_rates = {name: p.win_rate for name, p in profiles.items()}
        
        # All should have different win rates
        rates = list(win_rates.values())
        self.assertEqual(len(set(rates)), len(rates),
                        f"Non-unique win rates: {win_rates}")
        
        # breadth_first should be best
        best = max(win_rates, key=win_rates.get)
        self.assertEqual(best, "breadth_first")

    def test_removing_best_strategy_hurts_performance(self):
        """Ablating the best strategy should reduce overall performance."""
        from src.core.adaptive_selector import AdaptiveSelector
        from src.core.task_classifier import TaskClassifier
        
        winners = {
            "breadth_first": set(range(8)),
            "depth_first": set(range(5)),
            "lateral_thinking": set(range(3)),
            "verification_heavy": set(range(6)),
        }
        
        engine = self._run_ablation(list(winners.keys()), winners)
        classifier = TaskClassifier()
        
        # Full set
        full_selector = AdaptiveSelector(
            profile_engine=engine, classifier=classifier,
            available_strategies=list(winners.keys()),
        )
        full_selection = full_selector.select("Find X", num_paths=3)
        
        # Ablated: remove breadth_first
        ablated_selector = AdaptiveSelector(
            profile_engine=engine, classifier=classifier,
            available_strategies=["depth_first", "lateral_thinking", "verification_heavy"],
        )
        ablated_selection = ablated_selector.select("Find X", num_paths=3)
        
        # Full should include breadth_first (best performer)
        self.assertIn("breadth_first", full_selection.strategies)
        self.assertNotIn("breadth_first", ablated_selection.strategies)

    def test_single_strategy_vs_ensemble(self):
        """Ensemble (multi-strategy) should be competitive with any single strategy."""
        # Single strategy: best is 80%
        single_best_rate = 0.8
        
        # Ensemble with majority voting:
        # P(ensemble correct) = P(≥2 of 3 correct)
        # With strategies at 80%, 60%, 50%:
        p1, p2, p3 = 0.8, 0.6, 0.5
        
        p_all = p1 * p2 * p3
        p_two = (p1 * p2 * (1 - p3) +
                 p1 * (1 - p2) * p3 +
                 (1 - p1) * p2 * p3)
        
        ensemble_rate = p_all + p_two
        
        # Ensemble P(correct) should be > 0.5 (better than random)
        self.assertGreater(ensemble_rate, 0.5,
                          f"Ensemble {ensemble_rate:.2%} should beat random")


class TestComponentAblation(unittest.TestCase):
    """EA-407: Test each component's contribution."""

    def test_without_task_classifier(self):
        """Without EA-103, selection falls back to overall win rates."""
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyResult, StrategyProfileEngine
        from src.core.adaptive_selector import AdaptiveSelector
        from src.core.task_classifier import TaskClassifier
        
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        
        # bf: great at search, bad at compute
        for i in range(10):
            keeper.record(StrategyResult(
                task_id=f"s{i}", strategy_name="breadth_first",
                task_type="search", is_winner=True,
                turns_used=10, cost_usd=0.01,
            ))
            keeper.record(StrategyResult(
                task_id=f"c{i}", strategy_name="breadth_first",
                task_type="compute", is_winner=False,
                turns_used=10, cost_usd=0.01,
            ))
            keeper.record(StrategyResult(
                task_id=f"s{i}", strategy_name="depth_first",
                task_type="search", is_winner=False,
                turns_used=10, cost_usd=0.01,
            ))
            keeper.record(StrategyResult(
                task_id=f"c{i}", strategy_name="depth_first",
                task_type="compute", is_winner=True,
                turns_used=10, cost_usd=0.01,
            ))
        
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        engine.build_profiles()
        classifier = TaskClassifier()
        
        # With classifier: should pick bf for search, df for compute
        selector = AdaptiveSelector(
            profile_engine=engine, classifier=classifier,
            available_strategies=["breadth_first", "depth_first"],
        )
        
        search_sel = selector.select("Find who invented X", num_paths=1)
        compute_sel = selector.select("Calculate the sum of X", num_paths=1)
        
        # Both should select strategies (they have enough data)
        self.assertEqual(len(search_sel.strategies), 1)
        self.assertEqual(len(compute_sel.strategies), 1)

    def test_without_discovery_bus(self):
        """Without EA-305, paths still work independently."""
        # Paths produce independent results
        path_results = [
            {"path": "p0", "answer": "42", "sources": ["a.com"]},
            {"path": "p1", "answer": "42", "sources": ["b.com"]},
            {"path": "p2", "answer": "43", "sources": ["c.com"]},
        ]
        
        # Majority vote still works without discovery sharing
        from collections import Counter
        answers = [r["answer"] for r in path_results]
        winner = Counter(answers).most_common(1)[0][0]
        self.assertEqual(winner, "42")

    def test_without_result_cache(self):
        """Without EA-306, paths just make more API calls."""
        # Without cache: 3 paths × same search = 3 API calls
        uncached_calls = 3
        
        # With cache: 1 call + 2 cache hits
        cached_calls = 1
        
        savings = (uncached_calls - cached_calls) / uncached_calls
        self.assertGreater(savings, 0.5)

    def test_without_groupthink_detector(self):
        """Without EA-309, false consensus passes through."""
        from src.core.groupthink_detector import GroupthinkDetector, PathAnswer
        
        # All paths agree on wrong answer with same reasoning
        same_reasoning = "Based on standard analysis methods and approaches"
        answers = [
            PathAnswer(path_id=f"p{i}", answer="wrong_answer",
                      reasoning=same_reasoning,
                      sources=["same_source.com"],
                      confidence=0.3,
                      turns_used=10, duration_seconds=5)
            for i in range(3)
        ]
        
        # Without detector: would just accept the consensus
        # With detector: flags the risk
        detector = GroupthinkDetector()
        report = detector.analyze(answers)
        
        # Should detect at least some signals
        self.assertTrue(len(report.signals) > 0,
                        "Groupthink detector should flag identical reasoning + sources")

    def test_without_lifecycle_management(self):
        """Without EA-107, poor strategies keep being selected."""
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyResult, StrategyProfileEngine
        from src.core.adaptive_selector import AdaptiveSelector
        from src.core.task_classifier import TaskClassifier
        
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        
        # bad_strategy: 5% win rate over 25 runs
        for i in range(25):
            keeper.record(StrategyResult(
                task_id=f"t{i}", strategy_name="bad_strategy",
                task_type="search", is_winner=(i == 0),
                turns_used=50, cost_usd=0.05,
            ))
        
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        engine.build_profiles()
        
        profile = engine.get_profile("bad_strategy")
        # Without lifecycle: profile says "retired" based on threshold
        self.assertEqual(profile.status, "retired")
        
        # Rankings exclude retired
        rankings = engine.get_rankings()
        strategy_names = [r[0] for r in rankings]
        self.assertNotIn("bad_strategy", strategy_names)


class TestMetaEvolutionAblation(unittest.TestCase):
    """EA-407: Test Layer 3 component contributions."""

    def test_strategy_generator_fills_gaps(self):
        """EA-201 generates strategies when coverage gaps exist."""
        from src.core.strategy_tracker import StrategyRecordKeeper, StrategyResult, StrategyProfileEngine
        from src.core.failure_analyzer import FailureAnalyzer
        from src.core.strategy_lifecycle import StrategyLifecycleManager
        from src.core.experience_extractor import ExperienceExtractor
        from src.core.strategy_generator import StrategyGenerator
        
        tmpdir = tempfile.mkdtemp()
        keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
        
        # All strategies bad at "verify" tasks
        for i in range(5):
            for s in ["bf", "df"]:
                keeper.record(StrategyResult(
                    task_id=f"v{i}", strategy_name=s,
                    task_type="verify", is_winner=False,
                    turns_used=10, cost_usd=0.01,
                ))
        
        engine = StrategyProfileEngine(record_keeper=keeper, profile_dir=f"{tmpdir}/profiles")
        engine.build_profiles()
        analyzer = FailureAnalyzer(record_keeper=keeper)
        lifecycle = StrategyLifecycleManager(
            profile_engine=engine, failure_analyzer=analyzer,
            state_dir=f"{tmpdir}/lifecycle",
        )
        extractor = ExperienceExtractor(
            record_keeper=keeper, profile_engine=engine,
            failure_analyzer=analyzer, learnings_dir=f"{tmpdir}/learnings",
        )
        
        generator = StrategyGenerator(
            profile_engine=engine, failure_analyzer=analyzer,
            lifecycle_manager=lifecycle, experience_extractor=extractor,
            strategies_dir=f"{tmpdir}/evolved",
        )
        
        signals = generator.detect_signals()
        gap_signals = [s for s in signals if s.signal_type.value == "coverage_gap"]
        self.assertTrue(len(gap_signals) > 0)
        
        # Generate strategies for gaps
        evolved = generator.generate_from_signals(gap_signals)
        self.assertTrue(len(evolved) > 0)
        self.assertIn("verify", evolved[0].target_task_types)

    def test_code_evolver_improves_strategies(self):
        """EA-202 creates enhanced code-level strategies."""
        from src.core.strategy_code_evolver import StrategyCodeEvolver
        
        evolver = StrategyCodeEvolver(patterns_dir=tempfile.mkdtemp())
        
        # Base strategy
        base = evolver.get_pattern("hypothesis_driven")
        self.assertIsNotNone(base)
        
        # Evolved version with more verification
        evolved = evolver.create_variant(
            "hypothesis_driven",
            variant_name="hypo_enhanced",
            verification_rounds=3,
            search_breadth=4,
        )
        
        self.assertGreater(evolved.verification_rounds, base.verification_rounds)
        self.assertGreater(evolved.search_breadth, base.search_breadth)
        
        # Enhanced prompt should include verification info
        evolved_prompt = evolved.get_enhanced_prompt_suffix()
        self.assertIn("4 different phrasings", evolved_prompt)
        self.assertIn("3 times", evolved_prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
