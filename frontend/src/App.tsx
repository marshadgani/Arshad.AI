import React from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import AppLayout from './components/AppLayout';
import Dashboard from './pages/Dashboard';
import PersonalFinance from './pages/PersonalFinance';
import ShopifyStore from './pages/ShopifyStore';
import StockMarket from './pages/StockMarket';
import HealthFitness from './pages/HealthFitness';
import Learning from './pages/Learning';
import HomeIoT from './pages/HomeIoT';
import Travel from './pages/Travel';

interface ErrorBoundaryProps {
  children: React.ReactNode;
}
interface ErrorBoundaryState {
  error: Error | null;
}

// Catches render-time exceptions so a single broken component doesn't blank
// the whole UI. React error boundaries require class components — there is
// no functional equivalent for componentDidCatch / getDerivedStateFromError.
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

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AppLayout>
          <Routes>
            <Route path="/"          element={<Dashboard />} />
            <Route path="/finance"   element={<PersonalFinance />} />
            <Route path="/shopify"   element={<ShopifyStore />} />
            <Route path="/stocks"    element={<StockMarket />} />
            <Route path="/health"    element={<HealthFitness />} />
            <Route path="/learning"  element={<Learning />} />
            <Route path="/home-iot"  element={<HomeIoT />} />
            <Route path="/travel"    element={<Travel />} />
          </Routes>
        </AppLayout>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
