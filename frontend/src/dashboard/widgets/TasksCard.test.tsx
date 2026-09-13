/**
 * TasksCard — due string CSS-class contract test.
 *
 * Guards against backend format drift (e.g. switching to ISO-8601) silently
 * breaking the dueClass() urgency logic: if the prefix contract changes,
 * these tests fail immediately so the breakage is caught before it reaches
 * production.
 *
 * dueClass() in TasksCard.tsx:
 *   - starts with 'Yesterday'  →  styles.dueOverdue  (red)
 *   - starts with 'Today'      →  styles.dueToday    (amber)
 *   - anything else            →  no urgency class
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Task } from '../../data/mockData';
import styles from '../Dashboard.module.css';
import { TasksCard } from './TasksCard';

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 'test-id',
    title: 'Test task title',
    source: 'gmail',
    due: 'Today 09:30',
    priority: 'p1',
    ...overrides,
  };
}

describe('TasksCard — due string CSS-class contract', () => {
  it('applies dueOverdue class when due starts with "Yesterday"', () => {
    const task = makeTask({ id: 't-overdue', due: 'Yesterday 18:00' });
    render(<TasksCard tasks={[task]} />);
    const dueEl = screen.getByText('Yesterday 18:00');
    // styles.dueOverdue is the real CSS Modules class name for the overdue state
    expect(dueEl.className).toContain(styles.dueOverdue);
  });

  it('applies dueToday class when due starts with "Today"', () => {
    const task = makeTask({ id: 't-today', due: 'Today 09:30' });
    render(<TasksCard tasks={[task]} />);
    const dueEl = screen.getByText('Today 09:30');
    expect(dueEl.className).toContain(styles.dueToday);
  });

  it('applies no urgency class for a weekday date string', () => {
    const task = makeTask({ id: 't-future', due: 'Tue 09 Sep' });
    render(<TasksCard tasks={[task]} />);
    const dueEl = screen.getByText('Tue 09 Sep');
    // Neither overdue nor today class should be present for a plain date
    if (styles.dueOverdue) {
      expect(dueEl.className).not.toContain(styles.dueOverdue);
    }
    if (styles.dueToday) {
      expect(dueEl.className).not.toContain(styles.dueToday);
    }
  });

  it('does not apply dueOverdue to a "Today" due string', () => {
    const task = makeTask({ id: 't-today-2', due: 'Today 14:00' });
    render(<TasksCard tasks={[task]} />);
    const dueEl = screen.getByText('Today 14:00');
    if (styles.dueOverdue) {
      expect(dueEl.className).not.toContain(styles.dueOverdue);
    }
  });

  it('does not apply dueToday to a "Yesterday" due string', () => {
    const task = makeTask({ id: 't-yesterday-2', due: 'Yesterday 10:00' });
    render(<TasksCard tasks={[task]} />);
    const dueEl = screen.getByText('Yesterday 10:00');
    if (styles.dueToday) {
      expect(dueEl.className).not.toContain(styles.dueToday);
    }
  });
});
