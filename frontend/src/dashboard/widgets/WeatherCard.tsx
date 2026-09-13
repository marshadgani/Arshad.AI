import { Link } from 'react-router-dom';

import { CardHeader } from '../CardHeader';
import { type WeatherRes, type WidgetState } from '../useDashboardData';
import styles from './WeatherCard.module.css';

export interface WeatherCardProps {
  weather: WidgetState<WeatherRes>;
}

// Shown for an unmapped or absent condition — a generic sky beats an
// empty slot where the icon should be.
const DEFAULT_GLYPH = '🌤️';

// OpenWeatherMap's `weather[0].main` vocabulary is a small fixed set —
// mapped to a glyph so the card reads at a glance without an icon font
// dependency.
const CONDITION_GLYPH: Record<string, string> = {
  Clear: '☀️',
  Clouds: '☁️',
  Rain: '🌧️',
  Drizzle: '🌦️',
  Thunderstorm: '⛈️',
  Snow: '❄️',
  Mist: '🌫️',
  Fog: '🌫️',
  Haze: '🌫️',
  Smoke: '🌫️',
  Dust: '🌫️',
  Sand: '🌫️',
  Tornado: '🌪️',
  Squall: '💨',
};

function conditionGlyph(condition: string | null): string {
  if (!condition) return DEFAULT_GLYPH;
  return CONDITION_GLYPH[condition] ?? DEFAULT_GLYPH;
}

// The card body is one state at a time — loading, request error, expired
// key, upstream degraded, never-connected, live conditions — so it reads
// as an ordered chain of early returns rather than six mutually exclusive
// guards repeated inline in the JSX.
function weatherBody({ data, isLoading, error, refetch }: WidgetState<WeatherRes>) {
  if (isLoading) {
    return (
      <div className={styles.skeletonHero} aria-busy="true" aria-live="polite">
        <span className={styles.srOnly}>Loading weather…</span>
        <div className={styles.skeletonIcon} aria-hidden="true" />
        <div className={styles.skeletonLines} aria-hidden="true">
          <div className={styles.skeletonLine} />
          <div className={styles.skeletonLine} />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={`${styles.stateBlock} ${styles.stateError}`} role="alert">
        <span className={styles.stateGlyph} aria-hidden="true">⚠</span>
        <div>
          <p>Couldn&apos;t load the weather — {error.message}</p>
          {refetch && (
            <button type="button" className={styles.retryBtn} onClick={refetch}>
              Retry
            </button>
          )}
        </div>
      </div>
    );
  }

  if (!data) return null;

  // Keyed on `connected`, never on a null payload field: the backend can
  // legitimately return connected=true with every payload field null (an
  // upstream body missing `main.temp`, or a cache entry written by an
  // older parser shape — see conditions.from_upstream/from_cache). Keying
  // the Connect CTA on `temp == null` told an already-connected user to
  // connect an integration they had already set up.
  if (!data.connected) {
    return (
      <div className={`${styles.stateBlock} ${styles.stateEmpty}`}>
        <span>Connect OpenWeatherMap to see live conditions for your location.</span>
        <Link to="/integrations" className={styles.connectLink}>
          Connect
        </Link>
      </div>
    );
  }

  if (data.needs_reauth) {
    return (
      <div className={`${styles.stateBlock} ${styles.stateEmpty}`}>
        <span>Your OpenWeatherMap key has expired.</span>
        <Link to="/integrations" className={styles.connectLink}>
          Reconnect
        </Link>
      </div>
    );
  }

  // A connected integration with no temperature to show is the same thing
  // to the reader as an explicitly degraded one — there is nothing to
  // render and retrying is the only useful action.
  if (data.degraded || data.temp == null) {
    return (
      <div className={`${styles.stateBlock} ${styles.stateEmpty}`}>
        <span>Weather is temporarily unavailable.</span>
        {refetch && (
          <button type="button" className={styles.retryBtn} onClick={refetch}>
            Retry
          </button>
        )}
      </div>
    );
  }

  return (
    <div className={styles.hero}>
      <div className={styles.iconWrap} aria-hidden="true">
        {conditionGlyph(data.condition)}
      </div>
      <div className={styles.tempBlock}>
        <div className={styles.temp}>{data.temp}</div>
        <div className={styles.condition}>{data.condition ?? 'Current conditions'}</div>
        {data.city && <div className={styles.city}>{data.city}</div>}
      </div>
    </div>
  );
}

export function WeatherCard({ weather }: WeatherCardProps) {
  // The header dot means "this card is showing live data" (CardHeaderProps),
  // which a connected-but-degraded or expired-key tile is not.
  const showingLiveConditions = weather.data?.temp != null;
  return (
    <section className={styles.card}>
      <CardHeader
        title="Weather"
        meta={weather.data?.city ?? ''}
        live={showingLiveConditions}
      />
      {weatherBody(weather)}
    </section>
  );
}
