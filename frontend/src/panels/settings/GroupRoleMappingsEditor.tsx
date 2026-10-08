import type { GroupRoleMapping, Role } from '../../api/schemas'
import { ROLE_LABELS } from '../../auth/roles'

const ROLES: readonly Role[] = ['viewer', 'operator', 'admin']

/** グループ DN とロールの対応表の編集。どのグループにも一致しないユーザーはログインできない。 */
export function GroupRoleMappingsEditor({
  value,
  onChange,
}: {
  readonly value: readonly GroupRoleMapping[]
  readonly onChange: (next: GroupRoleMapping[]) => void
}) {
  const update = (index: number, patch: Partial<GroupRoleMapping>) =>
    onChange(value.map((m, i) => (i === index ? { ...m, ...patch } : m)))

  return (
    <div className="directories-panel__mappings">
      {value.length === 0 ? (
        <p className="hint">対応がありません。どのグループにも一致しないユーザーはログインできません。</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>グループの DN</th>
              <th>ロール</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {value.map((m, i) => (
              <tr key={i}>
                <td>
                  <input
                    aria-label={`${i + 1} 行目のグループの DN`}
                    placeholder="cn=vea-admins,ou=groups,dc=example,dc=com"
                    value={m.group_dn}
                    onChange={(e) => update(i, { group_dn: e.target.value })}
                  />
                </td>
                <td>
                  <select
                    aria-label={`${i + 1} 行目のロール`}
                    value={m.role}
                    onChange={(e) => update(i, { role: e.target.value as Role })}
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {ROLE_LABELS[r]}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="actions">
                  <button
                    type="button"
                    className="btn btn--gray"
                    aria-label={`${i + 1} 行目の対応を外す`}
                    onClick={() => onChange(value.filter((_, j) => j !== i))}
                  >
                    外す
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <button
        type="button"
        className="btn btn--gray"
        onClick={() => onChange([...value, { group_dn: '', role: 'viewer' }])}
      >
        対応を追加
      </button>
    </div>
  )
}
