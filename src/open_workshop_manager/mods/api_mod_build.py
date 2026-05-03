"""Build-assistance routes for mod sets."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from open_workshop_manager import standarts, tools
from open_workshop_manager.api_helpers import unique_ints
from open_workshop_manager.api_models import (
    ModBuildConflictGraphRead,
    ModBuildDependencyGraphRead,
    ModBuildEdgeRead,
    ModBuildNodeRead,
)
from open_workshop_manager.limits import LIMITS
from open_workshop_manager.sql_logic import sql_catalog as catalog

router = APIRouter()


def _raise_mods_not_found(request: Request, missing_ids: list[int]) -> None:
    raise standarts.StandardAPIError(
        status_code=404,
        title="Not Found",
        detail="One or more mods were not found.",
        code="MOD_NOT_FOUND",
        instance=str(request.url),
        context={"missing_ids": missing_ids},
    )


async def _ensure_mods_exist(
    request: Request,
    session,
    mod_ids: list[int],
) -> None:
    if not mod_ids:
        return

    found_ids = set(
        int(mod_id)
        for mod_id in (
            await session.execute(
                select(catalog.Mod.id).where(catalog.Mod.id.in_(mod_ids))
            )
        ).scalars().all()
    )
    missing_ids = [mod_id for mod_id in mod_ids if mod_id not in found_ids]
    if missing_ids:
        _raise_mods_not_found(request, missing_ids)


def _mod_name(mod_names: dict[int, str], mod_id: int) -> str:
    return mod_names.get(mod_id) or f"#{mod_id}"


def _build_nodes(
    mod_ids: list[int],
    mod_names: dict[int, str],
    *,
    selected_ids: set[int],
) -> list[ModBuildNodeRead]:
    return [
        ModBuildNodeRead(
            mod_id=mod_id,
            mod_name=_mod_name(mod_names, mod_id),
            selected=mod_id in selected_ids,
        )
        for mod_id in sorted(set(mod_ids))
    ]


def _build_edges(edges: list[tuple[int, int]]) -> list[ModBuildEdgeRead]:
    return [
        ModBuildEdgeRead(source_mod_id=source_mod_id, target_mod_id=target_mod_id)
        for source_mod_id, target_mod_id in edges
    ]


async def _load_mod_names(session, mod_ids: list[int]) -> dict[int, str]:
    if not mod_ids:
        return {}

    result = await session.execute(
        select(catalog.Mod.id, catalog.Mod.name).where(catalog.Mod.id.in_(mod_ids))
    )
    return {int(mod_id): str(name) for mod_id, name in result.all()}


async def _collect_conflicting_edges(
    session,
    mod_ids: list[int],
) -> list[tuple[int, int]]:
    result = await session.execute(
        select(
            catalog.mods_conflicts.c.mod_id,
            catalog.mods_conflicts.c.conflict,
        ).where(
            catalog.mods_conflicts.c.mod_id.in_(mod_ids),
            catalog.mods_conflicts.c.conflict.in_(mod_ids),
        )
    )
    conflicting_pairs: set[tuple[int, int]] = set()
    for mod_id, conflict_id in result.all():
        left_id = int(mod_id)
        right_id = int(conflict_id)
        if left_id == right_id:
            continue
        pair = (left_id, right_id) if left_id < right_id else (right_id, left_id)
        conflicting_pairs.add(pair)
    return sorted(conflicting_pairs)


async def _collect_dependency_edges(
    session,
    mod_ids: list[int],
) -> list[tuple[int, int]]:
    dependency_edges: set[tuple[int, int]] = set()
    expanded_ids: set[int] = set()
    frontier_ids: set[int] = set(mod_ids)

    while frontier_ids:
        batch_ids = [mod_id for mod_id in frontier_ids if mod_id not in expanded_ids]
        if not batch_ids:
            break

        expanded_ids.update(batch_ids)
        result = await session.execute(
            select(
                catalog.mods_dependencies.c.mod_id,
                catalog.mods_dependencies.c.dependence,
            ).where(
                catalog.mods_dependencies.c.mod_id.in_(batch_ids),
                catalog.mods_dependencies.c.optional.is_(False),
            )
        )

        next_frontier_ids: set[int] = set()
        for mod_id, dependency_id in result.all():
            mod_id = int(mod_id)
            dependency_id = int(dependency_id)
            dependency_edges.add((mod_id, dependency_id))
            if dependency_id not in expanded_ids:
                next_frontier_ids.add(dependency_id)

        frontier_ids = next_frontier_ids

    return sorted(dependency_edges)


def _build_conflict_graph_response(
    mod_ids: list[int],
    edges: list[tuple[int, int]],
    mod_names: dict[int, str],
) -> ModBuildConflictGraphRead:
    nodes = _build_nodes(mod_ids, mod_names, selected_ids=set(mod_ids))
    return ModBuildConflictGraphRead(nodes=nodes, edges=_build_edges(edges))


def _build_dependency_graph_response(
    mod_ids: list[int],
    edges: list[tuple[int, int]],
    mod_names: dict[int, str],
) -> ModBuildDependencyGraphRead:
    node_ids = sorted(
        set(mod_ids)
        | {source_mod_id for source_mod_id, _ in edges}
        | {target_mod_id for _, target_mod_id in edges}
    )
    nodes = _build_nodes(node_ids, mod_names, selected_ids=set(mod_ids))
    return ModBuildDependencyGraphRead(nodes=nodes, edges=_build_edges(edges))


@router.get(
    "/mods/build/conflicts",
    tags=["Mod", "Build"],
    summary="Find conflicts in a mod set",
    description=(
        "Returns the conflict graph for the supplied `mods_ids` list. "
        "Nodes are the requested mods and edges link conflicting mods."
    ),
    status_code=200,
    response_model=ModBuildConflictGraphRead,
    response_model_exclude_none=True,
    response_description="Conflict graph.",
)
async def find_mod_set_conflicts(
    request: Request,
    mods_ids: list[int] = Query(
        default_factory=list,
        description="Mod IDs to analyze for mutual conflicts.",
    ),
) -> ModBuildConflictGraphRead:
    normalized_mod_ids = unique_ints(mods_ids)
    if not normalized_mod_ids:
        return ModBuildConflictGraphRead(nodes=[], edges=[])
    if len(normalized_mod_ids) > LIMITS.mod.filters_max:
        raise standarts.PayloadTooLargeError(
            detail="The mod ID list is too large.",
            instance=str(request.url),
            context={"field": "mods_ids"},
        )

    async with catalog.AsyncSessionLocal() as session:
        await _ensure_mods_exist(request, session, normalized_mod_ids)
        await tools.access_mods(request=request, mods_ids=normalized_mod_ids)
        conflicting_edges = await _collect_conflicting_edges(session, normalized_mod_ids)
        mod_names = await _load_mod_names(session, normalized_mod_ids)

    return _build_conflict_graph_response(normalized_mod_ids, conflicting_edges, mod_names)


@router.get(
    "/mods/build/dependencies/missing",
    tags=["Mod", "Build"],
    summary="Find missing dependencies in a mod set",
    description=(
        "Returns the dependency graph for the supplied `mods_ids` list. "
        "Nested required dependencies are traversed transitively, and nodes with `selected=false` "
        "are the mods that still need to be added."
    ),
    status_code=200,
    response_model=ModBuildDependencyGraphRead,
    response_model_exclude_none=True,
    response_description="Dependency graph.",
)
async def find_mod_set_missing_dependencies(
    request: Request,
    mods_ids: list[int] = Query(
        default_factory=list,
        description="Mod IDs to analyze for missing required dependencies.",
    ),
) -> ModBuildDependencyGraphRead:
    normalized_mod_ids = unique_ints(mods_ids)
    if not normalized_mod_ids:
        return ModBuildDependencyGraphRead(nodes=[], edges=[])
    if len(normalized_mod_ids) > LIMITS.mod.filters_max:
        raise standarts.PayloadTooLargeError(
            detail="The mod ID list is too large.",
            instance=str(request.url),
            context={"field": "mods_ids"},
        )

    async with catalog.AsyncSessionLocal() as session:
        await _ensure_mods_exist(request, session, normalized_mod_ids)
        await tools.access_mods(request=request, mods_ids=normalized_mod_ids)
        dependency_edges = await _collect_dependency_edges(session, normalized_mod_ids)
        dependency_mod_ids = sorted(
            set(normalized_mod_ids)
            | {source_mod_id for source_mod_id, _ in dependency_edges}
            | {target_mod_id for _, target_mod_id in dependency_edges}
        )
        mod_names = await _load_mod_names(session, dependency_mod_ids)

    return _build_dependency_graph_response(normalized_mod_ids, dependency_edges, mod_names)
