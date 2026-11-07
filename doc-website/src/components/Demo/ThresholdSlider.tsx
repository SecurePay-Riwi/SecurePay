import {useState} from 'react';
import clsx from 'clsx';
import DecisionBadge from './DecisionBadge';
import type {DemoData} from './data';
import styles from './styles.module.css';

type Props = {data: DemoData};

export default function ThresholdSlider({data}: Props) {
  const variants = data.threshold_variants;
  const [ruleIndex, setRuleIndex] = useState(0);
  const variant = variants[ruleIndex];
  const defaultIndex = variant.values.findIndex((v) => v.value === variant.default);
  const [index, setIndex] = useState(defaultIndex);
  const option = variant.values[index] ?? variant.values[defaultIndex];
  const base = variant.values[defaultIndex].decisions;
  const rule = data.catalog.rules.find((r) => r.code === variant.rule);
  const label = variant.param.replace(/_/g, ' ');

  function chooseRule(i: number) {
    setRuleIndex(i);
    const next = variants[i];
    setIndex(next.values.findIndex((v) => v.value === next.default));
  }

  return (
    <section className={styles.threshold} aria-labelledby="threshold-title">
      <h2 id="threshold-title">Move a threshold</h2>
      <p>
        Change one parameter of the catalog and see which stories would be decided
        differently. In the real system the risk team does this with{' '}
        <code>POST /rules/simulations</code> over a whole day of history before
        activating a new version (HU-24).
      </p>

      <div className={styles.picker} role="group" aria-label="Rule">
        {variants.map((v, i) => {
          const r = data.catalog.rules.find((x) => x.code === v.rule);
          return (
            <button
              key={v.rule}
              type="button"
              className={clsx(styles.pickerButton, i === ruleIndex && styles.pickerActive)}
              aria-pressed={i === ruleIndex}
              onClick={() => chooseRule(i)}>
              <span className={styles.pickerRn}>{r?.rn}</span>
              <span className={styles.pickerTitle}>
                {r?.title ?? v.rule}: {v.param.replace(/_/g, ' ')}
              </span>
            </button>
          );
        })}
      </div>

      <label className={styles.slider}>
        <span>
          {rule?.title} {label}: <strong>{option.value}</strong>
          {option.value === variant.default && ' (default)'}
        </span>
        <input
          type="range"
          min={0}
          max={variant.values.length - 1}
          step={1}
          value={index}
          onChange={(e) => setIndex(Number(e.target.value))}
          aria-valuetext={`${label} ${option.value}`}
        />
        <span className={styles.sliderTicks} aria-hidden="true">
          {variant.values.map((v) => (
            <span key={v.value}>{v.value}</span>
          ))}
        </span>
      </label>

      <p className={styles.changed} aria-live="polite">
        <strong>{option.changed}</strong> of {data.scenarios.length} stories change
        their decision.
      </p>

      <ul className={styles.variantList}>
        {data.scenarios.map((s) => {
          const now = option.decisions[s.id];
          const changed = now !== base[s.id];
          return (
            <li key={s.id} className={clsx(changed && styles.variantChanged)}>
              <span>{s.title}</span>
              {changed && (
                <>
                  <DecisionBadge decision={base[s.id]} size="small" />
                  <span aria-label="becomes">→</span>
                </>
              )}
              <DecisionBadge decision={now} size="small" />
            </li>
          );
        })}
      </ul>
    </section>
  );
}
