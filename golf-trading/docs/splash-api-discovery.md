# Splash PGA Contest API Discovery

**Date captured:** 2026-07-01  
**Scope:** read-only discovery of public Splash PGA contest/lobby data.  
**Guardrails:** no login, no account creation, no entry submission, no picks submission, no payment/KYC/geolocation flow.

## Summary

Splash exposes public PGA contest data through a Next.js web app and JSON APIs. The public web URLs are useful provenance links, but the stable ingestion surface is the API under:

- `https://api.splashsports.com/games-service/api`
- `https://api.splashsports.com/contests-service/api`

The tested public PGA flow is:

1. `GET /v1/leagues` to resolve the PGA league id.
2. `GET /contests/filters?leagueId=<pga_league_uuid>` to discover available PGA filter values.
3. `POST /contests/search` to page the public contest lobby.
4. `GET /contests/<contest_uuid>` to fetch contest detail.
5. `GET /contests/<contest_uuid>/slates/<slate_uuid>/player-pool?tierId=...` to fetch tier/player pool rows.

Observed PGA league id:

```text
166b6639-8972-41e7-a962-b415f3e93847
```

## Source URLs

Public lobby URL used:

```text
https://app.splashsports.com/contest-lobby?league=166b6639-8972-41e7-a962-b415f3e93847
```

Public contest detail URL used:

```text
https://app.splashsports.com/contest/226159cc-7ac7-43c3-a323-d54e77d2cb96/detail
```

The lobby URL returns a static Next.js app shell and lets the client call the API. The contest detail URL is server-side rendered and embeds the contest data in `__NEXT_DATA__`, but the direct `GET /contests/<contest_uuid>` response is cleaner for ingestion and fixture capture.

## Required Headers

The public JSON endpoints worked without cookies, bearer tokens, or location tokens using:

```http
Accept: application/json
Content-Type: application/json
X-App-Platform: web
X-App-Version: 1.251.0
User-Agent: Mozilla/5.0
```

Static app bundles define these default headers:

```js
{
  Accept: "application/json",
  "Content-Type": "application/json",
  "X-App-Platform": "web",
  "X-App-Version": "1.251.0"
}
```

When logged in, the app request interceptor adds:

```http
Authorization: Bearer <accessToken>
```

For protected wager/entry actions, the app also has a location-token interceptor that can add:

```http
location-token-v2: <geolocation_token>
```

Those protected flows were not exercised.

## Endpoint Matrix

| Surface | Method | Endpoint | Auth | Pagination | Notes |
|---|---:|---|---|---|---|
| League discovery | `GET` | `https://api.splashsports.com/games-service/api/v1/leagues` | No for public list | None | Returns league ids, aliases, sports, active flags. PGA is `alias=pga`, `sport=golf`. |
| PGA filters | `GET` | `https://api.splashsports.com/contests-service/api/contests/filters?leagueId=<pga_league_uuid>` | No | None | Returns sort options, payout formats, entry types, entry-fee range, and PGA contest types. Same path under `games-service/api` returned `404`. |
| Lobby search | `POST` | `https://api.splashsports.com/contests-service/api/contests/search` | No for public contests | `limit`, `offset` in request and response | Primary lobby API. Supports filtering by league, contest type, entry type, payout format, entry fee, and contest ids. |
| Contest detail | `GET` | `https://api.splashsports.com/contests-service/api/contests/<contest_uuid>` | No for public contests | None | Rich contest object: rules, payout schedule, settings, league, slates, games, tee times, status, entry/prize counts. |
| Entrants | `GET` | `https://api.splashsports.com/contests-service/api/contests/<contest_uuid>/entries?limit=<n>&offset=<n>` | No for public contests | `limit`, `offset`, `total` | Returns public entry/user display data. Store only aggregate or redacted data unless explicitly needed. |
| Player pool | `GET` | `https://api.splashsports.com/contests-service/api/contests/<contest_uuid>/slates/<slate_uuid>/player-pool?tierId=<n>&offset=<n>&limit=<n>` | No for public contests | `limit`, `offset`, `total` | For tier contests, `tierId` is required. Without `tierId` or `rosterCategoryId`, API returned `400`. |
| Entry creation | `POST` | `https://api.splashsports.com/contests-service/api/v2/entries` | Yes | N/A | Static-discovered protected wager path. Do not call in ingestion. Requires account/location checks in app code. |
| Picks submission | `POST` | `https://api.splashsports.com/contests-service/api/picks` | Yes | N/A | Static-discovered protected pick path. Do not call in ingestion. |

## Lobby Search Payload

Observed minimal PGA lobby payload:

```json
{
  "filter": {
    "leagueId": "166b6639-8972-41e7-a962-b415f3e93847"
  },
  "includeFull": false,
  "hideUnlisted": true,
  "limit": 5,
  "offset": 0
}
```

Observed optional lobby filters from app code:

