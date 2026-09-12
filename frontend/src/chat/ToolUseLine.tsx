import styles from './ToolUseLine.module.css';

export interface ToolUseLineProps {
  /** Tool name as persisted; absent on rows written before names were stored. */
  toolName?: string;
}

// A persisted tool invocation in the transcript. Distinct from ToolCallChip,
// which reports a call that is still in flight.
export function ToolUseLine({ toolName }: ToolUseLineProps) {
  return (
    <div className={styles.toolUseInline}>
      <code>{toolName ?? '(tool)'}</code>
    </div>
  );
}
