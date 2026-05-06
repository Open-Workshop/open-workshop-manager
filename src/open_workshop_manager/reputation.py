from __future__ import annotations

import datetime
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from open_workshop_manager.sql_logic import sql_account as account
from open_workshop_manager.sql_logic import sql_catalog as catalog

MOD_RATING_SCALE = 10


@dataclass(frozen=True, slots=True)
class VoteSummary:
    rating: int = 0
    votes_count: int = 0


def _display_name(row: object, ident: int) -> str:
    name = str(getattr(row, "name", "") or getattr(row, "username", "") or "").strip()
    return name or f"#{ident}"


def _vote_history_key(row: object) -> tuple[str, int]:
    return (
        str(getattr(row, "target_type", "") or ""),
        int(getattr(row, "target_id", 0) or 0),
    )


def _approval_percent(positive_votes: int, votes_count: int) -> int:
    if votes_count <= 0:
        return 0
    return int((positive_votes * 200 + votes_count) // (2 * votes_count))


def _normalize_target_ids(target_ids: Iterable[int]) -> list[int]:
    return [target_id for target_id in dict.fromkeys(int(target_id) for target_id in target_ids) if target_id > 0]


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


async def _latest_vote_history_row(
    session: AsyncSession,
    *,
    voter_id: int,
    target_type: str,
    target_id: int,
) -> account.ReputationVoteHistory | None:
    return await session.scalar(
        select(account.ReputationVoteHistory)
        .where(
            account.ReputationVoteHistory.voter_id == voter_id,
            account.ReputationVoteHistory.target_type == target_type,
            account.ReputationVoteHistory.target_id == target_id,
        )
        .order_by(
            account.ReputationVoteHistory.created_at.desc(),
            account.ReputationVoteHistory.id.desc(),
        )
    )


async def _upsert_vote_history(
    session: AsyncSession,
    *,
    voter_id: int,
    target_type: str,
    target_id: int,
    target_name: str,
    previous_value: int,
    value: int,
    reputation_delta: float,
    mod_delta: int,
    created_at: datetime.datetime,
) -> None:
    row = await _latest_vote_history_row(
        session,
        voter_id=voter_id,
        target_type=target_type,
        target_id=target_id,
    )
    if row is None:
        session.add(
            account.ReputationVoteHistory(
                voter_id=voter_id,
                target_type=target_type,
                target_id=target_id,
                target_name=target_name,
                previous_value=previous_value,
                value=value,
                reputation_delta=reputation_delta,
                mod_delta=mod_delta,
                created_at=created_at,
            )
        )
        return

    row.voter_id = voter_id
    row.target_type = target_type
    row.target_id = target_id
    row.target_name = target_name
    row.previous_value = previous_value
    row.value = value
    row.reputation_delta = reputation_delta
    row.mod_delta = mod_delta
    row.created_at = created_at


async def load_vote_summary(
    session: AsyncSession,
    *,
    target_type: str,
    target_id: int,
) -> VoteSummary:
    summaries = await load_vote_summaries(
        session,
        target_type=target_type,
        target_ids=[target_id],
    )
    return summaries.get(int(target_id), VoteSummary())


async def load_vote_summaries(
    session: AsyncSession,
    *,
    target_type: str,
    target_ids: Iterable[int],
) -> dict[int, VoteSummary]:
    ids = _normalize_target_ids(target_ids)
    if not ids:
        return {}

    result = await session.execute(
        select(
            account.ReputationVote.target_id,
            func.count().label("votes_count"),
            func.coalesce(
                func.sum(case((account.ReputationVote.value > 0, 1), else_=0)),
                0,
            ).label("positive_votes"),
        )
        .where(
            account.ReputationVote.target_type == target_type,
            account.ReputationVote.target_id.in_(ids),
        )
        .group_by(account.ReputationVote.target_id)
    )

    votes_by_target: dict[int, VoteSummary] = {target_id: VoteSummary() for target_id in ids}
    for target_id, votes_count, positive_votes in result.all():
        target_key = int(target_id)
        votes_by_target[target_key] = VoteSummary(
            rating=_approval_percent(int(positive_votes or 0), int(votes_count or 0)),
            votes_count=int(votes_count or 0),
        )
    return votes_by_target


async def count_vote_counts(
    session: AsyncSession,
    *,
    target_type: str,
    target_ids: Iterable[int],
) -> dict[int, int]:
    ids = _normalize_target_ids(target_ids)
    if not ids:
        return {}

    result = await session.execute(
        select(
            account.ReputationVote.target_id,
            func.count().label("votes_count"),
        )
        .where(
            account.ReputationVote.target_type == target_type,
            account.ReputationVote.target_id.in_(ids),
        )
        .group_by(account.ReputationVote.target_id)
    )
    return {int(target_id): int(votes_count or 0) for target_id, votes_count in result.all()}


async def apply_profile_vote(
    session: AsyncSession,
    *,
    voter_id: int,
    profile: account.Account,
    value: int,
) -> VoteSummary:
    current_vote = await _current_vote(
        session,
        voter_id=voter_id,
        target_type="profile",
        target_id=int(profile.id),
    )
    previous_value = int(getattr(current_vote, "value", 0) or 0)
    if previous_value == value:
        summary = await load_vote_summary(
            session,
            target_type="profile",
            target_id=int(profile.id),
        )
        profile.rating = summary.rating
        profile.votes_count = summary.votes_count
        return summary

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

    summary = await load_vote_summary(
        session,
        target_type="profile",
        target_id=int(profile.id),
    )
    profile.rating = summary.rating
    profile.votes_count = summary.votes_count
    await _upsert_vote_history(
        session,
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
    return summary


async def apply_mod_vote(
    session: AsyncSession,
    *,
    voter_id: int,
    mod: catalog.Mod,
    value: int,
) -> VoteSummary:
    return await _apply_content_vote(
        session,
        voter_id=voter_id,
        target_type="mod",
        item=mod,
        value=value,
        relation_table=account.mod_and_author,
        relation_target_column="mod_id",
    )


async def apply_modpack_vote(
    session: AsyncSession,
    *,
    voter_id: int,
    modpack: catalog.Modpack,
    value: int,
) -> VoteSummary:
    return await _apply_content_vote(
        session,
        voter_id=voter_id,
        target_type="modpack",
        item=modpack,
        value=value,
        relation_table=account.modpack_and_author,
        relation_target_column="modpack_id",
    )


async def _apply_content_vote(
    session: AsyncSession,
    *,
    voter_id: int,
    target_type: str,
    item: catalog.Mod | catalog.Modpack,
    value: int,
    relation_table,
    relation_target_column: str,
) -> VoteSummary:
    current_vote = await _current_vote(
        session,
        voter_id=voter_id,
        target_type=target_type,
        target_id=int(item.id),
    )
    previous_value = int(getattr(current_vote, "value", 0) or 0)
    if previous_value == value:
        summary = await load_vote_summary(
            session,
            target_type=target_type,
            target_id=int(item.id),
        )
        item.rating = summary.rating
        return summary

    delta = value - previous_value
    now = datetime.datetime.now()
    author_delta = delta / MOD_RATING_SCALE

    if current_vote is None:
        if value != 0:
            session.add(
                account.ReputationVote(
                    voter_id=voter_id,
                    target_type=target_type,
                    target_id=int(item.id),
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

    authors_result = await session.execute(
        select(account.Account)
        .join(
            relation_table,
            account.Account.id == relation_table.c.user_id,
        )
        .where(getattr(relation_table.c, relation_target_column) == int(item.id))
    )
    seen_author_ids: set[int] = set()
    for author in authors_result.scalars().all():
        author_id = int(getattr(author, "id", 0) or 0)
        if author_id in seen_author_ids:
            continue
        seen_author_ids.add(author_id)
        author.reputation = float(getattr(author, "reputation", 0) or 0.0) + author_delta

    await _upsert_vote_history(
        session,
        voter_id=voter_id,
        target_type=target_type,
        target_id=int(item.id),
        target_name=_display_name(item, int(item.id)),
        previous_value=previous_value,
        value=value,
        reputation_delta=author_delta,
        mod_delta=delta,
        created_at=now,
    )
    summary = await load_vote_summary(
        session,
        target_type=target_type,
        target_id=int(item.id),
    )
    item.rating = summary.rating
    return summary


async def current_vote_value(
    session: AsyncSession,
    *,
    voter_id: int,
    target_type: str,
    target_id: int,
) -> int | None:
    """Return the latest recorded vote state for a target, if any."""
    row = await _latest_vote_history_row(
        session,
        voter_id=voter_id,
        target_type=target_type,
        target_id=target_id,
    )
    if row is None:
        current_vote = await _current_vote(
            session,
            voter_id=voter_id,
            target_type=target_type,
            target_id=target_id,
        )
        if current_vote is None:
            return None
        return int(getattr(current_vote, "value", 0) or 0)
    return int(getattr(row, "value", 0) or 0)


async def _latest_vote_history_rows(
    session: AsyncSession,
    *,
    voter_id: int,
) -> list[account.ReputationVoteHistory]:
    result = await session.execute(
        select(account.ReputationVoteHistory)
        .where(account.ReputationVoteHistory.voter_id == voter_id)
        .order_by(
            account.ReputationVoteHistory.created_at.desc(),
            account.ReputationVoteHistory.id.desc(),
        )
    )
    latest_rows: list[account.ReputationVoteHistory] = []
    seen: set[tuple[str, int]] = set()
    for row in result.scalars().all():
        key = _vote_history_key(row)
        if key in seen:
            continue
        seen.add(key)
        latest_rows.append(row)
    return latest_rows


async def load_vote_history_page(
    session: AsyncSession,
    *,
    voter_id: int,
    offset: int,
    limit: int,
) -> tuple[int, list[account.ReputationVoteHistory]]:
    rows = await _latest_vote_history_rows(session, voter_id=voter_id)
    return len(rows), rows[offset : offset + limit]


async def count_vote_history(session: AsyncSession, *, voter_id: int) -> int:
    total, _ = await load_vote_history_page(session, voter_id=voter_id, offset=0, limit=0)
    return total


async def list_vote_history(
    session: AsyncSession,
    *,
    voter_id: int,
    offset: int,
    limit: int,
) -> list[account.ReputationVoteHistory]:
    _, rows = await load_vote_history_page(session, voter_id=voter_id, offset=offset, limit=limit)
    return rows
