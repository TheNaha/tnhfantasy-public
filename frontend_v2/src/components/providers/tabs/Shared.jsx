import { Circle } from 'lucide-react';

export const STATUS_TONE = {
    running: 'green', active: 'green', connected: 'green',
    stopped: 'gray', idle: 'gray',
    queued: 'blue', reconciling: 'blue', completed: 'green',
    deploying: 'purple', failed: 'red',
};

export function statusDotClass(status) {
    const map = {
        green: 'text-green-400', running: 'text-green-400', active: 'text-green-400',
        blue: 'text-blue-400', queued: 'text-blue-400', reconciling: 'text-blue-400',
        purple: 'text-purple-400', deploying: 'text-purple-400',
        red: 'text-red-400', failed: 'text-red-400',
        yellow: 'text-yellow-400', orange: 'text-orange-400',
        gray: 'text-gray-500', stopped: 'text-gray-500', idle: 'text-gray-500',
    };
    return map[status] || map.gray;
}

export function humanize(status) {
    if (!status) return 'Unknown';
    return status.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function capitalize(v) {
    return v ? v.charAt(0).toUpperCase() + v.slice(1) : v;
}

export function DataRow({ label, value, mono = false }) {
    return (
        <div className="flex items-start justify-between gap-4 py-2.5 border-b border-white/[0.03] last:border-0">
            <span className="text-xs uppercase tracking-wide text-gray-500 flex-shrink-0">{label}</span>
            <span className={`text-sm text-right text-gray-200 break-all ${mono ? 'font-mono text-xs' : ''}`}>
                {value || 'n/a'}
            </span>
        </div>
    );
}

export function StatusRow({ label, value, tone = 'gray' }) {
    return (
        <div className="flex items-center justify-between gap-4 py-2.5 border-b border-white/[0.03] last:border-0">
            <span className="text-xs uppercase tracking-wide text-gray-500">{label}</span>
            <span className="flex items-center gap-2">
                <Circle className={`fill-current ${statusDotClass(tone)}`} size={7} />
                <span className="text-sm text-gray-200">{value}</span>
            </span>
        </div>
    );
}

export function ActionBtn({ onClick, disabled = false, tone = 'gray', icon: Icon, label }) {
    const tones = {
        gray: 'border-gray-700 bg-gray-800/70 text-gray-200 hover:bg-gray-700',
        blue: 'border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/15',
        green: 'border-green-500/30 bg-green-500/10 text-green-300 hover:bg-green-500/15',
        purple: 'border-purple-500/30 bg-purple-500/10 text-purple-300 hover:bg-purple-500/15',
        orange: 'border-orange-500/30 bg-orange-500/10 text-orange-300 hover:bg-orange-500/15',
        red: 'border-red-500/30 bg-red-500/10 text-red-300 hover:bg-red-500/15',
    };
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${tones[tone] || tones.gray}`}
        >
            <Icon size={14} />
            {label}
        </button>
    );
}

export function Notice({ tone, message }) {
    const tones = {
        red: 'border-red-500/20 bg-red-500/8 text-red-200',
        yellow: 'border-yellow-500/20 bg-yellow-500/8 text-yellow-200',
        green: 'border-green-500/20 bg-green-500/8 text-green-200',
    };
    return (
        <div className={`rounded-lg border px-4 py-2.5 text-sm ${tones[tone] || tones.yellow}`}>
            {message}
        </div>
    );
}
