"""PES 2021 / Destiny Football Project database editing core.

The module intentionally uses only Python's standard library.  Every mutation is
transactional, undoable and validated again after the rebuilt CPK is produced.
"""
from __future__ import annotations

import copy
import re
import struct
import unicodedata
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from archive import CPK, unwrap, wrap


PLAYER_SIZE = 312
APPEARANCE_SIZE = 60
ASSIGNMENT_SIZE = 16
TEAM_SIZE = 1532
COUNTRY_SIZE = 1420
FORMATION_SIZE = 792
TEAM_NAME_OFFSETS = (88, 368, 962)
TEAM_ABBR_OFFSETS = (882, 1382)

PATHS = {
    "Player": "common/etc/pesdb/Player.bin",
    "Player4": "common/etc/pesdb/Player4.bin",
    "PlayerAppearance": "common/character0/model/character/appearance/PlayerAppearance.bin",
    "PlayerAssignment": "common/etc/pesdb/PlayerAssignment.bin",
    "PlayerAssignment4": "common/etc/pesdb/PlayerAssignment4.bin",
    "Team": "common/etc/pesdb/Team.bin",
    "Team4": "common/etc/pesdb/Team4.bin",
    "Country": "common/etc/pesdb/Country.bin",
    "TacticsFormation": "common/etc/pesdb/TacticsFormation.bin",
    "TacticsFormation4": "common/etc/pesdb/TacticsFormation4.bin",
}

# Bit offsets are measured from the first bit of a 312-byte Player record,
# least-significant bit first.  Values with a bias are shown naturally in UI.
FIELDS = {
    "nationality": (233, 9, 0),
    "height": (216, 8, 100),
    "weight": (256, 7, 30),
    "age": (408, 6, 15),
    "position": (434, 4, 0),
    "form": (438, 3, 1),
    "weak_use": (454, 2, 1),
    "weak_accuracy": (462, 2, 1),
    "injury_resistance": (458, 2, 1),
    "playing_attitude": (382, 2, 0),
    "strong_foot": (514, 1, 0),
}

STATS = {
    "offensive_awareness": (370, 6, 40),
    "ball_control": (281, 6, 40),
    "dribbling": (352, 6, 40),
    "tight_possession": (416, 6, 40),
    "low_pass": (263, 6, 40),
    "lofted_pass": (402, 6, 40),
    "finishing": (396, 6, 40),
    "heading": (288, 6, 40),
    "place_kicking": (250, 6, 40),
    "curl": (332, 6, 40),
    "speed": (306, 6, 40),
    "acceleration": (344, 6, 40),
    "kicking_power": (358, 6, 40),
    "jump": (294, 6, 40),
    "physical_contact": (390, 6, 40),
    "balance": (376, 6, 40),
    "stamina": (338, 6, 40),
    "defensive_awareness": (275, 6, 40),
    "ball_winning": (312, 6, 40),
    "aggression": (384, 6, 40),
    "gk_awareness": (326, 6, 40),
    "gk_catching": (364, 6, 40),
    "gk_clearing": (269, 6, 40),
    "gk_reflexes": (320, 6, 40),
    "gk_reach": (300, 6, 40),
}

PLAYABLE = {
    "GK": (350, 2), "CB": (468, 2), "LB": (318, 2), "RB": (474, 2),
    "DMF": (414, 2), "CMF": (456, 2), "LMF": (466, 2), "RMF": (460, 2),
    "AMF": (464, 2), "LWF": (472, 2), "RWF": (476, 2), "SS": (478, 2),
    "CF": (470, 2),
}

POSITION_NAMES = ["PT", "DFC", "LI", "LD", "MCD", "MC", "MI", "MD", "MCO", "EI", "ED", "SD", "DC"]
POSITION_CODES = ["GK", "CB", "LB", "RB", "DMF", "CMF", "LMF", "RMF", "AMF", "LWF", "RWF", "SS", "CF"]

# (registered position, horizontal coordinate, vertical coordinate).  These
# values follow PES' native 104x46 formation grid and are written without
# altering the formation identifiers or slot markers.
FORMATION_PRESETS = {
    "4-3-3": [(0,52,3),(3,88,12),(1,64,11),(1,40,11),(2,16,12),(4,52,19),(5,68,27),(5,36,27),(10,84,42),(9,20,42),(12,52,43)],
    "4-2-3-1": [(0,52,3),(3,88,12),(1,64,11),(1,40,11),(2,16,12),(4,64,19),(4,40,19),(7,84,31),(6,20,31),(8,52,35),(12,52,43)],
    "4-4-2": [(0,52,3),(3,88,12),(1,64,11),(1,40,11),(2,16,12),(7,84,27),(5,64,24),(5,40,24),(6,20,27),(12,64,43),(12,40,43)],
    "4-1-4-1": [(0,52,3),(3,88,12),(1,64,11),(1,40,11),(2,16,12),(4,52,18),(7,84,29),(5,64,27),(5,40,27),(6,20,29),(12,52,43)],
    "3-4-3": [(0,52,3),(1,76,12),(1,52,10),(1,28,12),(7,88,26),(5,64,23),(5,40,23),(6,16,26),(10,84,42),(12,52,43),(9,20,42)],
    "3-5-2": [(0,52,3),(1,76,12),(1,52,10),(1,28,12),(4,52,18),(7,88,29),(5,66,27),(5,38,27),(6,16,29),(12,64,43),(12,40,43)],
    "5-3-2": [(0,52,3),(3,92,18),(1,72,11),(1,52,9),(1,32,11),(2,12,18),(5,72,27),(4,52,22),(5,32,27),(12,64,43),(12,40,43)],
}

POSITION_STAT_GROUPS = {
    0: ["gk_awareness","gk_catching","gk_clearing","gk_reflexes","gk_reach","jump"],
    1: ["defensive_awareness","ball_winning","physical_contact","jump","heading","speed"],
    2: ["speed","acceleration","stamina","defensive_awareness","ball_winning","lofted_pass","low_pass"],
    3: ["speed","acceleration","stamina","defensive_awareness","ball_winning","lofted_pass","low_pass"],
    4: ["defensive_awareness","ball_winning","physical_contact","stamina","low_pass","lofted_pass","ball_control"],
    5: ["low_pass","lofted_pass","ball_control","tight_possession","stamina","defensive_awareness"],
    6: ["speed","acceleration","dribbling","low_pass","lofted_pass","stamina","ball_control"],
    7: ["speed","acceleration","dribbling","low_pass","lofted_pass","stamina","ball_control"],
    8: ["ball_control","dribbling","tight_possession","low_pass","lofted_pass","offensive_awareness","finishing"],
    9: ["speed","acceleration","dribbling","tight_possession","offensive_awareness","finishing","curl"],
    10:["speed","acceleration","dribbling","tight_possession","offensive_awareness","finishing","curl"],
    11:["ball_control","tight_possession","offensive_awareness","finishing","low_pass","dribbling"],
    12:["finishing","offensive_awareness","ball_control","physical_contact","heading","kicking_power"],
}

# PES internal IDs.  Gaps are intentional and must not be compacted.
_COUNTRY_ROWS = """
0|Ninguna
1|Afganistán
2|Baréin
3|Bangladés
4|Bután
5|Brunéi
6|Camboya
7|China
8|Hong Kong
9|India
10|Indonesia
11|Irán
12|Irak
13|Japón
14|Jordania
15|Corea del Norte
16|Corea del Sur
17|Kuwait
18|Laos
19|Líbano
20|Macao
21|Malasia
22|Maldivas
23|Mongolia
24|Myanmar
25|Nepal
26|Omán
27|Pakistán
28|Palestina
29|Filipinas
30|Catar
31|Arabia Saudita
32|Singapur
33|Sri Lanka
34|Siria
36|Tailandia
37|Emiratos Árabes Unidos
38|Vietnam
39|Yemen
40|Kirguistán
41|Tayikistán
42|Turkmenistán
43|Timor Oriental
44|Argelia
45|Angola
46|Benín
47|Botsuana
48|Burkina Faso
49|Burundi
50|Camerún
51|Cabo Verde
52|República Centroafricana
53|Chad
54|Comoras
55|RD del Congo
56|Costa de Marfil
57|Yibuti
58|Egipto
59|Guinea Ecuatorial
60|Eritrea
61|Etiopía
62|Gabón
63|Gambia
64|Ghana
65|Guinea
66|Guinea-Bisáu
67|Kenia
68|Lesoto
69|Liberia
70|Libia
71|Madagascar
72|Malaui
73|Malí
74|Mauritania
75|Mauricio
76|Marruecos
77|Mozambique
78|Namibia
79|Níger
80|Nigeria
81|Ruanda
82|Santo Tomé y Príncipe
83|Senegal
84|Seychelles
85|Sierra Leona
86|Somalia
87|Sudáfrica
88|Sudán
89|Esuatini
90|Tanzania
91|Togo
92|Túnez
93|Uganda
94|Zambia
95|Zimbabue
98|Congo
100|Reunión
103|Anguila
104|Antigua y Barbuda
105|Aruba
106|Bahamas
107|Barbados
108|Belice
109|Bermudas
110|Canadá
111|Islas Caimán
112|Costa Rica
113|Cuba
114|Dominica
115|República Dominicana
116|El Salvador
117|Granada
118|Guadalupe
119|Guatemala
120|Haití
121|Honduras
122|Jamaica
123|Martinica
124|México
125|Montserrat
126|Antillas Neerlandesas
127|Nicaragua
128|Panamá
129|Puerto Rico
130|San Cristóbal y Nieves
131|Santa Lucía
132|San Vicente y las Granadinas
133|Trinidad y Tobago
134|Islas Turcas y Caicos
135|Estados Unidos
136|Islas Vírgenes Británicas
137|Islas Vírgenes de EE. UU.
138|Guayana Francesa
139|Surinam
140|Curazao
144|Argentina
145|Bolivia
146|Brasil
147|Chile
148|Colombia
149|Ecuador
150|Paraguay
151|Perú
152|Uruguay
153|Venezuela
159|Guyana
161|Samoa Americana
162|Australia
163|Islas Cook
164|Fiyi
165|Nueva Caledonia
166|Nueva Zelanda
167|Papúa Nueva Guinea
168|Samoa
169|Islas Salomón
170|Tahití
171|Tonga
172|Vanuatu
176|Guam
184|Palaos
189|Israel
190|Turquía
191|Albania
192|Andorra
193|Armenia
194|Austria
195|Azerbaiyán
196|Bielorrusia
197|Bélgica
198|Bosnia y Herzegovina
199|Bulgaria
200|Croacia
201|Chipre
202|República Checa
203|Dinamarca
204|Inglaterra
205|Estonia
206|Islas Feroe
207|Finlandia
208|Francia
209|Georgia
210|Alemania
211|Grecia
212|Hungría
213|Islandia
214|Irlanda
215|Italia
216|Kazajistán
217|Letonia
218|Liechtenstein
219|Lituania
220|Luxemburgo
221|Macedonia del Norte
222|Malta
223|Moldavia
224|Países Bajos
225|Irlanda del Norte
226|Noruega
227|Polonia
228|Portugal
229|Rumanía
230|Rusia
231|San Marino
232|Escocia
234|Eslovaquia
235|Eslovenia
236|España
237|Suecia
238|Suiza
239|Ucrania
240|Uzbekistán
241|Gales
245|Gibraltar
250|Mónaco
260|Otros
298|Taiwán
303|Serbia
304|Montenegro
310|Sint Maarten
311|Kosovo
312|Sudán del Sur
"""
COUNTRIES = {int(row.split("|", 1)[0]): row.split("|", 1)[1] for row in _COUNTRY_ROWS.strip().splitlines()}


