"""Command-line interface for SELECT Spire."""

import argparse

from .game import Game, GameError


HELP = """\
コマンド:
  attack [手札番号 ...] [--where 公開列名]  選んだカードで攻撃（カードなしも可）
  scout <手札番号>                         偵察カードを1枚使う
  end                                      ターンを終了する
  help                                     この説明を見る
  quit                                     保存せず終了する
手札番号は1から。WHEREカードを使うときは --where で公開列を指定。
例: 手札1がWHEREなら attack 1 --where element でelement列を狙う。
偵察は隠れた列を1つ公開し、弱点かどうかも知らせる。
JOINやWHEREのカードを選び、エネルギーの範囲で組み立てよう。
通常スキャンはNULLを含む行を除外する。WHEREは指定列だけを調べる。
攻撃は1ターンに1回。偵察カードは単独で使う。
"""


def _show_state(state):
    print(f"\n--- フロア {state.floor + 1} / ターン {state.turn} ---")
    print(f"あなたのHP: {state.player_hp}  エネルギー: {state.energy}  デッキ: {len(state.deck)}枚")
    print(f"敵: {state.enemy.name}  テーブル: {state.enemy.table}  HP: {state.enemy_hp}/{state.enemy.hp}")
    if state.status == "battle":
        traits = {"hide": "公開列を隠す", "null": "NULL混入", "grow": "行を4件増やす"}
        print(f"敵の予告: {state.enemy.attack}ダメージ + {traits[state.enemy.trait]}")
    print(f"公開列: {', '.join(sorted(state.visible_columns)) or 'なし'}")
    known = state.known_columns & state.visible_columns
    if known:
        hints = [f"{col}={'弱点' if col == state.enemy.weak_column else '弱点ではない'}" for col in sorted(known)]
        print(f"調査結果: {', '.join(hints)}")
    if state.status != "battle":
        return
    print("手札:")
    if state.hand:
        for number, card in enumerate(state.hand, 1):
            cost = max(0, card.cost - int(card.kind in state.relics))
            print(f"  {number}. {card.label} [{card.kind}] (コスト {cost})")
    else:
        print("  なし")
    if state.relics:
        print(f"レリック: {', '.join(state.relics)}")
    if state.attacked and state.status == "battle":
        print("攻撃済み: 偵察するか、end でターンを終了")


def _hand_number(text):
    try:
        number = int(text)
    except ValueError:
        raise ValueError("手札番号は1以上の整数で指定してください。") from None
    if number < 1:
        raise ValueError("手札番号は1以上の整数で指定してください。")
    return number - 1


def _attack(game, arguments):
    indices = []
    column = None
    i = 0
    while i < len(arguments):
        token = arguments[i]
        if token == "--where":
            if column is not None or i + 1 >= len(arguments):
                raise ValueError("--where は公開列名を1つ指定してください。")
            column = arguments[i + 1]
            if column not in game.state.visible_columns:
                raise ValueError("列は表示されている公開列から指定してください。")
            i += 2
        else:
            indices.append(_hand_number(token))
            i += 1
    return game.play(indices, column)


def _battle_command(game, command):
    parts = command.split()
    if not parts:
        raise ValueError("コマンドを入力してください。使い方は help。")
    action, arguments = parts[0], parts[1:]
    if action == "attack":
        return _attack(game, arguments)
    if action == "scout":
        if len(arguments) != 1:
            raise ValueError("使い方: scout <手札番号>")
        index = _hand_number(arguments[0])
        if index >= len(game.state.hand):
            raise ValueError("その手札番号はありません。")
        if game.state.hand[index].kind != "scout":
            raise ValueError("偵察カードを選んでください。")
        return game.play([index])
    if action == "end":
        if arguments:
            raise ValueError("使い方: end")
        return game.end_turn()
    raise ValueError("不明なコマンドです。使い方は help。")


def _choose_reward(game, command):
    try:
        number = int(command)
    except ValueError:
        raise ValueError("報酬の番号を1つ入力してください。") from None
    if not 1 <= number <= len(game.state.rewards):
        raise ValueError("表示されている報酬の番号を選んでください。")
    return game.choose_reward(number - 1)


def main(argv=None):
    parser = argparse.ArgumentParser(description="SELECT Spire - カードを組み合わせて敵を倒そう")
    parser.add_argument("--seed", type=int, default=None, help="乱数シードを指定する")
    args = parser.parse_args(argv)

    game = Game(seed=args.seed)
    try:
        print("=== SELECT Spire ===")
        game.start()
        while True:
            state = game.state
            _show_state(state)
            if state.status == "won":
                print(f"勝利！ 合計 {state.total_turns} ターン")
                break
            if state.status == "lost":
                print(f"敗北。合計 {state.total_turns} ターン")
                break
            if state.status == "reward":
                print("報酬を選んでください:")
                for number, reward in enumerate(state.rewards, 1):
                    print(f"  {number}. {reward.label}: {reward.description}")
                prompt = "報酬番号 > "
            else:
                print("attack で攻撃 / scout で偵察 / end でターン終了 / help")
                prompt = "> "
            command = input(prompt).strip()
            if command == "quit":
                print("保存せずに終了します。")
                break
            if command == "help":
                print(HELP)
                continue
            try:
                if state.status == "reward":
                    result = _choose_reward(game, command)
                else:
                    result = _battle_command(game, command)
                if result:
                    print(f"\n{result}")
            except (GameError, ValueError) as exc:
                print(f"エラー: {exc}")
    except (EOFError, KeyboardInterrupt):
        print("\n保存せずに終了します。")
    finally:
        game.close()
