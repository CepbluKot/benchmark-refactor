import React, { useState, useEffect } from 'react';
import {
  Database,
  Plus,
  Globe,
  Hexagon,
  Loader2,
  X,
  Users,
  User,
  Box,
  Zap,
  TrendingUp,
  AlertTriangle,
  History,
  ShieldCheck,
  ChevronDown,
  Edit,
  Trash2
} from 'lucide-react';
import {
  getQuotas,
  getTeams,
  getUsers,
  getModelRates,
  createQuota,
  updateQuota,
  deleteQuota,
  Quota,
  Team,
  User as AIUser,
  ModelRate
} from '../api/mock';
import { useCluster } from '../context/ClusterContext';
import { useLanguage } from '../context/LanguageContext';
import { cn } from '../lib/utils';
import { motion, AnimatePresence } from 'motion/react';

export function Quotas() {
  const { selectedClusterId } = useCluster();
  const { t } = useLanguage();
  const [quotas, setQuotas] = useState<Quota[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingQuota, setEditingQuota] = useState<Quota | null>(null);
  const [quotaToDelete, setQuotaToDelete] = useState<Quota | null>(null);

  const load = async () => {
    setLoading(true);
    const data = await getQuotas(selectedClusterId);
    setQuotas(data);
    setLoading(false);
  };

  useEffect(() => {
    load();
  }, [selectedClusterId]);

  const [showMenu, setShowMenu] = useState(false);
  const [initialType, setInitialType] = useState<'team' | 'user'>('team');

  const openForm = (type: 'team' | 'user') => {
    setInitialType(type);
    setEditingQuota(null);
    setShowForm(true);
    setShowMenu(false);
  };

  return (
    <div className="space-y-12 max-w-6xl mx-auto pb-20">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {t('quotasManagement')}
          </h1>
          <p className="text-gray-500 dark:text-slate-400 mt-1">
            {t('quotasSub')}
          </p>
        </div>

        <div>
          <button
            onClick={() => openForm('team')}
            className="px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium transition-all flex items-center gap-2 shadow-sm"
          >
            <Plus className="w-4 h-4" />
            {t('newQuota')}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
        <QuotaStatsCard
          title="Consolidated Budget"
          value="1.2M ₽"
          limit="5M ₽"
          percent={24}
          icon={TrendingUp}
        />
        <QuotaStatsCard
          title={t('activeQuotas')}
          value={quotas.length.toString()}
          sub="Governance Objects"
          icon={ShieldCheck}
        />
        <QuotaStatsCard
          title="Compliance Score"
          value="98.5%"
          sub="Policy adherence"
          color="emerald"
          icon={Zap}
        />
      </div>

      <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="text-xs font-semibold text-gray-500 uppercase tracking-wider bg-gray-50 dark:bg-slate-900/50 border-b border-gray-100 dark:border-slate-900">
                <th className="px-8 py-4">{t('teamProject')}</th>
                <th className="px-8 py-4">Limit Configuration</th>
                <th className="px-8 py-4">Current Usage</th>
                <th className="px-8 py-4 text-right">{t('actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-slate-900">
              {loading ? (
                <tr>
                   <td colSpan={4} className="px-8 py-20 text-center">
                    <Loader2 className="w-8 h-8 animate-spin text-indigo-500 mx-auto" />
                    <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mt-4">Analyzing throughput...</p>
                  </td>
                </tr>
              ) : quotas.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-8 py-20 text-center">
                    <Database className="w-12 h-12 text-gray-200 dark:text-slate-800 mx-auto mb-4" />
                    <p className="text-sm font-bold text-gray-500 uppercase">No active quotas found</p>
                  </td>
                </tr>
              ) : (
                quotas.map(quota => (
                  <QuotaRow
                    key={quota.id}
                    quota={quota}
                    onEdit={(q) => {
                      setEditingQuota(q);
                      setInitialType(q.subjectType);
                      setShowForm(true);
                    }}
                    onDelete={(q) => {
                      setQuotaToDelete(q);
                    }}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <AnimatePresence>
        {showForm && (
          <QuotaFormModal
             initialType={initialType}
             editingQuota={editingQuota}
             onClose={() => {
               setShowForm(false);
               setEditingQuota(null);
             }}
             onSuccess={() => {
               setShowForm(false);
               setEditingQuota(null);
               load();
             }}
          />
        )}

        {quotaToDelete && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setQuotaToDelete(null)}
              className="absolute inset-0 bg-slate-950/80 backdrop-blur-md"
            />

            <motion.div
              initial={{ scale: 0.95, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.95, opacity: 0, y: 20 }}
              className="w-full max-w-md bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl shadow-2xl relative p-6 space-y-4 z-10"
            >
              <div className="flex items-center gap-3">
                <div className="p-3 bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 rounded-xl">
                  <AlertTriangle className="w-5 h-5 animate-bounce" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-gray-900 dark:text-white">Подтверждение удаления</h3>
                  <p className="text-[11px] text-slate-400 mt-0.5">Субъект: <span className="font-mono text-indigo-500 dark:text-indigo-400 font-bold">{quotaToDelete.subjectName}</span></p>
                </div>
              </div>

              <p className="text-xs text-gray-500 dark:text-gray-400 leading-normal">
                Вы уверены, что хотите безвозвратно удалить эту квоту? Все ограничения будут сброшены для данного субъекта.
              </p>

              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setQuotaToDelete(null)}
                  className="flex-1 px-4 py-2 border border-gray-305 dark:border-slate-800 bg-transparent hover:bg-gray-50 dark:hover:bg-slate-900 rounded-xl text-xs font-bold text-gray-700 dark:text-slate-300 uppercase tracking-wider"
                >
                  Отмена
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    await deleteQuota(quotaToDelete.id);
                    setQuotaToDelete(null);
                    load();
                  }}
                  className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-xl text-xs font-bold uppercase tracking-wider shadow-md"
                >
                  Удалить
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}

function QuotaStatsCard({ title, value, limit, sub, percent, color = 'indigo', icon: Icon }: any) {
  return (
    <div className="p-6 bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl shadow-sm group hover:border-indigo-500/50 hover:shadow-md transition-all duration-300 relative overflow-hidden">
      <div className={cn(
        "absolute -right-4 -top-4 w-24 h-24 rounded-full blur-3xl opacity-10 group-hover:opacity-20 transition-opacity",
        color === 'indigo' ? 'bg-indigo-500' : color === 'emerald' ? 'bg-emerald-500' : 'bg-amber-500'
      )} />

      <div className="flex items-start justify-between relative mb-4">
        <div className={cn(
          "p-2.5 rounded-lg",
          color === 'indigo' ? 'bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600' :
          color === 'emerald' ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600' :
          'bg-amber-50 dark:bg-amber-500/10 text-amber-600'
        )}>
          <Icon className="w-5 h-5" />
        </div>
        {percent !== undefined && (
          <div className={cn(
            "text-xs font-medium px-2.5 py-1 rounded-lg",
            color === 'indigo' ? 'bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600' :
            color === 'emerald' ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600' :
            'bg-amber-50 dark:bg-amber-500/10 text-amber-600'
          )}>
            {percent}%
          </div>
        )}
      </div>

      <div className="space-y-1">
        <h4 className="text-sm font-medium text-gray-500">{title}</h4>
        <div className="text-2xl font-bold text-gray-900 dark:text-white">{value}</div>
        {limit && <div className="text-xs text-gray-500">limit: {limit}</div>}
        {sub && <div className="text-xs text-gray-500">{sub}</div>}
      </div>
    </div>
  );
}

const QuotaRow: React.FC<{
  quota: Quota;
  onEdit: (quota: Quota) => void;
  onDelete: (quota: Quota) => void;
}> = ({ quota, onEdit, onDelete }) => {
  const { t } = useLanguage();

  const usagePercent = Math.min(100, Math.round((quota.usageValue / quota.limitValue) * 100));
  const isOver = quota.status === 'blocked' || quota.usageValue > quota.limitValue;
  const isWarning = (usagePercent >= 80) && !isOver;

  const formatValue = (val: number) => {
    if (val >= 1000000000) return `${(val / 1000000000).toFixed(1)}B`;
    if (val >= 1000000) return `${(val / 1000000).toFixed(1)}M`;
    return val.toLocaleString();
  };

  const getActionColor = (action: string) => {
     if (action === 'block') return 'text-red-500';
     if (action === 'throttle') return 'text-amber-500';
     return 'text-indigo-500';
  };

  return (
    <tr className="hover:bg-gray-50/50 dark:hover:bg-slate-900/30 transition-colors group">
      <td className="px-8 py-6">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-gray-50 dark:bg-slate-900 border border-gray-100 dark:border-slate-800 text-indigo-600 dark:text-indigo-400 flex items-center justify-center font-black text-sm shadow-inner shrink-0">
            {quota.subjectName[0]}
          </div>
              <div className="flex flex-col">
                <span className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                  {quota.subjectName}
                  {quota.subjectType === 'user' ? <User className="w-3 h-3 text-gray-400" /> : <Users className="w-3 h-3 text-gray-400" />}
                </span>
                <span className="text-xs text-gray-500 mt-0.5">ID: {quota.id.slice(0, 8)}</span>
              </div>
        </div>
      </td>
      <td className="px-8 py-6">
         <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 bg-gray-100 dark:bg-slate-900 rounded-md text-[10px] font-medium text-gray-600 uppercase">{quota.period}ly</span>
                <span className="px-2 py-0.5 bg-gray-100 dark:bg-slate-900 rounded-md text-[10px] font-medium text-gray-600 uppercase">{quota.limitUnit}</span>
              </div>
              <div className="flex items-center gap-3 text-sm font-semibold text-gray-900 dark:text-white">
                {formatValue(quota.limitValue)} {quota.limitUnit}
                <span className="text-gray-400 font-normal">on</span>
                <span className="text-indigo-600 dark:text-indigo-400">{quota.model === 'all' ? 'Universal' : quota.model}</span>
              </div>
              <div className="flex items-center gap-4 text-[10px] font-medium uppercase text-gray-500">
                <span className={getActionColor(quota.action)}>{quota.action} mode</span>
                <span>Priority: {quota.priority}</span>
              </div>
         </div>
      </td>
      <td className="px-8 py-6">
        <div className="flex flex-col gap-3 min-w-[200px]">
          <div className="space-y-1.5">
            <div className="flex justify-between text-[10px] font-black uppercase tracking-widest">
              <div className="flex items-center gap-1.5">
                <Zap className={cn("w-3 h-3", usagePercent >= 90 ? 'text-red-500' : 'text-indigo-500')} />
                <span className="text-gray-900 dark:text-white">{formatValue(quota.usageValue)} processed</span>
              </div>
              <span className={cn(usagePercent >= 80 ? 'text-amber-500' : 'text-gray-400')}>{usagePercent}%</span>
            </div>
            <div className="w-full h-2 bg-gray-100 dark:bg-slate-900 rounded-full overflow-hidden p-0.5 border border-gray-100 dark:border-slate-800">
               <div
                  className={cn(
                    "h-full rounded-full transition-all duration-1000",
                    usagePercent >= 90 ? 'bg-red-500' : usagePercent >= 80 ? 'bg-amber-500' : 'bg-indigo-500'
                  )}
                  style={{ width: `${usagePercent}%` }}
               />
            </div>
          </div>
          <div className="flex items-center justify-between">
            <span className={`px-2 py-0.5 rounded-lg text-[9px] font-black uppercase tracking-widest border shadow-sm ${
              isOver ? 'bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 border-red-200' :
              isWarning ? 'bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-200' :
              'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-200'
            }`}>
              {quota.status}
            </span>
            <span className="text-[10px] font-black text-gray-400 uppercase">Cost: {Math.round(quota.usageCost).toLocaleString()} ₽</span>
          </div>
        </div>
      </td>
      <td className="px-8 py-6 text-right">
        <div className="flex items-center justify-end gap-1.5">
          <button
            type="button"
            onClick={() => onEdit(quota)}
            title="Редактировать"
            className="p-1.5 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-500/10 rounded-lg transition-colors"
          >
             <Edit className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={() => onDelete(quota)}
            title="Удалить"
            className="p-1.5 text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-lg transition-colors"
          >
             <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </td>
    </tr>
  );
};


function QuotaFormModal({
  initialType = 'team',
  editingQuota,
  onClose,
  onSuccess
}: {
  initialType?: 'team' | 'user';
  editingQuota?: Quota | null;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const { t, language } = useLanguage();
  const { selectedClusterId } = useCluster();

  const [loading, setLoading] = useState(false);
  const [teams, setTeams] = useState<Team[]>([]);
  const [users, setUsers] = useState<AIUser[]>([]);
  const [models, setModels] = useState<ModelRate[]>([]);

  const [formData, setFormData] = useState({
    subjectType: editingQuota ? editingQuota.subjectType : initialType,
    subjectId: editingQuota ? editingQuota.subjectId : '',
    model: editingQuota ? editingQuota.model : 'all',
    limitValue: editingQuota ? editingQuota.limitValue : 1000000,
    limitUnit: editingQuota ? editingQuota.limitUnit : ('tokens' as 'tokens' | 'requests'),
    period: editingQuota ? editingQuota.period : ('month' as 'hour' | 'day' | 'month'),
    action: editingQuota ? editingQuota.action : ('block' as 'block' | 'throttle' | 'warn'),
    priority: editingQuota ? editingQuota.priority : 5,
  });

  useEffect(() => {
    async function fetchData() {
      const [tData, uData, mData] = await Promise.all([
        getTeams(),
        getUsers(),
        getModelRates()
      ]);
      setTeams(tData);
      setUsers(uData);
      setModels(mData);

      if (!editingQuota) {
        if (initialType === 'team' && tData.length > 0) setFormData(prev => ({ ...prev, subjectId: tData[0].id }));
        if (initialType === 'user' && uData.length > 0) setFormData(prev => ({ ...prev, subjectId: uData[0].id }));
      }
    }
    fetchData();
  }, [initialType, editingQuota]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      const subject = formData.subjectType === 'team'
        ? teams.find(t => t.id === formData.subjectId)
        : users.find(u => u.id === formData.subjectId);

      if (editingQuota) {
        await updateQuota(editingQuota.id, {
          ...formData,
          subjectName: subject?.name || editingQuota.subjectName,
          clusterId: selectedClusterId || 'global'
        });
      } else {
        await createQuota({
          ...formData,
          subjectName: subject?.name || 'Unknown',
          clusterId: selectedClusterId || 'global'
        });
      }
      onSuccess();
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        className="absolute inset-0 bg-slate-950/80 backdrop-blur-md"
      />

      <motion.div
        initial={{ scale: 0.95, opacity: 0, y: 20 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: 0.95, opacity: 0, y: 20 }}
        className="w-full max-w-2xl bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl shadow-2xl relative overflow-hidden flex flex-col max-h-[92vh]"
      >
        <div className="p-6 border-b border-gray-100 dark:border-slate-800/60 flex items-center justify-between">
           <div className="flex items-center gap-3">
              <div className="p-2.5 bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 rounded-xl animate-pulse">
                 <ShieldCheck className="w-5 h-5" />
              </div>
              <div>
                 <h2 className="text-lg font-bold text-gray-900 dark:text-white">
                    {editingQuota ? (language === 'ru' ? 'Редактировать квоту' : 'Edit Quota') : t('newQuota')}
                 </h2>
                 <p className="text-xs text-gray-500 mt-1">Configure governance policy and rate limits</p>
              </div>
           </div>
           <button onClick={onClose} className="p-2 rounded-lg bg-gray-55/60 dark:bg-slate-900 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors">
              <X className="w-5 h-5 text-gray-400" />
           </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-5 overflow-y-auto custom-scrollbar">
            {/* Unified Target Selection */}
            <div className="space-y-1.5">
               <label className="text-[10px] font-bold text-gray-400 dark:text-slate-400 uppercase tracking-wider">
                  Target (Team or User)
               </label>
               <select
                  value={`${formData.subjectType}:${formData.subjectId}`}
                  disabled={!!editingQuota}
                  onChange={(e) => {
                     const [type, id] = e.target.value.split(':');
                     setFormData({
                        ...formData,
                        subjectType: type as 'team' | 'user',
                        subjectId: id
                     });
                  }}
                  className="w-full rounded-lg border border-gray-250 dark:border-slate-850 bg-white dark:bg-slate-900 px-3 py-2 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white disabled:opacity-60 disabled:cursor-not-allowed"
               >
                  {editingQuota ? (
                    <option value={`${formData.subjectType}:${formData.subjectId}`}>
                      {editingQuota.subjectName} ({formData.subjectType === 'user' ? 'User' : 'Team'})
                    </option>
                  ) : (
                    <>
                      <optgroup label="Teams">
                         {teams.map(t => (
                            <option key={t.id} value={`team:${t.id}`}>{t.name} (Team)</option>
                         ))}
                      </optgroup>
                      <optgroup label="Users">
                         {users.map(u => (
                            <option key={u.id} value={`user:${u.id}`}>{u.name} (User)</option>
                         ))}
                      </optgroup>
                    </>
                  )}
               </select>
            </div>

           {/* Model Restriction */}
           <div className="space-y-1.5">
              <label className="text-[10px] font-bold text-gray-400 dark:text-slate-400 uppercase tracking-wider">
                 {t('allowedModels')}
              </label>
              <select
                 value={formData.model}
                 onChange={(e) => setFormData({ ...formData, model: e.target.value })}
                 className="w-full rounded-lg border border-gray-250 dark:border-slate-800 bg-white dark:bg-slate-900 px-3 py-1.5 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white"
              >
                 <option value="all">{t('allModels')}</option>
                 {models.map(m => <option key={m.modelName} value={m.modelName}>{m.modelName}</option>)}
              </select>
           </div>

           {/* Limit & Period */}
           <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div className="space-y-1.5">
                 <label className="text-[10px] font-bold text-gray-400 dark:text-slate-400 uppercase tracking-wider">
                    {t('limit')}
                 </label>
                 <div className="flex gap-2">
                    <input
                       type="number"
                       value={formData.limitValue}
                       onChange={(e) => setFormData({ ...formData, limitValue: Number(e.target.value) })}
                       className="flex-1 rounded-lg border border-gray-250 dark:border-slate-800 bg-white dark:bg-slate-900 px-3 py-1.5 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white"
                    />
                    <select
                       value={formData.limitUnit}
                       onChange={(e) => setFormData({ ...formData, limitUnit: e.target.value as any })}
                       className="w-28 rounded-lg border border-gray-255 dark:border-slate-800 bg-white dark:bg-slate-900 px-3 py-1.5 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white"
                    >
                       <option value="tokens">{t('tokens')}</option>
                       <option value="requests">{t('requests')}</option>
                    </select>
                 </div>
              </div>

              <div className="space-y-1.5">
                 <label className="text-[10px] font-bold text-gray-400 dark:text-slate-400 uppercase tracking-wider">
                    {t('period')}
                 </label>
                 <select
                    value={formData.period}
                    onChange={(e) => setFormData({ ...formData, period: e.target.value as any })}
                    className="w-full rounded-lg border border-gray-250 dark:border-slate-800 bg-white dark:bg-slate-900 px-3 py-1.5 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white"
                 >
                    <option value="hour">{t('hour')}</option>
                    <option value="day">{t('day')}</option>
                    <option value="month">{t('month')}</option>
                 </select>
              </div>
           </div>

           {/* Action & Priority */}
           <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div className="space-y-1.5">
                 <label className="text-[10px] font-bold text-gray-400 dark:text-slate-400 uppercase tracking-wider">
                    {t('actionOnExceed')}
                 </label>
                 <select
                    value={formData.action}
                    onChange={(e) => setFormData({ ...formData, action: e.target.value as any })}
                    className="w-full rounded-lg border border-gray-250 dark:border-slate-800 bg-white dark:bg-slate-900 px-3 py-1.5 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white"
                 >
                    <option value="block">{t('block')}</option>
                    <option value="throttle">{t('throttle')}</option>
                    <option value="warn">{t('warn')}</option>
                 </select>
              </div>

              <div className="space-y-1.5">
                 <label className="text-[10px] font-bold text-gray-400 dark:text-slate-400 uppercase tracking-wider">
                    {t('priority')}
                 </label>
                 <input
                    type="number"
                    min="1"
                    max="100"
                    value={formData.priority}
                    onChange={(e) => setFormData({ ...formData, priority: Number(e.target.value) })}
                    className="w-full rounded-lg border border-gray-250 dark:border-slate-800 bg-white dark:bg-slate-900 px-3 py-1.5 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white"
                 />
              </div>
           </div>

           <div className="flex gap-3 pt-5 border-t border-gray-100 dark:border-slate-850">
              <button
                 type="button"
                 onClick={onClose}
                 className="flex-1 px-4 py-2 border border-gray-300 dark:border-slate-700 rounded-lg text-xs font-bold hover:bg-gray-50 dark:hover:bg-slate-950 transition-colors dark:text-slate-300 uppercase tracking-wider"
              >
                 {t('cancel')}
              </button>
              <button
                 type="submit"
                 disabled={loading}
                 className="flex-[1.5] bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-xs font-bold transition-all disabled:opacity-50 flex items-center justify-center gap-2 uppercase tracking-wider"
              >
                 {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
                 {editingQuota ? (language === 'ru' ? 'Сохранить' : 'Save') : t('create')}
               </button>
           </div>
        </form>
      </motion.div>
    </div>
  );
}
