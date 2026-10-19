import type { ReactNode } from 'react';
import styles from './styles.module.css';

type StepsProps = { children: ReactNode };

export function Step({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={styles.step}>
      <h3 className={styles.title}>{title}</h3>
      <div className={styles.content}>{children}</div>
    </section>
  );
}

export default function Steps({ children }: StepsProps) {
  return <div className={styles.steps}>{children}</div>;
}
