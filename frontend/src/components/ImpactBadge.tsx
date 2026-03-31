interface Props {
  impact: 'High' | 'Medium' | 'Low';
  size?: 'sm' | 'md';
}

const colors: Record<string, string> = {
  High: 'bg-red-100 text-red-700 border-red-200',
  Medium: 'bg-amber-100 text-amber-700 border-amber-200',
  Low: 'bg-green-100 text-green-700 border-green-200',
};

export default function ImpactBadge({ impact, size = 'sm' }: Props) {
  const cls = size === 'sm' ? 'text-xs px-2 py-0.5' : 'text-sm px-2.5 py-1';
  return (
    <span className={`inline-flex items-center rounded-full border font-medium ${cls} ${colors[impact] ?? 'bg-gray-100 text-gray-600'}`}>
      {impact}
    </span>
  );
}
