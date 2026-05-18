# Flutter Integration Guide

This doc explains how the Flutter app should interact with the optimised v2 API.

---

## Onboarding Flow (first launch)

```
1. GET  /v1/sources              -> show source picker (2-5 selections)
2. POST /v1/sources/select       -> { "feed_ids": ["abc", "def", "ghi"] }
                                    triggers immediate fetch of selected feeds
3. GET  /v1/today?page=1&per_page=5  -> stories ready, show home screen
```

## Normal Launch

```dart
// Show skeleton cards immediately, then:
final res = await api.getTodayStories(page: 1, perPage: 5);
storeLocally(res.lastRefreshAt); // persist for update polling
```

## Pagination (infinite scroll)

```dart
// Trigger when user is 2 cards from end:
void onStoryChanged(int index) {
  if (index >= stories.length - 2) {
    fetchNextPage(); // page=2, per_page=10
  }
}
```

## Incremental Updates (app resume)

```dart
void onAppResumed() async {
  if (lastCachedAt == null) return;
  final updates = await api.getUpdates(since: lastCachedAt!);
  if (updates.totalNew > 0) {
    stories.insertAll(0, updates.stories);
    lastCachedAt = updates.checkedAt;
  }
}
```

## Skeleton Loading

```dart
// In your NewsCard widget, show shimmer while isLoading == true
Widget build(BuildContext context) {
  if (isLoading) return SkeletonCard(); // shimmer placeholder
  return NewsCard(story: story);
}
```

---

## API Response Fields (v2)

### `GET /v1/today`
```json
{
  "stories": [...],
  "total": 142,
  "page": 1,
  "per_page": 5,
  "cached_at": "2026-05-14T14:00:00",
  "last_refresh_at": "2026-05-14T13:58:00",
  "from_cache": true
}
```

### `GET /v1/today/updates?since=<ISO timestamp>`
```json
{
  "stories": [...],
  "total_new": 3,
  "since": "2026-05-14T13:00:00",
  "checked_at": "2026-05-14T14:10:00"
}
```

### `StoryCard` (v2 addition)
```json
{
  "id": "abc123",
  "title": "...",
  "source_names": ["BBC News", "Reuters"],
  "...": "..."
}
```
`source_names` lists all publishers that reported the same story (dedup merge).

---

## Recommended Polling Frequency

| Scenario | Frequency | Endpoint |
|---|---|---|
| App launch | Once | `GET /v1/today?page=1&per_page=5` |
| Scroll to end | On demand | `GET /v1/today?page=N` |
| App resume from BG | On resume | `GET /v1/today/updates?since=<ts>` |
| Pull-to-refresh | User action | `GET /v1/today?page=1` |

Do **not** poll `/v1/today` on a timer — use `/v1/today/updates` on app resume instead.
The backend cron handles freshness; the app just reacts when it comes to foreground.
