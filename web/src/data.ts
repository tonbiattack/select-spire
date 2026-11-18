/**
 * Enemy roster and card definitions shared by the browser build.
 *
 * The numbers mirror select_spire/data.py and select_spire/game.py so the
 * Python and browser versions stay comparable.
 */

export type Trait = "hide" | "null" | "grow";
export type Column = "id" | "element" | "armor" | "status";

export interface EnemyDefinition {
  name: string;
  table: string;
  weak: Column;
  hp: number;
  attack: number;
  trait: Trait;
  rows: number;
}

export const COLUMNS: readonly Column[] = ["id", "element", "armor", "status"];

export const FLOOR_ENEMIES: readonly (readonly EnemyDefinition[])[] = [
  [
    { name: "Ember Slime", table: "ember_slime", weak: "element", hp: 16, attack: 2, trait: "hide", rows: 8 },
  ],
  [
    { name: "Iron Beetle", table: "iron_beetle", weak: "armor", hp: 11, attack: 1, trait: "null", rows: 9 },
    { name: "Moss Sprite", table: "moss_sprite", weak: "status", hp: 10, attack: 1, trait: "grow", rows: 10 },
  ],
  [
    { name: "Frost Wisp", table: "frost_wisp", weak: "element", hp: 12, attack: 1, trait: "null", rows: 11 },
    { name: "Stone Guardian", table: "stone_guardian", weak: "armor", hp: 12, attack: 1, trait: "hide", rows: 12 },
  ],
  [
    { name: "Plague Moth", table: "plague_moth", weak: "status", hp: 14, attack: 1, trait: "grow", rows: 13 },
    { name: "Storm Drake", table: "storm_drake", weak: "element", hp: 13, attack: 2, trait: "hide", rows: 14 },
  ],
  [
    { name: "Steel Sentinel", table: "steel_sentinel", weak: "armor", hp: 10, attack: 1, trait: "null", rows: 15 },
    { name: "Ember Wisp", table: "ember_wisp", weak: "element", hp: 10, attack: 1, trait: "hide", rows: 8 },
    { name: "Moss Crawler", table: "moss_crawler", weak: "status", hp: 10, attack: 1, trait: "grow", rows: 9 },
  ],
  [
    { name: "Plague Drake", table: "plague_drake", weak: "status", hp: 17, attack: 1, trait: "grow", rows: 13 },
    { name: "Iron Wisp", table: "iron_wisp", weak: "element", hp: 16, attack: 2, trait: "null", rows: 11 },
  ],
  [
    { name: "Storm Sentinel", table: "storm_sentinel", weak: "armor", hp: 12, attack: 2, trait: "hide", rows: 14 },
    { name: "Frost Beetle", table: "frost_beetle", weak: "element", hp: 12, attack: 1, trait: "null", rows: 9 },
    { name: "Moss Guardian", table: "moss_guardian", weak: "status", hp: 12, attack: 1, trait: "grow", rows: 10 },
  ],
  [
    { name: "Steel Drake", table: "steel_drake", weak: "armor", hp: 20, attack: 2, trait: "null", rows: 15 },
    { name: "Plague Wisp", table: "plague_wisp", weak: "status", hp: 20, attack: 2, trait: "grow", rows: 11 },
  ],
  [
    { name: "Spire Sovereign", table: "spire_sovereign", weak: "status", hp: 25, attack: 2, trait: "grow", rows: 18 },
    { name: "Sovereign Guard", table: "sovereign_guard", weak: "armor", hp: 10, attack: 2, trait: "hide", rows: 12 },
    { name: "Sovereign Herald", table: "sovereign_herald", weak: "element", hp: 10, attack: 1, trait: "null", rows: 10 },
  ],
];

export type CardKind = "where" | "join" | "group" | "order" | "limit" | "scout";

export interface Card {
  kind: CardKind;
  label: string;
  cost: number;
}

export const CARDS: Record<CardKind, Card> = {
  where: { kind: "where", label: "WHERE 列 = 'weak'", cost: 1 },
  join: { kind: "join", label: "JOIN support", cost: 2 },
  group: { kind: "group", label: "GROUP BY", cost: 1 },
  order: { kind: "order", label: "ORDER BY", cost: 1 },
  limit: { kind: "limit", label: "LIMIT 1", cost: 1 },
  scout: { kind: "scout", label: "LIMIT 偵察", cost: 0 },
};

export const CARD_TEXT: Record<CardKind, { title: string; description: string }> = {
  where: { title: "弱点を狙う", description: "公開列を指定。弱点の敵だけを狙い、その敵へのダメージ2倍。" },
  join: { title: "援護を呼ぶ", description: "ダメージ+3。隠れた列を1つ公開する。" },
  group: { title: "集計する", description: "全員に最低4ダメージ。散った敵をまとめて削る。" },
  order: { title: "並べ替える", description: "ダメージを最も弱った敵に集中させる。" },
  limit: { title: "1体に絞る", description: "最多ヒットの敵だけに+8ダメージ。" },
  scout: { title: "偵察する", description: "押すとすぐに非公開列を1つ公開し、弱点か調べる。" },
};

export const INITIAL_DECK: readonly CardKind[] = [
  "where", "where", "where", "where",
  "join", "join",
  "scout", "scout", "scout",
  "group", "order", "limit",
];

export const COLUMN_NAMES: Record<Column, string> = {
  id: "番号",
  element: "属性",
  armor: "装甲",
  status: "状態",
};

export const TRAITS: Record<Trait, string> = {
  hide: "公開列を1つ隠す",
  null: "データの一部を空にする（通常攻撃が弱まる）",
  grow: "データを4行増やす",
};
