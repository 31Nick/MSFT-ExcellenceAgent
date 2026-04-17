import { useEffect, useState, useCallback } from 'react';
import {
  RefreshCw,
  CheckCircle,
  AlertTriangle,
  Clock,
  Plus,
  Edit3,
  Trash2,
  Minus,
  ArrowRight,
} from 'lucide-react';
import {
  getCustomers,
  getSyncPlan,
  pushSync,
  getSyncStatus,
  getSyncHistory,
  retrySync,
} from '../lib/api';
import type {
  CustomerInfo,
  SyncPlanResponse,
  SyncPushResponse,
  SyncStatusResponse,
  SyncRunInfo,
  PlannedItemInfo,
} from '../lib/types';
import Spinner from '../components/Spinner';

const ACTION_ICONS: Record<string, typeof Plus> = {
  create: Plus,
  update: Edit3,
  orphaned: Trash2,
  unchanged: Minus,
  relink: ArrowRight,
};

const ACTION_COLORS: Record<string, string> = {
  create: 'text-green-600 bg-green-50',
  update: 'text-blue-600 bg-blue-50',
  orphaned: 'text-red-600 bg-red-50',
  unchanged: 'text-gray-400 bg-gray-50',
  relink: 'text-yellow-600 bg-yellow-50',
};

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    completed: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
    running: 'bg-blue-100 text-blue-700',
  };
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] ?? 'bg-gray-100 text-gray-600'}`}>
      {status}
    </span>
  );
}

function PlanTable({ items, label }: { items: PlannedItemInfo[]; label: string }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-700 mb-2">{label} ({items.length})</h3>
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Type</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Title</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {items.slice(0, 50).map((item) => {
              const Icon = ACTION_ICONS[item.action] ?? Minus;
              const color = ACTION_COLORS[item.action] ?? 'text-gray-400 bg-gray-50';
              return (
                <tr key={item.stable_key} className="hover:bg-gray-50">
                  <td className="px-3 py-2">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${color}`}>
                      <Icon size={12} />
                      {item.work_item_type}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-gray-700">{item.title}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {items.length > 50 && (
          <div className="px-3 py-2 text-xs text-gray-400 bg-gray-50">
            … and {items.length - 50} more
          </div>
        )}
      </div>
    </div>
  );
}

