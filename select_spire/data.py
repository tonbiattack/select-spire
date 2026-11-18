"""Enemy definitions and SQLite data generation for SELECT Spire.

Each floor is a battle against one to three enemies. Every enemy owns a table
with the same four columns, and each floor also gets a ``battle_<n>`` view that
unions those tables with an ``enemy`` column. The game queries that view, so
WHERE, JOIN and GROUP BY act on real rows rather than on a damage formula.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import random
import sqlite3


@dataclass(frozen=True)
class EnemyDefinition:
    name: str
    table: str
    columns: tuple[str, ...]
    weak_column: str
    hp: int
    attack: int
    trait: str
    rows: int


_COLUMNS = ("id", "element", "armor", "status")

# Row ids are spaced per enemy so a battle view can union tables without
# collisions and JOIN support still matches exactly one row.
_ID_BLOCK = 1000

# Total HP and total attack per floor stay close to the single-enemy version,
# so the run length is comparable while the tactical choices change.
FLOOR_ENEMIES: tuple[tuple[EnemyDefinition, ...], ...] = (
    (
        EnemyDefinition("Ember Slime", "ember_slime", _COLUMNS, "element", 16, 2, "hide", 8),
    ),
    (
        EnemyDefinition("Iron Beetle", "iron_beetle", _COLUMNS, "armor", 11, 1, "null", 9),
        EnemyDefinition("Moss Sprite", "moss_sprite", _COLUMNS, "status", 10, 1, "grow", 10),
    ),
    (
        EnemyDefinition("Frost Wisp", "frost_wisp", _COLUMNS, "element", 12, 1, "null", 11),
        EnemyDefinition("Stone Guardian", "stone_guardian", _COLUMNS, "armor", 12, 1, "hide", 12),
    ),
    (
        EnemyDefinition("Plague Moth", "plague_moth", _COLUMNS, "status", 14, 1, "grow", 13),
        EnemyDefinition("Storm Drake", "storm_drake", _COLUMNS, "element", 13, 2, "hide", 14),
    ),
    (
        EnemyDefinition("Steel Sentinel", "steel_sentinel", _COLUMNS, "armor", 10, 1, "null", 15),
        EnemyDefinition("Ember Wisp", "ember_wisp", _COLUMNS, "element", 10, 1, "hide", 8),
        EnemyDefinition("Moss Crawler", "moss_crawler", _COLUMNS, "status", 10, 1, "grow", 9),
    ),
    (
        EnemyDefinition("Plague Drake", "plague_drake", _COLUMNS, "status", 17, 1, "grow", 13),
        EnemyDefinition("Iron Wisp", "iron_wisp", _COLUMNS, "element", 16, 2, "null", 11),
    ),
    (
        EnemyDefinition("Storm Sentinel", "storm_sentinel", _COLUMNS, "armor", 12, 2, "hide", 14),
        EnemyDefinition("Frost Beetle", "frost_beetle", _COLUMNS, "element", 12, 1, "null", 9),
        EnemyDefinition("Moss Guardian", "moss_guardian", _COLUMNS, "status", 12, 1, "grow", 10),
    ),
    (
        EnemyDefinition("Steel Drake", "steel_drake", _COLUMNS, "armor", 20, 2, "null", 15),
        EnemyDefinition("Plague Wisp", "plague_wisp", _COLUMNS, "status", 20, 2, "grow", 11),
    ),
    (
        EnemyDefinition("Spire Sovereign", "spire_sovereign", _COLUMNS, "status", 25, 2, "grow", 18),
        EnemyDefinition("Sovereign Guard", "sovereign_guard", _COLUMNS, "armor", 10, 2, "hide", 12),
        EnemyDefinition("Sovereign Herald", "sovereign_herald", _COLUMNS, "element", 10, 1, "null", 10),
    ),
)

# Flat view of every enemy, kept for callers that only need the roster.
FLOORS: tuple[EnemyDefinition, ...] = tuple(
    enemy for floor in FLOOR_ENEMIES for enemy in floor
)


def battle_view(floor: int) -> str:
    """Name of the per-floor view that unions every enemy table."""
    return f"battle_{floor + 1}"


def row_id(enemy_index: int, row: int) -> int:
    """Globally unique id for one row of one enemy in a battle."""
    return enemy_index * _ID_BLOCK + row


def _identifier(value: str) -> str:
    """Quote a SQLite identifier, including any embedded double quotes."""
    return '"' + value.replace('"', '""') + '"'


def _row(enemy: EnemyDefinition, enemy_index: int, row: int, weak: bool) -> tuple[int, str, str, str]:
    values = {
        column: "weak" if column == enemy.weak_column and weak else "normal"
        for column in _COLUMNS[1:]
    }
    return row_id(enemy_index, row), values["element"], values["armor"], values["status"]


def generate_database(path: str | Path, seed: int) -> None:
    """Create a new database; never replace an existing file.

    The seed determines support values. Enemy weak rows are deliberately ordered,
    so the first floor(rows * 0.8) rows are useful for a weak-point query.
    """
    path = Path(path)
    # Exclusive creation prevents an existing database (or other file) being replaced.
    with path.open("xb"):
        pass

    rng = random.Random(seed)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE support (id INTEGER PRIMARY KEY, boost TEXT)")
        support_ids: set[int] = set()
        for floor_index, floor in enumerate(FLOOR_ENEMIES):
            selects = []
            for enemy_index, enemy in enumerate(floor):
                table = _identifier(enemy.table)
                connection.execute(
                    f"CREATE TABLE {table} "
                    "(id INTEGER PRIMARY KEY, element TEXT, armor TEXT, status TEXT)"
                )
                weak_count = enemy.rows * 4 // 5
                connection.executemany(
                    f"INSERT INTO {table} (id, element, armor, status) VALUES (?, ?, ?, ?)",
                    (
                        _row(enemy, enemy_index, row, row <= weak_count)
                        for row in range(1, enemy.rows + 1)
                    ),
                )
                support_ids.update(
                    row_id(enemy_index, row) for row in range(1, enemy.rows + 1)
                )
                selects.append(
                    f"SELECT '{enemy.table}' AS enemy, id, element, armor, status FROM {table}"
                )
            connection.execute(
                f"CREATE VIEW {_identifier(battle_view(floor_index))} AS "
                + " UNION ALL ".join(selects)
            )
        connection.executemany(
            "INSERT INTO support (id, boost) VALUES (?, ?)",
            ((value, rng.choice(("power", "guard", "focus"))) for value in sorted(support_ids)),
        )


def mutate_database(
    path: str | Path, enemy: EnemyDefinition, trait: str, rng: random.Random
) -> None:
    """Apply one enemy trait without changing another enemy's rows.

    Growth reuses existing support IDs when another table already uses them and
    creates support rows only for previously unseen IDs.
    """
    if trait not in {"hide", "null", "grow"}:
        raise ValueError(f"Unknown enemy trait: {trait!r}")
    if trait == "hide":
        return
    if enemy.weak_column not in _COLUMNS[1:]:
        raise ValueError(f"Invalid weak column: {enemy.weak_column!r}")

    table = _identifier(enemy.table)
    # Opening in rw mode avoids creating an empty DB on a missing or mistyped path.
    uri = Path(path).resolve().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True)) as connection, connection:
        if trait == "null":
            candidates = [column for column in _COLUMNS[1:] if column != enemy.weak_column]
            column = _identifier(rng.choice(candidates))
            row_ids = [row[0] for row in connection.execute(f"SELECT id FROM {table} ORDER BY id")]
            if row_ids:
                count = max(1, len(row_ids) // 4)
                selected = rng.sample(row_ids, count)
                connection.executemany(
                    f"UPDATE {table} SET {column} = NULL WHERE id = ?",
                    ((value,) for value in selected),
                )
        else:
            max_id = connection.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()[0]
            for offset in range(1, 5):
                new_id = max_id + offset
                connection.execute(
                    "INSERT OR IGNORE INTO support (id, boost) VALUES (?, ?)",
                    (new_id, rng.choice(("power", "guard", "focus"))),
                )
                values = {
                    column: "weak" if column == enemy.weak_column else "normal"
                    for column in _COLUMNS[1:]
                }
                connection.execute(
                    f"INSERT INTO {table} (id, element, armor, status) VALUES (?, ?, ?, ?)",
                    (new_id, values["element"], values["armor"], values["status"]),
                )
