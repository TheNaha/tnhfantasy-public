import React, { useState } from 'react';
import { Plus, Trash2, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';

export default React.memo(function StorySidebar({ stories, activeStoryId, onSelectStory, onCreateStory, onDeleteStory, isLoading }) {
    const [creating, setCreating] = useState(false);
    const [newTitle, setNewTitle] = useState('');

    const handleCreate = async () => {
        if (!newTitle.trim()) return;
        setCreating(true);
        try {
            await onCreateStory({ title: newTitle.trim() });
            setNewTitle('');
            toast.success('Story created');
        } catch {
            toast.error('Failed to create story');
        }
        setCreating(false);
    };

    return (
        <div className="flex flex-col shrink-0 min-h-0 flex-1">
            <div className="h-16 flex items-center justify-between px-4 border-b border-white/5 shrink-0">
                <h3 className="font-semibold text-gray-200">Stories</h3>
            </div>
            <div className="p-2 border-b border-white/5">
                <div className="flex gap-1">
                    <input
                        type="text"
                        value={newTitle}
                        onChange={e => setNewTitle(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') handleCreate(); }}
                        placeholder="New story title..."
                        className="flex-1 bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                        disabled={creating}
                    />
                    <button onClick={handleCreate} disabled={creating || !newTitle.trim()} className="p-1.5 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors disabled:opacity-30" title="Create Story">
                        <Plus size={18} />
                    </button>
                    <button onClick={() => window.dispatchEvent(new CustomEvent('open-parse-story'))} className="p-1.5 text-indigo-400 hover:text-indigo-300 hover:bg-indigo-500/10 rounded-lg transition-colors" title="Import & Parse Story">
                        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21 16-4 4-4-4"/><path d="M17 20V4"/><path d="m3 8 4-4 4 4"/><path d="M7 4v16"/></svg>
                    </button>
                </div>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-1">
                {isLoading ? (
                    <div className="flex justify-center p-4"><Loader2 className="animate-spin text-gray-500" /></div>
                ) : stories?.length === 0 ? (
                    <p className="text-xs text-gray-500 text-center p-4">No stories yet. Create one above.</p>
                ) : (
                    stories?.map(story => (
                        <div key={story.id} className="group relative">
                            <button
                                onClick={() => onSelectStory(story.id)}
                                className={clsx(
                                    "w-full text-left px-3 py-2 rounded-lg text-sm transition-colors flex items-center justify-between",
                                    activeStoryId === story.id ? "bg-indigo-500/20 text-indigo-300" : "text-gray-400 hover:bg-white/5"
                                )}
                            >
                                <span className="truncate flex-1">{story.title}</span>
                                {story.is_archived && <span className="text-[9px] uppercase text-amber-500/80 mr-1 shrink-0">archived</span>}
                                {story.genre && <span className="text-[10px] text-gray-500 ml-2 shrink-0">{story.genre}</span>}
                            </button>
                            <button
                                onClick={(e) => { e.stopPropagation(); onDeleteStory(story); }}
                                className="absolute right-1 top-1 p-1 opacity-0 group-hover:opacity-100 hover:text-red-400 text-gray-500 rounded transition-all"
                                title="Delete story"
                            >
                                <Trash2 size={12} />
                            </button>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
});
