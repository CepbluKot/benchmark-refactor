import React, { useState, useEffect } from "react";
import {
  DollarSign,
  TrendingUp,
  Activity,
  BarChart3,
  Calendar,
  Filter,
  Download,
  Loader2,
  AlertTriangle,
  Zap,
  Settings2,
  Save,
  Info,
  ArrowUpRight,
  TrendingDown,
  ChevronDown,
  Layers,
  Globe,
  Users,
  Search,
  Cpu,
} from "lucide-react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Legend,
  Cell,
  PieChart,
  Pie,
} from "recharts";
import {
  getCostHistory,
  getModelRates,
  getPlatformRates,
  updateModelRate,
  updateElectricityPrice,
  CostEntry,
  ModelRate,
  PlatformRates,
} from "../api/mock";

import { useCluster } from "../context/ClusterContext";
import { useLanguage } from "../context/LanguageContext";
import { cn } from "../lib/utils";
import { motion } from "motion/react";

type TimePeriod = "24h" | "7d" | "30d";
type GroupBy = "model" | "team" | "user" | "cluster" | "deployment";

// Custom Tooltip with precise metrics and automatic total sum calculations
const CostsMetricsTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    const formattedLabel = label ? new Date(label).toLocaleDateString([], {
      year: "numeric",
      month: "short",
      day: "numeric",
    }) : "";

    return (
      <div className="bg-[#111217] border border-[#2c323d] rounded-lg p-3.5 shadow-xl space-y-2 text-xs font-mono select-none pointer-events-none min-w-[210px]">
        <div className="text-[#9fa7b3] border-b border-[#2c323d] pb-1.5 mb-1.5 font-bold flex items-center justify-between">
          <span>{formattedLabel}</span>
          <span className="text-[8px] bg-emerald-500/20 text-emerald-300 px-1.5 py-0.5 rounded tracking-widest uppercase font-mono font-bold">billing</span>
        </div>
        <div className="space-y-1.5">
          {payload.map((item: any, idx: number) => (
            <div key={idx} className="flex items-center justify-between gap-5">
              <div className="flex items-center gap-2 text-slate-200">
                <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: item.color || item.stroke }} />
                <span className="text-[11px] text-slate-300 font-medium">{item.name}</span>
              </div>
              <span className="font-bold text-white tabular-nums">
                ₽{item.value ? item.value.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : 0}
              </span>
            </div>
          ))}
          {payload.length > 1 && (
            <div className="flex items-center justify-between border-t border-[#2c323d] pt-1.5 mt-1.5 text-[#9fa7b3] font-bold">
              <span>Total</span>
              <span className="text-[#5794f2] tabular-nums">
                ₽{payload.reduce((acc: number, item: any) => acc + (item.value || 0), 0).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
              </span>
            </div>
          )}
        </div>
      </div>
    );
  }
  return null;
};

