"""Database generation, enemy mutations, and read-only query safeguards."""

from contextlib import closing
from unittest.mock import patch
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest

from select_spire.data import FLOORS, generate_database, mutate_database
from select_spire.db import Query, execute_select


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "run.sqlite3"
        generate_database(self.path, seed=42)

    def rows(self, table):
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(f'SELECT * FROM "{table}" ORDER BY id').fetchall()

    def test_nine_floors_have_weak_rows_and_support(self):
        self.assertEqual(len(FLOORS), 9)
        self.assertEqual(len({enemy.table for enemy in FLOORS}), 9)
        support_ids = {row[0] for row in self.rows("support")}
        for enemy in FLOORS:
            with self.subTest(enemy=enemy.name):
                rows = self.rows(enemy.table)
                self.assertEqual(len(rows), enemy.rows)
                weak_index = enemy.columns.index(enemy.weak_column)
                self.assertEqual(sum(row[weak_index] == "weak" for row in rows), enemy.rows * 4 // 5)
                self.assertTrue({row[0] for row in rows} <= support_ids)

    def test_same_seed_produces_same_data_and_existing_file_is_preserved(self):
        second = Path(self.temp.name) / "second.sqlite3"
        generate_database(second, seed=42)
        with closing(sqlite3.connect(second)) as connection:
            support = connection.execute("SELECT * FROM support ORDER BY id").fetchall()
        self.assertEqual(self.rows("support"), support)
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            generate_database(self.path, seed=7)
        self.assertEqual(self.path.read_bytes(), before)

    def test_mutations_are_local_and_keep_weakness_and_support(self):
        enemy, other = FLOORS[1], FLOORS[0]
        before = self.rows(enemy.table)
        other_before = self.rows(other.table)
        mutate_database(self.path, enemy, "hide", random.Random(42))
        self.assertEqual(self.rows(enemy.table), before)
        mutate_database(self.path, enemy, "null", random.Random(42))
        after_null = self.rows(enemy.table)
        weak_index = enemy.columns.index(enemy.weak_column)
        self.assertEqual([row[weak_index] for row in after_null], [row[weak_index] for row in before])
        self.assertTrue(any(None in row for row in after_null))
        self.assertEqual(self.rows(other.table), other_before)
        mutate_database(self.path, enemy, "grow", random.Random(42))
        grown = self.rows(enemy.table)
        self.assertEqual(len(grown), len(after_null) + 4)
        self.assertTrue(all(row[weak_index] == "weak" for row in grown[-4:]))
        self.assertTrue({row[0] for row in grown} <= {row[0] for row in self.rows("support")})
        self.assertEqual(self.rows(other.table), other_before)
        with self.assertRaises(ValueError):
            mutate_database(self.path, enemy, "unknown", random.Random(42))

    def test_read_only_select_and_rejection_preserve_database(self):
        enemy = FLOORS[0]
        before = self.path.read_bytes()
        result = execute_select(self.path, Query(f'SELECT id FROM "{enemy.table}" WHERE element = ?', ("weak",)))
        self.assertIsNone(result.error)
        self.assertEqual(result.columns, ("id",))
        self.assertEqual(result.row_count, enemy.rows * 4 // 5)
        for sql in (
            f'DELETE FROM "{enemy.table}"',
            f'UPDATE "{enemy.table}" SET element = "bad"',
            'CREATE TABLE danger (id INTEGER)',
            'PRAGMA writable_schema=ON',
            f'SELECT 1; DELETE FROM "{enemy.table}"',
            "SELECT load_extension('not-a-real-extension')",
        ):
            with self.subTest(sql=sql):
                rejected = execute_select(self.path, Query(sql))
                self.assertIsNotNone(rejected.error)
        self.assertEqual(self.path.read_bytes(), before)

    def test_row_cap_and_timeout(self):
        # A cross join makes more than 100 rows without modifying the fixture.
        hundred = execute_select(self.path, Query("SELECT a.id FROM support a CROSS JOIN support b LIMIT 100"))
        self.assertIsNone(hundred.error)
        self.assertEqual(hundred.row_count, 100)
        self.assertFalse(hundred.over_budget)
        extra = execute_select(self.path, Query("SELECT a.id FROM support a CROSS JOIN support b LIMIT 101"))
        self.assertEqual(extra.row_count, 100)
        self.assertTrue(extra.over_budget)
        timed_out = execute_select(self.path, Query("SELECT 1"), timeout_ms=0)
        self.assertTrue(timed_out.over_budget)
        self.assertIsNotNone(timed_out.error)
        # A SELECT that needs many SQLite VM steps must be interruptible as well.
        # Advancing a fake monotonic clock avoids depending on machine speed.
        ticks = iter([0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
        with patch("select_spire.db.time.monotonic", side_effect=lambda: next(ticks, 1.0)):
            interrupted = execute_select(
                self.path,
                Query("SELECT count(*) FROM support a CROSS JOIN support b CROSS JOIN support c CROSS JOIN support d"),
                timeout_ms=100,
            )
        self.assertTrue(interrupted.over_budget)
        self.assertIsNotNone(interrupted.error)


if __name__ == "__main__":
    unittest.main()
