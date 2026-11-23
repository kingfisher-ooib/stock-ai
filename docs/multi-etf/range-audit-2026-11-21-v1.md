# 複数営業日・ページ分割日足のローカル監査

## 実装と区別する状態

src/stock_ai/data/jquants_range.pyとscripts/audit_jquants_range.pyを追加した。保存済みJSON原本をネットワーク・認証キーなしで監査する。新しい形式はrole=jquants_range_snapshot_v1、period=[開始日,終了日]とrequests配列を持つmanifest。従来の単日取得manifestも読み取り専用で受け付ける。

requestsの各要素はsymbol/url/file/sha256/bytes/http_status/requested_at/observed_at。URLは日足V2のcode/from/to（単日旧形式ではdate）と必要なpagination_keyだけを許可。ヘッダーやAPIキーは保存しない。原本ファイルはmanifestと同じディレクトリに置き、別ページには別ファイル名を使う。

固定5銘柄ごとに、取得条件とカーソルの連鎖、原本SHA/サイズ、取得日時、銘柄・日付、未調整OHLCV/売買代金、カレンダーを検査。重複行・対象外日・不正な値・部分null・ページ欠落・循環カーソルを拒否する。調整済み項目で未調整値を代替しない。

以下を区別する：

- raw_ohlcv_available：数値が存在し整合する配信原本。別資料との価格照合完了を意味しない。
- provider_reported_no_trade：O/H/L/C/Vo/Vaが全て存在し全てnull。価格足を作らず、無約定・売買停止等の原因も確定しない。
- missing_sessions：期待する市場営業日のレコードそのものがない。前日値で埋めず、カレンダーからも削除しない。

[公式ページング仕様](https://jpx-jquants.com/ja/spec/pagination)の検索条件維持・カーソル受け渡し・終端確認に従う。ただしページ取得の途中に配信データが更新される場合、APIは取得全体の一貫性を保証しない。このローカル検査だけでも完全な版一貫性は証明できない。[日足仕様](https://jpx-jquants.com/ja/spec/eq-bars-daily)に基づき、出来高は調整前の口数・東証立会内を対象とする。

## 全期間不足一覧への接続

coverage_inventory.pyは登録一覧のformatをjquants_day_v1（従来、省略可）とjquants_range_v1に分けて受け付ける。range形式ではprice_evidenceを要求しない代わり、未照合の原本を照合済み件数に加算しない。

- raw_available：配信原本の有効なOHLCVがある日数。
- provider_no_trade_sessions：配信元が約定なしと示す日。
- raw_missing_sessions：配信レコードを登録できていない日。
- source_audited / missing_count：従来どおり単日原本と目視済みJPX価格資料の照合完了/未完了件数。

同一銘柄・日付についてday/rangeを重ねて登録しても自動的に都合のよい版を選ばず拒否する。どの状態でもqualified_for_backtestはfalse。銘柄別売買停止、企業行動、分配金、当時単位、費用は別監査条件。

## 実行とテスト

- tests/test_jquants_range.py：29ケース。複数日、ページ連鎖、未完了・循環・重複、欠損・全null・部分null、非有限値・不正OHLCV、改変原本、時点境界、銘柄/日付違い、対象候補欠落、認証情報をクエリに含むURL、ファイル逸脱など。
- tests/test_coverage_inventory.py：range接続の3ケース追加。原本の存在を価格照合済みに昇格しないこと、約定なしと未取得を混同しないこと、不明形式を拒否することを確認。
- 実原本：既存の2025-10-24の5銘柄を旧manifestのまま新parserで読取成功。実際の複数営業日取得・ページングはまだ未実施で、複数日/ページの動作は合成fixtureで検証した。
- 全体pytest：**237成功・0失敗（2.39秒）**。前回205件に32件追加。
- git diff --check成功。config/swing.yaml、固定planに変更なし。

実行結果は新しいdata/results/jquants-range-compatibility-audit-2026-11-21-v1.jsonとswing-fixed-period-coverage-2026-11-21-v2.jsonへ保存。旧v1は保持。新しい市場データは増えておらず、5銘柄とも照合完了1日・未完了697日のまま。

## macOSの実行例

```bash
cd /Users/yuki/dev/stock-pj
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python scripts/audit_jquants_range.py \
  --directory data/raw/jquants-20251024-20261121T133610908151Z \
  --manifest-sha256 404e6e9704f21b10bd5f7672975ffa4fc2b450128a88726cebfce6c240e84829 \
  --calendar data/results/multi-etf-full-calendar-audit-2026-11-21.json \
  --calendar-sha256 709da30dc5203d587975a55ffd10561b03ff60b63da48467dd8ed9641e006396 \
  --as-of 2026-11-21T13:37:15+00:00 \
  --output /tmp/jquants-range-check-new.json
```

出力は上書き禁止。calendarsは既知のSHAを外部指定した既存監査記録を使用し、全期間集計側では祝日・休場規則の原本から営業日を再構成する。

## 外部データ取得の条件

環境変数JQUANTS_API_KEYと、このリポジトリの.env内の同名項目について、値を表示せず有無だけを確認したところ、どちらも未設定だった。チャットに公開されたキーは再利用していない。再発行したFreeキーをユーザーがローカル設定する必要がある。キー自体をチャットへ送らない。

今回の追加認証API呼び出し0件、実データ損益再計算0回、実注文・デモ注文・資金移動・有料API0件。コミット・プッシュなし。既存の未コミット変更と原本を保持した。
