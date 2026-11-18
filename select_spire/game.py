"""Turn-based game rules and safe card-to-query assembly.

A battle holds one to three enemies. Every attack runs one real SELECT against
the floor's ``battle_<n>`` view, and the per-enemy hit counts that come back
decide the damage. Each SQL clause therefore has its own tactical role instead
of being a flat damage bonus.
"""

from __future__ import annotations

import random
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .data import (
    FLOOR_ENEMIES,
    EnemyDefinition,
    battle_view,
    generate_database,
    mutate_database,
)
from .db import Query, execute_select


class GameError(ValueError):
    """An invalid player action that does not change the game state."""


@dataclass(frozen=True)
class Card:
    kind: str
    label: str
    cost: int


WHERE = Card("where", "WHERE 列 = 'weak'（弱点の敵だけを狙う）", 1)
JOIN = Card("join", "JOIN support（+3ダメージ＆隠れた列を1つ公開）", 2)
GROUP = Card("group", "GROUP BY（全員に最低4ダメージ）", 1)
ORDER = Card("order", "ORDER BY（ダメージを最も弱った敵に集中）", 1)
LIMIT = Card("limit", "LIMIT 1（最多ヒットの敵に+8ダメージ）", 1)
SCOUT = Card("scout", "LIMIT 偵察（隠れた列を1つ公開）", 0)
INITIAL_DECK = (WHERE,) * 4 + (JOIN,) * 2 + (SCOUT,) * 3 + (GROUP, ORDER, LIMIT)

CARD_KINDS = frozenset({"where", "join", "group", "order", "limit"})
ATTACK_KINDS = CARD_KINDS


@dataclass(frozen=True)
class Reward:
    label: str
    description: str
    card: Card | None = None
    relic: str | None = None


@dataclass(eq=False)
class EnemyState:
    definition: EnemyDefinition
    hp: int
    visible_columns: set[str] = field(default_factory=set)
    known_columns: set[str] = field(default_factory=set)

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def table(self) -> str:
        return self.definition.table

    @property
    def max_hp(self) -> int:
        return self.definition.hp

    @property
    def attack(self) -> int:
        return self.definition.attack

    @property
    def trait(self) -> str:
        return self.definition.trait

    @property
    def weak_column(self) -> str:
        return self.definition.weak_column

    @property
    def columns(self) -> tuple[str, ...]:
        return self.definition.columns


