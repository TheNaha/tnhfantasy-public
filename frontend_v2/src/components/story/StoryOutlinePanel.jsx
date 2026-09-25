import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import { Camera, ChevronDown, History, ListTree, Loader2 } from 'lucide-react';
import { buildStoryOutline, formatWordCount } from '../../utils/storyOutline';

/**
 * StoryOutlinePanel — progressive outline of the current story plus the
 * revision entry point. Both are built on the existing chapter/revision API
 * (`/api/v2/stories/{id}/chapters/...`), so no new backend surface is used.
 */
export default function StoryOutlinePanel({
    storyId,
    chapters = [],
    activeChapterId,
    wordCountGoal,
    onOpenRevisions,
    onSnapshot,
    isSnapshotting = false,
    onNavigate: onNavigateProp,
    defaultOpen = false,
    className = '',
}) {
    const routerNavigate = useNavigate();
    const [open, setOpen] = useState(defaultOpen);
    const outline = useMemo(
        () => buildStoryOutline(chapters, { activeChapterId, wordCountGoal }),
        [chapters, activeChapterId, wordCountGoal]
    );
    const navigateTo = onNavigateProp || routerNavigate;

    const hasActiveChapter = Boolean(activeChapterId);

    return (
        <div className={clsx('glass-panel rounded-xl border border-white/5', className)} data-testid="story-outline-panel">
            <div className="flex items-center justify-between gap-2 p-4">
                <button
                    type="button"
                    onClick={() => setOpen(o => !o)}
                    aria-expanded={open}
                    aria-controls="story-outline-body"
                    className="flex-1 min-w-0 text-left"
                >
                    <span className="flex items-center gap-1.5 text-[10px] font-semibold text-gray-300 uppercase tracking-widest">
                        <ListTree size={12} className="text-purple-400" />
                        Story Outline
                        <span className="text-[9px] text-gray-600">({outline.chapters.length})</span>
                        <ChevronDown size={13} className={clsx('text-gray-500 transition-transform', open && 'rotate-180')} aria-hidden="true" />
                    </span>
                    <span className="block text-[9px] text-gray-500 mt-0.5">
                        {formatWordCount(outline.totalWords)}
                        {outline.wordCountGoal ? ` of ${formatWordCount(outline.wordCountGoal)}` : ''}
                    </span>
                </button>
                <button
                    type="button"
                    onClick={onSnapshot}
                    disabled={!hasActiveChapter || isSnapshotting || !onSnapshot}
                    title="Save a snapshot of the current chapter"
                    className="shrink-0 inline-flex items-center gap-1 px-2 py-1 text-[9px] text-sky-300 hover:text-sky-200 bg-sky-500/10 hover:bg-sky-500/20 border border-sky-500/25 rounded-md transition-colors disabled:opacity-40"
                >
                    {isSnapshotting ? <Loader2 size={10} className="animate-spin" /> : <Camera size={10} />}
                    Snapshot
                </button>
                <button
                    type="button"
                    onClick={onOpenRevisions}
                    disabled={!hasActiveChapter || !onOpenRevisions}
                    title="Browse and restore snapshots"
                    className="shrink-0 inline-flex items-center gap-1 px-2 py-1 text-[9px] text-gray-400 hover:text-white bg-gray-800/50 hover:bg-gray-800 border border-white/5 rounded-md transition-colors disabled:opacity-40"
                >
                    <History size={10} />
                    History
                </button>
            </div>

            {open && (
                <div id="story-outline-body" role="region" className="px-3 pb-3 space-y-1.5">
                    {outline.progress != null && (
                        <div className="px-1 pb-1">
                            <div className="h-1.5 w-full rounded-full bg-gray-800 overflow-hidden">
                                <div
                                    className="h-full rounded-full bg-gradient-to-r from-purple-500 to-indigo-400 transition-all"
                                    style={{ width: `${outline.progress}%` }}
                                />
                            </div>
                            <p className="text-[9px] text-gray-500 mt-0.5">{outline.progress}% of word count goal</p>
                        </div>
                    )}

                    {outline.chapters.length === 0 ? (
                        <p className="text-[10px] text-gray-500 text-center py-3 border border-dashed border-gray-700/50 rounded-lg">
                            No chapters yet — add one to start the outline.
                        </p>
                    ) : (
                        outline.chapters.map(chapter => (
                            <button
                                key={chapter.id}
                                type="button"
                                onClick={() => storyId && navigateTo(`/story/${storyId}/chapter/${chapter.id}`)}
                                className={clsx(
                                    'w-full text-left px-2.5 py-2 rounded-lg border transition-colors',
                                    chapter.isActive
                                        ? 'bg-purple-500/15 border-purple-500/30'
                                        : 'bg-gray-800/40 border-white/5 hover:bg-gray-800'
                                )}
                            >
                                <div className="flex items-center gap-2">
                                    <span className="text-[9px] text-gray-500 font-mono shrink-0">{chapter.number}.</span>
                                    <span className={clsx('text-[11px] truncate flex-1', chapter.isActive ? 'text-purple-200' : 'text-gray-200')}>
                                        {chapter.title}
                                    </span>
                                    <span className="text-[9px] text-gray-500 shrink-0">{formatWordCount(chapter.wordCount)}</span>
                                </div>
                                {chapter.excerpt && (
                                    <p className="text-[9px] text-gray-500 mt-0.5 line-clamp-2 leading-snug">{chapter.excerpt}</p>
                                )}
                            </button>
                        ))
                    )}
                </div>
            )}
        </div>
    );
}
