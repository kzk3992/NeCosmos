"""Generate the v0.11.0 release record from completed local audit artifacts."""
import json,statistics
from pathlib import Path
R=Path(__file__).resolve().parents[1]
def load(p):return json.loads((R/p).read_text())
base=load('artifacts/baseline.json');draft=load('artifacts/oct23/pr1-before-fixes.json');final=load('artifacts/oct23/usable-food.json')
matrix=load('artifacts/oct23/matrix.json');perf=load('artifacts/performance-browser.json');native=load('artifacts/performance-native.json');browser=load('artifacts/browser.json');realtime=load('artifacts/realtime.json')
assert len(final)==3 and len(matrix)==60
assert all(r['peak']<=200 and max(r['residual'].values())<1e-8 for r in matrix)
assert not any(r['errors'] for r in browser)
assert len({r['hash'] for r in realtime})==1
assert all(r['fps']>=30 for r in perf['out'])
lines=['# NeCosmos v0.11.0 — 時間・行動・描画の分離','',
'基準: 最新 main `fdb6566`（v0.10.1）。初回ドラフト `1835c1a` から、実機確認と追加アニメーションを除く公開前課題を修正・再検証した。公開対象は public/ のみ。生データは artifacts/ にローカル保持。','',
'## 草ねこ・ふわふわねこが多い理由','',
'- 草ねこは光・水・栄養から自給でき、繁殖開始7日、繁殖基礎値0.07。他の通常種は開始48日、基礎値0.03〜0.06。初期 all8 でも草10匹に対して他種は各3匹。増加の先行条件がある。',
'- ふわふわねこは有機物Oを最大0.008/日食べ、エネルギー係数1.25で最大0.010を得る。基本消費0.001/日より大きい。落葉・排泄・死骸からOが供給され、寒冷時の集団保温も有利。実際の採食は資源量・同セルの競合で制限され、環境消費も加わる。',
'- 分解者はO/Rの一部を栄養Nへ戻す（きのこ60%、スライム72%）。ふわふわはOの65%を体重へ取り込む。魚は水域、鳥は乾いた餌場に依存する。餌・環境条件と資源循環の違いが種別の生存・繁殖を左右する。',
'- 全体200匹上限で、個体数の多い種ほど出生候補も多い。出生枠の抽選は種別優先ではないが、少数種の置換が確約される仕組みでもない。',
'この傾向は変更前にもある。本リリースで寿命・繁殖・採食量・資源転換係数や個体数上限を変更して均等化していない。全種の永続共存は保証しない。','',
'## 修正した課題','',
'1. 休息という意図が種類本来の移動機会をさらに取り消す処理を撤去。休息表示・FSMの保持と、生態系の移動確率を分けた。',
'2. きのこ・スライムの移動 Utility を、生の O+R 総量から「既存の採食式でその日に利用可能な量」へ変更。巨大でも分解の遅いRだけに引き寄せられる局所選択を修正した。採食量や変換係数は従来どおり。大きいRの隣に利用可能なOがある再現ケースを回帰テスト化。',
'3. 安全な行動保持中はUtility再評価と近傍索引の構築を省略。空腹・危険で中断する。省略前の実装との360日分の全状態一致を別途確認。',
'4. 全8種×8方向の既存PNGを起動時に1つのアトラスへ共有し、猫を1回の InstancedMesh 描画へ集約。アルファテストと深度書込を使い、透明オブジェクトの重複描画を削減。境界体積は選択時だけ再計算し、地形・水面・足元高さの生態系データは維持。',
'5. 低FPS時は描画解像度のみを段階調整（pixel ratio 下限0.25）。低解像度時もピクセル境界を保持する。描画負荷で生態系の計算や画面外個体を省略しない。',
'6. WebAssembly確保量とブラウザ全プロセスのPSS/RSSを測定。公開manifestとWorker原本の一致をテストし、.assetsignoreでネイティブPythonキャッシュを配信から除外。faviconの404も修正。','',
'## 時間・行動・保存','',
'1惑星日ごとにageが1日増え、生物学的年齢=age/48。季節は360日。旧days_per_year=1は既に日数へ換算された旧バランスの単位として維持し、生物学的表示と分離した。設定上の寿命目標16〜22歳相当を、新たな死亡確率として適用していない。',
'実時間→time.js→直列Worker→Python日次トランザクション→時刻付きイベント/移動計画→presentation.js→Three.js。描画は生態系の乱数や確定状態を変更しない。Utility/FSMは9状態と種類別資源選択を使い、従来の生産・分解・保温・水生適性・飛行・知恵300日処理を保持する。',
'観察は次の1日を一度だけ準備し、エンジンの移動計画を0.25m/実秒で表示。0.5mの移動は2秒、採食姿勢は日末、資源・出生・死亡は日境界で確定する。通常・倍速は4/3/2/2/1Hzで瞬間移動し、実時間の仕草位相は倍率で加速しない。',
'モード切替は現在step完了→時計と仕草停止→確定snapshot同期→最新要求適用→旧未処理時間破棄→同期フレーム描画→停止解除。手動停止/イベント停止は維持する。',
'v0.10.0 / v0.10.1 のセーブを読み込める。旧実セーブfixtureのハッシュ保持、再開結果、未消費の最後の通知バッチ、準備あり/なしの同一結果を検証。未確定の端数実時間は保存しない。オフライン離脱時間の自動補填は仕様未決定のため有効化していない。知恵は現在自動イベントであり、未実装の選択イベントを独断で自動選択しない。','',
'## 検証結果','',
'JavaScript 11件、追加Python18件、既存Python51件、計80件成功。追加Pythonは配布物の一致2件を含む。全6モード360日・同じ100/200日目の生息域拡張で、全個体フィールド・資源・出生/死亡・イベント・FSM・天候乱数を比較して一致。FPS分割や描画有無でも生態系が変化しない構造とテストを維持。',
'PC1440×1000とスマートフォン相当390×844のChromiumでゲーム起動、観察、UIによる切替、×100、保存・再読込・再起動を確認。JS/HTTPエラーなし。観察中のエンジン座標と表示座標の最大誤差は0m。300実秒の観察を含む全速度の0→1日を再測定し、状態ハッシュはすべて一致。','',
'|モード|設定 秒/日|実測 秒/日（通知・計算を含む）|','|---|---:|---:|']
seconds={.05:300,1:15,5:3,10:1.5,20:.75,100:.15}
for r in realtime:lines.append(f"|{'観察' if r['speed']==.05 else '×'+str(r['speed'])}|{seconds[r['speed']]}|{r['secondsPerDay']:.4f}|")
lines+=['','## 10,000日 前後比較','',
'hills/wet/all8、通常天候、固定解放域、同じfrozen overrides、seed 21001〜21003。初回ドラフトの問題を調べ、休息取消のみの対照と利用可能量による修正版をそれぞれ3シード×10,000日実行。以下は元のv0.10.1・初回ドラフト・最終版の比較。','',
'|版|10,000日目 スライム生存シード|きのこ生存シード|全滅|最大個体数|','|---|---:|---:|---:|---:|']
for label,data in [('v0.10.1',base),('初回ドラフト',draft),('v0.11.0',final)]:
 lines.append(f"|{label}|{sum(r['checkpoints'][-1]['counts']['slime']>0 for r in data)}/3|{sum(r['checkpoints'][-1]['counts']['kinoko']>0 for r in data)}/3|{sum(sum(r['checkpoints'][-1]['counts'].values())==0 for r in data)}/3|{max(r['peak'] for r in data)}|")
