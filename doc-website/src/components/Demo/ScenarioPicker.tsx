import clsx from 'clsx';
import type {Scenario} from './data';
import styles from './styles.module.css';

type Props = {
  scenarios: Scenario[];
  selected: string;
  onSelect: (id: string) => void;
};

export default function ScenarioPicker({scenarios, selected, onSelect}: Props) {
  return (
    <div className={styles.picker} role="group" aria-label="Scenarios">
      {scenarios.map((s) => (
        <button
          key={s.id}
          type="button"
          className={clsx(styles.pickerButton, s.id === selected && styles.pickerActive)}
          aria-pressed={s.id === selected}
          onClick={() => onSelect(s.id)}>
          <span className={styles.pickerRn}>{s.rn}</span>
          <span className={styles.pickerTitle}>{s.title}</span>
        </button>
      ))}
    </div>
  );
}