```json
{
  "filter": {
    "contestIds": ["<contest_uuid>"],
    "contestTypes": ["player_tier", "player_one_and_done"],
    "entryTypes": ["multientry", "singleentry"],
    "leagueId": "<pga_league_uuid>",
    "payoutFormats": ["TOP_X", "MULTIPLIER"],
    "entryFee": {
      "min": 0,
      "max": 10000000
    }
  },
  "sort": "startDate",
  "dir": "desc",
  "includeFull": false,
  "hideUnlisted": true,
  "limit": 50,
  "offset": 0
}
```

Observed response pagination:

```json
{
  "data": ["<contest objects>"],
  "total": 40,
  "limit": 5,
  "offset": 0
}
```

## Contest Detail Fields

The tested PGA contest detail response included:

- Contest identity: `id`, `name`, `contest_type`, `contest_template_id`, `schedule_id`.
- Contest economics: `entry_fee`, `entry_fee_in_dollars`, `prize_pool`, `prize_pool_in_dollars`, `payout_schedule`.
- Contest lifecycle: `status`, `start_date`, `end_date`, `created_at`, `is_after_first_late_swap_deadline`, `is_entry_deadline_pending`.
- Rules and settings: `rules`, `short_rules`, `roster_requirements`, `tier_rules_settings`, `settings`.
- PGA league metadata: `league.alias=pga`, `league.sport=golf`, `league.settings.players.relevantAttributes`.
- Slate/game metadata: `slates[].id`, `slates[].games[].state.type=golf`, round tee-time arrays, purse, `isPicksheetAvailable`.

The observed PGA tier contest used:

```json
{
  "contest_type": "player_tier",
  "settings": {
    "scoreType": "golf_score",
    "slateLabel": "Tournament",
    "dropWorstCount": 1,
    "expectedPicksCount": 6
  },
  "tier_rules_settings": {
    "numberOfTiers": 6,
    "numberPerTier": 1,
    "metricName": "datagolf_rank"
  }
}
```

## Player Pool Pagination

For a tier contest, the app calls the player pool endpoint with `tierId`:

```text
GET /contests/<contest_uuid>/slates/<slate_uuid>/player-pool?tierId=1&offset=0&limit=5
```

Observed response pagination:

```json
{
  "data": ["<player rows>"],
  "total": 10,
  "limit": 5,
  "offset": 0,
  "canMakePicks": true,
  "metadata": {
    "hasAutoPicks": false,
    "canMakePicks": true
  }
}
```

Player rows contain Splash player ids, display names, tier-row ids, slate ids, public golf stats, and DataGolf-adjacent fields such as `datagolf_rank`, `world_rank`, and `scoring_avg`.

Calling player pool without `tierId` or `rosterCategoryId` returned:

```json
{
  "statusCode": 400,
  "message": "tierId must not be less than 1,tierId must be an integer number,rosterCategoryId must be a UUID",
  "error": "Bad Request"
}
```

## Auth And Safety Findings

Public read endpoints listed above did not require auth during discovery.

Static app code shows auth is cookie/token based:

- Browser cookies/local state hold `accessToken` and `refreshToken`.
- If `refreshToken` exists, the request interceptor sets `Authorization: Bearer <accessToken>`.
- A 401 response can trigger token refresh and retry.

Static app code also shows location validation for protected wager flows:

- `POST /v2/entries`
- `POST /buybacks`

Those protected calls can require `location-token-v2` and reason codes such as `PURCHASE_WAGER`. They are out of scope for UpAndDown ingestion and should be blocklisted in any Splash client.

## Fixture Index

Captured redacted fixtures live in `docs/fixtures/splash/`:

- `leagues.redacted.json`
- `pga-contest-filters.redacted.json`
- `pga-lobby-search.redacted.json`
- `contest-detail.redacted.json`
- `contest-entries.redacted.json`
- `player-pool-tier1.redacted.json`
- `player-pool-missing-tier-error.redacted.json`

Redaction policy:

- Redacted auth/cookie/location-token fields if present.
- Redacted entrant usernames, handles, entry names, user ids, and avatar URLs.
- Redacted commissioner handles/user ids/avatar URLs in fixtures.
- Redacted most UUIDs to stable placeholders except named placeholders for PGA league, sampled contest, and sampled slate.
- Retained public contest names, dates, entry/prize counts, public PGA player names, and golf stats needed to understand schema.

## Implementation Notes For A Future Read-Only Client

- Keep Splash as an optional contest-ingestion source, not an execution source.
- Build an allowlist client that supports only `GET /v1/leagues`, `GET /contests/filters`, `POST /contests/search`, `GET /contests/<id>`, and read-only player-pool/entries endpoints.
- Reject any method/path matching `/v2/entries`, `/picks`, `/buybacks`, `/payments`, `/kyc`, `/universal-auth`, `/oauth`, or `/wallet`.
- Persist raw responses with source URL, request body, response status, app version, and captured timestamp.
- Treat lobby `total`, `limit`, and `offset` as the pagination contract.
- Use `contest_type`, `settings.scoreType`, and `tier_rules_settings` to decide parser logic. PGA contests currently observed as `player_tier`; filters also advertise `player_one_and_done`.
