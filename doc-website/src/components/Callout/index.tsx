import type { ReactNode } from 'react';
import styles from './styles.module.css';

type CalloutProps = {
  title?: string;
  type?: 'note' | 'tip' | 'warning' | 'important';
  children: ReactNode;
};

export default function Callout({ title, type = 'note', children }: CalloutProps) {
  return (
    <aside className={styles.callout} data-type={type} role="note">
      {title ? <p className={styles.title}>{title}</p> : null}
      <div className={styles.content}>{children}</div>
    </aside>
  );
}
