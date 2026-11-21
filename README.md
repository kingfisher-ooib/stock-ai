# 株式ETF研究

個別株の銘柄選定を避け、まず指数連動ETFを1銘柄に固定して、ローカルの過去データと仮想取引だけで検証する独立プロジェクト。

## ローカルAI推論環境

この環境は研究用です。証券会社への接続、実発注、デモ口座への注文、資金移動は実装していません。日足によるローカルの仮想売買計算のみ行います。LLMはBUY/SELL/HOLDの候補だけを返し、決定的な`RiskEngine`が注文候補を審査します。候補を送るBroker Adapterは存在しません。モデルの一致やconfidenceは収益性の証拠ではありません。

### 構成

`src/stock_ai/ai`にMLX APIクライアント、TimesFM/Chronosラッパー、予測結果の共通形式、Ensemble、`ResearchPipeline`を置きます。パイプラインは同じ`as_of_index`で両予測器と特徴量を呼び、LLMの出力を必ずRisk Engineへ渡します。`features`は確定済みOHLCVからテクニカル指標を計算し、`risk`は売買候補を制限します。`data/raw`, `processed`, `predictions`, `trades`は今後のローカルデータ置き場です。DuckDBは導入済みで、Parquetへの保存形式はデータ取得と検証計画を固定してから決めます。

### セットアップ（macOS Apple Silicon）

Python 3.12と`uv`が使える場合：

```bash
cd /Users/yuki/dev/stock-pj
uv sync --extra dev --python 3.12
source .venv/bin/activate
```

このマシンでは`uv`を`.uv-bootstrap`に、Python 3.12を`.python`に用意しました。グローバル環境を変更せず再同期できます：

```bash
UV_PYTHON_INSTALL_DIR="$PWD/.python" .uv-bootstrap/bin/uv sync --locked --extra dev --python 3.12
source .venv/bin/activate
```

`uv`の再導入が必要なら公式手順でインストールしてください。`uv`が使えない環境だけ`python3.12 -m venv .venv`と`.venv/bin/pip install -e '.[dev]'`を使います。`.env.example`を必要に応じて`.env`へコピーします。秘密情報は不要です。

### モデル・ライセンス・容量

|役割|採用モデル|精度・実行|チェックポイント概算|ライセンス|
|---|---|---|---:|---|
|LLM|`mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit`|4bit MLX/Metal|17.2 GB|Apache-2.0|
|TimesFM|`google/timesfm-2.5-200m-pytorch`|PyTorch MPS優先、CPU代替|約0.93 GB|Apache-2.0|
|Chronos|`amazon/chronos-2`|PyTorch MPS優先、CPU代替|約0.48 GB|Apache-2.0|

実行時メモリは重み容量だけでなくKV cache、トークナイザ、PyTorch、Metalのワーク領域を含むため変動します。Qwenは概ね18～30GB、TimesFMは約1～3GB、Chronosは約1～3GBを目安とし、同時実行時は合算してください。これは事前見積もりであり、実測値とは分けて扱います。TimesFM 3の重みは非商用・非本番の条件があるため採用せず、パッケージ`timesfm==3.0.2`内の2.5実装とApache-2.0の2.5重みを使います。

2026-11-15実測（M5 Pro/48GB、ウォーム状態）：Qwenサーバーの`vmmap`物理フットプリント17.9GB、100項目・291出力トークンの固定プロンプトで最初の出力まで0.431秒、生成約92.9トークン/秒。初回の17.2GBダウンロードは約15分。TimesFM 2.5とChronos-2の5点予測は両方`mps`で成功しました。QwenはMLX/Metalで実行されます。これらはダミー入力での動作・速度測定であり、予測精度や売買成績を示しません。

モデル名は`.env`の`MLX_MODEL`、`TIMESFM_MODEL`、`CHRONOS_MODEL`で設定します。TimesFM/Chronosラッパーはライセンス確認済みIDのみ受け付けます。変更する場合はライセンスとAPIの再確認が必要です。

### 起動・停止・検証

初回はモデル約17.2GBを取得するため、スクリプトがモデル名と概算容量を表示してから起動します。APIは`127.0.0.1:8080`のみにbindします。

```bash
bash scripts/start_mlx_server.sh
```

