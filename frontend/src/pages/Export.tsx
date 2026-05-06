import { useEffect, useState, useCallback } from 'react';
import { Download, CheckCircle, AlertTriangle, FileDown, RefreshCw, Clock, Layers } from 'lucide-react';
import { Link } from 'react-router-dom';
import { getStats, exportCsv, listAssessments, getActiveAssessment } from '../lib/api';
import type { Stats } from '../lib/types';
import type { AssessmentSummary } from '../lib/api';
import Spinner from '../components/Spinner';

type ExportScope = 'active' | 'all' | number;

export default function Export() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [areaPath, setAreaPath] = useState('');
  const [iterationPath, setIterationPath] = useState('');
  const [exporting, setExporting] = useState(false);
  const [success, setSuccess] = useState('');
  const [error, setError] = useState('');
  const [scope, setScope] = useState<ExportScope>('active');
  const [assessments, setAssessments] = useState<AssessmentSummary[]>([]);
  const [activeAppName, setActiveAppName] = useState('');

  useEffect(() => {
    Promise.all([getStats(), listAssessments(), getActiveAssessment()])
      .then(([s, a, active]) => {
        setStats(s);
        setAssessments(a.assessments);
        if (active.active) setActiveAppName(active.active.app_name);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const handleExport = useCallback(async () => {
    setExporting(true);
    setError('');
    setSuccess('');
    try {
      const scopeValue = typeof scope === 'number' ? scope.toString() : scope;
      await exportCsv({ area_path: areaPath, iteration_path: iterationPath, scope: scopeValue });
      const label = scope === 'active' ? 'latest run' : scope === 'all' ? 'all runs (merged)' : `run #${scope}`;
      setSuccess(`Exported ${label} successfully!`);
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message);
      else setError('Export failed');
    } finally {
      setExporting(false);
    }
  }, [areaPath, iterationPath, scope]);

  const formatDate = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  // Filter assessments to active app
  const appAssessments = assessments.filter(a => a.app_name === activeAppName);

  if (loading)
    return (
      <div className="flex items-center justify-center h-96">
        <Spinner className="w-10 h-10" />
      </div>
    );

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Export to Azure DevOps</h1>
        <p className="text-gray-500 mt-1">
          Generate a CSV file for importing work items into ADO, or{' '}
          <Link to="/sync" className="text-blue-600 hover:underline inline-flex items-center gap-1">
            <RefreshCw size={14} />
            sync directly via MCP
          </Link>
        </p>
      </div>

      {/* Export Scope Selector */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 space-y-4">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Export Scope</h2>
        <p className="text-xs text-gray-500">Choose what to include in the export for <span className="font-semibold text-gray-700">{activeAppName || 'this app'}</span></p>

        <div className="space-y-2">
          {/* Active (latest) */}
          <label
            className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
              scope === 'active' ? 'border-blue-300 bg-blue-50' : 'border-gray-200 hover:bg-gray-50'
            }`}
          >
            <input
              type="radio"
              name="scope"
              checked={scope === 'active'}
              onChange={() => setScope('active')}
              className="text-blue-600 focus:ring-blue-500"
            />
            <div className="flex-1">
              <span className="text-sm font-medium text-gray-800">Latest run only</span>
              <span className="ml-2 text-xs text-blue-600 bg-blue-100 px-1.5 py-0.5 rounded">Default</span>
              <p className="text-xs text-gray-500 mt-0.5">Export items from the most recent pipeline run</p>
            </div>
          </label>

          {/* All runs merged */}
          <label
            className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
              scope === 'all' ? 'border-green-300 bg-green-50' : 'border-gray-200 hover:bg-gray-50'
            }`}
          >
            <input
              type="radio"
              name="scope"
              checked={scope === 'all'}
              onChange={() => setScope('all')}
              className="text-green-600 focus:ring-green-500"
            />
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-800">All runs (merged)</span>
                <Layers size={14} className="text-green-600" />
              </div>
              <p className="text-xs text-gray-500 mt-0.5">
                Combine all {appAssessments.length} run{appAssessments.length !== 1 ? 's' : ''} into a single export — includes every story ever created for this app
              </p>
            </div>
          </label>

          {/* Individual runs */}
          {appAssessments.length > 0 && (
            <div className="border border-gray-200 rounded-lg overflow-hidden">
              <div className="px-3 py-2 bg-gray-50 border-b border-gray-100">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Or export a specific run</span>
              </div>
              <div className="max-h-48 overflow-y-auto divide-y divide-gray-50">
                {appAssessments.map(a => (
                  <label
                    key={a.id}
                    className={`flex items-center gap-3 px-3 py-2.5 cursor-pointer transition-colors ${
                      scope === a.id ? 'bg-purple-50' : 'hover:bg-gray-50'
                    }`}
                  >
                    <input
                      type="radio"
                      name="scope"
                      checked={scope === a.id}
                      onChange={() => setScope(a.id)}
                      className="text-purple-600 focus:ring-purple-500"
                    />
                    <div className="flex-1 min-w-0">
                      <span className="text-sm text-gray-800">{a.source_filename || `Run #${a.id}`}</span>
                      <div className="flex items-center gap-2 text-xs text-gray-500">
                        <Clock size={10} />
                        {formatDate(a.created_at)}
                        <span>•</span>
                        <span>{a.stats?.user_stories ?? 0} stories</span>
                        <span>•</span>
                        <span>{a.items_processed} items</span>
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Preview */}
      {stats?.has_data && scope === 'active' && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">Active Run Preview</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-center">
            <div className="bg-purple-50 rounded-lg p-3">
              <p className="text-xl font-bold text-purple-700">{stats.epics}</p>
              <p className="text-xs text-purple-500">Epics</p>
            </div>
            <div className="bg-blue-50 rounded-lg p-3">
              <p className="text-xl font-bold text-blue-700">{stats.features}</p>
              <p className="text-xs text-blue-500">Features</p>
            </div>
            <div className="bg-green-50 rounded-lg p-3">
              <p className="text-xl font-bold text-green-700">{stats.user_stories}</p>
              <p className="text-xs text-green-500">User Stories</p>
            </div>
            <div className="bg-orange-50 rounded-lg p-3">
              <p className="text-xl font-bold text-orange-700">{stats.recommendations}</p>
              <p className="text-xs text-orange-500">Recommendations</p>
            </div>
          </div>
        </div>
      )}

      {/* ADO Paths + Export Button */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 space-y-5">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">ADO Settings</h2>
        <div>
          <label htmlFor="area-path" className="block text-sm font-medium text-gray-700 mb-1">
            Area Path
          </label>
          <input
            id="area-path"
            type="text"
            value={areaPath}
            onChange={(e) => setAreaPath(e.target.value)}
            placeholder="e.g. MyProject\\MyTeam"
            className="w-full px-3 py-2 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
          />
        </div>
        <div>
          <label htmlFor="iteration-path" className="block text-sm font-medium text-gray-700 mb-1">
            Iteration Path
          </label>
          <input
            id="iteration-path"
            type="text"
            value={iterationPath}
            onChange={(e) => setIterationPath(e.target.value)}
            placeholder="e.g. MyProject\\Sprint 1"
            className="w-full px-3 py-2 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
          />
        </div>

        <button
          onClick={handleExport}
          disabled={exporting || !stats?.has_data}
          className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg bg-blue-600 text-white font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {exporting ? (
            <>
              <Spinner className="w-5 h-5 text-white" />
              Exporting…
            </>
          ) : (
            <>
              <Download size={18} />
              Export CSV
              {scope === 'all' && <span className="text-xs opacity-75">(all runs)</span>}
              {typeof scope === 'number' && <span className="text-xs opacity-75">(run #{scope})</span>}
            </>
          )}
        </button>

        {!stats?.has_data && (
          <p className="text-sm text-gray-400 text-center">
            Upload an APRL file on the Assessments page before exporting
          </p>
        )}
      </div>

      {/* Messages */}
      {success && (
        <div className="flex items-center gap-2 bg-green-50 border border-green-200 rounded-lg p-4 text-green-700">
          <CheckCircle size={18} />
          <div>
            <p className="font-medium">{success}</p>
            <p className="text-sm text-green-600 flex items-center gap-1 mt-0.5">
              <FileDown size={14} /> CSV has been downloaded
            </p>
          </div>
        </div>
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
