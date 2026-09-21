import React, { useState } from 'react';
import {
  Plus,
  Server,
  RefreshCw,
  Database,
  CheckCircle2,
  XCircle,
  Clock,
  ShieldCheck,
  Search,
  ExternalLink,
} from 'lucide-react';
import { useBenchmark } from '../context/BenchmarkContext';
import { DataSource } from '../types';
import { Button, StatusBadge, Modal, Input, Select, NoticeBanner } from '../components/ui/GpbComponents';

export const DataSourcesView: React.FC = () => {
  const { dataSources, createDataSource, checkDataSource } = useBenchmark();

  // Create Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [checkingIds, setCheckingIds] = useState<Record<string, boolean>>({});
  const [searchQuery, setSearchQuery] = useState('');

  // Form fields (as specified in Section 8)
  const [name, setName] = useState('');
  const [dbType, setDbType] = useState<'ClickHouse'>('ClickHouse');
  const [host, setHost] = useState('');
  const [port, setPort] = useState<number>(8123);
  const [login, setLogin] = useState('default');
  const [secretRef, setSecretRef] = useState('');

  const filteredSources = dataSources.filter(
    (ds) =>
      ds.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      ds.host.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const handleCheck = async (id: string) => {
    setCheckingIds((prev) => ({ ...prev, [id]: true }));
    try {
      await checkDataSource(id);
    } finally {
      setCheckingIds((prev) => ({ ...prev, [id]: false }));
    }
  };

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !host.trim() || !secretRef.trim()) return;

    createDataSource({
      name: name.trim(),
      type: 'ClickHouse',
      host: host.trim(),
      port: Number(port) || 8123,
      login: login.trim(),
      secretRef: secretRef.trim(),
    });

    // Reset
    setName('');
    setHost('');
    setPort(8123);
    setLogin('default');
    setSecretRef('');
    setIsModalOpen(false);
  };

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
            Источники данных
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Общий каталог подключений к серверам ClickHouse, доступный для всех рабочих пространств
          </p>
        </div>

        <Button
          id="add-source-btn"
          variant="primary"
          icon={Plus}
          onClick={() => setIsModalOpen(true)}
        >
          Добавить источник
        </Button>
      </div>

      {/* Note on Data Sources per specification Section 2 & 8 */}
      <NoticeBanner type="info" title="Общие источники для всех пространств">
        Источники данных не привязаны к конкретному пространству или отдельной базе данных. База и
        исходная таблица выбираются позже — при создании конкретного бенчмарка. Источник используется
        для чтения схемы, а запись тестовых кандидатов осуществляется с отдельными правами sandbox.
      </NoticeBanner>

      {/* Search Bar */}
      <div className="p-3 bg-white dark:bg-[#171D26] rounded border border-slate-200 dark:border-[#242C38] flex items-center justify-between gap-3 shadow-2xs">
        <div className="relative w-full max-w-sm">
          <Search className="w-4 h-4 absolute left-2.5 top-2.5 text-slate-400" />
          <input
            type="text"
            placeholder="Поиск источника по названию или адресу..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 text-xs bg-slate-50 dark:bg-[#1A212C] text-slate-900 dark:text-slate-100 border border-slate-300 dark:border-[#333C4B] rounded focus:outline-none focus:ring-1 focus:ring-[#0033A0]"
          />
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400">
          Всего источников: <span className="font-semibold">{dataSources.length}</span>
        </div>
      </div>

      {/* Sources Table */}
      <div className="bg-white dark:bg-[#171D26] border border-slate-200 dark:border-[#242C38] rounded overflow-hidden shadow-2xs">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-700 dark:text-slate-300 border-collapse">
            <thead>
              <tr className="border-b border-slate-200 dark:border-[#242C38] bg-slate-50 dark:bg-[#1C232E] text-slate-500 dark:text-slate-400 font-semibold uppercase tracking-wider text-[11px]">
                <th className="px-4 py-3">Название</th>
                <th className="px-4 py-3">Тип БД</th>
                <th className="px-4 py-3">Адрес и порт</th>
                <th className="px-4 py-3">Логин</th>
                <th className="px-4 py-3">Ссылка на секрет</th>
                <th className="px-4 py-3">Состояние</th>
                <th className="px-4 py-3 text-right">Действие</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-[#242C38]">
              {filteredSources.map((ds) => {
                const isChecking = !!checkingIds[ds.id];

                return (
                  <tr
                    key={ds.id}
                    className="hover:bg-slate-50 dark:hover:bg-[#1F2733] transition-colors"
                  >
                    {/* Name */}
                    <td className="px-4 py-3 font-semibold text-slate-900 dark:text-slate-100">
                      <div className="flex items-center gap-2">
                        <Server className="w-4 h-4 text-[#0033A0] dark:text-[#78A9FF] shrink-0" />
                        <span>{ds.name}</span>
                      </div>
                    </td>

                    {/* DB Type */}
                    <td className="px-4 py-3">
                      <span className="font-mono text-[11px] bg-slate-100 dark:bg-[#212835] px-2 py-0.5 rounded text-slate-800 dark:text-slate-200 border border-slate-200 dark:border-[#313B4A]">
                        {ds.type}
                      </span>
                    </td>

                    {/* Host & Port */}
                    <td className="px-4 py-3 font-mono text-[11px] text-slate-700 dark:text-slate-300">
                      {ds.host}:{ds.port}
                    </td>

                    {/* Login */}
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400 font-mono text-[11px]">
                      {ds.login}
                    </td>

                    {/* Secret Reference */}
                    <td className="px-4 py-3">
                      <span className="font-mono text-[10px] text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-[#1B222E] px-1.5 py-0.5 rounded truncate max-w-[180px] inline-block">
                        {ds.secretRef}
                      </span>
                    </td>

                    {/* Status */}
                    <td className="px-4 py-3">
                      {ds.status === 'ready' && <StatusBadge status="ready" label="Готов" />}
                      {ds.status === 'not_checked' && (
                        <StatusBadge status="not_checked" label="Не проверен" />
                      )}
                      {ds.status === 'unavailable' && (
                        <StatusBadge status="unavailable" label="Недоступен" />
                      )}
                      {ds.lastCheckedAt && (
                        <div className="text-[10px] text-slate-400 dark:text-slate-500 mt-0.5">
                          {ds.lastCheckedAt.split(' ')[1]}
                        </div>
                      )}
                    </td>

                    {/* Action: Check */}
                    <td className="px-4 py-3 text-right">
                      <Button
                        size="sm"
                        variant="secondary"
                        icon={RefreshCw}
                        isLoading={isChecking}
                        onClick={() => handleCheck(ds.id)}
                        title="Выполнить POST /api/v1/sources/:id/check"
                      >
                        Проверить
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ADCM Style Modal for Adding Data Source */}
      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title="Создать источник данных"
        subtitle="Подключение к серверу ClickHouse для экспериментов над таблицами"
        maxWidth="md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setIsModalOpen(false)}>
              Отмена
            </Button>
            <Button
              variant="primary"
              onClick={handleCreateSubmit}
              disabled={!name.trim() || !host.trim() || !secretRef.trim()}
            >
              Сохранить источник
            </Button>
          </>
        }
      >
        <form onSubmit={handleCreateSubmit} className="space-y-4">
          <Input
            id="source-name-input"
            label="Название подключения"
            required
            placeholder="Например: ch-cluster-analytics.internal"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-slate-700 dark:text-slate-300">
                Тип базы данных
              </label>
              <div className="mt-1 px-3 py-1.5 bg-slate-100 dark:bg-[#202734] border border-slate-200 dark:border-[#333C4B] rounded text-xs font-medium text-slate-700 dark:text-slate-300">
                ClickHouse
              </div>
            </div>

            <div>
              <Input
                id="source-port-input"
                label="Порт"
                type="number"
                required
                value={port}
                onChange={(e) => setPort(Number(e.target.value))}
              />
            </div>
          </div>

          <Input
            id="source-host-input"
            label="Хост (адрес сервера)"
            required
            placeholder="clickhouse-node01.prod.corp.internal"
            value={host}
            onChange={(e) => setHost(e.target.value)}
          />

          <Input
            id="source-login-input"
            label="Логин"
            required
            placeholder="default"
            value={login}
            onChange={(e) => setLogin(e.target.value)}
          />

          <div>
            <Input
              id="source-secret-input"
              label="Ссылка на секрет (Secret Reference)"
              required
              placeholder="vault://secrets/infra/clickhouse/ro-token"
              value={secretRef}
              onChange={(e) => setSecretRef(e.target.value)}
              helperText="В текущей версии вместо ввода пароля используется ссылка на серверный секрет. Поддержка произвольного ввода пароля через UI не предусмотрена."
            />
          </div>

          <div className="p-3 bg-slate-50 dark:bg-[#1A212D] border border-slate-200 dark:border-[#2C3644] rounded text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
            Отдельного выбора базы в этой форме нет. Конкретные таблицы выбираются позже в мастере
            создания бенчмарка.
          </div>
        </form>
      </Modal>
    </div>
  );
};