export default function Sync() {
  const [customers, setCustomers] = useState<CustomerInfo[]>([]);
  const [selected, setSelected] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Plan state
  const [plan, setPlan] = useState<SyncPlanResponse | null>(null);
  const [planning, setPlanning] = useState(false);

  // Push state
  const [pushResult, setPushResult] = useState<SyncPushResponse | null>(null);
  const [pushing, setPushing] = useState(false);

  // Status / history
  const [status, setStatus] = useState<SyncStatusResponse | null>(null);
  const [history, setHistory] = useState<SyncRunInfo[]>([]);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    getCustomers()
      .then((data) => {
        setCustomers(data);
        if (data.length === 1) setSelected(data[0].slug);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const loadStatus = useCallback(async (slug: string) => {
    try {
      const [s, h] = await Promise.all([getSyncStatus(slug), getSyncHistory(slug)]);
      setStatus(s);
      setHistory(h);
    } catch {
      // status might 404 if customer config not available — ignore
    }
  }, []);

  useEffect(() => {
    if (selected) {
      setPlan(null);
      setPushResult(null);
      loadStatus(selected);
    }
  }, [selected, loadStatus]);

  const handlePlan = useCallback(async () => {
    if (!selected) return;
    setPlanning(true);
    setError('');
    setPlan(null);
    setPushResult(null);
    try {
      const p = await getSyncPlan(selected);
      setPlan(p);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Plan failed');
    } finally {
      setPlanning(false);
    }
  }, [selected]);

  const handlePush = useCallback(async () => {
    if (!selected) return;
    setPushing(true);
    setError('');
    setPushResult(null);
    try {
      const result = await pushSync(selected);
      setPushResult(result);
      setPlan(null);
      await loadStatus(selected);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Push failed');
    } finally {
      setPushing(false);
    }
  }, [selected, loadStatus]);

  const handleRetry = useCallback(async () => {
    if (!selected) return;
    setRetrying(true);
    setError('');
    try {
      const result = await retrySync(selected);
      setPushResult(result);
      await loadStatus(selected);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Retry failed');
    } finally {
      setRetrying(false);
    }
  }, [selected, loadStatus]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Spinner className="w-10 h-10" />
      </div>
    );
  }

  const actionable = plan ? plan.summary.create + plan.summary.update + plan.summary.relink : 0;
  const hasFailed = (status?.status_counts?.failed ?? 0) > 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">ADO Sync</h1>
        <p className="text-gray-500 mt-1">Sync work items to Azure DevOps via MCP</p>
      </div>

      {/* Customer selector */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <label htmlFor="customer" className="block text-sm font-medium text-gray-700 mb-2">
          Customer
        </label>
        {customers.length === 0 ? (
          <p className="text-sm text-gray-400">
            No customer configs found. Create one in the <code className="bg-gray-100 px-1 rounded">customers/</code> directory.
          </p>
        ) : (
          <select
            id="customer"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="w-full max-w-sm px-3 py-2 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
          >
            <option value="">Select a customer…</option>
            {customers.map((c) => (
              <option key={c.slug} value={c.slug}>
                {c.customer_name} ({c.slug})
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Current status */}
      {status && status.total_items > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">Current Status</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {Object.entries(status.status_counts).map(([st, count]) => {
              const colors: Record<string, string> = {
                created: 'bg-green-50 text-green-700',
                updated: 'bg-blue-50 text-blue-700',
                failed: 'bg-red-50 text-red-700',
                orphaned: 'bg-yellow-50 text-yellow-700',
              };
              return (
                <div key={st} className={`rounded-lg p-3 text-center ${colors[st] ?? 'bg-gray-50 text-gray-600'}`}>
                  <p className="text-xl font-bold">{count}</p>
                  <p className="text-xs capitalize">{st}</p>
                </div>
              );
            })}
          </div>
          {status.latest_run && (
            <div className="mt-3 text-xs text-gray-500">
              Latest run: #{status.latest_run.id} <StatusBadge status={status.latest_run.status} />{' '}
              {status.latest_run.started_at.slice(0, 19).replace('T', ' ')}
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      {selected && (
        <div className="flex gap-3">
          <button
            onClick={handlePlan}
            disabled={planning || pushing}
            className="flex items-center gap-2 py-2.5 px-5 rounded-lg bg-slate-100 text-slate-700 font-medium hover:bg-slate-200 disabled:opacity-50 transition-colors text-sm"
          >
            {planning ? <Spinner className="w-4 h-4" /> : <Clock size={16} />}
            Preview Plan
          </button>
          <button
            onClick={handlePush}
            disabled={pushing || planning}
            className="flex items-center gap-2 py-2.5 px-5 rounded-lg bg-blue-600 text-white font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors text-sm"
          >
            {pushing ? <Spinner className="w-4 h-4 text-white" /> : <RefreshCw size={16} />}
            Push to ADO
          </button>
          {hasFailed && (
            <button
              onClick={handleRetry}
              disabled={retrying || pushing}
              className="flex items-center gap-2 py-2.5 px-5 rounded-lg bg-orange-500 text-white font-medium hover:bg-orange-600 disabled:opacity-50 transition-colors text-sm"
            >
              {retrying ? <Spinner className="w-4 h-4 text-white" /> : <RefreshCw size={16} />}
              Retry Failed
            </button>
          )}
        </div>
      )}

      {/* Plan preview */}
      {plan && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Sync Plan</h2>
            <span className="text-xs text-gray-400">{plan.summary.total} items total</span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-center">
            {[
              { label: 'Create', count: plan.summary.create, color: 'bg-green-50 text-green-700' },
              { label: 'Update', count: plan.summary.update, color: 'bg-blue-50 text-blue-700' },
              { label: 'Relink', count: plan.summary.relink, color: 'bg-yellow-50 text-yellow-700' },
              { label: 'Unchanged', count: plan.summary.unchanged, color: 'bg-gray-50 text-gray-500' },
              { label: 'Orphaned', count: plan.summary.orphaned, color: 'bg-red-50 text-red-600' },
            ].map(({ label, count, color }) => (
              <div key={label} className={`rounded-lg p-3 ${color}`}>
                <p className="text-xl font-bold">{count}</p>
                <p className="text-xs">{label}</p>
              </div>
            ))}
          </div>

          {actionable === 0 && (
            <p className="text-sm text-gray-500 text-center">All items up to date — nothing to push.</p>
          )}

          <PlanTable items={plan.to_create} label="To Create" />
          <PlanTable items={plan.to_update} label="To Update" />
          <PlanTable items={plan.orphaned} label="Orphaned" />
        </div>
      )}

      {/* Push result */}
      {pushResult && (
        <div className={`rounded-xl border p-6 ${pushResult.success ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'}`}>
          <div className="flex items-center gap-2 mb-3">
            {pushResult.success ? (
              <CheckCircle className="text-green-600" size={20} />
            ) : (
              <AlertTriangle className="text-red-600" size={20} />
            )}
            <h2 className="font-semibold text-gray-900">
              {pushResult.success ? 'Sync Complete' : 'Sync Finished with Errors'}
            </h2>
            <span className="text-xs text-gray-500">Run #{pushResult.run_id}</span>
          </div>
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 text-center text-sm">
            {[
              { label: 'Created', value: pushResult.items_created },
              { label: 'Updated', value: pushResult.items_updated },
              { label: 'Linked', value: pushResult.items_linked },
              { label: 'Unchanged', value: pushResult.items_unchanged },
              { label: 'Failed', value: pushResult.items_failed },
              { label: 'Orphaned', value: pushResult.items_orphaned },
            ].map(({ label, value }) => (
              <div key={label}>
                <p className="font-bold">{value}</p>
                <p className="text-xs text-gray-500">{label}</p>
              </div>
            ))}
          </div>
          {pushResult.errors.length > 0 && (
            <div className="mt-3 space-y-1">
              {pushResult.errors.map((err, i) => (
                <p key={i} className="text-xs text-red-700">✘ {err}</p>
              ))}
            </div>
          )}
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">Run History</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Run</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Status</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Started</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-gray-500">Created</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-gray-500">Updated</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-gray-500">Failed</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {history.map((run) => (
                  <tr key={run.id} className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-medium">#{run.id}</td>
                    <td className="px-3 py-2"><StatusBadge status={run.status} /></td>
                    <td className="px-3 py-2 text-gray-500">{run.started_at.slice(0, 19).replace('T', ' ')}</td>
                    <td className="px-3 py-2 text-right">{run.items_created}</td>
                    <td className="px-3 py-2 text-right">{run.items_updated}</td>
                    <td className="px-3 py-2 text-right">{run.items_failed}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
          <AlertTriangle size={18} />
          <span className="text-sm">{error}</span>
        </div>
      )}
    </div>
  );
}
