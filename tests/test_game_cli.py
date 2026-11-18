"""Game rules and command validation using deterministic isolated runs."""

import unittest
from contextlib import closing
from unittest.mock import patch
import sqlite3

from select_spire import cli
from select_spire.data import FLOOR_ENEMIES
from select_spire.db import QueryResult
from select_spire.game import Game, GameError, GROUP, JOIN, LIMIT, ORDER, SCOUT, WHERE


class GameTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(seed=42)
        self.addCleanup(self.game.close)
        self.game.start()
        self.state = self.game.state

    def test_start_and_end_turn(self):
        s = self.state
        self.assertEqual(s.floor, 0)
        self.assertEqual([e.name for e in s.enemies], [e.name for e in FLOOR_ENEMIES[0]])
        self.assertEqual(s.turn, 1)
        self.assertEqual(s.energy, 3)
        self.assertEqual(len(s.hand), 5)
        self.assertEqual(len(s.deck), 12)
        hp = s.player_hp
        incoming = sum(e.attack for e in s.alive_enemies)
        self.game.end_turn()
        self.assertEqual(s.player_hp, hp - incoming)
        self.assertEqual(s.turn, 2)
        self.assertEqual(s.energy, 3)
        self.assertFalse(s.attacked)
        self.assertIn("id", s.enemies[0].visible_columns)

    def test_weakness_join_and_card_consumption(self):
        s = self.state
        s.hand = [WHERE, JOIN, SCOUT]
        enemy = s.enemies[0]
        weak = enemy.weak_column
        enemy.visible_columns.add(weak)
        hp = enemy.hp
        self.game.play([0, 1], weak)
        expected = min(enemy.definition.rows * 4 // 5, 20) * 2 + 3
        self.assertEqual(enemy.hp, max(0, hp - expected))
        self.assertEqual(s.energy, 0)
        self.assertEqual(s.hand, [SCOUT])
        self.assertIn(weak, enemy.known_columns)
        with self.assertRaises(GameError):
            self.game.play([])

    def test_join_and_group_attack(self):
        s = self.state
        s.hand = [JOIN, GROUP]
        enemy = s.enemies[0]
        hp = enemy.hp
        self.game.play([0, 1])
        # GROUP BY guarantees at least 4 damage; JOIN adds 3 on top of the hits.
        self.assertLess(enemy.hp, hp)
        self.assertEqual(s.energy, 0)
        self.assertEqual(s.hand, [])

    def test_wrong_column_does_not_damage(self):
        s = self.state
        s.hand = [WHERE]
        enemy = s.enemies[0]
        nonweak = next(column for column in enemy.columns[1:] if column != enemy.weak_column)
        enemy.visible_columns.add(nonweak)
        hp = enemy.hp
        with self.assertRaises(GameError):
            self.game.play([0], nonweak)
        self.assertEqual(enemy.hp, hp)
        self.assertEqual(s.energy, 3)
        self.assertFalse(s.attacked)

    def test_scout_reveals_column_without_attacking(self):
        s = self.state
        s.hand = [SCOUT, WHERE]
        enemy = s.enemies[0]
        before = set(enemy.visible_columns)
        hp, energy = enemy.hp, s.energy
        self.game.play([0])
        revealed = enemy.visible_columns - before
        self.assertEqual(len(revealed), 1)
        self.assertTrue(revealed <= enemy.known_columns)
        self.assertEqual((enemy.hp, s.energy), (hp, energy))
        self.assertFalse(s.attacked)
        self.assertEqual(s.hand, [WHERE])

    def test_invalid_actions_and_failed_query_do_not_consume_cards(self):
        s = self.state
        s.hand = [WHERE, JOIN, GROUP, SCOUT]
        enemy = s.enemies[0]
        enemy.visible_columns = {"id"}
        for indices, column in (([0, 0], "id"), ([4], None), ([0], None), ([0], "element"), ([0, 1, 2], "id"), ([3, 0], "id")):
            with self.subTest(indices=indices, column=column):
                before = (list(s.hand), s.energy, enemy.hp, s.attacked)
                with self.assertRaises(GameError):
                    self.game.play(indices, column)
                self.assertEqual((s.hand, s.energy, enemy.hp, s.attacked), before)
        failed = QueryResult(0, (), 1.0, error="query failed")
        with patch("select_spire.game.execute_select", return_value=failed):
            before = (list(s.hand), s.energy, enemy.hp, s.attacked)
            with self.assertRaises(GameError):
                self.game.play([1])
            self.assertEqual((s.hand, s.energy, enemy.hp, s.attacked), before)

    def test_rewards_advance_floor_and_add_chosen_card(self):
        s = self.state
        for enemy in s.enemies:
            enemy.hp = 1
        self.game.play([])
        self.assertEqual(s.status, "reward")
        self.assertTrue(s.rewards)
        with self.assertRaises(GameError):
            self.game.choose_reward(len(s.rewards))
        reward = s.rewards[0]
        deck_size = len(s.deck)
        self.game.choose_reward(0)
        self.assertEqual(s.floor, 1)
        self.assertEqual([e.name for e in s.enemies], [e.name for e in FLOOR_ENEMIES[1]])
        self.assertEqual(s.status, "battle")
        if reward.card is not None:
            self.assertEqual(len(s.deck), deck_size + 1)
            self.assertIn(reward.card, s.deck)
        elif reward.relic is not None:
            self.assertIn(reward.relic, s.relics)

    def test_relic_reward_reduces_cost(self):
        s = self.state
        for enemy in s.enemies:
            enemy.hp = 1
        self.game.play([])
        index = next(i for i, reward in enumerate(s.rewards) if reward.relic is not None)
        kind = s.rewards[index].relic
        self.game.choose_reward(index)
        self.assertIn(kind, s.relics)
        card = {"where": WHERE, "join": JOIN, "group": GROUP, "order": ORDER, "limit": LIMIT}[kind]
        self.assertEqual(self.game._cost(card), max(0, card.cost - 1))

    def test_win_and_loss(self):
        s = self.state
        s.floor = len(FLOOR_ENEMIES) - 1
        self.game._start_floor()
        for enemy in s.enemies:
            enemy.hp = 1
        # The final floor has several enemies, so GROUP BY is needed to clear it.
        s.hand = [GROUP]
        self.game.play([0])
        self.assertEqual(s.status, "won")
        with self.assertRaises(GameError):
            self.game.end_turn()

        other = Game(seed=42)
        self.addCleanup(other.close)
        other.start()
        other.state.player_hp = 1
        other.end_turn()
        self.assertEqual(other.state.player_hp, 0)
        self.assertEqual(other.state.status, "lost")
        with self.assertRaises(GameError):
            other.play([])

    def test_hidden_columns_do_not_leak_in_attack_output(self):
        s = self.state
        enemy = s.enemies[0]
        enemy.visible_columns = {"id", "element"}
        output = self.game.play([])
        self.assertNotIn("armor", output)
        self.assertNotIn("status", output)

    def test_nulls_reduce_basic_attack_but_not_weak_targeting(self):
        s = self.state
        enemy = s.enemies[0]
        with closing(sqlite3.connect(self.game.path)) as connection, connection:
            nonweak = next(c for c in enemy.columns[1:] if c != enemy.weak_column)
            connection.execute(f'UPDATE "{enemy.table}" SET "{nonweak}" = NULL')
        hp = enemy.hp
        with self.assertRaises(GameError):
            self.game.play([])
        self.assertEqual(enemy.hp, hp)
        self.game.end_turn()
        s.hand = [WHERE]
        enemy.visible_columns.add(enemy.weak_column)
        self.game.play([0], enemy.weak_column)
        self.assertLess(enemy.hp, hp)

    def test_failed_mutation_does_not_consume_turn_or_hp(self):
        s = self.state
        s.floor = 1
        self.game._start_floor()
        before = (s.player_hp, s.turn, list(s.hand))
        with patch("select_spire.game.mutate_database", side_effect=sqlite3.OperationalError("failed")):
            with self.assertRaises(GameError):
                self.game.end_turn()
        self.assertEqual((s.player_hp, s.turn, s.hand), before)


class MultiEnemyTests(unittest.TestCase):
    """Issue #9: several enemies per battle and clause-specific roles."""

    def setUp(self):
        self.game = Game(seed=42)
        self.addCleanup(self.game.close)
        self.game.start()
        self.state = self.game.state
        self.state.floor = 1
        self.game._start_floor()

    def test_floor_has_multiple_enemies(self):
        self.assertGreaterEqual(len(self.state.enemies), 2)
        self.assertEqual(len(self.state.alive_enemies), len(self.state.enemies))

    def test_group_by_hits_every_enemy(self):
        s = self.state
        s.hand = [GROUP]
        before = {enemy.name: enemy.hp for enemy in s.enemies}
        self.game.play([0])
        for enemy in s.enemies:
            self.assertLess(enemy.hp, before[enemy.name])

    def test_order_by_concentrates_damage_on_weakest(self):
        s = self.state
        s.hand = [ORDER]
        weakest = min(s.enemies, key=lambda enemy: enemy.hp)
        others = [enemy for enemy in s.enemies if enemy is not weakest]
        before = {enemy.name: enemy.hp for enemy in s.enemies}
        self.game.play([0])
        self.assertLess(weakest.hp, before[weakest.name])
        for enemy in others:
            self.assertEqual(enemy.hp, before[enemy.name])

    def test_limit_restricts_to_one_target(self):
        s = self.state
        s.hand = [LIMIT]
        before = {enemy.name: enemy.hp for enemy in s.enemies}
        self.game.play([0])
        damaged = [enemy for enemy in s.enemies if enemy.hp < before[enemy.name]]
        self.assertEqual(len(damaged), 1)

    def test_join_reveals_a_hidden_column(self):
        s = self.state
        s.hand = [JOIN]
        # JOIN alone can defeat a weak floor; keep the enemies alive to observe it.
        for enemy in s.enemies:
            enemy.hp = 99
        hidden_before = sum(
            len(enemy.columns) - len(enemy.visible_columns) for enemy in s.enemies
        )
        self.game.play([0])
        hidden_after = sum(
            len(enemy.columns) - len(enemy.visible_columns) for enemy in s.enemies
        )
        self.assertEqual(hidden_after, hidden_before - 1)
    def test_defeated_enemy_stops_attacking(self):
        s = self.state
        s.enemies[0].hp = 0
        incoming = sum(enemy.attack for enemy in s.alive_enemies)
        hp = s.player_hp
        self.game.end_turn()
        self.assertEqual(s.player_hp, hp - incoming)

    def test_battle_ends_only_when_all_enemies_fall(self):
        s = self.state
        s.enemies[0].hp = 1
        s.enemies[1].hp = 99
        s.hand = [GROUP]
        self.game.play([0])
        self.assertEqual(s.status, "battle")
        self.assertEqual(len(s.alive_enemies), 1)
        s.attacked = False
        s.hand = [GROUP]
        s.enemies[1].hp = 1
        self.game.play([0])
        self.assertEqual(s.status, "reward")

    def test_two_valid_routes_exist(self):
        """Weakness targeting and GROUP BY splash are both viable plans."""
        s = self.state
        enemy = s.enemies[0]
        weak = enemy.weak_column
        enemy.visible_columns.add(weak)
        s.hand = [WHERE]
        hp_before = enemy.hp
        self.game.play([0], weak)
        weakness_damage = hp_before - enemy.hp
        self.assertGreater(weakness_damage, 0)

        other = Game(seed=42)
        self.addCleanup(other.close)
        other.start()
        other.state.floor = 1
        other._start_floor()
        other.state.hand = [GROUP]
        before = {e.name: e.hp for e in other.state.enemies}
        other.play([0])
        splash_targets = sum(1 for e in other.state.enemies if e.hp < before[e.name])
        self.assertGreaterEqual(splash_targets, 2)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(seed=42)
        self.addCleanup(self.game.close)
        self.game.start()
        self.game.state.hand = [WHERE, SCOUT]
        self.game.state.enemies[0].visible_columns = {"id", self.game.state.enemies[0].weak_column}

    def test_hand_number_validation(self):
        self.assertEqual(cli._hand_number("1"), 0)
        self.assertEqual(cli._hand_number("2"), 1)
        for value in ("0", "-1", "abc", "1.5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cli._hand_number(value)

    def test_battle_commands_reject_invalid_input(self):
        for command in ("", "unknown", "end extra", "scout", "scout 0", "scout 1", "scout 3", "attack --where", "attack 1 --where missing", "attack x"):
            with self.subTest(command=command):
                with self.assertRaises((ValueError, GameError)):
                    cli._battle_command(self.game, command)
        with self.assertRaises((ValueError, GameError)):
            cli._battle_command(self.game, "attack 1 1 --where " + self.game.state.enemies[0].weak_column)

    def test_commands_use_one_based_indices(self):
        enemy = self.game.state.enemies[0]
        before = set(enemy.visible_columns)
        cli._battle_command(self.game, "scout 2")
        self.assertEqual(len(enemy.visible_columns - before), 1)
        self.assertEqual(self.game.state.hand, [WHERE])
        cli._battle_command(self.game, "attack 1 --where " + enemy.weak_column)
        self.assertEqual(self.game.state.hand, [])

    def test_reward_input_validation(self):
        state = self.game.state
        for enemy in state.enemies:
            enemy.hp = 1
        self.game.play([])
        for command in ("", "x", "0", "-1", str(len(state.rewards) + 1)):
            with self.subTest(command=command), self.assertRaises(ValueError):
                cli._choose_reward(self.game, command)
        cli._choose_reward(self.game, "1")
        self.assertEqual(state.floor, 1)

    def test_telegraph_is_shown_only_during_battle(self):
        from contextlib import redirect_stdout
        from io import StringIO
        for status in ("battle", "reward", "won", "lost"):
            self.game.state.status = status
            output = StringIO()
            with redirect_stdout(output):
                cli._show_state(self.game.state)
            self.assertEqual("予告" in output.getvalue(), status == "battle")


if __name__ == "__main__":
    unittest.main()
