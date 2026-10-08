import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import FundFlowMap from './FundFlowMap';

describe('FundFlowMap', () => {
  it('labels the map as a static diagram, not live data', () => {
    render(<FundFlowMap />);
    expect(screen.getByText('Fund Flow')).toBeInTheDocument();
    expect(screen.getByText(/static diagram/i)).toBeInTheDocument();
  });
});