@dataclass
class State:
    player_hp: int = 50
    floor: int = 0
    turn: int = 0
    energy: int = 3
    hand: list[Card] = field(default_factory=list)
    deck: list[Card] = field(default_factory=list)
    enemies: list[EnemyState] = field(default_factory=list)
    status: str = "battle"
    rewards: list[Reward] = field(default_factory=list)
    total_turns: int = 0
    relics: list[str] = field(default_factory=list)
    last_message: str = ""
    attacked: bool = False

    @property
    def enemy(self) -> EnemyState | None:
        """First living enemy, kept for callers that only need one target."""
        return next((enemy for enemy in self.enemies if enemy.alive), None)

    @property
    def alive_enemies(self) -> list[EnemyState]:
        return [enemy for enemy in self.enemies if enemy.alive]


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
        s.enemies = []
        for definition in FLOOR_ENEMIES[s.floor]:
            # Always reveal id and one other column. Weakness is not automatically revealed.
            others = list(definition.columns[1:])
            self.rng.shuffle(others)
            s.enemies.append(
                EnemyState(
                    definition=definition,
                    hp=definition.hp,
                    visible_columns={definition.columns[0], others[0]},
                )
            )
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

    def _view(self) -> str:
        return battle_view(self.state.floor)

    def play(self, indices: list[int], column: str | None = None) -> str:
        s = self.state
        if s.status != "battle" or not s.alive_enemies:
            raise GameError("今はカードを使えません。")
        if len(indices) != len(set(indices)) or any(i < 0 or i >= len(s.hand) for i in indices):
            raise GameError("手札番号が不正か重複しています。")
        cards = [s.hand[i] for i in indices]
        kinds = [card.kind for card in cards]
        if "scout" in kinds:
            if kinds != ["scout"] or column is not None:
                raise GameError("偵察は1枚だけ単独で使います。")
            return self._scout(indices[0])
        if s.attacked:
            raise GameError("このターンは攻撃済みです。end でターンを終了してください。")
        if len(kinds) != len(set(kinds)):
            raise GameError("同じ種類の句は1枚までです。")
        if any(kind not in ATTACK_KINDS for kind in kinds):
            raise GameError("攻撃に使えないカードです。")
        if ("where" in kinds) != (column is not None):
            raise GameError("WHEREカード使用時は --where 公開列名 を指定してください。")
        if column is not None and not any(
            column in enemy.visible_columns for enemy in s.alive_enemies
        ):
            raise GameError("WHEREには公開済みの列を指定してください。")
        cost = sum(self._cost(card) for card in cards)
        if cost > s.energy:
            raise GameError("エネルギーが足りません。")

        sql, params = self._build_query(kinds, column)
        result = self._run(sql, params)
        hits = self._hits_by_enemy(result.rows)

        damage = self._damage(hits, kinds, column)
        if not damage:
            raise GameError("この組み合わせではダメージを与えられません。カードは消費されません。")

        s.energy -= cost
        s.attacked = True
        if column is not None:
            for enemy in s.alive_enemies:
                if column in enemy.visible_columns:
                    enemy.known_columns.add(column)
        for i in sorted(indices, reverse=True):
            self._discard.append(s.hand.pop(i))

        lines = [f"実行クエリ: {self._shown_sql(sql, column)}", f"{result.row_count}行 / {result.elapsed_ms:.1f}ms"]
        if "join" in kinds:
            revealed = self._reveal_one()
            if revealed:
                lines.append(f"JOIN で {revealed} を公開した。")
        for enemy, amount in damage.items():
            enemy.hp = max(0, enemy.hp - amount)
            lines.append(f"{enemy.name} に {amount} ダメージ（残り {enemy.hp}）")
            if not enemy.alive:
                lines.append(f"{enemy.name} を倒した！")
        if column is not None:
            critical = [e.name for e in s.enemies if column == e.weak_column]
            if critical:
                lines.append(f"弱点クリティカル（{'、'.join(critical)}）")
            else:
                lines.append(f"{column} はどの敵の弱点でもない")

        if not s.alive_enemies:
            if s.floor == len(FLOOR_ENEMIES) - 1:
                s.status = "won"
                lines.append(f"ボス撃破！ 勝利！ 残HP {s.player_hp} / 合計 {s.total_turns}ターン。")
            else:
                s.status = "reward"
                s.rewards = self._make_rewards()
                lines.append("撃破！ 報酬を1つ選んでください。")
        s.last_message = "\n".join(lines)
        return s.last_message

    def _build_query(self, kinds: list[str], column: str | None) -> tuple[str, tuple]:
        """Assemble one SELECT whose result drives the damage."""
        sql = f'SELECT t.enemy AS enemy, COUNT(*) AS hits FROM "{self._view()}" AS t'
        if "join" in kinds:
            sql += " JOIN support AS s ON t.id = s.id"
        params: tuple[str, ...] = ()
        if column is not None:
            # Only identifiers from the fixed enemy schema can reach here.
            sql += f' WHERE t."{column}" = ?'
            params = ("weak",)
        else:
            sql += " WHERE t.element IS NOT NULL AND t.armor IS NOT NULL AND t.status IS NOT NULL"
        sql += " GROUP BY t.enemy"
        if "order" in kinds:
            sql += " ORDER BY hits ASC"
        if "limit" in kinds:
            sql += " LIMIT 1"
        return sql, params

    def _run(self, sql: str, params: tuple):
        result = execute_select(self.path, Query(sql, params))
        if result.error or result.over_budget:
            raise GameError(f"クエリ失敗／コスト超過（{result.elapsed_ms:.1f}ms）。カードは消費されません。")
        return result

    def _hits_by_enemy(self, rows: list[tuple]) -> dict[str, int]:
        """Map table name to matched row count, ignoring defeated enemies."""
        alive = {enemy.table for enemy in self.state.alive_enemies}
        return {str(table): int(hits) for table, hits in rows if str(table) in alive}

    def _damage(
        self, hits: dict[str, int], kinds: list[str], column: str | None
    ) -> dict[EnemyState, int]:
        """Turn per-enemy hit counts into damage, applying each clause's role.

        A plain scan only reaches the front enemy. GROUP BY is what spreads the
        attack across the whole battle, so the clause choice changes the target
        set rather than just the number.
        """
        s = self.state
        alive = s.alive_enemies
        if not alive:
            return {}

        def base(enemy: EnemyState) -> int:
            amount = min(hits.get(enemy.table, 0), 20)
            if column is not None and column == enemy.weak_column:
                amount *= 2
            return amount

        if "group" in kinds:
            # GROUP BY aggregates every enemy, so unhit enemies still take splash.
            damage = {enemy: max(base(enemy), 4) for enemy in alive}
        elif "limit" in kinds:
            # LIMIT 1 keeps only the enemy with the most hits, but hits harder.
            target = max(alive, key=lambda enemy: (hits.get(enemy.table, 0), -enemy.hp))
            damage = {target: base(target) + 8} if base(target) else {}
        else:
            # A plain scan reaches the front enemy only.
            target = alive[0]
            damage = {target: base(target)} if base(target) else {}

        if "join" in kinds:
            for enemy in damage:
                damage[enemy] += 3

        if "order" in kinds:
            # ORDER BY concentrates the whole attack on the weakest enemy.
            total = sum(damage.values())
            if total:
                target = min(alive, key=lambda enemy: (enemy.hp, enemy.name))
                damage = {target: total}

        return {enemy: amount for enemy, amount in damage.items() if amount > 0}

    def _shown_sql(self, sql: str, column: str | None) -> str:
        shown = sql.replace("?", "'weak'")
        if column is None:
            shown = shown.replace(
                "t.element IS NOT NULL AND t.armor IS NOT NULL AND t.status IS NOT NULL",
                "[データ列のNULLを除外]",
            )
        return shown

    def _reveal_one(self) -> str | None:
        """Reveal one hidden column of a random living enemy."""
        candidates = [
            (enemy, column)
            for enemy in self.state.alive_enemies
            for column in enemy.columns
            if column not in enemy.visible_columns
        ]
        if not candidates:
            return None
        enemy, column = self.rng.choice(candidates)
        enemy.visible_columns.add(column)
        enemy.known_columns.add(column)
        return f"{enemy.name} の {column}"

    def _scout(self, index: int) -> str:
        s = self.state
        hidden = [
            (enemy, column)
            for enemy in s.alive_enemies
            for column in enemy.columns
            if column not in enemy.visible_columns
        ]
        if not hidden:
            raise GameError("公開できる列はありません。")
        enemy, column = hidden[0]
        result = self._run(f'SELECT * FROM "{self._view()}" LIMIT 1', ())
        if result.error:
            raise GameError("偵察クエリを実行できませんでした。")
        enemy.visible_columns.add(column)
        enemy.known_columns.add(column)
        s.hand.pop(index)
        self._discard.append(SCOUT)
        hint = "弱点列！ WHEREで狙おう。" if column == enemy.weak_column else "弱点ではない。"
        s.last_message = f"偵察成功：{enemy.name} の {column} を公開。{hint}（ダメージ0）"
        return s.last_message

    def _make_rewards(self) -> list[Reward]:
        pool = [WHERE, JOIN, SCOUT, GROUP, ORDER, LIMIT]
        cards = self.rng.sample(pool, 2)
        available = [
            kind for kind in ("where", "join", "group", "order", "limit")
            if kind not in self.state.relics
        ]
        if available:
            kind = self.rng.choice(available)
            relic = Reward(f"{kind.upper()} インデックス", f"{kind.upper()} のコストを1減らす", relic=kind)
        else:
            relic = Reward("偵察カード", "偵察カードをデッキに追加", card=SCOUT)
        return [Reward(card.label, "このカードをデッキに追加", card=card) for card in cards] + [relic]

    def end_turn(self) -> str:
        s = self.state
        if s.status != "battle" or not s.alive_enemies:
            raise GameError("今はターンを終了できません。")
        attackers = s.alive_enemies
        incoming = sum(enemy.attack for enemy in attackers)
        remaining_hp = max(0, s.player_hp - incoming)
        text = f"敵の反撃：{incoming}ダメージ（{len(attackers)}体）。"
        if remaining_hp == 0:
            s.player_hp = 0
            s.status = "lost"
            s.last_message = text + f" HP 0、敗北。到達 {s.floor + 1}階 / 合計 {s.total_turns}ターン。"
            return s.last_message
        for enemy in attackers:
            trait = enemy.trait
            if trait in ("null", "grow"):
                try:
                    mutate_database(self.path, enemy.definition, trait, self.rng)
                except (OSError, sqlite3.Error) as exc:
                    raise GameError(f"敵の反撃を適用できませんでした: {exc}") from exc
        s.player_hp = remaining_hp
        notes = []
        for enemy in attackers:
            trait = enemy.trait
            if trait == "hide":
                candidates = [
                    column for column in enemy.columns
                    if column != "id" and column in enemy.visible_columns
                ]
                if candidates:
                    hidden = self.rng.choice(candidates)
                    enemy.visible_columns.remove(hidden)
                    notes.append(f"{enemy.name} が {hidden} を隠した")
            elif trait == "null":
                notes.append(f"{enemy.name} が NULL を混入")
            elif trait == "grow":
                notes.append(f"{enemy.name} の行が4件増加")
        if notes:
            text += " " + "、".join(notes) + "。"
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
