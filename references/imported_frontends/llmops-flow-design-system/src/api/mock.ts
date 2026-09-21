import {
  collection,
  getDocs,
  getDoc,
  doc,
  addDoc,
  setDoc,
  updateDoc,
  deleteDoc,
  query,
  where,
  orderBy,
  Timestamp,
  serverTimestamp
} from 'firebase/firestore';
import { db, auth } from '../lib/firebase';

export type DeploymentStatus = 'pending' | 'pulling' | 'running' | 'failed';

export interface PodStatus {
  name: string;
  status: 'pending' | 'pulling' | 'running' | 'failed';
  progress: number;
  stage?: string;
}

export interface ClusterGroup {
  clusterId: string;
  replicas: number;
  status: DeploymentStatus;
  progress: number;
  message?: string;
  pods?: PodStatus[];
}

export interface Deployment {
  id: string;
  modelName: string;
  modelVersion: string;
  clusterId: string;
  replicas: number;
  status: DeploymentStatus;
  message?: string;
  createdAt: string;
  team: string;
  product: string;
  ownerId: string;
  isMultiCluster?: boolean;
  clusterGroups?: ClusterGroup[];
}

export interface ReleaseMetric {
  latencyP99: number;
  errorRate: number;
  throughput: number;
}

export interface ReleaseStep {
  percent: number;
  timestamp?: string;
  status: 'pending' | 'completed' | 'active';
  metrics?: ReleaseMetric;
}

export interface ReleaseEvent {
  timestamp: string;
  type: 'info' | 'warning' | 'error' | 'action';
  message: string;
}

export interface Release {
  id: string;
  name: string;
  sourceId: string;
  targetId: string;
  routeId: string;
  strategy: 'canary' | 'blue-green' | 'linear';
  status: 'rolling' | 'paused' | 'succeeded' | 'failed' | 'rolled-back';
  currentPercent: number;
  targetPercent: number;
  sloHealthy: boolean;
  currentMetrics: ReleaseMetric;
  sourceMetrics: ReleaseMetric;
  createdAt: string;
  type: 'standard' | 'migration';
  sourceCluster?: string;
  targetCluster?: string;
  steps: ReleaseStep[];
  events: ReleaseEvent[];
}

export interface RouteBackend {
  deploymentId: string;
  clusterId: string;
  weight: number;
}

export interface TrafficRoute {
  id: string;
  name: string;
  backends: RouteBackend[];
}

export interface Quota {
  id: string;
  subjectType: 'team' | 'user';
  subjectId: string;
  subjectName: string;
  model: string; // Model name or 'all'
  limitValue: number;
  limitUnit: 'tokens' | 'requests';
  period: 'hour' | 'day' | 'month';
  action: 'block' | 'throttle' | 'warn';
  priority: number;
  usageValue: number;
  usageCost: number;
  status: 'active' | 'throttled' | 'blocked';
  clusterId: string;
}

export interface EnergyTelemetry {
  deployment_id: string;
  model_name: string;
  model_version: string;
  inference_mode: 'cpu' | 'gpu';
  cluster_id: string;
  node_name: string;
  device_type: string;
  timestamp: string;
  power_watts_current: number;
  gpu_utilization_percent: number;
  cpu_utilization_percent: number;
  ram_used_bytes: number;
  vram_used_bytes: number;
  energy_kwh_1h: number;
  energy_kwh_24h: number;
  energy_kwh_period: number;
  uptime_seconds: number;
  requests_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  tokens_per_second: number;
  energy_per_request_wh: number;
  energy_per_1k_tokens_wh: number;
  cost_per_request: number;
  cost_per_1k_tokens: number;
  electricity_price_per_kwh: number;
  currency: string;
  cost_1h: number;
  cost_24h: number;
  cost_period_total: number;
  data_source: string;
  is_estimated: boolean;
  last_updated_at: string;
  sampling_interval_sec: number;
}

export interface NodeMetrics {
  node_name: string;
  cpu_percent: number;
  ram_percent: number;
  gpu_percent: number;
  power_watts: number;
  status: 'online' | 'offline';
}

export interface EnergyTimeSeries {
  timestamp: string;
  power_watts: number;
  cost: number;
  cpu_percent?: number;
  gpu_percent?: number;
  ram_percent?: number;
}

export interface CostEntry {
  id: string;
  deploymentId: string;
  modelName: string;
  team: string;
  product: string;
  inputTokens: number;
  outputTokens: number;
  inferenceCost: number;
  electricityCost: number;
  energyKWh: number;
  clusterId: string;
  timestamp: string;
  ownerId: string;
}

export interface PlatformRates {
  electricityPriceKWh: number;
}

export interface ModelRate {
  modelName: string;
  inputPricePer1M: number;
  outputPricePer1M: number;
  wattsPerReplica: number;
}

export type PlatformRole = 'admin' | 'developer' | 'manager' | 'viewer';
export type TeamRole = 'owner' | 'manager' | 'member' | 'viewer';

export interface UserTeamMembership {
  teamId: string;
  role: TeamRole;
}

export interface User {
  id: string;
  name: string;
  email: string;
  role: PlatformRole; // Global role
  memberships: UserTeamMembership[];
  allowedClusters: string[]; // Global cluster restrictions (for admins/trans-team users)
  createdAt: string;
}

export interface Team {
  id: string;
  name: string;
  memberCount: number;
  deploymentIds: string[];
  allowedClusters: string[]; // Which clusters this team can operate in
}

