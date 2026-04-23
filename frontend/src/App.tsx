import { BrowserRouter, Route, Routes } from 'react-router-dom';

function Dashboard() {
  return (
    <div style={{ padding: '2rem', fontFamily: 'sans-serif' }}>
      <h1>Arshad.AI</h1>
      <p>Your personal AI assistant — coming soon.</p>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
      </Routes>
    </BrowserRouter>
  );
}
