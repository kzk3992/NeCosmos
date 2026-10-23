"""Summarize measured artifacts without treating unmeasured requirements as passed."""
from pathlib import Path
import json,statistics,subprocess
ROOT=Path(__file__).resolve().parents[1]
def read(name):return json.loads((ROOT/'artifacts'/name).read_text())
baseline=read('baseline.json');after=read('after.json');realtime=read('realtime.json');native=read('performance-native.json');browser=read('performance-browser.json');smoke=read('browser.json')
assert len(baseline)==len(after)==3
lines=['# NeCosmos 惑星時間・行動・描画分離 検証レポート','',
'対象 HEAD: `fdb6566a0fdcf7fac51f2b30b5d9ce8aed5b7c0a`（v0.10.1）。取得後と作業終盤に origin/main を再確認。同じ HEAD。公開環境へのデプロイ・main へのマージは実施していない。','',
'## 実装範囲と未達','',
'時間管理、日次トランザクション、Utility/FSM、イベント連携、観察用移動計画、通常時の瞬間移動、描画プール、空間探索、保存互換を実装した。既存の Three.js / Python Worker 構成を維持した。',
'以下は完了扱いにしない。ソフトウェア GPU で200/500匹時の30〜60FPSは未達。既存素材は8方向の静止スプライトのため、歩行は距離同期の上下動・変形、採食は傾き、仕草は呼吸・伸び・揺れの簡易表現である。独立した足のコマ送り、瞬き・あくび・毛づくろい・寝返り・尻尾の専用アニメーション素材は追加していない。実機GPU・実スマートフォンの自然さの評価は未検証。',
'現行 HEAD に遺伝子・進化システムと「ネコスモス」種は存在しない（species.json の provenance にも固定種の制限が記載済み）。既存8種を維持し、新しい種や遺伝子モデルを独断で作成していない。したがって、これらの進化結果の検証は対象データがなく未実施。','',
'## アーキテクチャ','',
'変更前: main.js の実時間 accumulator が速度を「日/秒」として日次 Worker を呼び出し、render.js がスナップショット受信ごとに座標を反映。年齢表示は1日=1歳。',
'変更後: time.js（実時間→惑星時間）→ Worker / bridge（順序付き実行・日次トランザクション）→ Python 生態系（唯一の確定状態・乱数・Utility/FSM）→ 時刻付きイベント/不変の移動計画 → presentation.js（表示座標・実時間仕草・プール）→ render.js（地形・方向・可視判定・インスタンス描画）。描画から生態系への状態反映経路はない。','',
'## 1惑星日と年齢・バランス','',
'1ステップが1惑星日。日次ステップで生存個体の age は1増える。生物学的年齢は age / 48、季節は従来の360日周期。生態系は全モードで同じ整数日ステップを実行する。カメラやFPSは計算に渡さない。',
'既存の days_per_year=1 は旧バランスの閾値単位として維持した。単に48へ変更すると、すでに日数へ換算済みの繁殖閾値・寿命曲線を再び48倍してしまう。planet_time 設定に48日換算・360日季節・16〜22歳の目標と未適用フラグを分離した。繁殖確率・死亡確率・資源収支の係数を速度で変更しない。','',
'|種|現行寿命パラメータ（日）|48日換算の歳相当|繁殖開始（日）|','|---|---:|---:|---:|']
cfg=json.loads((ROOT/'NeCosmos-Simulation/configs/species/species.json').read_text())
for sp,s in cfg['species'].items():
 if 'lifespan_days' in s:
  life=s['lifespan_days'][0];repro=s.get('repro_min_age_years',[None])[0]
  lines.append(f'|{sp}|{life}|{life/48:.2f}|{repro}|')
