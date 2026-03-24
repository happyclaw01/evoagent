# Tests for EA-408, EA-409, EA-410: Continuous Prediction System

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

from src.core.prediction_engine import (
    Prediction,
    PredictionEngine,
    PredictionUpdate,
    PredictionValidation,
)


class TestPredictionDataModels(unittest.TestCase):
    """Test data model serialization/deserialization."""

    def test_prediction_roundtrip(self):
        pred = Prediction(
            id="test_001",
            target="VOO",
            target_type="stock",
            created_at="2026-03-20T20:15:00Z",
            data_cutoff="2026-03-20T20:15:00Z",
            resolve_at="2026-03-23T21:00:00Z",
            direction="down",
            confidence=0.7,
            predicted_open=597.0,
            predicted_close=593.0,
            key_drivers=["Middle East war", "oil price"],
            strategies_used=["intel_analysis", "depth_first"],
        )
        d = pred.to_dict()
        restored = Prediction.from_dict(d)
        self.assertEqual(restored.id, "test_001")
        self.assertEqual(restored.direction, "down")
        self.assertEqual(restored.confidence, 0.7)
        self.assertEqual(restored.predicted_open, 597.0)
        self.assertEqual(len(restored.key_drivers), 2)

    def test_prediction_with_updates_roundtrip(self):
        pred = Prediction(
            id="test_002",
            target="BTC",
            target_type="crypto",
            created_at="2026-03-20T10:00:00Z",
            data_cutoff="2026-03-20T10:00:00Z",
            resolve_at="2026-03-21T00:00:00Z",
            direction="up",
            confidence=0.6,
        )
        update = PredictionUpdate(
            prediction_id="test_002",
            timestamp="2026-03-20T12:00:00Z",
            current_price=85000.0,
            updated_direction="down",
            reason="breaking_news",
            new_info="Fed rate hike announced",
        )
        pred.updates.append(update)
        d = pred.to_dict()
        restored = Prediction.from_dict(d)
        self.assertEqual(len(restored.updates), 1)
        self.assertEqual(restored.updates[0].updated_direction, "down")
        self.assertEqual(restored.updates[0].reason, "breaking_news")

    def test_prediction_with_validation_roundtrip(self):
        pred = Prediction(
            id="test_003",
            target="VOO",
            target_type="stock",
            created_at="2026-03-20T20:15:00Z",
            data_cutoff="2026-03-20T20:15:00Z",
            resolve_at="2026-03-23T21:00:00Z",
            direction="down",
            confidence=0.7,
            predicted_open=597.0,
            predicted_close=593.0,
        )
        pred.validation = PredictionValidation(
            prediction_id="test_003",
            validated_at="2026-03-23T21:00:00Z",
            actual_open=598.0,
            actual_close=590.0,
            actual_change_pct=-1.34,
            direction_correct=True,
            magnitude_error_pct=0.5,
        )
        d = pred.to_dict()
        restored = Prediction.from_dict(d)
        self.assertIsNotNone(restored.validation)
        self.assertTrue(restored.validation.direction_correct)


