# NeCosmos v0.10

猫たちの生態活動、水循環、土壌移動が少しずつ景観を変える、小さな3D箱庭です。

## v0.10

現在の個体数上限は全種合計200匹です。既存セーブの超過個体は保持し、減少するまで新規増加を停止します。

- Phase 4の生態系・水文・動的地形モデルを、そのままPython / NumPyで実行します。計算はWeb Worker内のPyodideで行い、描画と分離しています。
- 8種の猫の方向別ピクセルスプライト、32個の低ポリゴン家具・自然装飾、地形と独立した水面を使用します。
- 水・土砂・栄養の収支、基盤岩と可動土壌、川と池、生息域開放、設置物の地形保護を扱います。
- 視点の回転・ズーム、観察速度、一時停止、保存・再開に対応します。旧バージョンの保存データは上書きしません。

ゲームの画面は `public/`、凍結した数値モデルの原本は `NeCosmos-Simulation/src/` と `configs/` にあります。暫定的な生態系パラメータを含む架空生態系です。

## ローカル実行

```bash
python3 -m http.server 8766 --directory public
```

`http://localhost:8766/` をブラウザで開いてください。Web Workerとファイル読み込みを使うため、HTMLファイルの直接オープンでは動作しません。初回は同梱した計算ランタイムの読み込みに時間がかかります。

## 再ビルド

```bash
python3 scripts/build-release.py
```

凍結した数値モデル・設定と公開用素材を `public/` へ配置し、`release-manifest.json` にファイルのハッシュを記録します。制作環境に元の `NeCosmos-Assets/` があれば、その完成GLBと48px猫画像から再配置します。クローン後は同梱済みの公開用素材をそのまま利用できます。

## 検証

```bash
python3 -m pip install -r NeCosmos-Simulation/requirements.txt
python3 -m unittest discover -s NeCosmos-Simulation/tests -v
```

1,200日×360条件、3,000日×8条件、感度比較75条件を実行済みです。詳細・限界は [v0.10リリースノート](docs/v0.10.md) を参照してください。検証CSV、スナップショット、ログ、試作レンダリング、Blenderバックアップはリポジトリ・配信対象から除外しています。

## 公開

Cloudflare Workers Buildsで `npx wrangler deploy` を実行します。`wrangler.jsonc` の静的アセット配信元は `public/` です。

## 依存ライブラリ

Pyodide 0.27.7 / NumPy 2.0.2、Three.js 0.160.0を同梱しています。実行時のCDNアクセスは不要です。ライセンスと配布元は [NOTICE](public/vendor/NOTICE.md) を参照してください。

## 惑星時間・行動と描画の分離（レビュー中）

×1は15秒/惑星日、じっくり観察は300秒/惑星日、最大×100。年齢表示は48惑星日で1歳相当です。旧寿命・繁殖パラメータと200匹上限は維持しています。Workerの生態系と表示座標・実時間の仕草を分離し、観察中はエンジンの移動計画へ同期、通常・高速中は瞬間移動で座標を反映します。

[実装・検証レポート](docs/planet-time-report.md) に、最新HEADの調査、75件のテスト、実ブラウザでの300秒観察、3シード×10,000日の前後比較、200/500匹の性能測定と未達項目を記載しています。専用仕草素材と大量個体時の描画性能には残る課題があり、本番リリース済みという意味ではありません。

開発用: `npm ci`、`npm test`、`npm start`。起動後に `npm run test:browser`。ブラウザ検証はPlaywrightと `/usr/bin/chromium` を使用します。生態系のPython依存は `NeCosmos-Simulation/requirements.txt` を参照してください。検証の生データ・画像はローカルの `artifacts/` に保持し、配信しません。