lines+=['','知恵ねこは通常の寿命目標・繁殖対象外。上記は寿命保証ではなく、既存 Gompertz 曲線の目標値。草ねこの繁殖開始7日は0.146歳相当であり、今回そのバランスは変更していない。','',
'## 再生速度実測','',
'Chromium / Pyodide の実ゲームを各モードで0→1日まで再生。観察モードは300実秒待って測定した。数値にはタイマー間隔・Worker計算・通知の遅れが含まれる。×100の設定値0.15秒と1日目の画面反映時間を混同しない。','',
'|モード|設定 秒/惑星日|実測 秒/惑星日|','|---|---:|---:|']
seconds={.05:300,1:15,5:3,10:1.5,20:.75,100:.15}
for r in realtime:lines.append(f"|{'観察' if r['speed']==.05 else '×'+str(r['speed'])}|{seconds[r['speed']]}|{r['secondsPerDay']:.4f}|")
lines+=['',f"全速度の1日目のハッシュ: `{realtime[0]['hash']}`。すべて一致。",'',
'## 行動AIとイベント','',
'Utility は空腹、疲労、温湿度ストレス、所在セルの食料、有機物、近傍数、ID由来の好奇心、種別の社交傾向を評価する。FSM は idle / seekFood / move / eat / rest / explore / socialize / avoidDanger / interact。最低2日の行動保持、空腹・危険時の中断、到着した目標セルを保持する。既存の光合成・採食・分解・保温・水生適性・鳥の広域移動・知恵の300日処理を残した。',
'日次順序の意図的な変更: 年齢/老衰抽選→Utility/FSM移動→ストレス・生産/採食・分解→エネルギー/排泄→繁殖→死亡→自然発生→知恵。採食前に到着できるよう、従来の採食後移動を前へ移した。この順序変更と疲労による移動抑制は生態系に影響するため、下記の前後比較を実施した。天候や知恵などのイベント順は保持。もぐもぐねこの餌は既存 HEAD と同じ生成資源 G。',
'FSM の開始は Utility 最大値または確定した生態行動、継続は2日の保持期限、完了はセル到達/日次採食/休息期限、中断は強い空腹またはストレス。行動資源の方程式を Utility で置き換えず、移動意思・目標・表示連携を段階的に導入した。社交性・警戒心は固定種特性とストレスに基づき、独立した遺伝子にはしていない。',
'move / eat / rest / birth / death / interact / environmentChange を通知。個体イベントはIDと惑星時刻、環境イベントは id=null。移動は開始時刻と終了時刻を含む。出生台帳・既存死亡台帳・最後の通知バッチを保存する。描画イベントを省略しても全日次計算は実行する。','',
'## 観察と通常描画','',
'観察では次の1日分をdeepcopy上で一度だけ計算して pending transaction とし、確定世界にはまだ反映しない。同じ計算を表示の都度繰り返さない。日境界でこの結果をそのまま採用する。描画なしでは直接stepでき、準備あり/なしの全状態一致を検証した。',
'連続座標はエンジンが発行した移動計画から ecosystem/timeline.py と presentation.js が同じ惑星時刻でサンプルする。日次占有セル i/j は資源収支の確定用、連続 x/y は日内の位置。移動速度は75m/惑星日、観察では0.25m/実秒。隣接0.5mの移動は2秒で終わり、残りは休息等に使う。採食予定個体は日末の1秒間に採食姿勢、日境界で資源・出生・死亡を確定する。足元高さは地形から補間。斜面・深水・解放域・保護された設置物の制約を使用。鳥は既存の飛行ルールを維持する。',
'通常・高速は4/3/2/2/1Hzで最新座標へ瞬間移動し、歩行を倍速再生しない。実時間の仕草位相は維持する。死亡個体は直ちに表示対象から外し、出生個体へプールを再割当。×20以上では出生・死亡累計をUI表示し、全イベント演出を強制再生しない。共通テクスチャと方向別 InstancedMesh を共有し、可視範囲外の描画のみを抑制。低FPS時は描画解像度だけを下げる。','',
'## 切り替え・保存・オフライン','',
'切り替え要求を統合→実行中step完了待ち→時計進行と仕草を停止→確定snapshot取得→生存個体・座標同期→最新要求適用→旧accumulator破棄→同期フレーム描画→停止解除。再生フラグを無条件にtrueにせず、手動停止/全滅停止を維持する。乱数・繁殖・死亡は同期のために追加実行しない。',
'既存 v0.10 JSON セーブ形式を維持。新しい behavior / birth_records は旧セーブで未存在なら初回更新時に初期化。旧版実コードで60日まで進めて作ったfixtureを読み込み、読込直後のハッシュ一致と翌日の進行を検証。過去の未記録出生履歴を創作しない。pending transaction 自体は保存せず、確定状態から同じ結果を再構築する。再生モードはUIメタデータに保存。端数の未確定実時間は保存対象外。',
'ヘッドレス進行・保存復元後の再現性・最後の未消費通知バッチの保持を検証。現在の知恵イベントは自動処理で選択待ちはない。将来の選択イベントをオフラインで自動選択しない設計が必要。離脱時間による進行・上限などの本番オフライン機能は有効化していない。','',
'## テスト結果','',
'JavaScript 11件、Python追加13件、既存Python51件が成功（合計75件）。追加には全速度の換算、FPS分割、停止、要求統合、瞬間移動、プール、仕草維持、採食姿勢、0.25m/s、準備時の無変更、ヘッドレス一致、保存復元、旧実セーブ、近傍探索の総当たり一致を含む。',
'同じシードと初期状態で全6モードを360日まで実行し、100/200日目に同じ生息域拡張を適用。個体全フィールド・出生/死亡台帳・資源・イベント履歴・FSM・天候乱数を含むシミュレーション全体のJSONを比較して一致した。',
'実ブラウザ: 1440×1000 と390×844（スマートフォン相当）で起動、観察、連続速度変更、×100進行、保存復元を確認。JS例外なし。観察座標のエンジン/描画誤差は両方0m。スクリーンショットは artifacts/*-observation.png と *-fast.png。実際の肉眼による実機評価を自動テスト成功で代替したとは扱わない。','',
'## 長期シミュレーション','',
'同一の hills / wet / all8 / normal weather / cap200 / 固定解放域 / frozen overrides、seed 21001〜21003で変更前後それぞれ10,000日。500/1,000/3,000/10,000日に記録。係数変更なし。単一環境3シードであり、全地形・気候のバランス保証ではない。','',
'|seed|日|変更前 個体数/共存種数|変更後 個体数/共存種数|','|---|---:|---:|---:|']
for a,b in zip(baseline,after):
 for x,y in zip(a['checkpoints'],b['checkpoints']):
  lines.append(f"|{a['seed']}|{x['day']}|{sum(x['counts'].values())}/{sum(v>0 for v in x['counts'].values())}|{sum(y['counts'].values())}/{sum(v>0 for v in y['counts'].values())}|")