class TestPredictionEngine(unittest.TestCase):
    """Test the PredictionEngine lifecycle."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = PredictionEngine(store_dir=self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_prediction(self):
        pred = self.engine.create_prediction(
            target="VOO",
            target_type="stock",
            direction="down",
            confidence=0.7,
            resolve_at="2026-03-23T21:00:00Z",
            predicted_open=597.0,
            predicted_close=593.0,
            key_drivers=["oil", "war"],
            strategies_used=["intel_analysis"],
        )
        self.assertIn(pred.id, self.engine.predictions)
        self.assertEqual(pred.target, "VOO")
        self.assertEqual(pred.direction, "down")
        # Verify persisted
        files = list(os.listdir(self.tmpdir))
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith(".json"))

    def test_create_and_reload(self):
        pred = self.engine.create_prediction(
            target="SPY",
            target_type="stock",
            direction="up",
            confidence=0.55,
            resolve_at="2026-03-24T21:00:00Z",
        )
        # Create new engine from same dir
        engine2 = PredictionEngine(store_dir=self.tmpdir)
        self.assertIn(pred.id, engine2.predictions)
        self.assertEqual(engine2.predictions[pred.id].direction, "up")

    def test_update_prediction(self):
        pred = self.engine.create_prediction(
            target="VOO",
            target_type="stock",
            direction="down",
            confidence=0.7,
            resolve_at="2026-03-23T21:00:00Z",
            predicted_close=593.0,
        )
        update = self.engine.update_prediction(
            prediction_id=pred.id,
            current_price=595.0,
            reason="scheduled",
        )
        self.assertEqual(len(pred.updates), 1)
        self.assertEqual(update.current_price, 595.0)

    def test_update_with_direction_change(self):
        pred = self.engine.create_prediction(
            target="VOO",
            target_type="stock",
            direction="down",
            confidence=0.7,
            resolve_at="2026-03-23T21:00:00Z",
        )
        self.engine.update_prediction(
            prediction_id=pred.id,
            current_price=610.0,
            reason="breaking_news",
            new_info="Ceasefire announced",
            updated_direction="up",
            updated_close=615.0,
            updated_confidence=0.6,
        )
        self.assertEqual(pred.updates[-1].updated_direction, "up")
        self.assertEqual(pred.updates[-1].updated_close, 615.0)

    def test_update_nonexistent_raises(self):
        with self.assertRaises(ValueError):
            self.engine.update_prediction(
                prediction_id="nonexistent",
                current_price=100.0,
            )

    def test_should_update_no_baseline(self):
        pred = self.engine.create_prediction(
            target="X",
            target_type="stock",
            direction="up",
            confidence=0.5,
            resolve_at="2026-04-01T00:00:00Z",
        )
        should, reason = self.engine.should_update(pred.id, 100.0)
        self.assertTrue(should)

    def test_should_update_within_threshold(self):
        pred = self.engine.create_prediction(
            target="X",
            target_type="stock",
            direction="up",
            confidence=0.5,
            resolve_at="2026-04-01T00:00:00Z",
            predicted_close=100.0,
        )
        should, reason = self.engine.should_update(pred.id, 100.5, price_threshold_pct=1.0)
        self.assertFalse(should)

    def test_should_update_exceeds_threshold(self):
        pred = self.engine.create_prediction(
            target="X",
            target_type="stock",
            direction="up",
            confidence=0.5,
            resolve_at="2026-04-01T00:00:00Z",
            predicted_close=100.0,
        )
        should, reason = self.engine.should_update(pred.id, 102.0, price_threshold_pct=1.0)
        self.assertTrue(should)
        self.assertIn("price_move", reason)


class TestPredictionValidation(unittest.TestCase):
    """Test validation and trajectory analysis."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = PredictionEngine(store_dir=self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_validate_correct_direction(self):
        pred = self.engine.create_prediction(
            target="VOO",
            target_type="stock",
            direction="down",
            confidence=0.7,
            resolve_at="2026-03-23T21:00:00Z",
            predicted_open=597.0,
            predicted_close=593.0,
        )
        v = self.engine.validate_prediction(
            prediction_id=pred.id,
            actual_open=598.0,
            actual_close=590.0,
        )
        self.assertTrue(v.direction_correct)
        self.assertLess(v.magnitude_error_pct, 5.0)

    def test_validate_wrong_direction(self):
        pred = self.engine.create_prediction(
            target="VOO",
            target_type="stock",
            direction="down",
            confidence=0.7,
            resolve_at="2026-03-23T21:00:00Z",
            predicted_open=597.0,
            predicted_close=593.0,
        )
        v = self.engine.validate_prediction(
            prediction_id=pred.id,
            actual_open=597.0,
            actual_close=605.0,
        )
        self.assertFalse(v.direction_correct)

    def test_validate_with_post_events(self):
        pred = self.engine.create_prediction(
            target="VOO",
            target_type="stock",
            direction="down",
            confidence=0.7,
            resolve_at="2026-03-23T21:00:00Z",
            predicted_open=597.0,
            predicted_close=593.0,
        )
        v = self.engine.validate_prediction(
            prediction_id=pred.id,
            actual_open=610.0,
            actual_close=615.0,
            post_prediction_events=["Ceasefire announced Sunday night"],
        )
        self.assertFalse(v.direction_correct)
        self.assertEqual(len(v.post_prediction_events), 1)

    def test_convergence_analysis(self):
        pred = self.engine.create_prediction(
            target="VOO",
            target_type="stock",
            direction="down",
            confidence=0.7,
            resolve_at="2026-03-23T21:00:00Z",
            predicted_close=593.0,
        )
        # Updates that converge toward actual (590)
        self.engine.update_prediction(pred.id, 595.0, updated_close=592.0)
        self.engine.update_prediction(pred.id, 591.0, updated_close=590.0)
        v = self.engine.validate_prediction(
            prediction_id=pred.id,
            actual_open=597.0,
            actual_close=590.0,
        )
        self.assertEqual(v.convergence, "converged")
        self.assertEqual(v.num_updates, 2)

    def test_divergence_analysis(self):
        pred = self.engine.create_prediction(
            target="VOO",
            target_type="stock",
            direction="down",
            confidence=0.7,
            resolve_at="2026-03-23T21:00:00Z",
            predicted_close=593.0,
        )
        # Updates that diverge from actual (590)
        self.engine.update_prediction(pred.id, 595.0, updated_close=595.0)
        self.engine.update_prediction(pred.id, 598.0, updated_close=600.0)
        v = self.engine.validate_prediction(
            prediction_id=pred.id,
            actual_open=597.0,
            actual_close=590.0,
        )
        self.assertEqual(v.convergence, "diverged")


