import { useEffect, useState, useCallback } from 'react';
import { Layers, GitBranch, BookOpen, CheckSquare, Copy, AlertTriangle, Database, ArrowRightLeft, ArrowRight, FileText, X } from 'lucide-react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { getStats, getDedup, getHierarchy, uploadFile, getCrossReference } from '../lib/api';
import type { Stats, DedupReport, CrossReferenceReport } from '../lib/types';
import StatCard from '../components/StatCard';
import ImpactBadge from '../components/ImpactBadge';
import FileDropZone from '../components/FileDropZone';
import Spinner from '../components/Spinner';

const IMPACT_COLORS: Record<string, string> = { High: '#ef4444', Medium: '#f59e0b', Low: '#22c55e' };

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [dedup, setDedup] = useState<DedupReport | null>(null);
  const [xref, setXref] = useState<CrossReferenceReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  // Staging state: files selected but not yet processed
  const [stagedAprlFile, setStagedAprlFile] = useState<File | null>(null);
  const [advisorFile, setAdvisorFile] = useState<File | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [s, d, x] = await Promise.all([getStats(), getDedup(), getCrossReference()]);
      setStats(s);
      setDedup(d);
      setXref(x);
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

  // Stage the APRL file (don't process yet)
  const handleAprlSelected = useCallback((file: File) => {
    setStagedAprlFile(file);
    setError('');
  }, []);

  // User clicks "Continue" — now process both files
  const handleContinue = useCallback(async () => {
    if (!stagedAprlFile) return;
    setUploading(true);
    setUploadProgress(0);
    setError('');
    try {
      await uploadFile(stagedAprlFile, setUploadProgress, advisorFile);
      setStagedAprlFile(null);
      setAdvisorFile(null);
      await fetchData();
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message);
      else setError('Upload failed');
    } finally {
      setUploading(false);
    }
  }, [stagedAprlFile, advisorFile, fetchData]);

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
          <p className="text-gray-500 mt-1">Upload your assessment files to get started</p>
        </div>

        {/* Processing overlay */}
        {uploading && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-8">
            <div className="flex flex-col items-center gap-3">
              <Spinner className="w-10 h-10" />
              <p className="text-gray-600 font-medium">Processing files… {uploadProgress}%</p>
              <div className="w-64 h-2 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 rounded-full transition-all duration-300"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
            </div>
          </div>
        )}

        {!uploading && (
          <>
            {/* Step 1: APRL Report (Required) */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
              <div className="flex items-center gap-2 mb-3">
                <div className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-600 text-white text-xs font-bold">1</div>
                <h3 className="text-sm font-semibold text-gray-700">APRL Assessment Report <span className="text-red-500">*</span></h3>
              </div>
              {stagedAprlFile ? (
                <div className="flex items-center gap-3 bg-blue-50 border border-blue-200 rounded-lg px-4 py-3">
                  <FileText size={18} className="text-blue-600" />
                  <span className="text-sm font-medium text-blue-700 flex-1">{stagedAprlFile.name}</span>
                  <button
                    onClick={() => setStagedAprlFile(null)}
                    className="p-1 rounded hover:bg-blue-100 text-blue-400 hover:text-blue-600 transition-colors"
                  >
                    <X size={16} />
                  </button>
                </div>
              ) : (
                <FileDropZone onFile={handleAprlSelected} uploading={false} progress={0} />
              )}
            </div>

            {/* Step 2: Advisor Export (Optional) */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
              <div className="flex items-center gap-2 mb-3">
                <div className="flex items-center justify-center w-6 h-6 rounded-full bg-indigo-500 text-white text-xs font-bold">2</div>
                <h3 className="text-sm font-semibold text-gray-700">Azure Advisor Export</h3>
                <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">Optional</span>
              </div>
              <p className="text-xs text-gray-500 mb-3">
                Include an Azure Advisor CSV export to cross-reference recommendations and identify overlapping insights.
              </p>
              {advisorFile ? (
                <div className="flex items-center gap-3 bg-indigo-50 border border-indigo-200 rounded-lg px-4 py-3">
                  <Database size={18} className="text-indigo-600" />
                  <span className="text-sm font-medium text-indigo-700 flex-1">{advisorFile.name}</span>
                  <button
                    onClick={() => setAdvisorFile(null)}
                    className="p-1 rounded hover:bg-indigo-100 text-indigo-400 hover:text-indigo-600 transition-colors"
                  >
                    <X size={16} />
                  </button>
                </div>
              ) : (
                <label className="flex items-center gap-3 border border-dashed border-indigo-300 rounded-lg px-4 py-3 cursor-pointer hover:bg-indigo-50 transition-colors">
                  <Database size={16} className="text-indigo-400" />
                  <span className="text-sm text-indigo-600 font-medium">Click to select Advisor CSV</span>
                  <input
                    type="file"
                    accept=".csv"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) setAdvisorFile(f);
                    }}
                  />
                </label>
              )}
            </div>

            {/* Continue Button */}
            <div className="flex justify-end">
              <button
                onClick={handleContinue}
                disabled={!stagedAprlFile}
                className={`flex items-center gap-2 px-6 py-3 rounded-lg text-sm font-semibold transition-all
                  ${stagedAprlFile
                    ? 'bg-blue-600 text-white hover:bg-blue-700 shadow-sm hover:shadow-md'
                    : 'bg-gray-200 text-gray-400 cursor-not-allowed'
                  }`}
              >
                Continue to Analyse
                <ArrowRight size={18} />
              </button>
            </div>
          </>
        )}

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
          onClick={() => {
            setStats(null);
            setDedup(null);
            setXref(null);
            setStagedAprlFile(null);
            setAdvisorFile(null);
          }}
          className="text-sm px-4 py-2 rounded-lg bg-blue-50 text-blue-600 hover:bg-blue-100 font-medium transition-colors"
        >
          Upload new files
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

      {/* Cross-Reference Summary (only shown when Advisor data was provided) */}
      {xref?.has_data && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <div className="flex items-center gap-2 mb-4">
            <ArrowRightLeft size={20} className="text-indigo-500" />
            <h2 className="text-lg font-semibold text-gray-900">APRL × Advisor Cross-Reference</h2>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
            <div className="bg-blue-50 rounded-lg p-4 text-center">
              <p className="text-2xl font-bold text-blue-700">{xref.total_aprl_rows}</p>
              <p className="text-xs text-blue-500 uppercase tracking-wide">APRL Rows</p>
            </div>
            <div className="bg-indigo-50 rounded-lg p-4 text-center">
              <p className="text-2xl font-bold text-indigo-700">{xref.total_advisor_rows}</p>
              <p className="text-xs text-indigo-500 uppercase tracking-wide">Advisor Rows</p>
            </div>
            <div className="bg-green-50 rounded-lg p-4 text-center">
              <p className="text-2xl font-bold text-green-700">{xref.matched_resources_count}</p>
              <p className="text-xs text-green-500 uppercase tracking-wide">Matched</p>
            </div>
            <div className="bg-purple-50 rounded-lg p-4 text-center">
              <p className="text-2xl font-bold text-purple-700">{xref.total_merged_rows}</p>
              <p className="text-xs text-purple-500 uppercase tracking-wide">Merged Total</p>
            </div>
          </div>
          {xref.duplicate_recommendations && xref.duplicate_recommendations.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-700 mb-2">Overlapping Recommendations</h3>
              <div className="space-y-2">
                {xref.duplicate_recommendations.map((dup, i) => (
                  <div key={i} className="bg-gray-50 rounded-lg p-3 text-sm">
                    <p className="font-medium text-gray-800">{dup.resource}</p>
                    <div className="flex gap-4 mt-1 text-xs text-gray-500">
                      <span>APRL: {dup.aprl_title}</span>
                      <span>Advisor: {dup.advisor_title}</span>
                      <span className="text-indigo-600 font-medium">
                        {(dup.similarity * 100).toFixed(0)}% match
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {xref.advisor_only_resources && xref.advisor_only_resources.length > 0 && (
            <div className="mt-4">
              <h3 className="text-sm font-semibold text-gray-700 mb-2">
                Advisor-Only Resources ({xref.advisor_only_resources.length})
              </h3>
              <div className="flex flex-wrap gap-2">
                {xref.advisor_only_resources.map((r) => (
                  <span key={r} className="text-xs bg-indigo-100 text-indigo-700 px-2 py-1 rounded-full">
                    {r}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

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
