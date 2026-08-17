# 07 — Cost & Abuse Control

> You host the API keys, so every generation spends your money. This document exists to make sure that
> is bounded, priced correctly, and impossible to get badly wrong by accident.
>
> **Every number below was computed, not estimated.** The margin table in §4 was verified row by row at
> the worst-case tier; the arithmetic is reproduced so it can be re-checked when prices move.

---

## 1. Principles

1. **The free path must be genuinely useful.** Drawing and image→pattern cost zero and always will.
   That is goal G4 in `00-overview.md`, and it is also the best abuse defence there is — the feature
   people would otherwise script is the one that costs nothing to serve.
2. **Never surprise anyone with a charge.** Credit cost appears on the button before the click.
3. **The ceiling is the budget.** Credits control *fairness between users*. The daily spend ceiling
   controls *your exposure*. Do not confuse the two — credits alone cannot protect you from a bug.
4. **Charge actual cost, not estimated.** The provider returns `balance_cost`; record it.
5. **Failures are refunded.** Always, automatically, and visibly.

## 2. What each action costs us

| Action | Engine | Provider | Unit cost | Total |
|---|---|---|---|---|
| Image → pattern | C | — (browser) | — | **$0.0000** |
| Router LLM call | — | small LLM | ~$0.0005 | $0.0005 |
| Text → pattern, geometric | A | LLM only | $0.0005 | **$0.0005** |
| Text → pattern, art ×1 | B | `rd_fast__1_bit` | $0.030 | **$0.0305** |
| Text → pattern, art ×4 | B | `rd_fast__1_bit` ×4 | $0.030 | **$0.1205** |
| AI region edit | D | `rd_pro__edit` | $0.180 | **$0.1800** |

The spread is the whole story: the **geometric engine is 240× cheaper than the art engine** for four
variants, and it handles the most common request (`03-ai-integration.md` §1). Routing well is not a
nicety here, it is the cost model.

Image→pattern being free is not a subsidy — it genuinely costs nothing, because it runs in the user's
browser (`04-image-to-pattern.md` §2).

## 3. Credit pricing

**1 credit ≈ $0.05 at retail**, less in bulk. Packs:

| Pack | Credits | Stripe fee (2.9% + $0.30) | Net to you | Net $/credit |
|---|---:|---:|---:|---:|
| $10 | 220 | $0.590 | $9.410 | $0.0428 |
| $25 | 600 | $1.025 | $23.975 | $0.0400 |
| $50 | 1,300 | $1.750 | $48.250 | **$0.0371** |

No $5 pack. At $5 the fixed $0.30 fee is 8.9% of the transaction — the drag is bad for you and the pack
is too small to be worth a checkout for the user.

Charges per action:

| Action | Credits |
|---|---:|
| Image → pattern | **0** |
| Text → pattern, geometric (4 variants) | **1** |
| Text → pattern, art, 1 variant | **1** |
| Text → pattern, art, 4 variants | **4** |
| AI region edit | **6** |

The geometric engine gives four variants for one credit because they cost essentially nothing to
produce and because steering users toward it is in everyone's interest — it is cheaper for you, faster
for them, and produces better output on the prompts it handles.

## 4. Margin verification

Checked at **$0.0371/credit**, the worst case (largest pack, after Stripe fees). Every other tier is
strictly better.

| Action | Credits | Net revenue | Provider cost | Margin | Margin % | |
|---|---:|---:|---:|---:|---:|---|
| Image → pattern | 0 | $0.0000 | $0.0000 | $0.0000 | — | ✅ free by design |
| Text → geometric | 1 | $0.0371 | $0.0005 | +$0.0366 | 98.7% | ✅ |
| Text → art ×1 | 1 | $0.0371 | $0.0305 | +$0.0066 | 17.8% | ✅ |
| Text → art ×4 | 4 | $0.1485 | $0.1205 | +$0.0280 | 18.8% | ✅ |
| AI region edit | 6 | $0.2227 | $0.1800 | +$0.0427 | 19.2% | ✅ |

