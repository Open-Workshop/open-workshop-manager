from __future__ import annotations

import asyncio
import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, insert, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# Install the same optional-driver stubs as the route tests before importing the API.
from tests.test_mod_list_size_filter import _mod
from open_workshop_manager import reputation
from open_workshop_manager import main as app_main
from open_workshop_manager.app import api_catalog_statistics
from open_workshop_manager.mods import api_mod
from open_workshop_manager.games import api_game
from open_workshop_manager.association import api_association_getter
from open_workshop_manager.sql_logic import sql_account as account, sql_catalog as catalog


class AsyncSessionAdapter:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, statement):
        return self.session.execute(statement)

    async def scalar(self, statement):
        return self.session.scalar(statement)

    async def get(self, model, key):
        return self.session.get(model, key)

    async def commit(self):
        self.session.commit()


class ModBatchQueryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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

    def test_association_maps_batch_filter_and_preserve_access_checks(self):
        catalog.Mod.__table__.create(self.engine)
        catalog.Genre.__table__.create(self.engine)
        catalog.game_genres.create(self.engine)
        with self.engine.begin() as connection:
            for mod_id in (1, 2):
                connection.exec_driver_sql("INSERT INTO mods (id, name, size, rating, `condition`, public, source, downloads, adult) VALUES (?, 'x', 0, 0, 0, 0, 'local', 0, 0)", (mod_id,))
            connection.execute(insert(catalog.Genre), [dict(id=1, name="Action"), dict(id=2, name="Strategy")])
            connection.execute(insert(catalog.game_genres), [dict(game_id=1, genre_id=1), dict(game_id=1, genre_id=2), dict(game_id=2, genre_id=2)])
        async def check():
            request = SimpleNamespace(url="http://test/")
            with patch.object(catalog, "AsyncSessionLocal", return_value=self.adapter), patch.object(api_association_getter.tools, "access_mods", AsyncMock(return_value=[1, 2])) as access:
                values = await api_association_getter.get_mod_tags_map(request, [1, 2], [1], True)
                self.assertEqual(values, {"items_by_mod_id": {"1": [1], "2": [1]}})
                access.assert_awaited_once()
                tags = await api_association_getter.get_mod_tags_map(request, [1, 2], [2], False)
                self.assertEqual(tags["items_by_mod_id"]["1"], [{"id": 2, "name": "Alpha"}])
                self.assertEqual(tags["items_by_mod_id"]["2"], [])
                values = await api_association_getter.get_game_genres_map(request, [1, 2, 3], [2], True)
                self.assertEqual(values, {"items_by_game_id": {"1": [2], "2": [2], "3": []}})
                genres = await api_association_getter.get_game_genres_map(request, [1, 2], [1], False)
                self.assertEqual(genres, {"items_by_game_id": {"1": [{"id": 1, "name": "Action"}], "2": []}})
        asyncio.run(check())

    def test_cleanup_batches_only_expired_unfinished_empty_resources(self):
        catalog.UploadJob.__table__.create(self.engine)
        with self.engine.begin() as connection:
            connection.execute(insert(catalog.Resource), [dict(id=4, type="image", sort_order=0, url="", owner_type="mods", owner_id=1), dict(id=5, type="image", sort_order=0, url="https://example.org/done", owner_type="mods", owner_id=1), dict(id=6, type="image", sort_order=0, url="", owner_type="mods", owner_id=1)])
            common = dict(kind="resource_image", transfer_url="x", ws_url="x", expires_at=datetime.datetime(2020, 1, 1), mode="create")
            connection.execute(insert(catalog.UploadJob), [dict(common, id="a", status="created", resource_id=4), dict(common, id="b", status="failed", resource_id=5), dict(common, id="c", status="completed", resource_id=6), dict(common, id="d", status="created", resource_id=4)])
        async def check():
            with patch.object(catalog, "AsyncSessionLocal", return_value=self.adapter):
                await app_main._cleanup_expired_upload_jobs_once()
        asyncio.run(check())
        self.assertEqual(set(self.session.execute(select(catalog.Resource.id)).scalars()), {1, 2, 5, 6})
        self.assertEqual(self.session.execute(select(catalog.UploadJob.id)).scalars().all(), [])

    def test_catalog_statistics_aggregates_including_missing_unpacked_sizes(self):
        catalog.Mod.__table__.create(self.engine)
        with self.engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE accounts (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql("INSERT INTO accounts (id) VALUES (1), (2)")
            for mod_id, condition, size, unpacked in [(1, 0, 12, None), (2, 0, 30, 50), (3, 1, 100, 200)]:
                connection.exec_driver_sql("INSERT INTO mods (id, name, size, size_unpacked, rating, `condition`, public, source, downloads, adult) VALUES (?, 'x', ?, ?, 0, ?, 0, 'local', 0, 0)", (mod_id, size, unpacked, condition))
        async def check():
            with patch.object(catalog, "AsyncSessionLocal", return_value=self.adapter), patch.object(account, "AsyncSessionLocal", return_value=self.adapter):
                return await api_catalog_statistics.get_catalog_statistics()
        actual = asyncio.run(check())
        self.assertEqual(actual, {"mods_count": 2, "users_count": 2, "database_size_bytes": 42, "database_size_unpacked_bytes": 62, "resources_size_bytes": 0})

    def test_static_association_routes_are_not_shadowed_by_id_routes(self):
        catalog.Genre.__table__.create(self.engine)
        catalog.game_genres.create(self.engine)
        with self.engine.begin() as connection:
            connection.execute(insert(catalog.Genre), [dict(id=1, name="Action")])
            connection.execute(insert(catalog.game_genres), [dict(game_id=1, genre_id=1)])
        with patch.object(catalog, "AsyncSessionLocal", return_value=self.adapter):
            client = TestClient(app_main.app)
            response = client.get("/games/genres", params={"game_ids": 1, "only_ids": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items_by_game_id": {"1": [1]}})

    def test_profile_content_votes_handle_duplicate_authorship_and_both_content_types(self):
        with self.engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE modpacks_and_authors (modpack_id INTEGER, user_id INTEGER, owner BOOLEAN)")
            connection.exec_driver_sql("CREATE TABLE reputation_votes (id INTEGER PRIMARY KEY, voter_id INTEGER, target_type TEXT, target_id INTEGER, value INTEGER)")
            connection.execute(insert(account.mod_and_author), [dict(mod_id=1, user_id=42, owner=False), dict(mod_id=1, user_id=42, owner=True)])
            connection.execute(insert(account.modpack_and_author), [dict(modpack_id=7, user_id=42, owner=True)])
            connection.exec_driver_sql("INSERT INTO reputation_votes VALUES (1, 2, 'mod', 1, 1), (2, 3, 'mod', 1, -1), (3, 2, 'modpack', 7, 1), (4, 3, 'modpack', 1, -1), (5, 3, 'profile', 42, -1)")
        async def check():
            return await reputation.load_profile_content_summary(self.adapter, profile_id=42)
        self.assertEqual(asyncio.run(check()), reputation.VoteSummary(rating=67, votes_count=3))

    def test_mod_list_loads_long_text_only_when_requested(self):
        catalog.Mod.__table__.create(self.engine)
        with self.engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO mods (id,name,short_description,description,size,rating,`condition`,public,source,downloads,adult) VALUES (1,'one','short','long text',1,0,0,0,'local',1,0)")
        statements = []
        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT MODS.ID,"):
                statements.append(statement.lower())
        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            with patch.object(catalog, "AsyncSessionLocal", return_value=self.adapter), patch.object(api_mod, "_load_mod_vote_counts", AsyncMock(return_value={})):
                client = TestClient(app_main.app)
                response = client.get("/mods", params={"page_size": 2})
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("description", response.json()["items"][0])
                self.assertNotIn("mods.description", statements[-1])
                self.session.expire_all()
                response = client.get("/mods", params={"page_size": 2, "include": "description"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["items"][0]["description"], "long text")
                self.assertIn("mods.description", statements[-1])
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)

    def test_resources_only_urls_loads_no_unneeded_resource_columns(self):
        with self.engine.begin() as connection:
            connection.execute(insert(catalog.Resource), [dict(id=3, type="image", sort_order=0, url="https://example.org/game", owner_type="games", owner_id=1)])
        statements = []
        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT RESOURCES.ID,"):
                statements.append(statement.lower())
        event.listen(self.engine, "before_cursor_execute", capture)
        try:
            with patch.object(catalog, "AsyncSessionLocal", return_value=self.adapter):
                response = TestClient(app_main.app).get("/resources", params={"owner_type": "games", "owner_id": 1, "only_urls": "true"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["items"], ["https://example.org/game"])
            self.assertNotIn("resources.size", statements[-1])
            self.assertNotIn("resources.type", statements[-1])
        finally:
            event.remove(self.engine, "before_cursor_execute", capture)

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
