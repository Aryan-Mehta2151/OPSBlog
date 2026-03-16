import { createRoot } from 'react-dom/client';
import './index.css';
import 'react-toastify/dist/ReactToastify.css';

const rootEl = document.getElementById('root');

if (!rootEl) {
  throw new Error('Root element #root was not found');
}

const root = createRoot(rootEl);

const renderStartupError = (message: string) => {
  root.render(
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: '2rem', background: '#111827', color: '#f9fafb', fontFamily: 'system-ui, sans-serif' }}>
      <div style={{ maxWidth: 900, width: '100%' }}>
        <h1 style={{ marginBottom: '0.75rem' }}>App failed to load</h1>
        <p style={{ marginBottom: '1rem', color: '#d1d5db' }}>
          A startup error occurred. Please share this message so it can be fixed quickly.
        </p>
        <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', padding: '1rem', borderRadius: 8, background: '#1f2937', border: '1px solid #374151', color: '#fca5a5' }}>
          {message}
        </pre>
      </div>
    </div>
  );
};

import('./App')
  .then(({ default: App }) => {
    root.render(<App />);
  })
  .catch((error) => {
    const msg = error instanceof Error ? `${error.name}: ${error.message}\n${error.stack || ''}` : String(error);
    renderStartupError(msg);
  });
