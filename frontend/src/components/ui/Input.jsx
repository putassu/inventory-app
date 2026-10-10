import { forwardRef, useId } from 'react'
import { Help } from './Help'
export const Input = forwardRef(function Input(
  { label, error, helpText, info, className = '', id, as: Tag = 'input', ...props },
  ref,
) {
  const generated = useId()
  const inputId = id || generated
  const help = error || helpText
  return (
    <div className={`input-group ${className}`}>
      {label && (
        <div className="field-label">
          <label htmlFor={inputId}>{label}</label>
          {info && <Help title={label}>{info}</Help>}
        </div>
      )}
      <Tag
        ref={ref}
        id={inputId}
        className={`input ${error ? 'input-error' : ''}`}
        aria-invalid={!!error}
        aria-describedby={help ? `${inputId}-help` : undefined}
        {...props}
      />
      {help && (
        <small id={`${inputId}-help`} className={error ? 'error' : 'muted'}>
          {help}
        </small>
      )}
    </div>
  )
})
