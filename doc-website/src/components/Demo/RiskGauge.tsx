import styles from './styles.module.css';

type Props = {score: number};

const RADIUS = 52;
const HALF = Math.PI * RADIUS;

// Semicircle from 0 to 100: risk_score is the sum of the scores of the
// rules that fired, at most 100.
export default function RiskGauge({score}: Props) {
  const value = Math.max(0, Math.min(100, score));
  return (
    <figure className={styles.gauge} aria-label={`Risk score ${value} of 100`}>
      <svg viewBox="0 0 128 72" aria-hidden="true">
        <path
          className={styles.gaugeTrack}
          d="M12 64a52 52 0 0 1 104 0"
          pathLength={HALF}
        />
        <path
          className={styles.gaugeValue}
          opacity={value > 0 ? 1 : 0}
          d="M12 64a52 52 0 0 1 104 0"
          pathLength={HALF}
          strokeDasharray={`${(value / 100) * HALF} ${HALF}`}
        />
      </svg>
      <figcaption>
        <strong>{value}</strong>
        <span>risk score</span>
      </figcaption>
    </figure>
  );
}