**All rows positive.** The paid rows sit at 18–19% gross margin, which is thin but real, and the
geometric engine's 98.7% is what makes the blended number healthy — another reason routing accuracy is
a financial metric, not just a quality one.

Re-run this whenever provider prices change:

```python
worst = 0.0371                       # net $/credit at the $50 pack
LLM   = 0.0005
rows = [("geometric", 1, LLM), ("art x1", 1, 0.03+LLM),
        ("art x4", 4, 4*0.03+LLM), ("edit", 6, 0.18)]
for name, credits, cost in rows:
    rev = credits * worst
    assert rev > cost, f"{name} is underwater: {rev:.4f} < {cost:.4f}"
```

Put that assertion in the test suite, reading from the same config the app uses. A price change that
makes a row unprofitable should fail CI, not be discovered in a Stripe report.

## 5. `SpendGuard` — the hard ceiling

The one control that makes a runaway impossible. Credits are per-user fairness; this is your bill.

```php
final class SpendGuard
{
    // Called BEFORE dispatching any paid job.
    public function check(int $estimatedCents): void
    {
        $spent = (int) Redis::get($this->key()) ?: 0;
        if ($spent + $estimatedCents > config('ai.daily_ceiling_cents')) {
            throw new DailyCeilingReached();
        }
    }

    // Called AFTER the provider responds, with the real cost.
    public function record(int $actualCents): void
    {
        Redis::incrby($this->key(), $actualCents);
        Redis::expire($this->key(), 172800);          // 48h, self-cleaning
    }

    private function key(): string
    {
        return 'ai:spend:' . now()->utc()->format('Y-m-d');
    }
}
```

Properties that matter:

- **Checked before dispatch**, so a rejected request never reaches the provider.
- **Records actual cost**, from the provider's `balance_cost`, not the estimate.
- **Keyed by UTC date**, self-expiring. No cleanup job, no table.
- **Fails closed.** If Redis is unreachable, generation is disabled. An outage that silently removed the
  spending ceiling would be the worst possible failure mode.

Recommended settings:

| Setting | Launch value |
|---|---|
| `AI_DAILY_CEILING_CENTS` | `1000` ($10/day → max ~$300/month) |
| Soft-warn threshold | 70% — alert to Slack/email |
| Behaviour at ceiling | Paid engines disabled; **free engines keep working** |

That last row is important. Hitting the ceiling must not take the whole product down — drawing, image
conversion, previews, and export all keep working, because none of them cost anything. The user sees an
honest message: *"AI generation is paused until 00:00 UTC. Everything else still works."*

## 6. Free-tier exposure

**6 free credits per user per day**, granted lazily (`06-data-model.md` §5.4).

Worst-case exposure if every daily active user spends their full allowance on the most expensive
per-credit action:

| Daily active free users | Max/day | Max/month |
|---:|---:|---:|
| 50 | $9.15 | $274.50 |
| 100 | $18.30 | $549.00 |
| 250 | $45.75 | $1,372.50 |
| 500 | $91.50 | $2,745.00 |

Those numbers are why the ceiling exists. At 250 DAU the free tier alone could theoretically cost more
than most side projects earn — but the $10/day ceiling caps actual exposure at **$300/month regardless
of user count**. The ceiling binds, the free tier does not.

The realistic figure is far lower: most users will use the free geometric engine (1 credit, $0.0005) and
image conversion (free), not four-variant art generation. But plan against the worst case, because the
worst case is what a bad day looks like.

**Tune the free tier against observed behaviour after launch**, not before. Start at 6, watch the
committed-generation rate (`06` §7, `was_committed`), and move it.

## 7. Rate limits

Credits handle economics; rate limits handle burst abuse and runaway client loops.

| Scope | Limit |
|---|---|
| AI generation, per user | 5/minute, 20/hour |
| AI generation, per IP (all users behind it) | 40/hour |
| Pattern save | 60/hour |
| Submit for review | 5/day |
| Image upload (AI-assisted path only) | 20/hour |
| Anonymous requests | Laravel default throttle |

Laravel's `RateLimiter` with Redis. Limits return `429` with `Retry-After`, and the UI renders that as a
countdown rather than an error.

