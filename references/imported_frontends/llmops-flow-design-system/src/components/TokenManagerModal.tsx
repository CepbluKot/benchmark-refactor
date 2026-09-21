import React, { useState, useEffect } from 'react';
import { X, Key, Trash2, Plus, Copy, Check, AlertCircle, Loader2 } from 'lucide-react';
import { getTokens, createToken, deleteToken, TechnicalToken, Deployment } from '../api/mock';
import { useLanguage } from '../context/LanguageContext';

interface TokenManagerModalProps {
  deployment: Deployment;
  onClose: () => void;
}

export function TokenManagerModal({ deployment, onClose }: TokenManagerModalProps) {
  const { t } = useLanguage();
  const [tokens, setTokens] = useState<TechnicalToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generatedToken, setGeneratedToken] = useState<TechnicalToken | null>(null);
  const [copied, setCopied] = useState(false);
  const [expiresInDays, setExpiresInDays] = useState<number>(30);
  const [tokenName, setTokenName] = useState<string>('');

  const fetchTokens = async () => {
    setLoading(true);
    const data = await getTokens(deployment.id);
    setTokens(data);
    setLoading(false);
  };

  useEffect(() => {
    fetchTokens();
  }, [deployment.id]);

  const handleGenerate = async () => {
    setIsGenerating(true);
    const newToken = await createToken({
      name: tokenName.trim() || undefined,
      model: deployment.modelName,
      cluster: deployment.clusterId,
      deploymentId: deployment.id,
      expiresInDays
    });
    setGeneratedToken(newToken);
    setTokenName('');
    fetchTokens();
    setIsGenerating(false);
  };

  const handleDelete = async (tokenId: string) => {
    await deleteToken(tokenId);
    fetchTokens();
  };

  const handleCopy = (tokenStr: string) => {
    navigator.clipboard.writeText(tokenStr);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-slate-950 w-full max-w-2xl rounded-2xl shadow-xl overflow-hidden flex flex-col border border-gray-200 dark:border-slate-800 max-h-[90vh]">
        <div className="px-6 py-5 border-b border-gray-100 dark:border-slate-800 flex items-center justify-between bg-gray-50/50 dark:bg-slate-900/50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-50 dark:bg-indigo-500/10 flex items-center justify-center">
              <Key className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-gray-900 dark:text-white">{t('apiTokens') || 'API Tokens'}</h3>
              <p className="text-sm text-gray-500 dark:text-slate-400">{deployment.modelName} &bull; {deployment.clusterId}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-gray-400 hover:bg-gray-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {generatedToken ? (
            <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div className="p-4 bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/20 rounded-xl flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
                <p className="text-sm text-emerald-800 dark:text-emerald-400 font-medium">Please copy your token now. You will not be able to see it again after closing this window.</p>
              </div>

              <div>
                 <label className="text-sm font-medium text-gray-700 dark:text-slate-300 block mb-1">Generated API Token</label>
                 <div className="relative">
                    <input type="text" readOnly value={generatedToken.token} className="w-full bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-4 py-3 font-mono text-sm text-gray-900 dark:text-white outline-none" />
                    <button className="absolute right-2 top-1/2 -translate-y-1/2 p-2 text-gray-400 hover:text-indigo-500 bg-white dark:bg-slate-900">
                       {copied ? <Check className="w-4 h-4 text-emerald-500" /> : <Copy className="w-4 h-4" onClick={() => handleCopy(generatedToken.token)} />}
                    </button>
                 </div>
              </div>

              <div className="space-y-2 mt-6">
                <h4 className="text-sm font-semibold text-gray-900 dark:text-white">Example usage (Inference API):</h4>
                <pre className="p-4 bg-slate-950 text-slate-300 font-mono text-xs rounded-xl overflow-x-auto border border-slate-800">
                  {`curl http://${generatedToken.cluster}:11434/v1/chat/completions \\
  -H "Authorization: Bearer ${generatedToken.token}" \\
  -d '{"model":"${generatedToken.model}", "messages":[{"role":"user","content":"Hi"}]}'`}
                </pre>
              </div>

              <button onClick={() => setGeneratedToken(null)} className="w-full py-2 bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 text-gray-900 dark:text-white rounded-lg text-sm font-medium mt-4 transition-colors">Done</button>
            </div>
          ) : (
            <>
              {/* Generate New */}
              <div className="bg-gray-50 dark:bg-slate-900/50 border border-gray-200 dark:border-slate-800 rounded-xl p-5 space-y-4">
                <h4 className="text-sm font-semibold text-gray-900 dark:text-white">Generate New Token</h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs font-semibold text-gray-500 block mb-1.5 uppercase tracking-wider">{t('tokenName') || 'Token Name'}</label>
                    <input
                      type="text"
                      value={tokenName}
                      onChange={e => setTokenName(e.target.value)}
                      placeholder={t('enterTokenName') || 'Enter token name'}
                      className="w-full bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-gray-500 block mb-1.5 uppercase tracking-wider">Expiration</label>
                    <select
                      value={expiresInDays}
                      onChange={e => setExpiresInDays(Number(e.target.value))}
                      className="w-full bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    >
                      <option value={1}>Expires in 1 day</option>
                      <option value={7}>Expires in 7 days</option>
                      <option value={30}>Expires in 30 days</option>
                      <option value={-1}>Never expires</option>
                    </select>
                  </div>
                </div>
                <div className="flex justify-end pt-2">
                  <button
                    onClick={handleGenerate}
                    disabled={isGenerating}
                    className="bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors disabled:opacity-50"
                  >
                    {isGenerating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                    Generate Token
                  </button>
                </div>
              </div>

              {/* List */}
              <div className="space-y-3">
                <h4 className="text-sm font-semibold text-gray-900 dark:text-white">Active Tokens</h4>
                {loading ? (
                  <div className="py-8 flex justify-center">
                    <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
                  </div>
                ) : tokens.length === 0 ? (
                  <div className="py-8 text-center text-sm text-gray-500">
                    No active tokens for this deployment.
                  </div>
                ) : (
                  <div className="border border-gray-200 dark:border-slate-800 rounded-xl overflow-hidden bg-white dark:bg-slate-950">
                     <table className="w-full text-left text-sm whitespace-nowrap">
                        <thead className="bg-gray-50 dark:bg-slate-900/50 text-xs font-semibold text-gray-500 uppercase tracking-wider border-b border-gray-200 dark:border-slate-800">
                           <tr>
                              <th className="px-4 py-3">Name / ID</th>
                              <th className="px-4 py-3">Created</th>
                              <th className="px-4 py-3">Expires</th>
                              <th className="px-4 py-3">Status</th>
                              <th className="px-4 py-3 text-right">Actions</th>
                           </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-200 dark:divide-slate-800">
                           {tokens.map(t => (
                              <tr key={t.id}>
                                 <td className="px-4 py-3">
                                   <div className="font-semibold text-gray-900 dark:text-white text-xs">{t.name || 'Unnamed Token'}</div>
                                   <div className="text-[10px] text-gray-400 font-mono mt-0.5">{t.id}</div>
                                 </td>
                                 <td className="px-4 py-3 text-gray-600 dark:text-slate-400">{new Date(t.createdAt).toLocaleDateString()}</td>
                                 <td className="px-4 py-3 text-gray-500">
                                   {t.expiresAt === 'never' ? 'Never' : new Date(t.expiresAt).toLocaleDateString()}
                                 </td>
                                 <td className="px-4 py-3">
                                   <span className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${
                                     t.status === 'active' ? 'bg-emerald-100 text-emerald-700' :
                                     t.status === 'revoked' ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-700'
                                   }`}>
                                     {t.status}
                                   </span>
                                 </td>
                                 <td className="px-4 py-3 text-right">
                                   <button
                                     onClick={() => handleDelete(t.id)}
                                     className="p-1.5 text-gray-400 hover:text-red-500 transition-colors"
                                     title="Delete Token"
                                   >
                                     <Trash2 className="w-4 h-4" />
                                   </button>
                                 </td>
                              </tr>
                           ))}
                        </tbody>
                     </table>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