def _u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _get_bits(data: bytes | bytearray, bit: int, width: int) -> int:
    value = 0
    for i in range(width):
        value |= ((data[(bit + i) >> 3] >> ((bit + i) & 7)) & 1) << i
    return value


def _set_bits(data: bytearray, bit: int, width: int, value: int) -> None:
    if value < 0 or value >= (1 << width):
        raise ValueError("Valor fuera del formato interno")
    for i in range(width):
        pos = bit + i
        mask = 1 << (pos & 7)
        if (value >> i) & 1:
            data[pos >> 3] |= mask
        else:
            data[pos >> 3] &= ~mask


def _read_text(record: bytes | bytearray, offset: int, length: int = 61) -> str:
    return bytes(record[offset:offset + length]).split(b"\0", 1)[0].decode("utf-8", "replace").strip()


def _write_text(record: bytearray, offset: int, value: str, length: int = 61) -> None:
    value = " ".join(str(value).strip().split())
    encoded = value.encode("utf-8")
    if not value:
        raise ValueError("El nombre no puede quedar vacío")
    if len(encoded) >= length:
        raise ValueError(f"El texto supera {length - 1} bytes UTF-8")
    record[offset:offset + length] = encoded + b"\0" * (length - len(encoded))


@lru_cache(maxsize=200_000)
def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text).casefold() if not unicodedata.combining(c))


def _name_key(text: str) -> str:
    """Stable comparison key for player names from independently edited patches."""
    return re.sub(r"[^a-z0-9]", "", _fold(text))


def _int(value: Any, name: str, lo: int, hi: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name}: se esperaba un número") from None
    if not lo <= result <= hi:
        raise ValueError(f"{name}: debe estar entre {lo} y {hi}")
    return result


@dataclass
class Change:
    table: str
    start: int
    old: bytes
    new: bytes


