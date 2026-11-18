"""Japanese, mouse-friendly interface for SELECT Spire."""

from __future__ import annotations

import argparse
import tkinter as tk
from tkinter import messagebox, ttk

from .data import FLOOR_ENEMIES
from .game import Game, GameError


INK = "#17233c"
BACKGROUND = "#e9f0f4"
PAPER = "#ffffff"
HEALTH = "#b44352"
ACCENT = "#246e79"
WEAK = "#a15718"
MUTED = "#526575"
PALE = "#dbe9eb"
BORDER = "#c8d5dd"

CARD_TEXT = {
    "where": ("弱点を狙う", "公開列を指定。弱点の敵だけを狙い、その敵へのダメージ2倍。"),
    "join": ("援護を呼ぶ", "ダメージ+3。隠れた列を1つ公開する。"),
    "group": ("集計する", "全員に最低4ダメージ。散った敵をまとめて削る。"),
    "order": ("並べ替える", "ダメージを最も弱った敵に集中させる。"),
    "limit": ("1体に絞る", "最多ヒットの敵だけに+8ダメージ。"),
    "scout": ("偵察する", "押すとすぐに非公開列を1つ公開し、弱点か調べる。"),
}
COLUMN_NAMES = {
    "id": "番号",
    "element": "属性",
    "armor": "装甲",
    "status": "状態",
}
TRAITS = {
    "hide": "公開列を1つ隠す",
    "null": "データの一部を空にする（通常攻撃が弱まる）",
    "grow": "データを4行増やす",
}


