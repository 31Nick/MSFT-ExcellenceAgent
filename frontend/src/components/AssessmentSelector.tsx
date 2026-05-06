import { useEffect, useState, useCallback } from 'react';
import { Clock, Trash2, ChevronDown, FolderOpen } from 'lucide-react';
import { listAssessments, loadAssessment, deleteAssessment } from '../lib/api';
import type { AssessmentSummary } from '../lib/api';

interface Props {
  onSwitch?: () => void;
}

export default function AssessmentSelector({ onSwitch }: Props) {
  const [assessments, setAssessments] = useState<AssessmentSummary[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const resp = await listAssessments();
      setAssessments(resp.assessments);
      setActiveId(resp.active_id);
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleLoad = async (id: number) => {
    setLoading(true);
    try {
      await loadAssessment(id);
      setActiveId(id);
      setOpen(false);
      onSwitch?.();
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    if (!confirm('Delete this assessment? This cannot be undone.')) return;
    try {
      await deleteAssessment(id);
      await refresh();
      if (id === activeId) {
        onSwitch?.();
      }
    } catch {
      // silent
    }
  };

  if (assessments.length === 0) return null;

  const active = assessments.find(a => a.id === activeId);

  const formatDate = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  // Group by app name
  const grouped: Record<string, AssessmentSummary[]> = {};
  for (const a of assessments) {
    if (!grouped[a.app_name]) grouped[a.app_name] = [];
    grouped[a.app_name].push(a);
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm hover:bg-gray-50 transition-colors shadow-sm"
      >
        <FolderOpen size={16} className="text-blue-600" />
        <span className="font-medium text-gray-700 max-w-[200px] truncate">
          {active ? `${active.app_name} (#${active.id})` : 'Select Assessment'}
        </span>
        <ChevronDown size={14} className={`text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 w-80 bg-white border border-gray-200 rounded-lg shadow-lg z-50 max-h-96 overflow-y-auto">
          {loading && (
            <div className="px-4 py-2 text-xs text-gray-500 text-center">Loading…</div>
          )}
          {Object.entries(grouped).map(([appName, items]) => (
            <div key={appName}>
              <div className="px-3 py-1.5 bg-gray-50 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                {appName}
              </div>
              {items.map(a => (
                <button
                  key={a.id}
                  onClick={() => handleLoad(a.id)}
                  className={`w-full text-left px-3 py-2 hover:bg-blue-50 flex items-center gap-2 border-b border-gray-50 transition-colors
                    ${a.id === activeId ? 'bg-blue-50 border-l-2 border-l-blue-500' : ''}`}
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-gray-800 truncate">
                      {a.source_filename || `Run #${a.id}`}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-gray-500">
                      <Clock size={10} />
                      {formatDate(a.created_at)}
                      <span className="text-gray-400">•</span>
                      {a.stats?.user_stories ?? 0} stories
                      <span className="text-gray-400">•</span>
                      {a.items_processed} new
                    </div>
                  </div>
                  <button
                    onClick={(e) => handleDelete(e, a.id)}
                    className="p-1 rounded hover:bg-red-100 text-gray-400 hover:text-red-500 transition-colors"
                    title="Delete assessment"
                  >
                    <Trash2 size={14} />
                  </button>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
