import { useState } from 'react';
import { Link } from 'react-router-dom';

import RenderDeployVerdict from '../../components/RenderDeployVerdict';
import { useRenderIntegrationSnapshot } from '../../hooks/useRenderIntegrationSnapshot';
import styles from './RenderMonitor.module.css';

export default function RenderMonitor() {
  const { data, isLoading, error } = useRenderIntegrationSnapshot();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (isLoading) {
    return (
      <p className={styles.note} role="status">
        Loading Render services...
      </p>
    );
  }
  if (error) {
    return (
      <p className={styles.error} role="alert">
        {error.message}
      </p>
    );
  }
  if (!data?.connected) {
    return (
      <p className={styles.note}>
        Render is not connected. <Link to="/integrations">Connect it on Integrations</Link>
      </p>
    );
  }

  const selected = data.services.find((s) => s.id === selectedId) ?? null;
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Render deploy verdict</h1>
      <label className={styles.field}>
        Service
        <select
          className={styles.select}
          value={selectedId ?? ''}
          onChange={(e) => setSelectedId(e.target.value || null)}
        >
          <option value="">Select a service</option>
          {data.services.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name ?? s.id}
            </option>
          ))}
        </select>
      </label>
      {selected && (
        <p className={styles.note}>
          Latest deploy: {selected.latest_deploy_id ?? 'none'} ({selected.latest_deploy_status ?? 'n/a'})
        </p>
      )}
      <RenderDeployVerdict
        serviceId={selected?.id ?? null}
        deployId={selected?.latest_deploy_id ?? null}
      />
    </main>
  );
}
