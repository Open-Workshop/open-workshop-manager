from __future__ import annotations

import importlib.util
import pathlib
import re
import unittest

path = pathlib.Path(__file__).resolve().parents[1] / "ops" / "nginx_otel_routes.py"
spec = importlib.util.spec_from_file_location("nginx_otel_routes", path)
routes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routes)


class NginxOtelRouteTests(unittest.TestCase):
    def test_template_normalizes_dynamic_values_and_keeps_routes_distinct(self):
        for route, valid, invalid, template in [
            ("/mods/{mod_id}", "/mods/123", "/mods/tags", "/mods/{mod_id}"),
            ("/mod/<int:mod_id>/edit.html", "/mod/123/edit.html", "/mod/add/edit.html", "/mod/{mod_id}/edit.html"),
            ("/download/{storage_type}/{path}", "/download/archive/mods/123/main.zip", "/download/archive/", "/download/{storage_type}/{path}"),
            ("/uploads/{upload_id}", "/uploads/a-b-c", "/uploads/a/b", "/uploads/{upload_id}"),
        ]:
            with self.subTest(route=route):
                pattern, actual = routes.route_pattern(route)
                self.assertEqual(actual, template)
                self.assertIsNotNone(re.fullmatch(pattern, valid))
                self.assertIsNone(re.fullmatch(pattern, invalid))

    def test_map_prefers_static_and_preserves_method_independent_routes(self):
        text = routes.build_map({"example.org": ["/mods/{mod_id}", "/mods/tags", "/mods/{mod_id}/rating"]})
        self.assertLess(text.index('/mods/tags$'), text.index('/mods/[0-9]+$'))
        self.assertIn('"/mods/{mod_id}/rating"', text)
        self.assertIn('"/mods/{mod_id}"', text)
        self.assertIn('default "/unmatched"', text)
        self.assertIn('"open-workshop-website" "WEBSITE";', text)
        self.assertIn('"open-workshop-storage-loader" "STORAGE LOADER";', text)

    def test_other_services_have_one_name_and_ow_keeps_method_and_route(self):
        text = routes.build_map({"api.openworkshop.miskler.ru": ["/healthz"]})
        self.assertIn('map "$server_name:$uri" $otel_target_service', text)
        self.assertIn('default "NGINX $server_name";', text)
        self.assertIn('"~^elastic\\.miskler\\.ru:" "elastic";', text)
        self.assertIn('"~^analytics\\.miskler\\.ru:" "rybbit";', text)
        self.assertIn('"elastic" "ELASTIC";', text)
        self.assertIn('"rybbit" "RYBBIT";', text)
        self.assertIn('"open-workshop-manager" "$otel_target_display $request_method $otel_normalized_route";', text)
        self.assertIn('"~^api\\.openworkshop\\.miskler\\.ru:/healthz$" "/healthz";', text)


if __name__ == "__main__":
    unittest.main()
