import {
  Palette,
  Sparkles,
  Type,
  Sliders,
  Terminal,
  Server,
  LogIn,
  LogOut,
  Moon,
  Sun
} from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

import { useLanguage } from '../context/LanguageContext';
import { useAuth } from '../context/AuthContext';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: any) => void;
}

export function Sidebar({ activeTab, setActiveTab }: SidebarProps) {
  const { language, t } = useLanguage();
  const { user, loginWithGoogle, logout } = useAuth();
  const isRu = language === 'ru';

  const mainNav = [
    { id: 'all', label: isRu ? 'Спецификация' : 'Design Spec', icon: Palette },
    { id: 'colors', label: isRu ? 'Палитра цветов' : 'Chromatics Palette', icon: Sparkles },
    { id: 'typography', label: isRu ? 'Типографика' : 'Type & Fonts', icon: Type },
    { id: 'components', label: isRu ? 'Элементы управления' : 'UI Components', icon: Sliders },
    { id: 'sandbox', label: isRu ? 'Песочница' : 'Interactive Sandbox', icon: Terminal },
  ];

  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map(n => n[0])
      .join('')
      .toUpperCase()
      .slice(0, 2);
  };

  return (
    <aside className="w-64 flex-shrink-0 border-r border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 flex flex-col transition-colors duration-200">
      <div className="h-16 flex items-center px-6 border-b border-gray-200 dark:border-slate-800">
        <div className="flex items-center gap-2 text-indigo-600 dark:text-indigo-400 font-extrabold text-lg tracking-tight">
          <Server className="w-5 h-5 text-indigo-500" />
          <span>OPS Design System</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto py-4 px-3 custom-scrollbar flex flex-col">
        <div className="mb-2 px-3">
          <span className="text-[10px] font-bold text-gray-400 dark:text-slate-500 uppercase tracking-[0.2em]">
            {isRu ? 'Навигация Спек' : 'Visual Spec Navigation'}
          </span>
        </div>

        <nav className="space-y-1">
          {mainNav.map((item) => (
            <NavItem
              key={item.id}
              item={item}
              activeTab={activeTab}
              setActiveTab={setActiveTab}
            />
          ))}
        </nav>
      </div>

      <div className="p-4 border-t border-gray-200 dark:border-slate-800 space-y-2">
        {user ? (
          <div className="flex flex-col gap-2 p-3 rounded-lg bg-gray-100 dark:bg-slate-800/50">
            <div className="flex items-center gap-3">
              {user.photoURL ? (
                <img
                  src={user.photoURL}
                  alt={user.displayName || 'User profile'}
                  className="w-8 h-8 rounded-full border border-indigo-200 dark:border-indigo-500/20"
                  referrerPolicy="no-referrer"
                />
              ) : (
                <div className="w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center text-white font-semibold text-xs">
                  {getInitials(user.displayName || user.email || 'GU')}
                </div>
              )}
              <div className="flex flex-col text-left overflow-hidden flex-1">
                <span className="text-sm font-medium text-gray-900 dark:text-gray-200 truncate leading-none">
                  {user.displayName || 'Google User'}
                </span>
                <span className="text-[10px] text-emerald-500 font-bold tracking-tight uppercase mt-1 leading-none">
                  Cloud Connected
                </span>
              </div>
            </div>
            <button
              onClick={() => logout()}
              className="w-full mt-2 flex items-center justify-center gap-2 px-2 py-1.5 rounded text-xs font-semibold bg-gray-200/50 hover:bg-red-50 hover:text-red-600 dark:bg-slate-800 dark:hover:bg-red-950/35 dark:hover:text-red-400 text-gray-700 dark:text-slate-300 transition-colors"
            >
              <LogOut className="w-3.5 h-3.5" />
              <span>{isRu ? 'Выйти' : 'Sign Out'}</span>
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-2 p-3 rounded-lg bg-gray-100 dark:bg-slate-800/50">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-indigo-600/10 text-indigo-500 flex items-center justify-center font-bold text-sm">
                DS
              </div>
              <div className="flex flex-col text-left overflow-hidden">
                <span className="text-sm font-medium text-gray-900 dark:text-gray-200 truncate">Igor Malysh</span>
                <span className="text-[10px] text-gray-500 dark:text-slate-400 truncate tracking-tight">Offline Preview</span>
              </div>
            </div>

            <button
              onClick={() => loginWithGoogle()}
              className="w-full mt-2 flex items-center justify-center gap-2 px-2 py-1.5 rounded text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm transition-colors"
            >
              <LogIn className="w-3.5 h-3.5" />
              <span>Connect Google</span>
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}

function NavItem({ item, activeTab, setActiveTab }: any) {
  const Icon = item.icon;
  const isActive = activeTab === item.id;

  return (
    <button
      onClick={() => setActiveTab(item.id)}
      className={cn(
        "w-full flex items-center px-3 py-2.5 rounded-lg text-sm font-medium transition-colors text-left",
        isActive
          ? "bg-indigo-50 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-400 font-bold"
          : "text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800/50 hover:text-gray-900 dark:hover:text-gray-200"
      )}
    >
      <div className="flex items-center gap-3">
        <Icon className={cn("w-5 h-5", isActive ? "text-indigo-600 dark:text-indigo-400" : "text-gray-400 dark:text-slate-500")} />
        <span>{item.label}</span>
      </div>
    </button>
  );
}
