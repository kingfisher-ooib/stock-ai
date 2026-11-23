# 固定期間のOHLCV原本監査カバレッジ

## 結果

既定の5候補、2024開発・2025検証・2026既視参考という期間を変更せず、登録済みのJ-Quants原本/JPX価格照合の監査完了状況を集計した。

各銘柄（1475/1306/1321/1346/2558）共通：

|期間|予定営業日|本監査を通過した日数|本監査未完了の日数|
|---|---:|---:|---:|
|2024開発|245|0|245|
|2025検証|243|1|242|
|2026既視参考|210|0|210|
|合計|698|1|697|

監査通過日は2025-10-24のみ。5銘柄合計で対象3,490銘柄日、通過5銘柄日、未完了3,485銘柄日。**これは登録した原本監査の進捗であり、他のデータが存在しないという意味ではない。** 既存Yahoo、発行会社NAV、出来高未確認のJPX OHLCなどはこの集計には含めない。出来高の別日別資料との相互照合もまだ残る。

不足日付はdata/results/swing-fixed-period-coverage-2026-11-21-v1.jsonの各銘柄missing_sessionsに全件保存。欠損を埋めたり、取引カレンダーを縮めたり、成績の良い期間・銘柄だけを残したりしていない。qualified_for_backtestはfalse。

## 実装

- src/stock_ai/data/coverage_inventory.py：取引カレンダーの元の祝日CSV・JPX休場規則をSHA付きで再読取し、営業日を再構成して既存カレンダー記録と照合する。固定期間の重複、未割当営業日、不正な端点を拒否。
- 登録するsnapshotはdirectory/manifest_sha256/price_evidence/evidence_sha256を明示。保存済みの成功ラベルを集計せず、audit_jquants_dayで原本を再監査する。重複日版は自動選択せず拒否。出所パスの逸脱やas-of後に取得したカレンダーも拒否。
- scripts/inventory_swing_coverage.py：キー・ネットワーク不要。既存出力は上書き禁止。全日揃っても、企業行動・分配金・単位・費用の検証は別条件のため自動合格させない。
- tests/test_coverage_inventory.py：15ケース追加。監査済みデータの不足、空の登録一覧、原本改変、カレンダー縮小、期間の重複/抜け、不正端点、重複版、対象外日、元監査の失敗伝播、取得時刻、パス逸脱、全日揃っても不採用状態維持を検査。単日原本監査自体は既存テストで検査し、この単体テストでは境界をモック化。

実原本5件とカレンダー原本2件を使ったCLI実行も成功。全体pytest **205成功・0失敗（1.30秒）**。git diff --check成功。固定config/planのGit差分なし。

## macOSの再実行

```bash
cd /Users/yuki/dev/stock-pj
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python scripts/inventory_swing_coverage.py \
  --config config/swing.yaml \
  --config-sha256 e56eee7a7d6978f2757717bed79e908c9ef0ed1b9b4b5f05d3488e8bce7f57b4 \
  --calendar data/results/multi-etf-full-calendar-audit-2026-11-21.json \
  --calendar-sha256 709da30dc5203d587975a55ffd10561b03ff60b63da48467dd8ed9641e006396 \
  --snapshot-index data/results/swing-source-snapshot-index-v1.json \
  --snapshot-index-sha256 57ee61051d5ff44d605bdd17772ce2ff79c6a2eda4a76fe087afd15097ed3f6d \
  --as-of 2026-11-21T13:37:15+00:00 \
  --output /tmp/swing-source-coverage-new.json
```

出力先が既存なら別名を使う。原本がGit管理外なので、このローカル環境の原本が必要。新しい取得版を追加するときは登録一覧を別バージョンとして作り、SHAとas-ofをその版に合わせて確認する。as-ofは今回取得版の読取可能時点であり、当時の市場公表時刻ではない。

## 残る作業

この段階の集計は全期間の日足取得を代替しない。現在の単日監査形式は5候補・1日分を前提としているため、一括取得形式へ広げる際は重複・欠損・分割前後の尺度を検査し、監査前入力を通過扱いしない。Free提供期間外を含めるには利用可能な原本が必要で、固定期間を都合よく縮めない。銘柄別売買停止・臨時休場の確認、分配履歴、1321分割権利落ち日の直接資料、費用も別途必要。

今回の追加API取得0件、実データ損益再計算0回、実注文・デモ注文・有料API・資金移動0件。既存原本・過去結果・未コミット変更を保持し、コミット・プッシュなし。