export interface Permission {
  id: string;
  category: string;
  name: string;
  label: string;
  description: string;
}

export interface RolePermissions {
  roleId: string;
  permissions: string[]; // Permission IDs
}

// MOCK DATA ARRAYS
const MOCK_USERS: User[] = [
  {
    id: 'u-1',
    name: 'Ivan Petrov',
    email: 'ivan@example.com',
    role: 'admin',
    memberships: [{ teamId: 't-1', role: 'owner' }],
    allowedClusters: [],
    createdAt: '2024-01-10T12:00:00Z'
  },
  {
    id: 'u-2',
    name: 'Elena Sidorova',
    email: 'elena@example.com',
    role: 'developer',
    memberships: [
      { teamId: 't-1', role: 'member' },
      { teamId: 't-3', role: 'manager' }
    ],
    allowedClusters: ['msk-gpu-01'],
    createdAt: '2024-02-15T09:30:00Z'
  },
  {
    id: 'u-3',
    name: 'Alex Smith',
    email: 'alex@example.com',
    role: 'viewer',
    memberships: [{ teamId: 't-2', role: 'viewer' }],
    allowedClusters: [],
    createdAt: '2024-03-20T15:45:00Z'
  },
];

const MOCK_TEAMS: Team[] = [
  { id: 't-1', name: 'Core AI', memberCount: 12, deploymentIds: ['dep-1', 'dep-m-1'], allowedClusters: ['msk-gpu-01', 'spb-cpu-01'] },
  { id: 't-2', name: 'Support', memberCount: 5, deploymentIds: [], allowedClusters: ['spb-cpu-01'] },
  { id: 't-3', name: 'Analytics', memberCount: 8, deploymentIds: [], allowedClusters: [] },
];

const MOCK_PERMISSIONS: Permission[] = [
  { id: 'p-1', category: 'Deployments', name: 'view', label: 'View Deployments', description: 'Can view deployment list and status' },
  { id: 'p-2', category: 'Deployments', name: 'create', label: 'Create Deployments', description: 'Can create new deployments' },
  { id: 'p-3', category: 'Deployments', name: 'delete', label: 'Delete Deployments', description: 'Can delete existing deployments' },
  { id: 'p-4', category: 'Traffic', name: 'manage', label: 'Manage Routes', description: 'Can edit traffic weights and routes' },
  { id: 'p-5', category: 'Quotas', name: 'view', label: 'View Quotas', description: 'Can view quota usage' },
  { id: 'p-6', category: 'Quotas', name: 'edit', label: 'Edit Quotas', description: 'Can change limits' },
  { id: 'p-7', category: 'RBAC', name: 'manage', label: 'Manage Access', description: 'Can manage users, roles and teams' },
];

const MOCK_RATES: ModelRate[] = [
  { modelName: 'llama3:70b', inputPricePer1M: 65, outputPricePer1M: 180, wattsPerReplica: 650 },
  { modelName: 'llama3:8b', inputPricePer1M: 15, outputPricePer1M: 40, wattsPerReplica: 350 },
  { modelName: 'mistral:v0.3', inputPricePer1M: 10, outputPricePer1M: 30, wattsPerReplica: 250 },
  { modelName: 'phi3:mini', inputPricePer1M: 5, outputPricePer1M: 15, wattsPerReplica: 150 },
  { modelName: 'gemma:2b', inputPricePer1M: 3, outputPricePer1M: 8, wattsPerReplica: 100 },
];

const MOCK_DEPLOYMENTS: Deployment[] = [
  {
    id: 'dep-1',
    modelName: 'llama3:8b',
    modelVersion: 'latest',
    clusterId: 'msk-gpu-01',
    replicas: 2,
    status: 'running',
    createdAt: new Date(Date.now() - 86400000 * 2).toISOString(),
    team: 'Core AI',
    product: 'Search SDK',
    ownerId: 'mock-user'
  },
  {
    id: 'dep-m-1',
    modelName: 'mistral:v0.3',
    modelVersion: 'v0.3',
    clusterId: 'multi',
    replicas: 6,
    status: 'running',
    createdAt: new Date(Date.now() - 86400000 * 5).toISOString(),
    team: 'Support',
    product: 'HelpBot',
    ownerId: 'mock-user',
    isMultiCluster: true,
    clusterGroups: [
      {
        clusterId: 'msk-gpu-01',
        replicas: 2,
        status: 'running',
        progress: 100,
        pods: [
          { name: 'pod-msk-101', status: 'running', progress: 100, stage: 'Healthy' },
          { name: 'pod-msk-102', status: 'running', progress: 100, stage: 'Healthy' }
        ]
      },
      {
        clusterId: 'spb-gpu-02',
        replicas: 4,
        status: 'running',
        progress: 100,
        pods: [
          { name: 'pod-spb-101', status: 'running', progress: 100, stage: 'Healthy' },
          { name: 'pod-spb-102', status: 'running', progress: 100, stage: 'Healthy' },
          { name: 'pod-spb-103', status: 'running', progress: 100, stage: 'Healthy' },
          { name: 'pod-spb-104', status: 'running', progress: 100, stage: 'Healthy' }
        ]
      }
    ]
  },
  { id: 'dep-3', modelName: 'phi3:mini', modelVersion: 'latest', clusterId: 'kazan-cpu-01', replicas: 1, status: 'running', createdAt: new Date().toISOString(), team: 'Internal', product: 'Slack App', ownerId: 'mock-user' },
];

