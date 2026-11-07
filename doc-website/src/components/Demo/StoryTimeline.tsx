import clsx from 'clsx';
import DecisionBadge from './DecisionBadge';
import {type Scenario, stepTime} from './data';
import styles from './styles.module.css';

type Props = {scenario: Scenario};

// What happened before the decision the page animates: earlier
// transfers and security events, with their time (UTC).
export default function StoryTimeline({scenario}: Props) {
  const last = scenario.steps.length - 1;
  return (
    <ol className={styles.story} aria-label="What happened">
      {scenario.steps.map((step, i) => (
        <li
          key={step.request.id}
          className={clsx(styles.storyStep, i === last && styles.storyStepMain)}>
          <time className={styles.storyTime}>{stepTime(step)}</time>
          <span className={styles.storyLabel}>
            {step.label}
            {step.kind === 'security_event' && (
              <span className={styles.storyTag}>Security event</span>
            )}
          </span>
          {step.kind === 'transaction' && i !== last && (
            <DecisionBadge decision={step.decision.decision} size="small" />
          )}
          {i === last && <span className={styles.storyTag}>Decided below</span>}
        </li>
      ))}
    </ol>
  );
}
