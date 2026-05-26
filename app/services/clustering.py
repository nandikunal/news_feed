"""
Story Clustering Service
========================
Groups stories that cover the same real-world event by combining:
  1. Title similarity  (SequenceMatcher ratio >= CLUSTER_TITLE_THRESHOLD)
  2. Publish-time proximity  (published within CLUSTER_TIME_WINDOW_HOURS of each other)

Output
------
cluster_stories(stories) -> List[StoryCard]
  Returns *only the representative story per cluster* (highest-ranked
  within the group). Each returned story has:
    - cluster_id      : shared key for all stories in the group
    - related_story_ids : IDs of the other stories in the same cluster

The full cluster map is also returned so callers can look up related
coverage without re-running the algorithm.
"""
import hashlib
import logging
from datetime import timedelta
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from app.core.config import settings
from app.models.schemas import StoryCard

logger = logging.getLogger(__name__)

# ── Tuneable constants (override via env / settings) ──────────────────────────
_TITLE_THRESHOLD: float = getattr(settings, "CLUSTER_TITLE_THRESHOLD", 0.72)
_TIME_WINDOW_HOURS: int = getattr(settings, "CLUSTER_TIME_WINDOW_HOURS", 2)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalise(title: str) -> str:
    """Lower-case, strip punctuation for a cleaner similarity signal."""
    import re
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalise(a), _normalise(b)).ratio()


def _within_window(t1, t2) -> bool:
    """True if both timestamps are non-None and within the time window."""
    if t1 is None or t2 is None:
        return True  # when pub time unknown, fall back to title-only matching
    delta = abs((t1 - t2).total_seconds())
    return delta <= _TIME_WINDOW_HOURS * 3600


def _cluster_key(story: StoryCard) -> str:
    """Deterministic cluster ID from normalised title."""
    return hashlib.md5(_normalise(story.title).encode()).hexdigest()[:12]


# ── Public API ────────────────────────────────────────────────────────────────

ClusterMap = Dict[str, List[str]]  # cluster_id -> [story_id, ...]


def build_clusters(stories: List[StoryCard]) -> Tuple[ClusterMap, Dict[str, str]]:
    """
    Run the O(n²) greedy clustering algorithm.

    Returns
    -------
    cluster_map   : {cluster_id: [story_ids in cluster]}
    story_to_cluster : {story_id: cluster_id}
    """
    # Work with a list of (index, story) so we can mutate assignment
    assignment: Dict[str, Optional[str]] = {s.id: None for s in stories}
    clusters: Dict[str, List[str]] = {}

    for i, story in enumerate(stories):
        if assignment[story.id] is not None:
            continue  # already clustered

        cid = _cluster_key(story)
        # Make cluster ID unique if two very different stories collide on hash
        if cid in clusters:
            cid = cid + story.id[:4]

        clusters[cid] = [story.id]
        assignment[story.id] = cid

        for other in stories[i + 1:]:
            if assignment[other.id] is not None:
                continue
            if (
                _similar(story.title, other.title) >= _TITLE_THRESHOLD
                and _within_window(story.published_at, other.published_at)
            ):
                clusters[cid].append(other.id)
                assignment[other.id] = cid

    story_to_cluster: Dict[str, str] = {
        sid: cid
        for cid, members in clusters.items()
        for sid in members
    }
    return clusters, story_to_cluster


def cluster_stories(
    stories: List[StoryCard],
    score_fn=None,
) -> Tuple[List[StoryCard], ClusterMap]:
    """
    Cluster *stories* and return (representatives, cluster_map).

    Parameters
    ----------
    stories   : full list coming out of the DB query
    score_fn  : optional callable(StoryCard) -> float used to pick the best
                story per cluster.  Defaults to preferring stories with an
                image and a longer summary.

    Returns
    -------
    representatives : one StoryCard per cluster, with `related_story_ids`
                      and `cluster_id` fields injected as extra attributes.
    cluster_map     : {cluster_id: [all story_ids in cluster]}
    """
    if not stories:
        return [], {}

    cluster_map, story_to_cluster = build_clusters(stories)
    id_to_story = {s.id: s for s in stories}

    if score_fn is None:
        def score_fn(s: StoryCard) -> float:  # type: ignore[misc]
            image_bonus = 1.0 if s.image_url else 0.0
            length_bonus = min(len(s.short_content) / 300, 1.0)
            return image_bonus + length_bonus

    representatives: List[StoryCard] = []
    for cid, member_ids in cluster_map.items():
        members = [id_to_story[mid] for mid in member_ids if mid in id_to_story]
        if not members:
            continue

        # Pick best story in cluster
        best = max(members, key=score_fn)

        # Inject cluster metadata as dynamic attributes so the ranker and
        # response layer can use them without changing the Pydantic schema here
        # (schema extension is done in schemas.py via optional fields).
        best.__dict__["cluster_id"] = cid
        best.__dict__["related_story_ids"] = [
            mid for mid in member_ids if mid != best.id
        ]
        representatives.append(best)

    logger.debug(
        "Clustering: %d stories -> %d clusters (%d singletons)",
        len(stories),
        len(cluster_map),
        sum(1 for v in cluster_map.values() if len(v) == 1),
    )
    return representatives, cluster_map
