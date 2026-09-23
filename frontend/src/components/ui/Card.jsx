export function Card({ children, className = '', padding = 'var(--space-4)', ...props }) {
  return (
    <div className={`card ${className}`} style={{ padding }} {...props}>
      {children}
    </div>
  )
}
