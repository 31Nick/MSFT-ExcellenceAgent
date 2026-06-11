"""Tests for stable_key properties on model classes."""

from __future__ import annotations

import pytest

from excellence_agent.models import (
    Epic,
    Feature,
    UserStory,
)


class TestEpicStableKey:
    def test_basic(self) -> None:
        epic = Epic(name="Networking")
        assert epic.stable_key == "epic:networking"

    def test_case_normalized(self) -> None:
        epic = Epic(name="Data")
        assert epic.stable_key == "epic:data"

    def test_spaces_preserved(self) -> None:
        epic = Epic(name="AI & ML")
        assert epic.stable_key == "epic:ai & ml"


class TestFeatureStableKey:
    def test_basic(self) -> None:
        epic = Epic(name="Networking")
        feat = Feature(name="VNets", resource_type="microsoft.network/virtualNetworks")
        epic.add_feature(feat)
        assert feat.stable_key == "feature:networking:microsoft.network/virtualnetworks"

    def test_raises_without_parent(self) -> None:
        feat = Feature(name="VNets", resource_type="microsoft.network/virtualNetworks")
        with pytest.raises(ValueError, match="parent Epic"):
            _ = feat.stable_key


class TestUserStoryStableKey:
    def test_basic(self) -> None:
        epic = Epic(name="Data")
        feat = Feature(name="Cosmos", resource_type="microsoft.documentdb/databaseaccounts")
        epic.add_feature(feat)
        story = UserStory(title="Databaseaccounts - Recommendations", impact="High")
        feat.add_user_story(story)
        assert story.stable_key == "story:data:microsoft.documentdb/databaseaccounts"

    def test_raises_without_parent(self) -> None:
        story = UserStory(title="Recs", impact="High")
        with pytest.raises(ValueError, match="parent Feature"):
            _ = story.stable_key
