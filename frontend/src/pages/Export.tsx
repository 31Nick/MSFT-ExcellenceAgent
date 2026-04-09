import { useEffect, useState, useCallback } from 'react';
import { Download, CheckCircle, AlertTriangle, FileDown } from 'lucide-react';
import { getStats, exportCsv, exportGitHub } from '../lib/api';
import type { Stats } from '../lib/types';
import Spinner from '../components/Spinner';

type Platform = 'ado' | 'github';

export default function Export() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [platform, setPlatform] = useState<Platform>('ado');

  // ADO fields
  const [areaPath, setAreaPath] = useState('');
  const [iterationPath, setIterationPath] = useState('');

  // GitHub fields
  const [repo, setRepo] = useState('');
  const [milestone, setMilestone] = useState('');
  const [assignee, setAssignee] = useState('');
  const [extraLabels, setExtraLabels] = useState('');

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
      if (platform === 'github') {
        await exportGitHub({
          repo,
          milestone: milestone || undefined,
          assignee: assignee || undefined,
          extra_labels: extraLabels || undefined,
        });
      } else {
        await exportCsv({ area_path: areaPath, iteration_path: iterationPath });
      }
      setSuccess(true);
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message);
      else setError('Export failed');
    } finally {
      setExporting(false);
    }
  }, [platform, areaPath, iterationPath, repo, milestone, assignee, extraLabels]);

  if (loading)
    return (
      <div className="flex items-center justify-center h-96">
        <Spinner className="w-10 h-10" />
      </div>
    );

  const exportDisabled =
    exporting ||
    !stats?.has_data ||
    (platform === 'github' && !repo.trim());

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Export Work Items</h1>
        <p className="text-gray-500 mt-1">
          Export your work items to Azure DevOps or GitHub
        </p>
      </div>

      {/* Platform Toggle */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
        <label className="block text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">
          Target Platform
        </label>
        <div className="flex gap-3">
          <button
            onClick={() => { setPlatform('ado'); setSuccess(false); setError(''); }}
            className={`flex-1 py-3 px-4 rounded-lg border-2 font-medium transition-colors text-sm ${
              platform === 'ado'
                ? 'border-blue-500 bg-blue-50 text-blue-700'
                : 'border-gray-200 bg-white text-gray-500 hover:border-gray-300'
            }`}
          >
            <div className="flex flex-col items-center gap-1">
              <svg className="w-6 h-6" viewBox="0 0 24 24" fill="currentColor">
                <path d="M22 4.5v15l-5.5 2.5V2L22 4.5zM2 7.5l4-2V20l5.5 2.5v-19L2 7.5z" />
              </svg>
              <span>Azure DevOps</span>
            </div>
          </button>
          <button
            onClick={() => { setPlatform('github'); setSuccess(false); setError(''); }}
            className={`flex-1 py-3 px-4 rounded-lg border-2 font-medium transition-colors text-sm ${
              platform === 'github'
                ? 'border-blue-500 bg-blue-50 text-blue-700'
                : 'border-gray-200 bg-white text-gray-500 hover:border-gray-300'
            }`}
          >
            <div className="flex flex-col items-center gap-1">
              <svg className="w-6 h-6" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
              </svg>
              <span>GitHub</span>
            </div>
          </button>
        </div>
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
        {platform === 'ado' ? (
          <>
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
          </>
        ) : (
          <>
            <div>
              <label htmlFor="repo" className="block text-sm font-medium text-gray-700 mb-1">
                Repository <span className="text-red-400">*</span>
              </label>
              <input
                id="repo"
                type="text"
                value={repo}
                onChange={(e) => setRepo(e.target.value)}
                placeholder="e.g. myorg/myrepo"
                className="w-full px-3 py-2 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
              />
            </div>
            <div>
              <label htmlFor="milestone" className="block text-sm font-medium text-gray-700 mb-1">
                Milestone <span className="text-gray-400 font-normal">(optional)</span>
              </label>
              <input
                id="milestone"
                type="text"
                value={milestone}
                onChange={(e) => setMilestone(e.target.value)}
                placeholder="e.g. Sprint 1"
                className="w-full px-3 py-2 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
              />
            </div>
            <div>
              <label htmlFor="assignee" className="block text-sm font-medium text-gray-700 mb-1">
                Assignee <span className="text-gray-400 font-normal">(optional)</span>
              </label>
              <input
                id="assignee"
                type="text"
                value={assignee}
                onChange={(e) => setAssignee(e.target.value)}
                placeholder="e.g. octocat"
                className="w-full px-3 py-2 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
              />
            </div>
            <div>
              <label htmlFor="extra-labels" className="block text-sm font-medium text-gray-700 mb-1">
                Extra Labels <span className="text-gray-400 font-normal">(optional, comma-separated)</span>
              </label>
              <input
                id="extra-labels"
                type="text"
                value={extraLabels}
                onChange={(e) => setExtraLabels(e.target.value)}
                placeholder="e.g. azure, remediation, aprl"
                className="w-full px-3 py-2 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
              />
            </div>
          </>
        )}

        <button
          onClick={handleExport}
          disabled={exportDisabled}
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
              {platform === 'ado' ? 'Export CSV' : 'Export GitHub Issues'}
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
              <FileDown size={14} />{' '}
              {platform === 'ado'
                ? 'ado_export.csv has been downloaded'
                : 'github_export.zip has been downloaded'}
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
