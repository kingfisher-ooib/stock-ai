# J-Quants Free範囲の日足原本取得

## 取得前に固定した計画

ユーザーのローカル.env設定完了を受け、data/results/jquants-free-acquisition-plan-2026-11-21-v1.jsonを取得前に登録した。SHA-256は7f3dc91e328092e241b603b6d7945fcf87b7e4554228c5615fc490c8bcf36f96。

固定候補順1475/1306/1321/1346/2558、Freeの提供範囲と既定研究期間の重なりである2024-08-29～2026-08-28を取得対象とした。各487営業日。最大10要求・各銘柄2ページまで、要求開始間隔13秒、再試行0回。無料範囲外211営業日は対象外理由を計画に保存し、研究の評価期間自体は変更していない。

参照仕様：[Free提供期間](https://jpx-jquants.com/ja/spec/data-spec)、[レート制限](https://jpx-jquants.com/ja/spec/rate-limits)、[未調整日足仕様](https://jpx-jquants.com/ja/spec/eq-bars-daily)。Free期間は2026-11-21を基準とした12週間遅延・2年分の計算であり、将来の取得時点でも同じ期間を取得できることを保証しない。

## 取得・整合性監査結果

5要求すべてHTTP 200、各1ページ487レコード。実要求5回・再試行0回。原本の取得URL、取得時刻、SHA-256、サイズをmanifestへ保存。取得時刻は2026-11-21 14:55～14:56 UTC（日本時間同日23:55～23:56）。

|ETF|期待する営業日|有効な未調整OHLCV|全項目null|期間内レコード欠損|
|---|---:|---:|---:|---:|
|1475|487|487|0|0|
|1306|487|487|0|0|
|1321|487|487|0|0|
|1346|487|487|0|0|
|2558|487|487|0|0|

合計2,435本を保存。原本SHA、OHLC整合性、正の整数出来高、正の売買代金、銘柄と日付、営業日照合、取得時刻、ページ終端をローカルで監査した。これらは配信原本の整合性確認であり、全日付の価格を別資料でも確認したという意味ではない。

別SHAを指定した既存のJPX目視価格記録を、今回の期間取得原本と再比較した。2025-10-24の全5銘柄・20価格項目が一致。範囲監査に任意の目視済み価格資料を接続する処理を追加し、一致した日だけをsource_auditedへ加算する。不一致・重複・参照日の欠落・未確認資料・as-ofより後の確認時刻・SHA違いは拒否する。

## 固定研究期間の残り

下表は5銘柄それぞれ共通。

|固定期間|営業日|原本取得済み|原本未取得|
|---|---:|---:|---:|
|2024開発|245|84|161|
|2025検証|243|243|0|
|2026既視参考|210|160|50|
|合計|698|487|211|

別資料との価格照合完了は各1日で、source_audited=1、価格照合未完了697日は維持。raw_missing_sessions=211と区別する。原本が全日揃った2025年についても、企業行動・分配金・当時単位・費用の条件は未達のため損益を計算していない。完全未使用期間もない。

## 分割境界の原本観察

旧Yahoo資料で尺度に疑義があった日について、今回の未調整配信値を保存した。

- 1306の2026-03-30は始値370円・終値376.4円、調整係数0.1。03-31は始値371.3円・終値371.4円、係数1。前に確認したJPXの分割権利落ち日03-30と整合する観察で、旧Yahooの37円台をそのまま当時値として使えない。
- 2558の2026-06-05は始値3,495円・終値3,477円、係数0.1。06-08は始値3,397円・終値3,404円、係数1。発行会社の市場価格切替06-05と整合する観察で、06-08にもう一度分割調整しない。

これは原本の境界値の記録であり、それ自体から企業行動の完全な履歴や法的効力日を推定していない。旧資料を上書きせず、新しい原本・観察記録を追加した。

## 保管場所と変更

- Git管理外原本：data/raw/jquants-free-range-20261121T145539300336Z/。manifest SHAはe55b81485467b5415b38e603a7691aad95e1a58af87751150bcd18d51d6f4e24。キーを含まない取得スクリプトとそのSHAも保存。
- data/results/jquants-free-range-audit-2026-11-21-v1.json：範囲原本監査。
- data/results/swing-source-snapshot-index-v2.json：今回の範囲版を明示選択。旧単日版との重複登録は行わない。JPX価格資料の別SHAを指定。登録一覧SHAは472445bcb88c0a6a5af4a27147791f515543d9d7c39f3f881b2a895cc072ade9。
- data/results/swing-fixed-period-coverage-2026-11-21-v3.json：全期間の取得・価格照合状況。旧v1/v2を保持。
- data/results/jquants-split-boundary-observations-2026-11-21-v1.json：1306/2558の境界8日分の原本観察。
- src/stock_ai/data/coverage_inventory.py：範囲原本と任意の別SHA価格資料の照合を追加。
- tests/test_coverage_inventory.py：8ケース追加。
- .env.example：JQUANTS_API_KEYの実値を空欄へ戻した。.envはバイト列を変えず保持し、Git管理外であることを確認。

キーを標準出力・コマンド引数・取得スクリプト・manifestへ書き込んでいない。.env.example、Git index内の同ファイル、今回の原本/取得スクリプト/主要結果について実キー文字列が含まれないことを値を表示せず確認した。実際の契約プラン画面は閲覧しておらず、ユーザーのFree利用申告と無料で利用可能な日足エンドポイントに限定した。追加契約・プラン変更・有料専用API利用はしていない。

## テスト・再実行

pytest全体 **245成功・0失敗（1.49秒）**。git diff --check成功。固定configとplanはGit差分なし。実データ損益再計算0回、実注文・デモ注文・資金移動0件。コミット・プッシュなし。

```bash
cd /Users/yuki/dev/stock-pj
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python scripts/inventory_swing_coverage.py \
  --config config/swing.yaml \
  --config-sha256 e56eee7a7d6978f2757717bed79e908c9ef0ed1b9b4b5f05d3488e8bce7f57b4 \
  --calendar data/results/multi-etf-full-calendar-audit-2026-11-21.json \
  --calendar-sha256 709da30dc5203d587975a55ffd10561b03ff60b63da48467dd8ed9641e006396 \
  --snapshot-index data/results/swing-source-snapshot-index-v2.json \
  --snapshot-index-sha256 472445bcb88c0a6a5af4a27147791f515543d9d7c39f3f881b2a895cc072ade9 \
  --as-of 2026-11-21T14:56:31.703134+00:00 \
  --output /tmp/swing-free-range-coverage-new.json
```

出力先が既存なら別名を使う。これはローカル再監査でAPIキー不要。追加取得は新しい事前取得計画・期間・SHAを確認してから行い、同じ原本を上書きしない。
