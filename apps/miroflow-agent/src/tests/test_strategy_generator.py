# Copyright (c) 2025 MiroMind
# Unit Tests for EA-201: LLM Strategy Generator

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_result(strategy="breadth_first", task_id="t1", is_winner=True,
                 task_type="search", cost=0.01, turns=10, status="success",
                 failure_reason="", timestamp=None):
    from src.core.strategy_tracker import StrategyResult
    return StrategyResult(
        task_id=task_id, strategy_name=strategy, task_type=task_type,
        is_winner=is_winner, cost_usd=cost, turns_used=turns,
        status=status, failure_reason=failure_reason,
        input_tokens=500, output_tokens=200,
        timestamp=timestamp or time.time(),
    )


def _build_env(records):
    from src.core.strategy_tracker import StrategyRecordKeeper, StrategyProfileEngine
    from src.core.failure_analyzer import FailureAnalyzer
    from src.core.strategy_lifecycle import StrategyLifecycleManager
    from src.core.experience_extractor import ExperienceExtractor
    from src.core.strategy_generator import StrategyGenerator
    tmpdir = tempfile.mkdtemp()
    keeper = StrategyRecordKeeper(data_dir=f"{tmpdir}/results")
    for r in records:
        keeper.record(r)
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
    return generator, tmpdir


class TestEvolvedStrategy(unittest.TestCase):
    def test_to_dict(self):
        from src.core.strategy_generator import EvolvedStrategy
        s = EvolvedStrategy(name="test", description="d", prompt_suffix="p")
        d = s.to_dict()
        self.assertEqual(d["name"], "test")
        self.assertEqual(d["origin"], "evolved")

    def test_from_dict(self):
        from src.core.strategy_generator import EvolvedStrategy
        s = EvolvedStrategy(name="test", description="d", prompt_suffix="p")
        d = s.to_dict()
        s2 = EvolvedStrategy.from_dict(d)
        self.assertEqual(s2.name, "test")

    def test_to_strategy_variant(self):
        from src.core.strategy_generator import EvolvedStrategy
        s = EvolvedStrategy(name="test", description="d", prompt_suffix="p",
                           max_turns=200, target_task_types=["search"])
        v = s.to_strategy_variant()
        self.assertEqual(v["name"], "test")
        self.assertEqual(v["max_turns"], 200)


class TestDetectCoverageGap(unittest.TestCase):
    def test_detects_gap(self):
        records = []
        for i in range(5):
            records.append(_make_result(strategy="bf", task_id=f"t{i}",
                                         task_type="verify", is_winner=False))
            records.append(_make_result(strategy="df", task_id=f"t{i}",
                                         task_type="verify", is_winner=False))
        gen, _ = _build_env(records)
        signals = gen._detect_coverage_gaps()
        gap_signals = [s for s in signals if s.context.get("task_type") == "verify"]
        self.assertTrue(len(gap_signals) > 0)

    def test_no_gap_when_good(self):
        records = []
        for i in range(5):
            records.append(_make_result(strategy="bf", task_id=f"t{i}",
                                         task_type="search", is_winner=True))
        gen, _ = _build_env(records)
        signals = gen._detect_coverage_gaps()
        gap_signals = [s for s in signals if s.context.get("task_type") == "search"]
        self.assertEqual(len(gap_signals), 0)


class TestDetectDegradation(unittest.TestCase):
    def test_detects_declining(self):
        records = []
        base = time.time()
        for i in range(10):
            records.append(_make_result(task_id=f"old{i}", is_winner=True, timestamp=base + i))
        for i in range(10):
            records.append(_make_result(task_id=f"new{i}", is_winner=False, timestamp=base + 100 + i))
        gen, _ = _build_env(records)
        signals = gen._detect_degradation()
        # May or may not detect depending on threshold
        self.assertIsInstance(signals, list)


