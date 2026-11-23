# 株式ETF研究

**複数ETF研究の現在地（2026-11-23）：採用戦略なし、実データの収益性は未判定。** [銘柄別の開始条件・到達点・残資料の基礎報告](docs/multi-etf/readiness-report-2026-11-22.md)と以下の最新設計・実装記録を参照してください。v1の実データ比較は約定モデルの問題で停止し、v2は合成検証専用です。以下の過去研究と最新状態を区別します。

最新設計（2026-11-23）：[研究用の統合設計と完了条件](docs/multi-etf/integration-design-2026-11-23-v1.md)。7要求と6段階の実装順序、後日確定分配金と判断時点の情報の分離、資金拘束・原価・税引前/端数停止の扱いを整理しました。実市場用契約・市場資料の確認は未完了です。対応表は `data/results/integration-design-coverage-2026-11-23-v7.json`、最新状態は `data/results/research-readiness-2026-11-23-v11.json`。

最新の追加実装：[原本からの開始条件再監査CLI](docs/multi-etf/readiness-originals-audit-2026-11-23-v1.md)。明示指定したv10報告について証拠37件のSHAと日足coverageを再監査し、各期間の開始前60営業日を再計算しました。集計の改変や参照差し替え・合格への書き換えを拒否します。追加28件を含む全pytestは612成功・0失敗。日足の不足は各270日のままで、実市場リリースと実データ損益計算は行っていません。

分配金の時点監査：[見込額と確定額・不整合日程の記録](docs/multi-etf/distribution-revision-audit-2026-11-23-v1.md)。1346の2025年7月見込391円と確定390円を別版として保存しました。現行BlackRock日程PDFは見出し年と掲載年の不一致等があり、過去の権利日取り込みには使用していません。公開時刻は未確認、既存の権利・改訂台帳テスト27件成功。実データ損益は未評価です。

最新監査：[無料範囲の1営業日追加取得](docs/multi-etf/free-increment-acquisition-2026-11-23-v1.md)。2026-08-31の5銘柄5本を取得・原本監査し、各488営業日へ更新しました。固定期間の不足は各210日、開始前60日を含めると270日です。独立価格照合は各1日のままです。[開始条件の再点検](docs/multi-etf/market-readiness-reassessment-2026-11-23-v1.md)で整理した企業行動・分配金・実市場用契約等の未確認事項は残り、実データ損益は計算していません。

v3の基礎部品：[I1入力スキーマ](docs/multi-etf/v3-schema-implementation-2026-11-23-v1.md)、[I2権利口数・分配金改訂](docs/multi-etf/v3-entitlement-implementation-2026-11-23-v1.md)、[I3現金・支払・注文別資金拘束](docs/multi-etf/v3-cash-implementation-2026-11-23-v1.md)。入金による未収残高の減少、二重使用防止、前日注文への当日資金流用防止を合成確認しました。実市場用契約は未完了で、実データの入口は閉じたままです。

保有部品：[I4ポジション・原価・分割調整](docs/multi-etf/v3-positions-implementation-2026-11-23-v1.md)。現金との照合、保有からの売却数量決定、分割時の総原価保存、売却後の分配帰属を実装しています。

統合実行器：[I5合成専用実行器](docs/multi-etf/v3-orchestrator-implementation-2026-11-23-v1.md)。I1〜I4を接続し、前日注文・日次制限・保有期限・期末決済・D/R曲線と未知額停止を検証しています。

最新実装：[I6会計照合・指標・実験登録・CLI](docs/multi-etf/v3-evaluation-implementation-2026-11-23-v1.md)。日次/最終会計、D/Rリスク、期待値CI、固定ケース/予算、失敗・中断保存まで合成確認し、全584テスト成功。I1〜I6の合成基盤は接続済みですが、実市場用契約・不足資料・研究比較セット全体の登録は未完了です。pytest外の新規比較と実データ評価は0件です。

最新実装：[企業行動台帳の合成検証](docs/multi-etf/corporate-ledger-implementation-2026-11-22-v1.md)。直前引け口数・市場切替後口数・未収分配金・現金を分ける独立部品を追加し、全373テスト成功。既存エンジンへの接続は未実施で、同日イベントと実データの拒否を維持しています。適格な実データ評価は0件です。撤回した過去の予備計算は保存しています。

