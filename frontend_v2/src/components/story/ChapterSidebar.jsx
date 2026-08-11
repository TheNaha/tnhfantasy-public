import React, { useState } from 'react';
import { Plus, Trash2, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';

export default React.memo(function ChapterSidebar({ chapters, activeChapterId, onSelectChapter, onCreateChapter, onDeleteChapter, isLoading }) {
    const [creating, setCreating] = useState(false);

    const handleCreate = async () => {
        setCreating(true);
        try {
            await onCreateChapter({ title: `Chapter ${(chapters?.length || 0) + 1}` });
            toast.success('Chapter created');
        } catch {
            toast.error('Failed to create chapter');
        }
        setCreating(false);
    };

    return (
        <div className="w-full border-t border-white/5 bg-gray-900/40 flex flex-col shrink-0 max-h-72 min-h-0">
            <div className="h-12 flex items-center justify-between px-3 border-b border-white/5 shrink-0">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Chapters</h4>
                <button onClick={handleCreate} disabled={creating} className="p-1 text-gray-400 hover:text-white hover:bg-white/10 rounded transition-colors disabled:opacity-30" title="New chapter">
                    <Plus size={14} />
                </button>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-1 min-h-0">
                {isLoading ? (
                    <div className="flex justify-center p-3"><Loader2 className="animate-spin text-gray-500" size={14} /></div>
                ) : chapters?.length === 0 ? (
                    <p className="text-[11px] text-gray-500 text-center p-3">No chapters yet</p>
                ) : (
                    chapters?.map(ch => (
                        <div key={ch.id} className="group relative">
                            <button
                                onClick={() => onSelectChapter(ch.id)}
                                className={clsx(
                                    "w-full text-left px-2 py-1.5 rounded text-xs transition-colors flex items-center gap-1.5",
                                    activeChapterId === ch.id ? "bg-indigo-500/20 text-indigo-300" : "text-gray-400 hover:bg-white/5"
                                )}
                            >
                                <span className="font-mono text-[10px] text-gray-500">{ch.chapter_number}</span>
                                <span className="truncate">{ch.title || `Chapter ${ch.chapter_number}`}</span>
                            </button>
                            {onDeleteChapter && (
                                <button
                                    onClick={(e) => { e.stopPropagation(); onDeleteChapter(ch.id); }}
                                    className="absolute right-1 top-1 p-1 opacity-0 group-hover:opacity-100 hover:text-red-400 text-gray-500 rounded transition-all"
                                    title="Delete chapter"
                                >
                                    <Trash2 size={10} />
                                </button>
                            )}
                        </div>
                    ))
                )}
            </div>
        </div>
    );
});
