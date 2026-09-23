import { forwardRef, useId } from 'react'
export const Input = forwardRef(function Input(
  { label, error, helpText, className = '', id, as: Tag = 'input', ...props },
  ref,
) {
  const generated = useId()
  const inputId = id || generated
  const help = error || helpText
  return (
    <div className={`input-group ${className}`}>
      {label && <label htmlFor={inputId}>{label}</label>}
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
