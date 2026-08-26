import React from 'react';
import { GitBranch, Play, ImageIcon, Loader2, FileDown, BookOpen, Wand2, PenLine, Maximize2, ScrollText, RotateCcw } from 'lucide-react';
import clsx from 'clsx';

const iconBtn = "flex items-center justify-center px-3 py-2 rounded-lg font-medium transition-all text-sm";

export default React.memo(function StoryActionBar({
    beatCount,
    showBeatsPanel,
    onToggleBeats,
    isStreaming,
    isContinuePending,
    onContinue,
    aiDirective,
    onAiDirectiveChange,
    canRetryLast,
    onRetryLast,
    onAiAction,
    isIllustrating,
    onIllustrate,
    beatInput,
    onBeatInputChange,
    onAddBeat,
    beatRole,
    onBeatRoleChange,
    onExport,
    onPublish,
    isPublished,
    onNarrate,
    activeChapterId,
    onBatchVariations,
    hasIllustration,
}) {
    return (
        <div className="max-w-3xl mx-auto flex flex-col sm:flex-row gap-2 sm:gap-3">
            <div className="grid grid-cols-2 sm:flex gap-2 shrink-0">
                <button
                    onClick={onToggleBeats}
                    className={clsx(
                        "flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all text-sm",
                        showBeatsPanel
                            ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                            : "bg-gray-800 text-gray-300 hover:bg-gray-700"
                    )}
                    title="Show story beats (fork points)"
                >
                    <GitBranch size={14} />
                    <span className="hidden sm:inline">Beats</span>
                    <span className="text-[10px] text-gray-500">({beatCount})</span>
                </button>
                <button
                    onClick={onContinue}
                    disabled={isStreaming || isContinuePending}
                    className={clsx(
                        "flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all text-sm",
                        isStreaming || isContinuePending
                            ? "bg-indigo-500/50 text-white/50 cursor-not-allowed"
                            : "bg-indigo-600 text-white hover:bg-indigo-500"
                    )}
                >
                    {isStreaming || isContinuePending ? (
                        <><Loader2 size={14} className="animate-spin" /> Gen...</>
                    ) : (
                        <><Play size={14} fill="currentColor" /> Continue</>
                    )}
                </button>
                {onRetryLast && (
                    <button
                        onClick={onRetryLast}
                        disabled={isStreaming || isContinuePending || !canRetryLast}
                        className={clsx(iconBtn, "bg-gray-800 text-gray-300", (isStreaming || isContinuePending || !canRetryLast) ? "opacity-40 cursor-not-allowed" : "hover:bg-gray-700")}
                        title={canRetryLast ? "Discard the AI's last continuation and regenerate it" : "No AI continuation to retry yet"}
                    >
                        <RotateCcw size={14} />
                        <span className="hidden sm:inline">Retry</span>
                    </button>
                )}
                {onAiAction && (
                    <>
                        <button onClick={() => onAiAction('rewrite')} disabled={isStreaming} className={clsx(iconBtn, "bg-gray-800 text-indigo-300", isStreaming ? "opacity-40 cursor-not-allowed" : "hover:bg-gray-700")} title="Rewrite the selected text with AI">
                            <PenLine size={14} />
                        </button>
                        <button onClick={() => onAiAction('expand')} disabled={isStreaming} className={clsx(iconBtn, "bg-gray-800 text-purple-300", isStreaming ? "opacity-40 cursor-not-allowed" : "hover:bg-gray-700")} title="Expand the selected text with more detail">
                            <Maximize2 size={14} />
                        </button>
                        <button onClick={() => onAiAction('summarize')} disabled={isStreaming} className={clsx(iconBtn, "bg-gray-800 text-emerald-300", isStreaming ? "opacity-40 cursor-not-allowed" : "hover:bg-gray-700")} title="Summarize the selected text (or whole chapter)">
                            <ScrollText size={14} />
                        </button>
                    </>
                )}
                <button
                    onClick={onIllustrate}
                    disabled={isIllustrating}
                    className={clsx(
                        "flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all text-sm",
                        isIllustrating
                            ? "bg-amber-500/50 text-white/50 cursor-not-allowed"
                            : "bg-amber-600 text-white hover:bg-amber-500"
                    )}
                >
                    {isIllustrating ? (
                        <><Loader2 size={14} className="animate-spin" /> Illus...</>
                    ) : (
                        <><ImageIcon size={14} /> Illustrate</>
                    )}
                </button>
                {hasIllustration && onBatchVariations && (
                    <button
                        onClick={onBatchVariations}
                        className={clsx(
                            "flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all text-sm",
                            "bg-purple-600 text-white hover:bg-purple-500"
                        )}
                        title="Generate batch variations of the last illustration"
                    >
                        <Wand2 size={14} />
                        <span className="hidden sm:inline">Variations</span>
                    </button>
                )}
            </div>

            <div className="flex-1 flex flex-col gap-2 w-full min-w-0">
                <div className="flex gap-2 w-full">
                    {onBeatRoleChange && (
                        <div className="flex shrink-0 rounded-lg border border-gray-700/50 overflow-hidden" role="group" aria-label="New beat role">
                            {['user', 'narrator'].map((r) => (
                                <button
                                    key={r}
                                    type="button"
                                    onClick={() => onBeatRoleChange(r)}
                                    className={clsx(
                                        "px-2.5 text-[10px] font-semibold uppercase tracking-wide transition-colors",
                                        beatRole === r
                                            ? r === 'user'
                                                ? "bg-blue-500/20 text-blue-300"
                                                : "bg-purple-500/20 text-purple-300"
                                            : "bg-gray-800/60 text-gray-500 hover:text-gray-300"
                                    )}
                                    title={r === 'user' ? "Add as your own input (prefixed with > in the prose)" : "Add as narrator prose"}
                                >
                                    {r}
                                </button>
                            ))}
                        </div>
                    )}
                    <input
                        type="text"
                        value={beatInput}
                        onChange={(e) => onBeatInputChange(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && onAddBeat()}
                        placeholder="Add a story beat..."
                        className="flex-1 bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 sm:px-4 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-indigo-500/50 min-w-0"
                    />
                    <button
                        onClick={onAddBeat}
                        disabled={!beatInput.trim()}
                        className="px-3 sm:px-4 py-2 bg-gray-800 text-gray-300 rounded-lg text-sm font-medium hover:bg-gray-700 disabled:opacity-50 transition-colors shrink-0"
                    >
                        Add
                    </button>
                </div>
                {onAiDirectiveChange && (
                    <input
                        type="text"
                        value={aiDirective || ''}
                        onChange={(e) => onAiDirectiveChange(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && !isStreaming && !isContinuePending && onContinue()}
                        placeholder="Direct the AI before continuing (optional) — e.g. 'introduce a storm', 'in first person'"
                        className="w-full bg-gray-800/30 border border-gray-700/30 rounded-lg px-3 sm:px-4 py-1.5 text-xs text-gray-300 placeholder-gray-600 focus:outline-none focus:border-indigo-500/50 min-w-0"
                    />
                )}
            </div>

            <div className="flex gap-2 shrink-0">
                {activeChapterId && onNarrate && (
                    <button
                        onClick={() => onNarrate(activeChapterId)}
                        className="flex items-center gap-2 px-3 py-2 bg-purple-600 text-white rounded-lg font-medium hover:bg-purple-700 transition-all text-sm"
                        title="Narrate chapter with TTS"
                    >
                        <Play size={14} /> <span className="hidden sm:inline">Narrate</span>
                    </button>
                )}
                {onExport && (
                    <button
                        onClick={onExport}
                        className="flex items-center gap-2 px-3 py-2 bg-gray-800 text-gray-300 rounded-lg font-medium hover:bg-gray-700 transition-all text-sm"
                        title="Export story"
                    >
                        <FileDown size={14} /> <span className="hidden sm:inline">Export</span>
                    </button>
                )}
                {onPublish && !isPublished && (
                    <button
                        onClick={onPublish}
                        className="flex items-center gap-2 px-3 py-2 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 transition-all text-sm"
                        title="Publish story to web"
                    >
                        <BookOpen size={14} /> <span className="hidden sm:inline">Publish</span>
                    </button>
                )}
            </div>
        </div>
    );
});
