# NeCosmos

猫たちがつくる、小さな生態圏を観察するブラウザ向けシミュレーションプロトタイプです。

## Files

- `public/index.html` — Cloudflare Workerで配信するV0.5
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