export const MOCK_RELEASES: Release[] = [
  {
    id: 'rel-1',
    name: 'llama3-upgrade',
    sourceId: 'dep-1',
    targetId: 'dep-4',
    routeId: 'route-1',
    strategy: 'canary',
    status: 'rolling',
    currentPercent: 30,
    targetPercent: 100,
    sloHealthy: true,
    currentMetrics: { latencyP99: 185, errorRate: 0.01, throughput: 1200 },
    sourceMetrics: { latencyP99: 210, errorRate: 0.05, throughput: 1150 },
    createdAt: new Date(Date.now() - 3600000).toISOString(),
    type: 'standard',
    steps: [
      { percent: 10, status: 'completed', timestamp: new Date(Date.now() - 3000000).toISOString(), metrics: { latencyP99: 190, errorRate: 0.02, throughput: 1100 } },
      { percent: 30, status: 'active', timestamp: new Date(Date.now() - 1500000).toISOString() },
      { percent: 60, status: 'pending' },
      { percent: 100, status: 'pending' }
    ],
    events: [
      { timestamp: new Date(Date.now() - 3600000).toISOString(), type: 'info', message: 'Release initialized' },
      { timestamp: new Date(Date.now() - 3500000).toISOString(), type: 'info', message: 'Step 1 (10%) started' },
      { timestamp: new Date(Date.now() - 3000000).toISOString(), type: 'info', message: 'Step 1 completed successfully' },
      { timestamp: new Date(Date.now() - 3000000).toISOString(), type: 'info', message: 'Step 2 (30%) started' }
    ]
  },
  {
    id: 'rel-2',
    name: 'msk-to-spb-migration',
    sourceId: 'dep-1',
    targetId: 'dep-2',
    routeId: 'route-1',
    strategy: 'linear',
    status: 'rolled-back',
    currentPercent: 0,
    targetPercent: 100,
    sloHealthy: false,
    currentMetrics: { latencyP99: 850, errorRate: 15.2, throughput: 400 },
    sourceMetrics: { latencyP99: 210, errorRate: 0.05, throughput: 1400 },
    createdAt: new Date(Date.now() - 7200000).toISOString(),
    type: 'migration',
    sourceCluster: 'msk-gpu-01',
    targetCluster: 'spb-gpu-02',
    steps: [
      { percent: 10, status: 'completed', timestamp: new Date(Date.now() - 6500000).toISOString(), metrics: { latencyP99: 850, errorRate: 15.2, throughput: 400 } },
      { percent: 50, status: 'pending' },
      { percent: 100, status: 'pending' }
    ],
    events: [
      { timestamp: new Date(Date.now() - 7200000).toISOString(), type: 'info', message: 'Migration release initialized' },
      { timestamp: new Date(Date.now() - 6500000).toISOString(), type: 'error', message: 'SLO check failed: errorRate (15.2%) exceeded threshold (5.0%)' },
      { timestamp: new Date(Date.now() - 6400000).toISOString(), type: 'action', message: 'Automatic rollback initiated' },
      { timestamp: new Date(Date.now() - 6300000).toISOString(), type: 'info', message: 'Rollback complete' }
    ]
  }
];

export const MOCK_ROUTES: TrafficRoute[] = [
  {
    id: 'route-1',
    name: 'search-api-v1',
    backends: [
      { deploymentId: 'dep-1', clusterId: 'msk-gpu-01', weight: 85 },
      { deploymentId: 'dep-4', clusterId: 'msk-gpu-01', weight: 15 }
    ]
  }
];

export const MOCK_QUOTAS: Quota[] = [
  {
    id: 'q-1',
    subjectType: 'team',
    subjectId: 't-1',
    subjectName: 'Core AI',
    model: 'all',
    limitValue: 5000000000,
    limitUnit: 'tokens',
    period: 'month',
    action: 'throttle',
    priority: 10,
    usageValue: 2100000000,
    usageCost: 450000,
    status: 'active',
    clusterId: 'global'
  },
  {
    id: 'q-2',
    subjectType: 'team',
    subjectId: 't-2',
    subjectName: 'Support',
    model: 'mistral:v0.3',
    limitValue: 500000000,
    limitUnit: 'tokens',
    period: 'day',
    action: 'block',
    priority: 5,
    usageValue: 480000000,
    usageCost: 42000,
    status: 'active',
    clusterId: 'spb-gpu-02'
  },
];

const MOCK_PLATFORM_RATES: PlatformRates = {
  electricityPriceKWh: 8.5
};

const MOCK_COSTS: CostEntry[] = Array.from({ length: 120 }).map((_, i) => {
  const date = new Date();
  date.setHours(date.getHours() - i * 4);
  const clusterId = i % 3 === 0 ? 'msk-gpu-01' : i % 3 === 1 ? 'spb-gpu-02' : 'kazan-cpu-01';
  const infCost = 15 + Math.random() * 80;
  const energy = 2 + Math.random() * 10;
  return {
    id: `cost-${i}`,
    deploymentId: `dep-${(i % 4) + 1}`,
    modelName: (i % 4 === 0) ? 'llama3:8b' : (i % 4 === 1) ? 'mistral:v0.3' : (i % 4 === 2) ? 'phi3:mini' : 'llama3:70b',
    team: (i % 3 === 0) ? 'Core AI' : (i % 3 === 1) ? 'Support' : 'Analytics',
    product: 'System SDK',
    inputTokens: 4000 + Math.random() * 6000,
    outputTokens: 8000 + Math.random() * 12000,
    inferenceCost: infCost,
    electricityCost: energy * MOCK_PLATFORM_RATES.electricityPriceKWh,
    energyKWh: energy,
    clusterId,
    timestamp: date.toISOString(),
    ownerId: 'mock-user'
  };
});

