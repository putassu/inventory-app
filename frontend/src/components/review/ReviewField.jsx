import { useId } from 'react'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'
import { NumberStepper } from '../ui/NumberStepper'
import { label } from '../../utils/labels'

export const supportedControls = new Set([
  'text_input',
  'number_stepper',
  'decimal_input',
  'date_picker',
  'month_picker',
  'checkbox',
  'switch',
  'segmented_control',
  'unit_select',
  'entity_picker',
  'location_picker',
  'readonly_summary',
  'candidate_cards',
  'chips_select',
])
export function ReviewField({ field, value, onChange, references = {} }) {
  const id = useId()
  const { key, control, editable, validation } = field
  const title = field.label || key
  const disabled = editable === false
  let options = (field.options || []).map((option) => ({
    value: option.value ?? option.code,
    label: option.label || option.name || label(option.value ?? option.code),
  }))
  if (control === 'location_picker')
    options = (references.locations || []).map((location) => ({
      value: location.id,
      label: location.full_path || location.name,
    }))
  if (key === 'unit_code')
    options = (references.units || []).map((unit) => ({
      value: unit.code,
      label: unit.display_name,
    }))
  if (key === 'item_id' && control !== 'candidate_cards')
    options = (references.items || []).map((item) => ({
      value: item.id,
      label: `${item.name} · ${label(item.primary_category)} · ${item.id.slice(0, 8)}`,
    }))
  if (['lot_id', 'lot_ids'].includes(key))
    options = (references.items || []).flatMap((item) =>
      item.lots
        .filter((lot) => !lot.archived_at)
        .map((lot) => ({
          value: lot.id,
          label: `${item.name} · ${lot.label || lot.serial_number || 'Партия'} · ${lot.effective_expiry_on || 'Срок неизвестен'} · ${lot.id.slice(0, 8)}`,
        })),
    )
  if (key === 'alias_id')
    options = (references.aliases || []).map((alias) => ({ value: alias.id, label: alias.alias }))
  if (!supportedControls.has(control))
    return (
      <p className="error" role="alert">
        Неизвестное поле «{title}» ({control}). Подтверждение заблокировано.
      </p>
    )
  if (control === 'readonly_summary')
    return (
      <div>
        <strong>{title}</strong>
        <pre className="json-output">
          {typeof value === 'object' ? JSON.stringify(value, null, 2) : (value ?? 'Не указано')}
        </pre>
      </div>
    )
  if (control === 'switch' || control === 'checkbox')
    return (
      <label className="check">
        <input
          type="checkbox"
          checked={!!value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        {title}
      </label>
    )
  if (control === 'candidate_cards')
    return (
      <fieldset disabled={disabled}>
        <legend>{title}</legend>
        {options.map((option) => (
          <label className="check" key={option.value}>
            <input
              type="radio"
              name={id}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
            />
            {option.label}
          </label>
        ))}
      </fieldset>
    )
  if (['entity_picker', 'location_picker', 'unit_select', 'segmented_control'].includes(control)) {
    const multiple = key === 'lot_ids'
    return (
      <Select
        label={title}
        disabled={disabled}
        multiple={multiple}
        value={value ?? (multiple ? [] : '')}
        onChange={(event) =>
          onChange(
            multiple
              ? [...event.target.selectedOptions].map((option) => option.value)
              : event.target.value || null,
          )
        }
      >
        {!multiple && <option value="">Не указано</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </Select>
    )
  }
  if (['number_stepper', 'decimal_input'].includes(control))
    return (
      <div className="input-group">
        <label htmlFor={id}>{title}</label>
        <NumberStepper
          id={id}
          label={title}
          value={value ?? ''}
          onChange={(value) =>
            onChange(field.value_type === 'integer' && value !== '' ? Number(value) : value)
          }
          min={validation?.min || '0'}
          step={validation?.step || '1'}
          disabled={disabled}
        />
      </div>
    )
  return (
    <Input
      label={title}
      disabled={disabled}
      type={control === 'date_picker' ? 'date' : control === 'month_picker' ? 'month' : 'text'}
      value={Array.isArray(value) ? value.join(', ') : (value ?? '')}
      helpText={control === 'chips_select' ? 'Значения через запятую' : undefined}
      onChange={(event) =>
        onChange(
          control === 'chips_select'
            ? event.target.value
                .split(',')
                .map((part) => part.trim())
                .filter(Boolean)
            : event.target.value === ''
              ? null
              : field.value_type === 'integer'
                ? Number(event.target.value)
                : event.target.value,
        )
      }
    />
  )
}
