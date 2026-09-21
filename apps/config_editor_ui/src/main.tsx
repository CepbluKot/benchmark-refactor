import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import { WorkspaceProvider } from './control/workspace';
import '@adqm/gpb-ui/styles.css';
import './styles.css';

const container = document.getElementById('root');
if (!container) throw new Error('Не найден контейнер #root');

createRoot(container).render(
  <StrictMode>
    <WorkspaceProvider>
      <App />
    </WorkspaceProvider>
  </StrictMode>,
);
