# 06 — Data Model

> PostgreSQL 16. Money is stored in **integer cents**, never floats. Credits are integers. Balances are
> **derived from an append-only ledger**, never stored as a mutable column — see §5 for why.

---

## 1. Entity overview

```
users ──┬── credit_entries        (append-only ledger; balance = SUM)
        ├── patterns ──┬── pattern_versions
        │              └── submissions
        ├── generations ── generation_results
        └── (Cashier: customers, payment methods, invoices)
```

## 2. `users`

Laravel's default table plus:

| Column | Type | Notes |
|---|---|---|
| `id` | bigint PK | |
| `name` | string | display name |
| `email` | string, unique, nullable | Discord may not expose one |
| `password` | string, nullable | **null for OAuth-only accounts** |
| `avatar_url` | string, nullable | |
| `free_credits_used_today` | int, default 0 | reset by scheduler |
| `free_credits_reset_at` | timestamp | |
| `is_banned` | bool, default false | |
| `stripe_id`, `pm_type`, `pm_last_four`, `trial_ends_at` | — | added by Cashier |

`password` must be nullable and the login flow must not assume it exists. An OAuth-only user with a
non-nullable password column is a bug that surfaces at the worst time.

### `oauth_identities`

Separate table rather than columns on `users`, so a user can link both Discord and Google.

| Column | Type |
|---|---|
| `id` | bigint PK |
| `user_id` | FK → users, cascade delete |
| `provider` | string — `discord` \| `google` |
| `provider_user_id` | string |
| `created_at` | timestamp |

Unique index on `(provider, provider_user_id)`.

## 3. `patterns`

| Column | Type | Notes |
|---|---|---|
| `id` | bigint PK | |
| `user_id` | FK → users, nullable | null = anonymous, kept for share links |
| `name` | string(32) | `^[a-z0-9_]+$` — matches OpenFront (`01` §2) |
| `pattern_data` | string(1403) | **validated and re-encoded server-side, always** |
| `width` | smallint | 2–129, denormalised from `pattern_data` |
| `height` | smallint | 2–65, denormalised |
| `scale` | smallint | 0–7, denormalised |
| `primary_color` | char(7) | `#rrggbb` |
| `secondary_color` | char(7) | |
| `ink_coverage` | real | fraction of secondary bits; used for quality filtering |
| `seam_score_h` | real | nullable |
| `seam_score_v` | real | nullable |
| `visibility` | enum | `private` \| `unlisted` \| `public` |
| `origin` | enum | `manual` \| `ai_parametric` \| `ai_diffusion` \| `image` \| `imported` |
| `generation_id` | FK → generations, nullable | provenance when AI-derived |
| `forked_from_id` | FK → patterns, nullable | |
| `created_at`, `updated_at` | timestamps | |
| `deleted_at` | timestamp, nullable | soft delete |

Indexes: `(user_id, updated_at desc)`, `(visibility, created_at desc)` partial on `visibility='public'`,
unique `(user_id, name)` where `deleted_at is null`.

**`width`/`height`/`scale` are denormalised on purpose.** They live in `pattern_data`, but decoding
1,000 rows to render a gallery page is silly. They are written only by the model's setter, which
decodes `pattern_data` — never set independently, so they cannot drift.

**`origin`** exists so we can answer "is AI output actually being kept?" — the most important product
question there is. A generation the user immediately deletes is a failure that no other metric catches.

## 4. `pattern_versions`

Snapshot history, distinct from the in-editor undo stack (`02` §3.3), which is client-side and ephemeral.

| Column | Type |
|---|---|
| `id` | bigint PK |
| `pattern_id` | FK → patterns, cascade delete |
| `pattern_data` | string(1403) |
| `label` | string, nullable — e.g. "before AI edit" |
| `created_at` | timestamp |

Written on explicit save, before an AI edit commits, and before a destructive resize. Capped at 50 per
pattern; the oldest are pruned. At ~1.4 KB each this is negligible storage and repeatedly valuable.

## 5. Credits — the append-only ledger

**`credit_entries`** is the single source of truth. There is no `balance` column anywhere.

| Column | Type | Notes |
|---|---|---|
| `id` | bigint PK | |
| `user_id` | FK → users | |
| `delta` | int | **signed**: +grant, −spend, +refund |
| `reason` | enum | `daily_free` \| `purchase` \| `spend` \| `refund` \| `admin_adjust` \| `promo` |
| `generation_id` | FK → generations, nullable | set for `spend` and `refund` |
| `stripe_payment_intent` | string, nullable | set for `purchase` |
| `idempotency_key` | string, nullable, unique | see below |
| `note` | string, nullable | |
| `created_at` | timestamp | |

```sql
balance = SELECT COALESCE(SUM(delta), 0) FROM credit_entries WHERE user_id = ?
```

### 5.1 Why a ledger and not a counter

A mutable `users.credits` column has three failure modes that a ledger does not:

1. **Races.** Two concurrent generations both read 5, both write 4, one generation is free. A ledger
   inserts two rows and the sum is correct without a lock.
2. **No audit trail.** When a user says "I was charged twice", a counter cannot answer. A ledger can.
3. **Refunds corrupt silently.** A double-refund bug on a counter is invisible; on a ledger it is two
   visible rows with the same `generation_id`, which a constraint can forbid.

The concurrency guarantee is the important one. It is also the thing to test explicitly
(`02-architecture.md` §7).

### 5.2 Spending safely

Reserve **before** dispatching the job, inside one transaction:

