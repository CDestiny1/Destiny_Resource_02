"""Puente entre la interfaz web y el motor Python (corre dentro de Pyodide).

Replica las rutas de server.py sin abrir ningún servidor HTTP: el navegador
llama a handle(metodo, ruta, cabeceras, cuerpo) y recibe (json_cabeceras, bytes).
"""
from __future__ import annotations

import json
import tempfile
import traceback
import urllib.parse
from pathlib import Path

from database import DatabaseManager
from team_assets import TeamAssetWorkspace


STATE: dict[str, object | None] = {"db": None, "import_db": None, "assets": TeamAssetWorkspace()}
JSON_TYPE = "application/json; charset=utf-8"
BIN_TYPE = "application/octet-stream"


def re_safe(value: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in value)[:120]


def _reply(code: int, body: bytes, content_type: str, extra: dict | None = None):
    headers = {"content-type": content_type}
    headers.update(extra or {})
    return code, headers, body


def _json(value, code: int = 200):
    return _reply(code, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), JSON_TYPE)


def _error(error: Exception, code: int = 400):
    return _json({"ok": False, "error": str(error) or error.__class__.__name__}, code)


def _unquote(headers: dict, name: str, default: str = "") -> str:
    return urllib.parse.unquote(headers.get(name, default))


def _db() -> DatabaseManager:
    db = STATE["db"]
    if db is None:
        raise ValueError("Primero carga el archivo Resource_02.cpk")
    return db  # type: ignore[return-value]


def _assets() -> TeamAssetWorkspace:
    assets = STATE["assets"]
    assert isinstance(assets, TeamAssetWorkspace)
    return assets


def _body_to_temp(body: bytes, limit: int) -> Path:
    if len(body) <= 0:
        raise ValueError("El archivo está vacío")
    if len(body) > limit:
        raise ValueError("El archivo supera el límite de seguridad")
    handle = tempfile.NamedTemporaryFile(prefix="upload_", dir=_assets().root, delete=False)
    path = Path(handle.name)
    try:
        handle.write(body)
        handle.close()
        return path
    except Exception:
        handle.close()
        path.unlink(missing_ok=True)
        raise


def _club_teams(source: DatabaseManager) -> list[dict]:
    return sorted(
        ({k: v for k, v in team.items() if k != "index"} for team in source.teams.values() if team["kind"] == "club"),
        key=lambda team: (team["name"].casefold(), team["id"]),
    )


def _payload(body: bytes) -> dict:
    try:
        value = json.loads(body.decode("utf-8"))
    except Exception:
        raise ValueError("Datos JSON no válidos") from None
    if not isinstance(value, dict):
        raise ValueError("Se esperaba un objeto JSON")
    return value


def _get(sub: str, q: dict):
    def first(key, default=""):
        return q.get(key, [default])[0]

    if sub == "api/status":
        db = STATE["db"]
        return _json({"ok": True, "loaded": db is not None, "summary": db.summary() if db else None})
    if sub == "api/meta":
        return _json({"ok": True, **_db().metadata()})
    if sub == "api/players":
        result = _db().search(first("q"), q.get("team", [None])[0], first("table"), first("page", 1), first("limit", 80))
        return _json({"ok": True, **result})
    if sub == "api/player":
        return _json({"ok": True, "player": _db().get_player(first("key"))})
    if sub == "api/team":
        return _json({"ok": True, "lineup": _db().get_team_lineup(first("team_id"))})
    if sub == "api/team/details":
        return _json({"ok": True, "team": _db().get_team_details(first("team_id"))})
    if sub == "api/team-import/status":
        source = STATE["import_db"]
        if source is None:
            return _json({"ok": True, "loaded": False})
        assert isinstance(source, DatabaseManager)
        return _json({"ok": True, "loaded": True, "summary": source.summary(), "club_teams": _club_teams(source)})
    if sub == "api/team-import/preview":
        source = STATE["import_db"]
        if source is None:
            raise ValueError("Primero carga la database externa")
        assert isinstance(source, DatabaseManager)
        return _json({"ok": True, "preview": _db().preview_team_import(source, first("source_team_id"), first("target_team_id"))})
    if sub == "api/team-assets/status":
        return _json({"ok": True, "status": _assets().status()})
    if sub == "api/team-assets/export":
        team_id = int(first("team_id", "0"))
        db = _db()
        team = db.get_team_details(team_id)
        path, filename, _result = _assets().build_package(team_id, team["name"])
        data = path.read_bytes()
        return _reply(200, data, "application/zip", {"content-disposition": f'attachment; filename="{re_safe(filename)}"'})
    if sub == "api/callup-candidates":
        return _json({"ok": True, **_db().search_callup_candidates(first("team_id"), first("q"), first("limit", 80))})
    if sub == "api/available-ids":
        return _json({"ok": True, **_db().available_ids()})
    if sub == "api/export":
        db = _db()
        data = db.export()
        filename = re_safe(Path(db.source_name).stem + "_EDITADO.cpk")
        return _reply(200, data, BIN_TYPE, {"content-disposition": f'attachment; filename="{filename}"'})
    return _reply(404, b"Not found", "text/plain")