lines+=['','|seed|日|v0.10.1 個体数/種数|v0.11.0 個体数/種数|','|---|---:|---:|---:|']
for a,b in zip(base,final):
 for x,y in zip(a['checkpoints'],b['checkpoints']):lines.append(f"|{a['seed']}|{x['day']}|{sum(x['counts'].values())}/{sum(v>0 for v in x['counts'].values())}|{sum(y['counts'].values())}/{sum(v>0 for v in y['counts'].values())}|")
for label,data in [('v0.10.1',base),('v0.11.0',final)]:
 ages=[v for r in data for v in r['death_age_days']];causes={k:sum(r['causes'].get(k,0) for r in data) for k in ('starvation','stress','old_age','collapse')}
 lines+=['',f"{label}: 平均死亡年齢 {statistics.mean(ages):.1f}日（{statistics.mean(ages)/48:.2f}歳相当）、中央値 {statistics.median(ages):.1f}日。死因 {json.dumps(causes,ensure_ascii=False)}。"]
lines+=['','3シードの比較から全環境の永続共存を保証することはしない。修正対象だったドラフトの共存率悪化は、この同条件比較では解消した。草・ふわふわの優勢自体は旧係数・初期条件に由来する傾向として残る。','',
'## 地形・気候の追加監査','',
'6地形（平原/丘陵/谷/窪地/既存河川/中央山）×5気候（苔原/湿潤/乾燥/寒冷/旧温暖）×別シード31001/31002、各1,000日、計60,000日。500/1,000日を記録。異常な増加・非有限値・許容誤差を超える負資源なし。全ケースで200匹上限を維持。全滅0/60。数値監査の目的であり、全種共存を合格条件にしていない。','']
lines.append('収支の最大絶対誤差: '+', '.join(f"{k}={max(r['residual'][k] for r in matrix):.3g}" for k in ('water','soil','matter'))+'（水/土m³、物質kg）。')
lines+=['','## 性能・メモリ','',
'重い長期シミュレーションと同時実行せず、Chromium/SwiftShaderで計測。下記は合成した表示負荷で、500匹へ本番上限を変更していない。CPU側の500匹・4倍面積は別のネイティブ計測。解像度調整を含む測定で、pixel ratioを併記する。','',
'|表示匹数|FPS|pixel ratio|draw calls|表示同期ms|入力→次frame 平均ms|Main JS heap MiB|WASM確保 MiB|ブラウザ全体PSS MiB|','|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
for r in perf['out']:
 lines.append(f"|{r['population']}|{r['fps']:.2f}|{r['presentation']['frameCost']['pixelRatio']:.3f}|{r['presentation']['frameCost']['drawCalls']}|{r['presentation']['reassignMs']:.3f}|{statistics.mean(r['activationToNextFrameMs']):.1f}|{r['mainThreadHeapBytes']/1048576:.2f}|{r['workerMemory']['wasmLinearMemoryBytes']/1048576:.2f}|{r['browserProcessMemory']['totalPssBytes']/1048576:.2f}|")
lines+=['',f"×100の実効速度 {perf['effective']['daysPerSecond']:.3f}日/秒（設定上限6.667）。入力測定はDOM処理から次描画までで、物理デバイスの入力遅延を含まない。PSSはゲームだけでなくChrome本体・GPU・Worker等の全プロセスを含むLinux上の比例割当メモリ。WASM値は使用中オブジェクト量ではなく確保済み線形メモリ。",'',
'|CPU初期匹数/面積|日/秒|生態系ms/日|AI判断ms/日|近傍1問ms|最寄り1問ms|追跡メモリMiB|','|---|---:|---:|---:|---:|---:|---:|']
for r in native:lines.append(f"|{r['initial_population']}/{r['area_factor']}倍|{r['days_per_second']:.2f}|{r['ecology_ms_mean']:.3f}|{r['ai_ms_mean']:.3f}|{r['neighbor_query_ms_mean']:.5f}|{(r['nearest_query_ms_mean'] or 0):.5f}|{r['memory_python_peak_bytes']/1048576:.2f}|")
lines+=['','## 今回の公開範囲外','',
'ユーザー指定により、専用の足運び・瞬き等のアニメーション素材と実機GPU/実スマートフォン確認は後続作業。現在は距離同期の上下動・変形、採食姿勢、実時間の簡易仕草を使う。ソフトウェア検証の成功を実機検証の成功とはしない。',
'最新の元HEADには遺伝子・進化計算および「ネコスモス」種の実装がなく、既存8種固定だった。既存の種/遺伝子コードを削除した変更ではない。新しい生物モデルや未確定のオフライン補填・選択イベントをこの公開へ独断で追加していない。','',
'## 変更ファイル・再実行','',
'時間・描画分離の基本ファイル一覧とアーキテクチャ詳細は [初回監査](planet-time-report.md) を参照。本修正は cats.py（分解者Utility・休息）、behavior.py（保持中の評価省略）、render.js（共通アトラス・深度・解像度・境界）、worker.js/main.js（メモリ測定・版互換）、build-release.py/.assetsignore（配布物）、UI/version、回帰テストを追加した。配布用Pythonは原本から再生成。寿命/繁殖/採食係数の設定ファイルは初回ドラフト以降変更していない。',
'`npm ci && npm test`。`npm start` 後に `npm run test:browser` / `npm run test:realtime` / `npm run test:performance`。`python scripts/audit-matrix.py`、`python scripts/measure-ecology.py --out artifacts/oct23/usable-food.json`、`python scripts/measure-performance.py`。`npm run build`、`npx wrangler deploy --dry-run`。ブラウザ性能試験はLinuxの /proc とCDPを使用する。公開後はCloudflareのbuild結果と実URLの版・manifest hash・ゲーム起動を確認する。','']
(R/'docs/v0.11.0.md').write_text('\n'.join(lines))
