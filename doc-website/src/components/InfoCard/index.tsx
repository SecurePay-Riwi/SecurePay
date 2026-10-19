import type { ReactNode } from 'react';
import styles from './styles.module.css';

type InfoCardProps = {
  title: string;
  children: ReactNode;
  icon?: ReactNode;
};

export default function InfoCard({ title, children, icon }: InfoCardProps) {
  return (
    <article className={styles.card}>
      {icon ? <div className={styles.icon} aria-hidden="true">{icon}</div> : null}
      <h3 className={styles.title}>{title}</h3>
      <div className={styles.content}>{children}</div>
    </article>
  );
}
