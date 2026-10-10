import { label } from '../../utils/labels'
import { describeValue } from '../../utils/display'

const hidden = new Set([
  'id',
  'workspace_id',
  'version',
  'created_at',
  'updated_at',
  'created_by',
  'last_confirmed_by',
  'last_confirmed_at',
  'search_revision',
  'indexed_revision',
  'attributes_schema_version',
  'expiry_generation',
  'expiry_derivation',
  'description_model_revision',
  'parent_lot_id',
  'item_id',
  'lot_id',
])

export function ChangePreview({ before, after, locations = [] }) {
  const keys = [...new Set([...Object.keys(before || {}), ...Object.keys(after || {})])].filter(
    (key) =>
      !hidden.has(key) &&
      JSON.stringify(before?.[key] ?? null) !== JSON.stringify(after?.[key] ?? null),
  )
  return (
    <div className="page-stack">
      {!before && <p className="muted">Новая запись</p>}
      {!after && <p className="muted">Удаление записи</p>}
      <dl>
        {keys.map((key) => (
          <div key={key}>
            <dt>{label(key)}</dt>
            <dd className="before-after">
              <span>{describeValue(before?.[key], key, locations)}</span>
              <span aria-label="изменится на">→</span>
              <strong>{describeValue(after?.[key], key, locations)}</strong>
            </dd>
          </div>
        ))}
      </dl>
      {!keys.length && <p className="muted">Свойства не изменились.</p>}
      <details>
        <summary>Технические данные</summary>
        <div className="before-after">
          <pre>{JSON.stringify(before ?? null, null, 2)}</pre>
          <span>→</span>
          <pre>{JSON.stringify(after ?? null, null, 2)}</pre>
        </div>
      </details>
    </div>
  )
}
