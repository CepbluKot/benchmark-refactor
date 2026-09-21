import React, { useState, useEffect } from 'react';
import {
  Rocket,
  Pause,
  Play,
  RotateCcw,
  FastForward,
  CheckCircle2,
  AlertTriangle,
  Clock,
  ArrowRight,
  Activity,
  X,
  Plus,
  ArrowUpRight,
  ChevronRight,
  Loader2,
  Globe,
  Settings,
  History,
  TrendingDown,
  BarChart2,
  Trash2,
  RefreshCw
} from 'lucide-react';
import {
  getReleases,
  pauseRelease,
  resumeRelease,
  rollbackRelease,
  skipReleaseTo100,
  startRelease,
  deleteRelease,
  retryRelease,
  getDeployments,
  MOCK_ROUTES,
  Release,
  Deployment
} from '../api/mock';

import { useLanguage } from '../context/LanguageContext';
import { useCluster } from '../context/ClusterContext';
import { cn } from '../lib/utils';
import { motion, AnimatePresence } from 'motion/react';

import { FieldTooltip } from '../components/FieldTooltip';

export function Releases() {
  const { t, language } = useLanguage();
  const { selectedClusterId } = useCluster();
  const [releases, setReleases] = useState<Release[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedRelease, setSelectedRelease] = useState<Release | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [confirmAction, setConfirmAction] = useState<{ action: (id: string) => Promise<void>, id: string, name: 'delete' | 'rollback' } | null>(null);

  const fetchData = async () => {
    setLoading(true);
    const data = await getReleases(selectedClusterId);
    setReleases(data);
    setLoading(false);
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000); // Polling for "real-time" updates
    return () => clearInterval(interval);
  }, [selectedClusterId]);

  const executeAction = async (action: (id: string) => Promise<void>, id: string) => {
    await action(id);
    await fetchData();
    // Update selected release if it's the one we just modified
    const updated = await getReleases(selectedClusterId);
    setReleases(updated);
    if (selectedRelease?.id === id) {
      setSelectedRelease(updated.find(r => r.id === id) || null);
    }
  };

  const handleAction = async (action: (id: string) => Promise<void>, id: string) => {
    if (action === deleteRelease || action === rollbackRelease) {
      setConfirmAction({
        action,
        id,
        name: action === deleteRelease ? 'delete' : 'rollback'
      });
      return;
    }
    await executeAction(action, id);
  };

  return (
    <div className="max-w-7xl mx-auto pb-20 relative">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
             <Rocket className="w-8 h-8 text-indigo-600" />
             {t('releases')}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
             {t('releasesSub')}
          </p>
        </div>

        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium shadow-sm transition-all shadow-indigo-500/10"
        >
          <Plus className="w-4 h-4" />
          {t('startRelease')}
        </button>
      </div>

      {/* Main Table */}
      <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-gray-50 dark:bg-slate-900/50 text-xs font-semibold uppercase tracking-wider text-gray-500 border-b border-gray-200 dark:border-slate-800">
                <th className="px-6 py-4">{t('release') || 'Release'}</th>
                <th className="px-6 py-4">{t('status')}</th>
                <th className="px-6 py-4 text-center">{t('rolloutProgress') || 'Rollout Progress'}</th>
                <th className="px-6 py-4">{t('sloHealth') || 'SLO / Health'}</th>
                <th className="px-6 py-4 text-right">{t('started') || 'Started'}</th>
                <th className="px-6 py-4 text-right">{t('actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 dark:divide-slate-900">
              {loading && releases.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-8 py-20 text-center">
                    <Loader2 className="w-8 h-8 animate-spin text-indigo-500 mx-auto" />
                  </td>
                </tr>
              ) : (
                releases.map(rel => (
                  <tr
                    key={rel.id}
                    onClick={() => setSelectedRelease(rel)}
                    className={cn(
                      "group cursor-pointer transition-colors",
                      selectedRelease?.id === rel.id ? "bg-indigo-50/50 dark:bg-indigo-500/5" : "hover:bg-gray-50 dark:hover:bg-slate-900/50"
                    )}
                  >
                    <td className="px-8 py-5">
                      <div className="flex flex-col">
                        <span className="text-sm font-black text-gray-900 dark:text-white uppercase tracking-tight">
                           {rel.name}
                        </span>
                        <div className="flex items-center gap-2 mt-1">
                          <span className="text-[10px] font-bold text-gray-400 uppercase">{rel.sourceId}</span>
                          <ArrowRight className="w-3 h-3 text-gray-300" />
                          <span className="text-[10px] font-bold text-indigo-600 dark:text-indigo-400 uppercase">{rel.targetId}</span>
                        </div>
                      </div>
                    </td>
                    <td className="px-8 py-5">
                       <StatusBadge status={rel.status} />
                    </td>
                    <td className="px-8 py-5">
                       <div className="flex flex-col items-center gap-1.5">
                          <div className="w-24 h-1.5 bg-gray-100 dark:bg-slate-800 rounded-full overflow-hidden">
                             <motion.div
                               initial={{ width: 0 }}
                               animate={{ width: `${rel.currentPercent}%` }}
                               className={cn(
                                 "h-full rounded-full",
                                 rel.status === 'rolled-back' ? 'bg-red-500' : 'bg-indigo-500'
                               )}
                             />
                          </div>
                          <span className="text-[10px] font-black text-gray-900 dark:text-white">{rel.currentPercent}%</span>
                       </div>
                    </td>
                    <td className="px-8 py-5">
                       <div className="flex flex-col">
                          <div className="flex items-center gap-2">
                             <span className={cn(
                               "text-sm font-black",
                               rel.sloHealthy ? "text-emerald-600" : "text-red-600"
                             )}>
                                {(100 - rel.currentMetrics.errorRate).toFixed(2)}%
                             </span>
                             {rel.sloHealthy ? (
                               <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                             ) : (
                               <AlertTriangle className="w-3.5 h-3.5 text-red-500 animate-pulse" />
                             )}
                          </div>
                          <span className="text-[10px] text-gray-400 font-bold uppercase tracking-tighter">p99: {rel.currentMetrics.latencyP99}ms</span>
                       </div>
                    </td>
                    <td className="px-8 py-5 text-right">
                       <span className="text-[10px] font-bold text-gray-400 uppercase">
                          {new Date(rel.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                       </span>
                    </td>
                    <td className="px-8 py-5 text-right">
                       <div className="flex items-center justify-end gap-2">
                         <button
                           onClick={(e) => {
                             e.stopPropagation();
                             handleAction(deleteRelease, rel.id);
                           }}
                           className="p-1.5 text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-md transition-colors"
                         >
                           <Trash2 className="w-4 h-4" />
                         </button>
                         <button
                           onClick={(e) => {
                             e.stopPropagation();
                             setSelectedRelease(rel);
                           }}
                           className="px-3 py-1.5 bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 hover:bg-gray-50 dark:hover:bg-slate-800 rounded-md text-xs font-semibold text-gray-700 dark:text-gray-300 transition-colors shadow-sm"
                         >
                           Edit
                         </button>
                       </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Side Panel */}
      <AnimatePresence>
        {selectedRelease && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setSelectedRelease(null)}
              className="fixed inset-0 bg-slate-950/20 backdrop-blur-sm z-40"
            />
            <motion.div
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', damping: 25, stiffness: 200 }}
              className="fixed right-0 top-0 h-full w-full max-w-2xl bg-white dark:bg-slate-950 border-l border-gray-200 dark:border-slate-800 z-50 shadow-2xl overflow-y-auto"
            >
              <ReleaseDetails
                release={selectedRelease}
                onClose={() => setSelectedRelease(null)}
                onAction={handleAction}
              />
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* Create Modal */}
      <AnimatePresence>
        {showCreateModal && (
          <CreateReleaseModal
            onClose={() => setShowCreateModal(false)}
            onCreated={fetchData}
          />
        )}
      </AnimatePresence>

      {confirmAction && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl p-6 max-w-sm w-full shadow-2xl space-y-4 text-gray-900 dark:text-white">
            <div className="flex items-center gap-3 text-red-500">
              <AlertTriangle className="w-6 h-6 shrink-0 animate-bounce" />
              <h3 className="text-base font-bold text-gray-900 dark:text-white font-sans">
                {language === 'ru' ? 'Вы уверены?' : 'Are you sure?'}
              </h3>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed font-sans">
              {language === 'ru'
                ? (confirmAction.name === 'delete'
                    ? `Вы действительно хотите безвозвратно удалить выпуск "${confirmAction.id}"? Все логи и настройки этого развертывания будут стерты.`
                    : `Вы пытаетесь запустить полный откат релиза "${confirmAction.id}". Трафик перенаправится на исходную версию подов.`)
                : (confirmAction.name === 'delete'
                    ? `Are you sure you want to permanently delete release "${confirmAction.id}"? All records and associated logs will be erased.`
                    : `You are about to initiate rollback for release "${confirmAction.id}". Traffic will immediately route back to preceding stable pod group.`)
              }
            </p>
            <div className="flex items-center gap-3">
              <button
                onClick={() => setConfirmAction(null)}
                className="flex-1 py-2 px-3 bg-gray-100 dark:bg-slate-800 text-gray-800 dark:text-white rounded-lg text-xs font-semibold hover:bg-gray-200 dark:hover:bg-slate-700 transition font-sans"
              >
                {language === 'ru' ? 'Отмена' : 'Cancel'}
              </button>
              <button
                onClick={async () => {
                  const { action, id } = confirmAction;
                  setConfirmAction(null);
                  await executeAction(action, id);
                }}
                className="flex-1 py-2 px-3 bg-red-650 dark:bg-red-600 hover:bg-red-700 text-white rounded-lg text-xs font-semibold transition bg-red-600 font-sans"
              >
                {language === 'ru' ? 'Выполнить' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useLanguage();
  const config: any = {
    rolling: { bg: 'bg-indigo-50 text-indigo-600 border-indigo-100 dark:bg-indigo-500/10 dark:text-indigo-400 dark:border-indigo-500/20', icon: Activity, animate: true },
    paused: { bg: 'bg-amber-50 text-amber-600 border-amber-100 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/20', icon: Pause },
    succeeded: { bg: 'bg-emerald-50 text-emerald-600 border-emerald-100 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20', icon: CheckCircle2 },
    rolledback: { bg: 'bg-red-50 text-red-600 border-red-100 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20', icon: RotateCcw },
    failed: { bg: 'bg-red-50 text-red-600 border-red-100 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20', icon: AlertTriangle }
  };

  const key = status.replace('-', '');
  const cfg = config[key] || config.rolling;
  const Icon = cfg.icon;

  return (
    <div className={cn(
      "flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[10px] font-semibold uppercase tracking-wider",
      cfg.bg
    )}>
      <Icon className={cn("w-3.5 h-3.5", cfg.animate && "animate-spin")} style={cfg.animate ? { animationDuration: '3s' } : {}}/>
      {t(status.replace('-', '')) || status.replace('-', ' ')}
    </div>
  );
}

function ReleaseDetails({ release: rel, onClose, onAction }: { release: Release, onClose: () => void, onAction: any }) {
  const { t } = useLanguage();

  return (
    <div className="flex flex-col h-full">
      <div className="p-8 border-b border-gray-100 dark:border-slate-800 flex items-center justify-between bg-gray-50/50 dark:bg-slate-900/30">
        <div className="flex items-center gap-4">
          <div className="p-3 bg-indigo-600 text-white rounded-xl shadow-lg shadow-indigo-500/10">
            <Rocket className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-900 dark:text-white">{rel.name}</h2>
            <div className="flex items-center gap-2 mt-1">
               <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">ID: {rel.id}</span>
               <div className="w-1 h-1 rounded-full bg-gray-300" />
               <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">{rel.strategy}</span>
            </div>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-2 hover:bg-gray-200 dark:hover:bg-slate-800 rounded-lg transition-colors"
        >
          <X className="w-5 h-5 text-gray-400" />
        </button>
      </div>

      <div className="flex-1 p-8 overflow-y-auto space-y-10 custom-scrollbar">
        {/* Progress & Quick Actions */}
        <div className="space-y-6">
           <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">Rollout Progress</h3>
              <div className="text-xs font-semibold text-indigo-600 tabular-nums">
                 {rel.currentPercent}% target reached
              </div>
           </div>

           <div className="h-3 bg-gray-100 dark:bg-slate-900 rounded-full overflow-hidden p-0.5 border border-gray-200 dark:border-slate-800">
              <motion.div
                 initial={{ width: 0 }}
                 animate={{ width: `${rel.currentPercent}%` }}
                 className={cn(
                   "h-full rounded-full transition-all duration-300 relative",
                   rel.status === 'rolled-back' ? 'bg-red-500' : 'bg-indigo-600'
                 )}
              >
                 <div className="absolute inset-0 bg-white/20 animate-pulse" />
              </motion.div>
           </div>

           {(rel.status === 'rolling' || rel.status === 'paused') && (
             <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mt-4">
                <ButtonAction
                  icon={rel.status === 'paused' ? Play : Pause}
                  label={rel.status === 'paused' ? t('resume') : t('pause')}
                  onClick={() => onAction(rel.status === 'paused' ? resumeRelease : pauseRelease, rel.id)}
                  color={rel.status === 'paused' ? 'indigo' : 'amber'}
                />
                <ButtonAction
                  icon={RotateCcw}
                  label={t('rollback')}
                  onClick={() => onAction(rollbackRelease, rel.id)}
                  color="red"
                />
                <ButtonAction
                  icon={FastForward}
                  label={t('skipTo100')}
                  onClick={() => onAction(skipReleaseTo100, rel.id)}
                  color="emerald"
                />
             </div>
           )}

           {(rel.status === 'rolled-back') && (
             <div className="grid grid-cols-2 gap-3 mt-4">
                <ButtonAction
                  icon={RefreshCw}
                  label={t('retry') || 'Retry Rollout'}
                  onClick={() => onAction(retryRelease, rel.id)}
                  color="indigo"
                />
                <ButtonAction
                  icon={Trash2}
                  label={t('delete') || 'Delete Release'}
                  onClick={() => onAction(deleteRelease, rel.id)}
                  color="red"
                />
             </div>
           )}

           {(rel.status === 'succeeded' || rel.status === 'failed') && (
             <div className="mt-4">
                <ButtonAction
                  icon={Trash2}
                  label={t('delete') || 'Delete Release'}
                  onClick={() => onAction(deleteRelease, rel.id)}
                  color="red"
                />
             </div>
           )}
        </div>

        {/* Real-time Metrics */}
        <div className="space-y-4">
           <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">Live Comparison</h3>
           <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <MetricCard
                title="SOURCE VERSION"
                metrics={rel.sourceMetrics}
                isTarget={false}
                label={rel.sourceCluster || rel.sourceId}
              />
              <MetricCard
                title="TARGET VERSION"
                metrics={rel.currentMetrics}
                isTarget={true}
                label={rel.targetCluster || rel.targetId}
              />
           </div>
        </div>

        {/* Timeline */}
        <div className="space-y-6">
           <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">{t('timeline')}</h3>
           <div className="relative pl-8 space-y-8 before:absolute before:left-[11px] before:top-2 before:bottom-2 before:w-0.5 before:bg-gray-100 dark:before:bg-slate-800">
             {rel.steps.map((step, idx) => (
                <div key={idx} className="relative group">
                   <div className={cn(
                     "absolute -left-10 w-6 h-6 rounded-lg flex items-center justify-center border-4 border-white dark:border-slate-950 z-10",
                     step.status === 'completed' ? "bg-emerald-500" :
                     step.status === 'active' ? "bg-indigo-600 animate-pulse" : "bg-gray-200 dark:bg-slate-800"
                   )}>
                      {step.status === 'completed' && <CheckCircle2 className="w-3 h-3 text-white" />}
                   </div>

                   <div className={cn(
                     "p-5 rounded-xl border transition-all",
                     step.status === 'active' ? "bg-indigo-50/50 dark:bg-indigo-500/5 border-indigo-200 dark:border-indigo-500/20" : "bg-white dark:bg-slate-950 border-gray-100 dark:border-slate-900"
                   )}>
                      <div className="flex items-center justify-between mb-3">
                         <span className="text-sm font-semibold uppercase tracking-wider">{step.percent}% Traffic Shift</span>
                         {step.timestamp && (
                            <span className="text-[10px] font-semibold text-gray-400 uppercase">{new Date(step.timestamp).toLocaleTimeString()}</span>
                         )}
                      </div>

                      {step.metrics && (
                        <div className="flex items-center gap-4">
                           <div className="flex items-center gap-1">
                              <Activity className="w-3.5 h-3.5 text-gray-400" />
                              <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">{step.metrics.latencyP99}ms</span>
                           </div>
                           <div className="flex items-center gap-1">
                              <AlertTriangle className="w-3.5 h-3.5 text-gray-400" />
                              <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">{step.metrics.errorRate}%</span>
                           </div>
                        </div>
                      )}
                   </div>
                </div>
             ))}
           </div>
        </div>

        {/* Event Log */}
        <div className="space-y-4">
           <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-400">{t('events')}</h3>
           <div className="bg-gray-50 dark:bg-slate-900/50 rounded-xl p-6 space-y-4 border border-gray-100 dark:border-slate-800">
              {rel.events.map((ev, idx) => (
                <div key={idx} className="flex gap-4 group">
                   <span className="text-[10px] font-semibold text-gray-400 uppercase w-12 pt-1">{new Date(ev.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                   <div className="flex-1">
                      <p className="text-xs font-semibold text-gray-700 dark:text-slate-300">{ev.message}</p>
                   </div>
                </div>
              ))}
           </div>
        </div>
      </div>
    </div>
  );
}

function MetricCard({ title, metrics, isTarget, label }: { title: string, metrics: any, isTarget: boolean, label: string }) {
  return (
    <div className={cn(
      "p-6 rounded-xl border shadow-sm",
      isTarget ? "bg-indigo-50/30 dark:bg-indigo-500/5 border-indigo-100 dark:border-indigo-500/20" : "bg-white dark:bg-slate-950 border-gray-100 dark:border-slate-900"
    )}>
       <div className="flex items-center justify-between mb-4">
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">{title}</h4>
          <span className="text-[10px] font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider">{label}</span>
       </div>

       <div className="space-y-4">
          <div className="flex items-center justify-between">
             <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-gray-400" />
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">p99 Latency</span>
             </div>
             <span className="text-lg font-bold text-gray-900 dark:text-white">{metrics.latencyP99}ms</span>
          </div>
          <div className="flex items-center justify-between">
             <div className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-gray-400" />
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Error Rate</span>
             </div>
             <span className={cn(
               "text-lg font-bold",
               metrics.errorRate > 5 ? "text-red-600" : "text-emerald-600"
             )}>{metrics.errorRate}%</span>
          </div>
          <div className="flex items-center justify-between">
             <div className="flex items-center gap-2">
                <TrendingDown className="w-4 h-4 text-gray-400" />
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Throughput</span>
             </div>
             <span className="text-lg font-bold text-gray-900 dark:text-white">{metrics.throughput} rps</span>
          </div>
       </div>
    </div>
  );
}

function ButtonAction({ icon: Icon, label, onClick, color }: any) {
  const colors: any = {
    indigo: 'bg-indigo-600 text-white hover:bg-indigo-700 shadow-indigo-500/10',
    amber: 'bg-amber-50 text-amber-600 hover:bg-amber-100 border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/20',
    red: 'bg-red-50 text-red-600 hover:bg-red-100 border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20',
    emerald: 'bg-emerald-50 text-emerald-600 hover:bg-emerald-100 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20',
    slate: 'bg-slate-50 text-slate-600 hover:bg-slate-100 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700'
  };

  return (
    <button
      onClick={onClick}
      className={cn(
        "flex flex-col items-center justify-center p-3 rounded-xl border transition-all active:scale-95 shadow-sm",
        colors[color]
      )}
    >
      <Icon className="w-5 h-5 mb-1.5" />
      <span className="text-[10px] font-semibold uppercase tracking-wider">{label}</span>
    </button>
  );
}

function CreateReleaseModal({ onClose, onCreated }: { onClose: () => void, onCreated: () => void }) {
  const { t } = useLanguage();
  const [loading, setLoading] = useState(false);
  const [routes, setRoutes] = useState<any[]>([]);
  const [deployments, setDeployments] = useState<Deployment[]>([]);

  const [formData, setFormData] = useState({
    name: '',
    routeId: 'r1',
    sourceId: '',
    targetId: '',
    strategy: 'step' as const,
    type: 'standard' as const,
    sloLatency: 300,
    sloErrors: 1.0,
  });

  useEffect(() => {
    async function load() {
      const deps = await getDeployments();
      setDeployments(deps);
      setRoutes(MOCK_ROUTES);
    }
    load();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await startRelease(formData);
      onCreated();
      onClose();
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-slate-950/40 backdrop-blur-md z-[100] flex items-center justify-center p-4">
       <motion.div
         initial={{ scale: 0.95, opacity: 0 }}
         animate={{ scale: 1, opacity: 1 }}
         className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl w-full max-w-2xl overflow-hidden shadow-2xl"
       >
          <div className="p-6 border-b border-gray-100 dark:border-slate-900 bg-gray-50/50 dark:bg-slate-900/30 flex items-center justify-between">
             <div>
                <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
                   <Rocket className="w-6 h-6 text-indigo-600" />
                   Initiate Rollout
                </h2>
                <p className="text-xs text-gray-500 font-medium uppercase tracking-wider mt-1">Automatic progressive deployment pipeline</p>
             </div>
             <button onClick={onClose} className="p-2 hover:bg-gray-200 dark:hover:bg-slate-800 rounded-lg transition-colors">
                <X className="w-5 h-5 text-gray-400" />
             </button>
          </div>

          <form onSubmit={handleSubmit} className="p-8 space-y-6 max-h-[70vh] overflow-y-auto custom-scrollbar">
             <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-2">
                   <label className="text-xs font-semibold uppercase tracking-wider text-gray-500">Release Name</label>
                   <input
                     required
                     value={formData.name}
                     onChange={e => setFormData({...formData, name: e.target.value})}
                     className="w-full bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-4 py-2 text-sm font-medium text-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-indigo-500"
                     placeholder="v1.2.0-stable..."
                   />
                </div>
                <div className="space-y-2">
                   <label className="text-xs font-semibold uppercase tracking-wider text-gray-500">
                     Strategy
                     <FieldTooltip content="Controls how traffic is shifted. 'Step-by-step' safely ramps traffic. 'Instant' immediately routes 100%." />
                   </label>
                   <select
                     value={formData.strategy}
                     onChange={e => setFormData({...formData, strategy: e.target.value as any})}
                     className="w-full bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-4 py-2 text-sm font-medium text-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-indigo-500"
                   >
                      <option value="step">Step-by-step (Pause after each step)</option>
                      <option value="instant">Instant (Immediate 100% switch)</option>
                   </select>
                </div>
             </div>

             {/* Source & Target Configuration with Overrides */}
             <div className="grid grid-cols-1 md:grid-cols-2 gap-6 bg-slate-50 dark:bg-slate-900/40 p-4 rounded-xl border border-gray-150 dark:border-slate-800/80">
                <div className="space-y-2">
                   <label className="text-xs font-bold uppercase tracking-wider text-gray-500 block">Source Deployment (Откуда идём)</label>
                   <select
                     required
                     value={formData.sourceId}
                     onChange={e => setFormData({...formData, sourceId: e.target.value})}
                     className="w-full bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-3 py-2 text-xs font-semibold text-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-indigo-500"
                   >
                      <option value="">Select source deployment...</option>
                      {deployments.map(d => (
                         <option key={d.id} value={d.id}>{d.modelName} [{d.id.slice(-5)}] (Replicas: {d.replicas}, Cluster: {d.clusterId})</option>
                      ))}
                   </select>
                </div>

                <div className="space-y-2">
                   <label className="text-xs font-bold uppercase tracking-wider text-gray-500 block">Target Deployment (Куда идём)</label>
                   <select
                     required
                     value={formData.targetId}
                     onChange={e => {
                       const selected = deployments.find(d => d.id === e.target.value);
                       setFormData({
                         ...formData,
                         targetId: e.target.value,
                         name: selected ? `release-${formData.name || selected.modelName.toLowerCase().replace(/\s+/g, '-')}` : formData.name
                       });
                     }}
                     className="w-full bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-3 py-2 text-xs font-semibold text-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-indigo-500"
                   >
                      <option value="">Select target...</option>
                      {deployments.map(d => (
                         <option key={d.id} value={d.id}>{d.modelName} [{d.id.slice(-5)}] ({d.clusterId})</option>
                      ))}
                   </select>
                </div>
             </div>

             {/* Interactive Custom Configuration Overrides */}
             <div className="bg-indigo-50/20 dark:bg-indigo-500/5 p-5 rounded-xl border border-indigo-100 dark:border-indigo-550/10 space-y-4">
                <div className="flex items-center justify-between mb-2">
                   <span className="text-xs font-bold uppercase tracking-wider text-indigo-700 dark:text-indigo-400">💡 Конфигурация параметров нового деплоймента (Target)</span>
                   <span className="text-[10px] bg-indigo-100 dark:bg-indigo-500/20 text-indigo-600 dark:text-indigo-400 px-2 py-0.5 rounded-full font-bold uppercase">Custom Configure</span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                   <div className="space-y-1">
                      <label className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">Target Реплики (Desired Replicas)</label>
                      <div className="flex items-center gap-3">
                        <input
                          type="range"
                          min="1"
                          max="20"
                          defaultValue="3"
                          className="flex-1 accent-indigo-600 cursor-pointer"
                          id="target-replicas-slider"
                          onChange={(e) => {
                             const lbl = document.getElementById('replicas-val-lbl');
                             if (lbl) lbl.innerText = e.target.value;
                          }}
                        />
                        <span id="replicas-val-lbl" className="text-xs font-bold text-indigo-600 dark:text-indigo-400 bg-white dark:bg-slate-900 px-2.5 py-1 border border-indigo-100 dark:border-slate-850 rounded">3</span>
                      </div>
                   </div>

                   <div className="space-y-1">
                      <label className="text-[10px] font-bold text-gray-500 uppercase tracking-wide">Аренда GPU для подов (vLLM core)</label>
                      <select className="w-full bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-3 py-1.5 text-xs font-medium text-gray-950 dark:text-white outline-none">
                         <option>No GPU Requirements (CPU inference)</option>
                         <option>1x NVIDIA A10G (24GB VRAM)</option>
                         <option selected>1x NVIDIA A100 (80GB VRAM)</option>
                         <option>2x NVIDIA A100 (Dual GPU Node-link)</option>
                         <option>1x NVIDIA H100 (SXM5 MultiTensor)</option>
                      </select>
                   </div>
                </div>

                <div className="grid grid-cols-2 gap-4 pt-1">
                   <label className="flex items-center gap-2.5 cursor-pointer">
                      <input type="checkbox" defaultChecked className="rounded text-indigo-600 focus:ring-indigo-500 h-4 w-4 border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900" />
                      <div className="text-[10px] font-bold text-gray-600 dark:text-slate-300 uppercase tracking-tight">Авто-эвикция KV Cache при утилизации &gt; 90%</div>
                   </label>
                   <label className="flex items-center gap-2.5 cursor-pointer">
                      <input type="checkbox" defaultChecked className="rounded text-indigo-600 focus:ring-indigo-500 h-4 w-4 border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900" />
                      <div className="text-[10px] font-bold text-gray-600 dark:text-slate-300 uppercase tracking-tight">Авто-балансировка Cross-Cluster (Failover ready)</div>
                   </label>
                </div>
             </div>

             <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-2">
                   <label className="text-xs font-semibold uppercase tracking-wider text-gray-500">Release Type</label>
                   <div className="flex bg-gray-100 dark:bg-slate-900 p-1 rounded-lg">
                      <button
                        type="button"
                        onClick={() => setFormData({...formData, type: 'standard'})}
                        className={cn("flex-1 py-2 text-[10px] font-semibold uppercase tracking-wider rounded-md transition-all", formData.type === 'standard' ? "bg-white dark:bg-slate-800 text-indigo-600 shadow-sm" : "text-gray-400")}
                      > Standard </button>
                      <button
                        type="button"
                        onClick={() => setFormData({...formData, type: 'migration'})}
                        className={cn("flex-1 py-2 text-[10px] font-semibold uppercase tracking-wider rounded-md transition-all", formData.type === 'migration' ? "bg-white dark:bg-slate-800 text-indigo-600 shadow-sm" : "text-gray-400")}
                      > Migration </button>
                   </div>
                </div>
             </div>

             <div className="pt-6 border-t border-gray-100 dark:border-slate-900">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-6">SLO Thresholds (Auto-Rollback)</h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                   <div className="space-y-2">
                      <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">TTFT Degradation</label>
                      <div className="relative">
                         <input
                           type="number"
                           defaultValue={50}
                           className="w-full bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg pl-3 pr-8 py-2 text-sm font-semibold outline-none focus:ring-2 focus:ring-red-500"
                         />
                         <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-semibold text-gray-400">MS</span>
                      </div>
                   </div>
                   <div className="space-y-2">
                      <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">TPS Drop limit</label>
                      <div className="relative">
                         <input
                           type="number"
                           defaultValue={10}
                           className="w-full bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm font-semibold outline-none focus:ring-2 focus:ring-red-500"
                         />
                         <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-semibold text-gray-400">%</span>
                      </div>
                   </div>
                   <div className="space-y-2">
                      <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">Max Error Rate</label>
                      <div className="relative">
                         <input
                           type="number"
                           step="0.1"
                           value={formData.sloErrors}
                           onChange={e => setFormData({...formData, sloErrors: Number(e.target.value)})}
                           className="w-full bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg pl-10 pr-4 py-2 text-sm font-semibold outline-none focus:ring-2 focus:ring-red-500"
                         />
                         <AlertTriangle className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                         <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] font-semibold text-gray-400">%</span>
                      </div>
                   </div>
                   <div className="space-y-2">
                      <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">Max Queue</label>
                      <div className="relative">
                         <input
                           type="number"
                           defaultValue={100}
                           className="w-full bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm font-semibold outline-none focus:ring-2 focus:ring-red-500"
                         />
                      </div>
                   </div>
                </div>
             </div>

             <button
               type="submit"
               disabled={loading}
               className="w-full py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-semibold transition-all shadow-md shadow-indigo-500/10 flex items-center justify-center gap-2 disabled:opacity-50"
             >
                {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : (
                   <>
                     <Rocket className="w-4 h-4" />
                     Launch Rollout
                   </>
                )}
             </button>
          </form>
       </motion.div>
    </div>
  );
}
