"""Game rules and command validation using deterministic isolated runs."""

import unittest
from contextlib import closing
from unittest.mock import patch

from select_spire import cli
from select_spire.data import FLOORS
from select_spire.db import QueryResult
from select_spire.game import Game, GameError, GROUP, JOIN, SCOUT, WHERE


class GameTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(seed=42)
        self.addCleanup(self.game.close)
        self.game.start()
        self.state = self.game.state

    def test_start_and_end_turn(self):
        s = self.state
        self.assertEqual(s.floor, 0)
        self.assertEqual(s.enemy, FLOORS[0])
        self.assertEqual(s.turn, 1)
        self.assertEqual(s.energy, 3)
        self.assertEqual(len(s.hand), 5)
        hp = s.player_hp
        self.game.end_turn()
        self.assertEqual(s.player_hp, hp - s.enemy.attack)
        self.assertEqual(s.turn, 2)
        self.assertEqual(s.energy, 3)
        self.assertFalse(s.attacked)
        self.assertIn("id", s.visible_columns)

    def test_weakness_join_and_card_consumption(self):
        s = self.state
        s.hand = [WHERE, JOIN, SCOUT]
        weak = s.enemy.weak_column
        s.visible_columns.add(weak)
        hp = s.enemy_hp
        self.game.play([0, 1], weak)
        self.assertEqual(s.enemy_hp, max(0, hp - (s.enemy.rows * 4 // 5 + 5) * 2))
        self.assertEqual(s.energy, 0)
        self.assertEqual(s.hand, [SCOUT])
        self.assertIn(weak, s.known_columns)
        with self.assertRaises(GameError):
            self.game.play([])

    def test_join_and_group_attack(self):
        s = self.state
        s.hand = [JOIN, GROUP]
        hp = s.enemy_hp
        self.game.play([0, 1])
        self.assertEqual(s.enemy_hp, max(0, hp - (min(s.enemy.rows, 20) + 5 + 3)))
        self.assertEqual(s.energy, 0)
        self.assertEqual(s.hand, [])

    def test_wrong_column_does_not_critical(self):
        s = self.state
        s.hand = [WHERE]
        nonweak = next(column for column in s.enemy.columns[1:] if column != s.enemy.weak_column)
        s.visible_columns.add(nonweak)
        hp = s.enemy_hp
        self.game.play([0], nonweak)
        self.assertEqual(s.enemy_hp, hp)
        self.assertEqual(s.energy, 2)
        self.assertIn(nonweak, s.known_columns)

    def test_scout_reveals_column_without_attacking(self):
        s = self.state
        s.hand = [SCOUT, WHERE]
        before = set(s.visible_columns)
        hp, energy = s.enemy_hp, s.energy
        self.game.play([0])
        revealed = s.visible_columns - before
        self.assertEqual(len(revealed), 1)
        self.assertTrue(revealed <= s.known_columns)
        self.assertEqual((s.enemy_hp, s.energy), (hp, energy))
        self.assertFalse(s.attacked)
        self.assertEqual(s.hand, [WHERE])

    def test_invalid_actions_and_failed_query_do_not_consume_cards(self):
        s = self.state
        s.hand = [WHERE, JOIN, GROUP, SCOUT]
        s.visible_columns = {"id"}
        for indices, column in (([0, 0], "id"), ([4], None), ([0], None), ([0], "element"), ([0, 1, 2], "id"), ([3, 0], "id")):
            with self.subTest(indices=indices, column=column):
                before = (list(s.hand), s.energy, s.enemy_hp, s.attacked)
                with self.assertRaises(GameError):
                    self.game.play(indices, column)
                self.assertEqual((s.hand, s.energy, s.enemy_hp, s.attacked), before)
        failed = QueryResult(0, (), 1.0, error="query failed")
        with patch("select_spire.game.execute_select", return_value=failed):
            before = (list(s.hand), s.energy, s.enemy_hp, s.attacked)
            with self.assertRaises(GameError):
                self.game.play([1])
            self.assertEqual((s.hand, s.energy, s.enemy_hp, s.attacked), before)

    def test_rewards_advance_floor_and_add_chosen_card(self):
        s = self.state
        s.enemy_hp = 1
        self.game.play([])
        self.assertEqual(s.status, "reward")
        self.assertTrue(s.rewards)
        with self.assertRaises(GameError):
            self.game.choose_reward(len(s.rewards))
        reward = s.rewards[0]
        deck_size = len(s.deck)
        self.game.choose_reward(0)
        self.assertEqual(s.floor, 1)
        self.assertEqual(s.enemy, FLOORS[1])
        self.assertEqual(s.status, "battle")
        if reward.card is not None:
            self.assertEqual(len(s.deck), deck_size + 1)
            self.assertIn(reward.card, s.deck)
        elif reward.relic is not None:
            self.assertIn(reward.relic, s.relics)

    def test_relic_reward_reduces_cost(self):
        s = self.state
        s.enemy_hp = 1
        self.game.play([])
        index = next(i for i, reward in enumerate(s.rewards) if reward.relic is not None)
        kind = s.rewards[index].relic
        self.game.choose_reward(index)
        self.assertIn(kind, s.relics)
        card = {"where": WHERE, "join": JOIN, "group": GROUP}[kind]
        self.assertEqual(self.game._cost(card), max(0, card.cost - 1))

    def test_hidden_columns_do_not_leak_in_attack_output(self):
        s = self.state
        s.visible_columns = {"id", "element"}
        output = self.game.play([])
        self.assertNotIn("armor", output)
        self.assertNotIn("status", output)

    def test_nulls_reduce_basic_attack_but_not_weak_targeting(self):
        import sqlite3
        s = self.state
        with closing(sqlite3.connect(self.game.path)) as connection, connection:
            nonweak = next(c for c in s.enemy.columns[1:] if c != s.enemy.weak_column)
            connection.execute(f'UPDATE "{s.enemy.table}" SET "{nonweak}" = NULL')
        hp = s.enemy_hp
        self.game.play([])
        self.assertEqual(s.enemy_hp, hp)
        self.game.end_turn()
        s.hand = [WHERE]
        s.visible_columns.add(s.enemy.weak_column)
        self.game.play([0], s.enemy.weak_column)
        self.assertLess(s.enemy_hp, hp)

    def test_failed_mutation_does_not_consume_turn_or_hp(self):
        import sqlite3
        s = self.state
        s.floor = 1
        self.game._start_floor()
        before = (s.player_hp, s.turn, list(s.hand))
        with patch("select_spire.game.mutate_database", side_effect=sqlite3.OperationalError("failed")):
            with self.assertRaises(GameError):
                self.game.end_turn()
        self.assertEqual((s.player_hp, s.turn, s.hand), before)

    def test_win_and_loss(self):
        s = self.state
        s.floor = len(FLOORS) - 1
        s.enemy = FLOORS[-1]
        s.enemy_hp = 1
        self.game.play([])
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


class CliTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(seed=42)
        self.addCleanup(self.game.close)
        self.game.start()
        self.game.state.hand = [WHERE, SCOUT]
        self.game.state.visible_columns = {"id", self.game.state.enemy.weak_column}

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
            cli._battle_command(self.game, "attack 1 1 --where " + self.game.state.enemy.weak_column)

    def test_commands_use_one_based_indices(self):
        before = set(self.game.state.visible_columns)
        cli._battle_command(self.game, "scout 2")
        self.assertEqual(len(self.game.state.visible_columns - before), 1)
        self.assertEqual(self.game.state.hand, [WHERE])
        cli._battle_command(self.game, "attack 1 --where " + self.game.state.enemy.weak_column)
        self.assertEqual(self.game.state.hand, [])

    def test_telegraph_is_shown_only_during_battle(self):
        from contextlib import redirect_stdout
        from io import StringIO
        for status in ("battle", "reward", "won", "lost"):
            self.game.state.status = status
            output = StringIO()
            with redirect_stdout(output):
                cli._show_state(self.game.state)
            self.assertEqual("敵の予告" in output.getvalue(), status == "battle")

    def test_reward_input_validation(self):
        self.game.state.enemy_hp = 1
        self.game.play([])
        for command in ("", "x", "0", "-1", str(len(self.game.state.rewards) + 1)):
            with self.subTest(command=command), self.assertRaises(ValueError):
                cli._choose_reward(self.game, command)
        cli._choose_reward(self.game, "1")
        self.assertEqual(self.game.state.floor, 1)


if __name__ == "__main__":
    unittest.main()