class TestPredictionReport(unittest.TestCase):
    """Test report generation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = PredictionEngine(store_dir=self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_report_basic(self):
        pred = self.engine.create_prediction(
            target="VOO",
            target_type="stock",
            direction="down",
            confidence=0.7,
            resolve_at="2026-03-23T21:00:00Z",
            predicted_open=597.0,
            predicted_close=593.0,
            key_drivers=["oil", "war"],
            strategies_used=["intel_analysis"],
        )
        report = self.engine.generate_report(pred.id)
        self.assertIn("VOO", report)
        self.assertIn("down", report)
        self.assertIn("oil", report)

    def test_report_with_validation(self):
        pred = self.engine.create_prediction(
            target="VOO",
            target_type="stock",
            direction="down",
            confidence=0.7,
            resolve_at="2026-03-23T21:00:00Z",
            predicted_open=597.0,
            predicted_close=593.0,
        )
        self.engine.validate_prediction(pred.id, 598.0, 590.0)
        report = self.engine.generate_report(pred.id)
        self.assertIn("✅ CORRECT", report)
        self.assertIn("Actual change", report)


class TestAccuracyStats(unittest.TestCase):
    """Test aggregate statistics."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = PredictionEngine(store_dir=self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_predictions(self):
        stats = self.engine.get_accuracy_stats()
        self.assertEqual(stats["total"], 0)

    def test_mixed_results(self):
        # Correct prediction
        p1 = self.engine.create_prediction("A", "stock", "down", 0.7, "2026-04-01",
                                            predicted_open=100.0, predicted_close=95.0)
        self.engine.validate_prediction(p1.id, 100.0, 96.0)

        # Wrong prediction
        p2 = self.engine.create_prediction("B", "stock", "up", 0.6, "2026-04-01",
                                            predicted_open=100.0, predicted_close=105.0)
        self.engine.validate_prediction(p2.id, 100.0, 97.0)

        stats = self.engine.get_accuracy_stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["direction_correct"], 1)
        self.assertEqual(stats["direction_wrong"], 1)
        self.assertAlmostEqual(stats["direction_accuracy"], 0.5)

    def test_list_predictions(self):
        p1 = self.engine.create_prediction("A", "stock", "up", 0.5, "2026-04-01")
        p2 = self.engine.create_prediction("B", "stock", "down", 0.5, "2026-04-01")
        self.engine.validate_prediction(p1.id, 100.0, 105.0)

        pending = self.engine.list_predictions(status="pending")
        validated = self.engine.list_predictions(status="validated")
        self.assertEqual(len(pending), 1)
        self.assertEqual(len(validated), 1)


if __name__ == "__main__":
    unittest.main()
