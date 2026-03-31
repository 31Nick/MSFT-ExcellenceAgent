import { useEffect, useState } from 'react';
import { Puzzle, AlertTriangle } from 'lucide-react';
import { getPatterns } from '../lib/api';
import type { Pattern } from '../lib/types';
import Spinner from '../components/Spinner';

export default function Patterns() {
  const [patterns, setPatterns] = useState<Pattern[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    getPatterns()
      .then(setPatterns)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading)
    return (
      <div className="flex items-center justify-center h-96">
        <Spinner className="w-10 h-10" />
      </div>
    );

  if (error)
    return (
      <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
        <AlertTriangle size={18} />
        <span>{error}</span>
      </div>
    );

  if (patterns.length === 0)
    return (
      <div className="text-center py-20">
        <Puzzle className="mx-auto text-gray-300" size={48} />
        <p className="text-gray-500 mt-4 text-lg">No patterns detected</p>
        <p className="text-gray-400 text-sm mt-1">Upload an APRL file on the Dashboard first</p>
      </div>
    );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Cross-Cutting Patterns</h1>
        <p className="text-gray-500 mt-1">{patterns.length} patterns detected across your assessment</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {patterns.map((p) => (
          <PatternCard key={p.name} pattern={p} />
        ))}
      </div>
    </div>
  );
}

function PatternCard({ pattern }: { pattern: Pattern }) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 hover:shadow-md transition-shadow flex flex-col">
      <div className="flex items-start gap-3">
        <div
          className={`flex items-center justify-center w-10 h-10 rounded-lg shrink-0 ${
            pattern.is_cross_epic ? 'bg-amber-100' : 'bg-blue-100'
          }`}
        >
          <Puzzle
            size={20}
            className={pattern.is_cross_epic ? 'text-amber-600' : 'text-blue-600'}
          />
        </div>
        <div className="min-w-0">
          <h3 className="font-semibold text-gray-900 text-sm leading-tight">{pattern.name}</h3>
          {pattern.is_cross_epic && (
            <span className="inline-block mt-1 text-[10px] font-medium px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200">
              Cross-Epic
            </span>
          )}
        </div>
      </div>

      <p className="text-sm text-gray-500 mt-3 leading-relaxed flex-1">
        {pattern.description || 'No description available'}
      </p>

      <div className="mt-4 space-y-3">
        {/* Affected Epics */}
        <div className="flex flex-wrap gap-1.5">
          {(pattern.affected_epics ?? []).map((e) => (
            <span
              key={e}
              className="text-[11px] px-2 py-0.5 rounded-full bg-purple-50 text-purple-700 border border-purple-200 font-medium"
            >
              {e}
            </span>
          ))}
        </div>

        {/* Counts */}
        <div className="flex gap-4 text-xs text-gray-400 pt-2 border-t border-gray-50">
          <span>{pattern.story_count} stories</span>
          <span>{pattern.task_count} tasks</span>
        </div>
      </div>
    </div>
  );
}
