# vCenter 編集機能 Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** 設定タブの vCenter 一覧で、登録済み vCenter を削除せずにインライン編集できるようにする。

**Architecture:** バックエンド API (`PATCH /api/vcenters/{id}`) は既に存在し、`VCenterUpdate` スキーマで全フィールドの部分更新に対応済み。フロントエンドの `VCentersPanel.tsx` に「編集」ボタンと行内フォームを追加し、`apiPatch` で更新を送信する。パスワードは API レスポンスに含まれない（`VCenterRead` にフィールドなし）ため、空欄の場合はリクエストから除外する設計とする。

**Tech Stack:** React (Vite), TypeScript, Zod, Python (FastAPI, SQLAlchemy), pytest, vitest

---

## 既存コードの状態

### バックエンド（変更不要）
- `src/vcenter_event_assistant/api/routes/vcenters.py:59-74` — `PATCH /api/vcenters/{id}` は `VCenterUpdate`（全フィールド optional）を受け取り、`exclude_unset=True` で部分更新する。
- `src/vcenter_event_assistant/api/schemas.py:21-27` — `VCenterUpdate` は `name`, `host`, `port`, `username`, `password`, `is_enabled` すべて `Optional`。
- `src/vcenter_event_assistant/api/schemas.py:30-40` — `VCenterRead` にはパスワードが含まれない。
- `tests/test_vcenters_api.py:33-35` — PATCH の基本テスト（`is_enabled` のみ）は既存。

### フロントエンド（変更対象）
- `frontend/src/panels/settings/VCentersPanel.tsx` — 追加フォーム＋一覧テーブル。編集 UI なし。
- `frontend/src/api/schemas.ts:97-109` — `vcenterSchema` / `VCenter` 型は存在。
- `frontend/src/api.ts:26-34` — `apiPatch` は存在し、VCentersPanel で既にインポート済み。

---

### Task 1: バックエンド PATCH テストの拡充（全フィールド更新）

**Files:**
- Modify: `tests/test_vcenters_api.py:33-35`

**Step 1: 複数フィールド PATCH テストを追記する**

```python
# tests/test_vcenters_api.py — 既存の test_vcenter_crud 末尾の delete の前に追加

async def test_vcenter_patch_multiple_fields(client: AsyncClient) -> None:
    """PATCH で name/host/port/username/password を一括更新できる。"""
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "before",
            "host": "old.example.local",
            "port": 443,
            "username": "admin",
            "password": "secret",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    vid = r.json()["id"]

    p = await client.patch(
        f"/api/vcenters/{vid}",
        json={
            "name": "after",
            "host": "new.example.local",
            "port": 8443,
            "username": "newadmin",
            "password": "newsecret",
        },
    )
    assert p.status_code == 200
    body = p.json()
    assert body["name"] == "after"
    assert body["host"] == "new.example.local"
    assert body["port"] == 8443
    assert body["username"] == "newadmin"
    assert "password" not in body
```

**Step 2: テストを実行して PASS を確認する**

Run: `uv run pytest tests/test_vcenters_api.py -v`
Expected: 2 tests PASS（既存 `test_vcenter_crud` + 新規 `test_vcenter_patch_multiple_fields`）

**Step 3: コミット**

```bash
git add tests/test_vcenters_api.py
git commit -m "test: add multi-field PATCH test for vcenters API"
```

---

### Task 2: VCentersPanel にインライン編集 UI を追加する

**Files:**
- Modify: `frontend/src/panels/settings/VCentersPanel.tsx`

**Step 1: 編集状態管理の型と state を追加する**

`VCentersPanel` コンポーネント内に以下の state を追加する:

```typescript
// 編集中の vCenter ID（null なら編集モードでない）
const [editingId, setEditingId] = useState<string | null>(null)

// 編集フォームの値
const [editForm, setEditForm] = useState({
  name: '',
  host: '',
  port: 443,
  username: '',
  password: '',
  is_enabled: true,
})
```

**Step 2: 編集開始・キャンセル・保存の関数を追加する**

```typescript
const startEdit = (v: VCenter) => {
  setEditingId(v.id)
  setEditForm({
    name: v.name,
    host: v.host,
    port: v.port,
    username: v.username,
    password: '',       // パスワードは API レスポンスに含まれない
    is_enabled: v.is_enabled,
  })
}

const cancelEdit = () => {
  setEditingId(null)
}

const saveEdit = async () => {
  if (!editingId) return
  onError(null)
  try {
    // パスワードが空の場合はリクエストから除外（既存値を保持）
    const body: Record<string, unknown> = {
      name: editForm.name,
      host: editForm.host,
      port: editForm.port,
      username: editForm.username,
      is_enabled: editForm.is_enabled,
    }
    if (editForm.password) {
      body.password = editForm.password
    }
    await apiPatch(`/api/vcenters/${editingId}`, body)
    setEditingId(null)
    await load()
  } catch (e) {
    onError(toErrorMessage(e))
  }
}
```

