/**
 * Wire types for the /api/v1/whoop/* responses.
 *
 * Mirrors backend/src/schemas/whoop.py. Kept out of the page component so
 * the cards, the hook, and any future consumer share one definition rather
 * than each re-declaring the parts they touch.
 *
 * Every field is nullable because the backend forwards Whoop's own
 * optionality: a record still being computed arrives with its score fields
 * absent, which must render as "—" rather than crash a card.
 */

export interface WhoopRecovery {
  recovery_score: number | null;
  hrv_rmssd_milli: number | null;
  resting_heart_rate: number | null;
  skin_temp_celsius: number | null;
  spo2_percentage: number | null;
  cycle_id: number | null;
  created_at: string | null;
}

export interface WhoopSleep {
  id: number | null;
  start: string | null;
  end: string | null;
  total_in_bed_time_milli: number | null;
  total_awake_time_milli: number | null;
  total_light_sleep_time_milli: number | null;
  total_slow_wave_sleep_time_milli: number | null;
  total_rem_sleep_time_milli: number | null;
  sleep_performance_percentage: number | null;
  sleep_consistency_percentage: number | null;
  sleep_efficiency_percentage: number | null;
  respiratory_rate: number | null;
}

export interface WhoopStrain {
  id: number | null;
  start: string | null;
  end: string | null;
  score: number | null;
  kilojoule: number | null;
  average_heart_rate: number | null;
  max_heart_rate: number | null;
}

export interface WhoopDashboard {
  connected: boolean;
  needs_reauth: boolean;
  /** True when a transient upstream failure forced null biometric fields,
   * as distinct from a genuine no-data-recorded-today response. */
  degraded: boolean;
  recovery: WhoopRecovery | null;
  sleep: WhoopSleep | null;
  strain: WhoopStrain | null;
  user_first_name: string | null;
}

export interface WhoopHRVPoint {
  date: string;
  hrv_rmssd_milli: number | null;
}

export interface WhoopWorkout {
  id: number | null;
  sport_id: number | null;
  sport_name: string | null;
  start: string | null;
  end: string | null;
  strain: number | null;
  average_heart_rate: number | null;
  max_heart_rate: number | null;
  kilojoule: number | null;
}
