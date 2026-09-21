import React, { useState, useEffect } from 'react';
import { Route as RouteIcon, Save, Users, Plus, Trash2, Hexagon, Play, ArrowRight, Gauge } from 'lucide-react';
import { getDeployments, Deployment, MOCK_ROUTES, TrafficRoute } from '../api/mock';
import { useCluster } from '../context/ClusterContext';
import { useLanguage } from '../context/LanguageContext';

export function TrafficManagement() {
  const { clusters } = useCluster();
  const { t } = useLanguage();
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [routes, setRoutes] = useState<TrafficRoute[]>(MOCK_ROUTES);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(MOCK_ROUTES[0].id);
  const selectedRoute = routes.find(r => r.id === selectedRouteId);

  const [isNewRouteOpen, setIsNewRouteOpen] = useState(false);

  useEffect(() => {
    async function load() {
      const deps = await getDeployments();
      setDeployments(deps);
    }
    load();
  }, []);

  const [testResult, setTestResult] = useState<any>(null);
  const [testing, setTesting] = useState(false);

  const handleTest = async () => {
    setTesting(true);
    await new Promise(r => setTimeout(r, 600));
    const randomBack = selectedRoute?.backends[Math.floor(Math.random() * (selectedRoute?.backends.length || 1))];
    const dep = deployments.find(d => d.id === randomBack?.deploymentId);
    setTestResult({
      id: Math.random().toString(36).substr(2, 9),
      deployment: dep?.modelName || 'Unknown',
      cluster: randomBack?.clusterId || 'Unknown',
      latency: 120 + Math.random() * 400
    });
    setTesting(false);
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-20">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{t('traffic')}</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">{t('trafficDesc') || 'Configure global ingress routing and cross-cluster traffic splits.'}</p>
        </div>
        <button
          onClick={() => setIsNewRouteOpen(true)}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-semibold transition-colors shadow-sm"
        >
          <Plus className="w-4 h-4" />
          {t('newRoute') || 'New Route'}
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Route Navigator */}
        <div className="lg:col-span-1 space-y-4">
          <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl shadow-sm overflow-hidden">
             <div className="p-4 border-b border-gray-200 dark:border-slate-800 bg-gray-50/50 dark:bg-slate-900/50">
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('activeRoutes') || 'Active Routes'}</h3>
             </div>
             <div className="p-2 space-y-1">
               {routes.map(route => (
                 <button
                   key={route.id}
                   onClick={() => setSelectedRouteId(route.id)}
                   className={`w-full flex items-center justify-between p-3 rounded-lg transition-colors ${
                     selectedRouteId === route.id
                       ? 'bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400'
                       : 'hover:bg-gray-50 dark:hover:bg-slate-900 text-gray-600 dark:text-slate-400'
                   }`}
                 >
                   <div className="flex items-center gap-3">
                     <RouteIcon className="w-4 h-4" />
                     <span className="text-sm font-bold">{route.name}</span>
                   </div>
                   <ArrowRight className="w-3.5 h-3.5 opacity-50" />
                 </button>
               ))}
             </div>
          </div>
        </div>

        {/* Route Editor */}
        <div className="lg:col-span-3 space-y-6">
          {selectedRoute ? (
             <>
               <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl shadow-sm overflow-hidden">
                 <div className="p-6 border-b border-gray-200 dark:border-slate-800 flex items-center justify-between">
                    <div>
                      <h2 className="text-lg font-semibold text-gray-900 dark:text-white">{selectedRoute.name}</h2>
                      <p className="text-xs text-gray-500 mt-0.5">API V1 Ingress Rule</p>
                    </div>
                    <div className="flex items-center gap-3">
                      <button
                        onClick={handleTest}
                        disabled={testing}
                        className="flex items-center gap-2 px-3 py-1.5 border border-gray-200 dark:border-slate-800 hover:bg-gray-50 dark:hover:bg-slate-900 text-gray-700 dark:text-slate-300 rounded-lg text-xs font-semibold transition-colors"
                      >
                        {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                        {t('testRequest') || 'Test Request'}
                      </button>
                      <button onClick={() => alert('Changes saved')} className="flex items-center gap-2 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-semibold transition-colors shadow-sm">
                        <Save className="w-3.5 h-3.5" />
                        {t('saveChanges') || 'Save Changes'}
                      </button>
                    </div>
                 </div>

                 <div className="p-6 space-y-8">
                    {/* Visualizer */}
                    <div className="flex items-center gap-4 h-12">
                      {selectedRoute.backends.map((backend, idx) => (
                        <div
                          key={idx}
                          className="h-full rounded-lg relative group overflow-hidden transition-all"
                          style={{ width: `${backend.weight}%` }}
                        >
                          <div className={`absolute inset-0 opacity-20 ${idx === 0 ? 'bg-indigo-500' : 'bg-emerald-500'}`}></div>
                          <div className={`absolute inset-0 border-b-2 ${idx === 0 ? 'border-indigo-500' : 'border-emerald-500'}`}></div>
                          <div className="absolute inset-0 flex items-center justify-center">
                            <span className="text-[10px] font-bold text-gray-900 dark:text-white">{backend.weight}%</span>
                          </div>
                        </div>
                      ))}
                    </div>

                    <div className="space-y-4">
                      <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wider">{t('backendsWeights') || 'Backends & Weights'}</h3>
                      <div className="space-y-3">
                        {selectedRoute.backends.map((backend, idx) => (
                          <div key={idx} className="flex items-center gap-4 p-4 bg-gray-50/50 dark:bg-slate-900/50 border border-gray-200 dark:border-slate-800 rounded-xl hover:border-indigo-300 dark:hover:border-indigo-500/30 transition-all">
                             <div className="w-10 h-10 rounded-lg bg-white dark:bg-slate-800 border border-gray-100 dark:border-slate-700 flex items-center justify-center shadow-sm">
                               <Hexagon className={`w-5 h-5 ${backend.clusterId === 'msk-gpu-01' ? 'text-indigo-500' : 'text-emerald-500'}`} />
                             </div>
                             <div className="flex-1 min-w-0">
                               <div className="flex items-center gap-2">
                                 <span className="text-sm font-semibold text-gray-900 dark:text-white truncate">
                                   {deployments.find(d => d.id === backend.deploymentId)?.modelName || backend.deploymentId}
                                 </span>
                                 <span className={`px-1.5 py-0.5 rounded text-[8px] font-semibold uppercase ${backend.clusterId === 'msk-gpu-01' ? 'bg-indigo-100 text-indigo-600' : 'bg-emerald-100 text-emerald-600'}`}>
                                   {backend.clusterId}
                                 </span>
                               </div>
                               <div className="text-[10px] text-gray-500 font-medium">{t('deployment') || 'Deployment'}: {backend.deploymentId}</div>
                             </div>
                             <div className="w-32 flex items-center gap-3">
                               <input
                                 type="range"
                                 className="w-full h-1 bg-gray-200 dark:bg-slate-800 rounded-full appearance-none accent-indigo-500"
                                 value={backend.weight}
                                 onChange={() => {}}
                               />
                               <span className="text-xs font-semibold text-gray-900 dark:text-white min-w-[30px]">{backend.weight}%</span>
                             </div>
                             <button onClick={() => alert('Removed backend')} className="p-2 text-gray-400 hover:text-red-500 transition-colors">
                               <Trash2 className="w-4 h-4" />
                             </button>
                          </div>
                        ))}
                        <button onClick={() => alert('Added new backend')} className="w-full py-3 border-2 border-dashed border-gray-200 dark:border-slate-800 rounded-xl text-xs font-bold text-gray-500 hover:border-indigo-500 hover:text-indigo-500 transition-all flex items-center justify-center gap-2">
                          <Plus className="w-4 h-4" />
                          {t('addCrossClusterBackend') || 'Add Cross-cluster Backend'}
                        </button>
                      </div>
                    </div>

                    {testResult && (
                      <div className="p-4 bg-slate-900 rounded-xl border border-slate-800 animate-in zoom-in-95 duration-200">
                        <div className="flex items-center justify-between mb-3 pb-2 border-b border-slate-800">
                          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">{t('testRequestTrace') || 'Test Request Trace'}</span>
                          <span className="text-[10px] text-slate-600 font-mono">ID: {testResult.id}</span>
                        </div>
                        <div className="flex items-center gap-8">
                          <div>
                            <div className="text-[10px] text-slate-500 uppercase font-bold tracking-tighter mb-1">{t('servedBy') || 'Served By'}</div>
                            <div className="text-sm font-bold text-white">{testResult.deployment}</div>
                          </div>
                          <div>
                            <div className="text-[10px] text-slate-500 uppercase font-bold tracking-tighter mb-1">{t('cluster')}</div>
                            <div className="text-sm font-bold text-indigo-400">{testResult.cluster}</div>
                          </div>
                          <div>
                            <div className="text-[10px] text-slate-500 uppercase font-bold tracking-tighter mb-1">{t('latency')}</div>
                            <div className="text-sm font-bold text-emerald-400">{testResult.latency.toFixed(0)}ms</div>
                          </div>
                        </div>
                      </div>
                    )}
                 </div>
               </div>
             </>
          ) : (
            <div className="flex items-center justify-center h-64 border-2 border-dashed border-gray-200 dark:border-slate-800 rounded-xl">
              <span className="text-gray-500 font-medium">{t('selectRouteConfig') || 'Select a route to configure traffic'}</span>
            </div>
          )}
        </div>
      </div>
      {isNewRouteOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-slate-950 rounded-xl border border-gray-200 dark:border-slate-800 shadow-xl w-full max-w-md overflow-hidden flex flex-col">
            <div className="p-6 border-b border-gray-200 dark:border-slate-800 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{t('createNewRoute') || 'Create New Route'}</h3>
              <button
                onClick={() => setIsNewRouteOpen(false)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 p-2 rounded-lg bg-gray-100 dark:bg-slate-800 transition-colors"
              >
                <Plus className="w-5 h-5 rotate-45" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="text-sm font-medium text-gray-700 dark:text-slate-300 block mb-1">{t('routeName') || 'Route Name'}</label>
                <input type="text" placeholder="e.g., api-v2-ingress" className="w-full rounded-lg border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white" />
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700 dark:text-slate-300 block mb-1">{t('domainPath') || 'Domain / Path'}</label>
                <input type="text" placeholder="e.g., api.cortex.dev/v2/*" className="w-full rounded-lg border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white" />
              </div>
              <p className="text-xs text-gray-500">{t('backendsConfiguredAfter') || 'Backends can be configured after route creation.'}</p>
            </div>
            <div className="p-6 border-t border-gray-200 dark:border-slate-800 bg-gray-50/50 dark:bg-slate-900/50 flex justify-end gap-3">
              <button
                onClick={() => setIsNewRouteOpen(false)}
                className="px-4 py-2 border border-gray-300 dark:border-slate-700 rounded-lg text-sm font-medium transition-colors hover:bg-gray-50 dark:text-white"
              >
                {t('cancel')}
              </button>
              <button
                onClick={() => {
                  alert('Route created');
                  setIsNewRouteOpen(false);
                }}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium transition-colors shadow-sm"
              >
                {t('createNewRoute') || 'Create Route'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Loader2(props: any) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
  );
}
