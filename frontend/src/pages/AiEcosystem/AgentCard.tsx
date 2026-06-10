import React from 'react';
import styles from './AgentCard.module.css';

export interface AgentData {
  agent_name: string;
  display_name: string;
  purpose: string;
  model: string;
  category: 'development_team' | 'other';
  pipeline_stage: number | null;
  is_active: boolean;
  status: 'ACTIVE' | 'IDLE' | 'UNKNOWN';
}

export interface AgentMetric {
  agent_name: string;
  usage_count: number;
  total_tokens: number;
  avg_tokens_per_use: number;
  success_rate: number;
  efficiency_score: number;
}

export interface AgentCardProps {
  agent: AgentData;
  metric?: AgentMetric;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function modelShortName(model: string): string {
  if (model.includes('opus')) return 'Opus';
  if (model.includes('sonnet')) return 'Sonnet';
  if (model.includes('haiku')) return 'Haiku';
  return model;
}

export default function AgentCard({ agent, metric }: AgentCardProps) {
  const usageCount = metric?.usage_count ?? 0;
  const totalTokens = metric?.total_tokens ?? 0;
  const efficiencyScore = metric?.efficiency_score ?? 0;

  return (
    <div className={`${styles.card} ${agent.status === 'ACTIVE' ? styles.cardActive : ''}`}>
      <div className={styles.header}>
        <span className={styles.name}>{agent.display_name}</span>
        <span className={`${styles.status} ${styles[`status${agent.status}`]}`}>
          {agent.status}
        </span>
      </div>

      <p className={styles.purpose}>{agent.purpose}</p>

      <div className={styles.modelRow}>
        <span className={`${styles.modelPill} ${styles[`model${modelShortName(agent.model)}`]}`}>
          {modelShortName(agent.model)}
        </span>
        {agent.pipeline_stage !== null && (
          <span className={styles.stage}>Stage {agent.pipeline_stage}</span>
        )}
      </div>

      <div className={styles.metrics}>
        <div className={styles.metric}>
          <span className={styles.metricIcon}>⚡</span>
          <span className={styles.metricLabel}>Uses</span>
          <span className={styles.metricValue}>{usageCount.toLocaleString()}</span>
        </div>
        <div className={styles.metric}>
          <span className={styles.metricIcon}>🔤</span>
          <span className={styles.metricLabel}>Tokens</span>
          <span className={styles.metricValue}>{formatTokens(totalTokens)}</span>
        </div>
      </div>

      {usageCount > 0 && (
        <div className={styles.efficiency}>
          <div className={styles.efficiencyLabel}>
            <span>Efficiency</span>
            <span>{efficiencyScore}%</span>
          </div>
          <div className={styles.efficiencyBar}>
            <div
              className={styles.efficiencyFill}
              style={{ width: `${efficiencyScore}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
