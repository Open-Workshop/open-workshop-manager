"""Build NGINX trace names from OpenAPI and Flask routes, without request values."""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path


def openapi_routes(url: str) -> list[str]:
    with urllib.request.urlopen(url, timeout=5) as response:
        paths = json.load(response)["paths"]
    if not isinstance(paths, dict) or not paths:
        raise ValueError(f"No OpenAPI routes from {url}")
    return list(paths)


def flask_config_routes(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "ROUTES":
            def flatten(value):
                if isinstance(value, dict):
                    for child in value.values():
                        yield from flatten(child)
                elif isinstance(value, list):
                    for child in value:
                        yield from flatten(child)
                elif isinstance(value, str):
                    yield value
            return list(flatten(ast.literal_eval(node.value)))
    raise ValueError(f"No ROUTES in {path}")


def flask_decorated_routes(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    routes = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == "app"
                and decorator.func.attr in {"route", "get", "post", "put", "delete", "patch"}
                and decorator.args and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)):
                routes.append(decorator.args[0].value)
    return routes


_PARAMETER = re.compile(r"\{([^{}]+)\}|<(?:(\w+):)?([^<>]+)>")


def route_pattern(route: str) -> tuple[str, str]:
    pattern, template, last = [], [], 0
    for match in _PARAMETER.finditer(route):
        literal = route[last:match.start()]
        pattern.append(re.escape(literal))
        template.append(literal)
        converter, name = match.group(2), match.group(1) or match.group(3)
        if converter == "path" or name == "path":
            pattern.append(".+")
        elif converter == "int" or name.endswith("_id") and name != "upload_id" and name != "job_id":
            pattern.append("[0-9]+")
        else:
            pattern.append("[^/]+")
        template.append("{" + name + "}")
        last = match.end()
    pattern.append(re.escape(route[last:]))
    template.append(route[last:])
    return "".join(pattern), "".join(template)


def build_map(routes_by_host: dict[str, list[str]]) -> str:
    rows = []
    for host, routes in sorted(routes_by_host.items()):
        for route in set(routes):
            if not route.startswith("/"):
                raise ValueError(f"Invalid route: {route!r}")
            pattern, template = route_pattern(route)
            # More literal characters and fewer parameters win over wildcards.
            literal_len = len(_PARAMETER.sub("", route))
            rows.append((-literal_len, len(_PARAMETER.findall(route)), host, pattern, template))
    lines = ["# Generated from application routes; do not edit manually.",
             'map "$host:$uri" $otel_normalized_route {', '    default "/unmatched";',
             '    "~^[^:]+:/assets/.*$" "/assets/{path}";',
             '    "~^[^:]+:/static/.*$" "/static/{path}";']
    for _, _, host, pattern, template in sorted(rows):
        lines.append(f'    "~^{re.escape(host)}:{pattern}$" "{template}";')
    lines.extend([
        "}", "",
        '# Backend selected by nginx; internal endpoints served by nginx stay unlabeled.',
        'map "$host:$uri" $otel_target_service {',
        '    default "";',
        r'    "~^(?:www\.)?(?:openworkshop\.miskler\.ru|miskler\.ru):/__rybbit_elastic_link$" "";',
        r'    "~^(?:www\.)?openworkshop\.miskler\.ru:" "open-workshop-website";',
        r'    "~^api\.openworkshop\.miskler\.ru:" "open-workshop-manager";',
        r'    "~^access\.openworkshop\.miskler\.ru:" "open-workshop-access";',
        r'    "~^(?:www\.)?miskler\.ru:" "personal-site";',
        r'    "~^storage\.openworkshop\.miskler\.ru:/(?:distributor(?:/|$)|download/|blurhashes$)" "open-workshop-storage-distributor";',
        r'    "~^storage\.openworkshop\.miskler\.ru:/(?:loader(?:/|$)|upload$|delete$|transfer/)" "open-workshop-storage-loader";',
        r'    "~^storage\.openworkshop\.miskler\.ru:" "storage";',
        r'    "~^elastic\.miskler\.ru:" "elastic";',
        r'    "~^analytics\.miskler\.ru:" "rybbit";',
        r'    "~^metabase\.miskler\.ru:" "metabase";',
        r'    "~^status\.miskler\.ru:" "uptime-kuma";',
        r'    "~^admin\.link\.miskler\.ru:" "shlink-admin";',
        r'    "~^link\.miskler\.ru:" "shlink";',
        r'    "~^mail\.miskler\.ru:" "webmail";',
        r'    "~^settings\.mail\.miskler\.ru:" "mail-settings";',
        r'    "~^cockpit\.miskler\.ru:" "cockpit-base";',
        r'    "~^cockpit\.storage\.openworkshop\.miskler\.ru:" "cockpit-storage";',
        r'    "~^platform\.miskler\.ru:" "platform";',
        "}", "",
        'map $otel_target_service $otel_target_display {',
        '    default "NGINX";',
        '    "open-workshop-website" "WEBSITE";',
        '    "open-workshop-manager" "MANAGER";',
        '    "open-workshop-access" "ACCESS";',
        '    "personal-site" "PERSONAL";',
        '    "open-workshop-storage-distributor" "STORAGE DISTRIBUTOR";',
        '    "open-workshop-storage-loader" "STORAGE LOADER";',
        "}", "",
        '# Applications have route templates; other services use one name per host.',
        'map $otel_target_service $otel_transaction_name {',
        '    default "NGINX $host";',
        '    "open-workshop-website" "$otel_target_display $request_method $otel_normalized_route";',
        '    "open-workshop-manager" "$otel_target_display $request_method $otel_normalized_route";',
        '    "open-workshop-access" "$otel_target_display $request_method $otel_normalized_route";',
        '    "personal-site" "$otel_target_display $request_method $otel_normalized_route";',
        '    "open-workshop-storage-distributor" "$otel_target_display $request_method $otel_normalized_route";',
        '    "open-workshop-storage-loader" "$otel_target_display $request_method $otel_normalized_route";',
        '    "storage" "STORAGE";',
        '    "elastic" "ELASTIC";',
        '    "rybbit" "RYBBIT";',
        '    "metabase" "METABASE";',
        '    "uptime-kuma" "UPTIME KUMA";',
        '    "shlink" "SHLINK";',
        '    "shlink-admin" "SHLINK ADMIN";',
        '    "webmail" "WEBMAIL";',
        '    "mail-settings" "MAIL SETTINGS";',
        '    "cockpit-base" "COCKPIT BASE";',
        '    "cockpit-storage" "COCKPIT STORAGE";',
        '    "platform" "PLATFORM";',
        "}", "",
    ])
    return "\n".join(lines)