for label,data in [('変更前',baseline),('変更後',after)]:
 ages=[v for r in data for v in r['death_age_days']];sorted_ages=sorted(ages)
 causes={k:sum(r['causes'].get(k,0) for r in data) for k in set().union(*(r['causes'] for r in data))}
 extinct=sum(sum(r['checkpoints'][-1]['counts'].values())==0 for r in data)
 lines += ['',f"{label}: 全滅 {extinct}/3、最大個体数 {max(r['peak'] for r in data)}。死亡年齢の平均 {statistics.mean(ages):.1f}日（{statistics.mean(ages)/48:.2f}歳相当）、中央値 {statistics.median(ages):.1f}日、10/90パーセンタイル {sorted_ages[int(len(ages)*.1)]}/{sorted_ages[int(len(ages)*.9)]}日。死因合計 `{json.dumps(causes,ensure_ascii=False)}`。"]
lines+=['','種別出生・死亡と最終共存率（3シード中の生存割合）:','', '|種|変更前 出生/死亡/最終共存率|変更後 出生/死亡/最終共存率|','|---|---:|---:|']
for sp in baseline[0]['checkpoints'][0]['counts']:
 vals=[]
 for data in [baseline,after]:
  birth=sum(r['births'].get(sp,0) for r in data);death=sum(r['deaths_by_species'].get(sp,0) for r in data);alive=sum(r['checkpoints'][-1]['counts'][sp]>0 for r in data)
  vals.append(f'{birth}/{death}/{alive}/3')
 lines.append(f'|{sp}|{vals[0]}|{vals[1]}|')
lines+=['','知恵ねこの出現は通常繁殖のbirths集計に含まず既存wisdomログに残る。資源推移（3シード合計kg）:','','|日|版|G|O|R|N|','|---:|---|---:|---:|---:|---:|']
for idx,day in enumerate([500,1000,3000,10000]):
 for label,data in [('前',baseline),('後',after)]:
  sums=[sum(r['checkpoints'][idx]['resources'][k] for r in data) for k in ['G','O','R','N']]
  lines.append(f"|{day}|{label}|"+'|'.join(f'{v:.3f}' for v in sums)+'|')