**Step 3: テーブルの各行を表示モード / 編集モードで切り替える**

一覧テーブルのtbody内の `{list.map((v) => ...)}` を以下に置き換える:

```tsx
{list.map((v) =>
  editingId === v.id ? (
    <tr key={v.id}>
      <td>
        <input
          value={editForm.name}
          onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
          aria-label="表示名"
        />
      </td>
      <td>
        <input
          value={editForm.host}
          onChange={(e) => setEditForm({ ...editForm, host: e.target.value })}
          aria-label="ホスト"
          style={{ display: 'inline', width: '60%' }}
        />
        :
        <input
          type="number"
          value={editForm.port}
          onChange={(e) => setEditForm({ ...editForm, port: Number(e.target.value) })}
          aria-label="ポート"
          style={{ display: 'inline', width: '30%' }}
        />
      </td>
      <td>
        <label className="check">
          <input
            type="checkbox"
            checked={editForm.is_enabled}
            onChange={(e) => setEditForm({ ...editForm, is_enabled: e.target.checked })}
          />
        </label>
      </td>
      <td>
        <input
          value={editForm.username}
          onChange={(e) => setEditForm({ ...editForm, username: e.target.value })}
          aria-label="ユーザー"
          placeholder="ユーザー"
        />
        <input
          type="password"
          value={editForm.password}
          onChange={(e) => setEditForm({ ...editForm, password: e.target.value })}
          aria-label="パスワード"
          placeholder="変更しない場合は空欄"
        />
      </td>
      <td className="actions">
        <button type="button" className="btn btn--filled" onClick={() => void saveEdit()}>
          保存
        </button>
        <button type="button" className="btn btn--gray" onClick={cancelEdit}>
          キャンセル
        </button>
      </td>
    </tr>
  ) : (
    <tr key={v.id}>
      <td>{v.name}</td>
      <td>
        {v.host}:{v.port}
      </td>
      <td>{v.is_enabled ? 'はい' : 'いいえ'}</td>
      <td>{v.username}</td>
      <td className="actions">
        <button type="button" className="btn btn--gray" onClick={() => void test(v.id)}>
          接続テスト
        </button>
        <button type="button" className="btn btn--gray" onClick={() => startEdit(v)}>
          編集
        </button>
        <button
          type="button"
          className="btn btn--gray"
          onClick={() => void toggleEnabled(v)}
        >
          {v.is_enabled ? '無効' : '有効'}
        </button>
        <button type="button" className="btn btn--gray" onClick={() => void remove(v.id)}>
          削除
        </button>
      </td>
    </tr>
  ),
)}
```

**Step 4: テーブルヘッダーに「ユーザー」列を追加する**

既存のヘッダー行にユーザー列を追加する:

```tsx
<thead>
  <tr>
    <th>名前</th>
    <th>ホスト</th>
    <th>有効</th>
    <th>ユーザー</th>
    <th />
  </tr>
</thead>
```

表示モードの行にも `<td>{v.username}</td>` を追加する（Step 3 のコードに含まれている）。

**Step 5: ビルド確認**

Run: `cd frontend && npx tsc --noEmit`
Expected: エラーなし

**Step 6: コミット**

```bash
git add frontend/src/panels/settings/VCentersPanel.tsx
git commit -m "feat: add inline edit UI for registered vCenters"
```

---

### Task 3: フロントエンドビルド・lint 確認

**Files:**
- (変更なし — 確認のみ)

**Step 1: TypeScript 型チェック**

Run: `cd frontend && npx tsc --noEmit`
Expected: エラーなし

**Step 2: ESLint チェック**

Run: `cd frontend && npm run lint`
Expected: エラーなし（warning は可）

**Step 3: バックエンドテスト全体**

Run: `uv run pytest tests/ -v --timeout=30`
Expected: 全テスト PASS

**Step 4: フロントエンドテスト全体**

Run: `cd frontend && npm test`
Expected: 全テスト PASS

---

### Task 4: 手動動作確認

**Step 1: 開発サーバを起動して確認**

1. 設定タブ → vCenter サブタブを開く
2. vCenter が登録済みの状態で一覧を確認
3. 「編集」ボタンをクリック → 行がインラインフォームに切り替わることを確認
4. フィールドを変更して「保存」→ 一覧に反映されることを確認
5. 「キャンセル」→ 編集が破棄されることを確認
6. パスワードを空欄のまま保存 → 既存パスワードが保持されることを確認（接続テストで検証）

---

## 設計上の注意点

### パスワードの扱い
- `VCenterRead` にパスワードは含まれない（セキュリティ上の仕様）
- 編集時のパスワード欄は常に空欄で表示する
- パスワードが空欄のまま保存した場合、`password` キーを PATCH リクエストに含めない → バックエンドの `exclude_unset=True` により既存値が保持される
- パスワードを変更したい場合のみ入力する（プレースホルダー「変更しない場合は空欄」で運用者に伝える）
