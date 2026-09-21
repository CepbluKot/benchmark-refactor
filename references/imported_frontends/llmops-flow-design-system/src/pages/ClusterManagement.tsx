import React, { useState, useEffect } from 'react';
import {
  Hexagon, Server, Cpu, Database,
  Activity, Cloud, Zap, Shield,
  Plus, Search, Filter, ArrowUpRight,
  ChevronDown, AlertTriangle, CheckCircle2, Clock
} from 'lucide-react';
import { useCluster, Cluster } from '../context/ClusterContext';
import { useLanguage } from '../context/LanguageContext';
import { getNodes, ClusterNode, getEnergyHistory, EnergyTimeSeries } from '../api/mock';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, BarChart, Bar
} from 'recharts';
import { cn } from '../lib/utils';
import { motion } from 'motion/react';

const metricConfigs: Record<string, { label: string; color: string; unit: string }> = {
  power_watts: { label: 'Power Consumed', color: '#5794f2', unit: ' W' },
  cost: { label: 'Electricity Cost', color: '#73bf69', unit: ' ₽' },
  cpu_percent: { label: 'CPU Utilization', color: '#f59e0b', unit: '%' },
  gpu_percent: { label: 'GPU Utilization', color: '#8b5cf6', unit: '%' },
  ram_percent: { label: 'RAM Utilization', color: '#ec4899', unit: '%' },
};