別のターミナルで：

```bash
source .venv/bin/activate
python scripts/smoke_test.py
python scripts/test_mlx.py
python scripts/test_timesfm.py
python scripts/test_chronos.py
python scripts/benchmark_mlx.py
python -m pytest -q
```

サーバー停止は起動ターミナルで`Ctrl-C`です。Smoke Testは実際にモデルをロードしダミーデータを推論します。初回実行ではダウンロード時間がかかります。サーバー未起動、GPU制限、モデル取得失敗などは`FAILED`と原因・推奨対処を表示します。

### モデル保存場所・削除

標準保存先は`~/.cache/huggingface/hub`です。`HF_HOME`を指定した場合は`$HF_HOME/hub`です。MLX、TimesFM、Chronosは各Hubのスナップショットに入ります。使用量と対象を確認してから削除してください：

```bash
du -sh ~/.cache/huggingface
.venv/bin/hf cache ls
```

サーバーや推論プロセスを停止した後、`hf cache rm model/mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit`のように対象モデルだけを削除します。TimesFMやChronosも`model/google/timesfm-2.5-200m-pytorch`、`model/amazon/chronos-2`に置き換えます。現行Hubは実体を共通blobに置くため、個々の`models--...`ディレクトリに対する`du`は容量を過小表示することがあります。`HF_HOME`を変更した環境では同じ環境変数を設定して`hf cache`を使います。

### 検証上の制約と次の段階

特徴量は`as_of_index`までの確定足のみで計算します。予測入力もその時点までの履歴に限定し、予測値には生成時刻、対象時刻、モデル版、入力範囲を将来保存します。評価期間は調整期間より後ろに時系列で分け、調整に使った期間を未使用期間として再利用しません。分割・配当調整や市場カレンダーも当時知り得た情報で再現します。

今回の固定ベースラインは、約定・費用・Risk Engineの適用順序を明示できる小さなPython実装で計算しました。将来外部ライブラリに移すなら`backtesting.py`を候補とし、単一ETFの日足で同じ約定条件を再現できるか照合します。`vectorbt`は大量のパラメータ比較で探索過多を招きやすいため保留します。いずれも現在は未導入です。

### 1475日足の探索的検証

入力のSHA-256を照合して、取得時刻・仮定した利用可能時刻・出所を持つParquetを作成します。実際に2024～2026年の各時点でYahooの後日修正済み日足を入手できたという意味ではありません。通常の`load_bars_as_of`は実際の取得時刻で制限し、過去検証では`historical_assumption`を明示します。

```bash
python scripts/build_1475_snapshot.py
python scripts/run_1475_baseline.py
```

条件を事前固定した探索結果は[計画](docs/research-plan-2026-11-15.md)と[結果](docs/1475-exploratory-results-2026-11-15.md)を参照。片道5bpでは開発313件・純損益−914.65円、後方135件・−774.76円でした。採用ルールは0件です。実データの全面照合と執行費用の確認前に、利益を見込める検証結果とは扱いません。

次の低コスト検証では、トレンド、トレンド内押し目、出来高確認モメンタムの3ルールだけを事前固定し、同一の約定・リスク条件で比較します。主条件は片道5bpで、開発区間の取引数30以上、純損益>0円、PF>1、1取引期待値95%区間の下限>0円をすべて満たす必要があります。2026年は既に結果を見た参考区間であり、未使用評価ではありません。

```bash
PYTHONPATH=src python scripts/run_1475_three_signal_screen.py
```

設計は[3シグナル比較](docs/superpowers/specs/2026-11-15-three-signal-screen-design.md)、保存結果は`data/results/1475-three-signal-screen-2026-11-15.json`です。固定手数料0円は口座コース未確認の仮定であり、通過しても新しい未使用期間なしに採用しません。

2026-11-15の固定実行では3ルールとも不合格でした。主条件5bpの開発区間は、トレンド313件・−914.65円・PF 0.69、押し目73件・+113.66円・PF 1.18、出来高モメンタム53件・−323.78円・PF 0.43。押し目の1取引期待値95%区間は−4.14～+8.40円で0をまたぎ、既視の2026年区間も36件・−1.22円・PF 1.00だったため採用しません。比較後の閾値変更は行っていません。

