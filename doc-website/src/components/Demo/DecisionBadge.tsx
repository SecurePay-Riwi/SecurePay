import clsx from 'clsx';
import type {DecisionValue} from './data';
import styles from './styles.module.css';

const ICON: Record<DecisionValue, string> = {APPROVE: '✓', HOLD: '❚❚', REJECT: '✕'};

type Props = {decision: DecisionValue; size?: 'small' | 'large'};

// The decision always as text too, never only as color.
export default function DecisionBadge({decision, size = 'large'}: Props) {
  return (
    <span
      className={clsx(
        styles.badge,
        styles[`tone${decision}`],
        size === 'small' && styles.badgeSmall,
      )}>
      <span aria-hidden="true" className={styles.badgeIcon}>
        {ICON[decision]}
      </span>
      {decision}
    </span>
  );
}
