import { useEffect, useState, useCallback } from 'react';
import { Layers, GitBranch, BookOpen, CheckSquare, Copy, AlertTriangle } from 'lucide-react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { getStats, getDedup, getHierarchy, uploadFile } from '../lib/api';
import type { Stats, DedupReport } from '../lib/types';
import StatCard from '../components/StatCard';
import ImpactBadge from '../components/ImpactBadge';
import FileDropZone from '../components/FileDropZone';
import Spinner from '../components/Spinner';

const IMPACT_COLORS: Record<string, string> = { High: '#ef4444', Medium: '#f59e0b', Low: '#22c55e' };

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [dedup, setDedup] = useState<DedupReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [s, d] = await Promise.all([getStats(), getDedup()]);
      setStats(s);
      setDedup(d);
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message);
      else setError('Failed to load data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleUpload = useCallback(async (file: File) => {
    setUploading(true);
    setUploadProgress(0);
    setError('');
    try {
      await uploadFile(file, setUploadProgress);
      await fetchData();
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message);
      else setError('Upload failed');
    } finally {
      setUploading(false);
    }
  }, [fetchData]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Spinner className="w-10 h-10" />
      </div>
    );
  }

  if (!stats?.has_data) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-500 mt-1">Upload an APRL assessment file to get started</p>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-8">
          <FileDropZone onFile={handleUpload} uploading={uploading} progress={uploadProgress} />
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
            <AlertTriangle size={18} />
            <span>{error}</span>
          </div>
        )}
      </div>
    );
  }

  const impactData = stats.impact_counts
    ? Object.entries(stats.impact_counts).map(([name, value]) => ({ name, value }))
    : [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-500 mt-1">Assessment overview and key metrics</p>
        </div>
        <button
          onClick={() => document.getElementById('reupload-input')?.click()}
          className="text-sm px-4 py-2 rounded-lg bg-blue-50 text-blue-600 hover:bg-blue-100 font-medium transition-colors"
        >
          Upload new file
          <input
            id="reupload-input"
            type="file"
            accept=".json,.csv,.xlsx"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleUpload(f);
            }}
          />
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      )}

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Epics"
          value={stats.epics}
          icon={<Layers size={22} className="text-purple-600" />}
          accent="bg-purple-100"
        />
        <StatCard
          title="Features"
          value={stats.features}
          icon={<GitBranch size={22} className="text-blue-600" />}
          accent="bg-blue-100"
        />
        <StatCard
          title="User Stories"
          value={stats.user_stories}
          icon={<BookOpen size={22} className="text-green-600" />}
          accent="bg-green-100"
        />
        <StatCard
          title="Tasks"
          value={stats.tasks}
          icon={<CheckSquare size={22} className="text-orange-600" />}
          accent="bg-orange-100"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Impact Donut Chart */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Impact Breakdown</h2>
          {impactData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie
                  data={impactData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  paddingAngle={3}
                  dataKey="value"
                >
                  {impactData.map((entry) => (
                    <Cell key={entry.name} fill={IMPACT_COLORS[entry.name] ?? '#94a3b8'} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-gray-400 text-center py-12">No impact data available</p>
          )}
        </div>

        {/* Dedup Summary */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <div className="flex items-center gap-2 mb-4">
            <Copy size={20} className="text-blue-500" />
            <h2 className="text-lg font-semibold text-gray-900">Deduplication Summary</h2>
          </div>
          {dedup ? (
            <div className="space-y-4">
              <div className="flex items-center justify-center">
                <div className="text-center">
                  <p className="text-4xl font-bold text-blue-600">{dedup.rows_saved}</p>
                  <p className="text-sm text-gray-500 mt-1">duplicate rows removed</p>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4 mt-4">
                <div className="bg-gray-50 rounded-lg p-4 text-center">
                  <p className="text-2xl font-bold text-gray-700">{dedup.original_count}</p>
                  <p className="text-xs text-gray-500 uppercase tracking-wide">Before</p>
                </div>
                <div className="bg-blue-50 rounded-lg p-4 text-center">
                  <p className="text-2xl font-bold text-blue-700">{dedup.deduplicated_count}</p>
                  <p className="text-xs text-blue-500 uppercase tracking-wide">After</p>
                </div>
              </div>
              {dedup.duplicate_groups && dedup.duplicate_groups.length > 0 && (
                <div className="mt-2">
                  <p className="text-sm text-gray-500">
                    {dedup.duplicate_groups.length} duplicate group{dedup.duplicate_groups.length !== 1 ? 's' : ''} detected
                  </p>
                </div>
              )}
            </div>
          ) : (
            <p className="text-gray-400 text-center py-12">No deduplication data</p>
          )}
        </div>
      </div>

      {/* Epic Overview Cards */}
      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Epics Overview</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {/* We need hierarchy for epics; render placeholder if no epic data in stats */}
          <EpicCards />
        </div>
      </div>
    </div>
  );
}

function EpicCards() {
  const [epics, setEpics] = useState<
    {
      name: string;
      features: { name: string; user_stories: { impact: string }[] }[];
      total_stories: number;
      total_tasks: number;
      impact_summary: { High: number; Medium: number; Low: number };
    }[]
  >([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getHierarchy()
      .then((h) => setEpics(h.epics ?? []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner />;
  if (epics.length === 0) return <p className="text-gray-400 col-span-full text-center py-8">No epics loaded</p>;

  return (
    <>
      {epics.map((epic) => (
        <div
          key={epic.name}
          className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 hover:shadow-md transition-shadow"
        >
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-purple-500 inline-block" />
            {epic.name}
          </h3>
          <div className="mt-3 flex gap-4 text-sm text-gray-500">
            <span>{epic.features?.length ?? 0} features</span>
            <span>{epic.total_stories} stories</span>
            <span>{epic.total_tasks} tasks</span>
          </div>
          <div className="mt-3 flex gap-1.5 flex-wrap">
            {epic.impact_summary?.High > 0 && <ImpactBadge impact="High" />}
            {epic.impact_summary?.Medium > 0 && <ImpactBadge impact="Medium" />}
            {epic.impact_summary?.Low > 0 && <ImpactBadge impact="Low" />}
            <span className="text-xs text-gray-400 ml-1 self-center">
              {epic.impact_summary?.High ?? 0}H / {epic.impact_summary?.Medium ?? 0}M / {epic.impact_summary?.Low ?? 0}L
            </span>
          </div>
        </div>
      ))}
    </>
  );
}
