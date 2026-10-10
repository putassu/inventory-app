import { taskPhases, phaseStateLabels } from '../utils/progress'

export function StageRing({ task, detailed = false }) {
  const phases = taskPhases(task)
  const done = phases.filter((phase) => phase.state === 'done').length
  const description = phases
    .map((phase) => `${phase.name}: ${phaseStateLabels[phase.state]}`)
    .join('; ')
  const length = 100 / phases.length
  return (
    <div className={`stage-progress${detailed ? ' stage-progress-detailed' : ''}`}>
      <svg
        className="stage-ring"
        viewBox="0 0 80 80"
        role="img"
        aria-label={`Этапы обработки: ${description}`}
      >
        <title>{description}</title>
        {phases.map((phase, index) => (
          <circle
            key={phase.key}
            cx="40"
            cy="40"
            r="32"
            pathLength="100"
            fill="none"
            className={`stage-segment stage-${phase.state}`}
            style={{ '--stage-color': phase.color }}
            strokeWidth="8"
            strokeDasharray={`${length - 1.8} ${100 - length + 1.8}`}
            strokeDashoffset={-index * length}
            transform="rotate(-90 40 40)"
          />
        ))}
        <text x="40" y="44" textAnchor="middle" aria-hidden="true">
          {done}/{phases.length}
        </text>
      </svg>
      {detailed && (
        <div className="page-stack">
          <ol className="stage-legend">
            {phases.map((phase) => (
              <li key={phase.key} aria-current={phase.state === 'current' ? 'step' : undefined}>
                <span
                  className={`stage-dot stage-${phase.state}`}
                  style={{ '--stage-color': phase.color }}
                  aria-hidden="true"
                />
                <span>
                  {phase.name} <small>— {phaseStateLabels[phase.state]}</small>
                </span>
              </li>
            ))}
          </ol>
          <small className="muted">
            Секции равны: это этапы, а не доли времени. Сохранение — после вашего подтверждения.
          </small>
        </div>
      )}
    </div>
  )
}
