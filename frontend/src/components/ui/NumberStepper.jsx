import { Minus, Plus } from 'lucide-react'
import { stepDecimal } from '../../utils/quantity'
export function NumberStepper({
  value,
  onChange,
  min = '0',
  max,
  step = '1',
  disabled = false,
  id,
  label = 'Количество',
}) {
  function change(direction) {
    try {
      onChange(stepDecimal(value, step, direction, min, max))
    } catch {
      /* Незавершённый ввод сохраняется до исправления. */
    }
  }
  return (
    <div className="number-stepper">
      <button
        type="button"
        aria-label={`Уменьшить: ${label}`}
        onClick={() => change(-1)}
        disabled={disabled}
      >
        <Minus size={16} />
      </button>
      <input
        id={id}
        aria-label={label}
        inputMode="decimal"
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
      />
      <button
        type="button"
        aria-label={`Увеличить: ${label}`}
        onClick={() => change(1)}
        disabled={disabled}
      >
        <Plus size={16} />
      </button>
    </div>
  )
}