// Error Handler
enum OperationType {
  CREATE = 'create',
  UPDATE = 'update',
  DELETE = 'delete',
  LIST = 'list',
  GET = 'get',
  WRITE = 'write',
}

interface FirestoreErrorInfo {
  error: string;
  operationType: OperationType;
  path: string | null;
  authInfo: {
    userId?: string | null;
    email?: string | null;
    emailVerified?: boolean | null;
    isAnonymous?: boolean | null;
    tenantId?: string | null;
    providerInfo?: {
      providerId?: string | null;
      email?: string | null;
    }[];
  }
}

function handleFirestoreError(error: unknown, operationType: OperationType, path: string | null) {
  const errInfo: FirestoreErrorInfo = {
    error: error instanceof Error ? error.message : String(error),
    authInfo: {
      userId: auth.currentUser?.uid,
      email: auth.currentUser?.email,
      emailVerified: auth.currentUser?.emailVerified,
      isAnonymous: auth.currentUser?.isAnonymous,
      tenantId: auth.currentUser?.tenantId,
      providerInfo: auth.currentUser?.providerData?.map(provider => ({
        providerId: provider.providerId,
        email: provider.email,
      })) || []
    },
    operationType,
    path
  };
  console.error('Firestore Error: ', JSON.stringify(errInfo));
  throw new Error(JSON.stringify(errInfo));
}

// Helpers
const toDoc = (id: string, data: any) => ({
  id,
  ...data,
  createdAt: data.createdAt instanceof Timestamp ? data.createdAt.toDate().toISOString() : data.createdAt,
  timestamp: data.timestamp instanceof Timestamp ? data.timestamp.toDate().toISOString() : data.timestamp,
  lastUpdated: data.lastUpdated instanceof Timestamp ? data.lastUpdated.toDate().toISOString() : data.lastUpdated,
});

export async function getDeployments(clusterId?: string): Promise<Deployment[]> {
  let items = MOCK_DEPLOYMENTS;

  if (auth.currentUser) {
    const path = 'deployments';
    try {
      const q = query(
        collection(db, path),
        where('ownerId', '==', auth.currentUser.uid),
        orderBy('createdAt', 'desc')
      );
      const snap = await getDocs(q);
      const dbItems = snap.docs.map(d => toDoc(d.id, d.data()) as Deployment);
      if (dbItems.length > 0) items = dbItems;
    } catch (error) {
      handleFirestoreError(error, OperationType.LIST, path);
    }
  }

  if (clusterId && clusterId !== 'all') {
    return items.filter(d => d.clusterId === clusterId);
  }
  return items;
}

export async function getDeployment(id: string): Promise<Deployment | undefined> {
  if (!auth.currentUser) return MOCK_DEPLOYMENTS.find(d => d.id === id);
  const path = `deployments/${id}`;
  try {
    const snap = await getDoc(doc(db, 'deployments', id));
    if (snap.exists() && snap.data().ownerId === auth.currentUser?.uid) {
      return toDoc(snap.id, snap.data()) as Deployment;
    }
    return MOCK_DEPLOYMENTS.find(d => d.id === id);
  } catch (error) {
    handleFirestoreError(error, OperationType.GET, path);
    return MOCK_DEPLOYMENTS.find(d => d.id === id);
  }
}

