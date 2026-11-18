/**
 * Pure game engine for the browser build.
 *
 * It mirrors select_spire/game.py: every attack is one SELECT against the
 * floor's battle view, and the per-enemy hit counts decide the damage. Enemy
 * rows are modelled directly so NULL injection and row growth behave the same
 * way as the SQLite version.
 */

import {
  CARDS,
  COLUMNS,
  FLOOR_ENEMIES,
  INITIAL_DECK,
  type Card,
  type CardKind,
  type Column,
  type EnemyDefinition,
} from "./data";

export class GameError extends Error {}

export interface Row {
  element: string | null;
  armor: string | null;
  status: string | null;
}

/** Data columns are the only ones a row stores; id is positional. */
type DataColumn = Exclude<Column, "id">;

export interface EnemyState {
  definition: EnemyDefinition;
  hp: number;
  rows: Row[];
  visible: Set<Column>;
  known: Set<Column>;
}

export interface Reward {
  label: string;
  description: string;
  card?: CardKind;
  relic?: CardKind;
}

export type Status = "battle" | "reward" | "won" | "lost";

export interface State {
  playerHp: number;
  floor: number;
  turn: number;
  energy: number;
  hand: Card[];
  deck: CardKind[];
  enemies: EnemyState[];
  status: Status;
  rewards: Reward[];
  totalTurns: number;
  relics: CardKind[];
  message: string;
  attacked: boolean;
}

