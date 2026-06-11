import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Clock, Trash2, FileText, X, Database, ArrowRight, FolderOpen, AlertTriangle } from 'lucide-react';
import { listAssessments, loadAssessment, deleteAssessment, uploadFile } from '../lib/api';
import type { AssessmentSummary } from '../lib/api';
import FileDropZone from '../components/FileDropZone';
import Spinner from '../components/Spinner';

export default function Assessments() {
  const navigate = useNavigate();
  const [assessments, setAssessments] = useState<AssessmentSummary[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState('');

  // New assessment form state
  const [showNewForm, setShowNewForm] = useState(false);
  const [stagedAprlFile, setStagedAprlFile] = useState<File | null>(null);
  const [advisorFile, setAdvisorFile] = useState<File | null>(null);
  const [appName, setAppName] = useState('ChangeMe-AppName');
  const [reviewedOnly, setReviewedOnly] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await listAssessments();
      setAssessments(resp.assessments);
      setActiveId(resp.active_id);
    } catch {
      setError('Failed to load assessments');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleLoad = async (id: number) => {
    setSwitching(true);
    setError('');
    try {
      await loadAssessment(id);
      setActiveId(id);
      navigate('/dashboard');
    } catch {
      setError('Failed to load assessment');
    } finally {
      setSwitching(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    if (!confirm('Delete this assessment? This cannot be undone.')) return;
    try {
      await deleteAssessment(id);
      await refresh();
    } catch {
      setError('Failed to delete assessment');
    }
  };

  const handleContinue = async () => {
    if (!stagedAprlFile) return;
    setUploading(true);
    setUploadProgress(0);
    setError('');
    try {
      await uploadFile(stagedAprlFile, setUploadProgress, advisorFile, appName, reviewedOnly);
      setStagedAprlFile(null);
      setAdvisorFile(null);
      setShowNewForm(false);
      navigate('/dashboard');
    } catch (err: unknown) {
      if (err instanceof Error) setError(err.message);
      else setError('Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const formatDate = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  };

  // Group assessments by app name
  const grouped: Record<string, AssessmentSummary[]> = {};
  for (const a of assessments) {
    if (!grouped[a.app_name]) grouped[a.app_name] = [];
    grouped[a.app_name].push(a);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Spinner className="w-10 h-10" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Assessments</h1>
          <p className="text-gray-500 mt-1">Start a new assessment or continue a previous one</p>
        </div>
        {!showNewForm && (
          <button
            onClick={() => setShowNewForm(true)}
            className="flex items-center gap-2 px-4 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-semibold hover:bg-blue-700 transition-colors shadow-sm"
          >
            <Plus size={18} />
            New Assessment
          </button>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      )}

      {/* New Assessment Form */}
      {showNewForm && (
        <div className="bg-white rounded-xl shadow-sm border border-blue-100 p-6 space-y-5">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900">New Assessment</h2>
            <button
              onClick={() => { setShowNewForm(false); setStagedAprlFile(null); setAdvisorFile(null); }}
              className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
            >
              <X size={20} />
            </button>
          </div>

          {uploading ? (
            <div className="flex flex-col items-center gap-3 py-6">
              <Spinner className="w-10 h-10" />
              <p className="text-gray-600 font-medium">Processing files… {uploadProgress}%</p>
              <div className="w-64 h-2 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 rounded-full transition-all duration-300"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
            </div>
          ) : (
            <>
              {/* Step 1: APRL Report */}
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <div className="flex items-center justify-center w-5 h-5 rounded-full bg-blue-600 text-white text-[10px] font-bold">1</div>
                  <h3 className="text-sm font-semibold text-gray-700">APRL Assessment Report <span className="text-red-500">*</span></h3>
                </div>
                {stagedAprlFile ? (
                  <div className="flex items-center gap-3 bg-blue-50 border border-blue-200 rounded-lg px-4 py-3">
                    <FileText size={18} className="text-blue-600" />
                    <span className="text-sm font-medium text-blue-700 flex-1">{stagedAprlFile.name}</span>
                    <button onClick={() => setStagedAprlFile(null)} className="p-1 rounded hover:bg-blue-100 text-blue-400 hover:text-blue-600">
                      <X size={16} />
                    </button>
                  </div>
                ) : (
                  <FileDropZone onFile={(f) => setStagedAprlFile(f)} uploading={false} progress={0} />
                )}
              </div>

              {/* Step 2: Advisor CSV */}
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <div className="flex items-center justify-center w-5 h-5 rounded-full bg-indigo-500 text-white text-[10px] font-bold">2</div>
                  <h3 className="text-sm font-semibold text-gray-700">Azure Advisor Export</h3>
                  <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">Optional</span>
                </div>
                {advisorFile ? (
                  <div className="flex items-center gap-3 bg-indigo-50 border border-indigo-200 rounded-lg px-4 py-3">
                    <Database size={18} className="text-indigo-600" />
                    <span className="text-sm font-medium text-indigo-700 flex-1">{advisorFile.name}</span>
                    <button onClick={() => setAdvisorFile(null)} className="p-1 rounded hover:bg-indigo-100 text-indigo-400 hover:text-indigo-600">
                      <X size={16} />
                    </button>
                  </div>
                ) : (
                  <label className="flex items-center gap-3 border border-dashed border-indigo-300 rounded-lg px-4 py-3 cursor-pointer hover:bg-indigo-50 transition-colors">
                    <Database size={16} className="text-indigo-400" />
                    <span className="text-sm text-indigo-600 font-medium">Click to select Advisor CSV</span>
                    <input type="file" accept=".csv" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) setAdvisorFile(f); }} />
                  </label>
                )}
              </div>

              {/* Step 3: Settings */}
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <div className="flex items-center justify-center w-5 h-5 rounded-full bg-green-600 text-white text-[10px] font-bold">3</div>
                  <h3 className="text-sm font-semibold text-gray-700">Settings</h3>
                </div>
                <div className="space-y-3 pl-7">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Application Name <span className="text-red-500">*</span></label>
                    <input
                      type="text"
                      value={appName}
                      onChange={(e) => setAppName(e.target.value)}
                      placeholder="ChangeMe-AppName"
                      className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                    />
                    <p className="text-xs text-gray-400 mt-1">The application name becomes the Epic in the ADO hierarchy.</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input type="checkbox" checked={reviewedOnly} onChange={(e) => setReviewedOnly(e.target.checked)} className="sr-only peer" />
                      <div className="w-9 h-5 bg-gray-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-600"></div>
                    </label>
                    <span className="text-sm text-gray-700">Reviewed items only</span>
                  </div>
                </div>
              </div>

              {/* Submit */}
              <div className="flex justify-end pt-2">
                <button
                  onClick={handleContinue}
                  disabled={!stagedAprlFile}
                  className={`flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-semibold transition-all
                    ${stagedAprlFile ? 'bg-blue-600 text-white hover:bg-blue-700 shadow-sm' : 'bg-gray-200 text-gray-400 cursor-not-allowed'}`}
                >
                  Run Assessment
                  <ArrowRight size={18} />
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Assessment History */}
      {assessments.length === 0 && !showNewForm ? (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-12 text-center">
          <FolderOpen size={48} className="mx-auto text-gray-300 mb-4" />
          <h3 className="text-lg font-semibold text-gray-700 mb-1">No assessments yet</h3>
          <p className="text-gray-500 text-sm mb-6">Upload an APRL report to create your first assessment.</p>
          <button
            onClick={() => setShowNewForm(true)}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-semibold hover:bg-blue-700 transition-colors"
          >
            <Plus size={18} />
            New Assessment
          </button>
        </div>
      ) : assessments.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-gray-800">History</h2>
          {Object.entries(grouped).map(([appName, items]) => (
            <div key={appName} className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
              <div className="px-5 py-3 bg-gray-50 border-b border-gray-100 flex items-center gap-2">
                <FolderOpen size={16} className="text-blue-600" />
                <h3 className="text-sm font-bold text-gray-700">{appName}</h3>
                <span className="text-xs text-gray-400 bg-gray-200 px-2 py-0.5 rounded-full">{items.length} run{items.length > 1 ? 's' : ''}</span>
              </div>
              <div className="divide-y divide-gray-50">
                {items.map(a => (
                  <div
                    key={a.id}
                    onClick={() => handleLoad(a.id)}
                    className={`flex items-center gap-4 px-5 py-3 cursor-pointer hover:bg-blue-50 transition-colors
                      ${a.id === activeId ? 'bg-blue-50 border-l-4 border-l-blue-500' : 'border-l-4 border-l-transparent'}`}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-gray-800">{a.source_filename || `Assessment #${a.id}`}</span>
                        {a.id === activeId && (
                          <span className="text-[10px] uppercase font-bold text-blue-600 bg-blue-100 px-1.5 py-0.5 rounded">Active</span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 mt-0.5 text-xs text-gray-500">
                        <span className="flex items-center gap-1"><Clock size={11} />{formatDate(a.created_at)}</span>
                        <span>{a.stats?.user_stories ?? 0} stories</span>
                        <span>{a.stats?.recommendations ?? 0} recommendations</span>
                        <span>{a.items_processed} new / {a.items_skipped} skipped</span>
                        {a.reviewed_only && <span className="text-green-600">Reviewed only</span>}
                      </div>
                    </div>
                    <button
                      onClick={(e) => handleDelete(e, a.id)}
                      className="p-2 rounded-lg hover:bg-red-100 text-gray-400 hover:text-red-500 transition-colors"
                      title="Delete assessment"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {switching && (
        <div className="fixed inset-0 bg-black/20 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 flex items-center gap-3 shadow-xl">
            <Spinner className="w-6 h-6" />
            <span className="text-gray-700 font-medium">Loading assessment…</span>
          </div>
        </div>
      )}
    </div>
  );
}
