"""Enemy definitions and SQLite data generation for SELECT Spire."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
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

# The numbers are intentionally kept together so they can be tuned after playtesting.
FLOORS: tuple[EnemyDefinition, ...] = (
    EnemyDefinition("Ember Slime", "ember_slime", _COLUMNS, "element", 18, 2, "hide", 8),
    EnemyDefinition("Iron Beetle", "iron_beetle", _COLUMNS, "armor", 21, 2, "null", 9),
    EnemyDefinition("Moss Sprite", "moss_sprite", _COLUMNS, "status", 24, 2, "grow", 10),
    EnemyDefinition("Frost Wisp", "frost_wisp", _COLUMNS, "element", 27, 3, "null", 11),
    EnemyDefinition("Stone Guardian", "stone_guardian", _COLUMNS, "armor", 30, 3, "hide", 12),
    EnemyDefinition("Plague Moth", "plague_moth", _COLUMNS, "status", 33, 3, "grow", 13),
    EnemyDefinition("Storm Drake", "storm_drake", _COLUMNS, "element", 36, 4, "hide", 14),
    EnemyDefinition("Steel Sentinel", "steel_sentinel", _COLUMNS, "armor", 40, 4, "null", 15),
    EnemyDefinition("Spire Sovereign", "spire_sovereign", _COLUMNS, "status", 45, 5, "grow", 18),
)


def _identifier(value: str) -> str:
    """Quote a SQLite identifier, including any embedded double quotes."""
    return '"' + value.replace('"', '""') + '"'


def _row(enemy: EnemyDefinition, row_id: int, weak: bool) -> tuple[int, str, str, str]:
    values = {
        column: "weak" if column == enemy.weak_column and weak else "normal"
        for column in _COLUMNS[1:]
    }
    return row_id, values["element"], values["armor"], values["status"]


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
        max_rows = max(enemy.rows for enemy in FLOORS)
        connection.executemany(
            "INSERT INTO support (id, boost) VALUES (?, ?)",
            ((row_id, rng.choice(("power", "guard", "focus"))) for row_id in range(1, max_rows + 1)),
        )
        for enemy in FLOORS:
            table = _identifier(enemy.table)
            connection.execute(
                f"CREATE TABLE {table} "
                "(id INTEGER PRIMARY KEY, element TEXT, armor TEXT, status TEXT)"
            )
            weak_count = enemy.rows * 4 // 5
            connection.executemany(
                f"INSERT INTO {table} (id, element, armor, status) VALUES (?, ?, ?, ?)",
                (_row(enemy, row_id, row_id <= weak_count) for row_id in range(1, enemy.rows + 1)),
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
                    ((row_id,) for row_id in selected),
                )
        else:
            max_id = connection.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()[0]
            for row_id in range(max_id + 1, max_id + 5):
                connection.execute(
                    "INSERT OR IGNORE INTO support (id, boost) VALUES (?, ?)",
                    (row_id, rng.choice(("power", "guard", "focus"))),
                )
                connection.execute(
                    f"INSERT INTO {table} (id, element, armor, status) VALUES (?, ?, ?, ?)",
                    _row(enemy, row_id, True),
                )
