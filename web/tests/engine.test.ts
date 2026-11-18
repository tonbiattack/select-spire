import { describe, expect, it } from "vitest";

import { FLOOR_ENEMIES, INITIAL_DECK } from "../src/data";
import { Game, GameError } from "../src/engine";

function newGame(seed = 42): Game {
  return new Game(seed);
}

describe("game start", () => {
  it("starts on floor 1 with the documented resources", () => {
    const game = newGame();
    const s = game.state;
    expect(s.floor).toBe(0);
    expect(s.playerHp).toBe(50);
    expect(s.turn).toBe(1);
    expect(s.energy).toBe(3);
    expect(s.hand).toHaveLength(5);
    expect(s.deck).toHaveLength(12);
    expect(s.deck).toEqual([...INITIAL_DECK]);
    expect(s.enemies.map((e) => e.definition.name)).toEqual(
      FLOOR_ENEMIES[0]!.map((e) => e.name),
    );
  });

  it("reveals id and one other column but not the weakness", () => {
    const game = newGame();
    const enemy = game.state.enemies[0]!;
    expect(enemy.visible.has("id")).toBe(true);
    expect(enemy.visible.size).toBe(2);
  });

  it("reproduces the same run for the same seed", () => {
    const a = newGame(7);
    const b = newGame(7);
    expect(a.state.hand.map((c) => c.kind)).toEqual(b.state.hand.map((c) => c.kind));
    expect(a.state.enemies[0]!.visible).toEqual(b.state.enemies[0]!.visible);
  });
});

describe("turns", () => {
  it("applies the combined attack of every living enemy", () => {
    const game = newGame();
    const s = game.state;
    s.floor = 1;
    // Restart the floor through a reward-free path: rebuild via chooseReward is
    // not available, so drive the engine through its public surface instead.
    const fresh = new Game(42);
    fresh.state.floor = 1;
    // @ts-expect-error startFloor is private but the test needs a multi-enemy floor.
    fresh.startFloor();
    const incoming = fresh.aliveEnemies.reduce((sum, e) => sum + e.definition.attack, 0);
    const hp = fresh.state.playerHp;
    fresh.endTurn();
    expect(fresh.state.playerHp).toBe(hp - incoming);
    expect(fresh.state.turn).toBe(2);
    expect(fresh.state.energy).toBe(3);
    expect(fresh.state.attacked).toBe(false);
  });

  it("loses when HP reaches zero", () => {
    const game = newGame();
    game.state.playerHp = 1;
    game.endTurn();
    expect(game.state.playerHp).toBe(0);
    expect(game.state.status).toBe("lost");
    expect(() => game.play([])).toThrow(GameError);
  });
});

describe("clause roles", () => {
  function multiEnemyGame(): Game {
    const game = newGame();
    game.state.floor = 1;
    // @ts-expect-error startFloor is private but the test needs a multi-enemy floor.
    game.startFloor();
    return game;
  }

  it("a plain scan only reaches the front enemy", () => {
    const game = multiEnemyGame();
    const before = game.state.enemies.map((e) => e.hp);
    game.play([]);
    const after = game.state.enemies.map((e) => e.hp);
    expect(after[0]).toBeLessThan(before[0]!);
    expect(after[1]).toBe(before[1]);
  });

  it("GROUP BY damages every enemy", () => {
    const game = multiEnemyGame();
    game.state.hand = [{ kind: "group", label: "GROUP BY", cost: 1 }];
    const before = game.state.enemies.map((e) => e.hp);
    game.play([0]);
    game.state.enemies.forEach((enemy, index) => {
      expect(enemy.hp).toBeLessThan(before[index]!);
    });
  });

  it("ORDER BY concentrates damage on the weakest enemy", () => {
    const game = multiEnemyGame();
    game.state.hand = [{ kind: "order", label: "ORDER BY", cost: 1 }];
    const weakest = game.state.enemies.reduce((best, e) => (e.hp < best.hp ? e : best));
    const before = new Map(game.state.enemies.map((e) => [e, e.hp]));
    game.play([0]);
    expect(weakest.hp).toBeLessThan(before.get(weakest)!);
    for (const enemy of game.state.enemies) {
      if (enemy !== weakest) expect(enemy.hp).toBe(before.get(enemy));
    }
  });

  it("LIMIT 1 restricts the attack to a single enemy", () => {
    const game = multiEnemyGame();
    game.state.hand = [{ kind: "limit", label: "LIMIT 1", cost: 1 }];
    const before = game.state.enemies.map((e) => e.hp);
    game.play([0]);
    const damaged = game.state.enemies.filter((e, i) => e.hp < before[i]!);
    expect(damaged).toHaveLength(1);
  });

  it("JOIN reveals one hidden column", () => {
    const game = multiEnemyGame();
    for (const enemy of game.state.enemies) enemy.hp = 99;
    game.state.hand = [{ kind: "join", label: "JOIN support", cost: 2 }];
    const hiddenBefore = game.state.enemies.reduce(
      (sum, e) => sum + (4 - e.visible.size),
      0,
    );
    game.play([0]);
    const hiddenAfter = game.state.enemies.reduce(
      (sum, e) => sum + (4 - e.visible.size),
      0,
    );
    expect(hiddenAfter).toBe(hiddenBefore - 1);
  });

  it("WHERE on a weakness doubles the damage", () => {
    const game = newGame();
    const enemy = game.state.enemies[0]!;
    const weak = enemy.definition.weak;
    enemy.visible.add(weak);
    game.state.hand = [{ kind: "where", label: "WHERE", cost: 1 }];
    const hp = enemy.hp;
    game.play([0], weak);
    const weakRows = Math.floor((enemy.definition.rows * 4) / 5);
    expect(enemy.hp).toBe(Math.max(0, hp - Math.min(weakRows, 20) * 2));
  });

  it("WHERE on a non-weakness deals no damage and consumes nothing", () => {
    const game = newGame();
    const enemy = game.state.enemies[0]!;
    const other = (["element", "armor", "status"] as const).find(
      (column) => column !== enemy.definition.weak,
    )!;
    enemy.visible.add(other);
    game.state.hand = [{ kind: "where", label: "WHERE", cost: 1 }];
    const hp = enemy.hp;
    const energy = game.state.energy;
    expect(() => game.play([0], other)).toThrow(GameError);
    expect(enemy.hp).toBe(hp);
    expect(game.state.energy).toBe(energy);
    expect(game.state.attacked).toBe(false);
  });
});

