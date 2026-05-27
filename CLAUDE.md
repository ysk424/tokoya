# Tokoya — Project Working Notes

This file is a handoff log for Claude Code sessions.
**Read this first** before touching anything in this repo.

---

## ⚠️ START HERE — Tokoya v0.2.6 (2026-05-28)

**This repo**: `C:\Users\azoo\git\blender-tokoya-extension\`  
**Active branch**: `vbd-features-applied` HEAD = `f6efff8`  
**Install zip**: `dist/tokoya-0.2.6.zip` — 要ビルド・インストール確認  
**N-panel tab**: "Tokoya"  
**Blender**: 5.1, Windows x64, RTX 5070 Ti (CUDA sm_120)

### このプロジェクトは何か

**床屋（Tokoya）**: 美容師向け Blender 5.1 ヘアー制作ツール。  
数学的に美しいヘアーをボタン操作だけで作る。最後の仕上げは Blender スカルプトで。

**Katsura との違い**:

| Katsura | Tokoya |
|---|---|
| アニメーション物理シミュレーション | 1フレーム静的スタイリング |
| frame_change_post ハンドラ有り | ハンドラなし |
| RAM ベイクバッファ有り | バッファなし |
| BYPASS/SIMULATING/PLAYBACK モード | モード概念なし |
| 35,792粒子リアルタイム | ボタンを押すたびN回実行 |

---

## アーキテクチャ (v0.2.5)

```
_sim_taichi.py        — Taichi XPBD ソルバー（Katsura から無改変）
_world_passthrough.py — シングルショット run_simulation(name, n_steps, scene)
_spiral_plant.py      — Vogel螺旋植毛（spiral-hair-build v5 から改造）
_mesh_ops.py          — 幾何学操作（shrink/extend/urchin_reset/extend_length）
__init__.py           — 6オペレーター + WMプロパティ登録
ui.py                 — Tokoya N-パネル
tokoya_defaults.json  — 物理パラメーターデフォルト
blender_manifest.toml — version=0.2.5（次回インストール時にバンプ必須）
```

### WM プロパティ一覧

| プロパティ | 型 | 説明 |
|---|---|---|
| `tokoya_alpha` | Float | 植毛半径 α cm（Plant Hair用） |
| `tokoya_beta`  | Float | 植毛間隔 β cm（Plant Hair用） |
| `tokoya_n`     | Float | 長さcm（Extend）または反復回数（Simulate） |
| `tokoya_ref_obj` | String | 参照オブジェクト名（Empty or Mesh） |
| `tokoya_spring_ke` など | Float/Int/Bool | 物理パラメーター（Simulate時に適用） |

---

## 6ボタンの動作仕様

### 1. Plant Hair
- **入力**: Ref Obj (EMPTY) + α + β
- **処理**: `_spiral_plant.plant_hair(empty_obj, alpha_cm, beta_cm)`
- **前提**: シーンにCurvesオブジェクトが1個、`curves.surface = CC_Base_Body`、UV設定済み、CC_Base_Tongue02ボーン有り
- **テスト実績**: α=27cm β=0.3cm、エンプティ（日本語名）で動作確認 ✅

### 2. Extend
- **入力**: N cm
- **処理**: `_mesh_ops.extend_length(obj, target_m=N/100)`
- **動作**: 全ストランドをローカル座標でスケール（根元固定、先端をN cmに）
- **用途**: ウニ → 大きなウニ（長さ統一）

### 3. Simulate（v0.2.6 保護機能追加）
- **入力**: N（反復回数）、Ref Obj（オプション: 閉じたMESH）
- **処理**: `_snapshot_sim_params()` → `_world_passthrough.run_simulation(name, N, scene, protected_indices)`
- **物理**: Taichi XPBD、CC_Base_Body 固定コリジョン（常にON）
- **modifier補正**: eval_world - orig_world のオフセット補正あり（Katsura方式）
- **ルート固定**: point[0]と point[1] がキネマティック（毛包アンカー）
- **保護機能**: Ref Obj が閉じたMESHのとき、内側の毛根を持つストランドは全点凍結（重力・コリジョン無効）
  - 内側判定: ray counting（+Z方向レイキャスト、奇数交差＝内側）
  - 凍結方式: 各ステップ後に初期world座標へリストア＋速度ゼロ化
  - Ref Obj未設定/開いたメッシュ/MESHでない場合は従来通り全毛シミュレーション

### 4. Mesh Shrink
- **入力**: Ref Obj (MESH)
- **処理**: `_mesh_ops.mesh_shrink(obj, ref_mesh_obj)`
- **アルゴリズム**:
  1. evaluated world 座標を読む（Surface Deform modifier込み）
  2. 全セグメントを走査して BVH 双方向レイキャスト
  3. **全交差のうち最小弧長**を切断点とする（筒・球体の2重交差対応）
  4. scale = hit_arc / total_arc でローカル座標をスケール
- **用途例**: Plane=高さカット、UV Sphere=丸くカット、筒=筒状カット
- **注意**: CURVE タイプ（楕円、円）は不可。UV Sphere を潰して使うこと

### 5. Mesh Extend（v0.2.6 仕様変更）
- **入力**: Ref Obj (閉じたMESH) + N cm
- **処理**: `_mesh_ops.mesh_extend_protected(obj, ref_mesh_obj, target_m)`
- **アルゴリズム**:
  1. `_is_closed_mesh` でRef Objが閉じているか確認（開いていれば0を返す）
  2. 各ストランドの `point[0]`（world座標）が閉じたプリミティブの内側か判定（ray counting）
  3. 内側のストランド → 現在の弧長に関わらず `target_m` にスケール（短ければ延長、長ければ短縮）
  4. 外側のストランド → 変更なし
- **用途**: 保護プリミティブ内側の毛を N cm に揃える（床屋の下から順次カット手順に対応）

### 6. Urchin Reset
- **入力**: なし
- **処理**: `_mesh_ops.urchin_reset(obj)`
- **動作**: 各ストランドを point[0]→point[1] 方向（毛包法線）に等間隔再配置。弧長保持。
- **用途**: シミュレーションや等比収縮後の歪みリセット → 再シミュレーション

---

## 標準作業手順（ユーザー確立済み）

```
1. Plant Hair (α=27, β=0.3, Empty配置)
   ↓
