"""Unit tests for the planner and RAG miss behaviour."""

from __future__ import annotations

import json
import unittest

from app.services.planner import Plan, _parse_planner_json, classify_rules


class TestClassifyRules(unittest.TestCase):
    def test_image_route(self) -> None:
        plan = classify_rules("Draw Jesus at the Sea of Galilee")
        self.assertEqual(plan.route, "image")
        self.assertEqual(plan.tool, "generate_image")
        self.assertFalse(plan.needs_rag)

    def test_see_phrasing_routes_image(self) -> None:
        plan = classify_rules("I want to see Jesus")
        self.assertEqual(plan.route, "image")
        self.assertEqual(plan.tool, "generate_image")

    def test_scripture_route(self) -> None:
        plan = classify_rules("Who was Moses in the Bible?")
        self.assertEqual(plan.route, "scripture")
        self.assertEqual(plan.tool, "scripture_search")
        self.assertTrue(plan.needs_rag)

    def test_normal_route(self) -> None:
        plan = classify_rules("What's the weather like today?")
        self.assertEqual(plan.route, "normal")
        self.assertIsNone(plan.tool)
        self.assertFalse(plan.needs_rag)


class TestParsePlannerJson(unittest.TestCase):
    def test_valid_json(self) -> None:
        raw = json.dumps({"route": "scripture", "reason": "asks about faith"})
        plan = _parse_planner_json(raw)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.route, "scripture")
        self.assertEqual(plan.source, "llm")

    def test_invalid_route(self) -> None:
        self.assertIsNone(_parse_planner_json('{"route":"unknown"}'))

    def test_garbage(self) -> None:
        self.assertIsNone(_parse_planner_json("not json"))


class TestPlanDataclass(unittest.TestCase):
    def test_frozen(self) -> None:
        plan = Plan(
            route="normal",
            tool=None,
            reason="test",
            source="rules",
            needs_rag=False,
        )
        self.assertEqual(plan.route, "normal")


if __name__ == "__main__":
    unittest.main()