export async function createDeployment(data: Omit<Deployment, 'id' | 'status' | 'createdAt' | 'ownerId'>): Promise<Deployment> {
  if (!auth.currentUser) throw new Error('Not authenticated');
  const path = 'deployments';
  try {
    const groupPods = (clusterId: string, count: number) => {
      return Array.from({ length: count }).map((_, i) => ({
        name: `pod-${clusterId.split('-')[0]}-${101 + i}`,
        status: 'pending' as const,
        progress: 0,
        stage: 'Scheduled'
      }));
    };

    let clusterGroups = data.clusterGroups || [];
    if (data.isMultiCluster && clusterGroups.length > 0) {
      clusterGroups = clusterGroups.map(g => ({
        ...g,
        status: 'pending' as const,
        progress: 0,
        pods: groupPods(g.clusterId, g.replicas)
      }));
    }

    const docData = {
      ...data,
      clusterGroups,
      status: 'pending',
      createdAt: serverTimestamp(),
      ownerId: auth.currentUser.uid
    };
    const ref = await addDoc(collection(db, path), docData);

    // Simulate background transitions
    if (data.isMultiCluster && clusterGroups.length > 0) {
      // Step 1: pulling starts for first pod in each group
      setTimeout(async () => {
        try {
          const updatedGroups = clusterGroups.map(g => {
            const nextPods = [...(g.pods || [])];
            if (nextPods.length > 0) {
              nextPods[0] = { ...nextPods[0], status: 'pulling', progress: 20, stage: 'Downloading weights...' };
            }
            return {
              ...g,
              status: 'pulling' as const,
              progress: 10,
              pods: nextPods
            };
          });
          await updateDoc(doc(db, 'deployments', ref.id), { status: 'pulling', clusterGroups: updatedGroups });

          // Step 2: progress increases
          setTimeout(async () => {
            try {
              const updatedGroups2 = updatedGroups.map(g => {
                const nextPods = [...(g.pods || [])];
                if (nextPods.length > 0) {
                  nextPods[0] = { ...nextPods[0], status: 'pulling', progress: 65, stage: 'Extracting model...' };
                }
                if (nextPods.length > 1) {
                  nextPods[1] = { ...nextPods[1], status: 'pulling', progress: 15, stage: 'Pulling layers...' };
                }
                return {
                  ...g,
                  progress: 40,
                  pods: nextPods
                };
              });
              await updateDoc(doc(db, 'deployments', ref.id), { clusterGroups: updatedGroups2 });

              // Step 3: first pod finished, others pulling
              setTimeout(async () => {
                try {
                  const updatedGroups3 = updatedGroups2.map(g => {
                    const nextPods = [...(g.pods || [])];
                    if (nextPods.length > 0) {
                      nextPods[0] = { ...nextPods[0], status: 'running', progress: 100, stage: 'Healthy' };
                    }
                    if (nextPods.length > 1) {
                      nextPods[1] = { ...nextPods[1], status: 'pulling', progress: 75, stage: 'Verifying checksum...' };
                    }
                    // trigger rest if any
                    for (let pIndex = 2; pIndex < nextPods.length; pIndex++) {
                      nextPods[pIndex] = { ...nextPods[pIndex], status: 'pulling', progress: 30, stage: 'Pulling layers...' };
                    }
                    return {
                      ...g,
                      progress: 70,
                      pods: nextPods
                    };
                  });
                  await updateDoc(doc(db, 'deployments', ref.id), { clusterGroups: updatedGroups3 });

                  // Step 4: All pods running, deployment fully running
                  setTimeout(async () => {
                    try {
                      const updatedGroups4 = updatedGroups3.map(g => {
                        const nextPods = (g.pods || []).map(p => ({
                          ...p,
                          status: 'running' as const,
                          progress: 100,
                          stage: 'Healthy'
                        }));
                        return {
                          ...g,
                          status: 'running' as const,
                          progress: 100,
                          pods: nextPods
                        };
                      });
                      await updateDoc(doc(db, 'deployments', ref.id), { status: 'running', clusterGroups: updatedGroups4 });
                    } catch (e) {}
                  }, 3000);
                } catch (e) {}
              }, 3000);
            } catch (e) {}
          }, 3000);
        } catch (e) {}
      }, 2000);
    } else {
      // Simple single cluster transition
      setTimeout(async () => {
        try {
          await updateDoc(doc(db, 'deployments', ref.id), { status: 'pulling' });
          setTimeout(async () => {
            await updateDoc(doc(db, 'deployments', ref.id), { status: 'running' });
          }, 5000);
        } catch (e) {}
      }, 3000);
    }

    return {
      id: ref.id,
      ...data,
      clusterGroups,
      status: 'pending',
      createdAt: new Date().toISOString(),
      ownerId: auth.currentUser.uid
    };
  } catch (error) {
    handleFirestoreError(error, OperationType.CREATE, path);
    throw error;
  }
}

export async function deleteDeployment(id: string): Promise<void> {
  if (!auth.currentUser) return;
  const path = `deployments/${id}`;
  try {
    await deleteDoc(doc(db, 'deployments', id));
  } catch (error) {
    handleFirestoreError(error, OperationType.DELETE, path);
  }
}

export async function getModelRates(): Promise<ModelRate[]> {
  const path = 'rates';
  try {
    const snap = await getDocs(collection(db, path));
    if (snap.empty) return MOCK_RATES;
    return snap.docs.map(d => d.data() as ModelRate);
  } catch (error) {
    handleFirestoreError(error, OperationType.LIST, path);
    return MOCK_RATES;
  }
}

export async function getElectricityPrice(): Promise<number> {
  try {
    const snap = await getDoc(doc(db, 'config', 'global'));
    return snap.exists() ? snap.data().electricityPriceKwh : 7.2;
  } catch (error) {
    return 7.2;
  }
}

export async function getCostHistory(period: string, clusterId?: string): Promise<CostEntry[]> {
  let items = MOCK_COSTS;
  // Period filtering logic
  const now = new Date();
  const limitDate = new Date();
  if (period === '24h') limitDate.setHours(now.getHours() - 24);
  else if (period === '7d') limitDate.setDate(now.getDate() - 7);
  else if (period === '30d') limitDate.setDate(now.getDate() - 30);

  items = items.filter(i => new Date(i.timestamp) > limitDate);

  if (clusterId && clusterId !== 'all') {
    return items.filter(c => c.clusterId === clusterId);
  }
  return items;
}

export async function getPlatformRates(): Promise<PlatformRates> {
  return MOCK_PLATFORM_RATES;
}