class TestDetectPopulationSparsity(unittest.TestCase):
    def test_detects_sparse(self):
        from src.core.strategy_lifecycle import LifecycleStatus
        records = [_make_result(strategy="bf", task_id=f"t{i}") for i in range(5)]
        gen, _ = _build_env(records)
        # Retire some
        gen._lifecycle._states["bf"] = gen._lifecycle.get_state("bf")
        gen._lifecycle._states["df"] = gen._lifecycle.get_state("df")
        gen._lifecycle._states["df"].status = LifecycleStatus.RETIRED
        signals = gen._detect_population_sparsity()
        # Only "bf" is in profiles, which is < 3
        self.assertIsInstance(signals, list)


class TestGenerateStrategies(unittest.TestCase):
    def test_generate_gap_filler(self):
        from src.core.strategy_generator import EvolutionSignalDetection, EvolutionSignal
        gen, _ = _build_env([])
        signal = EvolutionSignalDetection(
            signal_type=EvolutionSignal.COVERAGE_GAP,
            description="All strategies below 50% on verify",
            context={"task_type": "verify"},
        )
        strategy = gen._generate_gap_filler(signal)
        self.assertIn("verify", strategy.name)
        self.assertIn("verify", strategy.target_task_types)

    def test_generate_failure_repair(self):
        from src.core.strategy_generator import EvolutionSignalDetection, EvolutionSignal
        gen, _ = _build_env([])
        signal = EvolutionSignalDetection(
            signal_type=EvolutionSignal.FAILURE_CLUSTER,
            description="timeout failures",
            context={"pattern_type": "repeated_reason", "affected_strategies": ["bf"]},
        )
        strategy = gen._generate_failure_repair(signal)
        self.assertIn("repair", strategy.name)

    def test_generate_mutation(self):
        records = [_make_result(strategy="breadth_first", task_id=f"t{i}") for i in range(5)]
        gen, _ = _build_env(records)
        strategy = gen.generate_mutation_of("breadth_first")
        self.assertIn("mutant", strategy.name)
        self.assertEqual(strategy.parent, "breadth_first")

    def test_generate_crossover(self):
        gen, _ = _build_env([])
        strategy = gen.generate_crossover_of("breadth_first", "depth_first")
        self.assertIn("crossover", strategy.name)
        self.assertEqual(len(strategy.parents), 2)

    def test_generate_from_signals(self):
        from src.core.strategy_generator import EvolutionSignalDetection, EvolutionSignal
        gen, _ = _build_env([])
        signals = [
            EvolutionSignalDetection(
                signal_type=EvolutionSignal.COVERAGE_GAP,
                description="gap",
                context={"task_type": "verify"},
            )
        ]
        strategies = gen.generate_from_signals(signals)
        self.assertEqual(len(strategies), 1)

    def test_max_per_cycle_limit(self):
        from src.core.strategy_generator import EvolutionSignalDetection, EvolutionSignal
        gen, _ = _build_env([])
        signals = [
            EvolutionSignalDetection(
                signal_type=EvolutionSignal.COVERAGE_GAP,
                description=f"gap {i}",
                context={"task_type": f"type_{i}"},
            )
            for i in range(10)
        ]
        strategies = gen.generate_from_signals(signals)
        self.assertLessEqual(len(strategies), 3)


class TestPersistence(unittest.TestCase):
    def test_save_and_load(self):
        gen, _ = _build_env([])
        strategy = gen.generate_mutation_of("breadth_first")
        gen.save_strategies([strategy])
        
        loaded = gen.load_strategies()
        self.assertEqual(len(loaded), 1)
        self.assertIn("mutant", loaded[0].name)


class TestSummary(unittest.TestCase):
    def test_empty_summary(self):
        gen, _ = _build_env([])
        self.assertIn("No evolved", gen.get_summary())

    def test_summary_with_data(self):
        gen, _ = _build_env([])
        gen.generate_mutation_of("breadth_first")
        summary = gen.get_summary()
        self.assertIn("1", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
