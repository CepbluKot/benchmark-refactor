import React, { useState, useEffect } from 'react';
import {
  Activity,
  Clock,
  DollarSign,
  ArrowUpRight,
  ArrowDownRight,
  Zap
} from 'lucide-react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer
} from 'recharts';
import { useCluster } from '../context/ClusterContext';
import { useLanguage } from '../context/LanguageContext';
import { getCostSummary, getEnergyHistory } from '../api/mock';

const metricsData = [
  { time: '10:00', cpu: 45, mem: 60 },
  { time: '10:05', cpu: 50, mem: 62 },
  { time: '10:10', cpu: 80, mem: 65 },
  { time: '10:15', cpu: 75, mem: 68 },
  { time: '10:20', cpu: 40, mem: 61 },
  { time: '10:25', cpu: 42, mem: 60 },
  { time: '10:30', cpu: 90, mem: 75 },
  { time: '10:35', cpu: 85, mem: 74 },
];

// Custom Tooltip with precise metrics styling
const MetricsChartTooltip = ({ active, payload, label }: any) => {
  const { language } = useLanguage();
  if (active && payload && payload.length) {
    return (
      <div className="bg-white dark:bg-[#111217] border border-gray-200 dark:border-[#2c323d] rounded-lg p-3.5 shadow-xl space-y-2 text-xs font-mono select-none pointer-events-none min-w-[180px]">
        <div className="text-gray-500 dark:text-[#9fa7b3] border-b border-gray-100 dark:border-[#2c323d] pb-1.5 mb-1.5 font-bold flex items-center justify-between">
          <span>{label}</span>
          <span className="text-[9px] bg-gray-100 dark:bg-[#2c323d] px-1.5 py-0.5 rounded text-gray-600 dark:text-white tracking-widest uppercase">
            {language === 'ru' ? 'метрики' : 'metrics'}
          </span>
        </div>
        <div className="space-y-1.5">
          {payload.map((item: any, idx: number) => (
            <div key={idx} className="flex items-center justify-between gap-5">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: item.color || item.stroke }} />
                <span className="text-[11px] font-medium text-gray-600 dark:text-slate-300">
                  {item.name}
                </span>
              </div>
              <span className="font-bold text-gray-900 dark:text-white tabular-nums">
                {typeof item.value === 'number' ? `${item.value}%` : item.value}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  }
  return null;
};

export function Dashboard() {
  const { selectedClusterId } = useCluster();
  const { t, language } = useLanguage();
  const [summary, setSummary] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      const [s, h] = await Promise.all([
        getCostSummary(selectedClusterId),
        getEnergyHistory('24h', selectedClusterId)
      ]);
      setSummary(s);
      setHistory(h);
      setLoading(false);
    }
    load();
  }, [selectedClusterId]);

  if (loading) {
    return <div className="flex items-center justify-center h-64"><Zap className="w-8 h-8 animate-pulse text-indigo-500" /></div>;
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{t('metricsDashboard')}</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">{t('metricsSub')}</p>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title={t('latency')}
          value={language === 'ru' ? '245 мс' : '245ms'}
          change={language === 'ru' ? '-15 мс к вчера' : '-15ms vs yesterday'}
          trend="down"
          icon={Clock}
          color="emerald"
        />
        <StatCard
          title={t('throughput')}
          value={language === 'ru' ? '4 250 запр/с' : '4,250 req/s'}
          change={language === 'ru' ? '+12.5% к вчера' : '+12.5% vs yesterday'}
          trend="up"
          icon={Zap}
          color="blue"
        />
        <StatCard
          title={t('uptime')}
          value="99.99%"
          change={language === 'ru' ? 'Стабильно' : 'Stable'}
          trend="neutral"
          icon={Activity}
          color="indigo"
        />
        <StatCard
          title={t('costLast24h')}
          value={summary ? `${summary.totalCost.toLocaleString()} ₽` : '...'}
          change={language === 'ru' ? '+5% к вчера' : '+5% vs yesterday'}
          trend="up"
          icon={DollarSign}
          color="amber"
        />
      </div>

      {/* Metrics panel with technical background and grid */}
      <div className="bg-white dark:bg-[#111217] border border-gray-200 dark:border-[#2c323d] rounded-2xl p-6 shadow-sm dark:shadow-outline flex flex-col h-[520px]">
        <div className="flex items-center justify-between mb-6 border-b border-gray-100 dark:border-[#2c323d] pb-4">
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 bg-[#f97316] rounded-full" />
            <h2 className="text-sm font-bold uppercase tracking-wider text-gray-700 dark:text-slate-200">{t('metricsOverview')}</h2>
          </div>
          <select className="bg-gray-50 dark:bg-[#181b1f] border border-gray-200 dark:border-[#2c323d] text-xs font-mono text-gray-600 dark:text-[#9fa7b3] rounded-lg px-3 py-1.5 outline-none focus:border-indigo-500 dark:focus:border-[#5794f2] cursor-pointer">
            <option>{language === 'ru' ? 'Общий обзор LLM' : 'LLM Performance Overview'}</option>
            <option>{language === 'ru' ? 'Ресурсы кластера' : 'Cluster Resources'}</option>
            <option>{language === 'ru' ? 'Маршрутизация трафика' : 'Traffic Router'}</option>
          </select>
        </div>

        <div className="flex-1 rounded-xl bg-gray-50/30 dark:bg-[#181b1f] border border-gray-150 dark:border-[#2c323d] p-5 relative overflow-hidden flex flex-col justify-between">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-gray-650 dark:text-[#dae1e7] text-[11px] font-mono uppercase tracking-wider">
              {language === 'ru' ? 'Метрика: утилизация GPU/CPU и памяти' : 'Metric: kernel_cpu_memory_utilization ratio'}
            </h3>
            <div className="flex items-center gap-4 text-[10px] font-mono text-gray-500 dark:text-[#9fa7b3]">
              <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-[#5794f2]" /> {language === 'ru' ? 'CPU ср' : 'CPU avg'}: 60.1%</span>
              <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-[#73bf69]" /> {language === 'ru' ? 'ОЗУ ср' : 'MEM avg'}: 65.5%</span>
            </div>
          </div>

          <div className="h-[350px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={metricsData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="1 5" vertical={true} />
                <XAxis
                  dataKey="time"
                  stroke="var(--chart-text)"
                  fontSize={10}
                  fontFamily="monospace"
                  tickLine={true}
                  axisLine={true}
                  dy={5}
                />
                <YAxis
                  stroke="var(--chart-text)"
                  fontSize={10}
                  fontFamily="monospace"
                  tickLine={true}
                  axisLine={true}
                  tickFormatter={(v) => `${v}%`}
                />
                <Tooltip content={<MetricsChartTooltip />} cursor={{ stroke: '#5794f2', strokeWidth: 1.5, strokeDasharray: '2 2' }} />
                <Line
                  type="monotone"
                  dataKey="cpu"
                  name={language === 'ru' ? 'Использование CPU' : 'CPU Utilization'}
                  stroke="#5794f2"
                  strokeWidth={2}
                  dot={{ r: 2, strokeWidth: 1, fill: 'var(--chart-tooltip-bg)' }}
                  activeDot={{ r: 4, strokeWidth: 0 }}
                />
                <Line
                  type="monotone"
                  dataKey="mem"
                  name={language === 'ru' ? 'Использование ОЗУ' : 'Memory Resident'}
                  stroke="#73bf69"
                  strokeWidth={2}
                  dot={{ r: 2, strokeWidth: 1, fill: 'var(--chart-tooltip-bg)' }}
                  activeDot={{ r: 4, strokeWidth: 0 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({ title, value, change, trend, icon: Icon, color }: any) {
  const colorClasses = {
    blue: 'bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400',
    indigo: 'bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400',
    emerald: 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
    amber: 'bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400',
  };

  return (
    <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl p-6 shadow-sm hover:shadow-md transition-all duration-300">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-gray-500 dark:text-slate-400">{title}</h3>
        <div className={`p-2 rounded-lg ${colorClasses[color as keyof typeof colorClasses]}`}>
          <Icon className="w-5 h-5" />
        </div>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-bold text-gray-900 dark:text-white tabular-nums">{value}</span>
      </div>
      <div className="mt-2 flex items-center text-sm font-medium">
        {trend === 'up' && <ArrowUpRight className="w-4 h-4 text-emerald-500 mr-1" />}
        {trend === 'down' && <ArrowDownRight className="w-4 h-4 text-emerald-500 mr-1" />}
        {trend === 'neutral' && <span className="w-4 h-4 text-gray-400 mr-1">-</span>}
        <span className={trend === 'up' || trend === 'down' ? 'text-emerald-600 dark:text-emerald-400' : 'text-gray-500 dark:text-slate-400'}>
          {change}
        </span>
      </div>
    </div>
  );
}