export async function getEnergyTelemetry(clusterId?: string): Promise<EnergyTelemetry[]> {
  const deployments = await getDeployments(clusterId);
  const activeDeployments = deployments.filter(d => d.status === 'running' || d.id.startsWith('dep-'));
  const electricityPrice = await getElectricityPrice();
  const rates = await getModelRates();

  const nodes = ['node-a100-01', 'node-a100-02', 'node-t4-01', 'node-t4-02'];
  const devices = {
    'gpu-cluster-1': 'NVIDIA A100 80GB',
    'gpu-cluster-2': 'NVIDIA T4 16GB'
  };

  return activeDeployments.map((d, idx) => {
    const rate = rates.find(r => r.modelName === d.modelName) || { wattsPerReplica: 200, inputPricePer1M: 10, outputPricePer1M: 20 };
    const baseTime = d.createdAt ? new Date(d.createdAt).getTime() : Date.now() - 86400000;
    const uptimeHrs = (Date.now() - baseTime) / (1000 * 60 * 60);
    const power = rate.wattsPerReplica * d.replicas * (0.8 + Math.random() * 0.2);
    const energy1h = power / 1000;
    const energyPeriod = energy1h * uptimeHrs;
    const tokens = 250000 + Math.random() * 500000;

    return {
      deployment_id: d.id,
      model_name: d.modelName,
      model_version: d.modelVersion,
      inference_mode: 'gpu',
      cluster_id: d.clusterId,
      node_name: nodes[idx % nodes.length],
      device_type: devices[d.clusterId as keyof typeof devices] || 'Intel Xeon',
      timestamp: new Date().toISOString(),
      power_watts_current: power,
      gpu_utilization_percent: 30 + Math.random() * 50,
      cpu_utilization_percent: 10 + Math.random() * 15,
      ram_used_bytes: 16 * 1024 * 1024 * 1024,
      vram_used_bytes: 24 * 1024 * 1024 * 1024,
      energy_kwh_1h: energy1h,
      energy_kwh_24h: energy1h * 24,
      energy_kwh_period: energyPeriod,
      uptime_seconds: Math.floor(uptimeHrs * 3600),
      requests_count: Math.floor(tokens / 1000),
      prompt_tokens: Math.floor(tokens * 0.3),
      completion_tokens: Math.floor(tokens * 0.7),
      total_tokens: Math.floor(tokens),
      tokens_per_second: 20 + Math.random() * 20,
      energy_per_request_wh: (energyPeriod * 1000) / (tokens / 1000),
      energy_per_1k_tokens_wh: (energyPeriod * 1000) / (tokens / 1000),
      cost_per_request: (energyPeriod * electricityPrice) / (tokens / 1000),
      cost_per_1k_tokens: (energyPeriod * electricityPrice) / (tokens / 1000),
      electricity_price_per_kwh: electricityPrice,
      currency: 'RUB',
      cost_1h: energy1h * electricityPrice,
      cost_24h: energy1h * 24 * electricityPrice,
      cost_period_total: energyPeriod * electricityPrice,
      data_source: 'Prometheus',
      is_estimated: false,
      last_updated_at: new Date().toISOString(),
      sampling_interval_sec: 15
    };
  });
}

export async function getNodeMetrics(): Promise<NodeMetrics[]> {
  return [
    { node_name: 'node-a100-01', cpu_percent: 45 + Math.random() * 10, ram_percent: 60, gpu_percent: 85, power_watts: 450, status: 'online' },
    { node_name: 'node-a100-02', cpu_percent: 30, ram_percent: 45, gpu_percent: 70, power_watts: 380, status: 'online' },
    { node_name: 'node-t4-01', cpu_percent: 20, ram_percent: 30, gpu_percent: 40, power_watts: 180, status: 'online' },
    { node_name: 'node-t4-02', cpu_percent: 15, ram_percent: 25, gpu_percent: 10, power_watts: 120, status: 'online' },
  ];
}

export async function getEnergyHistory(period: string, clusterId?: string): Promise<EnergyTimeSeries[]> {
  const price = await getElectricityPrice();
  const data: EnergyTimeSeries[] = [];
  const hours = period === '24h' ? 24 : period === '1h' ? 12 : 72;
  const step = period === '1h' ? 5 : 60; // minutes
  const limit = hours * (60 / step);
  const start = new Date();
  start.setMinutes(start.getMinutes() - (limit * step));

  // Scale power based on cluster size if filtering
  let multiplier = 1;
  if (clusterId && clusterId !== 'all') multiplier = 0.3 + Math.random() * 0.2;

  for (let i = 0; i < limit; i++) {
    const time = new Date(start);
    time.setMinutes(time.getMinutes() + (i * step));
    const basePower = (700 + Math.random() * 500) * multiplier;
    const cpuVal = Math.floor(45 + Math.sin(i / 6) * 15 + Math.random() * 10);
    const gpuVal = Math.floor(55 + Math.cos(i / 4) * 20 + Math.random() * 12);
    const ramVal = Math.floor(65 + Math.sin(i / 10) * 5 + Math.random() * 5);
    data.push({
      timestamp: time.toISOString(),
      power_watts: basePower,
      cost: (basePower / 1000) * price,
      cpu_percent: Math.min(100, Math.max(0, cpuVal)),
      gpu_percent: Math.min(100, Math.max(0, gpuVal)),
      ram_percent: Math.min(100, Math.max(0, ramVal))
    });
  }
  return data;
}

