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

---

## Auth (JWT) and Push Integration

The backend now supports user accounts and JWT auth alongside the existing X-API-Key model. The Flutter app should:

1. Register / Login
   - POST /v1/auth/register  -> { "email": "...", "password": "..." }
   - POST /v1/auth/login     -> { "email": "...", "password": "..." }
     - Response: { "access_token": "<jwt>", "token_type": "bearer" }
   - Store the access_token securely on device (Keychain/Keystore).

2. Use both headers where appropriate
   - Continue sending X-API-Key (read key) for read-only endpoints if used by pre-login flows.
   - For user-scoped actions (read/like/bookmark, push token register), send Authorization: Bearer <access_token>.
   - When Authorization (Bearer) is present, endpoints such as GET /v1/stories/{id} return per-user state (read/liked/bookmarked). When absent, global/cache-level flags are returned.

3. Push registration flow
   - After login, obtain device push token (FCM/APNs) on the device.
   - POST /v1/push/register with Bearer token and body { "token": "<device-token>", "platform": "android" }
   - To remove: POST /v1/push/unregister { "token": "<device-token>" }
   - The server stores device tokens and dispatches notifications when new stories are ingested.

4. Practical notes for Flutter
   - Call /v1/auth/login once during onboarding or when user signs up.
   - After receiving JWT, immediately call /v1/push/register to opt-in for notifications.
   - Use the access token for user-specific actions (mark read, like, bookmark). Example:

```dart
final token = await auth.login(email, password);
final headers = { 'Authorization': 'Bearer $token' };
await api.post('/v1/push/register', body: {'token': deviceToken}, headers: headers);
await api.post('/v1/stories/$id/read', headers: headers);
```

5. Server configuration
   - Set FCM server key in environment (FCM_SERVER_KEY) to enable real push sending.
   - JWT_SECRET_KEY must be set in production and kept secret.

6. API docs
   - FastAPI OpenAPI docs available at /docs when running the server.

