import { useEffect, useState, useMemo } from 'react';
import {
  FolderOpen, Box, FileText, Server,
  ChevronRight, ChevronDown, Search, ExternalLink, AlertTriangle,
} from 'lucide-react';
import { getHierarchy } from '../lib/api';
import type { WorkItemHierarchy, Epic, Feature, UserStory, Task } from '../lib/types';
import ImpactBadge from '../components/ImpactBadge';
import Spinner from '../components/Spinner';

export default function Hierarchy() {
  const [hierarchy, setHierarchy] = useState<WorkItemHierarchy | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');

  useEffect(() => {
    getHierarchy()
      .then(setHierarchy)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    if (!hierarchy || !query.trim()) return hierarchy?.epics ?? [];
    const q = query.toLowerCase();
    return (hierarchy.epics ?? [])
      .map((epic) => {
        const features = epic.features
          .map((f) => {
            const stories = f.user_stories.filter(
              (s) =>
                s.title.toLowerCase().includes(q) ||
                s.long_description?.toLowerCase().includes(q) ||
                s.tasks.some((t) => t.resource_name.toLowerCase().includes(q))
            );
            if (
              f.name.toLowerCase().includes(q) ||
              f.resource_type.toLowerCase().includes(q) ||
              stories.length > 0
            )
              return { ...f, user_stories: stories.length > 0 ? stories : f.user_stories };
            return null;
          })
          .filter(Boolean) as Feature[];
        if (epic.name.toLowerCase().includes(q) || features.length > 0)
          return { ...epic, features: features.length > 0 ? features : epic.features };
        return null;
      })
      .filter(Boolean) as Epic[];
  }, [hierarchy, query]);

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

  if (!hierarchy || (hierarchy.epics ?? []).length === 0)
    return (
      <div className="text-center py-20">
        <FolderOpen className="mx-auto text-gray-300" size={48} />
        <p className="text-gray-500 mt-4 text-lg">No hierarchy data available</p>
        <p className="text-gray-400 text-sm mt-1">Upload an APRL file on the Dashboard first</p>
      </div>
    );

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Work Item Hierarchy</h1>
        <p className="text-gray-500 mt-1">
          {hierarchy.summary.epics} Epics · {hierarchy.summary.features} Features · {hierarchy.summary.user_stories} Stories · {hierarchy.summary.tasks} Tasks
        </p>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
        <input
          type="text"
          placeholder="Search epics, features, stories, tasks…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full pl-10 pr-4 py-2.5 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
        />
      </div>

      {/* Tree */}
      <div className="space-y-2">
        {filtered.map((epic) => (
          <EpicNode key={epic.name} epic={epic} defaultOpen={!!query} />
        ))}
        {filtered.length === 0 && (
          <p className="text-gray-400 text-center py-8">No results matching "{query}"</p>
        )}
      </div>
    </div>
  );
}

function EpicNode({ epic, defaultOpen }: { epic: Epic; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-gray-100 bg-white shadow-sm overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors text-left"
      >
        {open ? <ChevronDown size={18} className="text-gray-400" /> : <ChevronRight size={18} className="text-gray-400" />}
        <FolderOpen size={18} className="text-purple-500" />
        <span className="font-semibold text-gray-900 flex-1">{epic.name}</span>
        <span className="text-xs text-gray-400">{epic.features.length} features · {epic.total_stories} stories</span>
      </button>
      <div
        className={`transition-all duration-300 ease-in-out overflow-hidden ${open ? 'max-h-[10000px] opacity-100' : 'max-h-0 opacity-0'}`}
      >
        <div className="pl-8 pr-4 pb-3 space-y-1">
          {epic.features.map((f) => (
            <FeatureNode key={f.resource_type} feature={f} defaultOpen={defaultOpen} />
          ))}
        </div>
      </div>
    </div>
  );
}

function FeatureNode({ feature, defaultOpen }: { feature: Feature; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border border-gray-50">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-3 py-2 hover:bg-blue-50/50 transition-colors text-left rounded-lg"
      >
        {open ? <ChevronDown size={16} className="text-gray-400" /> : <ChevronRight size={16} className="text-gray-400" />}
        <Box size={16} className="text-blue-500" />
        <span className="font-medium text-gray-800 flex-1 text-sm">{feature.name}</span>
        <span className="text-xs text-gray-400">{feature.user_stories.length} stories · {feature.total_tasks} tasks</span>
      </button>
      <div
        className={`transition-all duration-300 ease-in-out overflow-hidden ${open ? 'max-h-[10000px] opacity-100' : 'max-h-0 opacity-0'}`}
      >
        <div className="pl-8 pr-2 pb-2 space-y-1">
          {feature.user_stories.map((s) => (
            <StoryNode key={s.recommendation_guid || s.title} story={s} defaultOpen={defaultOpen} />
          ))}
        </div>
      </div>
    </div>
  );
}

function StoryNode({ story, defaultOpen }: { story: UserStory; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-3 py-2 hover:bg-green-50/50 transition-colors text-left rounded-lg"
      >
        {open ? <ChevronDown size={14} className="text-gray-400" /> : <ChevronRight size={14} className="text-gray-400" />}
        <FileText size={14} className="text-green-500" />
        <span className="text-sm text-gray-700 flex-1 line-clamp-1">{story.title}</span>
        <ImpactBadge impact={story.impact} />
        <span className="text-xs text-gray-400 ml-1">{story.tasks.length} tasks</span>
      </button>
      <div
        className={`transition-all duration-300 ease-in-out overflow-hidden ${open ? 'max-h-[10000px] opacity-100' : 'max-h-0 opacity-0'}`}
      >
        <div className="pl-10 pr-2 pb-2 space-y-2">
          {story.long_description && (
            <p className="text-xs text-gray-500 leading-relaxed">{story.long_description}</p>
          )}
          {story.learn_more_link && (
            <a
              href={story.learn_more_link}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-blue-500 hover:underline"
            >
              Learn more <ExternalLink size={12} />
            </a>
          )}
          <p className="text-xs text-gray-400">
            {story.tasks.length} affected resource{story.tasks.length !== 1 ? 's' : ''}
          </p>
          <div className="space-y-1">
            {story.tasks.map((t, i) => (
              <TaskNode key={`${t.resource_id}-${i}`} task={t} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function TaskNode({ task }: { task: Task }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-gray-50 transition-colors text-left rounded-md"
      >
        <Server size={12} className="text-gray-400" />
        <span className="text-xs text-gray-600 flex-1 truncate">{task.resource_name}</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{task.location}</span>
      </button>
      <div
        className={`transition-all duration-200 ease-in-out overflow-hidden ${open ? 'max-h-96 opacity-100' : 'max-h-0 opacity-0'}`}
      >
        <div className="pl-6 pr-2 pb-2 text-xs text-gray-500 space-y-1">
          <p><span className="font-medium text-gray-600">Resource ID:</span> {task.resource_id}</p>
          <p><span className="font-medium text-gray-600">Resource Group:</span> {task.resource_group}</p>
          <p><span className="font-medium text-gray-600">Subscription:</span> {task.subscription_id}</p>
          <p><span className="font-medium text-gray-600">Location:</span> {task.location}</p>
        </div>
      </div>
    </div>
  );
}