### 1475ペーパーフォワード検証

2026-11-13より後に初めて観測する日足だけで、固定した3ルールを継続評価します。楽天証券への接続や注文はありません。初回だけ次を実行し、固定スナップショットから次の取引日用判断を凍結します。

```bash
PYTHONPATH=src python scripts/init_1475_paper_forward.py
```

新しい日足は、次の形式で1日1ファイルのJSONとして保存します。`source_observed_at_utc`には、その値を実際に確認したUTC時刻をタイムゾーン付きで記録します。未来データ混入防止のため、対象日の16:00 JSTより前の観測時刻は拒否します。

```json
{
  "bar_date": "2026-11-16",
  "open": 0,
  "high": 0,
  "low": 0,
  "close": 0,
  "volume": 0,
  "source_observed_at_utc": "2026-11-16T07:00:00+00:00",
  "provenance": "取得元とファイル名"
}
```

価格と出来高を実値へ置き換え、次で前回判断の仮想決済と次回判断を記録します。休日は入力せず、次に観測された取引日をそのまま使用します。

```bash
PYTHONPATH=src python scripts/record_1475_forward_bar.py --input /path/to/1475-2026-11-16.json
```

複数日をまとめて取り込む場合はCSVまたはJSON配列を使用できます。CSVの必須列は次の6列です。

```csv
bar_date,open,high,low,close,volume
2026-11-16,400.0,403.0,399.0,402.0,100000
2026-11-17,402.0,405.0,401.0,404.0,120000
```

全行を同時に確認した場合は、確認したUTC時刻を1回指定します。入力ファイル名とSHA-256は自動的に各行の出所へ記録されます。

```bash
PYTHONPATH=src python scripts/import_1475_forward_bars.py \
  --input /path/to/1475-new-bars.csv \
  --observed-at 2026-11-17T08:00:00+00:00
```

各行に`source_observed_at_utc`と`provenance`があるCSV/JSONなら`--observed-at`は不要です。日付順は自動整列しますが、重複日付、既存最終日以前、対象日の16:00 JSTより前、不正なOHLCVが1件でもあれば、バッチ全体を保存しません。

状態は`data/paper/1475-state.json`、ハッシュチェーン付き監査ログは`data/paper/1475-journal.jsonl`に保存され、Git管理外です。重複・過去日付、OHLCV不整合、時刻なし、元データまたはログの改変を検出した場合は更新しません。保存途中で停止して状態とログが不一致になった場合も処理を止め、証拠を自動削除・修復しません。ハッシュは偶発的変更の検出用で、外部署名ではありません。設計は[ペーパーフォワード設計](docs/superpowers/specs/2026-11-15-paper-forward-design.md)を参照してください。

[JPX月次表との照合と費用条件](docs/1475-data-and-cost-audit-2026-11-15.md)では、34ファイル・689日を月次集計で比較し、価格2項目と出来高2項目の差を確認しました。2価格だけの修正では固定ルールの損益は変わりません。再実行は`PYTHONPATH=src python scripts/audit_jpx_monthly.py`と`PYTHONPATH=src python scripts/run_1475_data_repair_sensitivity.py`です。元データと元の探索結果は保持します。

後続のETF月間平均33ファイルと1月15日の日報で差分を3日に絞りました。再実行は`PYTHONPATH=src python scripts/audit_jpx_etf_quotes.py`と`PYTHONPATH=src python scripts/run_1475_ohlcv_repair_sensitivity.py`。7項目の候補修正では開発区間の損益が約0.66円悪化し、既視の2026年区間は変わりません。3月29日の高値・日別出来高は一次資料未確認で、元データは変更していません。

楽天証券のSOR注文では「寄付」「引け」を選べませんが、ゼロコースでも寄付・引け注文は東証に発注できると公式FAQに明記されています。既存バックテストは約定成立や価格を保証する試算ではありません。Risk Engineは往復手数料見積りを1取引損失枠から控除して数量を決めます。超割コースの5万円以下・片道55円を仮適用した結果は[費用監査](docs/1475-data-and-cost-audit-2026-11-15.md)と`data/results/1475-cho-wari-fee-gate-2026-11-15.json`を参照。再実行は`PYTHONPATH=src python scripts/run_1475_fee_gate.py`。口座コース・実約定費用は未確認です。

