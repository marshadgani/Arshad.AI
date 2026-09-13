import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { OntologyErrorPanel } from './OntologyErrorPanel';

describe('OntologyErrorPanel', () => {
  it('announces itself as an alert', () => {
    render(<OntologyErrorPanel message="Failed to load ontology status." />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('displays the message provided by the caller', () => {
    render(<OntologyErrorPanel message="Failed to load ontology entities." />);
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Failed to load ontology entities.',
    );
  });
});