// Custom Tooltip with precise metrics formatting
const PowerMetricsTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-[#111217] border border-[#2c323d] rounded-lg p-3.5 shadow-xl space-y-2 text-xs font-mono select-none pointer-events-none min-w-[200px]">
        <div className="text-[#9fa7b3] border-b border-[#2c323d] pb-1.5 mb-1.5 font-bold flex items-center justify-between">
          <span>{new Date(label).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
          <span className="text-[9px] bg-indigo-500/20 text-indigo-300 px-1.5 py-0.5 rounded tracking-widest uppercase">realtime</span>
        </div>
        <div className="space-y-1.5">
          {payload.map((item: any, idx: number) => {
            const config = metricConfigs[item.dataKey] || { label: item.name, color: item.stroke || '#5794f2', unit: '' };
            return (
              <div key={idx} className="flex items-center justify-between gap-5">
                <div className="flex items-center gap-2 text-slate-200">
                  <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: config.color }} />
                  <span className="text-[11px] font-medium text-slate-300">{config.label}</span>
                </div>
                <span className="font-bold text-white tabular-nums">
                  {typeof item.value === 'number'
                    ? `${item.value.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 1 })}${config.unit}`
                    : item.value}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    );
  }
  return null;
};

export function ClusterManagement() {
  const { t, language } = useLanguage();
  const { clusters, selectedClusterId } = useCluster();
  const [nodes, setNodes] = useState<ClusterNode[]>([]);
  const [history, setHistory] = useState<EnergyTimeSeries[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeMetric, setActiveMetric] = useState<'power_watts' | 'cost' | 'cpu_percent' | 'gpu_percent' | 'ram_percent'>('power_watts');

  const metricOptions = [
    { id: 'power_watts', label: language === 'ru' ? 'Мощность (Вт)' : 'Power (W)', heading: language === 'ru' ? 'Динамика нагрузки' : 'Load Dynamics', query: 'metric: aggregate_compute_power_watts', color: '#5794f2', unit: 'W' },
    { id: 'cost', label: language === 'ru' ? 'Затраты (₽)' : 'Electricity Cost (₽)', heading: language === 'ru' ? 'Затраты на питание' : 'Electricity Expenses', query: 'query: sum(electricity_expense_rub)', color: '#73bf69', unit: '₽' },
    { id: 'cpu_percent', label: language === 'ru' ? 'Загрузка CPU (%)' : 'CPU Utilization (%)', heading: language === 'ru' ? 'Загрузка CPU' : 'CPU Utilization', query: 'metric: cluster_node_cpu_utilization_ratio', color: '#f59e0b', unit: '%' },
    { id: 'gpu_percent', label: language === 'ru' ? 'Загрузка GPU (%)' : 'GPU Utilization (%)', heading: language === 'ru' ? 'Загрузка GPU' : 'GPU Utilization', query: 'metric: cluster_node_gpu_utilization_ratio', color: '#8b5cf6', unit: '%' },
    { id: 'ram_percent', label: language === 'ru' ? 'Загрузка RAM (%)' : 'RAM Utilization (%)', heading: language === 'ru' ? 'Загрузка RAM' : 'RAM Utilization', query: 'metric: cluster_node_ram_utilization_bytes', color: '#ec4899', unit: '%' },
  ] as const;

  const currentMetric = metricOptions.find(m => m.id === activeMetric) || metricOptions[0];

  const filteredClusters = selectedClusterId === 'all'
    ? clusters.filter(c => c.id !== 'all')
    : clusters.filter(c => c.id === selectedClusterId);

  useEffect(() => {
    async function load() {
      setLoading(true);
      const [n, h] = await Promise.all([
        getNodes(selectedClusterId),
        getEnergyHistory('24h', selectedClusterId)
      ]);
      setNodes(n);
      setHistory(h);
      setLoading(false);
    }
    load();
  }, [selectedClusterId]);

  const filteredNodes = nodes.filter(n =>
    n.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    n.clusterId.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="space-y-10 max-w-7xl mx-auto pb-20">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          {t('infrastructure')}
        </h1>
        <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">
          {selectedClusterId === 'all' ? 'Global Fleet Status' : `Cluster Context: ${selectedClusterId}`}
        </p>
      </div>

      {/* Cluster Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filteredClusters.map(cluster => (
          <ClusterCard key={cluster.id} cluster={cluster} />
        ))}
      </div>

      {/* Resource Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-[#111217] border border-[#2c323d] rounded-2xl p-6 shadow-lg">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8 border-b border-[#2c323d] pb-4">
            <div className="flex items-center gap-3">
              <div className="p-2.5 bg-indigo-500/10 text-indigo-400 rounded-lg">
                <Activity className="w-4 h-4 text-indigo-400 animate-pulse" />
              </div>
              <div>
                <h3 className="text-sm font-bold uppercase tracking-wider text-slate-200">{currentMetric.heading}</h3>
                <p className="text-xs text-slate-400 font-mono">{currentMetric.query}</p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <select
                value={activeMetric}
                onChange={(e) => setActiveMetric(e.target.value as any)}
                className="bg-[#181b1f] border border-[#2c323d] text-xs font-mono text-[#9fa7b3] rounded-lg px-3 py-1.5 outline-none focus:border-[#5794f2] cursor-pointer"
              >
                {metricOptions.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {opt.label}
                  </option>
                ))}
              </select>

              <div className="flex gap-2 font-mono text-[10px]">
                <button type="button" className="px-2.5 py-1 bg-[#181b1f] hover:bg-[#22252b] text-[#9fa7b3] rounded-lg border border-[#2c323d] transition-colors cursor-pointer">1H</button>
                <button type="button" className="px-2.5 py-1 bg-[#5794f2] text-white rounded-lg font-bold transition-colors cursor-pointer">24H</button>
                <button type="button" className="px-2.5 py-1 bg-[#181b1f] hover:bg-[#22252b] text-[#9fa7b3] rounded-lg border border-[#2c323d] transition-colors cursor-pointer">7D</button>
              </div>
            </div>
          </div>

          <div className="h-[300px] w-full bg-[#181b1f] rounded-xl border border-[#2c323d] p-4">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={history} margin={{ top: 10, right: 10, left: -15, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorUsage" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={currentMetric.color} stopOpacity={0.3}/>
                    <stop offset="95%" stopColor={currentMetric.color} stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="1 5" stroke="#2c323d" vertical={true} />
                <XAxis
                  dataKey="timestamp"
                  axisLine={true}
                  tickLine={true}
                  stroke="#9fa7b3"
                  tick={{ fontSize: 9, fontFamily: 'monospace', fill: '#9fa7b3' }}
                  tickFormatter={(val) => new Date(val).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                />
                <YAxis
                   axisLine={true}
                   tickLine={true}
                   stroke="#9fa7b3"
                   tick={{ fontSize: 9, fontFamily: 'monospace', fill: '#9fa7b3' }}
                   tickFormatter={(val) => `${val}${currentMetric.unit}`}
                />
                <Tooltip content={<PowerMetricsTooltip />} cursor={{ stroke: currentMetric.color, strokeWidth: 1, strokeDasharray: '2 2' }} />
                <Area type="monotone" dataKey={activeMetric} stroke={currentMetric.color} strokeWidth={2} fillOpacity={1} fill="url(#colorUsage)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="space-y-6">
           <ResourceMeter label={t('gpuUtilization')} value={filteredClusters.reduce((acc, c) => acc + c.gpuUsage, 0) / filteredClusters.length} color="indigo" />
           <ResourceMeter label={t('ramUtilization')} value={filteredClusters.reduce((acc, c) => acc + c.ramUsage, 0) / filteredClusters.length} color="emerald" />
           <ResourceMeter label={t('cpuUtilization')} value={filteredClusters.reduce((acc, c) => acc + c.cpuUsage, 0) / filteredClusters.length} color="amber" />

        </div>
      </div>
    </div>
  );
}

function ClusterCard({ cluster }: any) {
  const { t } = useLanguage();
  const isOnline = cluster.status === 'online';
  const isDegraded = cluster.status === 'degraded';

  return (
    <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl overflow-hidden shadow-sm hover:shadow-md hover:-translate-y-1 transition-all duration-300 group">
      <div className="p-5 pb-0">
        <div className="flex items-start justify-between">
          <div className="w-12 h-12 rounded-xl bg-indigo-50 dark:bg-indigo-500/10 flex items-center justify-center text-indigo-600 dark:text-indigo-400 group-hover:scale-105 transition-transform">
             <Hexagon className="w-6 h-6" />
          </div>
          <div className={cn(
            "flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[10px] font-semibold uppercase tracking-wider",
            isOnline ? "bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 border-emerald-200 dark:border-emerald-500/20" :
            isDegraded ? "bg-amber-50 dark:bg-amber-500/10 text-amber-600 border-amber-200 dark:border-amber-500/20" :
            "bg-red-50 dark:bg-red-500/10 text-red-600 border-red-200 dark:border-red-500/20"
          )}>
            <div className={cn("w-1.5 h-1.5 rounded-full", isOnline ? "bg-emerald-500 animate-pulse" : isDegraded ? "bg-amber-500" : "bg-red-500")} />
            {t(cluster.status)}
          </div>
        </div>

        <div className="mt-4">
          <h3 className="text-xl font-bold text-gray-900 dark:text-white group-hover:text-indigo-600 transition-colors">{cluster.name}</h3>
          <p className="text-sm text-gray-500 dark:text-slate-400 mt-0.5">{cluster.region} • {cluster.provider}</p>
        </div>
      </div>

      <div className="p-5 pt-6 space-y-5">
        <div className="grid grid-cols-2 gap-4">
          <div className="flex flex-col">
             <span className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">{t('nodes')}</span>
             <span className="text-lg font-bold text-gray-900 dark:text-white">{cluster.nodeCount} Ready</span>
          </div>
          <div className="flex flex-col">
             <span className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Type</span>
             <span className="text-lg font-bold text-gray-900 dark:text-white">{cluster.type}</span>
          </div>
        </div>

        <div className="flex items-center gap-2 pt-4 border-t border-gray-100 dark:border-slate-800 text-xs font-medium text-gray-500 uppercase tracking-wider">
           <Clock className="w-3.5 h-3.5" />
           {t('heartbeat')}: {cluster.status === 'unreachable' ? '2 days ago' : new Date(cluster.lastHeartbeat).toLocaleTimeString()}
        </div>
      </div>
    </div>
  );
}

function ResourceMeter({ label, value, color }: { label: string, value: number, color: 'indigo' | 'emerald' | 'amber' }) {
  const colors = {
    indigo: 'bg-indigo-500',
    emerald: 'bg-emerald-500',
    amber: 'bg-amber-500'
  };

  return (
    <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
      <div className="flex justify-between items-end mb-2.5">
        <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">{label}</span>
        <span className="text-2xl font-bold text-gray-900 dark:text-white">{Math.round(value)}%</span>
      </div>
      <div className="w-full h-1.5 bg-gray-100 dark:bg-slate-900 rounded-full overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${value}%` }}
          transition={{ duration: 1.5, ease: "easeOut" }}
          className={cn("h-full", colors[color])}
        />
      </div>
    </div>
  );
}

function NodeCard({ node }: any) {
  const { t } = useLanguage();

  const getProgressColor = (percent: number) => {
    if (percent > 90) return 'bg-red-500';
    if (percent > 75) return 'bg-amber-500';
    return 'bg-indigo-500';
  };

  const cpuPercent = Math.round((node.used.cpu / node.allocatable.cpu) * 100);
  const ramPercent = Math.round((node.used.ram / node.allocatable.ram) * 100);
  const gpuPercent = node.type === 'gpu' ? Math.round((node.used.gpu / node.allocatable.gpu) * 100) : 0;

  return (
    <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-xl p-5 shadow-sm hover:border-indigo-500 transition-colors group">
      <div className="flex items-start justify-between mb-8">
        <div className="flex items-center gap-3">
           <div className={cn(
             "p-2.5 rounded-xl",
             node.type === 'gpu' ? "bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600" : "bg-amber-50 dark:bg-amber-500/10 text-amber-600"
           )}>
             {node.type === 'gpu' ? <Zap className="w-5 h-5" /> : <Cpu className="w-5 h-5" />}
           </div>
           <div>
             <h4 className="text-lg font-bold text-gray-900 dark:text-white tracking-tight">{node.name}</h4>
             <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">{node.clusterId}</span>
           </div>
        </div>
        {!node.isDeployable && (
          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-500/20 rounded-full text-[10px] font-bold uppercase tracking-widest">
            <Shield className="w-3.5 h-3.5" />
            Locked
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 mb-8">
         <div className="space-y-1.5">
            <div className="flex justify-between text-[10px] font-bold uppercase tracking-widest text-gray-500">
               <span>CPU</span>
               <span>{cpuPercent}%</span>
            </div>
            <div className="w-full h-1 bg-gray-100 dark:bg-slate-900 rounded-full overflow-hidden">
               <div className={cn("h-full", getProgressColor(cpuPercent))} style={{ width: `${cpuPercent}%` }} />
            </div>
            <div className="text-[10px] font-bold text-gray-400">{node.used.cpu} / {node.allocatable.cpu} cores</div>
         </div>
         <div className="space-y-1.5">
            <div className="flex justify-between text-[10px] font-bold uppercase tracking-widest text-gray-500">
               <span>RAM</span>
               <span>{ramPercent}%</span>
            </div>
            <div className="w-full h-1 bg-gray-100 dark:bg-slate-900 rounded-full overflow-hidden">
               <div className={cn("h-full", getProgressColor(ramPercent))} style={{ width: `${ramPercent}%` }} />
            </div>
            <div className="text-[10px] font-bold text-gray-400">{node.used.ram} / {node.allocatable.ram} GB</div>
         </div>
         {node.type === 'gpu' && (
           <div className="space-y-1.5">
              <div className="flex justify-between text-[10px] font-bold uppercase tracking-widest text-gray-500">
                 <span>GPU</span>
                 <span>{gpuPercent}%</span>
              </div>
              <div className="w-full h-1 bg-gray-100 dark:bg-slate-900 rounded-full overflow-hidden">
                 <div className={cn("h-full", getProgressColor(gpuPercent))} style={{ width: `${gpuPercent}%` }} />
              </div>
              <div className="text-[10px] font-bold text-indigo-500">{node.used.gpu} / {node.allocatable.gpu} cards</div>
           </div>
         )}
      </div>

      <div className="pt-6 border-t border-gray-100 dark:border-slate-800 flex items-center justify-between">
         <div className="flex flex-col">
            <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1.5">Active Deployments</span>
            <div className="flex -space-x-1.5">
               {node.deployments.map((d, i) => (
                 <div key={d} className="w-5 h-5 rounded-full bg-indigo-600 border-2 border-white dark:border-slate-950 flex items-center justify-center text-[7px] text-white font-bold uppercase">D{i+1}</div>
               ))}
               {node.deployments.length === 0 && <span className="text-xs font-medium text-gray-300 uppercase">None</span>}
            </div>
         </div>
         <button
           disabled={!node.isDeployable}
           className={cn(
            "px-4 py-2 rounded-lg text-xs font-semibold uppercase tracking-wider transition-all shadow-sm",
            node.isDeployable
              ? "bg-indigo-600 hover:bg-indigo-700 text-white"
              : "bg-gray-100 dark:bg-slate-900 text-gray-400 cursor-not-allowed"
           )}
         >
           {t('deployHere')}
         </button>
      </div>
    </div>
  );
}
