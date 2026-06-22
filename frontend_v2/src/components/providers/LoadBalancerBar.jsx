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
        <div className="mb-6 overflow-hidden rounded-2xl border border-white/5 bg-[#0B0E14]/60 shadow-inner backdrop-blur-sm">
            {/* Collapsed bar */}
            <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                className="flex w-full items-center justify-between px-5 py-4 text-left transition-all duration-300 hover:bg-white/5 group"
            >
                <div className="flex items-center gap-4">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/10 border border-indigo-500/20 shadow-inner group-hover:bg-indigo-500/20 transition-colors">
                        <Network className="text-indigo-400 drop-shadow-[0_0_8px_rgba(99,102,241,0.5)]" size={20} />
                    </div>
                    <div className="flex flex-wrap items-center gap-2 md:gap-3 text-xs md:text-sm">
                        <span className="font-bold tracking-wide text-white">Load Balancer</span>
                        <span className="hidden sm:inline text-gray-600">·</span>
                        <span className="rounded-lg bg-indigo-500/15 px-2.5 py-1 text-[10px] sm:text-[11px] font-bold uppercase tracking-widest text-indigo-300 border border-indigo-500/20 shadow-inner">
                            {humanizeStrategy(strategy)}
                        </span>
                        <span className="hidden sm:inline text-gray-600">·</span>
                        <span className="font-medium text-gray-400">
                            {activeCount} active
                        </span>
                        {fallback && (
                            <>
                                <span className="hidden sm:inline text-gray-600">·</span>
                                <span className="text-gray-500 text-[10px] sm:text-xs font-bold uppercase tracking-widest">Fallback on</span>
                            </>
                        )}
                    </div>
                </div>
                <ChevronDown
                    size={20}
                    className={`text-gray-500 transition-transform duration-300 ${
                        expanded ? 'rotate-180 text-blue-400' : 'group-hover:text-white'
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
                        transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
                        className="overflow-hidden bg-black/40 border-t border-white/5"
                    >
                        <div className="px-5 py-5">
                            <div className="mb-4 text-[10px] font-bold uppercase tracking-widest text-gray-500">
                                Routing Strategy
                            </div>
                            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
                                {STRATEGIES.map((s) => (
                                    <button
                                        key={s.id}
                                        type="button"
                                        className={`px-3 py-2.5 rounded-xl text-[11px] font-bold uppercase tracking-widest transition-all duration-300 shadow-inner ${
                                            strategy === s.id
                                                ? 'bg-blue-600/20 border border-blue-500/50 text-blue-300 shadow-[0_0_15px_rgba(59,130,246,0.2)]'
                                                : 'bg-white/5 border border-white/5 text-gray-400 hover:bg-white/10 hover:text-white'
                                        }`}
                                        onClick={() => onUpdateStrategy(s.id)}
                                    >
                                        {s.label}
                                    </button>
                                ))}
                            </div>
                            <div className="mt-5 flex flex-wrap items-center gap-5 text-[11px] font-bold uppercase tracking-widest text-gray-500">
                                <span className="flex items-center gap-2">
                                    <span className="inline-block h-2 w-2 rounded-full bg-green-400 shadow-[0_0_8px_rgba(74,222,128,0.5)]" />
                                    {activeCount} provider{activeCount !== 1 ? 's' : ''} active
                                </span>
                                <span className="flex items-center gap-2">
                                    <span className={`inline-block h-2 w-2 rounded-full ${fallback ? 'bg-blue-400 shadow-[0_0_8px_rgba(96,165,250,0.5)]' : 'bg-gray-600'}`} />
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