/** Small deterministic PRNG so a seed reproduces the same run. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffle<T>(items: T[], random: () => number): T[] {
  for (let i = items.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    const a = items[i] as T;
    const b = items[j] as T;
    items[i] = b;
    items[j] = a;
  }
  return items;
}

function makeRows(definition: EnemyDefinition): Row[] {
  const weakCount = Math.floor((definition.rows * 4) / 5);
  const rows: Row[] = [];
  for (let index = 1; index <= definition.rows; index += 1) {
    const weak = index <= weakCount;
    rows.push({
      element: definition.weak === "element" && weak ? "weak" : "normal",
      armor: definition.weak === "armor" && weak ? "weak" : "normal",
      status: definition.weak === "status" && weak ? "weak" : "normal",
    });
  }
  return rows;
}

export class Game {
  readonly seed: number;
  private random: () => number;
  private draw: CardKind[] = [];
  private discard: CardKind[] = [];
  state: State;

  constructor(seed?: number) {
    this.seed = seed ?? Math.floor(Math.random() * 2 ** 31);
    this.random = mulberry32(this.seed);
    this.state = {
      playerHp: 50,
      floor: 0,
      turn: 0,
      energy: 3,
      hand: [],
      deck: [...INITIAL_DECK],
      enemies: [],
      status: "battle",
      rewards: [],
      totalTurns: 0,
      relics: [],
      message: "",
      attacked: false,
    };
    this.startFloor();
  }

  get aliveEnemies(): EnemyState[] {
    return this.state.enemies.filter((enemy) => enemy.hp > 0);
  }

  private startFloor(): void {
    const s = this.state;
    s.enemies = FLOOR_ENEMIES[s.floor]!.map((definition) => {
      const others = shuffle(
        COLUMNS.filter((column) => column !== "id"),
        this.random,
      );
      return {
        definition,
        hp: definition.hp,
        rows: makeRows(definition),
        visible: new Set<Column>(["id", others[0] as Column]),
        known: new Set<Column>(),
      };
    });
    s.status = "battle";
    s.rewards = [];
    this.draw = shuffle([...s.deck], this.random);
    this.discard = [];
    s.hand = [];
    s.turn = 0;
    this.startTurn();
  }

  private startTurn(): void {
    const s = this.state;
    s.turn += 1;
    s.totalTurns += 1;
    s.energy = 3;
    s.attacked = false;
    while (s.hand.length < 5) {
      if (this.draw.length === 0) {
        if (this.discard.length === 0) break;
        this.draw = shuffle([...this.discard], this.random);
        this.discard = [];
      }
      s.hand.push(CARDS[this.draw.pop() as CardKind]);
    }
  }

  cost(card: Card): number {
    return Math.max(0, card.cost - (this.state.relics.includes(card.kind) ? 1 : 0));
  }

  /** Rows matching the query for one enemy, mirroring the SQL WHERE clause. */
  private hits(enemy: EnemyState, column: Column | null): number {
    if (column === null) {
      return enemy.rows.filter(
        (row) => row.element !== null && row.armor !== null && row.status !== null,
      ).length;
    }
    if (column === "id") return enemy.rows.length;
    return enemy.rows.filter((row) => row[column] === "weak").length;
  }

  play(indices: number[], column: Column | null = null): string {
    const s = this.state;
    if (s.status !== "battle" || this.aliveEnemies.length === 0) {
      throw new GameError("今はカードを使えません。");
    }
    if (new Set(indices).size !== indices.length) {
      throw new GameError("手札番号が不正か重複しています。");
    }
    if (indices.some((index) => index < 0 || index >= s.hand.length)) {
      throw new GameError("手札番号が不正か重複しています。");
    }
    const cards = indices.map((index) => s.hand[index] as Card);
    const kinds = cards.map((card) => card.kind);

    if (kinds.includes("scout")) {
      if (kinds.length !== 1 || column !== null) {
        throw new GameError("偵察は1枚だけ単独で使います。");
      }
      return this.scout(indices[0] as number);
    }
    if (s.attacked) {
      throw new GameError("このターンは攻撃済みです。ターンを終了してください。");
    }
    if (new Set(kinds).size !== kinds.length) {
      throw new GameError("同じ種類の句は1枚までです。");
    }
    if (kinds.some((kind) => kind === "scout")) {
      throw new GameError("攻撃に使えないカードです。");
    }
    if (kinds.includes("where") !== (column !== null)) {
      throw new GameError("WHEREカード使用時は公開列を指定してください。");
    }
    if (column !== null && !this.aliveEnemies.some((enemy) => enemy.visible.has(column))) {
      throw new GameError("WHEREには公開済みの列を指定してください。");
    }
    const cost = cards.reduce((total, card) => total + this.cost(card), 0);
    if (cost > s.energy) {
      throw new GameError("エネルギーが足りません。");
    }

    const damage = this.damage(kinds, column);
    if (damage.size === 0) {
      throw new GameError("この組み合わせではダメージを与えられません。カードは消費されません。");
    }

    s.energy -= cost;
    s.attacked = true;
    if (column !== null) {
      for (const enemy of this.aliveEnemies) {
        if (enemy.visible.has(column)) enemy.known.add(column);
      }
    }
    for (const index of [...indices].sort((a, b) => b - a)) {
      this.discard.push((s.hand.splice(index, 1)[0] as Card).kind);
    }

    const lines: string[] = [];
    if (kinds.includes("join")) {
      const revealed = this.revealOne();
      if (revealed) lines.push(`JOIN で ${revealed} を公開した。`);
    }
    for (const [enemy, amount] of damage) {
      enemy.hp = Math.max(0, enemy.hp - amount);
      lines.push(`${enemy.definition.name} に ${amount} ダメージ（残り ${enemy.hp}）`);
      if (enemy.hp === 0) lines.push(`${enemy.definition.name} を倒した！`);
    }
    if (column !== null) {
      const critical = s.enemies
        .filter((enemy) => enemy.definition.weak === column)
        .map((enemy) => enemy.definition.name);
      lines.push(
        critical.length > 0
          ? `弱点クリティカル（${critical.join("、")}）`
          : `${column} はどの敵の弱点でもない`,
      );
    }

    if (this.aliveEnemies.length === 0) {
      if (s.floor === FLOOR_ENEMIES.length - 1) {
        s.status = "won";
        lines.push(`ボス撃破！ 勝利！ 残HP ${s.playerHp} / 合計 ${s.totalTurns}ターン。`);
      } else {
        s.status = "reward";
        s.rewards = this.makeRewards();
        lines.push("撃破！ 報酬を1つ選んでください。");
      }
    }
    s.message = lines.join("\n");
    return s.message;
  }

  /** Apply each clause's role to the per-enemy hit counts. */
  private damage(kinds: CardKind[], column: Column | null): Map<EnemyState, number> {
    const alive = this.aliveEnemies;
    if (alive.length === 0) return new Map();

    const base = (enemy: EnemyState): number => {
      let amount = Math.min(this.hits(enemy, column), 20);
      if (column !== null && column === enemy.definition.weak) amount *= 2;
      return amount;
    };

    let damage = new Map<EnemyState, number>();
    if (kinds.includes("group")) {
      for (const enemy of alive) damage.set(enemy, Math.max(base(enemy), 4));
    } else if (kinds.includes("limit")) {
      const target = alive.reduce((best, enemy) =>
        this.hits(enemy, column) > this.hits(best, column) ? enemy : best,
      );
      const amount = base(target);
      if (amount > 0) damage.set(target, amount + 8);
    } else {
      const target = alive[0] as EnemyState;
      const amount = base(target);
      if (amount > 0) damage.set(target, amount);
    }

    if (kinds.includes("join")) {
      for (const [enemy, amount] of damage) damage.set(enemy, amount + 3);
    }
    if (kinds.includes("order")) {
      const total = [...damage.values()].reduce((sum, amount) => sum + amount, 0);
      if (total > 0) {
        const target = alive.reduce((best, enemy) =>
          enemy.hp < best.hp ? enemy : best,
        );
        damage = new Map([[target, total]]);
      }
    }
    return new Map([...damage].filter(([, amount]) => amount > 0));
  }

  private revealOne(): string | null {
    const candidates: [EnemyState, Column][] = [];
    for (const enemy of this.aliveEnemies) {
      for (const column of COLUMNS) {
        if (!enemy.visible.has(column)) candidates.push([enemy, column]);
      }
    }
    if (candidates.length === 0) return null;
    const [enemy, column] = candidates[Math.floor(this.random() * candidates.length)] as [
      EnemyState,
      Column,
    ];
    enemy.visible.add(column);
    enemy.known.add(column);
    return `${enemy.definition.name} の ${column}`;
  }

  private scout(index: number): string {
    const s = this.state;
    const hidden: [EnemyState, Column][] = [];
    for (const enemy of this.aliveEnemies) {
      for (const column of COLUMNS) {
        if (!enemy.visible.has(column)) hidden.push([enemy, column]);
      }
    }
    if (hidden.length === 0) throw new GameError("公開できる列はありません。");
    const [enemy, column] = hidden[0] as [EnemyState, Column];
    enemy.visible.add(column);
    enemy.known.add(column);
    this.discard.push((s.hand.splice(index, 1)[0] as Card).kind);
    const hint = column === enemy.definition.weak ? "弱点列！ WHEREで狙おう。" : "弱点ではない。";
    s.message = `偵察成功：${enemy.definition.name} の ${column} を公開。${hint}（ダメージ0）`;
    return s.message;
  }

  private makeRewards(): Reward[] {
    const pool: CardKind[] = ["where", "join", "scout", "group", "order", "limit"];
    const cards = shuffle([...pool], this.random).slice(0, 2);
    const available = (["where", "join", "group", "order", "limit"] as CardKind[]).filter(
      (kind) => !this.state.relics.includes(kind),
    );
    const relic: Reward =
      available.length > 0
        ? (() => {
            const kind = available[Math.floor(this.random() * available.length)] as CardKind;
            return {
              label: `${kind.toUpperCase()} インデックス`,
              description: `${kind.toUpperCase()} のコストを1減らす`,
              relic: kind,
            };
          })()
        : { label: "偵察カード", description: "偵察カードをデッキに追加", card: "scout" };
    return [
      ...cards.map((kind) => ({
        label: CARDS[kind].label,
        description: "このカードをデッキに追加",
        card: kind,
      })),
      relic,
    ];
  }

  endTurn(): string {
    const s = this.state;
    if (s.status !== "battle" || this.aliveEnemies.length === 0) {
      throw new GameError("今はターンを終了できません。");
    }
    const attackers = this.aliveEnemies;
    const incoming = attackers.reduce((sum, enemy) => sum + enemy.definition.attack, 0);
    const remaining = Math.max(0, s.playerHp - incoming);
    let text = `敵の反撃：${incoming}ダメージ（${attackers.length}体）。`;
    if (remaining === 0) {
      s.playerHp = 0;
      s.status = "lost";
      s.message = `${text} HP 0、敗北。到達 ${s.floor + 1}階 / 合計 ${s.totalTurns}ターン。`;
      return s.message;
    }
    s.playerHp = remaining;
    const notes: string[] = [];
    for (const enemy of attackers) {
      const trait = enemy.definition.trait;
      if (trait === "hide") {
        const candidates = COLUMNS.filter(
          (column) => column !== "id" && enemy.visible.has(column),
        );
        if (candidates.length > 0) {
          const hidden = candidates[Math.floor(this.random() * candidates.length)] as Column;
          enemy.visible.delete(hidden);
          notes.push(`${enemy.definition.name} が ${hidden} を隠した`);
        }
      } else if (trait === "null") {
        const candidates = COLUMNS.filter(
          (column): column is DataColumn =>
            column !== "id" && column !== enemy.definition.weak,
        );
        const target = candidates[Math.floor(this.random() * candidates.length)] as DataColumn;
        const count = Math.max(1, Math.floor(enemy.rows.length / 4));
        const indices = shuffle(
          enemy.rows.map((_, index) => index),
          this.random,
        ).slice(0, count);
        for (const index of indices) {
          (enemy.rows[index] as Row)[target] = null;
        }
        notes.push(`${enemy.definition.name} が NULL を混入`);
      } else if (trait === "grow") {
        for (let i = 0; i < 4; i += 1) {
          enemy.rows.push({
            element: enemy.definition.weak === "element" ? "weak" : "normal",
            armor: enemy.definition.weak === "armor" ? "weak" : "normal",
            status: enemy.definition.weak === "status" ? "weak" : "normal",
          });
        }
        notes.push(`${enemy.definition.name} の行が4件増加`);
      }
    }
    if (notes.length > 0) text += ` ${notes.join("、")}。`;
    this.discard.push(...s.hand.map((card) => card.kind));
    s.hand = [];
    this.startTurn();
    s.message = text;
    return text;
  }

  chooseReward(index: number): string {
    const s = this.state;
    if (s.status !== "reward" || index < 0 || index >= s.rewards.length) {
      throw new GameError("報酬番号が不正です。");
    }
    const reward = s.rewards[index] as Reward;
    if (reward.card) s.deck.push(reward.card);
    if (reward.relic) s.relics.push(reward.relic);
    s.floor += 1;
    this.startFloor();
    s.message = `${reward.label} を獲得。次の階へ。`;
    return s.message;
  }
}
