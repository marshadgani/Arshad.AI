import type { ToolCallRecord } from './useChatStream';
import styles from './ToolCallChip.module.css';

const STATUS_LABEL: Record<ToolCallRecord['status'], string> = {
  running: 'Calling',
  completed: 'Used',
  error: 'Failed',
};

export function ToolCallChip({ tool }: { tool: ToolCallRecord }) {
  return (
    <div className={`${styles.chip} ${styles[tool.status]}`} title={JSON.stringify(tool.input)}>
      <span className={styles.dot} />
      <span className={styles.label}>
        {STATUS_LABEL[tool.status]} <code>{tool.name}</code>
      </span>
    </div>
  );
}
