from __future__ import annotations

import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from open_workshop_manager.sql_logic import sql_account as account
from open_workshop_manager.sql_logic import sql_catalog as catalog

MOD_RATING_SCALE = 10


def _display_name(row: object, ident: int) -> str:
    name = str(getattr(row, "name", "") or getattr(row, "username", "") or "").strip()
    return name or f"#{ident}"


async def _current_vote(
    session: AsyncSession,
    *,
    voter_id: int,
    target_type: str,
    target_id: int,
) -> account.ReputationVote | None:
    return await session.scalar(
        select(account.ReputationVote).where(
            account.ReputationVote.voter_id == voter_id,
            account.ReputationVote.target_type == target_type,
            account.ReputationVote.target_id == target_id,
        )
    )


async def apply_profile_vote(
    session: AsyncSession,
    *,
    voter_id: int,
    profile: account.Account,
    value: int,
) -> float:
    current_vote = await _current_vote(
        session,
        voter_id=voter_id,
        target_type="profile",
        target_id=int(profile.id),
    )
    previous_value = int(getattr(current_vote, "value", 0) or 0)
    if previous_value == value:
        return float(getattr(profile, "reputation", 0) or 0.0)

    delta = value - previous_value
    now = datetime.datetime.now()
    if current_vote is None:
        if value != 0:
            session.add(
                account.ReputationVote(
                    voter_id=voter_id,
                    target_type="profile",
                    target_id=int(profile.id),
                    value=value,
                    created_at=now,
                    updated_at=now,
                )
            )
    elif value == 0:
        await session.delete(current_vote)
    else:
        current_vote.value = value
        current_vote.updated_at = now

    profile.reputation = float(getattr(profile, "reputation", 0) or 0.0) + float(delta)
    session.add(
        account.ReputationVoteHistory(
            voter_id=voter_id,
            target_type="profile",
            target_id=int(profile.id),
            target_name=_display_name(profile, int(profile.id)),
            previous_value=previous_value,
            value=value,
            reputation_delta=float(delta),
            mod_delta=0,
            created_at=now,
        )
    )
    return float(profile.reputation)


async def apply_mod_vote(
    session: AsyncSession,
    *,
    voter_id: int,
    mod: catalog.Mod,
    value: int,
) -> int:
    current_vote = await _current_vote(
        session,
        voter_id=voter_id,
        target_type="mod",
        target_id=int(mod.id),
    )
    previous_value = int(getattr(current_vote, "value", 0) or 0)
    if previous_value == value:
        return int(getattr(mod, "rating", 0) or 0)

    delta = value - previous_value
    mod_delta = delta
    now = datetime.datetime.now()
    previous_rating = int(getattr(mod, "rating", 0) or 0)
    updated_rating = previous_rating + mod_delta
    author_delta = mod_delta / MOD_RATING_SCALE

    if current_vote is None:
        if value != 0:
            session.add(
                account.ReputationVote(
                    voter_id=voter_id,
                    target_type="mod",
                    target_id=int(mod.id),
                    value=value,
                    created_at=now,
                    updated_at=now,
                )
            )
    elif value == 0:
        await session.delete(current_vote)
    else:
        current_vote.value = value
        current_vote.updated_at = now

    mod.rating = updated_rating

    authors_result = await session.execute(
        select(account.Account)
        .join(
            account.mod_and_author,
            account.Account.id == account.mod_and_author.c.user_id,
        )
        .where(account.mod_and_author.c.mod_id == int(mod.id))
    )
    seen_author_ids: set[int] = set()
    for author in authors_result.scalars().all():
        author_id = int(getattr(author, "id", 0) or 0)
        if author_id in seen_author_ids:
            continue
        seen_author_ids.add(author_id)
        author.reputation = float(getattr(author, "reputation", 0) or 0.0) + author_delta

    session.add(
        account.ReputationVoteHistory(
            voter_id=voter_id,
            target_type="mod",
            target_id=int(mod.id),
            target_name=_display_name(mod, int(mod.id)),
            previous_value=previous_value,
            value=value,
            reputation_delta=author_delta,
            mod_delta=mod_delta,
            created_at=now,
        )
    )
    return int(mod.rating)


async def count_vote_history(session: AsyncSession, *, voter_id: int) -> int:
    return int(
        (
            await session.scalar(
                select(func.count()).select_from(account.ReputationVoteHistory).where(
                    account.ReputationVoteHistory.voter_id == voter_id
                )
            )
            or 0
        )
    )


async def list_vote_history(
    session: AsyncSession,
    *,
    voter_id: int,
    offset: int,
    limit: int,
) -> list[account.ReputationVoteHistory]:
    result = await session.execute(
        select(account.ReputationVoteHistory)
        .where(account.ReputationVoteHistory.voter_id == voter_id)
        .order_by(
            account.ReputationVoteHistory.created_at.desc(),
            account.ReputationVoteHistory.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()
