import {useEffect, useState} from 'react';
import clsx from 'clsx';
import DecisionBadge from './DecisionBadge';
import RiskGauge from './RiskGauge';
import RuleCard, {type RuleStatus} from './RuleCard';
import TransactionMap from './TransactionMap';
import {
  type CatalogRule,
  type DemoData,
  type Scenario,
  formatAmount,
  protagonist,
  usePrefersReducedMotion,
} from './data';
import styles from './styles.module.css';

// RN-01's entry: never evaluated as a rule, only when the rules cannot
// decide (services/decision_engine/decision_service.default_decision).
const DEFAULT_RULE = 'default_timeout';
const SEVERITY = {APPROVE: 0, HOLD: 1, REJECT: 2};

// Milliseconds before each stage: the transaction travels to the engine,
// the cache answers, each rule, the result. About 3.5 s, then the map
// shows the answer going back and the published copies (TransactionMap).
const ENTER_MS = 900;
const CACHE_MS = 650;
const RULE_MS = 330;

type Props = {data: DemoData; scenario: Scenario};

/** The rule whose reason the engine gave: the most severe, first in order
 * (choose_decision in decision_service.py). */
function decisiveRule(rules: CatalogRule[], fired: string[]): string | undefined {
  const hits = rules.filter((r) => fired.includes(r.code));
  let best: CatalogRule | undefined;
  for (const rule of hits) {
    if (!best || SEVERITY[rule.action] > SEVERITY[best.action]) best = rule;
  }
  return best?.code;
}

export default function DecisionFlow({data, scenario}: Props) {
  const step = protagonist(scenario);
  const decision = step.decision;
  const tx = step.request;
  const rules = data.catalog.rules.filter((r) => r.enabled && r.code !== DEFAULT_RULE);
  const defaultRule = data.catalog.rules.find((r) => r.code === DEFAULT_RULE);
  const byDefault = decision.by_default;
  const finalStage = byDefault ? 3 : 2 + rules.length;
  const decisive = byDefault
    ? DEFAULT_RULE
    : decisiveRule(rules, decision.rules_triggered);

  const reduced = usePrefersReducedMotion();
  const [run, setRun] = useState(0);
  const [stage, setStage] = useState(finalStage);

  useEffect(() => {
    if (reduced) {
      setStage(finalStage);
      return undefined;
    }
    setStage(0);
    const delays = [ENTER_MS, CACHE_MS, ...Array(finalStage - 2).fill(byDefault ? CACHE_MS : RULE_MS)];
    const timers: ReturnType<typeof setTimeout>[] = [];
    let elapsed = 0;
    delays.forEach((delay, i) => {
      elapsed += delay;
      timers.push(setTimeout(() => setStage(i + 1), elapsed));
    });
    return () => timers.forEach(clearTimeout);
  }, [scenario.id, run, reduced, finalStage, byDefault]);

  const done = stage >= finalStage;
  const fired = (code: string) => decision.rules_triggered.includes(code);

  function ruleStatus(index: number): RuleStatus {
    if (byDefault) return stage >= 2 ? 'skipped' : 'pending';
    const at = 2 + index;
    if (stage < at) return 'pending';
    if (stage === at) return 'checking';
    return fired(rules[index].code) ? 'fired' : 'clear';
  }

  function defaultStatus(): RuleStatus {
    if (!byDefault) return stage >= 2 ? 'skipped' : 'pending';
    if (stage < 2) return 'pending';
    return stage === 2 ? 'checking' : 'fired';
  }

  const score = done
    ? decision.risk_score
    : rules.reduce((sum, r, i) => (ruleStatus(i) === 'fired' ? sum + r.score : sum), 0);

  const cacheText =
    stage < 1
      ? 'Waiting'
      : stage === 1
        ? 'Reading accounts, merchant and restricted list…'
        : byDefault
          ? 'Missing data: the rules cannot run'
          : 'Accounts and merchant found';

  return (
    <section className={styles.flow} aria-label="How the engine decides">
      <div className={styles.flowHeader}>
        <h2>The decision</h2>
        <button type="button" className={styles.replay} onClick={() => setRun((n) => n + 1)}>
          ↻ Replay
        </button>
      </div>

      <TransactionMap
        stage={stage}
        finalStage={finalStage}
        enterMs={ENTER_MS}
        cacheMs={CACHE_MS}
        decision={decision}
        amount={tx.amount}
        currency={tx.currency}
        reduced={reduced}
      />

      <div className={styles.txCard}>
        <span className={styles.txKind}>
          {tx.type} · {tx.channel}
        </span>
        <strong>{step.label}</strong>
        <span className={styles.txAmount}>{formatAmount(tx.amount, tx.currency)}</span>
      </div>

      <div
        className={clsx(
          styles.cache,
          stage === 1 && styles.cacheChecking,
          stage >= 2 && (byDefault ? styles.cacheMiss : styles.cacheOk),
        )}>
        <span className={styles.cacheLabel}>Cache lookup</span>
        <span>{cacheText}</span>
      </div>

      <ol className={styles.rules} aria-label="Rules of the catalog, in order">
        {rules.map((rule, i) => (
          <RuleCard
            key={rule.code}
            rule={rule}
            status={ruleStatus(i)}
            reason={rule.code === decisive ? decision.decision_reason : undefined}
          />
        ))}
        {defaultRule && (
          <RuleCard
            rule={defaultRule}
            status={defaultStatus()}
            reason={byDefault ? decision.decision_reason : undefined}
          />
        )}
      </ol>

      <div className={styles.result} aria-live="polite">
        <RiskGauge score={score} />
        {done ? (
          <div className={styles.resultBody}>
            <DecisionBadge decision={decision.decision} />
            <dl className={styles.facts}>
              <div>
                <dt>Amount</dt>
                <dd>
                  {formatAmount(tx.amount, tx.currency)}
                  {tx.currency !== 'USD' && <> = USD {decision.amount_usd}</>}
                </dd>
              </div>
              <div>
                <dt>Rate</dt>
                <dd>
                  {tx.currency === 'USD'
                    ? 'USD, no conversion'
                    : `1 USD = ${decision.usd_rate} ${tx.currency}`}
                  <br />
                  <small>rate of {decision.rate_date}</small>
                </dd>
              </div>
              <div>
                <dt>Rules version</dt>
                <dd>
                  {decision.rules_version}
                  {decision.rules_version === '0' && ' (code defaults)'}
                </dd>
              </div>
              <div>
                <dt>Rules fired</dt>
                <dd>{decision.rules_triggered.join(', ') || 'none'}</dd>
              </div>
            </dl>
          </div>
        ) : (
          <p className={styles.resultWaiting}>Deciding…</p>
        )}
      </div>
    </section>
  );
}