class DatabaseManager:
    """Loaded database plus transactional editing operations."""

    def __init__(self, cpk_bytes: bytes, source_name: str = "Resource_02.cpk"):
        if len(cpk_bytes) > 64 * 1024 * 1024:
            raise ValueError("El CPK supera el límite de seguridad de 64 MB")
        self.source_name = re.sub(r"[^A-Za-z0-9_.() -]", "_", source_name)[:120] or "Resource_02.cpk"
        self.source_bytes = bytes(cpk_bytes)
        self.cpk = CPK(self.source_bytes)
        self.tables: dict[str, bytearray] = {}
        self.original: dict[str, bytes] = {}
        self.headers: dict[str, bytes] = {}
        self.paths: dict[str, str] = {}
        self.history: list[tuple[str, list[Change]]] = []
        self.activity: list[str] = []
        self.dirty: set[str] = set()
        self._load_tables()
        self._reindex()
        self.activity.append("Resource_02 cargado y validado")

    def _load_tables(self) -> None:
        expected = {
            "Player": PLAYER_SIZE, "Player4": PLAYER_SIZE,
            "PlayerAppearance": APPEARANCE_SIZE,
            "PlayerAssignment": ASSIGNMENT_SIZE, "PlayerAssignment4": ASSIGNMENT_SIZE,
            "Team": TEAM_SIZE, "Team4": TEAM_SIZE,
            "Country": COUNTRY_SIZE,
            "TacticsFormation": FORMATION_SIZE, "TacticsFormation4": FORMATION_SIZE,
        }
        for key, wanted in PATHS.items():
            entry = self.cpk.by_name.get(wanted.casefold())
            if not entry:
                raise ValueError("Falta una tabla imprescindible: " + wanted)
            raw, header = unwrap(self.cpk.read(entry))
            if len(raw) % expected[key]:
                raise ValueError(f"{key}.bin tiene un tamaño incompatible")
            self.tables[key] = bytearray(raw)
            self.original[key] = bytes(raw)
            self.headers[key] = header
            self.paths[key] = entry["path"]

    def _reindex(self) -> None:
        self.players: dict[str, tuple[str, int]] = {}
        self.by_pid: dict[int, list[str]] = {}
        self.player_rows: list[dict[str, Any]] = []
        for table in ("Player", "Player4"):
            data = self.tables[table]
            for offset in range(0, len(data), PLAYER_SIZE):
                pid = _u32(data, offset + 8)
                key = f"{table}:{pid}"
                if key in self.players:
                    raise ValueError(f"ID de jugador duplicado dentro de {table}: {pid}")
                self.players[key] = (table, offset)
                self.by_pid.setdefault(pid, []).append(key)

        self.appearances: dict[int, int] = {}
        data = self.tables["PlayerAppearance"]
        for offset in range(0, len(data), APPEARANCE_SIZE):
            self.appearances[_u32(data, offset)] = offset

        self._build_assignments()

        # Build a multilingual country-name set from Country.bin.  It lets us
        # distinguish national selections from clubs without relying only on
        # fragile numeric ID ranges.
        country_names: set[str] = set()
        country_alias_to_id: dict[str, int] = {}
        static_country_ids = {_fold(name): country_id for country_id, name in COUNTRIES.items()}
        static_country_ids.update({"usa": 135, "united states": 135, "turkiye": 190, "turkey": 190})
        team_country_overrides = {
            "usa": 135, "south korea": 16, "north korea": 15, "qatar": 30,
            "cape verde": 51, "dr congo": 55, "bosnia and herzegovina": 198,
        }
        country_data = self.tables["Country"]
        for base in range(0, len(country_data), COUNTRY_SIZE):
            record = country_data[base:base + COUNTRY_SIZE]
            aliases: list[str] = []
            for text_offset in range(78, COUNTRY_SIZE, 70):
                value = _fold(_read_text(record, text_offset, 70))
                if len(value) > 3:  # avoid 3-letter country-code/club collisions
                    country_names.add(value)
                    aliases.append(value)
            country_id = next((static_country_ids[name] for name in aliases if name in static_country_ids), None)
            if country_id is not None:
                for alias in aliases:
                    country_alias_to_id[alias] = country_id

        self.teams: dict[int, dict[str, Any]] = {}
        for table in ("Team", "Team4"):
            data = self.tables[table]
            for offset in range(0, len(data), TEAM_SIZE):
                tid = _u32(data, offset + 8)
                name = _read_text(data[offset:offset + TEAM_SIZE], 368, 70) or f"Equipo {tid}"
                folded = _fold(name)
                classic = folded.startswith("classic ") and (
                    folded[8:] in country_names or
                    any(folded[8:].startswith(country + " ") for country in country_names)
                )
                is_selection = (
                    tid < 100 or 1010 <= tid <= 1184 or folded in country_names or
                    classic or folded == "classic usa"
                )
                country_key = folded[8:] if folded.startswith("classic ") else folded
                nationality_id = country_alias_to_id.get(country_key) or static_country_ids.get(country_key) or team_country_overrides.get(country_key)
                if nationality_id is None and country_key.startswith("brazil "): nationality_id = 146
                if nationality_id is None and folded == "classic usa": nationality_id = 135
                self.teams.setdefault(tid, {
                    "id": tid, "name": name, "table": table,
                    "index": offset // TEAM_SIZE,
                    "kind": "selection" if is_selection else "club",
                    "nationality_id": nationality_id if is_selection else None,
                })

        # Los 312 bytes de un jugador determinan sus nombres/posición/texto de
        # búsqueda.  Tras cada operación casi ningún registro cambia, así que
        # se reutiliza lo ya calculado en vez de decodificar 31 000 jugadores.
        record_cache = self.__dict__.setdefault("_record_cache", {})
        row_base: dict[str, str] = {}
        self._row_base = row_base
        for key, (table, offset) in self.players.items():
            pid = int(key.split(":", 1)[1])
            record = bytes(self.tables[table][offset:offset + PLAYER_SIZE])
            info = self._player_info(record, pid)
            game_name, shirt_name, full_name, localized_name, name, position_name, base_search = info
            row_base[key] = base_search
            assignment_table = "PlayerAssignment4" if table == "Player4" else "PlayerAssignment"
            matching = [(t, o) for t, o in self.assignments.get(pid, []) if t == assignment_table]
            team_ids = [_u32(self.tables[t], o + 8) for t, o in matching]
            team_names = [self.teams.get(tid, {}).get("name", f"Equipo {tid}") for tid in team_ids]
            club_names = [self.teams[tid]["name"] for tid in team_ids if tid in self.teams and self.teams[tid]["kind"] == "club"]
            selection_names = [self.teams[tid]["name"] for tid in team_ids if tid in self.teams and self.teams[tid]["kind"] == "selection"]
            self.player_rows.append({
                "key": key, "id": pid, "name": name, "game_name": game_name, "table": table,
                "position": position_name,
                "team_ids": team_ids, "team_names": team_names,
                "club_names": club_names, "selection_names": selection_names,
                "search": base_search + " " + _fold(" ".join(team_names)) if team_names else base_search,
            })
        self.player_rows.sort(key=lambda x: (x["name"].casefold(), x["id"]))
        self._row_index = {row["key"]: row for row in self.player_rows}
        if len(record_cache) > 120_000:
            record_cache.clear()

    def _player_info(self, record: bytes, pid: int) -> tuple:
        cache = self.__dict__.setdefault("_record_cache", {})
        info = cache.get(record)
        if info is None:
            game_name = _read_text(record, 129)
            shirt_name = _read_text(record, 190)
            full_name = _read_text(record, 251)
            localized_name = _read_text(record, 68)
            position_bits = _get_bits(record, *FIELDS["position"][:2])
            name = full_name or game_name or f"Jugador {pid}"
            info = cache[record] = (
                game_name, shirt_name, full_name, localized_name, name,
                POSITION_NAMES[position_bits] if position_bits < len(POSITION_NAMES) else "?",
                _fold(f"{pid} {name} {game_name} {shirt_name} {localized_name}"),
            )
        return info

    def _reindex_players(self, changes: list[Change]) -> bool:
        """Reindexado ligero para ediciones de jugador en el mismo sitio.

        Devuelve False (y no toca nada) si el cambio no es una edición simple,
        para que el llamador haga el reindexado completo.
        """
        touched: list[tuple[str, int]] = []
        for change in changes:
            if change.table in ("Player", "Player4"):
                if (len(change.old) != PLAYER_SIZE or len(change.new) != PLAYER_SIZE
                        or change.start % PLAYER_SIZE or change.old[8:12] != change.new[8:12]):
                    return False
                touched.append((change.table, change.start))
            elif change.table == "PlayerAppearance":
                if len(change.old) != len(change.new) or change.old[:4] != change.new[:4]:
                    return False
            else:
                return False
        rows = []
        for table, offset in touched:
            pid = _u32(self.tables[table], offset + 8)
            key = f"{table}:{pid}"
            row = self._row_index.get(key)
            if row is None or self.players.get(key) != (table, offset):
                return False
            rows.append((key, row, pid, bytes(self.tables[table][offset:offset + PLAYER_SIZE])))
        for key, row, pid, record in rows:
            game_name, _shirt, _full, _loc, name, position_name, base = self._player_info(record, pid)
            self._row_base[key] = base
            row["name"] = name; row["game_name"] = game_name; row["position"] = position_name
            row["search"] = base + " " + _fold(" ".join(row["team_names"])) if row["team_names"] else base
        if rows:
            self.player_rows.sort(key=lambda x: (x["name"].casefold(), x["id"]))
        return True

    def _build_assignments(self) -> None:
        self.assignments: dict[int, list[tuple[str, int]]] = {}
        setdefault = self.assignments.setdefault
        for table in ("PlayerAssignment", "PlayerAssignment4"):
            data = bytes(self.tables[table])
            for index, (_row_id, pid, _team, _rest) in enumerate(struct.iter_unpack("<IIII", data)):
                setdefault(pid, []).append((table, index * ASSIGNMENT_SIZE))

    @staticmethod
    def _changed_assignment_pids(changes: list[Change]) -> set[int]:
        """IDs de jugador cuyas filas de inscripción difieren entre old y new."""
        pids: set[int] = set()
        for change in changes:
            if change.table not in ("PlayerAssignment", "PlayerAssignment4"):
                continue
            old_rows = Counter(change.old[i:i + ASSIGNMENT_SIZE] for i in range(0, len(change.old), ASSIGNMENT_SIZE))
            new_rows = Counter(change.new[i:i + ASSIGNMENT_SIZE] for i in range(0, len(change.new), ASSIGNMENT_SIZE))
            for row in list((old_rows - new_rows) + (new_rows - old_rows)):
                pids.add(struct.unpack_from("<I", row, 4)[0])
        return pids

    def _reindex_assignments(self, pids: set[int]) -> None:
        """Reindexado ligero: solo cambiaron inscripciones/tácticas.

        Jugadores, apariencias y equipos no se tocan: se reconstruye el mapa de
        inscripciones y se refrescan únicamente las filas de los jugadores
        afectados.
        """
        self._build_assignments()
        teams = self.teams
        for pid in pids:
            for key in self.by_pid.get(pid, []):
                row = self._row_index[key]
                assignment_table = "PlayerAssignment4" if row["table"] == "Player4" else "PlayerAssignment"
                team_ids = [_u32(self.tables[t], o + 8) for t, o in self.assignments.get(pid, []) if t == assignment_table]
                team_names = [teams.get(tid, {}).get("name", f"Equipo {tid}") for tid in team_ids]
                base = self._row_base[key]
                row["team_ids"] = team_ids
                row["team_names"] = team_names
                row["club_names"] = [teams[tid]["name"] for tid in team_ids if tid in teams and teams[tid]["kind"] == "club"]
                row["selection_names"] = [teams[tid]["name"] for tid in team_ids if tid in teams and teams[tid]["kind"] == "selection"]
                row["search"] = base + " " + _fold(" ".join(team_names)) if team_names else base

    _LIGHT_TABLES = frozenset({"PlayerAssignment", "PlayerAssignment4", "TacticsFormation", "TacticsFormation4"})

    def _refresh_index(self, changes: list[Change]) -> None:
        tables = {c.table for c in changes}
        if tables <= self._LIGHT_TABLES:
            self._reindex_assignments(self._changed_assignment_pids(changes))
        elif not self._reindex_players(changes):
            self._reindex()

    def _locate(self, reference: Any) -> tuple[str, int, int, str]:
        """Return table, byte offset, numeric ID and stable composite key."""
        text = str(reference)
        if text in self.players:
            table, offset = self.players[text]
            return table, offset, int(text.split(":", 1)[1]), text
        try:
            pid = int(text)
        except (TypeError, ValueError):
            raise ValueError("Referencia de jugador no válida") from None
        keys = self.by_pid.get(pid, [])
        if not keys:
            raise ValueError("No existe ese ID de jugador")
        # Main Player.bin is the safe default if a legacy caller only provides ID.
        key = next((k for k in keys if k.startswith("Player:")), keys[0])
        table, offset = self.players[key]
        return table, offset, pid, key

    def summary(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "players": len(self.players),
            "teams": len(self.teams),
            "assignments": sum(len(v) for v in self.assignments.values()),
            "appearances": len(self.appearances),
            "dirty": bool(self.dirty),
            "undo": len(self.history),
            "last_action": self.activity[-1] if self.activity else "",
        }

    def metadata(self) -> dict[str, Any]:
        ordered_teams = sorted(self.teams.values(), key=lambda x: (x["name"].casefold(), x["id"]))
        return {
            "summary": self.summary(),
            "teams": ordered_teams,
            "club_teams": [team for team in ordered_teams if team["kind"] == "club"],
            "selection_teams": [team for team in ordered_teams if team["kind"] == "selection"],
            "countries": [{"id": k, "name": v} for k, v in sorted(COUNTRIES.items())],
            "positions": [{"id": i, "name": name, "code": POSITION_CODES[i]} for i, name in enumerate(POSITION_NAMES)],
            "stats": list(STATS),
            "formations": {
                name: [{"role": role, "code": POSITION_CODES[role], "x": x, "y": y} for role, x, y in slots]
                for name, slots in FORMATION_PRESETS.items()
            },
        }

    def get_team_details(self, team_id: int) -> dict[str, Any]:
        team_id = int(team_id)
        team = self.teams.get(team_id)
        if not team:
            raise ValueError("No existe ese equipo")
        record = self.tables[team["table"]][team["index"] * TEAM_SIZE:(team["index"] + 1) * TEAM_SIZE]
        abbreviation = _read_text(record, 882, 10) or _read_text(record, 1382, 10)
        roster_count = len(self._team_assignment_rows(team_id))
        return {
            **{k: v for k, v in team.items() if k != "index"},
            "abbreviation": abbreviation,
            "roster_count": roster_count,
            "slot_note": (
                "Este modo conserva el Team ID, la región, la liga y los enlaces del slot. "
                "Para crear un club en Otros de Europa o Latinoamérica, sustituye un club que ya pertenezca a esa zona."
            ),
        }

    def replace_team_slot(self, team_id: int, name: str, abbreviation: str) -> dict[str, Any]:
        team_id = int(team_id)
        team = self.teams.get(team_id)
        if not team:
            raise ValueError("No existe ese equipo")
        if team["kind"] != "club":
            raise ValueError("La creación segura de clubes solo puede sustituir otro club, no una selección")
        name = " ".join(str(name or "").strip().split())
        if not name:
            raise ValueError("Escribe el nombre del nuevo equipo")
        if len(name.encode("utf-8")) > 60:
            raise ValueError("El nombre del equipo admite hasta 60 bytes UTF-8")
        abbreviation = re.sub(r"[^A-Za-z0-9]", "", str(abbreviation or "").upper())[:3]
        if len(abbreviation) < 2:
            raise ValueError("La abreviatura debe tener entre 2 y 3 letras o números")

        offset = team["index"] * TEAM_SIZE
        old = bytes(self.tables[team["table"]][offset:offset + TEAM_SIZE])
        new = bytearray(old)
        # Main/localized display-name slots used by PES 2021 patches.  Writing
        # all three avoids the old club name resurfacing after a language swap.
        for text_offset in TEAM_NAME_OFFSETS:
            _write_text(new, text_offset, name, 70)
        for text_offset in TEAM_ABBR_OFFSETS:
            _write_text(new, text_offset, abbreviation, 10)
        self._commit(
            f"Equipo sustituido: {team['name']} → {name} (Team ID {team_id})",
            [Change(team["table"], offset, old, bytes(new))],
        )
        return self.get_team_details(team_id)

    def _team_import_roster(self, team_id: int) -> list[dict[str, Any]]:
        """Return a team's roster without assuming that its formation is usable."""
        rows: list[dict[str, Any]] = []
        seen: set[int] = set()
        for assignment_table, offset in self._team_assignment_rows(team_id):
            assignment = self.tables[assignment_table]
            pid = _u32(assignment, offset + 4)
            if pid in seen:
                raise ValueError(f"El equipo externo repite al jugador ID {pid}")
            seen.add(pid)
            player = self._player_for_assignment(assignment_table, offset)
            rows.append({
                "source_key": player["key"],
                "source_id": pid,
                "name": player["full_name"] or player["display_name"],
                "display_name": player["display_name"],
                "nationality": player["nationality"],
                "nationality_name": player["nationality_name"],
                "age": player["age"],
                "position": player["position_name"],
                "position_code": POSITION_CODES[player["position"]],
                "shirt_number": (assignment[offset + 12] & 0x7f) + 1,
                "squad_order": assignment[offset + 13] >> 2,
            })
        rows.sort(key=lambda row: (row["squad_order"], row["name"].casefold(), row["source_id"]))
        return rows

    def _build_team_import_plan(self, source: "DatabaseManager", source_team_id: int, target_team_id: int) -> dict[str, Any]:
        source_team_id = int(source_team_id); target_team_id = int(target_team_id)
        source_team = source.teams.get(source_team_id); target_team = self.teams.get(target_team_id)
        if not source_team or source_team["kind"] != "club":
            raise ValueError("Selecciona un club válido de la database externa")
        if not target_team or target_team["kind"] != "club":
            raise ValueError("Selecciona un slot de club válido en Destiny")

        roster = source._team_import_roster(source_team_id)
        if not roster:
            raise ValueError("El club externo no tiene jugadores inscritos")
        if len(roster) > 64:
            raise ValueError("El club externo supera el límite seguro de 64 inscripciones")
        # Validate the source formation now, before any edit is proposed.
        source_slots = source._formation_slots(source_team_id)
        expected_table = "Player4" if target_team["table"] == "Team4" else "Player"

        name_index: dict[str, list[str]] = {}
        for row in self.player_rows:
            if row["table"] != expected_table:
                continue
            for value in (row["name"], row["game_name"]):
                key = _name_key(value)
                if key:
                    name_index.setdefault(key, []).append(row["key"])

        occupied = set(self.by_pid) | set(self.appearances) | set(self.assignments)
        reserved: set[int] = set()
        claimed_existing: set[str] = set()
        player_cache: dict[str, dict[str, Any]] = {}

        def details(key: str) -> dict[str, Any]:
            if key not in player_cache:
                player_cache[key] = self.get_player(key)
            return player_cache[key]

        def names(player: dict[str, Any]) -> set[str]:
            return {key for key in (_name_key(player.get("full_name", "")), _name_key(player.get("display_name", ""))) if key}

        next_id = max(occupied, default=99999) + 1

        def fresh_id() -> int:
            nonlocal next_id
            while next_id in occupied or next_id in reserved:
                next_id += 1
            result = next_id; next_id += 1
            return result

        planned: list[dict[str, Any]] = []
        for source_row in roster:
            source_player = source.get_player(source_row["source_key"])
            source_names = names(source_player)
            candidates: list[str] = []
            for name in source_names:
                candidates.extend(name_index.get(name, []))
            candidates = list(dict.fromkeys(key for key in candidates if key not in claimed_existing))

            same_id_key = f"{expected_table}:{source_row['source_id']}"
            matching: list[str] = []
            for key in candidates:
                candidate = details(key)
                if candidate["nationality"] == source_player["nationality"] and names(candidate) & source_names:
                    matching.append(key)
            target_key: str | None = None
            if same_id_key in matching:
                target_key = same_id_key
            elif len(matching) == 1:
                target_key = matching[0]
            elif len(matching) > 1:
                same_age = [key for key in matching if details(key)["age"] == source_player["age"]]
                if len(same_age) == 1:
                    target_key = same_age[0]

            if target_key:
                target_player = details(target_key)
                target_id = target_player["id"]
                claimed_existing.add(target_key)
                clubs = [a["team_name"] for a in target_player["assignments"] if a["team_kind"] == "club" and a["team_id"] != target_team_id]
                action = "reuse"
            else:
                source_id = int(source_row["source_id"])
                if source_id > 0 and source_id not in occupied and source_id not in reserved:
                    target_id = source_id; action = "create_same_id"
                else:
                    target_id = fresh_id(); action = "create_new_id"
                reserved.add(target_id); clubs = []

            planned.append({
                **source_row,
                "target_key": target_key,
                "target_id": target_id,
                "action": action,
                "current_clubs": clubs,
            })

        source_details = source.get_team_details(source_team_id)
        target_details = self.get_team_details(target_team_id)
        duplicates = sorted(number for number in {p["shirt_number"] for p in planned} if sum(1 for p in planned if p["shirt_number"] == number) > 1)
        summary = {
            "players": len(planned),
            "reuse": sum(p["action"] == "reuse" for p in planned),
            "create_same_id": sum(p["action"] == "create_same_id" for p in planned),
            "create_new_id": sum(p["action"] == "create_new_id" for p in planned),
            "moved": sum(bool(p["current_clubs"]) for p in planned),
        }
        return {
            "source_team": source_details,
            "target_team": target_details,
            "players": planned,
            "summary": summary,
            "formation_name": source._preset_name(source_slots),
            "duplicate_shirts": duplicates,
            "warnings": [
                "Se conserva la liga, región, competiciones y Team ID del slot de Destiny.",
                "Las definiciones de jugadores y apariencias se copian; los archivos externos de faces no forman parte de la database.",
            ],
        }

    def preview_team_import(self, source: "DatabaseManager", source_team_id: int, target_team_id: int) -> dict[str, Any]:
        return self._build_team_import_plan(source, source_team_id, target_team_id)

    def import_team(self, source: "DatabaseManager", source_team_id: int, target_team_id: int) -> dict[str, Any]:
        plan = self._build_team_import_plan(source, source_team_id, target_team_id)
        target_id = int(plan["target_team"]["id"])
        source_id = int(plan["source_team"]["id"])
        target_team = self.teams[target_id]; source_team = source.teams[source_id]
        expected_player_table = "Player4" if target_team["table"] == "Team4" else "Player"
        assignment_table = "PlayerAssignment4" if target_team["table"] == "Team4" else "PlayerAssignment"

        changes: list[Change] = []
        team_offset = target_team["index"] * TEAM_SIZE
        team_old = bytes(self.tables[target_team["table"]][team_offset:team_offset + TEAM_SIZE])
        team_new = bytearray(team_old)
        imported_name = plan["source_team"]["name"]
        imported_abbr = plan["source_team"]["abbreviation"] or re.sub(r"[^A-Za-z0-9]", "", imported_name.upper())[:3]
        for text_offset in TEAM_NAME_OFFSETS:
            _write_text(team_new, text_offset, imported_name, 70)
        for text_offset in TEAM_ABBR_OFFSETS:
            _write_text(team_new, text_offset, imported_abbr, 10)
        changes.append(Change(target_team["table"], team_offset, team_old, bytes(team_new)))

        appended_players = bytearray()
        appended_appearances = bytearray()
        for item in plan["players"]:
            if item["action"] == "reuse":
                continue
            source_table, source_offset, source_pid, _ = source._locate(item["source_key"])
            record = bytearray(source.tables[source_table][source_offset:source_offset + PLAYER_SIZE])
            struct.pack_into("<I", record, 8, int(item["target_id"]))
            appended_players.extend(record)
            if source_pid in source.appearances:
                appearance_offset = source.appearances[source_pid]
                appearance = bytearray(source.tables["PlayerAppearance"][appearance_offset:appearance_offset + APPEARANCE_SIZE])
            else:
                appearance = bytearray(APPEARANCE_SIZE)
            struct.pack_into("<I", appearance, 0, int(item["target_id"]))
            appended_appearances.extend(appearance)
        if appended_players:
            changes.append(Change(expected_player_table, len(self.tables[expected_player_table]), b"", bytes(appended_players)))
        if appended_appearances:
            changes.append(Change("PlayerAppearance", len(self.tables["PlayerAppearance"]), b"", bytes(appended_appearances)))

        assignment_old = bytes(self.tables[assignment_table])
        assignment_new = bytearray()
        imported_player_ids = {int(item["target_id"]) for item in plan["players"]}
        max_row_id = -1
        for offset in range(0, len(assignment_old), ASSIGNMENT_SIZE):
            row = assignment_old[offset:offset + ASSIGNMENT_SIZE]
            max_row_id = max(max_row_id, _u32(row, 0))
            pid = _u32(row, 4); team_id = _u32(row, 8)
            remove = team_id == target_id
            if pid in imported_player_ids and self.teams.get(team_id, {}).get("kind") == "club":
                remove = True
            if not remove:
                assignment_new.extend(row)
        for order, item in enumerate(plan["players"]):
            row = bytearray(ASSIGNMENT_SIZE); max_row_id += 1
            struct.pack_into("<III", row, 0, max_row_id, int(item["target_id"]), target_id)
            row[12] = _int(item["shirt_number"], "Dorsal", 1, 99) - 1
            squad_order = min(63, max(0, int(item["squad_order"] if item["squad_order"] is not None else order)))
            row[13] = squad_order << 2
            assignment_new.extend(row)
        changes.append(Change(assignment_table, 0, assignment_old, bytes(assignment_new)))

        source_formation_table = "TacticsFormation4" if source_team["table"] == "Team4" else "TacticsFormation"
        target_formation_table = "TacticsFormation4" if target_team["table"] == "Team4" else "TacticsFormation"
        source_formation_offset = source_team["index"] * FORMATION_SIZE
        target_formation_offset = target_team["index"] * FORMATION_SIZE
        formation_old = bytes(self.tables[target_formation_table][target_formation_offset:target_formation_offset + FORMATION_SIZE])
        formation_new = bytes(source.tables[source_formation_table][source_formation_offset:source_formation_offset + FORMATION_SIZE])
        changes.append(Change(target_formation_table, target_formation_offset, formation_old, formation_new))

        label = f"Equipo importado: {imported_name} → slot {target_id} · {len(plan['players'])} jugadores"
        self._commit(label, changes)
        return {"plan": plan, "lineup": self.get_team_lineup(target_id), "team": self.get_team_details(target_id)}

    def search(self, query: str = "", team_id: int | None = None, table: str = "", page: int = 1, limit: int = 80) -> dict[str, Any]:
        needle = _fold(str(query).strip())
        page = max(1, int(page)); limit = max(10, min(200, int(limit)))
        items = [r for r in self.player_rows if (not needle or needle in r["search"])]
        if team_id not in (None, "", 0, "0"):
            tid = int(team_id); items = [r for r in items if tid in r["team_ids"]]
        if table in ("Player", "Player4"):
            items = [r for r in items if r["table"] == table]
        total = len(items); start = (page - 1) * limit
        return {"items": [{k: v for k, v in r.items() if k != "search"} for r in items[start:start + limit]], "total": total, "page": page, "pages": max(1, (total + limit - 1) // limit)}

    def get_player(self, reference: Any) -> dict[str, Any]:
        table, offset, pid, key = self._locate(reference)
        record = self.tables[table][offset:offset + PLAYER_SIZE]
        result: dict[str, Any] = {
            "key": key, "id": pid, "table": table,
            "display_name": _read_text(record, 129),
            "shirt_name": _read_text(record, 190),
            "full_name": _read_text(record, 251),
            "localized_name": _read_text(record, 68),
        }
        for key, (bit, width, bias) in FIELDS.items():
            result[key] = _get_bits(record, bit, width) + bias
        result["foot_name"] = "Izquierdo" if result["strong_foot"] else "Derecho"
        result["position_name"] = POSITION_NAMES[result["position"]] if 0 <= result["position"] < len(POSITION_NAMES) else "?"
        result["nationality_name"] = COUNTRIES.get(result["nationality"], f"ID {result['nationality']}")
        result["stats"] = {key: _get_bits(record, bit, width) + bias for key, (bit, width, bias) in STATS.items()}
        result["playable"] = {key: _get_bits(record, bit, width) for key, (bit, width) in PLAYABLE.items()}
        result["assignments"] = []
        assignment_table = "PlayerAssignment4" if table == "Player4" else "PlayerAssignment"
        for table_name, row_offset in self.assignments.get(pid, []):
            if table_name != assignment_table:
                continue
            row = self.tables[table_name]
            team_id = _u32(row, row_offset + 8)
            result["assignments"].append({
                "key": f"{table_name}:{row_offset // ASSIGNMENT_SIZE}",
                "table": table_name, "row": row_offset // ASSIGNMENT_SIZE,
                "team_id": team_id,
                "team_name": self.teams.get(team_id, {}).get("name", f"Equipo {team_id}"),
                "team_kind": self.teams.get(team_id, {}).get("kind", "unknown"),
                # PES stores the visible shirt number minus one in the low
                # seven bits.  The high bit is an unrelated flag and must be
                # preserved when an existing assignment is edited.
                "shirt_number": (row[row_offset + 12] & 0x7f) + 1,
                "squad_order": row[row_offset + 13] >> 2,
            })
        return result

    def available_ids(self, count: int = 24) -> dict[str, Any]:
        count = max(1, min(100, int(count)))
        used = set(self.by_pid)
        start = max(1, max(used, default=0) + 1)
        above: list[int] = []; candidate = start
        while len(above) < count:
            if candidate not in used and candidate not in self.appearances and candidate not in self.assignments:
                above.append(candidate)
            candidate += 1
        gaps: list[int] = []
        # Useful low gaps, but only call them "libres en estas tablas", never engine-reserved.
        candidate = 100000
        while candidate < start and len(gaps) < min(12, count):
            if candidate not in used and candidate not in self.appearances and candidate not in self.assignments:
                gaps.append(candidate)
            candidate += 1
        return {"recommended": above[0], "next": above, "gaps": gaps, "note": "Libres en Player, Appearance y Assignment. Para máxima compatibilidad usa el recomendado."}

    def _validated_record(self, source: bytes | bytearray, values: dict[str, Any]) -> bytes:
        record = bytearray(source)
        if "display_name" in values:
            _write_text(record, 129, values["display_name"])
        if "shirt_name" in values:
            shirt = " ".join(str(values["shirt_name"]).strip().split())
            if len(shirt.encode("utf-8")) > 24:
                raise ValueError("El nombre de camiseta admite hasta 24 bytes UTF-8")
            _write_text(record, 190, shirt)
        if "full_name" in values:
            _write_text(record, 251, values["full_name"])
            _write_text(record, 68, values["full_name"])
        ranges = {
            "nationality": (0, 511), "height": (100, 255), "weight": (30, 157),
            "age": (15, 78), "position": (0, 12), "form": (1, 8),
            "weak_use": (1, 4), "weak_accuracy": (1, 4), "injury_resistance": (1, 4),
            "playing_attitude": (0, 3), "strong_foot": (0, 1),
        }
        for key, (lo, hi) in ranges.items():
            if key in values:
                value = _int(values[key], key, lo, hi)
                bit, width, bias = FIELDS[key]
                _set_bits(record, bit, width, value - bias)
        for key, field in STATS.items():
            if key in values.get("stats", {}):
                value = _int(values["stats"][key], key, 40, 99)
                _set_bits(record, field[0], field[1], value - field[2])
        for key, field in PLAYABLE.items():
            if key in values.get("playable", {}):
                value = _int(values["playable"][key], f"posición {key}", 0, 2)
                _set_bits(record, field[0], field[1], value)
        return bytes(record)

    def _commit(self, label: str, changes: list[Change]) -> None:
        changes = [c for c in changes if c.old != c.new]
        if not changes:
            return
        applied: list[Change] = []
        try:
            for change in changes:
                data = self.tables[change.table]
                current = bytes(data[change.start:change.start + len(change.old)])
                if current != change.old:
                    raise ValueError("La base cambió durante la operación")
                data[change.start:change.start + len(change.old)] = change.new
                applied.append(change)
            self._refresh_index(changes)
        except Exception:
            for change in reversed(applied):
                self.tables[change.table][change.start:change.start + len(change.new)] = change.old
            self._reindex()
            raise
        self.history.append((label, changes))
        self.activity.append(label)
        for key in {c.table for c in changes}:
            if bytes(self.tables[key]) == self.original[key]: self.dirty.discard(key)
            else: self.dirty.add(key)

    def save_player(self, reference: Any, values: dict[str, Any]) -> dict[str, Any]:
        table, offset, pid, key = self._locate(reference)
        old = bytes(self.tables[table][offset:offset + PLAYER_SIZE])
        new = self._validated_record(old, values)
        name = _read_text(new, 129)
        self._commit(f"Jugador guardado: {name} (ID {pid})", [Change(table, offset, old, new)])
        return self.get_player(key)

    def transfer(self, reference: Any, assignment_key: str | None, team_id: int, shirt_number: int, squad_order: int | None = None) -> dict[str, Any]:
        ptable, _, pid, key = self._locate(reference); team_id = int(team_id)
        if team_id not in self.teams: raise ValueError("No existe ese equipo")
        if self.teams[team_id]["kind"] != "club":
            raise ValueError("Los traspasos normales solo admiten clubes, no selecciones")
        shirt_number = _int(shirt_number, "Dorsal", 1, 99)
        expected_assignment = "PlayerAssignment4" if ptable == "Player4" else "PlayerAssignment"
        rows = [(t, o) for t, o in self.assignments.get(pid, []) if t == expected_assignment]
        selected: tuple[str, int] | None = None
        if assignment_key:
            for table, offset in rows:
                if assignment_key == f"{table}:{offset // ASSIGNMENT_SIZE}": selected = (table, offset); break
            if not selected: raise ValueError("La inscripción seleccionada ya no existe")
        changes: list[Change] = []
        if selected:
            table, offset = selected
            old = bytes(self.tables[table][offset:offset + ASSIGNMENT_SIZE]); new = bytearray(old)
            old_team_id = _u32(old, 8)
            if self.teams.get(old_team_id, {}).get("kind") == "selection":
                raise ValueError("La inscripción de selección está protegida; crea una inscripción de club aparte")
            struct.pack_into("<I", new, 8, team_id)
            new[12] = (new[12] & 0x80) | (shirt_number - 1)
            if squad_order is not None:
                order = _int(squad_order, "Orden", 0, 63)
                new[13] = (new[13] & 0x03) | (order << 2)
            changes.append(Change(table, offset, old, bytes(new)))
        else:
            table = "PlayerAssignment4" if ptable == "Player4" else "PlayerAssignment"
            data = self.tables[table]
            indices = [_u32(data, o) for o in range(0, len(data), ASSIGNMENT_SIZE)]
            new = bytearray(ASSIGNMENT_SIZE)
            struct.pack_into("<III", new, 0, max(indices, default=-1) + 1, pid, team_id)
            new[12] = shirt_number - 1
            order = sum(1 for o in range(0, len(data), ASSIGNMENT_SIZE) if _u32(data, o + 8) == team_id) & 0x3f
            new[13] = order << 2
            changes.append(Change(table, len(data), b"", bytes(new)))
        self._commit(f"Traspaso: ID {pid} → {self.teams[team_id]['name']} · #{shirt_number}", changes)
        return self.get_player(key)

    def release_player(self, reference: Any, assignment_key: str | None = None, allow_below_minimum: bool = False) -> dict[str, Any]:
        """Move a player to the free-agent pool.

        This database has no "free agents" team record: a player is free when
        he has no club row in PlayerAssignment(4).  Releasing therefore deletes
        the selected *club* assignment, compacts the squad order of the team he
        leaves and never touches national-team rows.
        """
        ptable, _, pid, key = self._locate(reference)
        expected_assignment = "PlayerAssignment4" if ptable == "Player4" else "PlayerAssignment"
        club_rows: list[tuple[str, int]] = []
        for table, offset in self.assignments.get(pid, []):
            if table != expected_assignment:
                continue
            team = self.teams.get(_u32(self.tables[table], offset + 8))
            if team and team["kind"] == "club":
                club_rows.append((table, offset))
        if not club_rows:
            raise ValueError("Este jugador ya es libre: no tiene inscripción de club")
        if assignment_key:
            selected = next(((t, o) for t, o in club_rows if assignment_key == f"{t}:{o // ASSIGNMENT_SIZE}"), None)
            if not selected:
                raise ValueError("La inscripción seleccionada ya no existe o es una selección protegida")
        elif len(club_rows) == 1:
            selected = club_rows[0]
        else:
            raise ValueError("El jugador tiene varias inscripciones de club; selecciona cuál liberar")

        table, remove_offset = selected
        old_team_id = _u32(self.tables[table], remove_offset + 8)
        old_team = self.teams[old_team_id]
        remaining = len(self._team_assignment_rows(old_team_id)) - 1
        if remaining < 11 and not allow_below_minimum:
            raise ValueError(
                f"EQUIPO_MINIMO|{old_team['name']} se quedaría con {remaining} jugadores "
                "(el juego necesita al menos 11 para formar un once)"
            )
        player = self.get_player(key)
        player_name = player["full_name"] or player["display_name"]
        old = bytes(self.tables[table])
        new = bytearray(old[:remove_offset] + old[remove_offset + ASSIGNMENT_SIZE:])
        compact_rows = [o for o in range(0, len(new), ASSIGNMENT_SIZE) if _u32(new, o + 8) == old_team_id]
        compact_rows.sort(key=lambda o: new[o + 13] >> 2)
        for order, o in enumerate(compact_rows):
            new[o + 13] = (new[o + 13] & 0x03) | (order << 2)
        self._commit(f"Jugador libre: {player_name} (ID {pid}) sale de {old_team['name']}", [Change(table, 0, old, bytes(new))])
        return self.get_player(key)

    def create_player(self, new_id: int, template_reference: Any, values: dict[str, Any], team_id: int, shirt_number: int) -> dict[str, Any]:
        new_id = _int(new_id, "ID", 1, 0xffffffff)
        if new_id in self.by_pid or new_id in self.appearances or new_id in self.assignments:
            raise ValueError("Ese ID ya está ocupado en una tabla relacionada")
        if int(team_id) not in self.teams: raise ValueError("Selecciona un equipo válido")
        if self.teams[int(team_id)]["kind"] != "club": raise ValueError("El equipo inicial debe ser un club")
        source_table, source_offset, template_id, _ = self._locate(template_reference)
        source = bytes(self.tables[source_table][source_offset:source_offset + PLAYER_SIZE])
        player = bytearray(self._validated_record(source, values)); struct.pack_into("<I", player, 8, new_id)
        changes = [Change("Player", len(self.tables["Player"]), b"", bytes(player))]

        if source_table == "Player" and template_id in self.appearances:
            aoff = self.appearances[template_id]
            appearance = bytearray(self.tables["PlayerAppearance"][aoff:aoff + APPEARANCE_SIZE])
        else:
            appearance = bytearray(APPEARANCE_SIZE)
        struct.pack_into("<I", appearance, 0, new_id)
        changes.append(Change("PlayerAppearance", len(self.tables["PlayerAppearance"]), b"", bytes(appearance)))

        adata = self.tables["PlayerAssignment"]
        indices = [_u32(adata, o) for o in range(0, len(adata), ASSIGNMENT_SIZE)]
        assignment = bytearray(ASSIGNMENT_SIZE)
        struct.pack_into("<III", assignment, 0, max(indices, default=-1) + 1, new_id, int(team_id))
        assignment[12] = _int(shirt_number, "Dorsal", 1, 99) - 1
        assignment[13] = (sum(1 for o in range(0, len(adata), ASSIGNMENT_SIZE) if _u32(adata, o + 8) == int(team_id)) & 0x3f) << 2
        changes.append(Change("PlayerAssignment", len(adata), b"", bytes(assignment)))
        self._commit(f"Jugador creado: {_read_text(player, 129)} (ID {new_id})", changes)
        return self.get_player(f"Player:{new_id}")

    def _team_assignment_rows(self, team_id: int) -> list[tuple[str, int]]:
        team_id = int(team_id)
        if team_id not in self.teams:
            raise ValueError("No existe ese equipo")
        assignment_table = "PlayerAssignment4" if self.teams[team_id]["table"] == "Team4" else "PlayerAssignment"
        data = self.tables[assignment_table]
        return [(assignment_table, offset) for offset in range(0, len(data), ASSIGNMENT_SIZE) if _u32(data, offset + 8) == team_id]

    def _formation_slots(self, team_id: int, plan: int = 0) -> list[tuple[int, int, int]]:
        team = self.teams[int(team_id)]
        table = "TacticsFormation4" if team["table"] == "Team4" else "TacticsFormation"
        base = team["index"] * FORMATION_SIZE + _int(plan, "Plan táctico", 0, 5) * 11 * 12
        data = self.tables[table]
        if base + 132 > len(data):
            raise ValueError("La formación del equipo está fuera de la tabla")
        slots = []
        for slot in range(11):
            offset = base + slot * 12
            role = _u32(data, offset + 4)
            if role >= len(POSITION_CODES):
                raise ValueError("La formación contiene una posición no compatible")
            slots.append((role, data[offset + 9], data[offset + 8]))
        return slots

    @staticmethod
    def _preset_name(slots: list[tuple[int, int, int]]) -> str:
        roles = sorted(role for role, _x, _y in slots)
        for name, preset in FORMATION_PRESETS.items():
            if roles == sorted(role for role, _x, _y in preset):
                return name
        return "Personalizada"

    def _player_for_assignment(self, assignment_table: str, offset: int) -> dict[str, Any]:
        data = self.tables[assignment_table]
        pid = _u32(data, offset + 4)
        player_table = "Player4" if assignment_table == "PlayerAssignment4" else "Player"
        key = f"{player_table}:{pid}"
        if key not in self.players:
            # Some mixed patches reference a main-table player from Assignment4.
            key = self.by_pid.get(pid, [""])[0]
        if not key:
            raise ValueError(f"La plantilla referencia un jugador inexistente: {pid}")
        return self.get_player(key)

    @staticmethod
    def _weighted(stats: dict[str, int], names: list[str]) -> float:
        return sum(stats[name] for name in names) / len(names)

    def _slot_score(self, player: dict[str, Any], role: int) -> float:
        score = self._weighted(player["stats"], POSITION_STAT_GROUPS[role])
        code = POSITION_CODES[role]
        aptitude = int(player["playable"].get(code, 0))
        score += (0, 6, 13)[aptitude]
        if player["position"] == role:
            score += 12
        elif aptitude == 0:
            score -= 9
        if role == 0 and player["position"] != 0 and aptitude == 0:
            score -= 45
        if role in (2, 6, 9):
            score += 2 if player["strong_foot"] == 1 else 0
        if role in (3, 7, 10):
            score += 2 if player["strong_foot"] == 0 else 0
        return score

    @staticmethod
    def _hungarian_max(scores: list[list[float]]) -> list[int]:
        """Maximum-weight rectangular assignment; one player per tactical slot."""
        n = len(scores); m = len(scores[0]) if scores else 0
        if not n or m < n:
            raise ValueError("Se necesitan al menos once jugadores para AutoSort")
        costs = [[-value for value in row] for row in scores]
        u = [0.0] * (n + 1); v = [0.0] * (m + 1)
        p = [0] * (m + 1); way = [0] * (m + 1)
        for i in range(1, n + 1):
            p[0] = i; j0 = 0
            minv = [float("inf")] * (m + 1); used = [False] * (m + 1)
            while True:
                used[j0] = True; i0 = p[j0]; delta = float("inf"); j1 = 0
                for j in range(1, m + 1):
                    if used[j]: continue
                    cur = costs[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]: minv[j] = cur; way[j] = j0
                    if minv[j] < delta: delta = minv[j]; j1 = j
                for j in range(m + 1):
                    if used[j]: u[p[j]] += delta; v[j] -= delta
                    else: minv[j] -= delta
                j0 = j1
                if p[j0] == 0: break
            while True:
                j1 = way[j0]; p[j0] = p[j1]; j0 = j1
                if j0 == 0: break
        answer = [-1] * n
        for j in range(1, m + 1):
            if p[j]: answer[p[j] - 1] = j - 1
        return answer

    def get_team_lineup(self, team_id: int) -> dict[str, Any]:
        team_id = int(team_id)
        if team_id not in self.teams: raise ValueError("No existe ese equipo")
        rows = self._team_assignment_rows(team_id)
        roster = []
        for table, offset in rows:
            row = self.tables[table]
            player = self._player_for_assignment(table, offset)
            rating = round(self._weighted(player["stats"], POSITION_STAT_GROUPS[player["position"]]))
            roster.append({
                "assignment_key": f"{table}:{offset // ASSIGNMENT_SIZE}",
                "player_key": player["key"], "id": player["id"],
                "name": player["full_name"] or player["display_name"],
                "game_name": player["display_name"],
                "position": player["position_name"], "position_code": POSITION_CODES[player["position"]],
                "shirt_number": (row[offset + 12] & 0x7f) + 1,
                "order": row[offset + 13] >> 2, "rating": min(99, max(40, rating)),
            })
        roster.sort(key=lambda item: (item["order"], item["name"].casefold()))
        slots = self._formation_slots(team_id)
        return {
            "team": {k: v for k, v in self.teams[team_id].items() if k != "index"},
            "roster": roster,
            "formation_name": self._preset_name(slots),
            "formation": [{"role": role, "code": POSITION_CODES[role], "x": x, "y": y} for role, x, y in slots],
        }

    def autosort_preview(self, team_id: int, preset_name: str = "") -> dict[str, Any]:
        current = self.get_team_lineup(team_id)
        roster = current["roster"]
        if len(roster) < 11: raise ValueError("El equipo tiene menos de once jugadores")
        slots = FORMATION_PRESETS.get(preset_name) if preset_name else [(s["role"], s["x"], s["y"]) for s in current["formation"]]
        if slots is None: raise ValueError("Formación predefinida no válida")
        players = [self.get_player(item["player_key"]) for item in roster]
        scores = [[self._slot_score(player, role) for player in players] for role, _x, _y in slots]
        chosen = self._hungarian_max(scores)
        starters = [roster[index] for index in chosen]
        used = set(chosen)
        remaining = [item for index, item in enumerate(roster) if index not in used]
        remaining.sort(key=lambda item: (-item["rating"], item["name"].casefold()))
        # Put the best reserve goalkeeper first on the bench when available.
        reserve_gk = next((item for item in remaining if item["position_code"] == "GK"), None)
        if reserve_gk:
            remaining.remove(reserve_gk); remaining.insert(0, reserve_gk)
        ordered = starters + remaining
        return {
            "ordered_assignment_keys": [item["assignment_key"] for item in ordered],
            "starters": [{**item, "slot_code": POSITION_CODES[slots[i][0]], "slot_score": round(scores[i][chosen[i]])} for i, item in enumerate(starters)],
            "formation": [{"role": role, "code": POSITION_CODES[role], "x": x, "y": y} for role, x, y in slots],
            "formation_name": preset_name or current["formation_name"],
        }

    def save_lineup(self, team_id: int, ordered_assignment_keys: list[str], preset_name: str = "") -> dict[str, Any]:
        team_id = int(team_id)
        rows = self._team_assignment_rows(team_id)
        row_map = {f"{table}:{offset // ASSIGNMENT_SIZE}": (table, offset) for table, offset in rows}
        if len(ordered_assignment_keys) != len(row_map) or set(ordered_assignment_keys) != set(row_map):
            raise ValueError("La lista de plantilla está incompleta o contiene duplicados")
        if len(ordered_assignment_keys) > 64: raise ValueError("La plantilla supera 64 jugadores")
        changes: list[Change] = []
        for order, assignment_key in enumerate(ordered_assignment_keys):
            table, offset = row_map[assignment_key]
            old = bytes(self.tables[table][offset:offset + ASSIGNMENT_SIZE]); new = bytearray(old)
            new[13] = (new[13] & 0x03) | (order << 2)
            changes.append(Change(table, offset, old, bytes(new)))
        if preset_name:
            if preset_name not in FORMATION_PRESETS: raise ValueError("Formación predefinida no válida")
            team = self.teams[team_id]
            table = "TacticsFormation4" if team["table"] == "Team4" else "TacticsFormation"
            base = team["index"] * FORMATION_SIZE
            old = bytes(self.tables[table][base:base + FORMATION_SIZE]); new = bytearray(old)
            preset = FORMATION_PRESETS[preset_name]
            for plan in range(6):
                for slot, (role, x, y) in enumerate(preset):
                    offset = (plan * 11 + slot) * 12
                    struct.pack_into("<I", new, offset + 4, role)
                    new[offset + 8] = y; new[offset + 9] = x
            changes.append(Change(table, base, old, bytes(new)))
        label = f"Alineación guardada: {self.teams[team_id]['name']}"
        if preset_name: label += f" · {preset_name}"
        self._commit(label, changes)
        return self.get_team_lineup(team_id)

    def search_callup_candidates(self, selection_team_id: int, query: str = "", limit: int = 80) -> dict[str, Any]:
        """Find main-database players that can be called up by a national team."""
        selection_team_id = int(selection_team_id)
        team = self.teams.get(selection_team_id)
        if not team or team["kind"] != "selection":
            raise ValueError("El destino debe ser una selección nacional")
        limit = max(10, min(150, int(limit)))
        needle = _fold(str(query).strip())
        assigned = {
            _u32(self.tables[table], offset + 4)
            for table, offset in self._team_assignment_rows(selection_team_id)
        }
        target_nationality = team.get("nationality_id")
        candidates = []
        for summary in self.player_rows:
            # The normal national-team table uses Player.bin.  Player4 players
            # belong to the separate classic/legends assignment table.
            if summary["table"] != "Player":
                continue
            if needle and needle not in summary["search"]:
                continue
            player = self.get_player(summary["key"])
            rating = round(self._weighted(player["stats"], POSITION_STAT_GROUPS[player["position"]]))
            other_selections = []
            for assignment_table, offset in self.assignments.get(summary["id"], []):
                if assignment_table != "PlayerAssignment":
                    continue
                other_id = _u32(self.tables[assignment_table], offset + 8)
                other = self.teams.get(other_id)
                if other and other["kind"] == "selection" and other_id != selection_team_id:
                    other_selections.append(other["name"])
            eligible = target_nationality is None or player["nationality"] == target_nationality
            candidates.append({
                "player_key": player["key"], "id": player["id"],
                "name": player["full_name"] or player["display_name"],
                "game_name": player["display_name"],
                "position": player["position_name"], "position_code": POSITION_CODES[player["position"]],
                "nationality": player["nationality"], "nationality_name": player["nationality_name"],
                "clubs": summary["club_names"], "other_selections": other_selections,
                "eligible": eligible, "called_up": summary["id"] in assigned,
                "rating": min(99, max(40, rating)),
            })
        candidates.sort(key=lambda item: (
            not item["called_up"], bool(item["other_selections"]), not item["eligible"],
            -item["rating"], item["name"].casefold(), item["id"]
        ))
        return {
            "items": candidates[:limit], "total": len(candidates),
            "selection": {k: v for k, v in team.items() if k != "index"},
        }

    def call_up(self, selection_team_id: int, player_reference: Any, shirt_number: int, allow_mismatch: bool = False) -> dict[str, Any]:
        """Append a national-team assignment without disturbing the club row."""
        selection_team_id = int(selection_team_id)
        team = self.teams.get(selection_team_id)
        if not team or team["kind"] != "selection":
            raise ValueError("El destino debe ser una selección nacional")
        player_table, _offset, pid, player_key = self._locate(player_reference)
        if player_table != "Player":
            raise ValueError("Esta selección solo admite jugadores de Player.bin")
        player = self.get_player(player_key)
        shirt_number = _int(shirt_number, "Dorsal", 1, 99)
        selection_rows = []
        for assignment_table, offset in self.assignments.get(pid, []):
            if assignment_table != "PlayerAssignment":
                continue
            assigned_team_id = _u32(self.tables[assignment_table], offset + 8)
            assigned_team = self.teams.get(assigned_team_id)
            if assigned_team_id == selection_team_id:
                raise ValueError(f"{player['full_name'] or player['display_name']} ya está convocado por {team['name']}")
            if assigned_team and assigned_team["kind"] == "selection":
                selection_rows.append(assigned_team["name"])
        if selection_rows:
            raise ValueError("El jugador ya figura en otra selección: " + ", ".join(selection_rows))
        target_nationality = team.get("nationality_id")
        if target_nationality is not None and player["nationality"] != target_nationality and not allow_mismatch:
            raise ValueError(
                "NACIONALIDAD_INCOMPATIBLE|"
                f"{player['full_name'] or player['display_name']} figura como {player['nationality_name']}, "
                f"pero la selección es {team['name']}"
            )
        rows = self._team_assignment_rows(selection_team_id)
        if len(rows) >= 64:
            raise ValueError("La convocatoria ya alcanzó el máximo de 64 jugadores")
        for assignment_table, assignment_offset in rows:
            visible_number = (self.tables[assignment_table][assignment_offset + 12] & 0x7f) + 1
            if visible_number == shirt_number:
                occupant = self._player_for_assignment(assignment_table, assignment_offset)
                occupant_name = occupant["full_name"] or occupant["display_name"]
                raise ValueError(f"DORSAL_OCUPADO|El dorsal {shirt_number} ya lo usa {occupant_name}")
        data = self.tables["PlayerAssignment"]
        indices = [_u32(data, offset) for offset in range(0, len(data), ASSIGNMENT_SIZE)]
        new = bytearray(ASSIGNMENT_SIZE)
        struct.pack_into("<III", new, 0, max(indices, default=-1) + 1, pid, selection_team_id)
        new[12] = shirt_number - 1
        new[13] = (len(rows) & 0x3f) << 2
        label = f"Convocado: {player['full_name'] or player['display_name']} · {team['name']}"
        self._commit(label, [Change("PlayerAssignment", len(data), b"", bytes(new))])
        return self.get_team_lineup(selection_team_id)

    def change_assignment_shirt(self, team_id: int, assignment_key: str, shirt_number: int) -> dict[str, Any]:
        """Change one squad number while guaranteeing uniqueness inside the team."""
        team_id = int(team_id)
        if team_id not in self.teams:
            raise ValueError("No existe ese equipo")
        shirt_number = _int(shirt_number, "Dorsal", 1, 99)
        rows = self._team_assignment_rows(team_id)
        row_map = {f"{table}:{offset // ASSIGNMENT_SIZE}": (table, offset) for table, offset in rows}
        selected = row_map.get(str(assignment_key))
        if not selected:
            raise ValueError("La inscripción seleccionada ya no existe en este equipo")
        for key, (table, offset) in row_map.items():
            if key == assignment_key:
                continue
            visible_number = (self.tables[table][offset + 12] & 0x7f) + 1
            if visible_number == shirt_number:
                occupant = self._player_for_assignment(table, offset)
                occupant_name = occupant["full_name"] or occupant["display_name"]
                raise ValueError(f"DORSAL_OCUPADO|El dorsal {shirt_number} ya lo usa {occupant_name}")
        table, offset = selected
        old = bytes(self.tables[table][offset:offset + ASSIGNMENT_SIZE])
        current_number = (old[12] & 0x7f) + 1
        if current_number == shirt_number:
            return self.get_team_lineup(team_id)
        new = bytearray(old)
        new[12] = (new[12] & 0x80) | (shirt_number - 1)
        player = self._player_for_assignment(table, offset)
        player_name = player["full_name"] or player["display_name"]
        self._commit(
            f"Dorsal actualizado: {player_name} · {current_number} → {shirt_number}",
            [Change(table, offset, old, bytes(new))],
        )
        return self.get_team_lineup(team_id)

    def remove_callup(self, selection_team_id: int, assignment_key: str) -> dict[str, Any]:
        """Remove exactly one national-team assignment and compact squad order."""
        selection_team_id = int(selection_team_id)
        team = self.teams.get(selection_team_id)
        if not team or team["kind"] != "selection":
            raise ValueError("El destino debe ser una selección nacional")
        rows = self._team_assignment_rows(selection_team_id)
        row_map = {f"{table}:{offset // ASSIGNMENT_SIZE}": offset for table, offset in rows}
        if assignment_key not in row_map:
            raise ValueError("La convocatoria seleccionada ya no existe")
        if len(rows) <= 11:
            raise ValueError("Una selección debe conservar al menos once convocados")
        remove_offset = row_map[assignment_key]
        player = self._player_for_assignment("PlayerAssignment", remove_offset)
        old = bytes(self.tables["PlayerAssignment"])
        new = bytearray(old[:remove_offset] + old[remove_offset + ASSIGNMENT_SIZE:])
        compact_rows = [
            offset for offset in range(0, len(new), ASSIGNMENT_SIZE)
            if _u32(new, offset + 8) == selection_team_id
        ]
        compact_rows.sort(key=lambda offset: new[offset + 13] >> 2)
        for order, offset in enumerate(compact_rows):
            new[offset + 13] = (new[offset + 13] & 0x03) | (order << 2)
        label = f"Desconvocado: {player['full_name'] or player['display_name']} · {team['name']}"
        self._commit(label, [Change("PlayerAssignment", 0, old, bytes(new))])
        return self.get_team_lineup(selection_team_id)

    def replace_slot(self, target_reference: Any, template_reference: Any, values: dict[str, Any], copy_appearance: bool = True) -> dict[str, Any]:
        target_table, target_offset, target_id, target_key = self._locate(target_reference)
        source_table, source_offset, template_id, _ = self._locate(template_reference)
        old = bytes(self.tables[target_table][target_offset:target_offset + PLAYER_SIZE])
        source = bytes(self.tables[source_table][source_offset:source_offset + PLAYER_SIZE])
        new = bytearray(old)
        # Preserve the target slot's first 12 bytes (including its ID), replace
        # the editable/player definition area, then apply the requested names.
        new[12:] = source[12:]
        new = bytearray(self._validated_record(new, values))
        struct.pack_into("<I", new, 8, target_id)
        changes = [Change(target_table, target_offset, old, bytes(new))]
        if copy_appearance and target_table == "Player" and source_table == "Player" and template_id in self.appearances and target_id in self.appearances:
            toff = self.appearances[target_id]; soff = self.appearances[template_id]
            aold = bytes(self.tables["PlayerAppearance"][toff:toff + APPEARANCE_SIZE])
            anew = bytearray(self.tables["PlayerAppearance"][soff:soff + APPEARANCE_SIZE])
            struct.pack_into("<I", anew, 0, target_id)
            changes.append(Change("PlayerAppearance", toff, aold, bytes(anew)))
        self._commit(f"Slot reemplazado: ID {target_id} desde ID {template_id}", changes)
        return self.get_player(target_key)

    def undo(self) -> dict[str, Any]:
        if not self.history: raise ValueError("No hay operaciones para deshacer")
        label, changes = self.history.pop()
        for change in reversed(changes):
            data = self.tables[change.table]
            current = bytes(data[change.start:change.start + len(change.new)])
            if current != change.new: raise ValueError("No se puede deshacer: la base cambió")
            data[change.start:change.start + len(change.new)] = change.old
        self._refresh_index(changes)
        for key in {c.table for c in changes}:
            if bytes(self.tables[key]) == self.original[key]: self.dirty.discard(key)
            else: self.dirty.add(key)
        message = "Deshecho: " + label
        self.activity.append(message)
        return {"message": message, "summary": self.summary()}

    def export(self) -> bytes:
        if not self.dirty:
            return self.source_bytes
        replacements = {self.paths[key]: wrap(bytes(self.tables[key]), self.headers[key]) for key in self.dirty}
        result = self.cpk.rebuild(replacements)
        # Independent second pass: table lengths, IDs, and every changed raw byte.
        check = CPK(result)
        for key in self.dirty:
            entry = check.by_name[self.paths[key].casefold()]
            decoded, _ = unwrap(check.read(entry))
            if decoded != bytes(self.tables[key]):
                raise ValueError("La verificación final no coincide en " + key)
        # Verify referential IDs for every player introduced during this session.
        for key in ("Player", "Player4"):
            data = self.tables[key]
            ids = [_u32(data, o + 8) for o in range(0, len(data), PLAYER_SIZE)]
            if len(ids) != len(set(ids)): raise ValueError(f"IDs duplicados dentro de {key}")
        self.activity.append("CPK exportado y verificado")
        return result
