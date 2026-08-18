import React from 'react';
import { GitBranch, Play, ImageIcon, Loader2, FileDown, BookOpen, Wand2 } from 'lucide-react';
import clsx from 'clsx';

export default React.memo(function StoryActionBar({
    beatCount,
    showBeatsPanel,
    onToggleBeats,
    isStreaming,
    isContinuePending,
    onContinue,
    isIllustrating,
    onIllustrate,
    beatInput,
    onBeatInputChange,
    onAddBeat,
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

            <div className="flex-1 flex gap-2 w-full">
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
