import {useEffect, useState} from 'react';
import useBaseUrl from '@docusaurus/useBaseUrl';
import type {DecisionValue} from '@site/src/components/Demo/data';

// Types of static/aws-run/run.json (format_version 1), written by
// services/analytics/aws_run.py from a run on AWS. The page only reads it.

export type TraceStep = {label: string; at_ms: number | null; detail: string};

export type RunScenario = {
  id: string;
  title: string;
  rn: string;
  expected: DecisionValue;
  decision: DecisionValue;
  matches: boolean;
  rules_triggered: string[];
  risk_score: number;
  by_default: boolean;
  amount_usd: string | null;
  steps: {label: string; ms: number; decision: DecisionValue | null}[];
  trace: TraceStep[];
};

export type Run = {
  recorded_at: string;
  environment: string;
  region: string;
  engine_tasks: number;
  window: {from: string; to: string};
  scenarios: RunScenario[];
  skipped: {id: string; reason: string}[];
  metrics: {
    latency_ms: {p50: number | null; p95: number | null; p99: number | null};
    requests: number;
    fallback_decisions: number;
    queues: Record<string, number>;
    lambdas: Record<string, {invocations: number; errors: number}>;
  };
};

export type LoadStep = {
  rate: number;
  requests: number;
  p50: number | null;
  p95: number | null;
  p99: number | null;
  default_pct: number | null;
  http_5xx: number;
  cpu_avg: number | null;
  cpu_max: number | null;
};

export type LoadTest = {
  source: 'documented' | 'recorded';
  label: string;
  limit_ms: number;
  steps: LoadStep[];
  client: {requests?: number; failures?: number; p50?: number; p99?: number};
  series: {minute: string; p99: number; rate: number | null}[];
  notes: string | null;
};

export type AwsRunData = {
  format_version: number;
  generated_from: string;
  run: Run | null;
  load_test: LoadTest | null;
};

export const FORMAT_VERSION = 1;

export function useAwsRun(): {data?: AwsRunData; error?: string} {
  const url = useBaseUrl('/aws-run/run.json');
  const [state, setState] = useState<{data?: AwsRunData; error?: string}>({});
  useEffect(() => {
    let cancelled = false;
    fetch(url)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json() as Promise<AwsRunData>;
      })
      .then((data) => {
        if (cancelled) return;
        if (data.format_version !== FORMAT_VERSION) {
          throw new Error(`format_version ${data.format_version} is not ${FORMAT_VERSION}`);
        }
        setState({data});
      })
      .catch((error: Error) => {
        if (!cancelled) setState({error: error.message});
      });
    return () => {
      cancelled = true;
    };
  }, [url]);
  return state;
}

export function formatMs(ms: number | null): string {
  if (ms === null) return '—';
  if (ms >= 60000) return `${(ms / 60000).toFixed(1)} min`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms)} ms`;
}

export function formatCount(n: number | undefined): string {
  return n === undefined ? '—' : n.toLocaleString('en-US');
}

export function formatUtc(iso: string): string {
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
}
