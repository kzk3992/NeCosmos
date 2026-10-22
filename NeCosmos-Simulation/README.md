# NeCosmos Simulation — v0.10 numerical core

凍結したPhase 4の数値モデルです。Python原本を `scripts/build-release.py` で `public/engine/` へ配置し、ブラウザではPyodide Web Worker上で実行します。

- `src/ecosystem/`: 8種の個体、生産・採食・分解・移動・繁殖・死亡
- `src/hydrology/`: 保存的な水移動、積雪・浸透・中間流、侵食・堆積、川と池
- `src/terrain/`: 32×32セルの基盤岩・土壌、境界、開放面積、設置物保護
- `src/coupling/`: 日次更新、物質収支、種間・地形との連成、カウンタ方式乱数
- `configs/`: 種・気候・初期地形・凍結パラメータ
- `tests/`: 数値保存・保護・補間・更新順序・決定論の単体テスト

単位はm、m³、kg、1ゲーム日=1年齢年です。生態系セルと表示メッシュを分離しています。

Phase 4評価時点のソースハッシュ `f33fe9a232a05650`、基礎設定ハッシュ `1965af03719d58ed`。
ブラウザ接続部は `public/engine/bridge.py` で、現在は出生経路に任意の個体数上限を追加しており、本番では200匹を指定します。上限未指定の研究モデルは従来どおりです。wasm32向け添字の型変換、家具設置、ゲーム内の面積開放、保存などは接続部で扱います。

同じランタイム・設定・シードでは再現します。ネイティブ環境とWebAssembly間の浮動小数点のビット単位一致は保証しません。

```bash
python3 -m pip install -r NeCosmos-Simulation/requirements.txt
python3 -m unittest discover -s NeCosmos-Simulation/tests -v
```

制作時のバッチ結果・グラフ・キャリブレーションの副産物はローカルに保持し、配信とGitの対象から除外しています。成果の要約と残課題は [リリースノート](../docs/v0.10.md) を参照してください。

## Phase 4 再評価：明示的な上限200匹

`configs/scenarios/cap200_review.json` が今回の事前固定計画です。研究用 `Simulation` はシナリオの `max_population`（省略時は無制限）を受け付けます。200匹に達すると新しい出生・自然発生・知恵ねこの出現を止めます。既存個体を削除する処理はありません。初期個体数が設定上限を超える研究シナリオはエラーとして拒否します。

```bash
python3 -m unittest discover -s NeCosmos-Simulation/tests -v
python3 NeCosmos-Simulation/tools/cap200_review.py
# 事後補足（丘陵の自然河川を3000日まで観察）
python3 NeCosmos-Simulation/tools/cap200_review.py long_river
python3 NeCosmos-Simulation/tools/cap200_audit.py stage2 stage3 validation final controls long sens long_river
python3 NeCosmos-Simulation/tools/cap200_analyze.py
python3 NeCosmos-Simulation/tools/cap200_figures.py
python3 NeCosmos-Simulation/tools/cap200_replay.py final valley_wet_all8_190101
python3 NeCosmos-Simulation/tools/cap200_finalize.py
```

出力は `results/cap200_review/`、`figures/cap200_review/`、`reports/cap200_review/` に分離します。以前の結果を上書きしません。感度分析には、同じ初期条件・シードで上限を外す対照も含めます。パラメータは既存の学習用シードで決めた `frozen.json` を再使用し、今回の検証・最終シードに合わせた再調整をしません。

今回のコード・結果は研究領域内の成果物です。この再評価の時点では本番へ反映していません。天候追加の検証後、v0.10.1で公開用エンジンへ組み込んでいます。


## 天候生成の追加評価

`src/weather/generator.py` と `configs/scenarios/weather.json` に、360日季節・前日の天候・多雨／干ばつ期に依存する決定論的な確率モデルを実装しています。シナリオの `weather_mode` は `fixed / normal / wet / dry / extreme`。省略時は従来の天候と更新方式を保ちます。天候追加の検証後、v0.10.1で公開用エンジンへ組み込みました。

新方式は天候→水循環→保存した水流による侵食・堆積→猫の活動・地表作用→資源循環→確定の順です。前日までの地形・被覆で水流を計算し、当日の猫は水循環・地形更新後の環境を読みます。新しく生産した食料・栄養・有機物は資源循環段階まで利用できません。流水・直接的な猫の攪乱・腐植化の高度差を個別に記録し、間接作用は同じ天候の猫作用ON/OFF対比較で評価します。

```bash
python3 -m unittest discover -s NeCosmos-Simulation/tests -v
python3 NeCosmos-Simulation/tools/weather_review.py
python3 NeCosmos-Simulation/tools/weather_statistics.py
python3 NeCosmos-Simulation/tools/weather_audit.py comparison no_cats cat_effects_off long
python3 NeCosmos-Simulation/tools/weather_analyze.py
python3 NeCosmos-Simulation/tools/weather_figures.py
python3 NeCosmos-Simulation/tools/weather_replay.py comparison hills_wet_extreme_220101
python3 NeCosmos-Simulation/tools/weather_pair_audit.py
# 過去のローカルcap200結果を使う後方互換検査
python3 NeCosmos-Simulation/tools/weather_legacy_compat.py
python3 NeCosmos-Simulation/tools/weather_finalize.py
```

新しい結果は `results/weather_review/`、図は `figures/weather_review/`、報告は `reports/weather_review/` に保存します。試験計画は `configs/scenarios/weather_review.json` に固定し、既存の結果は上書きしません。
