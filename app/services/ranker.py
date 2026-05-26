"""
Smart Feed Ranker
=================
Applies a weighted scoring model to a list of StoryCards and returns
them in ranked order, with a publisher diversity cap applied after
ranking.

All weights and caps are read from ``app.core.config.settings`` so
they can be controlled via environment variables without a code change:

  RANK_W_FRESHNESS       float  default 0.35   freshness score weight
  RANK_W_QUALITY         float  default 0.25   source quality weight
  RANK_W_IMAGE           float  default 0.15   image completeness bonus
  RANK_W_DIVERSITY       float  default 0.15   back-to-back source penalty
  RANK_W_REGIONAL        float  default 0.10   regional topic boost
  RANK_MAX_SOURCE_FRAC   float  default 0.20   max fraction per source
  RANK_FRESHNESS_DECAY_H int    default 12     half-life for freshness decay

Public API
----------
rank_stories(stories, scores, limit, location_topics) -> List[StoryCard]
"""
import logging
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from app.core.config import settings
from app.models.schemas import StoryCard

logger = logging.getLogger(__name__)

# ── Weight constants (ENV-configurable) ─────────────────────────────────────
_W_FRESHNESS   = getattr(settings, "RANK_W_FRESHNESS",     0.35)
_W_QUALITY     = getattr(settings, "RANK_W_QUALITY",       0.25)
_W_IMAGE       = getattr(settings, "RANK_W_IMAGE",         0.15)
_W_DIVERSITY   = getattr(settings, "RANK_W_DIVERSITY",     0.15)
_W_REGIONAL    = getattr(settings, "RANK_W_REGIONAL",      0.10)
_MAX_SRC_FRAC  = getattr(settings, "RANK_MAX_SOURCE_FRAC", 0.20)
_DECAY_HOURS   = getattr(settings, "RANK_FRESHNESS_DECAY_H", 12)

# Topics that signal strong regional relevance (Berlin / Germany context)
_REGIONAL_TOPICS: Set[str] = {"berlin", "germany", "local", "transport", "city"}


# ── Scoring helpers ──────────────────────────────────────────────────

def _freshness(published_at: Optional[datetime]) -> float:
    """
    Exponential decay based on story age.
    score = exp(-lambda * age_hours)  where lambda = ln(2) / half_life
    Returns 1.0 for brand-new stories, ~0.5 at half-life, ~0.0 at 24h.
    """
    if published_at is None:
        return 0.5  # unknown age → neutral
    now = datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_hours = max((now - published_at).total_seconds() / 3600, 0)
    lam = math.log(2) / max(_DECAY_HOURS, 1)
    return math.exp(-lam * age_hours)


def _image_score(story: StoryCard) -> float:
    return 1.0 if story.image_url else 0.0


def _regional_score(story: StoryCard, location_topics: Set[str]) -> float:
    """
    Boost stories whose topic is in the user's location context OR in the
    global regional set.
    """
    topic = story.topic.value.lower()
    if topic in location_topics or topic in _REGIONAL_TOPICS:
        return 1.0
    return 0.0


def _compute_scores(
    stories: List[StoryCard],
    quality_scores: Dict[str, float],
    location_topics: Set[str],
) -> List[tuple]:
    """Return list of (raw_score, story) sorted descending."""
    scored = []
    for story in stories:
        f = _freshness(story.published_at)
        q = quality_scores.get(story.source, 0.5)
        im = _image_score(story)
        reg = _regional_score(story, location_topics)
        # Diversity bonus is computed after sorting (pass-2), so set to 1.0
        # here and then apply the penalty in the diversity-cap pass.
        raw = (
            _W_FRESHNESS * f
            + _W_QUALITY  * q
            + _W_IMAGE    * im
            + _W_DIVERSITY * 1.0   # placeholder; penalised post-sort
            + _W_REGIONAL * reg
        ) / (_W_FRESHNESS + _W_QUALITY + _W_IMAGE + _W_DIVERSITY + _W_REGIONAL)
        scored.append((raw, story))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def _apply_diversity_penalty(
    scored: List[tuple],
) -> List[tuple]:
    """
    Penalise stories that appear back-to-back from the same source.
    When two adjacent stories share the same source, the second one has
    its diversity component zeroed out.
    """
    if not scored:
        return scored

    result = [scored[0]]
    prev_source = scored[0][1].source

    for raw, story in scored[1:]:
        if story.source == prev_source:
            # Subtract the full diversity weight (normalised)
            total_w = _W_FRESHNESS + _W_QUALITY + _W_IMAGE + _W_DIVERSITY + _W_REGIONAL
            penalty = _W_DIVERSITY / total_w
            raw = max(0.0, raw - penalty)
        result.append((raw, story))
        prev_source = story.source

    # Re-sort after penalty application
    result.sort(key=lambda x: x[0], reverse=True)
    return result


# ── Publisher diversity cap (Task 5) ────────────────────────────────────

def _apply_diversity_cap(
    stories: List[StoryCard],
    limit: int,
    max_fraction: float = _MAX_SRC_FRAC,
) -> List[StoryCard]:
    """
    After ranking, ensure no single source exceeds `max_fraction` of
    the final deck.

    Algorithm (two-pass):
      Pass 1 — Walk the ranked list and accept stories up to the per-source
                budget.  Overflow stories are deferred.
      Pass 2 — Back-fill empty slots with deferred stories (still ranked
                order) until `limit` is reached.

    This preserves the best stories from each source and only trims
    excess from over-represented sources.
    """
    max_per_source = max(1, int(math.ceil(limit * max_fraction)))
    source_count: Dict[str, int] = {}
    accepted: List[StoryCard] = []
    deferred: List[StoryCard] = []

    for story in stories:
        count = source_count.get(story.source, 0)
        if count < max_per_source:
            accepted.append(story)
            source_count[story.source] = count + 1
        else:
            deferred.append(story)

        if len(accepted) >= limit:
            break

    # Back-fill from deferred if we're short
    for story in deferred:
        if len(accepted) >= limit:
            break
        accepted.append(story)

    return accepted[:limit]


# ── Public API ────────────────────────────────────────────────────────────────

def rank_stories(
    stories: List[StoryCard],
    quality_scores: Optional[Dict[str, float]] = None,
    limit: Optional[int] = None,
    location_topics: Optional[Set[str]] = None,
) -> List[StoryCard]:
    """
    Rank stories using weighted multi-signal scoring and apply
    publisher diversity cap.

    Parameters
    ----------
    stories         : Unordered list of StoryCards (typically after clustering)
    quality_scores  : source_name -> float mapping from quality_scorer
    limit           : Maximum number of stories to return
    location_topics : Set of topic strings signalling user's regional context

    Returns
    -------
    Ranked, diversity-capped list of StoryCards.
    """
    if not stories:
        return []

    if quality_scores is None:
        quality_scores = {}
    if location_topics is None:
        location_topics = set()

    effective_limit = limit or len(stories)

    # Pass 1: score everything
    scored = _compute_scores(stories, quality_scores, location_topics)

    # Pass 2: penalise back-to-back same-source runs
    scored = _apply_diversity_penalty(scored)

    # Extract ordered stories
    ranked = [story for _, story in scored]

    # Pass 3: publisher diversity hard cap (Task 5)
    capped = _apply_diversity_cap(ranked, effective_limit, _MAX_SRC_FRAC)

    logger.debug(
        "Ranker: %d -> %d stories after cap (limit=%d, src_frac=%.2f)",
        len(stories), len(capped), effective_limit, _MAX_SRC_FRAC,
    )
    return capped