分配金の照合状況：[分割時の権利口数・同日イベントの停止検証](docs/multi-etf/split-entitlement-audit-2026-11-22-v1.md)。金額観察23件、発行者資料に権利落ち日の記載があるもの5件。支払開始日の記載12件・予定11件、口座での現金利用可能日は未確認です。[基準日訂正](docs/multi-etf/remaining-distribution-audit-2026-11-22-v1.md)と[支払予定日照合](docs/multi-etf/maxis-payment-audit-2026-11-22-v1.md)も保持しています。

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

2026-11-13より後の日足で、固定した3ルールを継続評価します。楽天証券への接続や注文はありません。初回だけ次を実行し、固定スナップショットから次の取引日用判断を凍結します。

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

価格と出来高を実値へ置き換え、次で記録します。休日は入力せず、次に観測された取引日をそのまま使用します。対象日の16:00 JST以降に実際に観測し、直前の判断が対象日の9:00 JSTより前に存在した場合だけ`forward`として仮想決済を評価します。それ以外は`retrospective`として日足と次回判断を記録しますが、取引件数・損益・残高は変えません。過去に取得済みの日足なら、実際の取得時刻を記入し、取得日を偽装しないでください。

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

各行に`source_observed_at_utc`と`provenance`があるCSV/JSONなら`--observed-at`は不要です。日付順は自動整列しますが、重複日付、既存最終日以前、対象日の16:00 JSTより前、不正なOHLCVが1件でもあれば、バッチ全体を保存しません。一括取込の出力には`forward_bar_count`と`retrospective_bar_count`を表示します。例えば11月21日に初めて取得した11月16〜20日足は全件`retrospective`となり、その後の取引日の判断を準備する履歴にだけ使います。

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

1. **新規日足の記録**：1475ペーパーフォワードは2026-11-13確定足で停止中。11月16〜20日分を今から取得する場合は、実際の取得時刻と出所を記録して[一括インポーター](scripts/import_1475_forward_bars.py)で取り込む。遡及資料は取引件数・損益に含めず、次の取引日から前向き検証を再開する。3ルールの条件は固定する。
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

2026-11-21追加：J-Quantsから2025-10-24の5候補の調整前OHLCVを取得し、OHLC全20項目がユーザー提供JPX資料と一致しました。[取得・照合記録](docs/multi-etf/jquants-20251024-crosscheck-2026-11-21-v1.md)に出来高・出所・原本SHAを記録しています。一日分の部分確認であり、全期間の評価開始条件は未達です。過去に品質検査を回避した予備損益の採否結論は[訂正記録](docs/multi-etf/invalid-preliminary-results-correction-v1.md)のとおり撤回し、収益性判断不能・採用戦略なしを維持します。

保存済みJ-Quants原本を、APIキーなしで再監査する[オフライン監査CLI](docs/multi-etf/offline-jquants-audit-2026-11-21-v1.md)を追加しました。SHA・時点指定・固定5候補・未調整OHLCV・JPX価格記録との一致を検査し、不備を補完せず拒否します。一日分の確認からバックテスト合格へ昇格させません。追加33ケースを含むpytestは150成功・0失敗です。

続いて[時点指定・合成指定の検査](docs/multi-etf/snapshot-guard-fix-2026-11-21-v1.md)を修正しました。企業行動・記録済み単位情報のknown_atがas-ofより後なら読み取りを拒否し、市場由来の入力にsyntheticフラグを付けただけでは品質検査を通過させません。追加14ケースを含む最新pytestは164成功・0失敗です。

[執行時の時点・単位検査](docs/multi-etf/execution-guard-fix-2026-11-21-v1.md)も修正しました。現金・単純保有・最終日・準備履歴の観測時刻を事前検査し、売買単位をまたぐ前日注文を失効させ、未対応の単位未満売却を損益に計上しません。追加26ケースを含む最新pytestは190成功・0失敗です。

