import React, { useState, useEffect, useRef } from 'react';
import { Trash2, Eye, GitMerge, Loader2, Copy, Check, X, MessageSquare, Send, Bot, User, Pin, Cpu, Activity, Server, SlidersHorizontal, Key, AlertCircle, Users, Terminal, RefreshCw, ShieldCheck } from 'lucide-react';
import { getDeployments, deleteDeployment, Deployment } from '../api/mock';

import { useCluster } from '../context/ClusterContext';
import { useLanguage } from '../context/LanguageContext';
import { TokenManagerModal } from '../components/TokenManagerModal';

export function Deployments() {
  const { selectedClusterId } = useCluster();
  const { t, language } = useLanguage();
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [loading, setLoading] = useState(true);
  const [viewingDep, setViewingDep] = useState<Deployment | null>(null);
  const [copied, setCopied] = useState(false);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [managingNode, setManagingNode] = useState<{ dep: Deployment, group: any } | null>(null);
  const [managingPolicy, setManagingPolicy] = useState<Deployment | null>(null);
  const [managingTokensFor, setManagingTokensFor] = useState<Deployment | null>(null);

  // New features state
  const [accessControlDep, setAccessControlDep] = useState<Deployment | null>(null);
  const [logsDep, setLogsDep] = useState<Deployment | null>(null);
  const [selectedTeams, setSelectedTeams] = useState<string[]>(['engineering', 'research']);
  const [accessLevel, setAccessLevel] = useState<'inference' | 'admin'>('inference');

  const [redeployingId, setRedeployingId] = useState<string | null>(null);
  const [successNotification, setSuccessNotification] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  // Chat state
  const [chattingDep, setChattingDep] = useState<Deployment | null>(null);
  const [messages, setMessages] = useState<{role: 'user'|'assistant', content: string}[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const fetchDeployments = async () => {
    const data = await getDeployments(selectedClusterId);
    setDeployments(data);
    setLoading(false);
  };

  useEffect(() => {
    fetchDeployments();
    const interval = setInterval(fetchDeployments, 5000);
    return () => clearInterval(interval);
  }, [selectedClusterId]);

  const handleDelete = async (id: string) => {
    await deleteDeployment(id);
    fetchDeployments();
  };

  const handleRedeploy = async (id: string) => {
    setRedeployingId(id);
    setSuccessNotification(`Initiating redeployment of ${id} is in progress...`);

    setTimeout(() => {
      setSuccessNotification(`Deployment ${id} successfully redeployed! All replica pods have been restarted successfully.`);
      setRedeployingId(null);
      setTimeout(() => setSuccessNotification(null), 4000);
    }, 2000);
  };

  const timeAgo = (dateStr: string) => {
    const diff = Date.now() - new Date(dateStr).getTime();
    const minutes = Math.floor(diff / 60000);
    if (minutes < 60) return `${minutes} mins ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours} hours ago`;
    return `${Math.floor(hours / 24)} days ago`;
  };

  const StatusBadge = ({ status }: { status: string }) => {
    const colors = {
      pending: 'bg-yellow-50 text-yellow-700 border-yellow-200 dark:bg-yellow-500/10 dark:text-yellow-400 dark:border-yellow-500/20',
      pulling: 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-500/10 dark:text-blue-400 dark:border-blue-500/20',
      running: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/20',
      failed: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/20'
    };
    return (
      <span className={`px-2.5 py-1 rounded-full border text-xs font-semibold capitalize ${colors[status as keyof typeof colors]}`}>
        {status}
      </span>
    );
  };

  const handleCopy = (dep: Deployment) => {
    const cmd = `curl http://${dep.clusterId}:11434/api/chat -d '{"model":"${dep.modelName}","messages":[{"role":"user","content":"Hello"}]}'`;
    navigator.clipboard.writeText(cmd);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const openChat = (dep: Deployment) => {
    setChattingDep(dep);
    setMessages([{ role: 'assistant', content: `Hello! I'm the ${dep.modelName} model running on ${dep.clusterId}. How can I help you today?` }]);
    setChatInput('');
  };

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim() || isTyping) return;

    const userMsg = chatInput.trim();
    setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
    setChatInput('');
    setIsTyping(true);

    // Mock API delay
    await new Promise(resolve => setTimeout(resolve, 1000 + Math.random() * 1000));

    setMessages(prev => [...prev, {
      role: 'assistant',
      content: `This is a mock response from ${chattingDep?.modelName}. You said: "${userMsg}"`
    }]);
    setIsTyping(false);
  };

  const toggleRow = (id: string) => {
    const next = new Set(expandedRows);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExpandedRows(next);
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{t('deployments') || 'Deployments'}</h1>
          <p className="text-gray-500 dark:text-slate-400 mt-1">{t('deploymentsDesc') || 'Manage and monitor your active model deployments'}</p>
        </div>
      </div>

      {successNotification && (
        <div className="bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/20 rounded-xl p-4 flex items-center gap-3 text-sm text-emerald-850 dark:text-emerald-400 shadow-sm animate-fade-in">
          <ShieldCheck className="w-5 h-5 text-emerald-500 animate-bounce" />
          <div className="font-medium">{successNotification}</div>
        </div>
      )}

      <div className="bg-white dark:bg-slate-950 rounded-2xl border border-gray-200 dark:border-slate-800 overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
        <thead className="bg-gray-50 dark:bg-slate-900/50 text-xs font-semibold text-gray-500 uppercase tracking-wider border-b border-gray-200 dark:border-slate-800">
          <tr>
            <th className="px-6 py-4">{t('modelName') || 'Model'}</th>
            <th className="px-6 py-4">{t('cluster') || 'Cluster'}</th>
            <th className="px-6 py-4">{t('team') || 'Team'}</th>
            <th className="px-6 py-4">{t('replicas') || 'Replicas'}</th>
            <th className="px-6 py-4">{t('status') || 'Status'}</th>
            <th className="px-6 py-4">{t('createdAt') || 'Created'}</th>
            <th className="px-6 py-4 text-right">{t('actions') || 'Actions'}</th>
          </tr>
        </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-slate-800">
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center">
                    <Loader2 className="w-6 h-6 animate-spin text-indigo-500 mx-auto" />
                    <p className="text-gray-500 dark:text-slate-400 mt-2">{t('loadingDeployments') || 'Loading deployments...'}</p>
                  </td>
                </tr>
              ) : deployments.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center text-gray-500 dark:text-slate-400">
                    {t('noDeployments') || 'No deployments found.'}
                  </td>
                </tr>
              ) : (
                deployments.map((dep) => (
                  <React.Fragment key={dep.id}>
                    <tr
                      className={`transition-colors cursor-pointer ${expandedRows.has(dep.id) ? 'bg-indigo-50/30 dark:bg-indigo-500/5' : 'hover:bg-gray-50 dark:hover:bg-slate-900/50'}`}
                      onClick={() => dep.isMultiCluster && toggleRow(dep.id)}
                    >
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-3">
                          <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${dep.isMultiCluster ? 'bg-amber-50 dark:bg-amber-500/10' : 'bg-indigo-50 dark:bg-indigo-500/10'}`}>
                            <GitMerge className={`w-4 h-4 ${dep.isMultiCluster ? 'text-amber-600 dark:text-amber-400' : 'text-indigo-600 dark:text-indigo-400'}`} />
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <div className="font-semibold text-gray-900 dark:text-white">{dep.modelName}</div>
                              {dep.isMultiCluster && (
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 dark:bg-amber-500/20 text-amber-600 dark:text-amber-400 uppercase tracking-wider border border-amber-200 dark:border-amber-500/30">Multi</span>
                              )}
                            </div>
                            <div className="text-xs text-gray-500 dark:text-slate-400">{dep.id}</div>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        {dep.isMultiCluster ? (
                          <div className="flex items-center gap-1">
                            {dep.clusterGroups?.map(g => (
                              <div key={g.clusterId} className="w-2 h-2 rounded-full bg-indigo-500" title={g.clusterId}></div>
                            ))}
                            <span className="text-xs text-indigo-600 dark:text-indigo-400 font-medium ml-1">Across {dep.clusterGroups?.length} clusters</span>
                          </div>
                        ) : (
                          <div className="text-gray-600 dark:text-slate-300">{dep.clusterId}</div>
                        )}
                      </td>
                      <td className="px-6 py-4">
                        <div className="text-gray-900 dark:text-white">{dep.team}</div>
                        <div className="text-xs text-gray-500 dark:text-slate-400">{dep.product}</div>
                      </td>
                      <td className="px-6 py-4 text-gray-600 dark:text-slate-300">{dep.replicas}</td>
                      <td className="px-6 py-4">
                        <StatusBadge status={dep.status} />
                      </td>
                      <td className="px-6 py-4 text-gray-600 dark:text-slate-300">{timeAgo(dep.createdAt)}</td>
                      <td className="px-6 py-4 text-right" onClick={e => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-1.5 flex-wrap">
                          {dep.status === 'running' && (
                            <>
                              <button
                                onClick={() => setManagingTokensFor(dep)}
                                className="p-2 text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors"
                                title="Manage API Tokens"
                              >
                                <Key className="w-4 h-4" />
                              </button>
                              <button
                                onClick={() => openChat(dep)}
                                className="p-2 text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors"
                                title="Test Model (Chat)"
                              >
                                <MessageSquare className="w-4 h-4" />
                              </button>

                              {/* Model Access to Teams */}
                              <button
                                onClick={() => {
                                  setAccessControlDep(dep);
                                  setSelectedTeams(['engineering', 'research']);
                                }}
                                className="p-2 text-gray-400 hover:text-emerald-600 dark:hover:text-emerald-400 transition-colors"
                                title="Доступ к модели по командам"
                              >
                                <Users className="w-4 h-4" />
                              </button>

                              {/* Kubernetes Logs */}
                              <button
                                onClick={() => setLogsDep(dep)}
                                className="p-2 text-gray-400 hover:text-cyan-600 dark:hover:text-cyan-450 transition-colors"
                                title="Логи из кубов"
                              >
                                <Terminal className="w-4 h-4" />
                              </button>
                            </>
                          )}

                          {/* Redeploy Button */}
                          <button
                            onClick={() => handleRedeploy(dep.id)}
                            className={`p-2 text-gray-400 hover:text-amber-600 dark:hover:text-amber-400 transition-colors ${redeployingId === dep.id ? 'animate-spin text-amber-500' : ''}`}
                            title="Переразвернуть деплоймент"
                            disabled={redeployingId === dep.id}
                          >
                            <RefreshCw className="w-4 h-4" />
                          </button>

                          <button
                            onClick={() => setManagingPolicy(dep)}
                            className="p-2 text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors"
                            title="Autoscaling Policy"
                          >
                            <SlidersHorizontal className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => setViewingDep(dep)}
                            className="p-2 text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors"
                            title="View Details"
                          >
                            <Eye className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => setConfirmDeleteId(dep.id)}
                            className="p-2 text-gray-400 hover:text-red-600 dark:hover:text-red-400 transition-colors"
                            title={language === 'ru' ? 'Удалить деплоймент' : 'Delete Deployment'}
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                    {expandedRows.has(dep.id) && dep.clusterGroups?.map((group) => (
                      <tr key={`${dep.id}-${group.clusterId}`} className="bg-gray-50/50 dark:bg-slate-900/30 border-l-4 border-l-indigo-500">
                        <td className="px-6 py-3 pl-12">
                          <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Instance</div>
                          <div className="text-sm font-medium text-gray-900 dark:text-white">{dep.modelName}</div>
                        </td>
                        <td className="px-6 py-3">
                          <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Cluster</div>
                          <div className="text-sm font-medium text-gray-900 dark:text-white">{group.clusterId}</div>
                        </td>
                        <td className="px-6 py-3" colSpan={2}>
                          <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Replicas</div>
                          <div className="text-sm font-medium text-gray-900 dark:text-white">{group.replicas}</div>
                        </td>
                        <td className="px-6 py-3">
                          <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Status</div>
                          <StatusBadge status={group.status} />
                        </td>
                        <td className="px-6 py-3 text-right" colSpan={2}>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setManagingNode({ dep, group });
                            }}
                            className="text-xs font-semibold text-indigo-600 dark:text-indigo-400 hover:underline"
                          >
                            Manage Node
                          </button>
                        </td>
                      </tr>
                    ))}
                  </React.Fragment>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* View Modal */}
      {viewingDep && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-slate-950 rounded-xl border border-gray-200 dark:border-slate-800 shadow-xl w-full max-w-2xl overflow-hidden">
            <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-slate-800">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{t('deploymentDetails') || 'Deployment Details'}</h3>
              <button
                onClick={() => setViewingDep(null)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-6 space-y-6">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-xs text-gray-500 dark:text-slate-400 mb-1">Model</div>
                  <div className="font-medium text-gray-900 dark:text-white">{viewingDep.modelName}</div>
                </div>
                <div>
                  <div className="text-xs text-gray-500 dark:text-slate-400 mb-1">Status</div>
                  <StatusBadge status={viewingDep.status} />
                </div>
                <div>
                  <div className="text-xs text-gray-500 dark:text-slate-400 mb-1">Cluster</div>
                  <div className="font-medium text-gray-900 dark:text-white">{viewingDep.clusterId}</div>
                </div>
                <div>
                  <div className="text-xs text-gray-500 dark:text-slate-400 mb-1">Team</div>
                  <div className="font-medium text-gray-900 dark:text-white">{viewingDep.team}</div>
                </div>
              </div>

              {viewingDep.status === 'running' && (
                <div className="space-y-2">
                  <div className="text-sm font-medium text-gray-900 dark:text-white">API Usage</div>
                  <div className="relative group">
                    <div className="absolute right-2 top-2">
                      <button
                        onClick={() => handleCopy(viewingDep)}
                        className="p-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-md transition-colors"
                      >
                        {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
                      </button>
                    </div>
                    <pre className="bg-slate-950 text-slate-300 p-4 rounded-lg text-xs font-mono overflow-x-auto border border-slate-800">
                      <code>
                        curl http://{viewingDep.clusterId}:11434/api/chat -d '{`{"model":"${viewingDep.modelName}","messages":[{"role":"user","content":"Hello"}]}`}'
                      </code>
                    </pre>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {managingNode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-slate-950 rounded-xl border border-gray-200 dark:border-slate-800 shadow-xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[85vh]">
            <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-slate-800 bg-gray-50/50 dark:bg-slate-900/50">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{t('manageNode') || 'Manage Node'}</h3>
                <p className="text-xs font-medium text-gray-500 mt-1">{managingNode.dep.modelName} &bull; {managingNode.group.clusterId}</p>
              </div>
              <button
                onClick={() => setManagingNode(null)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 bg-gray-100 p-2 rounded-lg dark:bg-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-6 space-y-8">
               {/* Node Info */}
               <div className="space-y-4">
                  <h4 className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                     <Server className="w-4 h-4 text-indigo-500" />
                     Node Information
                  </h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      {/* Node name */}
                      <div className="p-4 bg-gray-50 dark:bg-slate-900/50 rounded-xl border border-gray-100 dark:border-slate-800">
                         <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Instance Host</div>
                         <div className="text-sm font-semibold text-gray-900 dark:text-white truncate">node-{managingNode.group.clusterId.split('-').pop() || '01'}-01</div>
                      </div>
                      <div className="p-4 bg-gray-50 dark:bg-slate-900/50 rounded-xl border border-gray-100 dark:border-slate-800">
                         <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Cluster</div>
                         <div className="text-sm font-semibold text-gray-900 dark:text-white truncate">{managingNode.group.clusterId}</div>
                      </div>
                      <div className="p-4 bg-gray-50 dark:bg-slate-900/50 rounded-xl border border-gray-100 dark:border-slate-800">
                         <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">GPU Type</div>
                         <div className="text-sm font-semibold text-gray-900 dark:text-white truncate">
                           {managingNode.group.clusterId.includes('gpu') ? 'NVIDIA A100' : 'NVIDIA T4'}
                         </div>
                      </div>
                      <div className="p-4 bg-gray-50 dark:bg-slate-900/50 rounded-xl border border-gray-100 dark:border-slate-800">
                         <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Current Load</div>
                         <div className="flex items-center gap-2">
                            <Activity className="w-4 h-4 text-emerald-500" />
                            <div className="text-sm font-semibold text-gray-900 dark:text-white">78%</div>
                         </div>
                      </div>
                  </div>
               </div>

               {/* Replicas Info */}
               <div className="space-y-4">
                  <div className="flex items-center justify-between">
                     <h4 className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                        <Cpu className="w-4 h-4 text-indigo-500" />
                        Replicas ({managingNode.group.replicas})
                     </h4>
                     <span className="text-[10px] font-medium text-gray-500 bg-gray-100 dark:bg-slate-800 px-2 py-1 rounded">Autoscaling Active</span>
                  </div>

                  <div className="border border-gray-200 dark:border-slate-800 rounded-xl overflow-hidden bg-white dark:bg-slate-950">
                     <table className="w-full text-left text-sm">
                        <thead className="bg-gray-50 dark:bg-slate-900/50 text-xs font-semibold text-gray-500 uppercase tracking-wider border-b border-gray-200 dark:border-slate-800">
                           <tr>
                              <th className="px-4 py-3">Replica ID</th>
                              <th className="px-4 py-3 text-right">Status</th>
                           </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-200 dark:divide-slate-800">
                           {Array.from({ length: managingNode.group.replicas }).map((_, i) => (
                              <tr key={i} className="hover:bg-gray-50/50 dark:hover:bg-slate-900/30 transition-colors">
                                 <td className="px-4 py-3">
                                    <div className="font-medium text-gray-900 dark:text-white">replica-{i}</div>
                                    <div className="text-[10px] text-gray-500 font-mono mt-0.5">{managingNode.dep.id}-rev{i}</div>
                                 </td>
                                 <td className="px-4 py-3 text-right">
                                    <StatusBadge status={managingNode.group.status} />
                                 </td>
                              </tr>
                           ))}
                        </tbody>
                     </table>
                  </div>
               </div>
            </div>
          </div>
        </div>
      )}

      {managingPolicy && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-slate-950 rounded-xl border border-gray-200 dark:border-slate-800 shadow-xl w-full max-w-lg overflow-hidden flex flex-col">
            <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-slate-800 bg-gray-50/50 dark:bg-slate-900/50">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{t('autoscalingPolicy') || 'Autoscaling Policy'}</h3>
                <p className="text-xs font-medium text-gray-500 mt-1">{managingPolicy.modelName} &bull; {managingPolicy.id}</p>
              </div>
              <button
                onClick={() => setManagingPolicy(null)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 bg-gray-100 p-2 rounded-lg dark:bg-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-6">
              {/* Current Scaling State */}
              <div className="bg-slate-50 dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-xl p-4 space-y-4">
                <div className="flex items-center justify-between border-b border-gray-100 dark:border-slate-800/60 pb-2">
                  <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider">{t('currentScalingState') || 'Current Scaling State'}</h4>
                  <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                    {t('stableMatch') || 'Stable (Match desired)'}
                  </span>
                </div>

                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                  <div>
                    <div className="text-[10px] text-gray-500 mb-1 font-medium uppercase">{t('currentReplicas') || 'Current Replicas'}</div>
                    <div className="text-lg font-bold text-gray-900 dark:text-white">{managingPolicy.replicas || 1}</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-gray-500 mb-1 font-medium uppercase">{t('activeRequests') || 'Active Requests'}</div>
                    <div className="text-lg font-bold text-indigo-600 dark:text-indigo-400">{Math.floor(Math.random() * 50) + 10}</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-gray-500 mb-1 font-medium uppercase">{t('queueLength') || 'Queue Length'}</div>
                    <div className="text-lg font-bold text-amber-600 dark:text-amber-400">{Math.floor(Math.random() * 20)}</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-gray-500 mb-1 font-medium uppercase">{t('avgTokensSec') || 'Avg Tokens/Sec'}</div>
                    <div className="text-lg font-bold text-emerald-600 dark:text-emerald-400">{Math.floor(Math.random() * 500) + 100}</div>
                  </div>
                </div>

                {/* HPA Trigger Condition details */}
                <div className="p-3 bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800/80 rounded-lg text-[11px] text-gray-600 dark:text-slate-400 space-y-1">
                  <div className="flex justify-between items-center text-xs font-semibold text-gray-800 dark:text-slate-200 mb-1">
                     <span>{t('hpaRuleAssessment') || 'HPA Rule Assessment'}</span>
                     <span className="text-gray-400 font-normal">Every 15s</span>
                  </div>
                  <div className="flex justify-between">
                     <span>Target metric evaluation:</span>
                     <span className="font-mono">queue_length avg (1.2) &lt; threshold (10.0)</span>
                  </div>
                  <div className="flex justify-between">
                     <span>Last scale event:</span>
                     <span className="text-gray-500 dark:text-slate-500">None inside cooldown window (cooldown left: 0s)</span>
                  </div>
                </div>

                {/* Active instances / pods */}
                <div className="space-y-2 mt-2">
                  <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">{t('activeReplicaPods') || 'Active Replica Pods & Telemetry'}</span>
                  <div className="grid grid-cols-1 gap-2 max-h-[160px] overflow-y-auto custom-scrollbar">
                     {Array.from({ length: managingPolicy.replicas || 1 }).map((_, i) => {
                       const podHash = `${managingPolicy.id.slice(-3)}-${100 + i}`;
                       const hasGpu = managingPolicy.isMultiCluster
                         ? (managingPolicy.clusterGroups?.some(g => g.clusterId.toLowerCase().includes('gpu')) ?? false)
                         : (managingPolicy.clusterId?.toLowerCase().includes('gpu') ?? false);

                       const gpuLoad = 60 + (i * 12) + Math.floor(Math.random() * 8);
                       const cpuLoad = 8 + i * 3;

                       const ramUsageLimit = 32; // 32 GB system RAM
                       const ramUsageVal = (14.2 + i * 2.1 + (i % 2) * 1.5).toFixed(1);

                       const vramUsageLimit = hasGpu ? (managingPolicy.clusterId?.toLowerCase().includes('01') || managingPolicy.clusterGroups?.some(g => g.clusterId.toLowerCase().includes('01')) ? 80 : 16) : 0;
                       const vramUsageVal = hasGpu ? (vramUsageLimit * (0.65 + i * 0.05 + 0.02)).toFixed(1) : "0";

                       return (
                         <div key={i} className="flex items-center justify-between p-2 rounded-lg border border-gray-100 dark:border-slate-800/60 bg-white/60 dark:bg-slate-950/40 text-[10px] font-mono">
                           <div className="flex items-center gap-2">
                             <div className="w-1.5 h-1.5 rounded-full bg-emerald-500"></div>
                             <span className="font-semibold text-gray-700 dark:text-slate-300">pod-{podHash}</span>
                           </div>
                           <div className="flex items-center gap-3 text-gray-500 dark:text-slate-400">
                             {hasGpu ? (
                               <>
                                 <span title="GPU Load">GPU: <strong className="text-indigo-600 dark:text-indigo-400 font-bold">{gpuLoad}%</strong></span>
                                 <span title="VRAM Memory">VRAM: <strong className="text-violet-600 dark:text-violet-400 font-semibold">{vramUsageVal}/{vramUsageLimit}GB</strong></span>
                               </>
                             ) : (
                               <span className="text-gray-400 dark:text-slate-500 italic">No GPU</span>
                             )}
                             <span title="CPU Load">CPU: <strong className="font-semibold text-gray-700 dark:text-slate-300">{cpuLoad}%</strong></span>
                             <span title="System RAM">RAM: <strong className="text-emerald-600 dark:text-emerald-400 font-semibold">{ramUsageVal}/{ramUsageLimit}GB</strong></span>
                             <span className="text-gray-400 hidden sm:inline">Uptime: 2d 4h</span>
                           </div>
                         </div>
                       );
                     })}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-700 dark:text-slate-300 mb-1 uppercase tracking-wider">Min Replicas</label>
                  <input type="number" defaultValue={1} className="w-full rounded-lg border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white" />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-700 dark:text-slate-300 mb-1 uppercase tracking-wider">Max Replicas</label>
                  <input type="number" defaultValue={5} className="w-full rounded-lg border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white" />
                </div>
              </div>

              <div>
                 <label className="block text-xs font-semibold text-gray-700 dark:text-slate-300 mb-1 uppercase tracking-wider">Metric</label>
                 <select className="w-full rounded-lg border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white">
                   <option value="queue_length">Queue Length (vllm:num_requests_waiting)</option>
                   <option value="tokens_per_second">Tokens per Second</option>
                 </select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-700 dark:text-slate-300 mb-1 uppercase tracking-wider">Target Value</label>
                  <input type="number" defaultValue={10} className="w-full rounded-lg border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white" />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-700 dark:text-slate-300 mb-1 uppercase tracking-wider">Cooldown (sec)</label>
                  <input type="number" defaultValue={60} className="w-full rounded-lg border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white" />
                </div>
              </div>

              {managingPolicy.isMultiCluster && (
                <div>
                   <label className="block text-xs font-semibold text-gray-700 dark:text-slate-300 mb-1 uppercase tracking-wider">Overflow Cluster Priority</label>
                   <p className="text-[10px] text-gray-500 mb-2">Drag to reorder clusters when primary reaches Max Replicas.</p>
                   <div className="space-y-2">
                      {managingPolicy.clusterGroups?.map((g: any, i: number) => (
                         <div key={g.clusterId} className="px-3 py-2 bg-gray-50 dark:bg-slate-900/50 border border-gray-200 dark:border-slate-800 rounded-lg text-sm font-medium text-gray-700 dark:text-slate-300 flex items-center gap-2">
                           <span className="text-[10px] text-gray-400">{i + 1}.</span> {g.clusterId}
                         </div>
                      ))}
                   </div>
                </div>
              )}

              <div className="pt-4 flex justify-end gap-3 border-t border-gray-100 dark:border-slate-800">
                 <button onClick={() => setManagingPolicy(null)} className="px-4 py-2 border border-gray-300 dark:border-slate-800 rounded-lg text-sm font-medium hover:bg-gray-50 dark:hover:bg-slate-900 transition-colors">Cancel</button>
                 <button onClick={() => setManagingPolicy(null)} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium shadow-sm transition-colors">Save Policy</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Chat Modal */}
      {chattingDep && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-slate-950 rounded-xl border border-gray-200 dark:border-slate-800 shadow-xl w-full max-w-2xl overflow-hidden flex flex-col h-[600px]">
            {/* Header */}
            <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-slate-800 bg-gray-50 dark:bg-slate-900/50">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-indigo-100 dark:bg-indigo-500/20 flex items-center justify-center">
                  <Bot className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-white">{chattingDep.modelName}</h3>
                  <p className="text-xs text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                    Online ({chattingDep.clusterId})
                  </p>
                </div>
              </div>
              <button
                onClick={() => setChattingDep(null)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Messages Area */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar bg-gray-50/50 dark:bg-slate-950/50">
              {messages.map((msg, idx) => (
                <div key={idx} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  {msg.role === 'assistant' && (
                    <div className="w-8 h-8 rounded-full bg-indigo-100 dark:bg-indigo-500/20 flex items-center justify-center flex-shrink-0">
                      <Bot className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                    </div>
                  )}
                  <div className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm ${
                    msg.role === 'user'
                      ? 'bg-indigo-600 text-white rounded-br-sm'
                      : 'bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 text-gray-900 dark:text-slate-200 rounded-bl-sm shadow-sm'
                  }`}>
                    {msg.content}
                  </div>
                  {msg.role === 'user' && (
                    <div className="w-8 h-8 rounded-full bg-gray-200 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
                      <User className="w-4 h-4 text-gray-500 dark:text-slate-400" />
                    </div>
                  )}
                </div>
              ))}
              {isTyping && (
                <div className="flex gap-3 justify-start">
                  <div className="w-8 h-8 rounded-full bg-indigo-100 dark:bg-indigo-500/20 flex items-center justify-center flex-shrink-0">
                    <Bot className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                  </div>
                  <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm flex items-center gap-1">
                    <div className="w-1.5 h-1.5 bg-gray-400 dark:bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                    <div className="w-1.5 h-1.5 bg-gray-400 dark:bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                    <div className="w-1.5 h-1.5 bg-gray-400 dark:bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input Area */}
            <div className="p-4 bg-white dark:bg-slate-950 border-t border-gray-200 dark:border-slate-800">
              <form onSubmit={handleSendMessage} className="flex gap-3">
                <input
                  type="text"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  placeholder="Type a message to test the model..."
                  className="flex-1 rounded-lg border border-gray-300 dark:border-slate-700 bg-gray-50 dark:bg-slate-900 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white"
                />
                <button
                  type="submit"
                  disabled={!chatInput.trim() || isTyping}
                  className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 dark:disabled:bg-indigo-800 text-white p-2.5 rounded-lg transition-colors flex items-center justify-center"
                >
                  <Send className="w-5 h-5" />
                </button>
              </form>
            </div>
          </div>
        </div>
      )}

      {accessControlDep && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-slate-950 rounded-xl border border-gray-200 dark:border-slate-800 shadow-xl w-full max-w-md overflow-hidden flex flex-col">
            <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-slate-800 bg-gray-50/50 dark:bg-slate-900/50">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Доступ к модели по командам</h3>
                <p className="text-xs font-medium text-gray-500 mt-1">{accessControlDep.modelName}</p>
              </div>
              <button
                onClick={() => setAccessControlDep(null)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 bg-gray-100 p-2 rounded-lg dark:bg-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-6">
              <div>
                <label className="block text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Выберите команды для предоставления доступа</label>
                <div className="space-y-2 max-h-[160px] overflow-y-auto custom-scrollbar pr-1">
                  {[
                    { id: 'engineering', label: 'Engineering' },
                    { id: 'research', label: 'AI Research' },
                    { id: 'data_science', label: 'Data Science' },
                    { id: 'devops', label: 'DevOps & SRE' },
                    { id: 'product', label: 'Product Analytics' },
                    { id: 'qa', label: 'Quality Assurance' }
                  ].map(team => {
                    const checked = selectedTeams.includes(team.id);
                    return (
                      <label
                        key={team.id}
                        className={`flex items-center justify-between p-2.5 rounded-lg border transition-all cursor-pointer ${
                          checked
                            ? 'bg-emerald-50/50 dark:bg-emerald-500/5 border-emerald-200 dark:border-emerald-500/20 text-gray-950 dark:text-white'
                            : 'bg-white dark:bg-slate-900 border-gray-100 dark:border-slate-800 text-gray-600 dark:text-slate-350 hover:bg-gray-50 dark:hover:bg-slate-900/40'
                        }`}
                      >
                        <span className="text-sm font-medium">{team.label}</span>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => {
                            if (checked) {
                              setSelectedTeams(selectedTeams.filter(t => t !== team.id));
                            } else {
                              setSelectedTeams([...selectedTeams, team.id]);
                            }
                          }}
                          className="rounded text-emerald-600 focus:ring-emerald-500 h-4 w-4 border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900"
                        />
                      </label>
                    );
                  })}
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Уровень привилегий доступа</label>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    onClick={() => setAccessLevel('inference')}
                    className={`p-3 rounded-lg border text-left transition-all ${
                      accessLevel === 'inference'
                        ? 'border-indigo-500 bg-indigo-50/40 dark:bg-indigo-500/5 ring-2 ring-indigo-500/20'
                        : 'border-gray-200 dark:border-slate-800 hover:bg-gray-50 dark:hover:bg-slate-900/30'
                    }`}
                  >
                    <div className="font-semibold text-xs text-gray-900 dark:text-white">Inference Only</div>
                    <div className="text-[10px] text-gray-500 mt-1">Доступ только к API инференса и тестированию в чате</div>
                  </button>
                  <button
                    onClick={() => setAccessLevel('admin')}
                    className={`p-3 rounded-lg border text-left transition-all ${
                      accessLevel === 'admin'
                        ? 'border-indigo-500 bg-indigo-50/40 dark:bg-indigo-500/5 ring-2 ring-indigo-500/20'
                        : 'border-gray-200 dark:border-slate-800 hover:bg-gray-50 dark:hover:bg-slate-900/30'
                    }`}
                  >
                    <div className="font-semibold text-xs text-gray-900 dark:text-white">Full Admin Access</div>
                    <div className="text-[10px] text-gray-500 mt-1">Управление токенами, перезапуском и политиками масштабирования</div>
                  </button>
                </div>
              </div>

              <div className="pt-4 flex justify-end gap-3 border-t border-gray-100 dark:border-slate-800">
                <button
                  onClick={() => setAccessControlDep(null)}
                  className="px-4 py-2 border border-gray-300 dark:border-slate-800 rounded-lg text-sm font-medium hover:bg-gray-50 dark:hover:bg-slate-900 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    setSuccessNotification(`Access policy updated for model ${accessControlDep.modelName}. Granted access to ${selectedTeams.length} teams.`);
                    setAccessControlDep(null);
                    setTimeout(() => setSuccessNotification(null), 4000);
                  }}
                  disabled={selectedTeams.length === 0}
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-55 text-white rounded-lg text-sm font-medium shadow-sm transition-colors"
                >
                  Сохранить настройки
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {logsDep && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-slate-950 rounded-xl border border-gray-200 dark:border-slate-800 shadow-xl w-full max-w-3xl overflow-hidden flex flex-col h-[580px]">
            <div className="flex items-center justify-between p-5 border-b border-gray-200 dark:border-slate-800 bg-gray-50/50 dark:bg-slate-900/50">
              <div className="flex items-center gap-2">
                <Terminal className="w-5 h-5 text-indigo-500 animate-pulse" />
                <div>
                  <h3 className="text-sm font-bold text-gray-900 dark:text-white">Консоль логов из kubernetes</h3>
                  <p className="text-xs text-gray-505 dark:text-slate-400">{logsDep.modelName} &bull; {logsDep.id}</p>
                </div>
              </div>
              <button
                onClick={() => setLogsDep(null)}
                className="text-gray-400 hover:text-gray-650 dark:hover:text-gray-250 bg-gray-100 p-2 rounded-lg dark:bg-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Pod Selector / Action Rail */}
            <div className="p-3 bg-gray-50 dark:bg-slate-900 border-b border-gray-200 dark:border-slate-800/80 flex flex-wrap items-center justify-between gap-2.5">
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider">Выбор подов:</span>
                <div className="flex items-center gap-1.5">
                  {['all', 'pod-01', 'pod-02', 'pod-03'].map(pId => (
                    <button
                      key={pId}
                      onClick={() => {
                        // simulate tab change
                        const simulatedElement = document.getElementById('log-scroller');
                        if (simulatedElement) {
                          simulatedElement.innerHTML += `<div class="text-indigo-400 font-mono text-[11px] py-1">--- Switching stream view to: ${pId} ---</div>`;
                        }
                      }}
                      className="px-2.5 py-1 rounded text-[11px] font-semibold tracking-wide border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 text-gray-700 dark:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-900 transition-colors"
                    >
                      {pId === 'all' ? 'All Pods' : pId}
                    </button>
                  ))}
                </div>
              </div>

              <button
                onClick={() => {
                  const logEl = document.getElementById('log-scroller');
                  if (logEl) {
                    const time = new Date().toLocaleTimeString();
                    logEl.innerHTML += `
                      <div class="text-emerald-400">[${time}] [K8S-HEALTH] Replica check completed successfully. 0 workloads throttled.</div>
                      <div class="text-gray-300">[${time}] [API] GET /metrics 200 OK - 8.2ms</div>
                    `;
                    logEl.scrollTop = logEl.scrollHeight;
                  }
                }}
                className="px-3 py-1 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold rounded shadow-sm flex items-center gap-1.5 transition-colors"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Обновить
              </button>
            </div>

            {/* Terminal area */}
            <div className="flex-1 bg-slate-950 p-4 font-mono text-[11px] text-gray-300 overflow-y-auto space-y-1 custom-scrollbar select-text" id="log-scroller">
              <div className="text-gray-500"># kubectl logs -l app=deployment-{logsDep.id.slice(-5)} --tail=100 -f</div>

              <div className="text-indigo-400">--- Pod startup sequence initialization (Deployment: {logsDep.id}) ---</div>
              <div className="text-emerald-500">[2026-05-19 21:30:11] [k8s-agent] Scheduled pod-{logsDep.id.slice(-3)}-101 on node-01-gpu</div>
              <div className="text-emerald-500">[2026-05-19 21:30:12] [k8s-agent] Pulling lightweight model tensors image registry.local/models/{logsDep.modelName}:latest</div>
              <div className="text-gray-400">[2026-05-19 21:30:18] [k8s-agent] Successfully pulled image. Container initialized.</div>
              <div className="text-slate-200">[2026-05-19 21:30:20] [pod-101-vllm] INFO vllm.entrypoints.openai.api_server: args=Namespace(host='0.0.0.0', port=11434, model='{logsDep.modelName}')</div>
              <div className="text-slate-200">[2026-05-19 21:30:22] [pod-101-vllm] INFO vllm.config: Dataset and weights matched. Loading tensor allocations...</div>
              <div className="text-slate-200">[2026-05-19 21:31:02] [pod-101-vllm] INFO vllm.engine.llm_engine: Initializing cache engine with block_size=16, num_gpu_blocks=4310</div>
              <div className="text-slate-100">[2026-05-19 21:31:05] [pod-101-vllm] INFO vllm.entrypoints.openai.api_server: Model is ready! Serving HTTP requests at port 11434</div>

              <div className="text-amber-400">[2026-05-19 21:40:02] [vllm-engine] WARNING kv_cache: KV cache utilization is at 82.5%. Auto-eviction scheduler enabled.</div>
              <div className="text-gray-300">[2026-05-19 21:42:10] [pod-101-api] POST /api/chat 11434 status=200 ok (TTFT: 12.3ms, tokens/sec: 84.1)</div>
              <div className="text-gray-300">[2026-05-19 21:42:15] [pod-101-api] POST /api/chat 11434 status=200 ok (TTFT: 11.8ms, tokens/sec: 86.3)</div>
              <div className="text-indigo-400">[2026-05-19 21:44:00] [k8s-agent] Cluster sync-agent metrics reported healthy. 3 total pods ready.</div>
              <div className="text-gray-400">[2026-05-19 21:44:30] [pod-102-vllm] INFO loading: Replica synced with master node. Warmup inference PASS.</div>
            </div>

            <div className="p-4 bg-gray-50 dark:bg-slate-900 border-t border-gray-200 dark:border-slate-800 flex justify-end">
              <button
                onClick={() => setLogsDep(null)}
                className="px-4 py-2 bg-slate-850 hover:bg-slate-800 text-gray-800 dark:text-white border border-gray-200 dark:border-slate-850 rounded-lg text-xs font-semibold"
              >
                Close Console
              </button>
            </div>
          </div>
        </div>
      )}

      {managingTokensFor && (
        <TokenManagerModal
          deployment={managingTokensFor}
          onClose={() => setManagingTokensFor(null)}
        />
      )}

      {confirmDeleteId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl p-6 max-w-sm w-full shadow-2xl space-y-4">
            <div className="flex items-center gap-3 text-red-500">
              <AlertCircle className="w-6 h-6 shrink-0 animate-bounce" />
              <h3 className="text-base font-bold text-gray-900 dark:text-white">
                {language === 'ru' ? 'Вы уверены?' : 'Are you sure?'}
              </h3>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed font-sans">
              {language === 'ru'
                ? `Вы действительно хотите безвозвратно удалить развертывание модели "${confirmDeleteId}"? Данное действие немедленно остановит инференс и удалит поды кластера.`
                : `Are you sure you want to permanently delete deployment "${confirmDeleteId}"? This will immediately stop inference proxies and terminate the runner replica pods.`
              }
            </p>
            <div className="flex items-center gap-3">
              <button
                onClick={() => setConfirmDeleteId(null)}
                className="flex-1 py-2 px-3 bg-gray-100 dark:bg-slate-800 text-gray-800 dark:text-white rounded-lg text-xs font-semibold hover:bg-gray-200 dark:hover:bg-slate-700 transition font-sans"
              >
                {language === 'ru' ? 'Отмена' : 'Cancel'}
              </button>
              <button
                onClick={async () => {
                  const id = confirmDeleteId;
                  setConfirmDeleteId(null);
                  await handleDelete(id);
                }}
                className="flex-1 py-2 px-3 bg-red-650 dark:bg-red-600 hover:bg-red-700 text-white rounded-lg text-xs font-semibold transition bg-red-600 font-sans"
              >
                {language === 'ru' ? 'Удалить' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
