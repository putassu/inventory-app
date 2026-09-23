import React from 'react'

export const Button = React.forwardRef(
  (
    {
      children,
      variant = 'primary', // primary, secondary, danger, text
      size = 'md', // sm, md, lg
      className = '',
      isLoading = false,
      disabled,
      type = 'button',
      ...props
    },
    ref,
  ) => {
    const baseClass = 'btn'
    const variantClass = variant === 'text' ? 'btn-text' : `btn-${variant}`
    const sizeClass = size === 'sm' ? 'btn-sm' : size === 'lg' ? 'btn-lg' : ''

    return (
      <button
        ref={ref}
        type={type}
        className={`${baseClass} ${variantClass} ${sizeClass} ${className}`}
        disabled={disabled || isLoading}
        {...props}
      >
        {isLoading ? (
          <span className="loader-inline">Загрузка...</span> // Placeholder for actual spinner icon
        ) : null}
        {children}
      </button>
    )
  },
)

Button.displayName = 'Button'
