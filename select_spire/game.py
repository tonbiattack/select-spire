"""Turn-based game rules and safe card-to-query assembly."""

from __future__ import annotations

import random
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .data import FLOORS, EnemyDefinition, generate_database, mutate_database
from .db import Query, execute_select


class GameError(ValueError):
    """An invalid player action that does not change the game state."""


@dataclass(frozen=True)
class Card:
    kind: str
    label: str
    cost: int


WHERE = Card("where", "WHERE 列 = 'weak'（弱点で×2）", 1)
JOIN = Card("join", "JOIN support（ダメージ+5）", 2)
SCOUT = Card("scout", "LIMIT 偵察（隠れた列を1つ公開）", 0)
GROUP = Card("group", "GROUP BY（集計ボーナス+3）", 1)
INITIAL_DECK = (WHERE,) * 5 + (JOIN,) * 3 + (SCOUT,) * 3 + (GROUP,)


@dataclass(frozen=True)
class Reward:
    label: str
    description: str
    card: Card | None = None
    relic: str | None = None


@dataclass
class State:
    player_hp: int = 50
    floor: int = 0
    turn: int = 0
    energy: int = 3
    hand: list[Card] = field(default_factory=list)
    deck: list[Card] = field(default_factory=list)
    enemy: EnemyDefinition | None = None
    enemy_hp: int = 0
    visible_columns: set[str] = field(default_factory=set)
    known_columns: set[str] = field(default_factory=set)
    status: str = "battle"
    rewards: list[Reward] = field(default_factory=list)
    total_turns: int = 0
    relics: list[str] = field(default_factory=list)
    last_message: str = ""
    attacked: bool = False