The per-IP limit exists because a single user hammering from a script is a client bug, while forty
requests an hour from one address across many accounts is a signal worth acting on.

## 8. Abuse vectors

| Vector | Mitigation |
|---|---|
| Free-tier farming via many accounts | OAuth-only signup (Discord/Google raise the cost of account creation); per-IP hourly limit; ceiling caps total damage |
| Scripted generation loops | Per-user rate limits; credits deplete; ceiling |
| Very large image uploads | 8 MB / 4096² cap, and the free path never uploads at all |
| Prompt injection into the router | DSL validation with clamped ranges (`03` §4.4) — a prompt can only produce a differently-shaped bitmap |
| Provider key extraction | Key lives only in `Domain/Ai/*`, never in a Livewire property (`02` §6.1) |
| Credit race / double-spend | `FOR UPDATE` + unique `idempotency_key` (`06` §5.2) |
| Double refund | Unique `refund:{generation_id}` key |
| Stripe webhook replay | Unique `purchase:{payment_intent}` key |
| Chargeback after spending credits | Ledger records everything; ban flag; small absolute amounts |

The prompt-injection row deserves a note. Because the LLM's only output path is a schema-validated,
range-clamped DSL, there is no prompt that causes anything other than a pattern. It cannot make the
system call the expensive engine, spend more credits, or reach the filesystem. That property is designed
in, and it should be tested with an explicit adversarial prompt set.

## 9. Stripe integration

Laravel Cashier, **one-time payments only** — no subscriptions.

```
User clicks Top up
  → Cashier checkout session (credits pack)
  → Stripe hosted checkout
  → webhook: checkout.session.completed
       └─ CreditEntry: +credits, reason=purchase,
          idempotency_key = "purchase:{payment_intent}"
```

- Grant credits on the **webhook**, never on the browser redirect. The redirect can be lost, replayed,
  or forged; the webhook is signed.
- The unique idempotency key makes webhook replay a no-op.
- Refund handling: on `charge.refunded`, insert a negative entry. Balance may go negative; that is
  correct and honest. Generation is blocked below zero, and the ledger shows exactly why.
- Purchased credits **never expire**. Free daily credits do not accumulate.

## 10. Monitoring

A one-page internal dashboard. Not optional — an unmonitored spend ceiling is a tripwire nobody hears.

| Metric | Source | Alert |
|---|---|---|
| Spend today vs ceiling | Redis | ≥70% |
| Spend, 7-day trend | `generations.cost_cents` | — |
| Cost per **committed** result | `generations` ⋈ `generation_results.was_committed` | rising |
| Commit rate by engine | `generation_results` | <40% |
| Routing accuracy | `router_engine_chosen` vs eval set (`03` §8) | <90% |
| Generation failure rate | `generations.status` | >5% |
| Refunds issued today | `credit_entries` where `reason='refund'` | spike |
| Margin realised | `credits_charged × $/credit − cost_cents` | negative |

**Cost per committed result** is the metric to actually watch. Total spend tells you what you paid;
cost per *kept* pattern tells you whether it was worth it. If the art engine costs $0.12 per generation
and only one in ten results is committed, the real cost is $1.20 per useful pattern — and that is a
product problem, not a billing one.

## 11. Configuration

Everything tunable without a deploy:

```env
AI_DAILY_CEILING_CENTS=1000
AI_CEILING_WARN_PCT=70
AI_FREE_CREDITS_PER_DAY=6

CREDITS_COST_GEOMETRIC=1
CREDITS_COST_ART_SINGLE=1
CREDITS_COST_ART_BATCH=4
CREDITS_COST_EDIT=6

RATE_AI_PER_MINUTE=5
RATE_AI_PER_HOUR=20
RATE_AI_PER_IP_HOUR=40

RETRO_DIFFUSION_API_KEY=
AI_ROUTER_MODEL=
AI_ROUTER_API_KEY=
```

The margin assertion in §4 reads `CREDITS_COST_*` from this config, so changing a price without checking
the arithmetic fails the test suite.