class SpireApp:
    """Render the current Game state and translate clicks into game actions."""

    def __init__(self, root: tk.Tk, seed: int | None = None):
        self.root = root
        self.seed = seed
        self.game: Game | None = None
        self.selected: set[int] = set()
        self.column: str | None = None
        self.notice = "カードを選ばずに攻撃することもできます。"
        self.notice_error = False
        self.wrap_width = 430
        self.root.title("SELECT Spire")
        self.root.geometry("960x850")
        self.root.minsize(560, 400)
        self.root.configure(bg=BACKGROUND)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        # A scrolling page keeps every control reachable on small displays.
        outer = tk.Frame(root, bg=BACKGROUND)
        outer.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(outer, bg=BACKGROUND, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.page = tk.Frame(self.canvas, bg=BACKGROUND)
        self.page_window = self.canvas.create_window((0, 0), window=self.page, anchor="nw")
        self.page.bind("<Configure>", self._page_changed)
        self.canvas.bind("<Configure>", self._canvas_changed)
        self.root.bind_all("<MouseWheel>", self._mousewheel)
        self.root.bind_all("<Button-4>", self._mousewheel)
        self.root.bind_all("<Button-5>", self._mousewheel)
        self.new_game()

    def _page_changed(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _canvas_changed(self, event):
        self.canvas.itemconfigure(self.page_window, width=event.width)
        width = max(180, event.width - 100)
        if width != self.wrap_width:
            self.wrap_width = width
            for widget in self.page.winfo_children():
                self._update_wrap(widget)

    def _update_wrap(self, widget):
        if isinstance(widget, (tk.Label, tk.Button)):
            widget.configure(wraplength=self.wrap_width)
        for child in widget.winfo_children():
            self._update_wrap(child)

    def _mousewheel(self, event):
        if getattr(event, "num", None) == 4:
            amount = -1
        elif getattr(event, "num", None) == 5:
            amount = 1
        else:
            amount = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(amount, "units")

    def close(self):
        try:
            if self.game is not None:
                self.game.close()
                self.game = None
        finally:
            self.root.destroy()

    def new_game(self):
        if self.game is not None:
            self.game.close()
        self.game = Game(seed=self.seed)
        try:
            self.game.start()
        except Exception:
            self.game.close()
            self.game = None
            raise
        self.selected.clear()
        self.column = None
        self.notice = "カードを選ばずに攻撃することもできます。"
        self.notice_error = False
        self.canvas.yview_moveto(0)
        self.render()

    def confirm_new_game(self):
        if messagebox.askyesno(
            "最初からやり直す",
            "現在の階層、HP、獲得したカードなどの進捗が失われます。\n最初からやり直しますか？",
            parent=self.root,
            default=messagebox.NO,
        ):
            self.new_game()

    def _label(self, parent, text, *, size=10, color=INK, bg=PAPER,
               bold=False, wrap=800, **kwargs):
        return tk.Label(parent, text=text, bg=bg, fg=color,
                        font=("TkDefaultFont", size, "bold" if bold else "normal"),
                        anchor="w", justify="left", wraplength=min(wrap, self.wrap_width), **kwargs)

    def _button(self, parent, text, command, *, primary=False, selected=False,
                wrap=700, **kwargs):
        bg = ACCENT if primary or selected else PAPER
        fg = PAPER if primary or selected else INK
        return tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                         activebackground=INK if primary or selected else PALE,
                         activeforeground=PAPER if primary or selected else INK,
                         disabledforeground=MUTED, relief="solid", borderwidth=1,
                         highlightthickness=2, highlightcolor=WEAK,
                         font=("TkDefaultFont", 10), anchor="w", justify="left",
                         wraplength=min(wrap, self.wrap_width), padx=10, pady=6, cursor="hand2", **kwargs)

    def _section(self, parent, title):
        frame = tk.Frame(parent, bg=PAPER, highlightbackground=BORDER,
                         highlightthickness=1, padx=12, pady=8)
        frame.pack(fill="x", pady=(0, 8))
        self._label(frame, title, size=12, bold=True).pack(anchor="w", pady=(0, 4))
        return frame

    @staticmethod
    def _column_name(column):
        return f"{COLUMN_NAMES.get(column, column)}（{column}）"

    def _cost(self, card):
        return max(0, card.cost - int(card.kind in self.game.state.relics))

    def _column_result(self, enemy, column):
        if column not in enemy.known_columns:
            return "未調査"
        return "弱点！" if column == enemy.weak_column else "弱点ではない"

    def _set_notice(self, message, error=False):
        self.notice = message
        self.notice_error = error

    def _action(self, action, success=None):
        try:
            message = action()
        except GameError as exc:
            self._set_notice(str(exc), True)
            self.render()
            return False
        self._set_notice(success if success is not None else message)
        self.render()
        return True

    def toggle_card(self, index):
        state = self.game.state
        if state.status != "battle" or index < 0 or index >= len(state.hand):
            self._set_notice("この手札は使えません。画面を確認してください。", True)
            self.render()
            return
        card = state.hand[index]
        if card.kind == "scout":
            # The hand shifts when scouting consumes a card; preserve selections.
            try:
                message = self.game.play([index])
            except GameError as exc:
                self._set_notice(str(exc), True)
            else:
                self.selected = {i - 1 if i > index else i for i in self.selected}
                self._set_notice(message)
            self.render()
            return
        if state.attacked:
            self._set_notice("このターンは攻撃済みです。偵察するか、ターンを終了してください。", True)
        elif index in self.selected:
            self.selected.remove(index)
            if card.kind == "where":
                self.column = None
            self._set_notice("カードの選択を解除しました。")
        elif any(state.hand[i].kind == card.kind for i in self.selected):
            self._set_notice("同じ種類のカードは1枚までです。先に選択を解除してください。", True)
        else:
            new_cost = sum(self._cost(state.hand[i]) for i in self.selected) + self._cost(card)
            if new_cost > state.energy:
                self._set_notice(f"必要エネルギーは{new_cost}、残りは{state.energy}です。別のカードを解除してください。", True)
            else:
                self.selected.add(index)
                self._set_notice("公開列を選んでください。" if card.kind == "where" else "カードを選択しました。もう一度押すと解除できます。")
        self.render()

    def choose_column(self, column):
        state = self.game.state
        if not any(column in enemy.visible_columns for enemy in state.alive_enemies) or not any(
            state.hand[i].kind == "where" for i in self.selected
        ):
            self._set_notice("弱点を狙うカードを選び、公開列を指定してください。", True)
        else:
            self.column = column
            self._set_notice(f"{self._column_name(column)}を狙います。")
        self.render()

    def attack(self):
        state = self.game.state
        if state.status != "battle" or state.attacked:
            self._set_notice("このターンは攻撃できません。ターンを終了してください。", True)
            self.render()
            return
        cards = [state.hand[i] for i in sorted(self.selected)]
        kinds = [card.kind for card in cards]
        if len(kinds) != len(set(kinds)):
            self._set_notice("同じ種類のカードは1枚までです。", True)
            self.render()
            return
        cost = sum(self._cost(card) for card in cards)
        if cost > state.energy:
            self._set_notice(f"必要エネルギーは{cost}、残りは{state.energy}です。", True)
            self.render()
            return
        if "where" in kinds and not any(
            self.column in enemy.visible_columns for enemy in state.alive_enemies
        ):
            self._set_notice("弱点を狙うカードには、公開列を1つ選んでください。", True)
            self.render()
            return
        indices = sorted(self.selected)
        column = self.column if "where" in kinds else None
        try:
            result = self.game.play(indices, column)
        except GameError as exc:
            self._set_notice(str(exc), True)
        else:
            self.selected.clear()
            self.column = None
            # The query is an implementation detail; report its damage and outcome.
            result = result.split("\n", 1)[-1]
            if self.game.state.status == "battle":
                result += "\n攻撃は1ターンに1回です。偵察するか、ターンを終了してください。"
            self._set_notice(result)
        self.render()

    def end_turn(self):
        try:
            result = self.game.end_turn()
        except GameError as exc:
            self._set_notice(str(exc), True)
        else:
            self.selected.clear()
            self.column = None
            self._set_notice(result)
        self.render()

    def choose_reward(self, index):
        if self._action(lambda: self.game.choose_reward(index)):
            self.selected.clear()
            self.column = None
            self.canvas.yview_moveto(0)

    def render(self):
        state = self.game.state
        for child in self.page.winfo_children():
            child.destroy()

        header = tk.Frame(self.page, bg=INK, padx=16, pady=9)
        header.pack(fill="x")
        self._label(header, "▰  SELECT Spire", size=16, color=PAPER, bg=INK,
                    bold=True).pack(anchor="w")
        self._label(header, "敵のHPを0にすると次へ。あなたのHPは引き継ぎ、0になると敗北。", color="#d8e8ec", bg=INK, wrap=430).pack(anchor="w")
        if state.status in ("battle", "reward"):
            self._button(header, "最初からやり直す", self.confirm_new_game,
                         wrap=400).pack(anchor="w", pady=(6, 0))

        body = tk.Frame(self.page, bg=BACKGROUND, padx=12, pady=10)
        body.pack(fill="both", expand=True)
        guide = "偵察 →『弱点を狙う』カード → 公開列を選ぶ → 攻撃"
        self._label(body, guide, bg=BACKGROUND, color=ACCENT, bold=True,
                    wrap=430).pack(anchor="w", pady=(0, 8))

        overview = self._section(body, f"{state.floor + 1} / {len(FLOOR_ENEMIES)}階　ターン {state.turn}")
        self._label(overview, f"あなたのHP  {state.player_hp} / 50", size=12, color=HEALTH, bold=True, wrap=430).pack(anchor="w")
        for enemy in state.enemies:
            mark = "" if enemy.alive else "（撃破済み）"
            self._label(
                overview,
                f"{enemy.name}{mark}  HP {enemy.hp} / {enemy.max_hp}",
                color=HEALTH if enemy.alive else MUTED,
                bold=enemy.alive,
                wrap=430,
            ).pack(anchor="w", pady=(2, 0))
            if state.status == "battle" and enemy.alive:
                self._label(
                    overview,
                    f"  予告: {enemy.attack}ダメージ ＋ {TRAITS.get(enemy.trait, enemy.trait)}",
                    color=HEALTH,
                    wrap=430,
                ).pack(anchor="w")

        notice_bg = "#fbecef" if self.notice_error else "#e5f1f1"
        notice = tk.Frame(body, bg=notice_bg, padx=10, pady=7)
        notice.pack(fill="x", pady=(0, 8))
        self._label(notice, self.notice, bg=notice_bg,
                    color=HEALTH if self.notice_error else INK, wrap=430).pack(anchor="w")

        if state.status == "battle":
            self._render_battle(body)
        elif state.status == "reward":
            self._render_rewards(body)
        elif state.status in ("won", "lost"):
            self._render_finish(body)

    def _render_battle(self, body):
        state = self.game.state
        actions = self._section(body, "次の行動")
        if not state.attacked:
            selected_cards = [CARD_TEXT[state.hand[i].kind][0] for i in sorted(self.selected)]
            summary = "、".join(selected_cards) if selected_cards else "カードなしの基本攻撃"
            if any(state.hand[i].kind == "where" for i in self.selected):
                summary += f" ／ 狙い: {self._column_name(self.column) if self.column else '未選択'}"
            self._label(actions, f"攻撃の準備: {summary}", color=INK, wrap=430).pack(anchor="w", pady=(0, 4))
        if state.attacked:
            self._label(actions, "攻撃済みです。偵察するか、ターンを終了してください。",
                        color=ACCENT, bold=True, wrap=430).pack(anchor="w", pady=(0, 4))
            self._button(actions, "ターン終了（敵が反撃）", self.end_turn,
                         primary=True, wrap=400).pack(fill="x")
        else:
            self._button(actions, "攻撃する（カードなしでも可能）", self.attack,
                         primary=True, wrap=400).pack(fill="x", pady=(0, 4))
            self._button(actions, "攻撃せずターン終了（敵が反撃）", self.end_turn,
                         wrap=400).pack(fill="x")

        table = self._section(body, "敵のデータ表")
        self._label(table, "『弱点を狙う』カードを選んでから公開列を指定。外すと基本ダメージは0。",
                    color=MUTED, wrap=430).pack(anchor="w")
        where_selected = any(state.hand[i].kind == "where" for i in self.selected)
        for enemy in state.enemies:
            if not enemy.alive:
                continue
            self._label(table, enemy.name, color=INK, bold=True, wrap=430).pack(anchor="w", pady=(6, 0))
            for column in enemy.columns:
                if column in enemy.visible_columns:
                    result = self._column_result(enemy, column)
                    text = f"公開  {self._column_name(column)}  ／  {result}"
                    row = tk.Frame(table, bg=PAPER)
                    row.pack(fill="x", pady=(3, 0))
                    if where_selected and not state.attacked:
                        self._button(row, ("✓ " if self.column == column else "選ぶ  ") + text,
                                     lambda c=column: self.choose_column(c),
                                     selected=self.column == column, wrap=400).pack(fill="x")
                    else:
                        self._label(row, text, color=WEAK if result == "弱点！" else INK,
                                    wrap=430).pack(anchor="w")
                else:
                    text = "非公開  ？？？  ／  偵察すると選べます"
                    self._label(table, text, color=MUTED, wrap=430).pack(anchor="w", pady=(3, 0))

        hand = self._section(body, "手札")
        cost = sum(self._cost(state.hand[i]) for i in self.selected)
        self._label(hand, f"エネルギー  {state.energy}　／　選択中のコスト  {cost}　（同じ種類は1枚まで）",
                    color=ACCENT, bold=True, wrap=430).pack(anchor="w", pady=(0, 4))
        if not state.hand:
            self._label(hand, "手札はありません。カードなしでも攻撃できます。", wrap=430).pack(anchor="w")
        for index, card in enumerate(state.hand):
            title, description = CARD_TEXT.get(card.kind, (card.label, ""))
            chosen = index in self.selected
            prefix = "✓ 選択中  " if chosen else ("即使用  " if card.kind == "scout" else "選択  ")
            text = f"{prefix}{title}（{card.kind.upper()}）　コスト {self._cost(card)}\n{description}"
            self._button(hand, text, lambda i=index: self.toggle_card(i),
                         selected=chosen, wrap=400).pack(fill="x", pady=(0, 4))
        if state.relics:
            names = "、".join(CARD_TEXT[k][0] for k in state.relics if k in CARD_TEXT)
            self._label(hand, f"獲得済み：{names}のコストが1減少", color=MUTED,
                        wrap=430).pack(anchor="w")

    def _render_rewards(self, body):
        section = self._section(body, "敵を撃破！ 報酬を1つ選んで次の階へ")
        for index, reward in enumerate(self.game.state.rewards):
            if reward.card is not None:
                title, description = CARD_TEXT.get(reward.card.kind, (reward.label, ""))
                text = f"{title}（{reward.card.kind.upper()}）を追加　コスト {self._cost(reward.card)}\n{description}"
            elif reward.relic in CARD_TEXT:
                title = CARD_TEXT[reward.relic][0]
                text = f"{title}のコストを1減らす\nこの先ずっと有効"
            else:
                text = f"{reward.label}\n{reward.description}"
            self._button(section, text, lambda i=index: self.choose_reward(i),
                         wrap=400).pack(fill="x", pady=(0, 5))

    def _render_finish(self, body):
        state = self.game.state
        title = "塔を制覇！ 勝利" if state.status == "won" else "HPが0になりました"
        section = self._section(body, title)
        self._label(section, f"到達 {state.floor + 1}階　／　合計 {state.total_turns}ターン",
                    wrap=430).pack(anchor="w", pady=(0, 6))
        self._button(section, "もう一度挑戦する", self.new_game,
                     primary=True, wrap=400).pack(fill="x")
        self._label(section, "再挑戦すると、最初の階から始まります。", color=MUTED,
                    wrap=430).pack(anchor="w", pady=(5, 0))


def main(argv=None):
    parser = argparse.ArgumentParser(description="SELECT Spire の日本語GUI")
    parser.add_argument("--seed", type=int, default=None, help="乱数シードを指定する")
    args = parser.parse_args(argv)
    root = tk.Tk()
    app = None
    try:
        app = SpireApp(root, seed=args.seed)
        root.mainloop()
    finally:
        if app is not None and app.game is not None:
            app.game.close()
            app.game = None
        try:
            root.destroy()
        except tk.TclError:
            pass


if __name__ == "__main__":
    main()