def routes_for(role: str) -> dict[str, list[str]]:
    if role == "base":
        # Framework and health endpoints are intentionally absent from OpenAPI.
        infrastructure = ["/healthz", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"]
        manager = openapi_routes("http://127.0.0.1:7776/openapi.json") + infrastructure
        access = openapi_routes("http://127.0.0.1:7778/openapi.json") + infrastructure
        website = flask_config_routes(Path("/var/www/open-workshop-website/app_config.py"))
        website += flask_decorated_routes(Path("/var/www/open-workshop-website/main.py"))
        personal = flask_decorated_routes(Path("/var/www/website/main.py"))
        return {"api.openworkshop.miskler.ru": manager, "access.openworkshop.miskler.ru": access,
                "openworkshop.miskler.ru": website, "www.openworkshop.miskler.ru": website,
                "miskler.ru": personal, "www.miskler.ru": personal}
    distributor = openapi_routes("http://127.0.0.1:8000/openapi.json")
    loader = openapi_routes("http://127.0.0.1:8001/openapi.json")
    routes = distributor + loader + [
        "/distributor/", "/loader/", "/", "/openapi.json",
        "/distributor/openapi.json", "/loader/openapi.json",
        "/distributor/redoc", "/distributor/redoc/", "/loader/redoc", "/loader/redoc/",
        "/distributor/swagger-ui/openapi.json", "/loader/swagger-ui/openapi.json",
    ]
    routes += ["/distributor" + p for p in distributor] + ["/loader" + p for p in loader]
    return {"storage.openworkshop.miskler.ru": routes}


def install_map(path: Path, contents: str, reload_nginx: bool) -> None:
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == contents:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        stream.write(contents)
        temp = Path(stream.name)
    os.chmod(temp, 0o644)
    os.replace(temp, path)
    if not reload_nginx:
        return
    try:
        subprocess.run(["nginx", "-t"], check=True, timeout=15)
        subprocess.run(["systemctl", "reload", "nginx"], check=True, timeout=30)
    except Exception:
        if old is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(old, encoding="utf-8")
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["base", "storage"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    config = build_map(routes_for(args.role))
    if args.output:
        install_map(args.output, config, args.reload)
    else:
        print(config, end="")


if __name__ == "__main__":
    main()
