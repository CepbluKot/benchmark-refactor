import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import { WorkspaceProvider } from './control/workspace';
import { I18nProvider } from './i18n';
import '@adqm/gpb-ui/styles.css';
import './styles.css';

const container = document.getElementById('root');
if (!container) throw new Error('Не найден контейнер #root');

createRoot(container).render(
  <StrictMode>
    <I18nProvider><WorkspaceProvider><App /></WorkspaceProvider></I18nProvider>
  </StrictMode>,
);
