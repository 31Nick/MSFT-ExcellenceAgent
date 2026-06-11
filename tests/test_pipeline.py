"""Tests for the shared pipeline helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestBuildHierarchy:
    def test_returns_hierarchy_and_stats(self):
        """Verify build_hierarchy runs the full pipeline and returns tuple."""
        from excellence_agent.pipeline import build_hierarchy

        mock_report = MagicMock()
        mock_report.impacted_resources = MagicMock()

        mock_hierarchy = MagicMock()
        mock_hierarchy.summary_stats.return_value = {
            "epics": 2, "features": 3, "user_stories": 5, "recommendations": 10,
        }

        with (
            patch("excellence_agent.pipeline.APRLParser") as MockParser,
            patch("excellence_agent.pipeline.ResourceMapper") as MockMapper,
            patch("excellence_agent.pipeline.HierarchyBuilder") as MockBuilder,
            patch("excellence_agent.pipeline.load_resource_matrix") as mock_matrix,
        ):
            MockParser.return_value.parse.return_value = mock_report
            mock_matrix.return_value = {"categories": {}}
            MockMapper.return_value.map_dataframe.return_value = mock_report.impacted_resources
            MockBuilder.return_value.build.return_value = mock_hierarchy

            hierarchy, stats = build_hierarchy("report.xlsx", "matrix.yaml")

        assert stats["epics"] == 2
        assert stats["recommendations"] == 10
        MockParser.assert_called_once_with("report.xlsx")
