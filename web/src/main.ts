/**
 * Browser UI for SELECT Spire.
 *
 * The whole screen is re-rendered from the engine state after every action, so
 * the preview, the hand, and the enemy list can never drift apart.
 */

import {
  CARD_TEXT,
  COLUMN_NAMES,
  COLUMNS,
  FLOOR_ENEMIES,
  TRAITS,
  type Card,
  type CardKind,
  type Column,
} from "./data";
import { Game, GameError, type EnemyState, type State } from "./engine";
import "./style.css";

const app = document.querySelector<HTMLDivElement>("#app");
if (!app) throw new Error("#app is missing");

let game = new Game();
let selected = new Set<number>();
let column: Column | null = null;
let notice = "カードを選ばずに攻撃することもできます。";
let noticeError = false;

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props: Partial<HTMLElementTagNameMap[K]> & { class?: string } = {},
  children: (Node | string)[] = [],
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  const { class: className, ...rest } = props as Record<string, unknown> & { class?: string };
  if (className) node.className = className;
  Object.assign(node, rest);
  for (const child of children) {
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

function setNotice(message: string, error = false): void {
  notice = message;
  noticeError = error;
}

function run(action: () => string): void {
  try {
    setNotice(action());
  } catch (error) {
    if (error instanceof GameError) {
      setNotice(error.message, true);
    } else {
      throw error;
    }
  }
  render();
}

function cost(card: Card): number {
  return Math.max(0, card.cost - (game.state.relics.includes(card.kind) ? 1 : 0));
}

function selectedCost(): number {
  return [...selected].reduce((total, index) => {
    const card = game.state.hand[index];
    return total + (card ? cost(card) : 0);
  }, 0);
}

function selectedKinds(): CardKind[] {
  return [...selected]
    .map((index) => game.state.hand[index]?.kind)
    .filter((kind): kind is CardKind => Boolean(kind));
}

function toggleCard(index: number): void {
  const state = game.state;
  const card = state.hand[index];
  if (!card) return;
  if (card.kind === "scout") {
    run(() => game.play([index]));
    selected = new Set([...selected].map((value) => (value > index ? value - 1 : value)));
    return;
  }
  if (state.attacked) {
    setNotice("このターンは攻撃済みです。偵察するか、ターンを終了してください。", true);
    render();
    return;
  }
  if (selected.has(index)) {
    selected.delete(index);
    if (card.kind === "where") column = null;
    setNotice("カードの選択を解除しました。");
  } else if (selectedKinds().includes(card.kind)) {
    setNotice("同じ種類のカードは1枚までです。先に選択を解除してください。", true);
  } else if (selectedCost() + cost(card) > state.energy) {
    setNotice(
      `必要エネルギーは${selectedCost() + cost(card)}、残りは${state.energy}です。`,
      true,
    );
  } else {
    selected.add(index);
    setNotice(
      card.kind === "where"
        ? "公開列を選んでください。"
        : "カードを選択しました。もう一度押すと解除できます。",
    );
  }
  render();
}

function chooseColumn(next: Column): void {
  if (!selectedKinds().includes("where")) {
    setNotice("弱点を狙うカードを選んでから公開列を指定してください。", true);
  } else {
    column = next;
    setNotice(`${COLUMN_NAMES[next]}（${next}）を狙います。`);
  }
  render();
}

function attack(): void {
  const kinds = selectedKinds();
  if (kinds.includes("where") && column === null) {
    setNotice("弱点を狙うカードには、公開列を1つ選んでください。", true);
    render();
    return;
  }
  const indices = [...selected].sort((a, b) => a - b);
  const target = kinds.includes("where") ? column : null;
  try {
    const result = game.play(indices, target);
    selected = new Set();
    column = null;
    setNotice(result);
  } catch (error) {
    if (error instanceof GameError) setNotice(error.message, true);
    else throw error;
  }
  render();
}

function endTurn(): void {
  run(() => {
    const result = game.endTurn();
    selected = new Set();
    column = null;
    return result;
  });
}

function chooseReward(index: number): void {
  run(() => {
    const result = game.chooseReward(index);
    selected = new Set();
    column = null;
    return result;
  });
}

function restart(): void {
  game = new Game();
  selected = new Set();
  column = null;
  setNotice("新しいランを開始しました。");
  render();
}

function enemyPanel(enemy: EnemyState, state: State): HTMLElement {
  const defeated = enemy.hp === 0;
  const panel = el("div", { class: `enemy${defeated ? " defeated" : ""}` });
  panel.append(
    el("h3", {}, [
      el("span", {}, [enemy.definition.name]),
      el("span", {}, [`HP ${enemy.hp} / ${enemy.definition.hp}`]),
    ]),
  );
  const bar = el("div", { class: "hp-bar" }, [el("span")]);
  const fill = bar.firstElementChild as HTMLSpanElement;
  fill.style.width = `${(enemy.hp / enemy.definition.hp) * 100}%`;
  panel.append(bar);
  if (!defeated && state.status === "battle") {
    panel.append(
      el("p", { class: "telegraph" }, [
        `予告: ${enemy.definition.attack}ダメージ ＋ ${TRAITS[enemy.definition.trait]}`,
      ]),
    );
  }
  const chips = el("div", { class: "columns" });
  const whereSelected = selectedKinds().includes("where");
  for (const name of COLUMNS) {
    const visible = enemy.visible.has(name);
    const known = enemy.known.has(name);
    const isWeak = visible && known && name === enemy.definition.weak;
    const label = visible
      ? `${COLUMN_NAMES[name]}（${name}）${known ? (isWeak ? " 弱点！" : " 弱点ではない") : ""}`
      : "？？？";
    if (visible && whereSelected && !state.attacked) {
      const button = el("button", {
        class: `column-chip${isWeak ? " weak" : ""}`,
        type: "button",
        textContent: label,
      });
      button.setAttribute("aria-pressed", String(column === name));
      button.addEventListener("click", () => chooseColumn(name));
      chips.append(button);
    } else {
      chips.append(
        el("span", {
          class: `column-chip${isWeak ? " weak" : ""}${visible ? "" : " hidden"}`,
          textContent: label,
        }),
      );
    }
  }
  panel.append(chips);
  return panel;
}

function renderBattle(state: State): HTMLElement[] {
  const sections: HTMLElement[] = [];

  const enemies = el("section", { class: "panel" }, [el("h2", {}, ["敵"])]);
  const list = el("div", { class: "enemy-list" });
  for (const enemy of state.enemies) list.append(enemyPanel(enemy, state));
  enemies.append(list);
  sections.push(enemies);

  const hand = el("section", { class: "panel" }, [
    el("h2", {}, ["手札"]),
    el("p", { class: "preview" }, [
      `エネルギー ${state.energy} ／ 選択中のコスト ${selectedCost()} ／ 同じ種類は1枚まで`,
    ]),
  ]);
  const grid = el("div", { class: "hand" });
  state.hand.forEach((card, index) => {
    const info = CARD_TEXT[card.kind];
    const button = el("button", {
      class: "card",
      type: "button",
      disabled: state.attacked && card.kind !== "scout",
    });
    button.setAttribute("aria-pressed", String(selected.has(index)));
    button.append(
      el("span", { class: "card-title" }, [info.title]),
      el("span", { class: "card-meta" }, [
        `${card.kind.toUpperCase()} ・ コスト ${cost(card)}${card.kind === "scout" ? " ・ 押すと即使用" : ""}`,
      ]),
      el("span", { class: "card-desc" }, [info.description]),
    );
    button.addEventListener("click", () => toggleCard(index));
    grid.append(button);
  });
  if (state.hand.length === 0) {
    grid.append(el("p", { class: "preview" }, ["手札はありません。カードなしでも攻撃できます。"]));
  }
  hand.append(grid);
  if (state.relics.length > 0) {
    hand.append(
      el("p", { class: "preview" }, [
        `獲得済み: ${state.relics.map((kind) => CARD_TEXT[kind].title).join("、")} のコストが1減少`,
      ]),
    );
  }
  sections.push(hand);

  const actions = el("section", { class: "panel" }, [el("h2", {}, ["次の行動"])]);
  const kinds = selectedKinds();
  const summary = kinds.length > 0 ? kinds.map((kind) => CARD_TEXT[kind].title).join("、") : "カードなしの基本攻撃";
  const targetText = kinds.includes("where") ? ` ／ 狙い: ${column ? COLUMN_NAMES[column] : "未選択"}` : "";
  actions.append(el("p", { class: "preview" }, [`攻撃の準備: ${summary}${targetText}`]));
  const row = el("div", { class: "actions" });
  if (state.attacked) {
    const end = el("button", { class: "action primary", type: "button", textContent: "ターン終了（敵が反撃）" });
    end.addEventListener("click", endTurn);
    row.append(end);
  } else {
    const attackButton = el("button", { class: "action primary", type: "button", textContent: "攻撃する" });
    attackButton.addEventListener("click", attack);
    const end = el("button", { class: "action", type: "button", textContent: "攻撃せずターン終了（敵が反撃）" });
    end.addEventListener("click", endTurn);
    row.append(attackButton, end);
  }
  actions.append(row);
  sections.push(actions);
  return sections;
}

function renderRewards(state: State): HTMLElement[] {
  const section = el("section", { class: "panel" }, [
    el("h2", {}, ["敵を撃破！ 報酬を1つ選んで次の階へ"]),
  ]);
  const list = el("div", { class: "rewards" });
  state.rewards.forEach((reward, index) => {
    const button = el("button", { class: "reward", type: "button" });
    const title = reward.card
      ? `${CARD_TEXT[reward.card].title}（${reward.card.toUpperCase()}）を追加`
      : reward.relic
        ? `${CARD_TEXT[reward.relic].title}のコストを1減らす`
        : reward.label;
    const detail = reward.card
      ? CARD_TEXT[reward.card].description
      : reward.relic
        ? "この先ずっと有効"
        : reward.description;
    button.append(el("strong", {}, [title]), el("span", {}, [detail]));
    button.addEventListener("click", () => chooseReward(index));
    list.append(button);
  });
  section.append(list);
  return [section];
}

function renderFinish(state: State): HTMLElement[] {
  const won = state.status === "won";
  const section = el("section", { class: "panel finish" }, [
    el("h2", {}, [won ? "塔を制覇！ 勝利" : "HPが0になりました"]),
    el("p", {}, [`到達 ${state.floor + 1}階 ／ 合計 ${state.totalTurns}ターン`]),
  ]);
  const again = el("button", { class: "action primary", type: "button", textContent: "もう一度挑戦する" });
  again.addEventListener("click", restart);
  section.append(again);
  return [section];
}

function render(): void {
  const state = game.state;
  app!.replaceChildren();

  const header = el("header", { class: "app-header" }, [
    el("h1", {}, ["SELECT Spire"]),
    el("p", {}, ["敵のHPを0にすると次へ。あなたのHPは引き継ぎ、0になると敗北。"]),
  ]);
  app!.append(header);

  const main = el("main");
  main.append(
    el("p", { class: "guide" }, ["偵察 →『弱点を狙う』カード → 公開列を選ぶ → 攻撃"]),
  );

  const status = el("section", { class: "panel" }, [
    el("h2", {}, [`${state.floor + 1} / ${FLOOR_ENEMIES.length}階 ・ ターン ${state.turn}`]),
  ]);
  const row = el("div", { class: "status-row" }, [
    el("span", { class: "hp" }, [`あなたのHP ${state.playerHp} / 50`]),
    el("span", { class: "energy" }, [`エネルギー ${state.energy}`]),
    el("span", {}, [`デッキ ${state.deck.length}枚`]),
  ]);
  status.append(row);
  main.append(status);

  const message = el("div", { class: `message${noticeError ? " error" : ""}` }, [notice]);
  main.append(message);

  if (state.status === "battle") {
    main.append(...renderBattle(state));
  } else if (state.status === "reward") {
    main.append(...renderRewards(state));
  } else {
    main.append(...renderFinish(state));
  }

  if (state.status === "battle" || state.status === "reward") {
    const restartRow = el("section", { class: "panel" }, [el("h2", {}, ["ラン"])]);
    const button = el("button", { class: "action", type: "button", textContent: "最初からやり直す" });
    button.addEventListener("click", () => {
      if (window.confirm("現在の階層、HP、獲得したカードなどの進捗が失われます。\n最初からやり直しますか？")) {
        restart();
      }
    });
    restartRow.append(button);
    main.append(restartRow);
  }

  app!.append(main);
}

render();
