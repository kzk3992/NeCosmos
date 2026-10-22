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
