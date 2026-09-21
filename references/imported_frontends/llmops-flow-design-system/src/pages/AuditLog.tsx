import React, { useState } from 'react';
import { Shield, Filter, Hexagon, Globe, X } from 'lucide-react';
import { useCluster } from '../context/ClusterContext';
import { useLanguage } from '../context/LanguageContext';

export function AuditLog() {
  const { selectedClusterId } = useCluster();
  const { t } = useLanguage();
  const [showFilters, setShowFilters] = useState(false);
  const logs = [
    { id: 1, user: 'Igor Malysh', action: t('deployedModelMsg'), target: 'llama-3-70b-instruct', time: t('tenMinsAgo'), status: 'success', clusterId: 'msk-gpu-01' },
    { id: 2, user: 'System', action: t('scaledReplicasMsg'), target: 'mistral-large-latest (2 -> 4)', time: t('oneHourAgo'), status: 'info', clusterId: 'spb-gpu-02' },
    { id: 3, user: 'Anna Smith', action: t('updatedTrafficSplitMsg'), target: 'qwen-1.5-32b-chat (90/10)', time: t('threeHoursAgo'), status: 'warning', clusterId: 'global' },
    { id: 4, user: 'Igor Malysh', action: t('rolledBackReleaseMsg'), target: 'rel-1a2b3c', time: t('oneDayAgo'), status: 'error', clusterId: 'msk-gpu-01' },
    { id: 5, user: 'Admin', action: t('modifiedQuotaMsg'), target: 'Data Science Team', time: t('twoDaysAgo'), status: 'info', clusterId: 'global' },
  ];

  const filteredLogs = selectedClusterId === 'all'
    ? logs
    : logs.filter(l => l.clusterId === selectedClusterId || l.clusterId === 'global');

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{t('auditLog')}</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">{t('auditLogSub')}</p>
        </div>
        <button
          onClick={() => setShowFilters(!showFilters)}
          className="px-4 py-2 bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors flex items-center gap-2"
        >
          <Filter className="w-4 h-4" />
          {t('filterLogs')}
        </button>
      </div>

      {showFilters && (
        <div className="p-4 bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl shadow-sm flex items-center gap-4">
           <div className="flex-1">
             <label className="text-xs font-semibold text-gray-500 uppercase block mb-1">{t('users')}</label>
             <select className="w-full bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm text-gray-900 dark:text-gray-100">
               <option>{t('allUsers')}</option>
               <option>Igor Malysh</option>
               <option>Anna Smith</option>
               <option>System</option>
             </select>
           </div>
           <div className="flex-1">
             <label className="text-xs font-semibold text-gray-500 uppercase block mb-1">{t('status')}</label>
             <select className="w-full bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm text-gray-900 dark:text-gray-100">
               <option>{t('allStatuses')}</option>
               <option>{t('success')}</option>
               <option>{t('warning')}</option>
               <option>{t('failed')}</option>
             </select>
           </div>
        </div>
      )}

      <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl shadow-sm overflow-hidden">
        <div className="divide-y divide-gray-200 dark:divide-slate-800">
          {filteredLogs.map((log) => (
            <div key={log.id} className="p-4 hover:bg-gray-50 dark:hover:bg-slate-900/50 transition-colors flex items-start gap-4">
               <div className="mt-1">
                 <Shield className={`w-5 h-5 ${
                   log.status === 'success' ? 'text-emerald-500' :
                   log.status === 'error' ? 'text-red-500' :
                   log.status === 'warning' ? 'text-amber-500' : 'text-blue-500'
                 }`} />
               </div>
               <div className="flex-1 min-w-0">
                 <div className="flex items-center justify-between">
                   <div className="flex items-center gap-2">
                     <p className="text-sm font-semibold text-gray-900 dark:text-white truncate">
                       {log.user} <span className="text-xs text-gray-500 ml-1">{log.action}</span>
                     </p>
                     <div className="flex items-center gap-1.5 px-1.5 py-0.5 rounded bg-gray-100 dark:bg-slate-900 border border-gray-200 dark:border-slate-800">
                       {log.clusterId === 'global' ? (
                         <Globe className="w-2.5 h-2.5 text-indigo-500" />
                       ) : (
                         <Hexagon className="w-2.5 h-2.5 text-emerald-500" />
                       )}
                       <span className="text-[9px] font-bold text-gray-600 dark:text-slate-400 uppercase">{log.clusterId}</span>
                     </div>
                   </div>
                   <span className="text-xs text-gray-400 dark:text-slate-500 font-medium">{log.time}</span>
                 </div>
                 <p className="text-xs text-indigo-600 dark:text-indigo-400 mt-1 font-mono">{log.target}</p>
               </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
