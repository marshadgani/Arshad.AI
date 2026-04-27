import React from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from './auth/AuthContext';
import AppLayout from './components/AppLayout';
import AuthCallback from './pages/AuthCallback';
import Chat from './pages/Chat';
import Dashboard from './pages/Dashboard';
import HealthFitness from './pages/HealthFitness';
import HomeIoT from './pages/HomeIoT';
import Integrations from './pages/Integrations';
import Learning from './pages/Learning';
import Login from './pages/Login';
import PersonalFinance from './pages/PersonalFinance';
import ShopifyStore from './pages/ShopifyStore';
import StockMarket from './pages/StockMarket';
import Travel from './pages/Travel';

interface ErrorBoundaryProps {
  children: React.ReactNode;
}
interface ErrorBoundaryState {
  error: Error | null;
}

// React error boundaries require class components — there is no functional
// equivalent for componentDidCatch / getDerivedStateFromError.
class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    console.error('UI error boundary caught:', error, info);
  }

  render(): React.ReactNode {
    if (this.state.error) {
      return (
        <div style={{ padding: '2rem' }}>
          <h1>Something went wrong</h1>
          <p>{this.state.error.message}</p>
          <button type="button" onClick={() => this.setState({ error: null })}>Reload</button>
        </div>
      );
    }
    return this.props.children;
  }
}

function ProtectedRoutes() {
  const { token, user, isLoading } = useAuth();
  const location = useLocation();

  if (!token) return <Navigate to="/login" replace state={{ from: location }} />;
  // Token present but /auth/me hasn't resolved yet — render a thin shell so
  // the user doesn't see the dashboard flicker before the user record loads.
  if (isLoading && !user) {
    return <div style={{ padding: '2rem', color: '#8b949e' }}>Loading…</div>;
  }

  return (
    <AppLayout>
      <Routes>
        <Route path="/"                   element={<Dashboard />} />
        <Route path="/chat"               element={<Chat />} />
        <Route path="/chat/:sessionId"    element={<Chat />} />
        <Route path="/finance"            element={<PersonalFinance />} />
        <Route path="/shopify"            element={<ShopifyStore />} />
        <Route path="/stocks"             element={<StockMarket />} />
        <Route path="/health"             element={<HealthFitness />} />
        <Route path="/learning"           element={<Learning />} />
        <Route path="/home-iot"           element={<HomeIoT />} />
        <Route path="/travel"             element={<Travel />} />
        <Route path="/integrations"       element={<Integrations />} />
        <Route path="*"                   element={<Navigate to="/" replace />} />
      </Routes>
    </AppLayout>
  );
}

function LoginRoute() {
  const { token } = useAuth();
  if (token) return <Navigate to="/" replace />;
  return <Login />;
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login"          element={<LoginRoute />} />
            <Route path="/auth/callback"  element={<AuthCallback />} />
            <Route path="/*"              element={<ProtectedRoutes />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