export async function getCostSummary(clusterId?: string) {
  const costHistory = await getCostHistory('30d', clusterId);

  const inferenceCost = costHistory.reduce((sum, entry) => sum + entry.inferenceCost, 0);
  const totalTokens = costHistory.reduce((sum, entry) => sum + entry.inputTokens + entry.outputTokens, 0);
  const energyCost = costHistory.reduce((sum, entry) => sum + entry.electricityCost, 0);

  const totalCost = inferenceCost + energyCost;
  const daily: Record<string, number> = {};
  costHistory.forEach(entry => {
    const day = entry.timestamp.split('T')[0];
    daily[day] = (daily[day] || 0) + entry.inferenceCost + entry.electricityCost;
  });

  return {
    totalCost,
    inferenceCost,
    energyCost,
    totalTokens,
    chartData: Object.entries(daily).map(([date, cost]) => ({ date, cost })).sort((a, b) => a.date.localeCompare(b.date)),
    avgCostPerRequest: costHistory.length > 0 ? totalCost / costHistory.length : 0
  };
}

export async function updateModelRate(modelName: string, inputPrice: number, outputPrice: number, watts: number): Promise<void> {
  const path = `rates/${modelName}`;
  try {
    await setDoc(doc(db, 'rates', modelName), {
      modelName,
      inputPricePer1M: inputPrice,
      outputPricePer1M: outputPrice,
      wattsPerReplica: watts
    });
  } catch (error) {
    handleFirestoreError(error, OperationType.WRITE, path);
  }
}

export async function updateElectricityPrice(price: number): Promise<void> {
  const path = 'config/global';
  try {
    await setDoc(doc(db, 'config', 'global'), {
      electricityPriceKwh: price,
      lastUpdated: serverTimestamp()
    });
  } catch (error) {
    handleFirestoreError(error, OperationType.WRITE, path);
  }
}

export async function getReleases(clusterId?: string): Promise<Release[]> {
  let items = MOCK_RELEASES;
  if (clusterId && clusterId !== 'all') {
    return items.filter(r => r.sourceCluster === clusterId || r.targetCluster === clusterId);
  }
  return items;
}

export async function pauseRelease(id: string): Promise<void> {
  const rel = MOCK_RELEASES.find(r => r.id === id);
  if (rel) {
    rel.status = 'paused';
    rel.events.push({ timestamp: new Date().toISOString(), type: 'info', message: 'Manual pause initiated' });
  }
}

export async function resumeRelease(id: string): Promise<void> {
  const rel = MOCK_RELEASES.find(r => r.id === id);
  if (rel) {
    rel.status = 'rolling';
    rel.events.push({ timestamp: new Date().toISOString(), type: 'info', message: 'Release resumed' });
  }
}

export async function rollbackRelease(id: string): Promise<void> {
  const rel = MOCK_RELEASES.find(r => r.id === id);
  if (rel) {
    rel.status = 'rolled-back';
    rel.currentPercent = 0;
    rel.events.push({ timestamp: new Date().toISOString(), type: 'action', message: 'Manual rollback initiated' });
  }
}

export async function skipReleaseTo100(id: string): Promise<void> {
  const rel = MOCK_RELEASES.find(r => r.id === id);
  if (rel) {
    rel.status = 'succeeded';
    rel.currentPercent = 100;
    rel.events.push({ timestamp: new Date().toISOString(), type: 'action', message: 'Skipped to 100% traffic' });
  }
}

export async function deleteRelease(id: string): Promise<void> {
  const idx = MOCK_RELEASES.findIndex(r => r.id === id);
  if (idx > -1) {
    MOCK_RELEASES.splice(idx, 1);
  }
}

export async function retryRelease(id: string): Promise<void> {
  const rel = MOCK_RELEASES.find(r => r.id === id);
  if (rel) {
    rel.status = 'rolling';
    rel.currentPercent = 0;
    rel.steps.forEach(s => s.status = 'pending');
    rel.events.push({ timestamp: new Date().toISOString(), type: 'action', message: 'Manual retry initiated' });
  }
}

export async function startRelease(data: any): Promise<Release> {
  const newRel: Release = {
    id: `rel-${Date.now()}`,
    name: data.name,
    sourceId: data.sourceId,
    targetId: data.targetId,
    routeId: data.routeId,
    strategy: data.strategy,
    status: 'rolling',
    currentPercent: 0,
    targetPercent: 100,
    sloHealthy: true,
    currentMetrics: { latencyP99: 0, errorRate: 0, throughput: 0 },
    sourceMetrics: { latencyP99: 200, errorRate: 0.1, throughput: 1000 },
    createdAt: new Date().toISOString(),
    type: data.type || 'standard',
    steps: data.steps || [{ percent: 25, status: 'pending' }, { percent: 50, status: 'pending' }, { percent: 100, status: 'pending' }],
    events: [{ timestamp: new Date().toISOString(), type: 'info', message: 'Release started' }]
  };
  MOCK_RELEASES.unshift(newRel);
  return newRel;
}

export async function createQuota(data: any): Promise<Quota> {
  const newQuota: Quota = {
    id: `q-${Date.now()}`,
    ...data,
    usageValue: 0,
    usageCost: 0,
    status: 'active',
    clusterId: data.clusterId || 'global'
  };
  MOCK_QUOTAS.unshift(newQuota);
  return newQuota;
}

export async function updateQuota(id: string, data: any): Promise<Quota> {
  const index = MOCK_QUOTAS.findIndex(q => q.id === id);
  if (index === -1) {
    throw new Error('Quota not found');
  }
  const updated: Quota = {
    ...MOCK_QUOTAS[index],
    ...data
  };
  MOCK_QUOTAS[index] = updated;
  return updated;
}

export async function deleteQuota(id: string): Promise<boolean> {
  const index = MOCK_QUOTAS.findIndex(q => q.id === id);
  if (index !== -1) {
    MOCK_QUOTAS.splice(index, 1);
    return true;
  }
  return false;
}

