"""Exercise the Tk interface against real, isolated game sessions."""

import unittest
from unittest.mock import patch

try:
    import tkinter as tk
except ImportError:
    tk = None

from select_spire.game import GROUP, JOIN, SCOUT, WHERE

if tk is not None:
    from select_spire import gui


@unittest.skipIf(tk is None, "tkinter is not installed")
class GuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display is unavailable: {exc}")
        self.root.withdraw()
        self.app = None
        self.addCleanup(self._close_app)
        self.app = gui.SpireApp(self.root, seed=42)
        self.root.update_idletasks()

    def _close_app(self):
        if self.app is not None and self.app.game is not None:
            self.app.game.close()
            self.app.game = None
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _widgets(self, parent=None):
        parent = self.app.page if parent is None else parent
        for child in parent.winfo_children():
            yield child
            yield from self._widgets(child)

    def _texts(self):
        return [widget.cget("text") for widget in self._widgets()
                if isinstance(widget, (tk.Label, tk.Button))]

    def _click(self, text):
        buttons = [widget for widget in self._widgets()
                   if isinstance(widget, tk.Button) and text in widget.cget("text")]
        self.assertGreaterEqual(len(buttons), 1, f"Expected a button containing {text!r}")
        buttons[0].invoke()
        self.root.update_idletasks()

    def test_card_selection_validation_and_deselection(self):
        state = self.app.game.state
        state.hand = [WHERE, WHERE, JOIN, GROUP]
        self.app.render()

        self.app.toggle_card(0)
        self.assertEqual(self.app.selected, {0})
        self.assertTrue(any("✓ 選択中  弱点を狙う" in text for text in self._texts()))
        self.app.toggle_card(1)
        self.assertEqual(self.app.selected, {0})
        self.assertTrue(self.app.notice_error)
        self.app.toggle_card(2)
        self.assertEqual(self.app.selected, {0, 2})
        self.app.toggle_card(3)
        self.assertEqual(self.app.selected, {0, 2})
        self.assertTrue(self.app.notice_error)
        self.app.toggle_card(0)
        self.assertEqual(self.app.selected, {2})
        self.assertIsNone(self.app.column)

    def test_scout_preserves_selection_when_hand_indices_shift(self):
        state = self.app.game.state
        state.hand = [SCOUT, WHERE, JOIN]
        state.visible_columns = {"id"}
        self.app.render()
        self._click("選択  弱点を狙う")
        self._click("選ぶ  公開  番号")
        self.assertEqual(self.app.column, "id")
        self._click("即使用  偵察する")
        self.assertEqual(state.hand, [WHERE, JOIN])
        self.assertEqual(self.app.selected, {0})
        self.assertEqual(self.app.column, "id")
        self.assertIn("element", state.visible_columns)
        self.assertIn("element", state.known_columns)
        self.assertFalse(state.attacked)
        self._click("選択  援護を呼ぶ")
        self.assertEqual(self.app.selected, {0, 1})

    def test_where_attack_and_end_turn(self):
        state = self.app.game.state
        state.hand = [WHERE, GROUP]
        state.visible_columns = {"id", state.enemy.weak_column}
        self.app.render()
        self._click("選択  弱点を狙う")
        self._click("攻撃する（カードなしでも可能）")
        self.assertTrue(self.app.notice_error)
        self.assertEqual(state.hand, [WHERE, GROUP])
        self.assertFalse(state.attacked)
        self._click("選ぶ  公開  属性")
        self._click("攻撃する（カードなしでも可能）")
        self.assertTrue(state.attacked)
        self.assertEqual(state.enemy_hp, state.enemy.hp - (state.enemy.rows * 4 // 5) * 2)
        self.assertEqual(state.energy, 2)
        self.assertEqual(state.hand, [GROUP])
        self.assertIn(state.enemy.weak_column, state.known_columns)
        self.assertEqual(self.app.selected, set())
        self.assertIsNone(self.app.column)
        self.assertIn("クリティカル", self.app.notice)
        hp = state.player_hp
        self._click("ターン終了（敵が反撃）")
        self.assertEqual(state.turn, 2)
        self.assertEqual(state.player_hp, hp - state.enemy.attack)
        self.assertFalse(state.attacked)
        self.assertEqual(state.energy, 3)

    def test_reward_selection_advances_floor(self):
        state = self.app.game.state
        state.enemy_hp = 1
        self.app.render()
        self._click("攻撃する（カードなしでも可能）")
        self.assertEqual(state.status, "reward")
        reward = state.rewards[0]
        deck_size = len(state.deck)
        buttons = [widget for widget in self._widgets() if isinstance(widget, tk.Button)]
        self.assertEqual(len(buttons), len(state.rewards))
        buttons[0].invoke()
        self.root.update_idletasks()
        self.assertEqual(state.floor, 1)
        self.assertEqual(state.status, "battle")
        self.assertEqual(len(state.deck), deck_size + 1)
        self.assertIn(reward.card, state.deck)
        self.assertEqual(self.app.selected, set())
        self.assertIsNone(self.app.column)

    def test_hidden_unknown_columns_are_not_rendered_or_leaked_by_attack(self):
        state = self.app.game.state
        state.visible_columns = {"id", "element"}
        state.known_columns.clear()
        self.app.render()
        text = "\n".join(self._texts())
        self.assertEqual(text.count("非公開  ？？？  ／  偵察すると選べます"), 2)
        for hidden in ("armor", "status"):
            self.assertNotIn(hidden, text)
        self.assertNotIn("弱点！", text)
        self._click("攻撃する（カードなしでも可能）")
        text = "\n".join(self._texts())
        for hidden in ("armor", "status"):
            self.assertNotIn(hidden, text)
        self.assertNotIn("SELECT ", self.app.notice)
        self.assertNotIn("弱点！", text)

        state.known_columns.add("armor")
        self.app.render()
        text = "\n".join(self._texts())
        self.assertNotIn("armor", text)
        self.assertNotIn("status", text)

    def test_retry_closes_old_game_and_resets_state(self):
        old_game = self.app.game
        old_path = old_game.path
        state = old_game.state
        state.player_hp = 1
        self.app.render()
        self._click("攻撃せずターン終了（敵が反撃）")
        self.assertEqual(state.status, "lost")
        self._click("もう一度挑戦する")
        self.assertIsNot(self.app.game, old_game)
        self.assertFalse(old_path.exists())
        self.assertTrue(self.app.game.path.exists())
        self.assertEqual(self.app.game.state.status, "battle")
        self.assertEqual(self.app.game.state.floor, 0)
        self.assertEqual(self.app.game.state.player_hp, 50)
        self.assertEqual(self.app.selected, set())
        self.assertIsNone(self.app.column)

    def test_close_releases_game_and_destroys_root(self):
        game = self.app.game
        path = game.path
        self.assertTrue(path.exists())
        self.app.close()
        self.assertIsNone(self.app.game)
        self.assertFalse(path.exists())
        with self.assertRaises(tk.TclError):
            self.root.winfo_exists()

    def test_failed_start_releases_new_game(self):
        old_game = self.app.game
        old_path = old_game.path
        created = []
        real_game = gui.Game

        def new_game(*args, **kwargs):
            game = real_game(*args, **kwargs)
            created.append(game)
            return game

        with patch.object(gui, "Game", side_effect=new_game), patch.object(
                real_game, "start", side_effect=RuntimeError("start failed")):
            with self.assertRaisesRegex(RuntimeError, "start failed"):
                self.app.new_game()
        self.assertFalse(old_path.exists())
        self.assertEqual(len(created), 1)
        self.assertFalse(created[0].path.parent.exists())
        self.assertIsNone(self.app.game)


if __name__ == "__main__":
    unittest.main()