公式資料：[MLX-LM server](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md)、[Qwen MLXモデル](https://huggingface.co/mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit)、[TimesFM 2.5](https://huggingface.co/google/timesfm-2.5-200m-pytorch)、[Chronos-2](https://huggingface.co/amazon/chronos-2)、[TimesFMライセンス方針](https://github.com/google-research/timesfm/blob/master/README.md)。

## 現在地（2026-11-15）

- 最初の調査候補はTOPIX連動ETFの1475。銘柄選択は研究上の固定であり、買付推奨ではない。
- 東証公表の売買単位は10口。2026-11-11の日報終値407.8円なら1単位4,078円。これは資金10万円での最低売買額の概算に限る。
- 1取引の損失予算は100円（資金10万円の0.1%）を暫定的に引き継ぐ。ギャップや約定ずれで実損失が上回る可能性がある。
- 楽天証券のゼロコースはSOR（Rクロスを含む）の利用同意などの条件を満たせば現物委託手数料0円。超割コースは5万円以下の1約定55円。利用者の口座コース、売買スプレッド、約定ずれは未確認。
- 東証の無料日報で日次OHLC、ETF気配提示統計で日次の気配情報を確認できる。過去5分・10分足のBid/Askを取得したわけではない。
- 1475は2024-08-08に市場価格と売買単位が変わり、受益権分割の効力発生日は2024-08-13。無料Yahoo日足698行の品質監査で8月8・9日の価格が約10分の1、2025-10-24がOHLCV欠損と判明。`data/results/data-quality-2026-11-15.json`を参照。
- 東証の日報で3営業日を置換した研究用日足698行を `data/processed/1475-daily-split-normalized-2024-2026.csv` に作成。再生成は `python3 scripts/prepare_daily_1475.py`。置換以外の日足は未全面照合、過去Bid/Ask・実約定データもない。`data/results/cleaning-manifest-2026-11-15.json` を参照。
- ローカルQwenへの仮説依頼は1回だけで候補なし。「予測パターンは存在しない」という回答内の断定は根拠不足として採用しない。その後、Pythonで固定した単純ベースラインを探索的に1回検証したが赤字。採用ルール0件。

## 次の作業

2026-11-21時点の状態。1475単独の日中研究と複数ETFスイング研究は別の検証として扱う。どちらも採用戦略はない。

1. **新規日足の記録**：1475ペーパーフォワードは2026-11-13確定足で停止中。11月16〜20日分を今から取得する場合は遡及資料として別保存し、未使用の前向き検証件数に含めない。現在の[一括インポーター](scripts/import_1475_forward_bars.py)には遡及と前向きを分ける仕組みがないため、まずその区別と再開手順を整える。3ルールの条件は固定する。
2. **一次資料の照合**：1475の2024-03-29の高値・終値は[JPX原本で確認済み](docs/multi-etf/1475-20240329-audit.md)。同日の出来高と他の日足差分は未確認。JPX過去日報の手動取得資料で5候補のOHLCVと企業行動・分配金を照合し、原本のハッシュと取得時刻を残す。
3. **執行費用の確定**：楽天証券の現物手数料コース、寄付・引けの実際の気配と約定可能性を確認する。月次平均スプレッドは寄付時の実費用として流用しない。
4. **研究の再判定**：上記の品質ゲートを満たした銘柄だけ、固定済み[複数ETFスイング計画](docs/multi-etf/plan.md)で評価する。2026年の既視区間を未使用期間と呼ばず、利益・PF・期待値区間が未計算の間は採用しない。現在の詳細な不足項目は[最終研究記録](docs/multi-etf/research-record-2026-11-21-final.md)に記載。

## 出典

- [東証：1475の売買単位変更](https://www.jpx.co.jp/news/1030/20240722-01.html)
- [東証：日報](https://www.jpx.co.jp/markets/statistics-equities/daily/index.html)
- [東証：ETF気配提示・取引状況](https://www.jpx.co.jp/equities/products/etfs/quoting-data/index.html)
- [東証：月間相場表](https://www.jpx.co.jp/markets/statistics-equities/price/)
- [東証：ETF気配提示・取引状況](https://www.jpx.co.jp/equities/products/etfs/quoting-data/)
- [東証：2024年1月15日の日報](https://www.jpx.co.jp/english/markets/statistics-equities/daily/o4sio70000005r5s-att/stq_20240115.pdf)
- [東証：2024年4月1日の日報](https://www.jpx.co.jp/markets/statistics-equities/daily/mklp770000003i2z-att/stq_20240401.pdf)
- [ブラックロック：1475ファクトシート](https://www.blackrock.com/jp/individual/ja/literature/fact-sheet/1475-ishares-core-topix-etf-fund-fact-sheet-ja-jp.pdf)
- [楽天証券：現物取引手数料](https://www.rakuten-sec.co.jp/web/domestic/stock/commission.html)
- [楽天証券：SOR注文の基本ルール](https://www.rakuten-sec.co.jp/web/domestic/sor/rule/ground_rules.html)
- [楽天証券：ゼロコースの寄付・引け注文FAQ](https://www.rakuten-sec.co.jp/web/info/info20230831-03.html)

## 複数ETFスイング研究（2026-11-21）

1475/1306/1321/1346/2558候補に対する研究基盤を追加しました。現金、配分上限付き単純保有、固定したA（トレンド）/B（押し目）/C（ブレイクアウト）を比較できます。初期資金10万円、最大3銘柄、損失予算100円、最大ポジション5%を専用の`config/swing.yaml`に設定しています。

**現時点は採用戦略なし。監査済み日足・企業行動・分配金・執行費用が未整備のため、実データによる収益性評価は未実施です。** 150通りの合成実行は実装テスト専用です。既存1475の結果、AI構成、ペーパーフォワード状態は保持しています。

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python scripts/run_multi_etf_swing.py --output /tmp/multi-etf-exclusions-new.json
PYTHONPATH=src .venv/bin/python scripts/run_multi_etf_swing.py --synthetic --output /tmp/multi-etf-synthetic-new.json
```

出力は上書き禁止です。再実行時は新しい出力名を使ってください。
[事前固定計画](docs/multi-etf/plan.md)、[候補調査](docs/multi-etf/investigation.md)、[結果・リスク・開発優先順位](docs/multi-etf/results.md)、[入力仕様](docs/multi-etf/input-schema.md)を参照してください。

実データ整備の追加進捗：JPX原本67ファイルから5候補の174価格区間・165気配統計を抽出、1475の2026年210営業日のカレンダー一致を確認しました。公式NAV履歴は取引所OHLCVと区別して保存しています。[取得結果・残る不足・再実行手順](docs/multi-etf/data-progress-2026-11-21.md)を参照してください。追加後のpytestは99成功・0失敗です。

続く監査で、内閣府祝日CSVとJPX休場規則から1475の全698営業日（2024〜2026年11月13日）の日付一致を確認しました。旧日報URLの404と過去株価原本の手動取得方針を記録し、ローカル原本登録機能を追加しています。[全期間カレンダー監査・手動取得が必要な資料](docs/multi-etf/daily-access-2026-11-21.md)を参照してください。テストは114成功・0失敗。実データ収益性評価は未実施です。

## 最終研究記録（2026-11-21）

[最終記録](docs/multi-etf/research-record-2026-11-21-final.md)を追加しました。

**結論: 採用戦略なし。実データによる収益性評価は未実施。**

5銘柄（1475/1306/1321/1346/2558）すべてが実データ検証の開始条件を満たさないため、判断材料が得られていない。利益が確認できないことは確認できていない。

追加で確認した事項:
- JPX月次スプレッド統計から5銘柄の月次平均スプレッド・出来高を抽出（`data/results/multi-etf-spread-inventory-2026-11-21.json`）
- 1306/1321の野村AM NAV CSVから分配金（NAV基準）を抽出（`data/results/multi-etf-distribution-inventory-2026-11-21.json`）
- 1321/1346は5%配分上限で1単位が購入できないことを確認
- 1475/1306/2558（分割後）は資金面で可能だが、日足データが未整備

次の優先課題は、JPXの日足原本を手動取得し、1475/1306/2558の2024-2026年の日足OHLCV・企業行動・分配金・執行コストを揃えることです。