export function Costs() {
  const { t } = useLanguage();
  const { selectedClusterId } = useCluster();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);

  const [period, setPeriod] = useState<TimePeriod>("7d");
  const [groupBy, setGroupBy] = useState<GroupBy>("model");
  const [chartMode, setChartMode] = useState<"combined" | "stacked">("stacked");

  const [costEntries, setCostEntries] = useState<CostEntry[]>([]);
  const [rates, setRates] = useState<ModelRate[]>([]);
  const [platformRates, setPlatformRates] = useState<PlatformRates | null>(
    null,
  );
  const [editingRates, setEditingRates] = useState<
    Record<string, { input: number; output: number; watts: number }>
  >({});
  const [elecPrice, setElecPrice] = useState(0);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [historyData, ratesData, platData] = await Promise.all([
        getCostHistory(period, selectedClusterId),
        getModelRates(),
        getPlatformRates(),
      ]);

      setCostEntries(historyData);
      setRates(ratesData);
      setPlatformRates(platData);
      setElecPrice(platData.electricityPriceKWh);

      const editObj: Record<
        string,
        { input: number; output: number; watts: number }
      > = {};
      ratesData.forEach((r) => {
        editObj[r.modelName] = {
          input: r.inputPricePer1M,
          output: r.outputPricePer1M,
          watts: r.wattsPerReplica,
        };
      });
      setEditingRates(editObj);
    } catch (err) {
      console.error("Failed to fetch cost data", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [selectedClusterId, period]);

  const handleUpdateElectricity = async () => {
    setSaving("electricity");
    await updateElectricityPrice(elecPrice);
    await fetchData();
    setSaving(null);
  };

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat("ru-RU", {
      style: "currency",
      currency: "RUB",
      maximumFractionDigits: 0,
    }).format(value);
  };

  const totalInference = costEntries.reduce(
    (sum, e) => sum + e.inferenceCost,
    0,
  );
  const totalElectricity = costEntries.reduce(
    (sum, e) => sum + e.electricityCost,
    0,
  );
  const totalCost = totalInference + totalElectricity;
  const totalTokens = costEntries.reduce(
    (sum, e) => sum + e.inputTokens + e.outputTokens,
    0,
  );
  const totalKWh =
    elecPrice > 0 ? totalElectricity / elecPrice : totalElectricity / 5.5;

  // Group chart data by day
  const dailyData = costEntries.reduce((acc: any, entry) => {
    const day = entry.timestamp.split("T")[0];
    if (!acc[day])
      acc[day] = { date: day, inference: 0, electricity: 0, total: 0 };
    acc[day].inference += entry.inferenceCost;
    acc[day].electricity += entry.electricityCost;
    acc[day].total += entry.inferenceCost + entry.electricityCost;
    return acc;
  }, {});

  const chartData = Object.values(dailyData).sort((a: any, b: any) =>
    a.date.localeCompare(b.date),
  );

  // Breakdown records
  const breakdownRaw = costEntries.reduce((acc: any, entry) => {
    let key = "";
    if (groupBy === "model") key = entry.modelName;
    else if (groupBy === "team") key = entry.team;
    else if (groupBy === "user") key = entry.ownerId;
    else if (groupBy === "cluster") key = entry.clusterId;
    else if (groupBy === "deployment")
      key = `${entry.team} / ${entry.deploymentId}`;

    if (!acc[key])
      acc[key] = {
        label: key,
        tokens: 0,
        inference: 0,
        electricity: 0,
        total: 0,
      };
    acc[key].tokens += entry.inputTokens + entry.outputTokens;
    acc[key].inference += entry.inferenceCost;
    acc[key].electricity += entry.electricityCost;
    acc[key].total += entry.inferenceCost + entry.electricityCost;
    return acc;
  }, {});

  const breakdown = Object.values(breakdownRaw).sort(
    (a: any, b: any) => b.total - a.total,
  );

  if (loading && costEntries.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh]">
        <Loader2 className="w-10 h-10 animate-spin text-indigo-500 mb-4" />
        <p className="text-gray-500 dark:text-slate-400 font-bold uppercase tracking-widest text-xs">
          Calculating Cost Metrics...
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-10 pb-20">
      {/* Header & Main Filters */}
      <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Costs & FinOps
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Hybrid Cloud Resource Economy
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex bg-gray-100 dark:bg-slate-900 p-1 rounded-lg border border-gray-200 dark:border-slate-800">
            {(["24h", "7d", "30d"] as TimePeriod[]).map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={cn(
                  "px-4 py-1.5 rounded-md text-xs font-medium transition-all",
                  period === p
                    ? "bg-indigo-600 text-white shadow-sm"
                    : "text-gray-500 hover:text-gray-900 dark:hover:text-white",
                )}
              >
                {p}
              </button>
            ))}
          </div>

          <button className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-lg text-xs font-semibold hover:border-indigo-500 transition-colors">
            <Download className="w-4 h-4" />
            CSV Export
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <CostStatCard
          title={t("totalCosts")}
          value={formatCurrency(totalCost)}
          change="+14%"
          trend="up"
          icon={DollarSign}
          color="indigo"
        />
        <CostStatCard
          title={t("inferenceCost")}
          value={formatCurrency(totalInference)}
          change="-2.1%"
          trend="down"
          icon={Zap}
          color="amber"
          label={t("inference")}
        />
        <CostStatCard
          title={t("electricityCost")}
          value={formatCurrency(totalElectricity)}
          subValue={`⚡ Consumed: ${totalKWh.toLocaleString("ru-RU", { maximumFractionDigits: 1 })} kWh`}
          change="+8.4%"
          trend="up"
          icon={Cpu}
          color="emerald"
          label={t("electricity")}
        />
      </div>

      {/* Main Chart */}
      <div className="bg-[#111217] border border-[#2c323d] rounded-2xl p-6 shadow-xl">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8 border-b border-[#2c323d] pb-4">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-indigo-500/10 text-indigo-400 rounded-lg">
              <BarChart3 className="w-4 h-4 text-indigo-400" />
            </div>
            <div>
              <h3 className="text-sm font-bold uppercase tracking-wider text-slate-200">
                {t("costsHistory")}
              </h3>
              <p className="text-xs text-slate-400 font-mono">
                query: sum_over_time(cluster_expenses_rub[24h])
              </p>
            </div>
          </div>

          <div className="flex bg-[#181b1f] p-1 rounded border border-[#2c323d]">
            <button
              onClick={() => setChartMode("combined")}
              className={cn(
                "px-3 py-1 rounded text-[10px] font-mono font-bold uppercase transition-all",
                chartMode === "combined"
                  ? "bg-[#5794f2] text-white shadow-sm"
                  : "text-[#9fa7b3] hover:text-white",
              )}
            >
              {t("combined")}
            </button>
            <button
              onClick={() => setChartMode("stacked")}
              className={cn(
                "px-3 py-1 rounded text-[10px] font-mono font-bold uppercase transition-all",
                chartMode === "stacked"
                  ? "bg-[#5794f2] text-white shadow-sm"
                  : "text-[#9fa7b3] hover:text-white",
              )}
            >
              {t("stacked")}
            </button>
          </div>
        </div>

        <div className="h-[350px] w-full bg-[#181b1f] rounded-lg border border-[#2c323d] p-4">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
              <defs>
                <linearGradient id="colorInf" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#5794f2" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#5794f2" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="colorElec" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#73bf69" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#73bf69" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="1 5"
                stroke="#2c323d"
                vertical={true}
              />
              <XAxis
                dataKey="date"
                axisLine={true}
                tickLine={true}
                stroke="#9fa7b3"
                tick={{ fontSize: 9, fontFamily: "monospace", fill: "#9fa7b3" }}
                tickFormatter={(val) =>
                  new Date(val).toLocaleDateString([], {
                    month: "short",
                    day: "numeric",
                  })
                }
              />
              <YAxis
                axisLine={true}
                tickLine={true}
                stroke="#9fa7b3"
                tick={{ fontSize: 9, fontFamily: "monospace", fill: "#9fa7b3" }}
                tickFormatter={(val) => `₽${val}`}
              />
              <Tooltip content={<CostsMetricsTooltip />} cursor={{ stroke: '#5794f2', strokeWidth: 1, strokeDasharray: '2 2' }} />
              <Legend
                iconType="circle"
                wrapperStyle={{ paddingTop: '15px', fontSize: '11px', fontFamily: 'monospace', color: '#9fa7b3' }}
              />
              <Area
                type="monotone"
                dataKey="inference"
                stackId={chartMode === "stacked" ? "1" : undefined}
                stroke="#5794f2"
                strokeWidth={2}
                fillOpacity={1}
                fill="url(#colorInf)"
                name={t("inference")}
              />
              <Area
                type="monotone"
                dataKey="electricity"
                stackId={chartMode === "stacked" ? "1" : undefined}
                stroke="#73bf69"
                strokeWidth={2}
                fillOpacity={1}
                fill="url(#colorElec)"
                name={t("electricity")}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Breakdown Table */}
      <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl overflow-hidden shadow-sm">
        <div className="p-6 border-b border-gray-100 dark:border-slate-900 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Cost Breakdown
            </h3>
            <p className="text-sm text-gray-500">
              Granular resource attribution
            </p>
          </div>

          <div className="flex bg-gray-100 dark:bg-slate-900 p-1 rounded-lg border border-gray-200 dark:border-slate-800">
            {(
              ["model", "team", "user", "cluster", "deployment"] as GroupBy[]
            ).map((g) => (
              <button
                key={g}
                onClick={() => setGroupBy(g)}
                className={cn(
                  "px-4 py-1.5 rounded-md text-xs font-medium transition-all",
                  groupBy === g
                    ? "bg-white dark:bg-slate-800 text-indigo-600 shadow-sm"
                    : "text-gray-500",
                )}
              >
                {t(`groupBy${g.charAt(0).toUpperCase() + g.slice(1)}`)}
              </button>
            ))}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-gray-50/50 dark:bg-slate-900/30 text-xs font-semibold uppercase tracking-wider text-gray-500">
                <th className="px-6 py-4">{groupBy.toUpperCase()}</th>
                <th className="px-6 py-4">{t("totalTokens")}</th>
                <th className="px-6 py-4">{t("inference")}</th>
                <th className="px-6 py-4">{t("electricity")}</th>
                <th className="px-6 py-4">
                  {t("avgCostPerToken") || "Avg Cost / Token"}
                </th>
                <th className="px-6 py-4 text-right">TOTAL</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-slate-900">
              {breakdown.map((row: any) => {
                const rowKWh =
                  elecPrice > 0 ? row.electricity / elecPrice : row.electricity / 5.5;
                const avgCostVal = row.total / (row.tokens || 1);
                return (
                  <tr
                    key={row.label}
                    className="group hover:bg-gray-50 dark:hover:bg-slate-900/50 transition-colors"
                  >
                    <td className="px-6 py-4">
                      <span className="text-sm font-semibold text-gray-900 dark:text-white">
                        {row.label}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-sm font-medium text-gray-500">
                      {(row.tokens / 1000000).toFixed(1)}M
                    </td>
                    <td className="px-6 py-4 text-sm font-medium text-gray-900 dark:text-white">
                      {formatCurrency(row.inference)}
                    </td>
                    <td className="px-6 py-4 text-sm font-medium text-emerald-600">
                      <div>{formatCurrency(row.electricity)}</div>
                      <div className="text-[10px] text-gray-400 dark:text-slate-500 font-bold uppercase mt-1">
                        ⚡ {rowKWh.toLocaleString("ru-RU", { maximumFractionDigits: 1 })} kWh
                      </div>
                    </td>
                    <td className="px-6 py-4 text-xs font-semibold text-gray-750 dark:text-slate-300">
                      <div>
                        {avgCostVal.toLocaleString("ru", {
                          minimumFractionDigits: 5,
                          maximumFractionDigits: 7,
                        })}{" "}
                        ₽
                      </div>
                      <div className="text-[10px] text-gray-400 dark:text-slate-500 font-normal mt-1">
                        или {(avgCostVal * 1000).toFixed(3)} ₽/1K
                      </div>
                    </td>
                    <td className="px-6 py-4 text-right">
                      <span className="text-lg font-bold text-indigo-600 dark:text-indigo-400">
                        {formatCurrency(row.total)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function CostStatCard({
  title,
  value,
  subValue,
  change,
  trend,
  icon: Icon,
  color,
  label,
}: any) {
  const colors = {
    indigo: {
      bg: "bg-indigo-50 dark:bg-indigo-500/10",
      text: "text-indigo-600 dark:text-indigo-400",
      border: "border-indigo-100 dark:border-indigo-500/20",
      circle: "bg-indigo-500",
    },
    amber: {
      bg: "bg-amber-50 dark:bg-amber-500/10",
      text: "text-amber-600 dark:text-amber-400",
      border: "border-amber-100 dark:border-amber-500/20",
      circle: "bg-amber-500",
    },
    emerald: {
      bg: "bg-emerald-50 dark:bg-emerald-500/10",
      text: "text-emerald-600 dark:text-emerald-400",
      border: "border-emerald-100 dark:border-emerald-500/20",
      circle: "bg-emerald-500",
    },
  };

  const c = colors[color as keyof typeof colors] || colors.indigo;

  return (
    <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl p-6 shadow-sm group hover:scale-[1.02] transition-transform">
      <div className="flex items-start justify-between mb-6">
        <div className={cn("p-4 rounded-lg", c.bg, c.text)}>
          <Icon className="w-6 h-6" />
        </div>
        <div
          className={cn(
            "flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[10px] font-semibold uppercase tracking-wider",
            trend === "up"
              ? "bg-red-50 text-red-600 border-red-100"
              : "bg-emerald-50 text-emerald-600 border-emerald-100",
          )}
        >
          {trend === "up" ? (
            <ArrowUpRight className="w-3 h-3" />
          ) : (
            <TrendingDown className="w-3 h-3" />
          )}
          {change}
        </div>
      </div>

      <div className="space-y-1">
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
          {title}
        </h4>
        <div className="text-2xl font-bold text-gray-900 dark:text-white tabular-nums tracking-tight">
          {value}
        </div>
        {subValue && (
          <div className="text-xs font-bold text-emerald-600 dark:text-emerald-400 mt-1 uppercase tracking-wider">
            {subValue}
          </div>
        )}
        {label && (
          <div className="flex items-center gap-2 mt-2 pt-2 border-t border-gray-50 dark:border-slate-900">
            <div className={cn("w-2 h-2 rounded-full", c.circle)} />
            <span className="text-xs text-gray-500">{label} allocation</span>
          </div>
        )}
      </div>
    </div>
  );
}
