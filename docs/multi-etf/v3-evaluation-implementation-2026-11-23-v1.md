# v3評価・会計照合・実験登録（I6）

2026-11-23。[実装前仕様](v3-evaluation-plan-2026-11-23-v1.md)に従い、I5の完了結果を検査する評価部品と、合成専用の登録/実行CLIを追加した。I1〜I6の合成検証基盤が接続された段階であり、実市場対応・収益性評価・戦略採用の完了ではない。既存コード・設定・研究結果は保持。

## A. 変更ファイル

- `src/stock_ai/backtest/evaluation_v3.py`：厳密会計照合、税引前費用控除後指標、D/R別リスク、期待値CI、算出不能理由。
- `src/stock_ai/backtest/experiment_v3.py`：排他的新規登録、入力/原本/設定/コードSHA、ケース固定、試行予算、開始/終了/失敗記録、全候補除外の保存。
- `scripts/run_synthetic_swing_v3.py`：register/execute。実データモードなし。
- `tests/test_evaluation_v3.py`（26ケース）、`tests/test_experiment_v3.py`（22）、`tests/test_synthetic_v3_cli.py`（3）。
- `data/results/v3-evaluation-synthetic-check-2026-11-23-v1.json`：検証結果と出典コードのハッシュ。
- `data/results/integration-design-coverage-2026-11-23-v7.json`、`data/results/research-readiness-2026-11-23-v7.json`、README、仕様/本記録。

## B. 比較結果の扱い

今回、pytest外で戦略比較セットを登録・実行していない。実験登録・成功/停止/失敗/中断はpytestの一時領域だけで確認した。次は既存監査に由来する未解決状態であり、本日の新規価格取得や実データ損益ではない。

|候補|現金以外の実データ比較|主要な残条件|
|---|---|---|
|1475|未評価|不足日足/ウォームアップ、権利/単位/企業行動網羅性、判断時点の額、費用/執行条件|
|1306|未評価|同上|
|1321|未評価|同上|
|1346|未評価|同上|
|2558|未評価|同上|

前回の固定期間監査は各銘柄698日中487日取得・211日不足。2025年の日足243日は揃うが、それだけで開始条件を満たさない。詳細は最新readinessの既存証拠参照を使う。未評価を負けの実証や利益確認として扱わない。撤回済みの予備結果は保存したまま、適格な実データ評価0、採用戦略なし。

## C. 会計とリスク評価

完了結果について、Entry/ClosedTradeとraw OHLCV・費用契約から買付原価、分割後売却口数、出口価格、手数料/影響費用、保有期間、前日注文時刻を再計算する。各日の現金は初期資金−買付支出＋売却純額＋既払分配金から再構成し、保有時価は日別口数と終値から照合する。

Dは保存された当時の権利評価、Rは確定額と当日に存在した権利だけを使い、どちらも既払額を差し引く。日次資産、期末資産差と分配帰属後取引損益の合計まで一致することを要求する。不整合ならAccountingErrorで停止し、成功評価にしない。

純損益・総リターン・年率・PF・勝率・平均利益/損失・期待値・件数・平均保有セッション・資金稼働率・費用・最悪取引・100円予算超過を出す。主DD/シャープはD、RのDD/シャープは別欄。主損益/期待値は確定分配のR帰属。比較基準を混ぜて一つのスコアにはしない。

会計金額はFraction/Decimalで厳密に照合し、平均や比率の表示統計はfloat。年率は旧実装と同じ252セッション以上、シャープは無リスク金利0の仮定。年率が算出不能、分散0、勝ち/負け/取引なし等はnullと理由を表示。損失なしのPFを無限大と表示しない。

CIは決済日単位の10営業日循環ブロック、固定seed20261121・1000回。銘柄間の同日依存を残す。30取引未満または10セッション未満はCIなし。空の再標本は使わず、有効再標本数も返す。適切な将来分布や独立性が保証されたとはしない。CIが正でも合成結果のstatistical_edge_confirmed/adoptedはfalse。

I5の未完了/停止結果はmetrics=null、理由付き。途中の曲線を完了成績にしない。ギャップで予算を超える損失、実測でないスプレッド/スリッページ、全量寄付/引け約定仮定は依然残る。実市場のDDや期待値は今回算出していない。

## 登録・失敗・試行管理

登録時に合成入力と原本バイト列をコピーし、実験ID、固定ケース、優先順、期間、as_of、設定、入力/原本SHA、実装10ファイル・依存定義/lock/CLIのSHA、Python/Pydantic版を保存する。コード/入力の変更後に同じ登録で実行しない。JSONのハッシュは事故検出の整合検査で、データの真正性や悪意に対する証明ではない。

登録可能な設定は既存計画の5個だけ：主設定、片道0bp、片道10bp（spread16/slippage2）、損失予算50円、200円。資金や5%/3枠/5日/2%等は主設定から変更不可。費用とリスクの同時変更、別パラメータ、大量探索、同一条件の別ID反復、ケースごとの優先順変更を拒否する。低水準の合成テストだけは異常系再現の別設定を使っている。

同じ入力版・優先順では最大5方式×5設定の固有ケース。登録予算は宣言集合以下、上限450。450は旧計画の全期間/全体+銘柄別の上限で、このAPIが別登録間の総数を自動集計するわけではない。将来の研究比較セット全体の登録・総回数照合が必要で、今回そのセットを作っていない。費用感度はI5が要求する費用契約と一致した別入力版を明示し、同一入力の費用契約を黙って上書きしない。