```php
DB::transaction(function () use ($user, $cost, $generation) {
    $balance = CreditLedger::balanceForUpdate($user);   // SELECT … FOR UPDATE on the user row
    if ($balance < $cost) {
        throw new InsufficientCredits();
    }
    CreditEntry::create([
        'user_id'         => $user->id,
        'delta'           => -$cost,
        'reason'          => 'spend',
        'generation_id'   => $generation->id,
        'idempotency_key' => "spend:{$generation->id}",
    ]);
});
```

`FOR UPDATE` on the **user row** serialises concurrent spends for that user. Contention is per-user and
these transactions are microseconds, so this costs nothing in practice.

`idempotency_key` is unique, so a retried job cannot double-charge and a duplicated webhook cannot
double-grant. Every write goes through a key: `spend:{gen}`, `refund:{gen}`, `daily:{user}:{date}`,
`purchase:{payment_intent}`.

### 5.3 Refunds

On job failure, insert `+cost` with `reason='refund'` and key `refund:{generation_id}`. The unique index
makes a double refund impossible rather than merely unlikely.

### 5.4 Free daily credits

Granted lazily, not by a nightly job over every user: on first AI action of the day, if no
`daily_free` entry exists with key `daily:{user_id}:{YYYY-MM-DD}`, insert one. Users who don't visit
generate no rows.

Unused free credits **do not accumulate** — the daily grant is capped at the daily allowance, so a user
returning after a month gets 10, not 300. Purchased credits never expire.

## 6. `generations`

One row per AI request, created **before** the provider is called.

| Column | Type | Notes |
|---|---|---|
| `id` | bigint PK | |
| `user_id` | FK → users | |
| `engine` | enum | `parametric` \| `diffusion` \| `edit` |
| `status` | enum | `pending` \| `running` \| `completed` \| `failed` \| `cancelled` |
| `prompt` | text | as typed |
| `refined_prompt` | text, nullable | what the router produced (`03` §3) |
| `dsl_program` | jsonb, nullable | the validated program, for parametric |
| `router_engine_chosen` | string, nullable | for measuring routing accuracy (`03` §8) |
| `provider_params` | jsonb, nullable | exact request sent, minus the key |
| `credits_charged` | int | |
| `cost_cents` | int, nullable | **actual**, from the provider's `balance_cost` |
| `llm_cost_cents` | int, nullable | router call |
| `error_code` | string, nullable | |
| `error_message` | text, nullable | |
| `duration_ms` | int, nullable | |
| `created_at`, `completed_at` | timestamps | |

Indexes: `(user_id, created_at desc)`, `(status)` partial on `pending`/`running` for the timeout sweeper,
`(created_at)` for daily spend rollups.

`dsl_program` as `jsonb` means we can query which primitives people actually use — directly useful for
deciding what to add to the DSL.

Storing both `credits_charged` and `cost_cents` is what makes the margin in
`07-cost-and-abuse.md` §4 measurable rather than theoretical.

## 7. `generation_results`

| Column | Type |
|---|---|
| `id` | bigint PK |
| `generation_id` | FK → generations, cascade delete |
| `index` | smallint — variant number |
| `image_path` | string, nullable — diffusion output |
| `pattern_data` | string(1403), nullable — parametric output |
| `seam_score_h`, `seam_score_v` | real, nullable |
| `was_committed` | bool, default false |
| `created_at` | timestamp |

Parametric results are `pattern_data` directly; diffusion results are images awaiting reduction
(`03` §5.3). Exactly one of the two is non-null.

**`was_committed`** is the quality signal that matters. Generations are cheap to count; generations the
user actually keeps are the real measure of whether the AI works.

Images are cache. A retention job deletes `image_path` files older than 30 days for uncommitted results;
the row stays for analytics.

## 8. `submissions`

For the OpenFront submit flow (`02` §9 open item 1).

| Column | Type |
|---|---|
| `id` | bigint PK |
| `pattern_id` | FK → patterns |
| `user_id` | FK → users |
| `status` | enum: `draft` \| `submitted` \| `accepted` \| `rejected` \| `withdrawn` |
| `proposed_name` | string(32) |
| `notes` | text, nullable |
| `reviewer_notes` | text, nullable |
| `external_ref` | string, nullable — issue/PR URL once known |
| `submitted_at`, `resolved_at` | timestamps, nullable |

Until the destination is confirmed, `submitted` means "the user generated a `cosmetics.json` entry and
marked it as sent". The table shape does not change once a real destination exists — only
`external_ref` starts getting populated.

## 9. Anonymous users

A logged-out visitor can draw, convert images, preview, and export — no rows written. Their state lives
in the URL hash (`05` §9) and `localStorage`.

Nothing is persisted server-side until they either sign in or use an AI feature. On sign-in, any
`localStorage` working pattern is offered for import.

## 10. Retention & deletion

| Data | Retention |
|---|---|
| Patterns | Until deleted; soft-deleted rows purged after 30 days |
| Pattern versions | 50 most recent per pattern |
| Generated images (uncommitted) | 30 days |
| Generated images (committed) | Until the pattern is deleted |
| `generations` rows | 2 years — needed for cost analysis |
| `credit_entries` | **Never deleted.** Financial record. |

**Account deletion** anonymises rather than cascades: `user_id` set null on patterns the user marked
public, personal fields cleared, `credit_entries` retained with the user reference intact for accounting
integrity. This must be stated in the privacy policy — "we keep your transaction records" is a normal
and defensible position, but only if disclosed.

## 11. Migration order

1. `users` (Laravel default) → add columns
2. `oauth_identities`
3. `credit_entries`
4. `generations`
5. `generation_results`
6. `patterns` (FK to generations)
7. `pattern_versions`
8. `submissions`
9. Cashier tables

`patterns` comes after `generations` because of `generation_id`. The reverse dependency
(`generations` → patterns) does not exist, deliberately: a generation is not owned by a pattern, a
pattern optionally references its origin.