def _post(sub: str, headers: dict, body: bytes):
    if sub == "api/load":
        if not body:
            raise ValueError("El archivo está vacío")
        name = _unquote(headers, "x-file-name", "Resource_02.cpk")
        STATE["db"] = DatabaseManager(body, name)
        STATE["import_db"] = None
        return _json({"ok": True, **STATE["db"].metadata()})  # type: ignore[union-attr]
    if sub == "api/team-import/load":
        if not body:
            raise ValueError("El archivo está vacío")
        name = _unquote(headers, "x-file-name", "Resource_02_EXTERNA.cpk")
        source = DatabaseManager(body, name)
        STATE["import_db"] = source
        return _json({"ok": True, "loaded": True, "summary": source.summary(), "club_teams": _club_teams(source)})
    if sub == "api/team-import/clear":
        STATE["import_db"] = None
        return _json({"ok": True, "loaded": False})
    if sub == "api/team-assets/source/reset":
        return _json({"ok": True, "status": _assets().reset_source()})
    if sub == "api/team-assets/source/file":
        relative = _unquote(headers, "x-relative-path")
        incoming = _body_to_temp(body, 128 * 1024 * 1024)
        try:
            status = _assets().add_source_file(relative, incoming)
        finally:
            incoming.unlink(missing_ok=True)
        return _json({"ok": True, "status": status})
    if sub == "api/team-assets/logo":
        variant = headers.get("x-logo-variant", "")
        incoming = _body_to_temp(body, 16 * 1024 * 1024)
        try:
            status = _assets().set_logo(variant, incoming)
        finally:
            incoming.unlink(missing_ok=True)
        return _json({"ok": True, "status": status})
    if sub == "api/team-assets/target-cpk":
        name = _unquote(headers, "x-file-name", "Destiny_Kits.cpk")
        incoming = _body_to_temp(body, 1024 * 1024 * 1024)
        try:
            status = _assets().set_target_cpk(incoming, name)
        finally:
            incoming.unlink(missing_ok=True)
        return _json({"ok": True, "status": status})
    if sub == "api/team-assets/target-folder":
        raise ValueError("Elegir una carpeta de destino solo funciona en la versión de PC (Windows). En el celular usa el paquete de kits como archivo CPK.")
    if sub == "api/team-assets/target-clear":
        return _json({"ok": True, "status": _assets().clear_target_cpk()})
    if sub == "api/team-assets/target-folder-clear":
        return _json({"ok": True, "status": _assets().clear_target_folder()})
    if sub == "api/shutdown":
        STATE["db"] = None
        STATE["import_db"] = None
        return _json({"ok": True})

    payload = _payload(body)
    db = _db()
    if sub == "api/save":
        player = db.save_player(payload.get("key"), payload.get("values") or {})
    elif sub == "api/transfer":
        player = db.transfer(payload.get("key"), payload.get("assignment_key"), payload.get("team_id"), payload.get("shirt_number"), payload.get("squad_order"))
    elif sub == "api/release":
        player = db.release_player(payload.get("key"), payload.get("assignment_key"), bool(payload.get("allow_below_minimum", False)))
        result = {"ok": True, "player": player, "summary": db.summary()}
        if payload.get("team_id") not in (None, ""):
            result["lineup"] = db.get_team_lineup(payload.get("team_id"))
        return _json(result)
    elif sub == "api/create":
        player = db.create_player(payload.get("new_id"), payload.get("template_key"), payload.get("values") or {}, payload.get("team_id"), payload.get("shirt_number"))
    elif sub == "api/replace":
        player = db.replace_slot(payload.get("target_key"), payload.get("template_key"), payload.get("values") or {}, bool(payload.get("copy_appearance", True)))
    elif sub == "api/team/autosort":
        result = db.autosort_preview(payload.get("team_id"), payload.get("preset_name") or "")
        return _json({"ok": True, **result, "summary": db.summary()})
    elif sub == "api/team/save":
        lineup = db.save_lineup(payload.get("team_id"), payload.get("ordered_assignment_keys") or [], payload.get("preset_name") or "")
        return _json({"ok": True, "lineup": lineup, "summary": db.summary()})
    elif sub == "api/team/shirt":
        lineup = db.change_assignment_shirt(payload.get("team_id"), payload.get("assignment_key"), payload.get("shirt_number"))
        return _json({"ok": True, "lineup": lineup, "summary": db.summary()})
    elif sub == "api/team/replace-slot":
        team = db.replace_team_slot(payload.get("team_id"), payload.get("name"), payload.get("abbreviation"))
        return _json({"ok": True, "team": team, **db.metadata()})
    elif sub == "api/team-import/apply":
        source = STATE["import_db"]
        if source is None:
            raise ValueError("Primero carga la database externa")
        assert isinstance(source, DatabaseManager)
        result = db.import_team(source, payload.get("source_team_id"), payload.get("target_team_id"))
        return _json({"ok": True, **result, **db.metadata()})
    elif sub == "api/callup":
        lineup = db.call_up(payload.get("team_id"), payload.get("player_key"), payload.get("shirt_number"), bool(payload.get("allow_mismatch", False)))
        return _json({"ok": True, "lineup": lineup, "summary": db.summary()})
    elif sub == "api/callup/remove":
        lineup = db.remove_callup(payload.get("team_id"), payload.get("assignment_key"))
        return _json({"ok": True, "lineup": lineup, "summary": db.summary()})
    elif sub == "api/undo":
        return _json({"ok": True, **db.undo()})
    else:
        return _reply(404, b"Not found", "text/plain")
    return _json({"ok": True, "player": player, "summary": db.summary()})


def handle(method: str, path: str, headers, body):
    """Punto de entrada único. Devuelve (json con status y cabeceras, bytes)."""
    try:
        if isinstance(headers, str):          # el worker de JS envía las cabeceras como JSON
            headers = json.loads(headers or "{}")
        headers = dict(headers or {})
        if body is None:
            raw = b""
        elif hasattr(body, "to_bytes"):       # Uint8Array de JavaScript (JsProxy) dentro de Pyodide
            raw = body.to_bytes()
        else:
            raw = bytes(body)
        parts = urllib.parse.urlsplit(path)
        sub = parts.path.lstrip("/")
        if method == "GET":
            code, out_headers, out_body = _get(sub, urllib.parse.parse_qs(parts.query))
        else:
            code, out_headers, out_body = _post(sub, headers, raw)
    except (ValueError, KeyError, TypeError) as exc:
        code, out_headers, out_body = _error(exc)
    except Exception as exc:  # error inesperado: se muestra la causa porque en el celular no hay log
        traceback.print_exc()
        code, out_headers, out_body = _error(RuntimeError(f"Error interno: {exc.__class__.__name__}: {exc}"), 500)
    return json.dumps({"status": code, "headers": out_headers}), out_body
