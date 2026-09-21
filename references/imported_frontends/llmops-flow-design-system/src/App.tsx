/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { useState, useEffect } from 'react';
import { Sidebar } from './components/Sidebar';
import { Header } from './components/Header';
import { DesignSystem } from './pages/DesignSystem';
import { Dashboard } from './pages/Dashboard';

import { ClusterProvider } from './context/ClusterContext';
import { LanguageProvider } from './context/LanguageContext';
import { AuthProvider } from './context/AuthContext';

export default function App() {
  const [darkMode, setDarkMode] = useState(true);
  const [activeTab, setActiveTab] = useState('all');
  const [page, setPage] = useState<'dashboard' | 'design-system'>(() =>
    window.location.pathname === '/design-system' ? 'design-system' : 'dashboard'
  );

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [darkMode]);

  useEffect(() => {
    const path = page === 'design-system' ? '/design-system' : '/';
    if (window.location.pathname !== path) window.history.replaceState(null, '', path);
  }, [page]);

  return (
    <LanguageProvider>
      <AuthProvider>
        <ClusterProvider>
        <div className="flex h-screen overflow-hidden bg-gray-50 dark:bg-slate-900 transition-colors duration-200">
          <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />
          <div className="flex flex-col flex-1 w-full overflow-hidden">
            <Header darkMode={darkMode} setDarkMode={setDarkMode} />
            <main className="flex-1 overflow-y-auto custom-scrollbar p-6">
              <div className="max-w-7xl mx-auto mb-6 flex items-center gap-2">
                <button onClick={() => setPage('dashboard')} className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${page === 'dashboard' ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 dark:bg-slate-800 dark:text-slate-300'}`}>Обзор</button>
                <button onClick={() => setPage('design-system')} className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${page === 'design-system' ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 dark:bg-slate-800 dark:text-slate-300'}`}>Дизайн-система</button>
              </div>
              {page === 'dashboard' ? <Dashboard /> : <DesignSystem activeSection={activeTab as any} onSectionChange={setActiveTab} />}
            </main>
          </div>
        </div>
        </ClusterProvider>
      </AuthProvider>
    </LanguageProvider>
  );
}
