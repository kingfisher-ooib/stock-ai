# 監査済み入力と利用可能時刻

入力はUTF-8 JSONの独立したバージョン。修正時は別ファイル名と別SHAを使う。既存CSV/Parquetの上書きや自動変換は行わない。
`synthetic: false`、`availability_mode: observed`（観測済み情報だけ）または`historical_assumption`（事後取得データでの明示的な過去利用仮定）を必須とする。後者の結果を完全未使用と呼ばない。

- `calendar`: ソート済み重複なしの日付文字列配列。全銘柄で一致し、評価期間の開始/終了営業日を含む。
- `calendar_source`: 公式取引カレンダーの出所。単なる平日生成は実市場用に認めない。
- `instruments`: 銘柄コードから以下へのマッピング。
- `price_basis`: `raw`（当時の実取引単位での未調整値）。後日調整済み価格をそのまま渡さない。
- `bars`: 全calendarの各日に `bar_date,open,high,low,close,volume,observed_at,source`。観測時刻はUTCオフセット必須、対象日の16:00 JST以降。データ取得時刻と当時利用可能だった時刻は混同しない。時点読取は全versionの観測完了後でなければ拒否する。
- `lots`: `date,size`のソート済み配列。最初の日以前の初期単位と以降の変更を含める。全履歴の一次資料はverification_evidenceへ。
- `actions`: この入力期間内の企業行動。`kind: split`は`date,ratio,known_at,source`、`kind: distribution`は`date,amount,pay_date,known_at,source`。dateは市場価格切替日/権利落ち日を使用し、法的効力日や分配決算日を代用しない。金額は権利日当時の1口あたり、ratioは新口数/旧口数。企業行動を配列から省略する際は期間内イベントが存在しないことを一次資料で照合する。
- `verification`: `ohlcv_verified,calendar_verified,lot_history_verified,actions_complete,distributions_complete,execution_cost_verified`の全項目trueが実データ実行に必要。
- `verification_evidence`: 同じキーに監査文書パス/URL/原本SHA等の根拠を指定。フラグ自体はデータの正しさを証明せず、独立した監査担当の判断が必要。

分割は判断時点までに市場効力が生じた分だけ、特徴量用の過去履歴を現時点単位に変換する。将来の分割イベントを過去判断に使用しない。保有口数と損切り参照値も同時に換算。イベントのknown_atは保存するが、経済的な権利処理は市場効力日ベースで行い、事前予測シグナルには使わない。

```bash
shasum -a 256 /path/to/audited-v1.json
PYTHONPATH=src .venv/bin/python scripts/run_multi_etf_swing.py \
  --input /path/to/audited-v1.json \
  --sha256 <確認した64桁SHA-256> \
  --as-of 2026-11-21T12:00:00+00:00 \
  --output /tmp/multi-etf-audited-v1-results.json
```

実データの公開情報収集と日足の全面照合は未完了。上記は接続・注文機能ではなくローカルファイル入力契約である。
