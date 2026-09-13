import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AgentActivityCard } from './AgentActivityCard';

describe('AgentActivityCard', () => {
  it('shows an empty state when there is no activity and no error', () => {
    render(<AgentActivityCard agentActivity={[]} />);
    expect(screen.getByText('No open pull requests tracked yet.')).toBeInTheDocument();
  });

  it('shows an error banner instead of silently rendering nothing', () => {
    render(<AgentActivityCard agentActivity={null} error={new Error('boom')} />);
    expect(screen.getByRole('alert')).toHaveTextContent('boom');
  });

  it('labels the ticker "live" and shows a Live badge only when mode="live"', () => {
    render(<AgentActivityCard agentActivity={[]} mode="live" />);
    expect(screen.getByText('live')).toBeInTheDocument();
    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it('does not claim "live" for seed data', () => {
    render(<AgentActivityCard agentActivity={[]} mode="seed" />);
    expect(screen.queryByText('live')).not.toBeInTheDocument();
    expect(screen.getByText('Demo')).toBeInTheDocument();
  });
});
