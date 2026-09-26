import React, { useCallback, useState } from 'react';
import { BookOpen, Sparkles, Loader2, Save, Edit3, Book, Layers, ImageIcon, Download, FileText } from 'lucide-react';
import clsx from 'clsx';

export default React.memo(function StoryHeader({
    activeStory,
    activeChapter,
    activeChapterId,
    isGeneratingTitle,
    onAutoGenerateTitle,
    isSaving,
    onSave,
    isStreaming,
    isPreviewMode,
    onTogglePreview,
    isPanelOpen,
    onTogglePanel,
    mobileTab,
    onOpenContextMobile,
    onTitleChange,
    onExport,
}) {
    const serverTitle = activeStory?.title || '';
    // The title box holds a local draft rather than `defaultValue`, so what is
    // on screen is what the field believes, and clearing it is a value the
    // field can actually hold and commit. Uncontrolled, an emptied box stayed
    // empty forever while the row kept the old title in the database — and the
    // field was keyed on the story id, so switching stories was the only way to
    // resynchronise it.
    const [draftTitle, setDraftTitle] = useState(serverTitle);
    const [syncedTitle, setSyncedTitle] = useState(serverTitle);

    // Re-sync on a story switch or an out-of-band rename (auto-generate title,
    // a rollback). Adjusted during render, the ContextSlider pattern, so no
    // effect can land after the user has started typing.
    if (serverTitle !== syncedTitle) {
        setSyncedTitle(serverTitle);
        setDraftTitle(serverTitle);
    }

    // `onTitleChange` reads `event.target.value`, so Enter reuses the same
    // commit path as blur instead of duplicating the payload shape here.
    const handleTitleKeyDown = useCallback((e) => {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        e.currentTarget.blur();
    }, []);

    return (
        <div className="h-16 border-b border-white/5 flex items-center justify-between px-2 sm:px-6 bg-gray-900/60 backdrop-blur-md z-10 shrink-0 gap-2">
            <div className="flex items-center gap-1 sm:gap-3 min-w-0 flex-1">
                <div className="md:hidden p-1.5 sm:p-2 text-gray-500">
                    <BookOpen size={20} />
                </div>
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500/20 to-purple-500/20 border border-white/10 hidden sm:flex items-center justify-center shrink-0">
                    <BookOpen className="text-indigo-400" size={20} />
                </div>
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 min-w-0">
      <input
        type="text"
        value={draftTitle}
        onChange={(e) => setDraftTitle(e.target.value)}
                            onBlur={onTitleChange}
                            onKeyDown={handleTitleKeyDown}
                            placeholder="Untitled story"
                            aria-label="Story title"
                            className="bg-transparent font-semibold text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-500/50 rounded px-1 transition-all w-full truncate text-sm sm:text-base"
                        />
                    </div>
                    <div className="flex items-center gap-1 sm:gap-2 px-1 min-w-0">
                         <div className="flex flex-col min-w-0">
                             <p className="font-bold text-sm sm:text-base text-gray-200 truncate flex items-center gap-2">
                                 {activeChapter ? `${activeChapter.title || `Chapter ${activeChapter.chapter_number}`}` : 'Select a chapter'}
                                 {activeStory?.genre && <span className="hidden sm:inline font-normal text-xs text-gray-500">· {activeStory.genre}</span>}
                             </p>
                             {activeChapter?.content && (() => {
                                 const wordCount = activeChapter.content.trim().split(/\s+/).filter(Boolean).length;
                                 const readingTime = Math.ceil(wordCount / 200);
                                 return (
                                     <p className="text-[10px] text-gray-500 flex items-center gap-1">
                                         <FileText size={10} />
                                         <span>{wordCount} words · {readingTime} min read</span>
                                     </p>
                                 );
                             })()}
                         </div>
                        {activeChapter && (
                            <button 
                                onClick={onAutoGenerateTitle} 
                                disabled={isGeneratingTitle}
                                className="text-[10px] bg-indigo-500/10 text-indigo-400 px-1.5 py-0.5 rounded hover:bg-indigo-500/20 transition-colors flex items-center gap-1 disabled:opacity-50 shrink-0"
                                title="Auto-generate chapter title using AI"
                            >
                                {isGeneratingTitle ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
                                <span className="hidden sm:inline">Auto Title</span>
                            </button>
                        )}
                    </div>
                </div>
            </div>
            
            <div className="flex items-center gap-1 sm:gap-2 shrink-0">
                {activeChapterId && (
                    <button
                        onClick={onSave}
                        disabled={isStreaming || isSaving}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-green-500/20 text-green-300 rounded-lg hover:bg-green-500/30 transition-colors disabled:opacity-30"
                        title="Save chapter content"
                    >
                        {isSaving ? <Loader2 size={12} className="animate-spin" /> : <Save size={14} />}
                        Save
                    </button>
                )}
                {onExport && activeStory && (
                    <button
                        onClick={onExport}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-blue-500/20 text-blue-300 rounded-lg hover:bg-blue-500/30 transition-colors"
                        title="Export story as JSON"
                    >
                        <Download size={14} />
                        <span className="hidden sm:inline">Export</span>
                    </button>
                )}
                        <button
                            onClick={onTogglePreview}
                            className={clsx(
                                "p-1.5 sm:p-2 rounded-lg transition-colors border",
                                isPreviewMode ? "bg-purple-500/20 text-purple-400 border-purple-500/30" : "bg-white/5 text-gray-400 border-white/5 hover:text-white hover:bg-white/10"
                            )}
                            title={isPreviewMode ? "Edit Mode" : "Preview Mode"}
                        >
                            {isPreviewMode ? <Edit3 size={16} /> : <Book size={16} />}
                        </button>
                <button
                    onClick={onOpenContextMobile}
                    aria-label="Open context panel"
                    title="Context panel"
                    className={clsx(
                        "p-2 rounded-lg transition-colors border flex lg:hidden",
                        mobileTab === 'context' ? "bg-indigo-500/20 text-indigo-400 border-indigo-500/30" : "bg-white/5 text-gray-400 border-white/5 hover:text-white hover:bg-white/10"
                    )}
                >
                    <Layers size={20} />
                </button>
                <button
                    onClick={onTogglePanel}
                    aria-label="Toggle context panel"
                    title="Context panel"
                    className={clsx(
                        "p-2 rounded-lg transition-colors border hidden lg:flex",
                        isPanelOpen ? "bg-indigo-500/20 text-indigo-400 border-indigo-500/30" : "bg-white/5 text-gray-400 border-white/5 hover:text-white hover:bg-white/10"
                    )}
                >
                    <ImageIcon size={20} />
                </button>
            </div>
        </div>
    );
});