実行はローカルファイルロックを取り、STARTED記録を先に排他作成。失敗・中断も予算消費。同じケースの再実行なし。中断でoutcomeがない場合も開始記録を残し、自動復旧/再試行しない。成功COMPLETED、未評価STOPPED、例外FAILEDを別ファイルに保存する。失敗時は段階・型・固定理由コードを保存し、任意の例外本文や原本内容を転記しない。登録が壊れて実験を特定できない場合は実行前に拒否する。

全候補除外は `save_all_excluded` で全候補の理由を必須として別保存し、metrics=null、run_count=0。理由の根拠をこの関数が独立認証するわけではない。既存ファイルは上書きしない。

## D. AI導入

Qwen/MLX、TimesFM、Chronosの既存コードは保持。今回のAI呼出し0。合成の評価成功をAIなし戦略の実市場での成立と解釈しない。資料・費用・再現性と非AIの実データ結果保存が未達のため、AI改善比較の開始条件も未達。可能性の否定ではなく、独立した次段階の研究とする。

## E. 次の優先順位

1. 実市場用の入力契約/監査を仕上げる。税引前口座受取額、分配の単位、情報時刻/利用仮定、時点別取引単位、実際の値幅/規制・費用/執行条件を明確にする。
2. 不足日足とウォームアップ、権利日程・企業行動の網羅性を一次資料で補う。JPX手動対象の日足資料は自動取得しない。原本・過去研究は保持。
3. 候補採否・期間・費用仮定・比較集合・全体回数・SHAを成績確認前に固定し、別の実データ実験を登録する。全候補不可なら除外表で終え、無理に損益を出さない。現CLIでrealデータを有効化しない。
4. 完全未使用の評価が現状ないため探索的結果とし、将来のローカルペーパーフォワードを開始前登録する。実注文計画の許可にはしない。

## F. macOS実行手順

```bash
cd /Users/yuki/dev/stock-pj
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_evaluation_v3.py tests/test_experiment_v3.py tests/test_synthetic_v3_cli.py
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python scripts/run_synthetic_swing_v3.py --help
```

以下はユーザーが任意に実行する合成の現金保有1ケースだけのデモ。実データや既存研究ファイルは使わない。今回はこのデモをpytest外で実行していない。

```bash
SWING_DEMO_DIR="$(mktemp -d /tmp/stock-ai-v3-demo.XXXXXX)"
PYTHONPATH=src:tests .venv/bin/python - "$SWING_DEMO_DIR" <<'PY'
from pathlib import Path
import hashlib, json, sys
from test_swing_v3_schema import fixture, BLOB
root = Path(sys.argv[1]); data = fixture(); raw = json.dumps(data).encode()
(root / 'input.json').write_bytes(raw)
(root / 'source.bin').write_bytes(BLOB)
(root / 'input.sha256').write_text(hashlib.sha256(raw).hexdigest())
(root / 'cases.json').write_text(json.dumps([
    {'case_id': 'cash', 'strategy': 'cash', 'priority': data['symbols'], 'config': {}}
]))
PY
SWING_INPUT_SHA="$(cat "$SWING_DEMO_DIR/input.sha256")"
PYTHONPATH=src .venv/bin/python scripts/run_synthetic_swing_v3.py register \
  --input "$SWING_DEMO_DIR/input.json" --sha256 "$SWING_INPUT_SHA" \
  --as-of 2025-12-31T23:59:59+00:00 --source "s=$SWING_DEMO_DIR/source.bin" \
  --cases "$SWING_DEMO_DIR/cases.json" --directory "$SWING_DEMO_DIR/experiment" \
  --experiment-id synthetic-cash-demo --max-runs 1
PYTHONPATH=src .venv/bin/python scripts/run_synthetic_swing_v3.py execute \
  --directory "$SWING_DEMO_DIR/experiment" --case cash
```

registerとexecuteは別操作。COMPLETEDは終了コード0、STOPPED/FAILEDは1、入力/登録拒否は2。同じケースは再実行不可。結果はoutcomes/cash.json、開始記録はattempts/cash.json。比較研究の承認や利益の証明ではない。

## G. テスト・保持

追加51成功・0失敗、全体 **584成功・0失敗（4.35秒）**。CIの件数成立ケース、252日以上の年率分岐、実際の分配入金を含む損益照合、費用の往復一回控除、D/Rの別リスクも確認。API/CLIの登録成功、停止、失敗、コード/入力/原本変更、ロック、予算、中断、全候補除外、パラメータ制限を検証した。

初回の評価テストは20成功・1失敗。保有セッション改ざんを検出する検査を追加して修正し、失敗履歴を新記録へ残す。その後の追加テストとCLI拡張に応じ再検証したもので、利益が出るまでの再試行ではない。

今回のネット取得、実注文・デモ注文、資金移動、有料API、AI、コミット・プッシュは0。適格な実データ損益評価0。pytest外の新規戦略比較0。旧v2の比較も再実行なし。既存I1〜I5/旧台帳試作/v2の固定成果物SHAと、文書リンク・JSON参照・git diff --checkを確認した。税引後・実市場約定・独立期間再現は未評価。
