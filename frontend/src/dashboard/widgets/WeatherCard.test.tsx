import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { type WeatherRes, type WidgetState } from '../useDashboardData';
import { WeatherCard } from './WeatherCard';

function renderCard(weather: WidgetState<WeatherRes>) {
  return render(
    <MemoryRouter>
      <WeatherCard weather={weather} />
    </MemoryRouter>,
  );
}

const connectedLive: WeatherRes = {
  temp: '18 °C',
  condition: 'Clouds',
  city: 'London',
  connected: true,
  needs_reauth: false,
  degraded: false,
};

describe('WeatherCard — four-state contract', () => {
  it('shows an accessible loading announcement while loading', () => {
    renderCard({ data: null, isLoading: true, error: null });
    expect(screen.getByText('Loading weather…')).toBeInTheDocument();
    expect(screen.queryByText('18 °C')).not.toBeInTheDocument();
  });

  it('renders an alert with a retry action when the request fails', () => {
    const refetch = vi.fn();
    renderCard({ data: null, isLoading: false, error: new Error('network down'), refetch });

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('network down');
    screen.getByRole('button', { name: 'Retry' }).click();
    expect(refetch).toHaveBeenCalledOnce();
  });

  it('shows a Connect CTA when OpenWeatherMap has never been connected', () => {
    renderCard({
      data: { temp: null, condition: null, city: null, connected: false, needs_reauth: false, degraded: false },
      isLoading: false,
      error: null,
    });

    expect(screen.getByText(/Connect OpenWeatherMap/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Connect' })).toHaveAttribute('href', '/integrations');
  });

  it('shows a Reconnect CTA when the stored key needs re-auth', () => {
    renderCard({
      data: { temp: null, condition: null, city: null, connected: true, needs_reauth: true, degraded: false },
      isLoading: false,
      error: null,
    });

    expect(screen.getByText(/key has expired/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Reconnect' })).toHaveAttribute('href', '/integrations');
  });

  it('shows a degraded message with retry when the upstream call failed', () => {
    const refetch = vi.fn();
    renderCard({
      data: { temp: null, condition: null, city: null, connected: true, needs_reauth: false, degraded: true },
      isLoading: false,
      error: null,
      refetch,
    });

    expect(screen.getByText(/temporarily unavailable/)).toBeInTheDocument();
    screen.getByRole('button', { name: 'Retry' }).click();
    expect(refetch).toHaveBeenCalledOnce();
  });

  it('never shows the Connect CTA to a connected user whose payload came back empty', () => {
    // connected=true with an all-null payload and no flags is a legal
    // backend state (upstream body missing `main.temp`). It must read as
    // "temporarily unavailable", not "connect the integration you already
    // connected".
    renderCard({
      data: { temp: null, condition: null, city: null, connected: true, needs_reauth: false, degraded: false },
      isLoading: false,
      error: null,
    });

    expect(screen.queryByText(/Connect OpenWeatherMap/)).not.toBeInTheDocument();
    expect(screen.getByText(/temporarily unavailable/)).toBeInTheDocument();
  });

  it('renders live current conditions when connected and healthy', () => {
    renderCard({ data: connectedLive, isLoading: false, error: null });

    expect(screen.getByText('18 °C')).toBeInTheDocument();
    expect(screen.getByText('Clouds')).toBeInTheDocument();
    expect(screen.getAllByText('London').length).toBeGreaterThan(0);
  });
});
