"""Keyword-based Jaccard similarity for Azure recommendation title matching."""

from __future__ import annotations

import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

STOP_WORDS = {
    "the", "a", "an", "is", "are", "to", "for", "of", "and", "or", "in",
    "by", "your", "this", "that", "with", "from", "on", "it", "be", "as",
    "at", "not", "do", "has", "have", "was", "were", "will", "can",
    "should", "may", "might", "all", "its", "their", "our",
}

_NON_ALPHA = re.compile(r"[^a-z]+")


class SimilarityMatcher:
    """Detect whether two recommendation titles are semantically the same
    using keyword-based Jaccard similarity — no heavy NLP libraries needed."""

    def __init__(self, threshold: float = 0.3):
        """
        Args:
            threshold: Jaccard similarity threshold (0.0-1.0).
                       0.3 works well for Azure recommendation titles.
        """
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold must be between 0.0 and 1.0, got {threshold}")
        self.threshold = threshold

    def tokenise(self, text: str) -> set[str]:
        """Tokenise text: lowercase, split on non-alpha, remove stop words,
        remove short tokens (< 3 chars)."""
        lowered = text.lower()
        tokens = _NON_ALPHA.split(lowered)
        return {t for t in tokens if len(t) >= 3 and t not in STOP_WORDS}

    def jaccard_similarity(self, tokens_a: set[str], tokens_b: set[str]) -> float:
        """Compute Jaccard similarity: |intersection| / |union|."""
        if not tokens_a and not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)

    def are_similar(self, text_a: str, text_b: str) -> bool:
        """Check if two recommendation titles are semantically similar."""
        score = self.similarity_score(text_a, text_b)
        return score >= self.threshold

    def similarity_score(self, text_a: str, text_b: str) -> float:
        """Return the similarity score between two texts.

        Uses the maximum of Jaccard similarity and overlap coefficient
        so that length-asymmetric pairs (short APRL title vs long Advisor
        title) are scored fairly.
        """
        tokens_a = self.tokenise(text_a)
        tokens_b = self.tokenise(text_b)
        jaccard = self.jaccard_similarity(tokens_a, tokens_b)
        # Overlap coefficient: |intersection| / min(|A|, |B|)
        if tokens_a and tokens_b:
            overlap = len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))
        else:
            overlap = 0.0
        score = max(jaccard, overlap)
        logger.debug(
            "similarity %.3f (jaccard=%.3f overlap=%.3f)  tokens_a=%s  tokens_b=%s",
            score,
            jaccard,
            overlap,
            sorted(tokens_a),
            sorted(tokens_b),
        )
        return score

    def find_matches(
        self,
        source_titles: List[str],
        target_titles: List[str],
    ) -> List[Tuple[str, str, float]]:
        """Find all matching pairs between two lists of titles.

        Returns list of (source_title, target_title, score) tuples where
        score >= threshold.  For each source title, only the best match
        from *target_titles* is returned.
        """
        # Pre-tokenise targets for efficiency
        target_tokens = [(t, self.tokenise(t)) for t in target_titles]

        matches: List[Tuple[str, str, float]] = []
        for src in source_titles:
            src_tokens = self.tokenise(src)
            best_score = 0.0
            best_target = ""
            for tgt, tgt_tok in target_tokens:
                jaccard = self.jaccard_similarity(src_tokens, tgt_tok)
                if src_tokens and tgt_tok:
                    overlap = len(src_tokens & tgt_tok) / min(
                        len(src_tokens), len(tgt_tok)
                    )
                else:
                    overlap = 0.0
                score = max(jaccard, overlap)
                if score > best_score:
                    best_score = score
                    best_target = tgt
            if best_score >= self.threshold:
                matches.append((src, best_target, best_score))
                logger.info(
                    "Matched: '%s' ↔ '%s' (score=%.3f)",
                    src,
                    best_target,
                    best_score,
                )

        logger.info(
            "find_matches: %d/%d source titles matched (threshold=%.2f)",
            len(matches),
            len(source_titles),
            self.threshold,
        )
        return matches
