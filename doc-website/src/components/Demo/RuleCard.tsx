import clsx from 'clsx';
import type {CatalogRule} from './data';
import styles from './styles.module.css';

export type RuleStatus = 'pending' | 'checking' | 'fired' | 'clear' | 'skipped';

const STATUS_TEXT: Record<RuleStatus, string> = {
  pending: 'Waiting',
  checking: 'Checking…',
  fired: 'Fired',
  clear: 'Did not apply',
  skipped: 'Not evaluated',
};

type Props = {
  rule: CatalogRule;
  status: RuleStatus;
  reason?: string; // shown when this rule is the one that decided
};

function params(rule: CatalogRule): string {
  return Object.entries(rule.params)
    .map(([key, value]) => `${key.replace(/_/g, ' ')}: ${value}`)
    .join(', ');
}

function effect(rule: CatalogRule): string {
  if (rule.action === 'APPROVE') return `+${rule.score} risk`;
  return rule.opens_case ? `${rule.action} + case` : rule.action;
}

export default function RuleCard({rule, status, reason}: Props) {
  const fired = status === 'fired';
  return (
    <li
      className={clsx(
        styles.rule,
        styles[`rule_${status}`],
        fired && styles[`fired${rule.action}`],
      )}>
      <div className={styles.ruleHead}>
        <span className={styles.ruleRn}>{rule.rn}</span>
        <span className={styles.ruleTitle}>{rule.title}</span>
        <span className={styles.ruleStatus}>{STATUS_TEXT[status]}</span>
      </div>
      <div className={styles.ruleMeta}>
        <span>{params(rule) || 'no parameters'}</span>
        <span className={styles.ruleEffect}>{effect(rule)}</span>
      </div>
      {fired && reason && <p className={styles.ruleReason}>{reason}</p>}
    </li>
  );
}
