import { useAuth } from '../auth/AuthContext';
import styles from './Login.module.css';

export default function Login() {
  const { loginWith } = useAuth();
  return (
    <div className={styles.wrapper}>
      <div className={styles.card}>
        <h1 className={styles.title}>Arshad.AI</h1>
        <p className={styles.subtitle}>Sign in to continue</p>
        <button
          type="button"
          className={`${styles.button} ${styles.google}`}
          onClick={() => loginWith('google')}
        >
          Continue with Google
        </button>
        <button
          type="button"
          className={`${styles.button} ${styles.github}`}
          onClick={() => loginWith('github')}
        >
          Continue with GitHub
        </button>
      </div>
    </div>
  );
}
