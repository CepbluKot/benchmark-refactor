import React, { useState, useEffect } from 'react';
import { Key, Shield, Trash2, Calendar, HardDrive, Cpu, AlertTriangle } from 'lucide-react';
import { getTokens, revokeToken, deleteToken, TechnicalToken } from '../api/mock';
import { useLanguage } from '../context/LanguageContext';

export function ApiTokens() {
  const { t, language } = useLanguage();
  const [tokens, setTokens] = useState<TechnicalToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [confirmAction, setConfirmAction] = useState<{ type: 'revoke' | 'delete'; id: string } | null>(null);

  const fetchTokens = async () => {
    setLoading(true);
    const data = await getTokens();
    setTokens(data);
    setLoading(false);
  };

  useEffect(() => {
    fetchTokens();
  }, []);

  const handleRevoke = async (id: string) => {
    await revokeToken(id);
    fetchTokens();
  };

  const handleDelete = async (id: string) => {
    await deleteToken(id);
    fetchTokens();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
             <Key className="w-8 h-8 text-indigo-600" />
             {t('apiTokens') || 'API Tokens'}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
             {language === 'ru'
               ? 'Управление всеми активными техническими токенами деплойментов моделей.'
               : 'Manage all active technical tokens across model deployments.'}
          </p>
        </div>
      </div>

      <div className="bg-white dark:bg-slate-950 rounded-2xl shadow-sm border border-gray-200 dark:border-slate-800 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-sm">
            <thead>
              <tr className="bg-gray-50 dark:bg-slate-900/50 text-xs font-semibold uppercase tracking-wider text-gray-500 border-b border-gray-200 dark:border-slate-800">
                <th className="px-6 py-4">Name / ID</th>
                <th className="px-6 py-4">{language === 'ru' ? 'Деплоймент' : 'Deployment'}</th>
                <th className="px-6 py-4">{language === 'ru' ? 'Создан' : 'Created'}</th>
                <th className="px-6 py-4">{language === 'ru' ? 'Истекает' : 'Expires'}</th>
                <th className="px-6 py-4">{language === 'ru' ? 'Статус' : 'Status'}</th>
                <th className="px-6 py-4 text-right">{language === 'ru' ? 'Действия' : 'Actions'}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 dark:divide-slate-900">
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-gray-500">
                     {language === 'ru' ? 'Загрузка токенов...' : 'Loading tokens...'}
                  </td>
                </tr>
              ) : tokens.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-gray-500">
                     {language === 'ru' ? 'Токены не найдены.' : 'No tokens found.'}
                  </td>
                </tr>
              ) : (
                tokens.map(token => (
                  <tr key={token.id} className="hover:bg-gray-50/50 dark:hover:bg-slate-900/20 transition-colors">
                    <td className="px-6 py-4">
                      <div className="font-semibold text-gray-900 dark:text-slate-200 text-xs">{token.name || 'Unnamed Token'}</div>
                      <div className="text-[10px] text-gray-400 font-mono mt-0.5">{token.id}</div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <Cpu className="w-4 h-4 text-indigo-500" />
                        <span className="font-semibold text-gray-900 dark:text-slate-200">{token.model}</span>
                      </div>
                      <div className="text-[10px] text-gray-500 mt-1 flex items-center gap-1">
                        <HardDrive className="w-3 h-3" /> {token.cluster}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-gray-600 dark:text-gray-400">
                      {new Date(token.createdAt).toLocaleString()}
                    </td>
                    <td className="px-6 py-4 text-gray-600 dark:text-gray-400">
                      {token.expiresAt === 'never' ? (language === 'ru' ? 'Никогда' : 'Never') : new Date(token.expiresAt).toLocaleString()}
                    </td>
                    <td className="px-6 py-4">
                      <span className={`px-2.5 py-1 rounded-full text-xs font-semibold capitalize ${
                        token.status === 'active' ? 'bg-emerald-100 text-emerald-700' :
                        token.status === 'revoked' ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-700'
                      }`}>
                         {token.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                         {token.status === 'active' && (
                           <button
                             onClick={() => setConfirmAction({ type: 'revoke', id: token.id })}
                             className="p-1.5 text-gray-400 hover:text-amber-500 transition-colors"
                             title={language === 'ru' ? 'Отозвать токен' : 'Revoke Token'}
                           >
                             <AlertTriangle className="w-4 h-4" />
                           </button>
                         )}
                         <button
                           onClick={() => setConfirmAction({ type: 'delete', id: token.id })}
                           className="p-1.5 text-gray-400 hover:text-red-500 transition-colors"
                           title={language === 'ru' ? 'Удалить токен навсегда' : 'Delete Token permanently'}
                         >
                           <Trash2 className="w-4 h-4" />
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

      {confirmAction && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl p-6 max-w-sm w-full shadow-2xl space-y-4">
            <div className="flex items-center gap-3 text-amber-500">
              <AlertTriangle className="w-6 h-6 shrink-0 animate-bounce" />
              <h3 className="text-base font-bold text-gray-900 dark:text-white">
                {language === 'ru' ? 'Вы уверены?' : 'Are you sure?'}
              </h3>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
              {language === 'ru'
                ? (confirmAction.type === 'revoke'
                    ? 'Вы собираетесь отозвать этот токен. С этого момента он больше не сможет использоваться для авторизации запросов к API.'
                    : 'Вы собираетесь безвозвратно удалить этот технический токен из базы данных панели управления.')
                : (confirmAction.type === 'revoke'
                    ? 'You are about to revoke this token. It will no longer serve authentication requests or access to APIs.'
                    : 'You are about to permanently delete this technical token from the dashboard database.')
              }
            </p>
            <div className="flex items-center gap-3">
              <button
                onClick={() => setConfirmAction(null)}
                className="flex-1 py-2 px-3 bg-gray-100 dark:bg-slate-800 text-gray-800 dark:text-white rounded-lg text-xs font-semibold hover:bg-gray-200 dark:hover:bg-slate-700 transition"
              >
                {language === 'ru' ? 'Отмена' : 'Cancel'}
              </button>
              <button
                onClick={async () => {
                  const { type, id } = confirmAction;
                  setConfirmAction(null);
                  if (type === 'revoke') {
                    await handleRevoke(id);
                  } else {
                    await handleDelete(id);
                  }
                }}
                className="flex-1 py-2 px-3 bg-red-650 dark:bg-red-600 hover:bg-red-700 text-white rounded-lg text-xs font-semibold transition bg-red-600"
              >
                {language === 'ru' ? 'Подтвердить' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
