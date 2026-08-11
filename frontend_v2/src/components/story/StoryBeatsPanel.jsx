import React from 'react';
import { GitBranch, X, Loader2 } from 'lucide-react';
import clsx from 'clsx';

export default React.memo(function StoryBeatsPanel({
    beats,
    isStreaming,
    branchingBeatId,
    branchPending,
    onBranch,
    onClose,
}) {
    return (
        <div className="max-w-3xl mx-auto mb-3 max-h-56 overflow-y-auto custom-scrollbar rounded-xl border border-white/5 bg-gray-950/60 p-3 space-y-1.5">
            <div className="flex items-center justify-between mb-1.5">
                <h4 className="text-[11px] font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                    <GitBranch size={11} /> Story Beats
                </h4>
                <button
                    onClick={onClose}
                    className="p-1 text-gray-500 hover:text-white hover:bg-white/10 rounded transition-colors"
                    title="Close beats panel"
                >
                    <X size={12} />
                </button>
            </div>
            {beats.length === 0 ? (
                <p className="text-xs text-gray-500 text-center py-2">No beats recorded yet. Use the beat input below or press Continue.</p>
            ) : (
                beats.map((beat, idx) => {
                    const beatId = beat?.id || null;
                    const isUser = beat?.role === 'user';
                    const snippet = (beat?.content || '').length > 140
                        ? (beat?.content || '').slice(0, 140) + '…'
                        : (beat?.content || '');
                    return (
                        <div key={beatId || idx} className="group flex items-start gap-2 rounded-lg bg-white/[0.03] border border-white/5 px-2.5 py-1.5">
                            <span className={clsx(
                                "mt-0.5 shrink-0 text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded",
                                isUser ? "bg-blue-500/15 text-blue-300" : "bg-purple-500/15 text-purple-300"
                            )}>
                                {isUser ? 'user' : (beat?.role || 'narrator')}
                            </span>
                            <p className="flex-1 text-xs text-gray-400 leading-relaxed min-w-0">{snippet || <span className="italic text-gray-600">(empty)</span>}</p>
                            <button
                                onClick={() => onBranch(beatId)}
                                disabled={!beatId || isStreaming || branchPending || branchingBeatId === beatId}
                                className="shrink-0 opacity-60 group-hover:opacity-100 disabled:opacity-20 flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 hover:bg-amber-500/20 transition-colors"
                                title="Branch the story from this beat into a new chapter"
                            >
                                {branchingBeatId === beatId ? <Loader2 size={10} className="animate-spin" /> : <GitBranch size={10} />}
                                Branch
                            </button>
                        </div>
                    );
                })
            )}
        </div>
    );
});
