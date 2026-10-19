# NeCosmos

猫たちがつくる、小さな生態圏を観察するブラウザ向けシミュレーションプロトタイプです。

## Files

- `public/index.html` — Cloudflare Workerで配信するV0.7
- `NeCosmos_v07.html` — V0.7の保管用原本
- `NeCosmos_v05.html` — V0.5の保管用原本
- `NeCosmos_v04.html` — V0.4 prototype
- `NeCosmos_v033.html` — V0.3.3 prototype
- `NeCosmos_引継ぎ資料.md` — 新規プロジェクト向けの引継ぎ資料
- `wrangler.jsonc` — Workerの静的アセット設定

## Cloudflare Workers deployment

Cloudflare Workers Buildsのデプロイコマンドは `npx wrangler deploy` です。`wrangler.jsonc` が `public/` を静的ファイルの配信元に指定します。Workerの名前をCloudflareダッシュボードで変更した場合は、`wrangler.jsonc` の `name` も同じ値にしてください。

カスタムドメインはWorkerの **Settings → Domains & Routes** から追加できます。例: `necosmos.mikaspark.com`。

## Run locally

`public/index.html` をSafariまたはChromeで開いてください。世界データはブラウザのローカルストレージに保存されます。

## Notes

本作は架空の生態系を使ったゲームプロトタイプです。現実の生態系を厳密に予測するものではありません。

## V0.7 草ねこ調整

- 草ねこは7日齢から繁殖し、繁殖確率を5.5%から6%へ変更。他種の年齢条件は維持。現在は全種の基礎確率に15ポイント加算し、草ねこ21%・もぐもぐ猫16.9%・きのこ猫17.5%・ふわねこ17.2%・さかなねこ17.1%・スライムねこ17.7%・とりねこ16.9%。質量は繁殖条件に含めず、子の質量は親から移せる分だけ引き継ぐ。個体数補正とマタタビ効果は別途適用。
- もぐもぐ猫は草ねこを追跡・捕食し、捕食のたびに質量を取り込む。草ねこは1回目の捕食を生き延び、2回目でエネルギー枯渇により絶命する。
- 草ねこが3匹未満の場合、温度8〜30°C・水分35〜82%・土壌栄養0.08以上のセルで自然発生を判定。日確率は草ねこ0匹で1.8%、1匹で1.2%、2匹で0.6%。発生により土壌栄養0.08を消費。
- おすすめ配置・苔原・窓辺・四季ありの16試行では、DAY 280は変更前後とも16/16、DAY 500は10/16から13/16、DAY 1000は4/16から7/16が存続。初期環境を固定した試行結果で、他バイオームでも同じ結果になるとは限りません。
