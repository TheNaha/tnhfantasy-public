import { useState } from 'react';
import { ChevronDown, Network } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const STRATEGIES = [
    { id: 'round-robin', label: 'Round Robin' },
    { id: 'random', label: 'Random' },
    { id: 'priority', label: 'Priority' },
    { id: 'least-connections', label: 'Least Conn.' },
    { id: 'priority-round-robin', label: 'Priority + RR' },
    { id: 'priority-least-connections', label: 'Priority + LC' },
];

function humanizeStrategy(id) {
    const found = STRATEGIES.find((s) => s.id === id);
    return found ? found.label : id;
}

export default function LoadBalancerBar({ config, stats, onUpdateStrategy }) {
    const [expanded, setExpanded] = useState(false);

    if (!config) return null;

    const activeCount = stats?.total_providers || 0;
    const strategy = config.strategy || 'round-robin';
    const fallback = config.fallback_enabled;

    return (
        <div className="mb-6 overflow-hidden rounded-xl border border-gray-800 bg-gray-950/60">
            {/* Collapsed bar */}
            <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                className="flex w-full items-center justify-between px-5 py-3.5 text-left transition-colors hover:bg-gray-900/60"
            >
                <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500/10 border border-indigo-500/20">
                        <Network className="text-indigo-400" size={16} />
                    </div>
                    <div className="flex items-center gap-2 text-sm">
                        <span className="font-medium text-gray-200">Load Balancer</span>
                        <span className="text-gray-600">·</span>
                        <span className="rounded-md bg-indigo-500/15 px-2 py-0.5 text-xs font-medium text-indigo-300 border border-indigo-500/20">
                            {humanizeStrategy(strategy)}
                        </span>
                        <span className="text-gray-600">·</span>
                        <span className="text-gray-400">
                            {activeCount} active
                        </span>
                        {fallback && (
                            <>
                                <span className="text-gray-600">·</span>
                                <span className="text-gray-500 text-xs">Fallback on</span>
                            </>
                        )}
                    </div>
                </div>
                <ChevronDown
                    size={16}
                    className={`text-gray-500 transition-transform duration-200 ${
                        expanded ? 'rotate-180' : ''
                    }`}
                />
            </button>

            {/* Expanded strategy picker */}
            <AnimatePresence>
                {expanded && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2, ease: [0.4, 0, 0.2, 1] }}
                        className="overflow-hidden"
                    >
                        <div className="border-t border-gray-800/60 px-5 py-4">
                            <div className="mb-3 text-xs font-medium uppercase tracking-wider text-gray-500">
                                Routing Strategy
                            </div>
                            <div className="segmented-control">
                                {STRATEGIES.map((s) => (
                                    <button
                                        key={s.id}
                                        type="button"
                                        className={strategy === s.id ? 'active' : ''}
                                        onClick={() => onUpdateStrategy(s.id)}
                                    >
                                        {s.label}
                                    </button>
                                ))}
                            </div>
                            <div className="mt-3 flex items-center gap-4 text-xs text-gray-500">
                                <span className="flex items-center gap-1.5">
                                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-green-500" />
                                    {activeCount} provider{activeCount !== 1 ? 's' : ''} active
                                </span>
                                <span className="flex items-center gap-1.5">
                                    <span className={`inline-block h-1.5 w-1.5 rounded-full ${fallback ? 'bg-blue-500' : 'bg-gray-600'}`} />
                                    Fallback {fallback ? 'enabled' : 'disabled'}
                                </span>
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}