2. Extend (N=30 → 30cmウニ)
   ↓
3. Simulate (N=20 → 自然な垂れ)
   ↓
4. Mesh Shrink (球or平面で高さカット/丸カット)
   ↓
5. Mesh Shrink (前髪ラインをPlaneで)  ← 複数回OK
   ↓
6. Urchin Reset (等比収縮の歪み除去)
   ↓
7. Simulate (N=20 → 最終仕上げ)
   ↓
8. Blender スカルプト (Hair Brush で細部)
```

---

## 重要な地雷・注意事項

### Taichi 地雷（_sim_taichi.py を触る場合）
1. **`from __future__ import annotations` 禁止** → PEP 563 がカーネル型注釈を文字列化 → コンパイル失敗
2. **`@ti.kernel` の引数はスカラーのみ** → ndarray は `field.from_numpy()` / `to_numpy()` 経由
3. **カーネル内条件分岐**: `ti.select(cond, a, b)` を使う（if/else 不可）
4. **キャッシュ問題**: pyc 削除では解決しない。必ずアンインストール→再インストール

### Blender 5.1 地雷
- **ExportHelper / ImportHelper 禁止** → `context.window_manager.fileselect_add(self)` を使う
- **CURVE タイプは BVH 不可** → Plane/Sphere 等 MESH タイプのみ Shrink/Extend で使える
- **`surface_uv_coordinate` 属性**: スカルプト Add ブラシで自動生成されるが、空の Curves オブジェクトには存在しない → `_spiral_plant.py` で自動作成済み

### Mesh Shrink/Extend の座標系
- **交差判定**: 必ず `evaluated_get(deps)` の world 座標を使う（Surface Deform modifier込み）
- **書き戻し**: ローカル座標に scale-from-root で書く（スケールは無次元なので modifier 補正不要）

---

## バージョン履歴（Tokoya）

| バージョン | コミット | 内容 |
|---|---|---|
| v0.1.1 | f81b435 | Katsura からリネーム fork |
| v0.2.0 | 0966efd | 床屋アーキテクチャ完成（バッファ・ハンドラ削除、新ファイル追加） |
| v0.2.1 | f80e608 | pick_ref オペレーター（スポイトボタン） |
| v0.2.2 | cfefb86 | surface_uv_coordinate 欠損バグ修正 |
| v0.2.3 | e59a4c0 | mesh_shrink/extend 座標系バグ修正（evaluated使用、双方向レイキャスト） |
| v0.2.4 | 9d55c72 | CURVE タイプのエラーメッセージ改善 |
| v0.2.5 | f6efff8 | mesh_shrink: 閉じたメッシュの2重交差で最小弧長を選ぶ |
| **v0.2.6** | **未コミット** | **Simulate 保護機能 + Mesh Extend 仕様変更（内側N cm統一）** |

---

## 未解決 / 次回持ち越し

### 確定している次の作業
- なし（ユーザーが「今日はここまで」と終了）

### ユーザーが寝ながら考えること
- 追加ボタンのアイデア（現状6ボタン、10個まで余裕あり）

### 候補アイデア（未確定）
- **長さ情報表示** — 平均・最大・最小長さを表示するボタン
- **領域選択カット** — Empty 近傍だけ操作（部分カット）
- **ランダム変化** — 長さに±X%のランダムゆらぎ
- **旋毛位置のQuickSet** — 前回の Empty 座標を一発再現

### 旋毛テストデータ（要確認）
- α=27cm、β=0.3cm、Empty名=「エンプティ」
- **Empty の正確な世界座標は未取得**（次回 MCP 接続時に読む）
  ```python
  import bpy
  for o in bpy.data.objects:
      if o.type == "EMPTY":
          print(o.name, list(o.matrix_world.translation))
  ```

---

## MCP クイックリファレンス（Tokoya 用）

```python
# 現状確認
import bpy
curves = [o for o in bpy.data.objects if o.type == "CURVES"]
print(len(curves), "Curves objects")

# 植毛テスト（エンプティが選択されている状態で）
import bpy
wm = bpy.context.window_manager
wm.tokoya_ref_obj = "エンプティ"
wm.tokoya_alpha = 27.0
wm.tokoya_beta = 0.3
bpy.ops.tokoya.plant_hair()

# Extend テスト
wm.tokoya_n = 30.0
bpy.ops.tokoya.extend()

# Simulate テスト
wm.tokoya_n = 20
bpy.ops.tokoya.simulate()
```

---

## ブランチ地図

```
* vbd-features-applied  f6efff8  Tokoya v0.2.5 (現在)
  main (Katsura)        7e7f63a  Phase 7W-G frozen — 触らない
```

origin への push はユーザー未承認。

---

## オーナー情報

Owner: `azoo` / `ysk424` (ysk424@hotmail.com)  
Communication: 主に日本語  
Platform: Windows 11, RTX 5070 Ti, Blender 5.1
