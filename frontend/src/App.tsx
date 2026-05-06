import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom';
import { LayoutDashboard, GitBranch, Puzzle, Download, Shield, RefreshCw, FolderOpen } from 'lucide-react';
import Assessments from './pages/Assessments';
import Dashboard from './pages/Dashboard';
import Hierarchy from './pages/Hierarchy';
import Patterns from './pages/Patterns';
import Export from './pages/Export';
import Sync from './pages/Sync';

const navItems = [
  { to: '/assessments', label: 'Assessments', icon: FolderOpen },
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/hierarchy', label: 'Hierarchy', icon: GitBranch },
  { to: '/patterns', label: 'Patterns', icon: Puzzle },
  { to: '/export', label: 'Export', icon: Download },
  { to: '/sync', label: 'Sync', icon: RefreshCw },
];

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen bg-gray-50">
        {/* Sidebar */}
        <aside className="w-64 bg-slate-800 text-white flex flex-col shrink-0">
          {/* Brand */}
          <div className="flex items-center gap-3 px-5 py-5 border-b border-slate-700">
            <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-blue-500">
              <Shield size={20} className="text-white" />
            </div>
            <div>
              <h1 className="text-base font-bold leading-tight">ExcellenceAgent</h1>
              <p className="text-[11px] text-slate-400 leading-tight">Azure Assessment</p>
            </div>
          </div>

          {/* Navigation */}
          <nav className="flex-1 px-3 py-4 space-y-1">
            {navItems.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-blue-600 text-white'
                      : 'text-slate-300 hover:bg-slate-700 hover:text-white'
                  }`
                }
              >
                <Icon size={18} />
                {label}
              </NavLink>
            ))}
          </nav>

          {/* Footer */}
          <div className="px-5 py-4 border-t border-slate-700">
            <p className="text-[11px] text-slate-500">v3.0 · APRL Powered</p>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-y-auto">
          <div className="max-w-7xl mx-auto px-6 py-6">
            <Routes>
              <Route path="/" element={<Navigate to="/assessments" replace />} />
              <Route path="/assessments" element={<Assessments />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/hierarchy" element={<Hierarchy />} />
              <Route path="/patterns" element={<Patterns />} />
              <Route path="/export" element={<Export />} />
              <Route path="/sync" element={<Sync />} />
            </Routes>
          </div>
        </main>
      </div>
    </BrowserRouter>
  );
}
