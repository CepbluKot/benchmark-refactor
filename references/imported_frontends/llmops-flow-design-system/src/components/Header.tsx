import { Sun, Moon, Search, Hexagon, ChevronDown, Globe, Languages } from 'lucide-react';
import { useCluster } from '../context/ClusterContext';
import { useLanguage } from '../context/LanguageContext';

export function Header({ darkMode, setDarkMode }: { darkMode: boolean, setDarkMode: (v: boolean) => void }) {
  const { selectedClusterId, setSelectedClusterId, clusters } = useCluster();
  const { language, setLanguage, t } = useLanguage();
  const selectedCluster = clusters.find(c => c.id === selectedClusterId);

  return (
    <header className="h-16 flex-shrink-0 border-b border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 flex items-center justify-between px-6 transition-colors duration-200 z-20">
      <div className="flex items-center gap-6 flex-1">
        {/* Cluster Selector */}
        <div className="relative group">
          <button className="flex items-center gap-2.5 px-3 py-1.5 bg-gray-50 dark:bg-slate-900 hover:bg-gray-100 dark:hover:bg-slate-800 border border-gray-200 dark:border-slate-800 rounded-lg transition-all shadow-sm">
            <div className={`p-1 rounded-md ${selectedClusterId === 'all' ? 'bg-indigo-500/10 text-indigo-500' : 'bg-emerald-500/10 text-emerald-500'}`}>
              {selectedClusterId === 'all' ? <Globe className="w-4 h-4" /> : <Hexagon className="w-4 h-4" />}
            </div>
            <div className="flex flex-col items-start leading-none">
              <span className="text-[10px] font-bold text-gray-400 uppercase tracking-tighter">{t('currentCluster')}</span>
              <span className="text-xs font-bold text-gray-900 dark:text-white">{selectedCluster?.name}</span>
            </div>
            <ChevronDown className="w-3.5 h-3.5 text-gray-400 ml-1 group-hover:translate-y-0.5 transition-transform" />
          </button>

          <div className="absolute top-full left-0 mt-2 w-64 bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all p-2 z-50 transform origin-top-left -translate-y-2 group-hover:translate-y-0 text-gray-900 dark:text-white">
            {clusters.map((cluster) => (
              <button
                key={cluster.id}
                onClick={() => setSelectedClusterId(cluster.id)}
                className={`w-full flex items-center justify-between p-3 rounded-lg transition-colors ${
                  selectedClusterId === cluster.id
                    ? 'bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400'
                    : 'hover:bg-gray-50 dark:hover:bg-slate-800 text-gray-600 dark:text-slate-400 font-medium'
                }`}
              >
                <div className="flex items-center gap-3">
                  {cluster.id === 'all' ? <Globe className="w-4 h-4" /> : <Hexagon className="w-4 h-4" />}
                  <div className="flex flex-col items-start text-left">
                    <span className="text-xs font-bold">{cluster.name}</span>
                    <span className="text-[10px] opacity-70 tracking-tight">{cluster.region} · {cluster.provider}</span>
                  </div>
                </div>
                <div className={`w-1.5 h-1.5 rounded-full ${cluster.status === 'online' ? 'bg-emerald-500' : 'bg-red-500'}`}></div>
              </button>
            ))}
          </div>
        </div>

      </div>
      <div className="flex items-center gap-3">
        {/* Language Selector Dropdown */}
        <div className="relative group">
          <button className="flex items-center gap-2.5 px-3 py-1.5 bg-gray-50 dark:bg-slate-900 hover:bg-gray-100 dark:hover:bg-slate-800 border border-gray-200 dark:border-slate-800 rounded-lg transition-all shadow-sm">
            <div className="p-1 rounded-md bg-gray-100 dark:bg-slate-800 text-gray-500">
              <Languages className="w-4 h-4" />
            </div>
            <div className="flex flex-col items-start leading-none">
              <span className="text-[10px] font-bold text-gray-400 uppercase tracking-tighter">Language</span>
              <span className="text-xs font-bold text-gray-900 dark:text-white uppercase">{language}</span>
            </div>
            <ChevronDown className="w-3.5 h-3.5 text-gray-400 ml-1 group-hover:translate-y-0.5 transition-transform" />
          </button>

          <div className="absolute top-full right-0 mt-2 w-40 bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all p-2 z-50 transform origin-top-right -translate-y-2 group-hover:translate-y-0 text-gray-900 dark:text-white">
            <button
              onClick={() => setLanguage('en')}
              className={`w-full flex items-center gap-3 p-2.5 rounded-lg transition-colors ${
                language === 'en'
                  ? 'bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400'
                  : 'hover:bg-gray-50 dark:hover:bg-slate-800 text-gray-600 dark:text-slate-400 font-medium'
              }`}
            >
              <span className="text-xs font-bold uppercase">English (EN)</span>
            </button>
            <button
              onClick={() => setLanguage('ru')}
              className={`w-full flex items-center gap-3 p-2.5 rounded-lg transition-colors ${
                language === 'ru'
                  ? 'bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400'
                  : 'hover:bg-gray-50 dark:hover:bg-slate-800 text-gray-600 dark:text-slate-400 font-medium'
              }`}
            >
              <span className="text-xs font-bold uppercase">Русский (RU)</span>
            </button>
          </div>
        </div>


        <button
          onClick={() => setDarkMode(!darkMode)}
          className="p-2 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
        >
          {darkMode ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
        </button>
      </div>
    </header>
  );
}
