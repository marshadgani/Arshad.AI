import { useEffect, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';

import { getToken } from '../auth/tokenStorage';
import type { NavItem } from '../data/mockData';
import { useFetch } from '../hooks/useFetch';
import styles from './Sidebar.module.css';

export interface SidebarProps {}

interface ChatSessionRow {
  id: string;
  title: string;
  updated_at: string | null;
}

export default function Sidebar(_: SidebarProps) {
  const { data: navItems } = useFetch<NavItem[]>('/api/v1/nav');
  const [sessions, setSessions] = useState<ChatSessionRow[]>([]);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const navigate = useNavigate();

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    fetch('/api/v1/chat/sessions', {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((body) => setSessions((body.data ?? []) as ChatSessionRow[]))
      .catch(() => undefined);
  }, [refreshNonce]);

  const startNewChat = async () => {
    const token = getToken();
    if (!token) return;
    const res = await fetch('/api/v1/chat/sessions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({}),
    });
    if (!res.ok) return;
    const body = (await res.json()) as { data: ChatSessionRow };
    setRefreshNonce((n) => n + 1);
    navigate(`/chat/${body.data.id}`);
  };

  return (
    <aside className={styles.sidebar}>
      <div className={styles.brand}>
        <span className={styles.brandMark}>A</span>
        <div className={styles.brandText}>
          <strong>Arshad.AI</strong>
          <span>Personal OS</span>
        </div>
      </div>

      <div className={styles.section}>
        <div className={styles.label}>Workspace</div>
        {(navItems ?? []).map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.to === '/'}
            className={({ isActive }) =>
              isActive ? `${styles.item} ${styles.itemActive}` : styles.item
            }
          >
            <span className={styles.icon}>{n.icon}</span>
            <span>{n.label}</span>
          </NavLink>
        ))}
      </div>

      <div className={styles.section}>
        <div className={styles.labelRow}>
          <div className={styles.label}>Chats</div>
          <button type="button" className={styles.newChat} onClick={startNewChat}>
            + New
          </button>
        </div>
        {sessions.length === 0 && (
          <div className={styles.emptyHint}>No chats yet.</div>
        )}
        {sessions.slice(0, 12).map((s) => (
          <NavLink
            key={s.id}
            to={`/chat/${s.id}`}
            className={({ isActive }) =>
              isActive ? `${styles.item} ${styles.itemActive}` : styles.item
            }
            title={s.title}
          >
            <span className={styles.icon}>💬</span>
            <span className={styles.sessionTitle}>{s.title}</span>
          </NavLink>
        ))}
      </div>

      <div className={styles.section}>
        <div className={styles.label}>Account</div>
        <a className={styles.item} href="#"><span className={styles.icon}>⚙</span>Settings</a>
        <a className={styles.item} href="#"><span className={styles.icon}>⌗</span>Integrations</a>
        <a className={styles.item} href="#"><span className={styles.icon}>📜</span>Activity log</a>
      </div>

      <div className={styles.footer}>
        <div className={styles.avatar}>A</div>
        <div className={styles.user}>
          <span className={styles.userName}>Arshad</span>
          <span className={styles.userStatus}>online</span>
        </div>
      </div>
    </aside>
  );
}
