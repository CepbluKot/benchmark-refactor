import React, { createContext, useContext, useState, ReactNode } from 'react';

export interface Cluster {
  id: string;
  name: string;
  region: string;
  provider: 'on-premise' | 'cloud';
  status: 'online' | 'degraded' | 'unreachable';
  type: 'gpu' | 'cpu' | 'hybrid';
  lastHeartbeat: string;
  nodeCount: number;
  gpuUsage: number;
  ramUsage: number;
  cpuUsage: number;
}

interface ClusterContextType {
  selectedClusterId: string;
  setSelectedClusterId: (id: string) => void;
  clusters: Cluster[];
}

const ClusterContext = createContext<ClusterContextType | undefined>(undefined);

export const clusters: Cluster[] = [
  { id: 'all', name: 'All Clusters', region: 'Global', provider: 'on-premise', status: 'online', type: 'hybrid', lastHeartbeat: new Date().toISOString(), nodeCount: 16, gpuUsage: 65, ramUsage: 45, cpuUsage: 35 },
  { id: 'msk-gpu-01', name: 'MSK-GPU-01', region: 'Moscow', provider: 'on-premise', status: 'online', type: 'gpu', lastHeartbeat: new Date().toISOString(), nodeCount: 4, gpuUsage: 82, ramUsage: 60, cpuUsage: 45 },
  { id: 'spb-gpu-02', name: 'SPB-GPU-02', region: 'St. Petersburg', provider: 'on-premise', status: 'degraded', type: 'gpu', lastHeartbeat: new Date(Date.now() - 45000).toISOString(), nodeCount: 4, gpuUsage: 95, ramUsage: 88, cpuUsage: 70 },
  { id: 'kazan-cpu-01', name: 'KZN-CPU-01', region: 'Kazan', provider: 'on-premise', status: 'online', type: 'cpu', lastHeartbeat: new Date().toISOString(), nodeCount: 8, gpuUsage: 0, ramUsage: 30, cpuUsage: 25 },
];

export function ClusterProvider({ children }: { children: ReactNode }) {
  const [selectedClusterId, setSelectedClusterId] = useState<string>('all');

  return (
    <ClusterContext.Provider value={{ selectedClusterId, setSelectedClusterId, clusters }}>
      {children}
    </ClusterContext.Provider>
  );
}

export function useCluster() {
  const context = useContext(ClusterContext);
  if (context === undefined) {
    throw new Error('useCluster must be used within a ClusterProvider');
  }
  return context;
}
