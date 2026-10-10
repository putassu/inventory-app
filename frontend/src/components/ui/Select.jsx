import { forwardRef, useId } from 'react'
import { Help } from './Help'
export const Select = forwardRef(function Select(
  { label, error, helpText, info, className = '', id, children, ...props },
  ref,
) {
  const generated = useId()
  const selectId = id || generated
  const help = error || helpText
  return (
    <div className={`input-group ${className}`}>
      {label && (
        <div className="field-label">
          <label htmlFor={selectId}>{label}</label>
          {info && <Help title={label}>{info}</Help>}
        </div>
      )}
      <select
        ref={ref}
        id={selectId}
        className={`input ${error ? 'input-error' : ''}`}
        aria-invalid={!!error}
        aria-describedby={help ? `${selectId}-help` : undefined}
        {...props}
      >
        {children}
      </select>
      {help && (
        <small id={`${selectId}-help`} className={error ? 'error' : 'muted'}>
          {help}
        </small>
      )}
    </div>
  )
})
