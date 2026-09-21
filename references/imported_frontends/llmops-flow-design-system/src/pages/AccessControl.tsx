import React, { useState, useEffect } from 'react';
import {
  Users,
  Plus,
  ShieldAlert,
  Hexagon,
  Globe,
  Search,
  X,
  ChevronRight,
  LayoutGrid,
  Shield,
  Package,
  Check,
  AlertCircle,
  Copy,
  Info,
  User as UserIcon,
  Box,
  Zap,
  Key,
  Loader2,
  Trash2,
  ChevronDown,
  Globe2
} from 'lucide-react';
import { useCluster } from '../context/ClusterContext';
import { useLanguage } from '../context/LanguageContext';
import {
  getUsers,
  getTeams,
  getPermissions,
  getModelRates,
  User,
  Team,
  Permission,
  PlatformRole,
  ModelRate,
  TeamRole
} from '../api/mock';
import { cn } from '../lib/utils';
import { motion, AnimatePresence } from 'motion/react';

type Tab = 'users' | 'teams' | 'roles';

import { FieldTooltip } from '../components/FieldTooltip';

export function AccessControl() {
  const { t } = useLanguage();
  const { clusters } = useCluster();
  const [activeTab, setActiveTab] = useState<Tab>('users');
  const [users, setUsers] = useState<User[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [selectedTeam, setSelectedTeam] = useState<Team | null>(null);
  const [showUserModal, setShowUserModal] = useState(false);
  const [showTeamModal, setShowTeamModal] = useState(false);
  const [showRoleModal, setShowRoleModal] = useState(false);

  const loadData = async () => {
    setLoading(true);
    const [u, t, p] = await Promise.all([
      getUsers(),
      getTeams(),
      getPermissions()
    ]);
    setUsers(u);
    setTeams(t);
    setPermissions(p);
    setLoading(false);
  };

  useEffect(() => {
    loadData();
  }, []);

  if (loading) {
    return <div className="flex items-center justify-center h-64"><Shield className="w-8 h-8 animate-pulse text-indigo-500" /></div>;
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{t('accessControl')}</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">{t('accessSub')}</p>
        </div>
        <div className="flex gap-3">
          <button className="px-4 py-2.5 border border-gray-300 dark:border-slate-700 hover:bg-gray-50 dark:hover:bg-slate-800 text-gray-700 dark:text-gray-300 rounded-lg text-sm font-medium transition-all">
            {t('audit')}
          </button>
          <button
            onClick={() => {
              if (activeTab === 'users') setShowUserModal(true);
              else if (activeTab === 'teams') setShowTeamModal(true);
              else if (activeTab === 'roles') setShowRoleModal(true);
            }}
            className={cn("px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium transition-all shadow-sm flex items-center gap-2", activeTab === 'tokens' && "hidden")}
          >
            <Plus className="w-4 h-4" />
            {activeTab === 'users' ? t('addUser') : activeTab === 'teams' ? t('newTeam') : t('createRole')}
          </button>
        </div>
      </div>

      {/* Internal Navigation Tabs */}
      <div className="flex items-center gap-1 p-1 bg-gray-100 dark:bg-slate-900/50 rounded-2xl w-fit border border-gray-200 dark:border-slate-800">
        <TabButton id="users" label={t('users')} icon={Users} active={activeTab === 'users'} onClick={() => setActiveTab('users')} />
        <TabButton id="teams" label={t('teams')} icon={LayoutGrid} active={activeTab === 'teams'} onClick={() => setActiveTab('teams')} />
        <TabButton id="roles" label={t('rolesPermissions')} icon={Shield} active={activeTab === 'roles'} onClick={() => setActiveTab('roles')} />
        <TabButton id="tokens" label={t('technicalTokens')} icon={Key} active={activeTab === 'tokens'} onClick={() => setActiveTab('tokens')} />
      </div>

      <div className="min-h-[600px]">
        {activeTab === 'users' && (
          <UsersTable users={users} teams={teams} onSelect={setSelectedUser} />
        )}
        {activeTab === 'teams' && (
          <TeamsList teams={teams} onSelect={setSelectedTeam} />
        )}
        {activeTab === 'roles' && (
          <RolesMatrix permissions={permissions} />
        )}
        {activeTab === 'tokens' && (
          <TokensList />
        )}
      </div>

      {/* User Sidebar Panel */}
      {selectedUser && (
        <UserPanel
          user={selectedUser}
          teams={teams}
          clusters={clusters}
          onClose={() => setSelectedUser(null)}
        />
      )}

      {/* Team Sidebar Panel */}
      {selectedTeam && (
          <TeamPanel
              team={selectedTeam}
              onClose={() => setSelectedTeam(null)}
          />
      )}

      {/* Modals */}
      {showUserModal && (
        <UserFormModal
          teams={teams}
          onClose={() => setShowUserModal(false)}
          onSuccess={() => {
            setShowUserModal(false);
            loadData();
          }}
        />
      )}
      {showTeamModal && (
        <TeamModal
          users={users}
          onClose={() => setShowTeamModal(false)}
          onSuccess={() => {
            setShowTeamModal(false);
            loadData();
          }}
        />
      )}
      {showRoleModal && (
        <RoleModal
          permissions={permissions}
          onClose={() => setShowRoleModal(false)}
          onSuccess={() => {
            setShowRoleModal(false);
            loadData();
          }}
        />
      )}
    </div>
  );
}

function TabButton({ id, label, icon: Icon, active, onClick }: any) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
        active
          ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-sm'
          : 'text-gray-500 hover:text-gray-700 dark:hover:text-slate-300'
      }`}
    >
      <Icon className="w-4 h-4" />
      {label}
    </button>
  );
}

function UsersTable({ users, teams, onSelect }: any) {
  const { t } = useLanguage();
  return (
    <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl shadow-sm overflow-hidden">
      <table className="w-full text-sm text-left border-collapse">
        <thead className="text-xs font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wider bg-gray-50 dark:bg-slate-900/50 border-b border-gray-200 dark:border-slate-800">
          <tr>
            <th className="px-6 py-4">{t('users')}</th>
            <th className="px-6 py-4">{t('platformRole')}</th>
            <th className="px-6 py-4">{t('memberships')}</th>
            <th className="px-6 py-4">{t('createdAt')}</th>
            <th className="px-6 py-4 text-right"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 dark:divide-slate-800">
          {users.map((user: User) => (
            <tr
              key={user.id}
              onClick={() => onSelect(user)}
              className="group hover:bg-gray-50 dark:hover:bg-slate-900/50 transition-colors cursor-pointer"
            >
              <td className="px-6 py-4">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-indigo-100 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 flex items-center justify-center font-bold text-sm">
                    {user.name.charAt(0)}
                  </div>
                  <div className="flex flex-col">
                    <span className="font-semibold text-gray-900 dark:text-white group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors">{user.name}</span>
                    <span className="text-xs text-gray-500 dark:text-slate-500 font-medium">{user.email}</span>
                  </div>
                </div>
              </td>
              <td className="px-6 py-4">
                <span className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider ${
                  user.role === 'admin' ? 'bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400' :
                  user.role === 'developer' ? 'bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400' :
                  user.role === 'viewer' ? 'bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-400' :
                  'bg-amber-50 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400'
                }`}>
                  {user.role}
                </span>
              </td>
              <td className="px-6 py-4">
                <div className="flex flex-wrap gap-1">
                  {user.memberships.map(m => (
                    <span key={m.teamId} className="px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-slate-900 text-gray-600 dark:text-slate-400 text-[10px] font-semibold uppercase tracking-wider">
                      {teams.find((team: any) => team.id === m.teamId)?.name} ({m.role})
                    </span>
                  ))}
                </div>
              </td>
              <td className="px-6 py-4 text-gray-500 dark:text-slate-500 text-xs">
                {new Date(user.createdAt).toLocaleDateString()}
              </td>
              <td className="px-6 py-4 text-right">
                <ChevronRight className="w-4 h-4 text-gray-400 group-hover:translate-x-1 transition-transform" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function UserPanel({ user, teams, clusters, onClose }: { user: User, teams: Team[], clusters: any[], onClose: () => void }) {
  const { t } = useLanguage();
  const [role, setRole] = useState<PlatformRole>(user.role);

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-white dark:bg-slate-950 shadow-2xl h-full flex flex-col border-l border-gray-200 dark:border-slate-800">
        <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-slate-800">
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">{t('userPanel')}</h2>
          <button onClick={onClose} className="p-2 hover:bg-gray-100 dark:hover:bg-slate-800 rounded-lg transition-colors">
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-8">
          <div className="flex items-center gap-4">
             <div className="w-14 h-14 rounded-xl bg-indigo-100 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 flex items-center justify-center font-bold text-xl shadow-inner uppercase">
                {user.name.charAt(0)}
              </div>
              <div>
                <h3 className="text-xl font-bold text-gray-900 dark:text-white">{user.name}</h3>
                <p className="text-sm text-gray-500 dark:text-slate-400 font-medium">{user.email}</p>
              </div>
          </div>

          <div className="space-y-6">
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-gray-700 dark:text-slate-300">{t('platformRole')}</label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as PlatformRole)}
                className="w-full bg-white dark:bg-slate-900 border border-gray-300 dark:border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all dark:text-white"
              >
                <option value="admin">Admin - Full system access</option>
                <option value="developer">Developer - Deploy and manage models</option>
                <option value="manager">Manager - Manage teams and quotas</option>
                <option value="viewer">Viewer - Read-only access</option>
              </select>
            </div>

            <div className="space-y-4">
               <div className="flex items-center justify-between">
                  <label className="text-sm font-medium text-gray-700 dark:text-slate-300">{t('memberships')}</label>
                  <button className="text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1">
                    <Plus className="w-4 h-4" />
                    {t('addMembership')}
                  </button>
               </div>
               <div className="space-y-2">
                  {user.memberships.map(m => {
                    const team = teams.find(t => t.id === m.teamId);
                    return (
                      <div key={m.teamId} className="flex items-center justify-between p-3 bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg">
                        <div className="flex flex-col">
                           <span className="text-sm font-medium text-gray-900 dark:text-white">{team?.name}</span>
                           <span className="text-xs text-gray-500">{m.role}</span>
                        </div>
                        <button className="p-1 hover:bg-gray-100 dark:hover:bg-slate-800 text-gray-400 hover:text-red-500 transition-colors rounded-md">
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    );
                  })}
               </div>
            </div>

            <div className="space-y-4 pt-4 border-t border-gray-100 dark:border-slate-800">
               <div className="flex items-center gap-2">
                  <Hexagon className="w-4 h-4 text-indigo-500" />
                  <label className="text-sm font-medium text-gray-700 dark:text-slate-300">{t('allowedClusters')}</label>
               </div>
               <div className="grid grid-cols-2 gap-3">
                  {clusters.filter(c => c.id !== 'all').map(c => (
                    <label key={c.id} className="flex items-center gap-3 p-3 bg-gray-50 dark:bg-slate-900 rounded-lg border border-gray-200 dark:border-slate-800 cursor-pointer hover:border-indigo-500 transition-colors">
                      <input type="checkbox" className="w-4 h-4 rounded border-gray-300 dark:border-slate-700 text-indigo-600 focus:ring-indigo-500" defaultChecked={user.allowedClusters.includes(c.id)} />
                      <span className="text-xs font-medium text-gray-700 dark:text-slate-300">{c.name}</span>
                    </label>
                  ))}
               </div>
            </div>
          </div>
        </div>

        <div className="p-6 border-t border-gray-200 dark:border-slate-800 flex gap-3">
          <button className="flex-1 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium transition-all shadow-sm">
            {t('saveChanges')}
          </button>
          <button onClick={onClose} className="px-6 py-2.5 border border-gray-300 dark:border-slate-700 hover:bg-gray-50 dark:hover:bg-slate-800 text-gray-700 dark:text-gray-300 rounded-lg text-sm font-medium transition-all">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function TeamsList({ teams, onSelect }: any) {
  const { t } = useLanguage();
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      {teams.map((team: Team) => (
        <div
          key={team.id}
          onClick={() => onSelect(team)}
          className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-xl p-6 shadow-sm hover:shadow-md hover:border-indigo-500/50 transition-all cursor-pointer group"
        >
          <div className="flex items-center justify-between mb-4">
            <div className="w-11 h-11 rounded-lg bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 flex items-center justify-center group-hover:scale-105 transition-transform">
              <LayoutGrid className="w-6 h-6" />
            </div>
            <span className="text-[10px] font-semibold text-gray-400 dark:text-slate-500 uppercase tracking-wider bg-gray-50 dark:bg-slate-900 px-2 py-1 rounded-lg border border-gray-100 dark:border-slate-800">
              ID: {team.id}
            </span>
          </div>
          <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-1 group-hover:text-indigo-600 transition-colors uppercase tracking-tight">{team.name}</h3>
          <div className="flex items-center gap-6 mt-6 pt-4 border-t border-gray-50 dark:border-slate-900">
            <div className="flex flex-col">
              <span className="text-[10px] font-semibold text-gray-400 dark:text-slate-500 uppercase tracking-wider">{t('members')}</span>
              <span className="text-xl font-bold text-gray-900 dark:text-white tabular-nums">{team.memberCount}</span>
            </div>
            <div className="w-px h-8 bg-gray-100 dark:bg-slate-800" />
            <div className="flex flex-col">
              <span className="text-[10px] font-semibold text-gray-400 dark:text-slate-500 uppercase tracking-wider">{t('deployments')}</span>
              <span className="text-xl font-bold text-gray-900 dark:text-white tabular-nums">{team.deploymentIds.length}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function TeamPanel({ team, onClose }: any) {
    const { t } = useLanguage();
    const { clusters } = useCluster();
    return (
        <div className="fixed inset-0 z-50 flex justify-end">
            <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
            <div className="relative w-full max-w-lg bg-white dark:bg-slate-950 shadow-2xl h-full flex flex-col border-l border-gray-200 dark:border-slate-800">
                <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-slate-800">
                    <h2 className="text-xl font-bold text-gray-900 dark:text-white">{t('teamPanel')}</h2>
                    <button onClick={onClose} className="p-2 hover:bg-gray-100 dark:hover:bg-slate-800 rounded-lg transition-colors">
                        <X className="w-5 h-5 text-gray-400" />
                    </button>
                </div>
                <div className="flex-1 overflow-y-auto p-6 space-y-8">
                    <div className="flex items-center gap-4">
                       <div className="w-14 h-14 rounded-xl bg-indigo-100 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 flex items-center justify-center font-bold text-xl shadow-inner">
                          <LayoutGrid className="w-7 h-7" />
                       </div>
                       <div>
                          <h3 className="text-xl font-bold text-gray-900 dark:text-white uppercase tracking-tight">{team.name}</h3>
                          <p className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider">Team ID: {team.id}</p>
                       </div>
                    </div>

                    <div className="space-y-3">
                        <button className="w-full flex items-center justify-between p-4 bg-gray-50 dark:bg-slate-900 border border-gray-100 dark:border-slate-800 rounded-xl hover:border-indigo-500 transition-all group">
                            <div className="flex items-center gap-3">
                                <Users className="w-4 h-4 text-gray-400 group-hover:text-indigo-500 transition-colors" />
                                <span className="text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">{t('manageMembers')}</span>
                            </div>
                            <span className="text-sm font-bold text-indigo-600">{team.memberCount}</span>
                        </button>
                        <button className="w-full flex items-center justify-between p-4 bg-gray-50 dark:bg-slate-900 border border-gray-100 dark:border-slate-800 rounded-xl hover:border-indigo-500 transition-all group">
                            <div className="flex items-center gap-3">
                                <Package className="w-4 h-4 text-gray-400 group-hover:text-indigo-500 transition-colors" />
                                <span className="text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">{t('deployments')}</span>
                            </div>
                            <span className="text-sm font-bold text-indigo-600">{team.deploymentIds.length}</span>
                        </button>
                    </div>

                    <div className="space-y-4 pt-4 border-t border-gray-100 dark:border-slate-800">
                        <div className="flex items-center gap-2">
                           <Hexagon className="w-4 h-4 text-indigo-500" />
                           <label className="text-sm font-semibold text-gray-700 dark:text-slate-300">Cluster Isolation</label>
                        </div>
                        <div className="grid grid-cols-1 gap-2">
                           {clusters.filter(c => c.id !== 'all').map(c => (
                             <label key={c.id} className="flex items-center justify-between p-3 bg-gray-50 dark:bg-slate-900 rounded-xl border border-gray-100 dark:border-slate-800 cursor-pointer hover:border-indigo-500 transition-colors">
                               <div className="flex items-center gap-3">
                                 <input type="checkbox" className="w-4 h-4 rounded border-gray-300 dark:border-slate-700 text-indigo-600 focus:ring-indigo-500" defaultChecked={team.allowedClusters?.includes(c.id)} />
                                 <div>
                                   <span className="text-xs font-semibold text-gray-700 dark:text-slate-300 uppercase tracking-tight block leading-none">{c.name}</span>
                                   <span className="text-[10px] text-gray-500 font-medium lowercase">{c.region}</span>
                                 </div>
                               </div>
                               <Globe2 className="w-3.5 h-3.5 text-gray-300" />
                             </label>
                           ))}
                        </div>
                    </div>
                </div>

                <div className="p-6 border-t border-gray-200 dark:border-slate-800 flex gap-3">
                  <button className="flex-1 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium transition-all shadow-sm">
                    {t('saveChanges')}
                  </button>
                </div>
            </div>
        </div>
    );
}

function RolesMatrix({ permissions }: { permissions: Permission[] }) {
  const { t } = useLanguage();
  const roles: PlatformRole[] = ['admin', 'developer', 'manager', 'viewer'];

  return (
    <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl shadow-sm overflow-hidden mt-6">
      <div className="p-6 border-b border-gray-100 dark:border-slate-800 bg-gray-50/50 dark:bg-slate-900/30">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">{t('permissionsMatrix')}</h2>
        <p className="text-sm text-gray-500 mt-1">Capabilities mapped to platform roles</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-center border-collapse">
          <thead className="bg-gray-50/50 dark:bg-slate-900/50">
            <tr className="text-xs font-semibold text-gray-500 uppercase tracking-wider border-b border-gray-100 dark:border-slate-800">
              <th className="px-6 py-4 text-left">{t('permission')}</th>
              {roles.map(r => (
                <th key={r} className="px-6 py-4">{r}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-slate-800">
            {permissions.map(p => (
              <tr key={p.id} className="hover:bg-gray-50/50 dark:hover:bg-slate-900/10 transition-colors">
                <td className="px-6 py-4 text-left">
                  <div className="flex flex-col">
                    <span className="text-sm font-semibold text-gray-900 dark:text-white">{p.label}</span>
                    <span className="text-xs font-medium text-gray-500">{p.description}</span>
                  </div>
                </td>
                {roles.map(r => (
                  <td key={`${p.id}-${r}`} className="px-6 py-4">
                    <PermissionCheck role={r} permId={p.id} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PermissionCheck({ role, permId }: any) {
  const hasPerm = (r: string, p: string) => {
    if (r === 'admin') return true;
    if (r === 'viewer') return p === 'p-1' || p === 'p-5';
    if (r === 'developer') return p !== 'p-7' && p !== 'p-6';
    if (r === 'manager') return p === 'p-1' || p === 'p-5' || p === 'p-7' || p === 'p-4';
    return false;
  };

  const active = hasPerm(role, permId);
  return (
    <div className={`mx-auto w-6 h-6 flex items-center justify-center rounded-md ${
      active
        ? 'text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-500/10'
        : 'text-gray-300 dark:text-slate-800'
    }`}>
      {active ? <Check className="w-4 h-4" /> : <X className="w-3.5 h-3.5" />}
    </div>
  );
}

function PermissionGroup({ title, icon: Icon, permissions, values, onChange }: any) {
  const [isOpen, setIsOpen] = useState(true);

  return (
    <div className="border border-gray-100 dark:border-slate-800 rounded-xl overflow-hidden bg-white dark:bg-slate-950">
       <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          className="w-full flex items-center justify-between p-4 bg-gray-50/50 dark:bg-slate-900/50 border-b border-gray-100 dark:border-slate-800 hover:bg-indigo-50/10 transition-colors"
       >
          <div className="flex items-center gap-3">
             <Icon className="w-4 h-4 text-gray-500" />
             <span className="text-xs font-semibold text-gray-700 dark:text-slate-200 uppercase tracking-wider">{title}</span>
          </div>
          <ChevronDown className={cn("w-4 h-4 text-gray-400 transition-transform duration-300", isOpen ? "rotate-180" : "")} />
       </button>

       <AnimatePresence>
          {isOpen && (
            <motion.div
               initial={{ height: 0, opacity: 0 }}
               animate={{ height: "auto", opacity: 1 }}
               exit={{ height: 0, opacity: 0 }}
               className="overflow-hidden"
            >
               <div className="divide-y divide-gray-100 dark:divide-slate-800">
                  {permissions.map((p: any) => (
                     <div key={p.id} className="flex items-center justify-between p-4 hover:bg-gray-50/30 dark:hover:bg-slate-900/5 transition-colors group">
                        <div className="flex flex-col">
                           <span className="text-sm font-semibold text-gray-900 dark:text-white group-hover:text-indigo-600 transition-colors">{p.label}</span>
                           <span className="text-xs text-gray-500 font-medium leading-relaxed">{p.description}</span>
                        </div>
                        <select
                          value={values[p.id] || 'deny'}
                          onChange={(e) => onChange(p.id, e.target.value)}
                          className="bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-2 py-1 text-xs font-medium text-gray-700 dark:text-gray-300 outline-none focus:ring-2 focus:ring-indigo-500"
                        >
                           <option value="allow">Allow</option>
                           <option value="partial">Partial</option>
                           <option value="deny">Deny</option>
                        </select>
                     </div>
                  ))}
               </div>
            </motion.div>
          )}
       </AnimatePresence>
    </div>
  );
}

function ModalContainer({ title, sub, icon: Icon, onClose, children }: any) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        className="absolute inset-0 bg-slate-950/80 backdrop-blur-md"
      />
      <motion.div
        initial={{ scale: 0.95, opacity: 0, y: 20 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: 0.95, opacity: 0, y: 20 }}
        className="w-full max-w-2xl bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-xl shadow-2xl relative overflow-hidden flex flex-col max-h-[90vh]"
      >
        <div className="p-6 pb-0 flex items-center justify-between">
           <div className="flex items-center gap-3">
              <div className="p-2.5 bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 rounded-xl">
                 <Icon className="w-5 h-5" />
              </div>
              <div>
                 <h2 className="text-xl font-bold text-gray-900 dark:text-white">{title}</h2>
                 <p className="text-sm text-gray-500">{sub}</p>
              </div>
           </div>
           <button onClick={onClose} className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-slate-900 transition-colors">
              <X className="w-5 h-5 text-gray-400" />
           </button>
        </div>
        {children}
      </motion.div>
    </div>
  );
}

function UserFormModal({ teams, onClose, onSuccess }: any) {
  const { t } = useLanguage();
  const [loading, setLoading] = useState(false);
  const [models, setModels] = useState<ModelRate[]>([]);
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    role: 'developer' as PlatformRole,
    teamId: teams[0]?.id || '',
    allowedModels: [] as string[]
  });

  useEffect(() => {
    getModelRates().then(setModels);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    // Simulate API call
    await new Promise(r => setTimeout(r, 1000));
    onSuccess();
  };

  const toggleModel = (name: string) => {
    setFormData(prev => ({
      ...prev,
      allowedModels: prev.allowedModels.includes(name)
        ? prev.allowedModels.filter(m => m !== name)
        : [...prev.allowedModels, name]
    }));
  };

  return (
    <ModalContainer title={t('addUser')} sub="Identity Access Manager" icon={UserIcon} onClose={onClose}>
      <form onSubmit={handleSubmit} className="p-6 space-y-5 overflow-y-auto">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
           <div className="space-y-1.5">
              <label className="text-sm font-medium text-gray-700 dark:text-slate-300">{t('name')}</label>
              <input required value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})} className="w-full rounded-lg border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white" />
           </div>
           <div className="space-y-1.5">
              <label className="text-sm font-medium text-gray-700 dark:text-slate-300">{t('Email')}</label>
              <input required type="email" value={formData.email} onChange={e => setFormData({...formData, email: e.target.value})} className="w-full rounded-lg border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white" />
           </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
           <div className="space-y-1.5">
              <label className="text-sm font-medium text-gray-700 dark:text-slate-300">{t('platformRole')}</label>
              <select value={formData.role} onChange={e => setFormData({...formData, role: e.target.value as any})} className="w-full rounded-lg border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white">
                 <option value="admin">Admin</option>
                 <option value="developer">Developer</option>
                 <option value="manager">Manager</option>
                 <option value="viewer">Viewer</option>
              </select>
           </div>
           <div className="space-y-1.5">
              <label className="text-sm font-medium text-gray-700 dark:text-slate-300">{t('team')}</label>
              <select value={formData.teamId} onChange={e => setFormData({...formData, teamId: e.target.value})} className="w-full rounded-lg border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white">
                 {teams.map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
           </div>
        </div>

        <div className="space-y-3">
           <label className="text-sm font-medium text-gray-700 dark:text-slate-300">{t('allowedModels')}</label>
           <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {models.map(m => (
                 <button
                  key={m.modelName}
                  type="button"
                  onClick={() => toggleModel(m.modelName)}
                  className={cn(
                    "flex items-center gap-3 p-3 rounded-lg border transition-all text-left",
                    formData.allowedModels.includes(m.modelName)
                      ? "border-indigo-500 bg-indigo-500/5 text-indigo-600 shadow-sm"
                      : "border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-gray-500"
                  )}
                 >
                    <Box className="w-4 h-4 shrink-0" />
                    <span className="text-xs font-medium">{m.modelName}</span>
                    {formData.allowedModels.includes(m.modelName) && <Check className="w-3 h-3 ml-auto" />}
                 </button>
              ))}
           </div>
        </div>

        <div className="flex gap-3 pt-4">
           <button type="button" onClick={onClose} className="flex-1 py-2.5 border border-gray-300 dark:border-slate-700 rounded-lg text-sm font-medium transition-colors hover:bg-gray-50 dark:text-white">Cancel</button>
           <button type="submit" disabled={loading} className="flex-[1.5] py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium shadow-sm transition-all">
              {loading ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : t('addUser')}
           </button>
        </div>
      </form>
    </ModalContainer>
  );
}

function TeamModal({ users, onClose, onSuccess }: any) {
  const { t } = useLanguage();
  const { clusters } = useCluster();
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({
    name: '',
    members: [] as string[],
    role: 'member' as TeamRole,
    allowedClusters: [] as string[]
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    await new Promise(r => setTimeout(r, 1000));
    onSuccess();
  };

  const toggleMember = (id: string) => {
    setFormData(prev => ({
      ...prev,
      members: prev.members.includes(id)
        ? prev.members.filter(m => m !== id)
        : [...prev.members, id]
    }));
  };

  const toggleCluster = (id: string) => {
    setFormData(prev => ({
      ...prev,
      allowedClusters: prev.allowedClusters.includes(id)
        ? prev.allowedClusters.filter(c => c !== id)
        : [...prev.allowedClusters, id]
    }));
  };

  return (
    <ModalContainer title={t('newTeam')} sub="Organization Structurer" icon={LayoutGrid} onClose={onClose}>
      <form onSubmit={handleSubmit} className="p-6 space-y-6 overflow-y-auto">
        <div className="space-y-1.5">
           <label className="text-sm font-medium text-gray-700 dark:text-slate-300">{t('teamName')}</label>
           <input required value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})} className="w-full rounded-lg border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white font-medium" />
        </div>

        <div className="space-y-3">
           <label className="text-sm font-medium text-gray-700 dark:text-slate-300">{t('members')}</label>
           <div className="grid grid-cols-1 gap-2 max-h-48 overflow-y-auto p-1 scrollbar-thin scrollbar-thumb-gray-200 dark:scrollbar-thumb-slate-800">
              {users.map((u: any) => (
                 <button
                  key={u.id}
                  type="button"
                  onClick={() => toggleMember(u.id)}
                  className={cn(
                    "flex items-center gap-3 p-2.5 rounded-lg border transition-all text-left",
                    formData.members.includes(u.id)
                      ? "border-indigo-500 bg-indigo-500/5 text-indigo-600 shadow-sm"
                      : "border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-gray-500"
                  )}
                 >
                    <div className="w-7 h-7 rounded-md bg-indigo-100 dark:bg-indigo-500/20 text-indigo-600 flex items-center justify-center font-bold text-xs">{u.name[0]}</div>
                    <div className="flex flex-col">
                      <span className="text-xs font-semibold">{u.name}</span>
                      <span className="text-[10px] opacity-70">{u.email}</span>
                    </div>
                    {formData.members.includes(u.id) && <Check className="w-4 h-4 ml-auto" />}
                 </button>
              ))}
           </div>
        </div>

        <div className="space-y-3">
           <label className="text-sm font-medium text-gray-700 dark:text-slate-300">{t('teamRole')}</label>
           <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {(['member', 'manager', 'owner', 'viewer'] as TeamRole[]).map(r => (
                 <button
                  key={r}
                  type="button"
                  onClick={() => setFormData({...formData, role: r})}
                  className={cn(
                    "py-2 rounded-lg border transition-all text-center text-xs font-medium uppercase tracking-wider",
                    formData.role === r
                      ? "border-indigo-500 bg-indigo-600 text-white shadow-md shadow-indigo-500/20"
                      : "border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-gray-500 hover:bg-gray-50"
                  )}
                 >
                    {r}
                  </button>
              ))}
           </div>
           <p className="text-[11px] text-gray-500">This role will be automatically assigned to all selected members within this team.</p>
        </div>

        <div className="space-y-3 pt-4 border-t border-gray-100 dark:border-slate-800">
           <div className="flex items-center gap-2">
              <Hexagon className="w-4 h-4 text-indigo-500 animate-pulse" />
              <label className="text-sm font-semibold text-gray-700 dark:text-slate-300">Allowed Clusters</label>
           </div>
           <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {clusters.filter((c: any) => c.id !== 'all').map((c: any) => (
                 <button
                  key={c.id}
                  type="button"
                  onClick={() => toggleCluster(c.id)}
                  className={cn(
                    "flex items-center gap-3 p-3 rounded-xl border transition-all text-left",
                    formData.allowedClusters.includes(c.id)
                      ? "border-indigo-500 bg-indigo-500/5 text-indigo-600 shadow-sm"
                      : "border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-gray-500 hover:bg-gray-50 dark:hover:bg-slate-800/50"
                  )}
                 >
                    <Hexagon className="w-4 h-4 shrink-0 text-indigo-400" />
                    <div className="flex flex-col">
                      <span className="text-xs font-semibold">{c.name}</span>
                      <span className="text-[10px] opacity-75">{c.region}</span>
                    </div>
                    {formData.allowedClusters.includes(c.id) && <Check className="w-3.5 h-3.5 ml-auto text-indigo-600" />}
                 </button>
              ))}
           </div>
        </div>

        <div className="flex gap-3 pt-4">
           <button type="button" onClick={onClose} className="flex-1 py-2.5 border border-gray-300 dark:border-slate-700 rounded-lg text-sm font-medium transition-colors hover:bg-gray-50 dark:text-white">Cancel</button>
           <button type="submit" disabled={loading} className="flex-[1.5] py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium shadow-sm transition-all focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2">
              {loading ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : t('newTeam')}
           </button>
        </div>
      </form>
    </ModalContainer>
  );
}

function RoleModal({ permissions, onClose, onSuccess }: any) {
  const { t } = useLanguage();
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    permissions: {} as Record<string, string>
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    await new Promise(r => setTimeout(r, 1000));
    onSuccess();
  };

  const handlePermChange = (id: string, val: string) => {
    setFormData(prev => ({
      ...prev,
      permissions: { ...prev.permissions, [id]: val }
    }));
  };

  const activePermsCount = Object.values(formData.permissions).filter(v => v !== 'deny').length;
  const groups = Array.from(new Set(permissions.map((p: any) => p.category)));

  return (
    <ModalContainer title={t('createRole')} sub="Policy Governance Architect" icon={Shield} onClose={onClose}>
      <form onSubmit={handleSubmit} className="p-6 space-y-6 overflow-y-auto">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
           <div className="space-y-1.5">
              <label className="text-sm font-medium text-gray-700 dark:text-slate-300">
                {t('roleName')}
                <FieldTooltip content="A unique name for the new role." />
              </label>
              <input required value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})} className="w-full rounded-lg border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white" />
           </div>
           <div className="space-y-1.5">
              <label className="text-sm font-medium text-gray-700 dark:text-slate-300">
                {t('roleDescription')}
                <FieldTooltip content="Brief description of the role's purpose." />
              </label>
              <input value={formData.description} onChange={e => setFormData({...formData, description: e.target.value})} className="w-full rounded-lg border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:text-white" />
           </div>
        </div>

        <div className="space-y-4">
           <div className="flex items-center justify-between">
              <label className="text-sm font-medium text-gray-700 dark:text-slate-300">
                {t('permissionsMatrix')}
                <FieldTooltip content="Set allow, deny, or inherit (neutral) for each permission category." />
              </label>
              <div className="px-2 py-0.5 bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 rounded text-[10px] font-semibold uppercase tracking-wider">
                 {activePermsCount} Active Enforcements
              </div>
           </div>

           <div className="space-y-3">
              {groups.map((category: any) => (
                 <PermissionGroup
                    key={category}
                    title={category}
                    icon={Shield}
                    permissions={permissions.filter((p: any) => p.category === category)}
                    values={formData.permissions}
                    onChange={handlePermChange}
                 />
              ))}
           </div>
        </div>

        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-3">
           <div className="flex items-center gap-2 text-white text-[10px] font-semibold uppercase tracking-wider border-b border-slate-800 pb-2">
              <Zap className="w-3 h-3 text-amber-500" />
              {t('currentActivePermissions')}
           </div>
           <p className="text-[11px] text-slate-400 font-medium">
              {Object.entries(formData.permissions)
                .filter(([_, v]) => v !== 'deny')
                .map(([id, v]) => `${permissions.find((p: any) => p.id === id)?.label} (${v})`)
                .join(', ') || 'No permissions defined yet.'}
           </p>
        </div>

        <div className="flex gap-3 pt-4">
           <button type="button" onClick={onClose} className="flex-1 py-2.5 border border-gray-300 dark:border-slate-700 rounded-lg text-sm font-medium transition-colors hover:bg-gray-50 dark:text-white">Cancel</button>
           <button type="submit" disabled={loading} className="flex-[1.5] py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium shadow-sm transition-all">
              {loading ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : t('createRole')}
           </button>
        </div>
      </form>
    </ModalContainer>
  );
}

export function TokensList() {
  const { t } = useLanguage();
  const [tokens, setTokens] = useState([{ name: 'CI/CD Pipeline', token: 'ctx_abc123...', ttl: '30 days', cluster: 'msk-gpu-01' }]);
  const [showCreate, setShowCreate] = useState(false);
  const [newToken, setNewToken] = useState<any>(null);

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    setNewToken({ name: 'New Token', token: 'ctx_' + Math.random().toString(36).substr(2, 9), cluster: 'msk-gpu-01' });
    setTokens([...tokens, { name: 'New Token', token: 'ctx_...', ttl: '30 days', cluster: 'msk-gpu-01' }]);
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center bg-white dark:bg-slate-950 p-6 rounded-xl border border-gray-200 dark:border-slate-800">
         <div>
            <h2 className="text-xl font-bold text-gray-900 dark:text-white">API Tokens</h2>
            <p className="text-sm text-gray-500 mt-1">Generate programmatic access tokens for proxy and platform APIs.</p>
         </div>
         <button onClick={() => setShowCreate(true)} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium flex items-center gap-2 shadow-sm">
            <Plus className="w-4 h-4" /> Create Token
         </button>
      </div>

      <div className="bg-white dark:bg-slate-950 border border-gray-200 dark:border-slate-800 rounded-2xl overflow-hidden shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-gray-50 dark:bg-slate-900/50 text-xs font-semibold text-gray-500 uppercase tracking-wider border-b border-gray-200 dark:border-slate-800">
            <tr>
              <th className="px-6 py-4">Name</th>
              <th className="px-6 py-4">Token Preview</th>
              <th className="px-6 py-4">Cluster Scope</th>
              <th className="px-6 py-4">TTL</th>
              <th className="px-6 py-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-slate-800">
            {tokens.map((tk, i) => (
              <tr key={i} className="hover:bg-gray-50/50 dark:hover:bg-slate-900/30">
                <td className="px-6 py-4 font-medium text-gray-900 dark:text-white">{tk.name}</td>
                <td className="px-6 py-4 text-gray-500 font-mono text-xs">{tk.token}</td>
                <td className="px-6 py-4">
                  <span className="px-2 py-1 bg-gray-100 dark:bg-slate-800 rounded text-xs font-medium text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-slate-700">{tk.cluster}</span>
                </td>
                <td className="px-6 py-4 text-gray-500">{tk.ttl}</td>
                <td className="px-6 py-4 text-right">
                  <button className="text-gray-400 hover:text-red-500 transition-colors p-2"><Trash2 className="w-4 h-4" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showCreate && !newToken && (
        <ModalContainer title="Create API Token" sub="Authentication Configuration" icon={Key} onClose={() => setShowCreate(false)}>
           <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="text-sm font-medium text-gray-700 dark:text-slate-300 block mb-1">
                  Token Name
                  <FieldTooltip content="A descriptive identifier for this API token." />
                </label>
                <input type="text" className="w-full bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-500" required placeholder="e.g. CI/CD automation" />
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700 dark:text-slate-300 block mb-1">
                  Permission Scope
                  <FieldTooltip content="Defines the level of access. Inference Proxy allows invoking models, Platform Admin grants full control." />
                </label>
                <select className="w-full bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-500">
                   <option>Inference Proxy Only (LLM calls)</option>
                   <option>Platform Admin API</option>
                </select>
              </div>
              <div className="grid grid-cols-2 gap-4">
                 <div>
                   <label className="text-sm font-medium text-gray-700 dark:text-slate-300 block mb-1">
                     Cluster binding
                     <FieldTooltip content="Restrict this token to only interact with a specific cluster." />
                   </label>
                   <select className="w-full bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-500">
                      <option>All Clusters</option>
                      <option>msk-gpu-01</option>
                      <option>eu-central-02</option>
                   </select>
                 </div>
                 <div>
                   <label className="text-sm font-medium text-gray-700 dark:text-slate-300 block mb-1">
                     TTL (Expiration)
                     <FieldTooltip content="How long this token remains valid." />
                   </label>
                   <select className="w-full bg-gray-50 dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-500">
                      <option>30 Days</option>
                      <option>90 Days</option>
                      <option>Never Expires</option>
                   </select>
                 </div>
              </div>
              <div className="pt-4 flex gap-3">
                 <button type="button" onClick={() => setShowCreate(false)} className="flex-1 py-2 bg-gray-100 hover:bg-gray-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-gray-700 dark:text-white rounded-lg text-sm font-medium transition-colors">Cancel</button>
                 <button type="submit" className="flex-[1.5] py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium shadow-sm transition-colors">Generate Token</button>
              </div>
           </form>
        </ModalContainer>
      )}

      {newToken && (
        <ModalContainer title="Token Generated" sub="Save it securely" icon={Key} onClose={() => { setShowCreate(false); setNewToken(null); }}>
           <div className="space-y-4">
             <div className="p-4 bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/20 rounded-xl flex items-start gap-3">
               <AlertCircle className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
               <p className="text-sm text-emerald-800 dark:text-emerald-400 font-medium">Please copy your token now. You will not be able to see it again after closing this window.</p>
             </div>

             <div>
                <label className="text-sm font-medium text-gray-700 dark:text-slate-300 block mb-1 mt-4">API Token</label>
                <div className="relative">
                   <input type="text" readOnly value={newToken.token} className="w-full bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-lg px-4 py-3 font-mono text-sm text-gray-900 dark:text-white outline-none" />
                   <button className="absolute right-2 top-1/2 -translate-y-1/2 p-2 text-gray-400 hover:text-indigo-500 bg-white dark:bg-slate-900"><Copy className="w-4 h-4" /></button>
                </div>
             </div>

             <div className="space-y-2 mt-6">
               <h4 className="text-sm font-semibold text-gray-900 dark:text-white">Example usage (Inference API):</h4>
               <pre className="p-4 bg-slate-950 text-slate-300 font-mono text-xs rounded-xl overflow-x-auto border border-slate-800">
                 {`curl http://${newToken.cluster}:11434/v1/chat/completions \\
  -H "Authorization: Bearer ${newToken.token}" \\
  -d '{"model":"llama3:8b", "messages":[{"role":"user","content":"Hi"}]}'`}
               </pre>
             </div>

             <button onClick={() => { setShowCreate(false); setNewToken(null); }} className="w-full py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium mt-4 transition-colors">Done</button>
           </div>
        </ModalContainer>
      )}
    </div>
  );
}