[固定期間の原本監査カバレッジ](docs/multi-etf/fixed-period-coverage-2026-11-21-v1.md)を出力するCLIを追加しました。元の祝日・休場規則と登録日足原本を再検査し、各銘柄698営業日のうち本監査通過1日・未完了697日を日付付きで保存しています。これは他の既存資料が存在しないという意味ではありません。追加15ケースを含む最新pytestは205成功・0失敗です。

[複数日・ページ分割原本の監査](docs/multi-etf/range-audit-2026-11-21-v1.md)に対応しました。原本の存在、価格照合完了、配信元の約定なし、未取得を分けて記録し、原本が揃っただけではバックテスト合格にしません。追加32ケースを含む最新pytestは237成功・0失敗。追加の市場データ取得は未実施です。

その後、[J-Quants Free範囲の原本取得](docs/multi-etf/free-range-acquisition-2026-11-21-v1.md)を実施しました。2024-08-29～2026-08-28の各487営業日、5銘柄合計2,435本を取得し、期間内の欠損・全null・OHLCV不整合はありませんでした。固定研究期間では各211営業日が未取得。別JPX資料による価格照合完了は各1日のままで、企業行動・分配金・費用等の条件も未達のため損益評価は未実施です。最新pytestは245成功・0失敗。実キーは.envだけに置き、.env.exampleには保存しません。

分配金の追加照合（2026-11-22）：[一次資料の確認記録](docs/multi-etf/distribution-audit-2026-11-22-v1.md)。1475の2025年2月・8月、1346の7月、2558の6月・12月の確定額を保存した。権利落ち日など未確認項目を残し、実データの戦略損益評価は開始していない。

2025年の検証開始条件：[分配金8件の台帳と開始時の買付可能性](docs/multi-etf/validation-readiness-2026-11-22-v1.md)。既存の最大ポジション比率5%では、確認した単位を仮適用した場合、1475以外は2025年の全寄付で開始時上限5,000円を超える。条件は変更せず、実データ損益は未評価。

楽天証券の公開条件と実装点検：[費用・約定仮定の確認記録](docs/multi-etf/broker-execution-review-2026-11-22-v1.md)。手数料0円の適用条件を保存し、単純保有に誤適用されていた日次損失決済を修正。pytest 247成功・0失敗。寄付価格の判明後に同じ寄付で判断・約定する仮定など、実行可能性の未解決点を記録した。実データ損益は未評価。

現行v1の実データ計算：[約定モデルの事前確認と次版設計案](docs/multi-etf/execution-preflight-2026-11-22-v1.md)。A/B/Cの寄付後情報を同じ寄付へ遡って使う問題が解消するまで、実データの比較を計算前に停止し、除外理由を保存する。合成テストは継続可能。pytest 251成功・0失敗。

v2の前日注文モデルを別実験として追加しました：[事前固定計画](docs/multi-etf/plan-v2.md)、[実装・テスト記録と実行手順](docs/multi-etf/v2-implementation-2026-11-22-v1.md)。寄付後情報による事後取消しをなくし、日次損失制限を終値判定・翌寄付処理へ変更。初期資金10万円・暫定損失予算100円を維持。合成比較30回、pytest 280成功・0失敗。v2も実データ入力を拒否し、収益性は未判定です。

呼値・値幅・配分の追加監査：[確認記録](docs/multi-etf/market-rules-audit-2026-11-22-v1.md)。2025年5月7日の制度変更を確認し、未確認の過去適用表・日次値幅・配分数量を推測しない独立検査を追加しました。改定後各163営業日、OHLC計3,260項目は、資料上の単位を仮適用した場合の呼値不整合0件。pytest 325成功・0失敗。実データの約定・収益性は未確認です。

権利日の再構成：[T+2ルールと確認済み確定日からの候補](docs/multi-etf/entitlement-reconstruction-2026-11-22-v1.md)。1475の2025年2月・8月について権利落ち候補2/6・8/7を別記録に保存し、直接確認済みの権利落ち日へ格上げしていません。既知の1306・1321スケジュールとの一致を確認。pytest 335成功・0失敗。
