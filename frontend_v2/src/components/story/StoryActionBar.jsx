import React from 'react';
import { GitBranch, Play, ImageIcon, Loader2, FileDown, BookOpen, Wand2, PenLine, Maximize2, ScrollText, RotateCcw, History, Sparkles } from 'lucide-react';
import clsx from 'clsx';

const iconBtn = "flex items-center justify-center px-3 py-2 rounded-lg font-medium transition-all text-sm";

const DIRECTOR_PRESETS = [
    { id: 'conflict', label: '⚡ Conflict', text: 'Introduce an immediate complication or dramatic plot twist that raises the stakes.' },
    { id: 'atmosphere', label: '🌧️ Atmosphere', text: 'Deepen the sensory atmosphere, physical textures, lighting, and environmental mood.' },
    { id: 'dialogue', label: '💬 Dialogue', text: 'Focus on an intense, nuanced dialogue exchange with character subtext.' },
    { id: 'action', label: '⏱️ Action', text: 'Escalate into visceral, fast-paced kinetic action and physical momentum.' },
    { id: 'introspection', label: '🎭 Introspect', text: 'Reveal intimate internal thoughts and emotional revelations.' },
];

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
    onOpenRevisions,
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
    onScanWorldbuilding,
    isDiscoveringWorld,
}) {
    return (
        // Stacked until `2xl`, not `sm`. At >=640px this was
        // `flex-direction: row` with three children that all carry `shrink-0`:
        // the left group needed 649px, the right group 299px, and the
        // `flex-1 min-w-0` beat input in between was squeezed to exactly 0px.
        // Its children then overflowed *on top of* the right group — 7 sibling
        // overlaps and up to 9 controls off-screen, measured at 640, 768 and
        // 900. Sibling overlaps rather than clipping, so panning did not help:
        // a real touch tap at the centre of "Publish story to web", 125px
        // outside the viewport, delivered no event at all.
        //
        // `sm:overflow-x-auto` was what hid this: it turns "unreachable" into
        // "the whole page pans sideways", so the editor placeholder lost its left
        // half instead. `2xl` is where 649 + 299 + a usable input actually fit.
        <div className="max-w-3xl mx-auto flex flex-col 2xl:flex-row gap-2 2xl:gap-3">
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
                    <span className="text-xs text-gray-500">({beatCount})</span>
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
                {onOpenRevisions && (
                    <button
                        onClick={onOpenRevisions}
                        className={clsx(iconBtn, "bg-gray-800 text-sky-300 hover:bg-gray-700")}
                        title="Revision history — browse and restore chapter snapshots"
                    >
                        <History size={14} />
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
                            : "bg-amber-700 text-white hover:bg-amber-600"
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
                            {['user', 'narrator', 'director'].map((r) => (
                                <button
                                    key={r}
                                    type="button"
                                    onClick={() => onBeatRoleChange(r)}
                                    className={clsx(
                                        "px-2.5 text-xs font-semibold uppercase tracking-wide transition-colors",
                                        beatRole === r
                                            ? r === 'user'
                                                ? "bg-blue-500/20 text-blue-300"
                                                : r === 'director'
                                                    ? "bg-amber-500/20 text-amber-300"
                                                    : "bg-purple-500/20 text-purple-300"
                                            : "bg-gray-800/60 text-gray-500 hover:text-gray-300"
                                    )}
                                    title={r === 'user' ? "Add as user input (>)" : r === 'director' ? "Add as director guidance note" : "Add as narrator prose"}
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
                        aria-label="Story beat" placeholder="Add a story beat..."
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
                    <div className="flex flex-col gap-1 w-full">
                        <input
                            type="text"
                            value={aiDirective || ''}
                            onChange={(e) => onAiDirectiveChange(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && !isStreaming && !isContinuePending && onContinue()}
                            placeholder="Direct the AI before continuing (optional) — e.g. 'introduce a storm', 'in first person'"
                            className="w-full bg-gray-800/30 border border-gray-700/30 rounded-lg px-3 sm:px-4 py-1.5 text-xs text-gray-300 placeholder-gray-600 focus:outline-none focus:border-indigo-500/50 min-w-0"
                        />
                        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                            <span className="text-3xs text-gray-500 font-medium">Director Presets:</span>
                            {DIRECTOR_PRESETS.map((p) => {
                                const isActive = aiDirective?.includes(p.text);
                                return (
                                    <button
                                        key={p.id}
                                        type="button"
                                        onClick={() => {
                                            if (isActive) {
                                                onAiDirectiveChange(aiDirective.replace(p.text, '').trim());
                                            } else {
                                                onAiDirectiveChange(aiDirective ? `${aiDirective.trim()} ${p.text}` : p.text);
                                            }
                                        }}
                                        className={clsx(
                                            "px-2 py-0.5 rounded-full text-3xs font-medium transition-all",
                                            isActive
                                                ? "bg-amber-500/20 text-amber-300 border border-amber-500/40 shadow-sm"
                                                : "bg-gray-800/60 text-gray-400 hover:text-gray-200 hover:bg-gray-700/60 border border-white/5"
                                        )}
                                        title={p.text}
                                    >
                                        {p.label}
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                )}
            </div>

            <div className="flex gap-2 shrink-0">
                {onScanWorldbuilding && (
                    <button
                        onClick={onScanWorldbuilding}
                        disabled={isDiscoveringWorld}
                        className="flex items-center gap-1.5 px-3 py-2 bg-gradient-to-r from-amber-600/80 to-amber-700/80 hover:from-amber-600 hover:to-amber-700 text-white rounded-lg font-medium transition-all text-sm shadow-sm"
                        title="Discover novel entities and lore from this scene"
                    >
                        {isDiscoveringWorld ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                        <span className="hidden sm:inline">Discover Lore</span>
                    </button>
                )}
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
                        className="flex items-center gap-2 px-3 py-2 bg-green-700 text-white rounded-lg font-medium hover:bg-green-600 transition-all text-sm"
                        title="Publish story to web"
                    >
                        <BookOpen size={14} /> <span className="hidden sm:inline">Publish</span>
                    </button>
                )}
            </div>
        </div>
    );
});
