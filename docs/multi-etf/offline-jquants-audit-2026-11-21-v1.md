# J-Quants保存原本のオフライン再監査

## 実装

- src/stock_ai/data/jquants_audit.py：取得manifestとJPX価格照合記録を、呼出側が指定するSHA-256で確認。固定5候補を再抽出し、保存済みの成功フラグや集計行を信用せず原本から再検査する。
- scripts/audit_jquants_day.py：認証キー・通信不要のCLI。出力を新規作成に限定し、既存ファイルを上書きしない。監査失敗時に成功報告を作らない。
- tests/test_jquants_audit.py：33ケース。合成のAPI形式データを使用し実市場の収益性とは無関係。

確認項目は固定5銘柄の欠落・重複、原本SHA/サイズ、HTTPS取得先とクエリ、HTTP成功、取得時刻とas-of境界、ファイルのパス逸脱（symlink含む）、JSONキー重複、ページング未完了、銘柄/日付違い、未調整OHLCVの欠損・非有限値・非整数出来高・OHLC不整合、目視照合済みJPX価格記録との一致。調整済みAdj項目への代替や欠損補完は行わない。

返すのは一日分の監査報告で、バックテスト入力形式ではない。qualified_for_backtest=Falseを固定し、全期間カレンダー・単位履歴・企業行動・分配金・執行費用等が未完了と明示する。外部指定SHAは既知の信頼済み値を使用する必要があり、SHA照合だけで資料の内容の正しさや公表当時の利用可能性を証明するものではない。

## 実行結果

保存済み2025-10-24の実原本5件をCLIで再監査し、全5銘柄の未調整OHLCがJPX資料と一致。結果はdata/results/jquants-20251024-offline-audit-v1.jsonに新規保存した。追加API要求0件、実データ損益再計算0件、実注文・デモ注文・有料API呼び出し0件。

pytest全体：**150成功・0失敗（1.80秒）**。変更前117件に今回33件追加。最終コードで全体実行後、文書のみを追加。git diff --check成功。既存の未コミットコード・原本・過去結果は保持し、コミット・プッシュは行っていない。

## macOSでの再実行

```bash
cd /Users/yuki/dev/stock-pj
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python scripts/audit_jquants_day.py \
  --directory data/raw/jquants-20251024-20261121T133610908151Z \
  --manifest-sha256 404e6e9704f21b10bd5f7672975ffa4fc2b450128a88726cebfce6c240e84829 \
  --price-evidence data/results/jpx-20251024-price-audit-v1.json \
  --price-evidence-sha256 449c2e42fe6631f01aa342c2edf5b80f4236d17c62100e003255cb55b770f64d \
  --as-of 2026-11-21T13:37:15+00:00 \
  --output /tmp/jquants-20251024-recheck-new.json
```

出力ファイル名が既存なら別名を使う。as-ofは今回取得原本を読み取れる時点の境界であり、2025年の前向き検証や売買判断の時刻ではない。原本をローカル保存しているためAPIキーは不要。

## 次の課題

このCLIは一日・固定5候補の取得形式に限定する。全期間版への拡張では、監査済み取引カレンダーとの全日照合と、欠損日を削除しない設計、企業行動日付の分離を追加する。分配履歴・1321の分割権利落ち日等の直接資料も引き続き必要。損益比較は開始条件が揃ってから実施する。