describe("scouting", () => {
  it("reveals a column without attacking", () => {
    const game = newGame();
    const enemy = game.state.enemies[0]!;
    game.state.hand = [{ kind: "scout", label: "LIMIT 偵察", cost: 0 }];
    const before = new Set(enemy.visible);
    const hp = enemy.hp;
    game.play([0]);
    expect(enemy.visible.size).toBe(before.size + 1);
    expect(enemy.hp).toBe(hp);
    expect(game.state.attacked).toBe(false);
    expect(game.state.hand).toHaveLength(0);
  });
});

describe("rewards and victory", () => {
  it("advances the floor after choosing a reward", () => {
    const game = newGame();
    for (const enemy of game.state.enemies) enemy.hp = 1;
    game.play([]);
    expect(game.state.status).toBe("reward");
    expect(game.state.rewards).toHaveLength(3);
    const deckSize = game.state.deck.length;
    game.chooseReward(0);
    expect(game.state.floor).toBe(1);
    expect(game.state.status).toBe("battle");
    expect(game.state.deck.length).toBeGreaterThanOrEqual(deckSize);
  });

  it("wins after clearing the final floor", () => {
    const game = newGame();
    game.state.floor = FLOOR_ENEMIES.length - 1;
    // @ts-expect-error startFloor is private but the test needs the boss floor.
    game.startFloor();
    for (const enemy of game.state.enemies) enemy.hp = 1;
    game.state.hand = [{ kind: "group", label: "GROUP BY", cost: 1 }];
    game.play([0]);
    expect(game.state.status).toBe("won");
  });
});

describe("enemy traits", () => {
  it("hide removes a revealed column", () => {
    const game = newGame();
    const enemy = game.state.enemies[0]!;
    expect(enemy.definition.trait).toBe("hide");
    const before = new Set(enemy.visible);
    game.endTurn();
    expect(enemy.visible.size).toBe(before.size - 1);
  });

  it("grow adds four rows", () => {
    const game = newGame();
    game.state.floor = 1;
    // @ts-expect-error startFloor is private but the test needs a grow enemy.
    game.startFloor();
    const grower = game.state.enemies.find((e) => e.definition.trait === "grow")!;
    const before = grower.rows.length;
    game.endTurn();
    expect(grower.rows.length).toBe(before + 4);
  });

  it("null injection reduces a plain scan", () => {
    const game = newGame();
    game.state.floor = 1;
    // @ts-expect-error startFloor is private but the test needs a null enemy.
    game.startFloor();
    const injector = game.state.enemies.find((e) => e.definition.trait === "null")!;
    game.endTurn();
    expect(injector.rows.some((row) => row.element === null || row.armor === null || row.status === null)).toBe(true);
  });
});
