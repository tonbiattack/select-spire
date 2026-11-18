# SELECT Spire

SQLの句をカードで組み立て、敵テーブルの弱点を突いて塔を登る、ひとり用ローグライク。8フロアとボスを突破しよう。

**ブラウザで遊ぶ: https://tonbiattack.github.io/select-spire/**

インストールもログインも不要です。PC・スマホのどちらでも遊べます。

## 遊び方

1. 敵のデータ表で公開されている列を確認する
2. 「偵察する」カードを押して、隠れた列と弱点を調べる
3. 「弱点を狙う」カードを選び、公開列を指定する
4. 「攻撃する」を押す
5. 倒しきれなければ「ターン終了」で敵の反撃を受ける

敵を全滅させると報酬を1つ選んで次の階へ進みます。HPは引き継ぎ、0になると敗北です。

### 句ごとの役割

| カード | コスト | 役割 |
|---|---:|---|
| 基本攻撃（カードなし） | 0 | 先頭の敵だけを攻撃 |
| WHERE | 1 | 弱点の敵だけを狙う。弱点なら2倍 |
| JOIN | 2 | ダメージ+3。隠れた列を1つ公開 |
| GROUP BY | 1 | 全員に最低4ダメージ |
| ORDER BY | 1 | ダメージを最も弱った敵に集中 |
| LIMIT 1 | 1 | 最多ヒットの敵1体に+8ダメージ |
| 偵察 | 0 | 隠れた列を1つ公開（ダメージ0） |

どの句を使うかで「誰に当たるか」が変わります。単体を落とすか、全体を削るか、弱った敵に集中するかを選んでください。

## ローカルで動かす

### ブラウザ版

Node.js 20以上が必要です。

```sh
cd web
npm ci
npm run dev
```

表示されたURLを開いてください。テストは `npm test`、型チェックは `npm run typecheck`、本番ビルドは `npm run build` です。

### Python版（GUI / CLI）

Python 3.11以上が必要です。追加パッケージは不要です。

```sh
python -m select_spire.gui
```

カードをクリックして攻撃を組み立てるウィンドウが開きます。途中で新しく始めたいときは「最初からやり直す」を押してください。

従来のCLIは `python -m select_spire` で起動できます。WindowsでCLIの日本語が文字化けする場合は `python -X utf8 -m select_spire` を使用してください。GUI・CLIともに乱数を固定するには `--seed 7` を付けます。

Python版のテストは `python -m unittest discover -s tests -v` で実行できます。GUIにはPythonの標準Tkinterが必要です。

## 構成

- `select_spire/` — Python版（SQLiteで実際にSELECTを実行する）
- `web/` — ブラウザ版（TypeScriptで同じルールを実装）
- `docs/SPEC.md` — 仕様書
- `.github/workflows/` — PythonテストとGitHub Pages公開

ブラウザ版はGitHub Pagesが静的ホスティングのため、SQLiteの代わりに同じ行データをTypeScriptで保持し、SQLの意味（WHERE・JOIN・GROUP BY・ORDER BY・LIMIT）を同じように適用しています。

## 公開

`main` に push すると GitHub Actions がテスト・ビルド・Pages公開を自動実行します。

[仕様書](docs/SPEC.md)には詳細なルール、安全制限、MVPの対象外を記載しています。
