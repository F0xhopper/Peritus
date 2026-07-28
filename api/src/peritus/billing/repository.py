"""Persistence for accounts, the credit ledger, and build usage.

Balance is always ``SUM(delta)`` over the ledger — there is no cached balance
column, so it cannot drift from its own history. Every write that depends on a
balance takes ``SELECT ... FOR UPDATE`` on the account row first, which
serialises concurrent enqueues for one user and makes double-spend impossible
without a distributed lock.
"""

import json
from decimal import Decimal

import asyncpg

from peritus.billing.domain import CreditSource, LedgerEntry, LedgerEntryType
from peritus.billing.metering import UsageBucket, UsageKey


class BillingRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── accounts ────────────────────────────────────────────────────────────

    async def ensure_account(
        self,
        owner_id: str,
        email: str | None = None,
        plan: str = "free",
        signup_credits: int = 0,
    ) -> dict:
        """Get-or-create the account, granting signup credits exactly once.

        The grant rides in the same transaction as the insert and is skipped
        entirely when the account already existed, so a user cannot re-trigger
        it by signing in again.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO accounts (owner_id, plan, email)
                VALUES ($1::uuid, $2, $3)
                ON CONFLICT (owner_id) DO NOTHING
                RETURNING *
                """,
                owner_id, plan, email,
            )
            created = row is not None
            if created and signup_credits > 0:
                await conn.execute(
                    """
                    INSERT INTO credit_ledger
                        (owner_id, entry_type, delta, reason, source, actor)
                    VALUES ($1::uuid, 'grant', $2, $3, $4, 'system')
                    """,
                    owner_id,
                    signup_credits,
                    f"Welcome grant ({plan} plan)",
                    CreditSource.SIGNUP.value,
                )
            if row is None:
                row = await conn.fetchrow(
                    "SELECT * FROM accounts WHERE owner_id = $1::uuid", owner_id
                )
                # Backfill an email we learn later (the JWT carries it, the
                # first touch might not have).
                if email and not row["email"]:
                    row = await conn.fetchrow(
                        """
                        UPDATE accounts SET email = $2, updated_at = NOW()
                        WHERE owner_id = $1::uuid RETURNING *
                        """,
                        owner_id, email,
                    )
        return dict(row)

    async def get_account(self, owner_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM accounts WHERE owner_id = $1::uuid", owner_id
            )
        return dict(row) if row else None

    async def find_account_by_email(self, email: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM accounts WHERE lower(email) = lower($1)", email
            )
        return dict(row) if row else None

    async def set_plan(self, owner_id: str, plan: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE accounts SET plan = $2, updated_at = NOW() WHERE owner_id = $1::uuid",
                owner_id, plan,
            )

    async def set_spend_cap_override(self, owner_id: str, cap_usd: float | None) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE accounts SET spend_cap_override_usd = $2, updated_at = NOW()
                WHERE owner_id = $1::uuid
                """,
                owner_id, Decimal(str(cap_usd)) if cap_usd is not None else None,
            )

    async def list_accounts(self, limit: int = 100) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT a.*,
                       COALESCE((SELECT SUM(delta) FROM credit_ledger l
                                 WHERE l.owner_id = a.owner_id), 0)::int AS balance
                FROM accounts a
                ORDER BY a.created_at DESC
                LIMIT $1
                """,
                limit,
            )
        return [dict(r) for r in rows]

    # ── credits ─────────────────────────────────────────────────────────────

    async def balance(self, owner_id: str) -> int:
        async with self._pool.acquire() as conn:
            value = await conn.fetchval(
                "SELECT COALESCE(SUM(delta), 0)::int FROM credit_ledger WHERE owner_id = $1::uuid",
                owner_id,
            )
        return int(value or 0)

    async def credit_totals(self, owner_id: str) -> dict[str, int]:
        """Balance plus the components a client needs to explain it."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COALESCE(SUM(delta), 0)::int AS balance,
                    COALESCE(SUM(delta) FILTER (WHERE delta > 0), 0)::int AS granted,
                    COALESCE(-SUM(delta) FILTER (WHERE delta < 0), 0)::int AS consumed,
                    COALESCE(-SUM(l.delta) FILTER (
                        WHERE l.entry_type = 'hold'
                          AND j.status IN ('queued', 'running')
                    ), 0)::int AS held
                FROM credit_ledger l
                LEFT JOIN build_jobs j ON j.id = l.job_id
                WHERE l.owner_id = $1::uuid
                """,
                owner_id,
            )
        return {
            "balance": int(row["balance"]),
            "granted": int(row["granted"]),
            "consumed": int(row["consumed"]),
            "held": int(row["held"]),
        }

    async def grant(
        self,
        owner_id: str,
        amount: int,
        reason: str | None = None,
        source: str = CreditSource.MANUAL.value,
        actor: str | None = None,
        external_ref: str | None = None,
        entry_type: str = LedgerEntryType.GRANT.value,
    ) -> int:
        """Add credits. Returns the new balance."""
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                INSERT INTO credit_ledger
                    (owner_id, entry_type, delta, reason, source, actor, external_ref)
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7)
                """,
                owner_id, entry_type, amount, reason, source, actor, external_ref,
            )
            value = await conn.fetchval(
                "SELECT COALESCE(SUM(delta), 0)::int FROM credit_ledger WHERE owner_id = $1::uuid",
                owner_id,
            )
        return int(value or 0)

    async def hold_for_job(
        self,
        owner_id: str,
        job_id: int,
        credits: int,
        tier: str,
        require_balance: bool = True,
    ) -> tuple[bool, int]:
        """Reserve credits for a build job.

        Returns ``(placed, balance_before)``. ``placed`` is False only when the
        balance is insufficient; a hold that already exists for this job counts
        as placed, which is what makes enqueue idempotent under double-submit
        (the unique index on ``(job_id) WHERE entry_type='hold'`` is the
        authority, not a prior read).

        The account row is locked for the whole check-then-write so two
        concurrent enqueues for the same user cannot both pass the balance test.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.fetchrow(
                "SELECT owner_id FROM accounts WHERE owner_id = $1::uuid FOR UPDATE",
                owner_id,
            )
            existing = await conn.fetchval(
                "SELECT 1 FROM credit_ledger WHERE job_id = $1 AND entry_type = 'hold'",
                job_id,
            )
            balance = int(
                await conn.fetchval(
                    """
                    SELECT COALESCE(SUM(delta), 0)::int FROM credit_ledger
                    WHERE owner_id = $1::uuid
                    """,
                    owner_id,
                )
                or 0
            )
            if existing:
                return True, balance
            if require_balance and balance < credits:
                return False, balance
            await conn.execute(
                """
                INSERT INTO credit_ledger
                    (owner_id, entry_type, delta, job_id, tier, reason, source, actor)
                VALUES ($1::uuid, 'hold', $2, $3, $4, $5, 'system', 'system')
                ON CONFLICT DO NOTHING
                """,
                owner_id, -credits, job_id, tier, f"Build ({tier})",
            )
        return True, balance

    async def refund_job(self, job_id: int, reason: str) -> int:
        """Return a job's hold. Idempotent — a second call is a no-op.

        Returns the number of credits refunded (0 if there was no hold, or one
        was already refunded).
        """
        async with self._pool.acquire() as conn, conn.transaction():
            hold = await conn.fetchrow(
                """
                SELECT owner_id, delta, tier FROM credit_ledger
                WHERE job_id = $1 AND entry_type = 'hold'
                """,
                job_id,
            )
            if hold is None:
                return 0
            already = await conn.fetchval(
                "SELECT 1 FROM credit_ledger WHERE job_id = $1 AND entry_type = 'refund'",
                job_id,
            )
            if already:
                return 0
            amount = -int(hold["delta"])
            if amount <= 0:
                return 0
            await conn.execute(
                """
                INSERT INTO credit_ledger
                    (owner_id, entry_type, delta, job_id, tier, reason, source, actor)
                VALUES ($1::uuid, 'refund', $2, $3, $4, $5, 'system', 'system')
                ON CONFLICT DO NOTHING
                """,
                hold["owner_id"], amount, job_id, hold["tier"], reason,
            )
        return amount

    async def record_job_cost(self, job_id: int, cost_usd: float) -> None:
        """Stamp realised spend onto the job's hold entry, for reporting."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE credit_ledger SET cost_usd = $2
                WHERE job_id = $1 AND entry_type = 'hold'
                """,
                job_id, Decimal(str(round(cost_usd, 6))),
            )

    async def list_ledger(self, owner_id: str, limit: int = 50) -> list[LedgerEntry]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM credit_ledger
                WHERE owner_id = $1::uuid
                ORDER BY id DESC
                LIMIT $2
                """,
                owner_id, limit,
            )
        return [_row_to_entry(r) for r in rows]

    # ── build usage ─────────────────────────────────────────────────────────

    async def record_usage(
        self,
        job_id: int,
        expert_id: int | None,
        owner_id: str | None,
        rows: list[tuple[UsageKey, UsageBucket]],
    ) -> None:
        """Append usage rows and refresh the job's rollup, in one transaction."""
        if not rows:
            return
        records = [
            (
                job_id, expert_id, owner_id,
                key[0], key[1], key[2], key[3],
                bucket.calls,
                bucket.input_tokens,
                bucket.output_tokens,
                bucket.cache_creation_input_tokens,
                bucket.cache_read_input_tokens,
                Decimal(str(round(float(bucket.cost_usd), 6))),
            )
            for key, bucket in rows
        ]
        delta_cost = sum((r[12] for r in records), Decimal(0))
        delta_input = sum(r[8] for r in records)
        delta_output = sum(r[9] for r in records)
        # Embedding spend is tracked separately: it is the one provider cost the
        # tier knobs don't move, so it must stay visible next to Claude spend.
        delta_embed = sum(r[8] for r in records if r[4] == "openai")

        async with self._pool.acquire() as conn, conn.transaction():
            await conn.executemany(
                """
                INSERT INTO build_usage_events
                    (job_id, expert_id, owner_id, stage, provider, model, mode,
                     calls, input_tokens, output_tokens,
                     cache_creation_input_tokens, cache_read_input_tokens, cost_usd)
                VALUES ($1,$2,$3::uuid,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                """,
                records,
            )
            await conn.execute(
                """
                UPDATE build_jobs
                SET cost_usd = cost_usd + $2,
                    input_tokens = input_tokens + $3,
                    output_tokens = output_tokens + $4,
                    embed_tokens = embed_tokens + $5,
                    updated_at = NOW()
                WHERE id = $1
                """,
                job_id, delta_cost, delta_input, delta_output, delta_embed,
            )

    async def set_job_cap(self, job_id: int, cap_usd: float | None) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE build_jobs SET spend_cap_usd = $2 WHERE id = $1",
                job_id, Decimal(str(cap_usd)) if cap_usd else None,
            )

    async def mark_cap_exceeded(self, job_id: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE build_jobs SET cap_exceeded_at = NOW() WHERE id = $1 "
                "AND cap_exceeded_at IS NULL",
                job_id,
            )

    async def job_usage_breakdown(self, job_id: int) -> dict:
        """Per-stage and per-provider spend for one build job."""
        async with self._pool.acquire() as conn:
            job = await conn.fetchrow(
                """
                SELECT id, expert_id, status, cost_usd, input_tokens, output_tokens,
                       embed_tokens, spend_cap_usd, cap_exceeded_at
                FROM build_jobs WHERE id = $1
                """,
                job_id,
            )
            if job is None:
                return {}
            stages = await conn.fetch(
                """
                SELECT stage,
                       SUM(calls)::bigint AS calls,
                       SUM(input_tokens)::bigint AS input_tokens,
                       SUM(output_tokens)::bigint AS output_tokens,
                       SUM(cost_usd) AS cost_usd
                FROM build_usage_events WHERE job_id = $1
                GROUP BY stage ORDER BY SUM(cost_usd) DESC
                """,
                job_id,
            )
            providers = await conn.fetch(
                """
                SELECT provider, mode, model,
                       SUM(calls)::bigint AS calls,
                       SUM(cost_usd) AS cost_usd
                FROM build_usage_events WHERE job_id = $1
                GROUP BY provider, mode, model ORDER BY SUM(cost_usd) DESC
                """,
                job_id,
            )
        return {
            "job_id": job["id"],
            "expert_id": job["expert_id"],
            "status": job["status"],
            "cost_usd": float(job["cost_usd"] or 0),
            "input_tokens": int(job["input_tokens"] or 0),
            "output_tokens": int(job["output_tokens"] or 0),
            "embed_tokens": int(job["embed_tokens"] or 0),
            "spend_cap_usd": float(job["spend_cap_usd"]) if job["spend_cap_usd"] else None,
            "cap_exceeded_at": job["cap_exceeded_at"],
            "by_stage": [
                {
                    "stage": r["stage"],
                    "calls": int(r["calls"]),
                    "input_tokens": int(r["input_tokens"]),
                    "output_tokens": int(r["output_tokens"]),
                    "cost_usd": float(r["cost_usd"] or 0),
                }
                for r in stages
            ],
            "by_model": [
                {
                    "provider": r["provider"],
                    "mode": r["mode"],
                    "model": r["model"],
                    "calls": int(r["calls"]),
                    "cost_usd": float(r["cost_usd"] or 0),
                }
                for r in providers
            ],
        }


def _row_to_entry(row: asyncpg.Record) -> LedgerEntry:
    return LedgerEntry(
        id=row["id"],
        owner_id=str(row["owner_id"]),
        entry_type=LedgerEntryType(row["entry_type"]),
        delta=int(row["delta"]),
        job_id=row["job_id"],
        tier=row["tier"],
        reason=row["reason"],
        source=row["source"],
        external_ref=row["external_ref"],
        actor=row["actor"],
        cost_usd=float(row["cost_usd"]) if row["cost_usd"] is not None else None,
        created_at=row["created_at"],
    )


# Re-exported for callers that persist usage without importing the metering
# module's internals.
__all__ = ["BillingRepository", "UsageBucket", "UsageKey", "json"]
