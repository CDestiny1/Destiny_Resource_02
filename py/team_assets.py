"""Team kit/logo package builder for DFP Database Manager.

The browser uploads source folders one file at a time so large kit packs do not
need to live in RAM.  The builder always creates a non-destructive ZIP overlay;
when an existing kit CPK is supplied it additionally replaces every matching
entry that already exists in that archive and verifies the rebuilt CPK.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import tempfile
import time
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from archive import CPK


KIT_ROOT = PurePosixPath("common/character0/model/character/uniform/team")
LOGO_ROOT = PurePosixPath("common/render/symbol/flag")
SLOT_RE = re.compile(r"(?<![a-z0-9])([pg][1-9])(?![a-z0-9])", re.I)
UNIFORM_CODE_RE = re.compile(rb"u([0-9]{4,6})([pg][1-9])", re.I)
MAX_SOURCE_TOTAL = 768 * 1024 * 1024


def _safe_relative(value: str) -> PurePosixPath:
    value = (value or "").replace("\\", "/").lstrip("/")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or ":" in value or "\0" in value:
        raise ValueError("Ruta de kit no válida")
    return path


def _fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value or "") if not unicodedata.combining(c)).casefold()


def _slot_for(path: PurePosixPath) -> str | None:
    for part in path.parts:
        if re.fullmatch(r"[pg][1-9]", part, re.I):
            return part.lower()
    match = re.search(r"u[0-9]{3,6}([pg][1-9])", path.name, re.I)
    if match:
        return match.group(1).lower()
    match = SLOT_RE.search(path.stem)
    return match.group(1).lower() if match else None


def _rename_component(value: str, team_id: int) -> str:
    target = f"{team_id:04d}"
    return re.sub(r"(?i)u[0-9]{3,6}(?=[pg][1-9])", "u" + target, value)


class TeamAssetWorkspace:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="DFP_TEAM_ASSETS_")
        self.root = Path(self._tmp.name)
        self.source_root = self.root / "source"
        self.logo_root = self.root / "logos"
        self.source_root.mkdir(); self.logo_root.mkdir()
        self.source_files: dict[str, Path] = {}
        self.logo_files: dict[str, Path] = {}
        self.source_bytes = 0
        self.target_cpk_path: Path | None = None
        self.target_cpk_name = ""
        self.target_folder: Path | None = None

    def reset_source(self) -> dict[str, Any]:
        shutil.rmtree(self.source_root, ignore_errors=True)
        self.source_root.mkdir()
        self.source_files.clear(); self.source_bytes = 0
        return self.status()

    def add_source_file(self, relative: str, incoming: Path) -> dict[str, Any]:
        rel = _safe_relative(relative)
        size = incoming.stat().st_size
        previous = self.source_files.get(rel.as_posix())
        previous_size = previous.stat().st_size if previous and previous.exists() else 0
        if self.source_bytes - previous_size + size > MAX_SOURCE_TOTAL:
            raise ValueError("La carpeta de kits supera el límite de seguridad de 768 MB")
        out = self.source_root.joinpath(*rel.parts)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(incoming), out)
        self.source_files[rel.as_posix()] = out
        self.source_bytes += size - previous_size
        return self.status()

    def set_logo(self, variant: str, incoming: Path) -> dict[str, Any]:
        if variant not in {"r", "r_l", "r_ll"}:
            raise ValueError("Variante de logo no válida")
        raw = incoming.read_bytes()
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("El logo generado no es PNG")
        out = self.logo_root / f"{variant}.png"
        shutil.move(str(incoming), out)
        self.logo_files[variant] = out
        return self.status()

    def set_target_cpk(self, incoming: Path, name: str) -> dict[str, Any]:
        # Parse immediately: a false/unsupported CPK must never look loaded.
        raw = incoming.read_bytes()
        archive = CPK(raw)
        if not any("/uniform/team/" in ("/" + e["path"].casefold()) for e in archive.entries):
            raise ValueError("Ese CPK no contiene la carpeta uniform/team")
        out = self.root / "kit_target.cpk"
        shutil.move(str(incoming), out)
        self.target_cpk_path = out
        self.target_cpk_name = re.sub(r"[^A-Za-z0-9_.() -]", "_", name or "Kits.cpk")[:120]
        return self.status()

    def clear_target_cpk(self) -> dict[str, Any]:
        if self.target_cpk_path:
            self.target_cpk_path.unlink(missing_ok=True)
        self.target_cpk_path = None; self.target_cpk_name = ""
        return self.status()

    def set_target_folder(self, folder: str | Path) -> dict[str, Any]:
        root = Path(folder).resolve()
        if not root.is_dir():
            raise ValueError("La carpeta de destino no existe")
        # Accept either the extracted CPK root or the uniform/team folder.
        direct = root / Path(KIT_ROOT.as_posix())
        if direct.is_dir():
            base = root
        elif root.as_posix().casefold().endswith(KIT_ROOT.as_posix().casefold()):
            base = root
            for _ in KIT_ROOT.parts:
                base = base.parent
        else:
            raise ValueError("No encontré common/character0/model/character/uniform/team dentro de esa carpeta")
        self.target_folder = base
        return self.status()

    def clear_target_folder(self) -> dict[str, Any]:
        self.target_folder = None
        return self.status()

    def status(self) -> dict[str, Any]:
        slots: dict[str, int] = {}
        ignored = 0
        for relative in self.source_files:
            slot = _slot_for(PurePosixPath(relative))
            if slot: slots[slot] = slots.get(slot, 0) + 1
            else: ignored += 1
        return {
            "source_files": len(self.source_files), "source_bytes": self.source_bytes,
            "slots": slots, "ignored": ignored,
            "logo_variants": sorted(self.logo_files),
            "target_cpk": self.target_cpk_name or None,
            "target_cpk_bytes": self.target_cpk_path.stat().st_size if self.target_cpk_path else 0,
            "target_folder": str(self.target_folder) if self.target_folder else None,
        }

    def _kit_outputs(self, team_id: int) -> tuple[dict[str, bytes], list[str]]:
        outputs: dict[str, bytes] = {}
        ignored: list[str] = []
        old_codes: set[tuple[bytes, bytes]] = set()
        for relative in self.source_files:
            raw_name = relative.encode("utf-8", "ignore")
            for match in UNIFORM_CODE_RE.finditer(raw_name):
                old_codes.add((match.group(1), match.group(2).lower()))

        for relative, disk_path in self.source_files.items():
            source_rel = PurePosixPath(relative)
            slot = _slot_for(source_rel)
            if not slot:
                ignored.append(relative); continue
            # PES CPK does not keep p1/p2/p3/g1/g2 as subdirectories here.
            # Those folders merely separate the downloaded kit slots. Their
            # CONTENTS are flattened together into uniform/team/<Team ID>/.
            destination_name = _rename_component(source_rel.name, team_id)
            destination = (KIT_ROOT / str(team_id) / destination_name).as_posix()
            payload = disk_path.read_bytes()
            for old_id, old_slot in old_codes:
                source_code = b"u" + old_id + old_slot
                target_id = str(team_id).zfill(len(old_id)).encode("ascii")
                target_code = b"u" + target_id + old_slot
                if len(source_code) == len(target_code):
                    payload = re.sub(re.escape(source_code), target_code, payload, flags=re.I)
            if destination.casefold() in {key.casefold() for key in outputs}:
                raise ValueError("Dos archivos de origen producen la misma ruta: " + destination)
            outputs[destination] = payload
        return outputs, ignored

    def build_package(self, team_id: int, team_name: str) -> tuple[Path, str, dict[str, Any]]:
        team_id = int(team_id)
        if team_id <= 0: raise ValueError("Selecciona un equipo válido")
        if not self.source_files and not self.logo_files:
            raise ValueError("Carga una carpeta de kits o un logo")
        kit_files, ignored = self._kit_outputs(team_id)
        logo_files = {
            (LOGO_ROOT / f"e_{team_id:06d}_{variant}.png").as_posix(): path.read_bytes()
            for variant, path in self.logo_files.items()
        }
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", _fold(team_name).replace(" ", "_"))[:60] or f"team_{team_id}"
        package_path = self.root / f"DFP_TEAM_{team_id}_{safe_name}.zip"
        replaced: list[str] = []; missing_in_cpk: list[str] = []
        rebuilt_name = ""
        folder_applied = 0; folder_backup = ""

        if self.target_folder:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            backup_root = self.target_folder.with_name(self.target_folder.name + "_DFP_BACKUP_" + stamp)
            for path, payload in {**kit_files, **logo_files}.items():
                destination = self.target_folder.joinpath(*PurePosixPath(path).parts)
                if destination.exists():
                    backup = backup_root.joinpath(*PurePosixPath(path).parts)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup)
                    folder_backup = str(backup_root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(destination.name + ".dfp_tmp")
                temporary.write_bytes(payload); os.replace(temporary, destination)
                folder_applied += 1

        with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
            for path, payload in {**kit_files, **logo_files}.items():
                bundle.writestr("COPIAR_SOBRE_CPK_EXTRAIDO/" + path, payload)

            if self.target_cpk_path and kit_files:
                original = self.target_cpk_path.read_bytes()
                archive = CPK(original)
                replacements: dict[str, bytes] = {}
                by_lower = {e["path"].casefold(): e for e in archive.entries}
                for path, payload in kit_files.items():
                    entry = by_lower.get(path.casefold())
                    if entry:
                        replacements[entry["path"]] = payload; replaced.append(entry["path"])
                    else:
                        missing_in_cpk.append(path)
                if replacements:
                    rebuilt = archive.rebuild(replacements)
                    rebuilt_name = Path(self.target_cpk_name).stem + "_EDITADO.cpk"
                    bundle.writestr(rebuilt_name, rebuilt)

            report = [
                "DFP TEAM & KIT MANAGER V3", "=" * 31,
                f"Equipo: {team_name}", f"Team ID: {team_id}",
                f"Archivos de kit preparados: {len(kit_files)}",
                f"Logos preparados: {len(logo_files)}",
                f"CPK de kits: {self.target_cpk_name or 'no cargado (modo carpeta/overlay)'}",
                f"Reemplazados dentro del CPK: {len(replaced)}",
                f"Nuevos/no existentes en ese CPK: {len(missing_in_cpk)}",
                f"Aplicados a carpeta extraída: {folder_applied}",
                f"Backup de carpeta: {folder_backup or 'no fue necesario'}",
                "",
                "IMPORTANTE:",
                "- El CPK original nunca se modifica.",
                "- COPIAR_SOBRE_CPK_EXTRAIDO contiene todos los kits y logos.",
                "- Un CPK solo puede recibir directamente rutas que ya existían en él.",
                "- Las rutas nuevas quedan en el overlay para añadirlas al reempaquetar la carpeta.",
            ]
            if ignored:
                report += ["", "ARCHIVOS SIN SLOT DETECTABLE (omitidos):", *ignored]
            if missing_in_cpk:
                report += ["", "RUTAS NUEVAS PARA EL CPK EXTRAÍDO:", *missing_in_cpk]
            bundle.writestr("LEEME_RESULTADO.txt", "\r\n".join(report).encode("utf-8"))

        result = {
            "kit_files": len(kit_files), "logo_files": len(logo_files), "ignored": len(ignored),
            "cpk_replaced": len(replaced), "cpk_missing": len(missing_in_cpk),
            "rebuilt_cpk": rebuilt_name or None,
            "folder_applied": folder_applied, "folder_backup": folder_backup or None,
        }
        return package_path, package_path.name, result
