from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event, insert, select, func
from sqlalchemy.orm import Session

# Install the same optional-driver stubs as the route tests before importing the API.
from tests.test_mod_list_size_filter import _mod
from open_workshop_manager.mods import api_mod
from open_workshop_manager.games import api_game
from open_workshop_manager.sql_logic import sql_account as account, sql_catalog as catalog


class AsyncSessionAdapter:
    def __init__(self, session):
        self.session = session

    async def execute(self, statement):
        return self.session.execute(statement)

    async def get(self, model, key):
        return self.session.get(model, key)


class ModBatchQueryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        tables = [catalog.Game.__table__, catalog.TagGroup.__table__, catalog.Tag.__table__,
                  catalog.mods_tags, catalog.mods_dependencies, catalog.mods_conflicts,
                  catalog.Resource.__table__]
        catalog.Base.metadata.create_all(self.engine, tables=tables)
        with self.engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE mods_and_authors (mod_id INTEGER, user_id INTEGER, owner BOOLEAN)")
            connection.execute(insert(catalog.Game), [dict(id=1, name="Game", type="game", mods_count=2, mods_downloads=0, source="local")])
            connection.execute(insert(catalog.TagGroup), [dict(id=1, name="Type")])
            connection.execute(insert(catalog.Tag), [dict(id=1, name="Zulu", group_id=1), dict(id=2, name="Alpha", group_id=None)])
            connection.execute(insert(catalog.mods_tags), [dict(mod_id=1, tag_id=1), dict(mod_id=1, tag_id=2), dict(mod_id=2, tag_id=1)])
            connection.execute(insert(catalog.mods_dependencies), [dict(mod_id=1, dependence=4, optional=True), dict(mod_id=1, dependence=3, optional=False)])
            connection.execute(insert(catalog.mods_conflicts), [dict(mod_id=1, conflict=2), dict(mod_id=2, conflict=1), dict(mod_id=1, conflict=3)])
            connection.execute(insert(account.mod_and_author), [dict(mod_id=1, user_id=42, owner=True), dict(mod_id=2, user_id=41, owner=False)])
            connection.execute(insert(catalog.Resource), [dict(id=1, type="image", sort_order=1, url="https://example.org/1", owner_type="mods", owner_id=1), dict(id=2, type="image", sort_order=0, url="https://example.org/2", owner_type="mods", owner_id=1)])
        self.session = Session(self.engine)
        self.adapter = AsyncSessionAdapter(self.session)
        self.rows = [_mod(mod_id=1, game=1), _mod(mod_id=2, game=1), _mod(mod_id=3, game=None)]

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_batch_matches_single_mod_results_for_all_conflict_scopes(self):
        async def check():
            includes = {"game", "tags", "dependencies", "conflicts", "authors", "resources", "dates", "description"}
            for scope in ("all", "incoming", "outgoing"):
                with self.subTest(scope=scope):
                    original = [(await api_mod._serialize_mod_with_includes(self.adapter, None, row, includes, scope)).model_dump(mode="json", exclude_none=True) for row in self.rows]
                    statements = []
                    def count(*args):
                        statements.append(args[2])
                    event.listen(self.engine, "before_cursor_execute", count)
                    try:
                        data = await api_mod._load_mod_includes_batch(self.adapter, self.rows, includes, scope)
                        actual = [(await api_mod._serialize_mod_with_includes(self.adapter, None, row, includes, scope, preloaded=data[row.id])).model_dump(mode="json", exclude_none=True) for row in self.rows]
                    finally:
                        event.remove(self.engine, "before_cursor_execute", count)
                    self.assertEqual(actual, original)
                    self.assertEqual(len(statements), 6)
        asyncio.run(check())

    def test_game_batch_matches_single_game_results(self):
        catalog.Genre.__table__.create(self.engine)
        catalog.game_genres.create(self.engine)
        catalog.allowed_mods_tags.create(self.engine)
        with self.engine.begin() as connection:
            connection.execute(insert(catalog.Game), [dict(id=2, name="Other", type="game", mods_count=0, mods_downloads=0, source="local")])
            connection.execute(insert(catalog.Genre), [dict(id=1, name="Action")])
            connection.execute(insert(catalog.game_genres), [dict(game_id=1, genre_id=1)])
            connection.execute(insert(catalog.allowed_mods_tags), [dict(game_id=1, tag_id=1), dict(game_id=1, tag_id=2), dict(game_id=2, tag_id=1)])
            connection.execute(insert(catalog.Resource), [dict(id=3, type="image", sort_order=0, url="https://example.org/game", owner_type="games", owner_id=1)])
        rows = self.session.execute(select(catalog.Game).order_by(catalog.Game.id)).scalars().all()
        async def check():
            includes = {"genres", "tags", "resources", "statistics"}
            original = [(await api_game._serialize_game_with_includes(self.adapter, None, row, includes)).model_dump(mode="json", exclude_none=True) for row in rows]
            statements = []
            def count(*args):
                statements.append(args[2])
            event.listen(self.engine, "before_cursor_execute", count)
            try:
                data = await api_game._load_game_includes_batch(self.adapter, rows, includes)
                actual = [(await api_game._serialize_game_with_includes(self.adapter, None, row, includes, preloaded=data[row.id])).model_dump(mode="json", exclude_none=True) for row in rows]
            finally:
                event.remove(self.engine, "before_cursor_execute", count)
            self.assertEqual(actual, original)
            self.assertEqual(len(statements), 3)
        asyncio.run(check())

    def test_feed_aggregate_matches_individual_queries_and_empty_results(self):
        catalog.Mod.__table__.create(self.engine)
        with self.engine.begin() as connection:
            for mod_id, game, public, size, unpacked in [(10, 1, 0, 12, None), (11, 1, 0, 30, 50), (12, 1, 2, 1, 2), (13, 2, 0, 100, 200)]:
                connection.exec_driver_sql("INSERT INTO mods (id, name, size, size_unpacked, rating, `condition`, public, source, downloads, game, adult) VALUES (?, 'x', ?, ?, 0, 0, ?, 'local', 0, ?, 0)", (mod_id, size, unpacked, public, game))
        for game in (1, 999):
            filters = (catalog.Mod.condition == 0, catalog.Mod.public == 0, catalog.Mod.game == game)
            aggregate = select(func.count(), func.min(catalog.Mod.size), func.max(catalog.Mod.size), func.min(catalog.Mod.size_unpacked), func.max(catalog.Mod.size_unpacked)).where(*filters)
            actual = tuple(self.session.execute(aggregate).one())
            original = tuple(self.session.scalar(select(expr).select_from(catalog.Mod).where(*filters)) for expr in (func.count(), func.min(catalog.Mod.size), func.max(catalog.Mod.size), func.min(catalog.Mod.size_unpacked), func.max(catalog.Mod.size_unpacked)))
            self.assertEqual(actual, original)
        self.assertEqual(actual, (0, None, None, None, None))