export async function getQuotas(clusterId?: string): Promise<Quota[]> {
  let items = MOCK_QUOTAS;
  if (clusterId && clusterId !== 'all') {
    return items.filter(q => q.clusterId === clusterId || q.clusterId === 'global');
  }
  return items;
}

export interface TechnicalToken {
  id: string;
  name?: string;
  token: string;
  model: string;
  cluster: string;
  deploymentId: string;
  createdAt: string;
  expiresAt: string;
  status: 'active' | 'revoked' | 'expired';
}

const MOCK_TOKENS: TechnicalToken[] = [
  {
    id: 'tok-1',
    name: 'Production Access Key',
    token: 'ctx_mocktoken123',
    model: 'llama3:8b',
    cluster: 'msk-gpu-01',
    deploymentId: 'dep-1',
    createdAt: new Date(Date.now() - 86400000 * 2).toISOString(),
    expiresAt: new Date(Date.now() + 86400000 * 5).toISOString(),
    status: 'active'
  }
];

export async function getTokens(deploymentId?: string): Promise<TechnicalToken[]> {
  const now = new Date().toISOString();
  // Update expired statuses
  MOCK_TOKENS.forEach(t => {
    if (t.status === 'active' && t.expiresAt !== 'never' && t.expiresAt < now) {
      t.status = 'expired';
    }
  });

  if (deploymentId && deploymentId !== 'all') {
    return MOCK_TOKENS.filter(t => t.deploymentId === deploymentId);
  }
  return MOCK_TOKENS;
}

export async function createToken(data: { name?: string, model: string, cluster: string, deploymentId: string, expiresInDays: number }): Promise<TechnicalToken> {
  const now = Date.now();
  const expiresAt = data.expiresInDays === -1 ? 'never' : new Date(now + 86400000 * data.expiresInDays).toISOString();

  const newToken: TechnicalToken = {
    id: `tok-${Date.now()}`,
    name: data.name || 'Unnamed Token',
    token: 'ctx_' + Math.random().toString(36).substr(2, 12),
    model: data.model,
    cluster: data.cluster,
    deploymentId: data.deploymentId,
    createdAt: new Date(now).toISOString(),
    expiresAt,
    status: 'active'
  };
  MOCK_TOKENS.unshift(newToken);
  return newToken;
}

export async function revokeToken(id: string): Promise<void> {
  const t = MOCK_TOKENS.find(tk => tk.id === id);
  if (t) {
    t.status = 'revoked';
  }
}

export async function deleteToken(id: string): Promise<void> {
  const idx = MOCK_TOKENS.findIndex(tk => tk.id === id);
  if (idx > -1) {
    MOCK_TOKENS.splice(idx, 1);
  }
}

export interface ClusterNode {
  id: string;
  name: string;
  clusterId: string;
  type: 'gpu' | 'cpu';
  gpuModel?: string;
  allocatable: {
    cpu: number;
    ram: number;
    gpu: number;
  };
  used: {
    cpu: number;
    ram: number;
    gpu: number;
  };
  deployments: string[];
  isDeployable: boolean;
  status: 'ready' | 'not-ready';
}

const MOCK_NODES: ClusterNode[] = [
  {
    id: 'n-1',
    name: 'gpu-node-01',
    clusterId: 'msk-gpu-01',
    type: 'gpu',
    gpuModel: 'NVIDIA A100 80GB',
    allocatable: { cpu: 64, ram: 512, gpu: 8 },
    used: { cpu: 24, ram: 128, gpu: 6 },
    deployments: ['dep-1', 'dep-m-1'],
    isDeployable: true,
    status: 'ready'
  },
  {
    id: 'n-2',
    name: 'gpu-node-02',
    clusterId: 'msk-gpu-01',
    type: 'gpu',
    gpuModel: 'NVIDIA A100 80GB',
    allocatable: { cpu: 64, ram: 512, gpu: 8 },
    used: { cpu: 12, ram: 64, gpu: 2 },
    deployments: [],
    isDeployable: true,
    status: 'ready'
  },
  {
    id: 'n-3',
    name: 'gpu-node-03',
    clusterId: 'spb-gpu-02',
    type: 'gpu',
    gpuModel: 'NVIDIA T4 16GB',
    allocatable: { cpu: 32, ram: 128, gpu: 4 },
    used: { cpu: 28, ram: 110, gpu: 4 },
    deployments: ['dep-m-1'],
    isDeployable: false,
    status: 'ready'
  },
  {
    id: 'n-4',
    name: 'cpu-node-01',
    clusterId: 'kazan-cpu-01',
    type: 'cpu',
    allocatable: { cpu: 128, ram: 1024, gpu: 0 },
    used: { cpu: 20, ram: 100, gpu: 0 },
    deployments: ['dep-3'],
    isDeployable: true,
    status: 'ready'
  }
];

export async function getNodes(clusterId?: string): Promise<ClusterNode[]> {
  if (clusterId && clusterId !== 'all') {
    return MOCK_NODES.filter(n => n.clusterId === clusterId);
  }
  return MOCK_NODES;
}

export async function getUsers(): Promise<User[]> {
  return MOCK_USERS;
}

export async function getTeams(): Promise<Team[]> {
  return MOCK_TEAMS;
}

export async function getPermissions(): Promise<Permission[]> {
  return MOCK_PERMISSIONS;
}
