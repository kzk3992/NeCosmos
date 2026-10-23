# アニメーション素材の状態と制作リスト

既存は8種×8方向×1枚、48×48px、透過PNG。フレーム列は存在しない。今回の実時間演出は全身の拡縮/傾き/呼吸、距離連動の歩行ボブ、出生時の拡大。採食は実際の摂取計画に同期した傾き。高速時の出生/死亡は既存UIで件数集計し、死亡個体の表示は即時返却する。

これらは正式な足、目、尻尾のフレームアニメーションではない。特にまばたき・尻尾の独立運動は素材不足で未実装。look/blink/tail の演出状態は準備したが、存在しないフレームを選ばない。欠損PNGは同じ種色の簡易シルエットをアトラスに入れ、ゲームの起動を継続する。

制作仕様（提案、未生成）：8種それぞれ、下記の8方向を原則共通フレーム数で制作。front/front_left/left/back_left/back/back_right/right/front_right。48×48px RGBA透過PNG、足元基準は現行48px画像の共通rig、全フレームでキャンバス/原点固定。`assets/cats/<species>_cat/animations/<action>/<direction>_<frame:02>.png` と、fps・ループ・原点を記したJSON manifest。拡大用96px版は任意。

| action | 各方向の提案フレーム数 | fps/ループ | 現状 |
|---|---:|---|---|
| idle/look | 4 | 4/loop | 静止8方向、look状態のみ |
| walk | 8 | 距離に同期、基準8/loop | 全身ボブのみ |
| blink | 3 | 10/once | 専用画像未実装 |
| groom | 8 | 6/loop | 全身の傾きのみ |
| stretch | 6 | 6/once | 全身の拡縮のみ |
| roll | 8 | 6/once | 小さい傾きのみ |
| tail | 6 | 6/loop | 専用画像未実装 |
| sleep | 4 | 2/loop | 呼吸と縮小のみ |
| eat | 6 | 6/loop | 確定採食に同期した傾きのみ |
| birth | 6 | 8/once | 拡大のみ |
| death | 6 | 6/once | 非表示＋高速時集計のみ |

画像が揃った後は Presentation のanimation名、実時間progress、距離gaitからframeを選ぶ。惑星速度をfpsに掛けない。正式な足運び・まばたき・尻尾・死亡演出の受入確認は素材導入後の残課題。