lines+=['','前後とも200匹上限近くへ達し、魚・鳥・もぐもぐ等の長期絶滅がある。今回のAI変更でも全種共存は実現していない。通常の上限処理を超えた増加はなかった。係数や上限の自動調整はせず、バランス改善は別課題。','',
'## 性能測定','',
'Native Python、寒冷環境で近傍探索を実行。100日計測。500匹/64×64は試験用シナリオのみで、本番上限は200のまま。Pythonメモリはtracemallocのピークでプロセス全体RSSではない。','',
'|初期個体数/面積|実効日/秒|生態系平均ms|AI平均ms|近傍1問ms|最寄り1問ms|追跡メモリMiB|','|---|---:|---:|---:|---:|---:|---:|']
for r in native:
 lines.append(f"|{r['initial_population']}/{r['area_factor']}倍|{r['days_per_second']:.2f}|{r['ecology_ms_mean']:.3f}|{r['ai_ms_mean']:.3f}|{r['neighbor_query_ms_mean']:.5f}|{(r['nearest_query_ms_mean'] or 0):.5f}|{r['memory_python_peak_bytes']/1048576:.2f}|")
lines+=['','Chromium SwiftShader（ソフトウェアGPU）。200/500匹は描画専用の合成負荷。生態系自体の500匹/面積4倍は上の独立試験で検証。','', '|表示個体数|FPS|表示データ同期ms|main JS heap MiB|入力→次frame 平均/最大ms|','|---:|---:|---:|---:|---:|']
for r in browser['out']:
 latency=r['activationToNextFrameMs'];lines.append(f"|{r['population']}|{r['fps']:.2f}|{r['presentation']['reassignMs']:.3f}|{r['mainThreadHeapBytes']/1048576:.2f}|{statistics.mean(latency):.1f}/{max(latency):.1f}|")
lines += ['',f"×100でのブラウザ実効速度 {browser['effective']['daysPerSecond']:.3f}惑星日/秒（設定上限6.667）。最後のWorker応答 `{json.dumps(browser['effective']['lastStep'])}`。",'',
'表示データ同期時間はPresentationの再割当を含む同期処理で、GPU初期化時間は含まない。GPUを持つPC/実スマートフォンでのFPS・全Worker/WASMを含む総メモリ・物理入力遅延は未測定。描画テストは1回の測定でありGPU性能保証ではない。InstancedMesh化と描画解像度調整を追加したが、ソフトウェアGPUでの大量個体30〜60FPSは未達。','',
'## 変更ファイルと再実行','',
'- NeCosmos-Simulation/src/ecosystem/{cats,behavior,spatial,timeline}.py: 移動順序、Utility/FSM、出生台帳、空間探索、日内座標。',
'- NeCosmos-Simulation/configs/species/species.json: 生物学的時間と旧バランスの区別。',
'- public/js/{time,presentation,main,worker,render}.js、public/index.html: 時計、同期、描画・UI・Worker連携。',
'- public/engine/bridge.py: 日次準備/確定、イベント、保存互換。',
'- public/engine/NeCosmos-Simulation/**、engine/manifest.json、release-manifest.json: build-release.pyで生成した本番配布ソース（公開はしていない）。',
'- tests/*、scripts/measure-{ecology,performance}.py、scripts/write-time-report.py、package*.json: 検証と再現用。',
'- artifacts/*.json / *.txt / *.png: 生データ、ログ、起動画面（ローカル保持、配信・PRには含めない）。旧セーブfixtureは tests/fixtures/v0101-save.json。','',
'`npm ci && npm test`。別ターミナルで `npm start`、`npm run test:browser`、`npm run test:realtime`（約6分）、`npm run test:performance`。ブラウザは /usr/bin/chromium を使用。`python scripts/measure-ecology.py --out artifacts/after.json`、`python scripts/measure-performance.py`。基準版は対象HEADを別ディレクトリへ展開し、measure-ecology.py の --root に渡す。','',
'## 残る課題','',
'専用の足運び/瞬き等のアニメーション素材、実機での自然さ・性能の確認、全地形/気候での長期バランス、完全なWASMメモリ計測、現行HEADに存在しない進化/ネコスモス種への対応は未完了。知恵等の将来の選択型イベントと本番オフライン進行の速度/上限は未決定。厳密な全要件達成としてリリースせず、レビュー対象の実装として提出する。','']
(ROOT/'docs/planet-time-report.md').write_text('\n'.join(lines))
