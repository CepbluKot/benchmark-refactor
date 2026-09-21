import React, { useState, useEffect } from "react";
import {
  Settings2,
  Save,
  Zap,
  Info,
  Loader2,
  Database,
  Cpu,
  Dna,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import {
  getModelRates,
  getPlatformRates,
  updateModelRate,
  updateElectricityPrice,
  ModelRate,
  PlatformRates,
} from "../api/mock";

import { useLanguage } from "../context/LanguageContext";
import { cn } from "../lib/utils";
import { motion } from "motion/react";

export function EconomicsSettings() {
  const { t, language } = useLanguage();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [rates, setRates] = useState<ModelRate[]>([]);
  const [platformRates, setPlatformRates] = useState<PlatformRates | null>(
    null,
  );
  const [editingRates, setEditingRates] = useState<
    Record<string, { input: number; output: number; watts: number }>
  >({});
  const [elecPrice, setElecPrice] = useState(0);
  const [autoCalculate, setAutoCalculate] = useState(false);
  const [profitMargin, setProfitMargin] = useState(2.5);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [ratesData, platData] = await Promise.all([
        getModelRates(),
        getPlatformRates(),
      ]);

      setRates(ratesData);
      setPlatformRates(platData);
      setElecPrice(platData.electricityPriceKWh);

      const editObj: Record<
        string,
        { input: number; output: number; watts: number }
      > = {};
      ratesData.forEach((r) => {
        editObj[r.modelName] = {
          input: r.inputPricePer1M / 1000000,
          output: r.outputPricePer1M / 1000000,
          watts: r.wattsPerReplica,
        };
      });
      setEditingRates(editObj);
    } catch (err) {
      console.error("Failed to fetch economics data", err);
    } finally {
      setLoading(false);
    }
  };

  const calculateAutoRates = (watts: number) => {
    // Basic formula: (Watts * Price/kWh / 1000) * Margin * Constant (model throughput proxy)
    // For demo purposes, we will just scale it linearly to look realistic
    const hourlyCost = (watts / 1000) * elecPrice;
    const inputPer1M = Math.round(hourlyCost * profitMargin * 1.2);
    const outputPer1M = Math.round(hourlyCost * profitMargin * 1.8);
    return {
      input: inputPer1M / 1000000,
      output: outputPer1M / 1000000,
    };
  };

  useEffect(() => {
    if (autoCalculate) {
      const newRates = { ...editingRates };
      rates.forEach((r) => {
        const { input, output } = calculateAutoRates(
          editingRates[r.modelName]?.watts || r.wattsPerReplica,
        );
        newRates[r.modelName] = { ...newRates[r.modelName], input, output };
      });
      setEditingRates(newRates);
    }
  }, [autoCalculate, elecPrice, profitMargin, rates]);

  useEffect(() => {
    fetchData();
  }, []);

  const handleUpdateElectricity = async () => {
    setSaving("electricity");
    await updateElectricityPrice(elecPrice);
    await fetchData();
    setSaving(null);
  };

  const handleUpdateRate = async (modelName: string) => {
    setSaving(modelName);
    const data = editingRates[modelName];
    const inputPer1M = Math.round(data.input * 1000000);
    const outputPer1M = Math.round(data.output * 1000000);
    await updateModelRate(modelName, inputPer1M, outputPer1M, data.watts);
    // Refresh data
    await fetchData();
    setSaving(null);
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh]">
        <Loader2 className="w-8 h-8 animate-spin text-indigo-500 mb-4" />
        <p className="text-gray-500 font-semibold uppercase tracking-wider text-xs">
          Loading Economic Models...
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-12 pb-20">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          {t("economics")}
        </h1>
        <p className="text-sm text-gray-500 mt-1">{t("economicsSub")}</p>
      </div>

      <div className="grid grid-cols-1 gap-10">
        {/* Economics Engine Configuration */}
        <section className="bg-slate-900 border border-slate-800 rounded-2xl p-6 relative overflow-hidden group">
          <div className="absolute top-0 right-0 w-64 h-64 bg-indigo-500/10 blur-[100px] rounded-full -mr-20 -mt-20 group-hover:bg-indigo-500/20 transition-all duration-1000" />
          <div className="relative z-10 space-y-6">
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-indigo-500/20 text-indigo-400 rounded-xl">
                  <Database className="w-6 h-6" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-white">
                    {language === "ru" ? "Управление экономикой моделей" : "Economics Engine"}
                  </h3>
                  <p className="text-sm text-slate-400">
                    {language === "ru" ? "Автоматический расчёт стоимости и оптимизация инференса" : "Autonomous Pricing & Cost Optimization"}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-6">
                <div className="flex flex-col items-end">
                  <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                    {t("autoCalculateCost")}
                  </span>
                  <div className="flex items-center gap-3">
                    <span
                      className={cn(
                        "text-xs font-medium uppercase transition-colors",
                        !autoCalculate ? "text-white" : "text-slate-600",
                      )}
                    >
                      {language === "ru" ? "Вручную" : "Manual"}
                    </span>
                    <button
                      onClick={() => setAutoCalculate(!autoCalculate)}
                      className={cn(
                        "w-11 h-6 rounded-full relative transition-all duration-300",
                        autoCalculate ? "bg-indigo-500" : "bg-slate-800",
                      )}
                    >
                      <div
                        className={cn(
                          "absolute top-1 left-1 w-4 h-4 rounded-full bg-white transition-all duration-300 shadow-sm",
                          autoCalculate ? "translate-x-5" : "translate-x-0",
                        )}
                      />
                    </button>
                    <span
                      className={cn(
                        "text-xs font-medium uppercase transition-colors",
                        autoCalculate ? "text-indigo-400" : "text-slate-600",
                      )}
                    >
                      {language === "ru" ? "Авторежим" : "Auto"}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="p-5 bg-slate-800/50 border border-slate-700/50 rounded-xl space-y-2">
                <div className="flex items-center gap-2 text-slate-400 mb-1">
                  <Zap className="w-3 h-3" />
                  <span className="text-[10px] font-semibold uppercase tracking-wider">
                    {t("baseKwhPrice")}
                  </span>
                </div>
                <div className="flex items-end gap-2">
                  <span className="text-2xl font-bold text-white tabular-nums">
                    ₽{elecPrice}
                  </span>
                  <div className="flex flex-col mb-1 shrink-0 font-sans">
                    <span className="text-[9px] font-bold text-emerald-400 tracking-wider uppercase leading-none">
                      {language === "ru" ? "АВТО-СИНХРОНИЗАЦИЯ" : "AUTO-SYNC"}
                    </span>
                    <span className="text-[8px] font-medium text-slate-500 tracking-wider uppercase leading-none mt-0.5">
                      {language === "ru" ? "ИЗ PROMETHEUS" : "FROM PROMETHEUS"}
                    </span>
                  </div>
                </div>
              </div>
              <div className="md:col-span-2 p-5 bg-indigo-500/5 border border-indigo-500/20 rounded-xl flex gap-4">
                <Info className="w-5 h-5 text-indigo-400 shrink-0 mt-1" />
                <div>
                  <h4 className="text-xs font-semibold text-white uppercase tracking-wider mb-1">
                    {t("pricingLogic")}
                  </h4>
                  <p className="text-xs text-slate-400 leading-relaxed font-medium">
                    {language === "ru"
                      ? "При включённом авторежиме тарифы автоматически пересчитываются каждые 5 минут на основе живых показателей PUE из метрик Prometheus."
                      : "When auto-calculation is active, inference rates are dynamically re-calculated every 5 minutes based on live PUE data from Prometheus cluster metrics."}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Tariff Management */}
        <section className="space-y-6">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 rounded-xl">
              <Settings2 className="w-6 h-6" />
            </div>
            <h3 className="text-xl font-bold text-gray-900 dark:text-white">
              {t("tariffCatalog")}
            </h3>
          </div>

          <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl overflow-hidden shadow-sm">
            <table className="w-full text-left">
              <thead>
                <tr className="bg-gray-50 dark:bg-slate-900/50 text-xs font-semibold text-gray-500 uppercase tracking-wider border-b border-gray-100 dark:border-slate-900">
                  <th className="px-6 py-4">{language === "ru" ? "Модель" : "Model"}</th>
                  <th className="px-6 py-4 text-center">
                    {language === "ru" ? "Раздельный тариф за 1 вх. токен" : "Rate per 1 Input Token"}
                  </th>
                  <th className="px-6 py-4 text-center">
                    {language === "ru" ? "Раздельный тариф за 1 исх. токен" : "Rate per 1 Output Token"}
                  </th>
                  <th className="px-6 py-4 text-right">{language === "ru" ? "Действия" : "Actions"}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-slate-900">
                {rates.map((rate) => (
                  <tr
                    key={rate.modelName}
                    className="group hover:bg-gray-50/50 dark:hover:bg-slate-900/30 transition-colors"
                  >
                    <td className="px-6 py-4">
                      <div className="flex flex-col">
                        <span className="text-sm font-semibold text-gray-900 dark:text-white">
                          {rate.modelName}
                        </span>
                        <span className="text-[10px] text-gray-400 font-bold uppercase tracking-widest leading-none mt-1">
                          {language === "ru" ? "ИИ ИНФРАСТРУКТУРА" : "AI INFRASTRUCTURE"}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-col items-center gap-1">
                        <div className="relative">
                          <input
                            type="number"
                            step="0.000001"
                            disabled={autoCalculate}
                            value={editingRates[rate.modelName]?.input || 0}
                            onChange={(e) =>
                              setEditingRates({
                                ...editingRates,
                                [rate.modelName]: {
                                  ...editingRates[rate.modelName],
                                  input: Number(e.target.value),
                                },
                              })
                            }
                            className={cn(
                              "w-full max-w-[140px] block bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-3 py-2 text-xs font-semibold text-center outline-none focus:ring-2 focus:ring-indigo-500 transition-all font-mono",
                              autoCalculate
                                ? "opacity-60 text-indigo-500"
                                : "text-gray-900 dark:text-white",
                            )}
                          />
                        </div>
                        <span className="text-[10px] text-gray-400 font-mono">
                          ~{Math.round((editingRates[rate.modelName]?.input || 0) * 1000000)} ₽ / 1M
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-col items-center gap-1">
                        <div className="relative">
                          <input
                            type="number"
                            step="0.000001"
                            disabled={autoCalculate}
                            value={editingRates[rate.modelName]?.output || 0}
                            onChange={(e) =>
                              setEditingRates({
                                ...editingRates,
                                [rate.modelName]: {
                                  ...editingRates[rate.modelName],
                                  output: Number(e.target.value),
                                },
                              })
                            }
                            className={cn(
                              "w-full max-w-[140px] block bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-3 py-2 text-xs font-semibold text-center outline-none focus:ring-2 focus:ring-indigo-500 transition-all font-mono",
                              autoCalculate
                                ? "opacity-60 text-indigo-500"
                                : "text-gray-900 dark:text-white",
                            )}
                          />
                        </div>
                        <span className="text-[10px] text-gray-400 font-mono">
                          ~{Math.round((editingRates[rate.modelName]?.output || 0) * 1000000)} ₽ / 1M
                        </span>
                      </div>
                    </td>

                    <td className="px-6 py-4 text-right">
                      <button
                        onClick={() => handleUpdateRate(rate.modelName)}
                        disabled={saving === rate.modelName}
                        className="p-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition-all shadow-sm disabled:opacity-50"
                      >
                        {saving === rate.modelName ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Save className="w-4 h-4" />
                        )}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Global Energy Config */}
        <section className="space-y-6">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 rounded-xl">
              <Zap className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-xl font-bold text-gray-900 dark:text-white font-sans">
                {language === "ru" ? "Глобальные настройки" : "Global Economics Config"}
              </h3>
              <p className="text-xs text-gray-500">
                {language === "ru"
                  ? "Управление экономическими параметрами платформы"
                  : "Platform-level economic parameters control"}
              </p>
            </div>
          </div>

          <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl p-8 space-y-8 w-full">
            <div className="space-y-4">
              <div className="flex flex-col gap-1">
                <label className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
                  {language === "ru" ? "Цена кВт·ч — одна цифра на всю платформу" : "Electricity Price per kWh — one single number for the entire platform"}
                </label>
                <p className="text-xs text-gray-400">
                  {language === "ru"
                    ? "Укажите базовую стоимость электроэнергии. Данный параметр применяется глобально ко всей платформе и используется в авторежиме для автоматического расчёта тарифов всех моделей."
                    : "Specify the baseline cost of electricity. This parameter is applied platform-wide and is used in auto-mode to compute tariffs for all active models."}
                </p>
              </div>
              <div className="flex items-center gap-4">
                <div className="relative flex-1">
                  <input
                    type="number"
                    step="0.1"
                    value={elecPrice}
                    onChange={(e) => setElecPrice(Number(e.target.value))}
                    className="w-full bg-gray-100 dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-10 py-4 text-3xl font-bold text-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-emerald-500 font-mono"
                  />
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 text-xl font-bold text-emerald-500">
                    ₽
                  </span>
                </div>
                <button
                  onClick={handleUpdateElectricity}
                  disabled={saving === "electricity"}
                  className="p-4 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 transition-all shadow-sm disabled:opacity-50"
                >
                  {saving === "electricity" ? (
                    <Loader2 className="w-7 h-7 animate-spin" />
                  ) : (
                    <Save className="w-7 h-7" />
                  )}
                </button>
              </div>
            </div>

            <div className="bg-slate-950 dark:bg-slate-900 rounded-xl p-6 border border-slate-800 flex gap-4">
              <div className="p-2.5 bg-indigo-500/10 text-indigo-400 rounded-lg h-fit">
                <Info className="w-5 h-5" />
              </div>
              <div>
                <h4 className="text-sm font-semibold text-white uppercase tracking-wider mb-2">
                  {t("pricingLogic")}
                </h4>
                <p className="text-xs text-slate-400 leading-relaxed font-medium">
                  {language === "ru"
                    ? "В авторежиме тариф модели за 1 входящий и 1 исходящий токен рассчитывается автоматически на основе параметров потребляемой мощности за реплику и единой стоимости кВт·ч на всю платформу."
                    : "In automated calculation mode, the model tariff for 1 incoming and 1 outgoing token is computed automatically based on the model consumption index (Watts/replica) and the unified price per kWh for the entire platform."}
                </p>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
