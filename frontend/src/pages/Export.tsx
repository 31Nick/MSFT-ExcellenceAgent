import { useEffect, useState, useCallback } from 'react';
import { Download, CheckCircle, AlertTriangle, FileDown, RefreshCw } from 'lucide-react';
import { Link } from 'react-router-dom';
import { getStats, exportCsv } from '../lib/api';
import type { Stats } from '../lib/types';
import Spinner from '../components/Spinner';

export default function Export() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [areaPath, setAreaPath] = useState('');
  const [iterationPath, setIterationPath] = useState('');
  const [exporting, setExporting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    getStats()
      .then(setStats)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const handleExport = useCallback(async () => {
    setExporting(true);
    setError('');
    setSuccess(false);
    try {
      await exportCsv({ area_path: areaPath, iteration_path: iterationPath });
      setSuccess(true);
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message);
      else setError('Export failed');
    } finally {
      setExporting(false);
    }
  }, [areaPath, iterationPath]);

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

      {/* Preview */}
      {stats?.has_data && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">Export Preview</h2>
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
              <p className="text-xl font-bold text-orange-700">{stats.tasks}</p>
              <p className="text-xs text-orange-500">Tasks</p>
            </div>
          </div>
        </div>
      )}

      {/* Form */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 space-y-5">
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
            </>
          )}
        </button>

        {!stats?.has_data && (
          <p className="text-sm text-gray-400 text-center">
            Upload an APRL file on the Dashboard before exporting
          </p>
        )}
      </div>

      {/* Messages */}
      {success && (
        <div className="flex items-center gap-2 bg-green-50 border border-green-200 rounded-lg p-4 text-green-700">
          <CheckCircle size={18} />
          <div>
            <p className="font-medium">Export successful!</p>
            <p className="text-sm text-green-600 flex items-center gap-1 mt-0.5">
              <FileDown size={14} /> ado_export.csv has been downloaded
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