class Game:
    """One isolated run. Enemy changes are written separately from the read-only query connection."""

    def __init__(self, seed: int | None = None):
        self.seed = seed if seed is not None else random.SystemRandom().randrange(2**63)
        self.rng = random.Random(self.seed)
        self._temp = tempfile.TemporaryDirectory(prefix="select-spire-")
        self.path = Path(self._temp.name) / "run.sqlite3"
        self.state = State(deck=list(INITIAL_DECK))
        self._draw: list[Card] = []
        self._discard: list[Card] = []
        self._started = False

    def start(self) -> None:
        if self._started:
            raise GameError("このランは開始済みです。")
        generate_database(self.path, self.seed)
        self._started = True
        self._start_floor()

    def close(self) -> None:
        self._temp.cleanup()

    def _start_floor(self) -> None:
        s = self.state
        s.enemy = FLOORS[s.floor]
        s.enemy_hp = s.enemy.hp
        # Always reveal id and one other column. Weakness is not automatically revealed.
        others = list(s.enemy.columns[1:])
        self.rng.shuffle(others)
        s.visible_columns = {s.enemy.columns[0], others[0]}
        s.known_columns = set()
        s.status = "battle"
        s.rewards = []
        self._draw = list(s.deck)
        self.rng.shuffle(self._draw)
        self._discard = []
        s.hand = []
        s.turn = 0
        self._start_turn()

    def _start_turn(self) -> None:
        s = self.state
        s.turn += 1
        s.total_turns += 1
        s.energy = 3
        s.attacked = False
        while len(s.hand) < 5:
            if not self._draw:
                if not self._discard:
                    break
                self._draw, self._discard = self._discard, []
                self.rng.shuffle(self._draw)
            s.hand.append(self._draw.pop())

    def _cost(self, card: Card) -> int:
        return max(0, card.cost - int(card.kind in self.state.relics))

    def play(self, indices: list[int], column: str | None = None) -> str:
        s = self.state
        if s.status != "battle" or s.enemy is None:
            raise GameError("今はカードを使えません。")
        if len(indices) != len(set(indices)) or any(i < 0 or i >= len(s.hand) for i in indices):
            raise GameError("手札番号が不正か重複しています。")
        cards = [s.hand[i] for i in indices]
        kinds = [card.kind for card in cards]
        if "scout" in kinds:
            if kinds != ["scout"] or column is not None:
                raise GameError("偵察は1枚だけ単独で使います。")
            hidden = [c for c in s.enemy.columns if c not in s.visible_columns]
            if not hidden:
                raise GameError("公開できる列はありません。")
            result = execute_select(self.path, Query(f'SELECT * FROM "{s.enemy.table}" LIMIT 1'))
            if result.error or result.over_budget:
                raise GameError("偵察クエリを実行できませんでした。")
            s.visible_columns.add(hidden[0])
            s.known_columns.add(hidden[0])
            s.hand.pop(indices[0])
            self._discard.append(SCOUT)
            hint = "弱点列！ WHEREで狙おう。" if hidden[0] == s.enemy.weak_column else "弱点ではない。"
            s.last_message = f"偵察成功：列 {hidden[0]} を公開。{hint}（ダメージ0）"
            return s.last_message
        if s.attacked:
            raise GameError("このターンは攻撃済みです。end でターンを終了してください。")
        if len(kinds) != len(set(kinds)):
            raise GameError("同じ種類の句は1枚までです。")
        if any(k not in {"where", "join", "group"} for k in kinds):
            raise GameError("攻撃に使えないカードです。")
        if ("where" in kinds) != (column is not None):
            raise GameError("WHEREカード使用時は --where 公開列名 を指定してください。")
        if column is not None and column not in s.visible_columns:
            raise GameError("WHEREには公開済みの列を指定してください。")
        cost = sum(self._cost(card) for card in cards)
        if cost > s.energy:
            raise GameError("エネルギーが足りません。")
        # Baseline scanning ignores damaged rows; WHERE can target an intact column.
        selected = f't."{column}"' if column is not None else 't.id'
        sql = f'SELECT {selected} FROM "{s.enemy.table}" AS t'
        if "join" in kinds:
            sql += ' JOIN support AS s ON t.id = s.id'
        params: tuple[str, ...] = ()
        if column is not None:
            # Only identifiers from the fixed, revealed enemy schema can reach here.
            sql += f' WHERE t."{column}" = ?'
            params = ("weak",)
        else:
            # All columns stay private even though SQL still tests their NULL status.
            sql += ' WHERE t.element IS NOT NULL AND t.armor IS NOT NULL AND t.status IS NOT NULL'
        if "group" in kinds:
            sql += ' GROUP BY t.id'
        sql += ' LIMIT 100'
        result = execute_select(self.path, Query(sql, params))
        if result.error or result.over_budget:
            raise GameError(f"クエリ失敗／コスト超過（{result.elapsed_ms:.1f}ms）。カードは消費されません。")
        damage = min(result.row_count, 20) + (5 if "join" in kinds else 0) + (3 if "group" in kinds else 0)
        critical = column == s.enemy.weak_column
        if critical:
            damage *= 2
        s.energy -= cost
        s.attacked = True
        if column is not None:
            s.known_columns.add(column)
        for i in sorted(indices, reverse=True):
            self._discard.append(s.hand.pop(i))
        s.enemy_hp = max(0, s.enemy_hp - damage)
        shown_sql = sql.replace("?", "'weak'")
        if column is None:
            shown_sql = shown_sql.replace(
                't.element IS NOT NULL AND t.armor IS NOT NULL AND t.status IS NOT NULL',
                '[データ列のNULLを除外]',
            )
        details = f"実行クエリの概略（非公開列は伏せ字）: {shown_sql}\n{result.row_count}行 / {result.elapsed_ms:.1f}ms => {damage}ダメージ"
        if column is None:
            details += "（通常スキャンはNULL行を除外）"
        if column is not None and not critical:
            details += f"。{column} は弱点ではない"
        if critical:
            details += "！ 弱点クリティカル ×2"
        if "join" in kinds:
            details += "（JOIN +5）"
        if "group" in kinds:
            details += "（GROUP BY +3）"
        if s.enemy_hp == 0:
            if s.floor == len(FLOORS) - 1:
                s.status = "won"
                details += f"\nボス撃破！ 勝利！ 残HP {s.player_hp} / 合計 {s.total_turns}ターン。"
            else:
                s.status = "reward"
                s.rewards = self._make_rewards()
                details += "\n撃破！ 報酬を1つ選んでください。"
        s.last_message = details
        return details

    def _make_rewards(self) -> list[Reward]:
        cards = self.rng.sample([WHERE, JOIN, SCOUT, GROUP], 2)
        available = [kind for kind in ("where", "join", "group") if kind not in self.state.relics]
        if available:
            kind = self.rng.choice(available)
            relic = Reward(f"{kind.upper()} インデックス", f"{kind.upper()} のコストを1減らす", relic=kind)
        else:
            relic = Reward("偵察カード", "偵察カードをデッキに追加", card=SCOUT)
        return [Reward(card.label, "このカードをデッキに追加", card=card) for card in cards] + [relic]

    def end_turn(self) -> str:
        s = self.state
        if s.status != "battle" or s.enemy is None:
            raise GameError("今はターンを終了できません。")
        remaining_hp = max(0, s.player_hp - s.enemy.attack)
        text = f"敵の反撃：{s.enemy.attack}ダメージ。"
        if remaining_hp == 0:
            s.player_hp = 0
            s.status = "lost"
            s.last_message = text + f" HP 0、敗北。到達 {s.floor + 1}階 / 合計 {s.total_turns}ターン。"
            return s.last_message
        trait = s.enemy.trait
        if trait in ("null", "grow"):
            try:
                mutate_database(self.path, s.enemy, trait, self.rng)
            except (OSError, sqlite3.Error) as exc:
                raise GameError(f"敵の反撃を適用できませんでした: {exc}") from exc
        s.player_hp = remaining_hp
        if trait == "hide":
            candidates = [c for c in s.enemy.columns if c != "id" and c in s.visible_columns]
            if candidates:
                hidden = self.rng.choice(candidates)
                s.visible_columns.remove(hidden)
                text += f" 列 {hidden} が隠された。"
            else:
                text += " 隠せる列はなかった。"
        elif trait in ("null", "grow"):
            text += " NULLを混入。" if trait == "null" else " 行が4件増加。"
        self._discard.extend(s.hand)
        s.hand = []
        self._start_turn()
        s.last_message = text
        return text

    def choose_reward(self, index: int) -> str:
        s = self.state
        if s.status != "reward" or index < 0 or index >= len(s.rewards):
            raise GameError("報酬番号が不正です。")
        reward = s.rewards[index]
        if reward.card is not None:
            s.deck.append(reward.card)
        if reward.relic is not None:
            s.relics.append(reward.relic)
        s.floor += 1
        self._start_floor()
        s.last_message = f"{reward.label} を獲得。次の階へ。"
        return s.last_message
