import React, { useState } from 'react';
import { Plus, Trash2, Loader2, GripVertical } from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import {
    DndContext,
    closestCenter,
    PointerSensor,
    useSensor,
    useSensors,
} from '@dnd-kit/core';
import {
    arrayMove,
    SortableContext,
    useSortable,
    verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { QueryErrorState } from '../common/QueryState';

const ChapterItem = React.memo(function ChapterItem({ chapter, isActive, onSelect, onDelete, hasDelete }) {
    const {
        attributes,
        listeners,
        setNodeRef,
        transform,
        transition,
        isDragging,
    } = useSortable({ id: chapter.id });

    const style = {
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.4 : 1,
    };

    return (
        <div ref={setNodeRef} style={style} className="group relative flex items-center">
            <button
                {...attributes}
                {...listeners}
                className="p-0.5 text-gray-600 hover:text-gray-300 cursor-grab active:cursor-grabbing touch-none shrink-0"
                title="Drag to reorder chapters"
            >
                <GripVertical size={10} />
            </button>
            <button
                onClick={() => onSelect(chapter.id)}
                className={clsx(
                    "flex-1 min-w-0 text-left px-1.5 py-1.5 rounded text-xs transition-colors flex items-center gap-1.5",
                    isActive ? "bg-indigo-500/20 text-indigo-300" : "text-gray-400 hover:bg-white/5"
                )}
            >
                <span className="font-mono text-xs text-gray-500">{chapter.chapter_number}</span>
                <span className="truncate">{chapter.title || `Chapter ${chapter.chapter_number}`}</span>
            </button>
            {hasDelete && (
                <button
                    onClick={(e) => { e.stopPropagation(); onDelete(chapter.id); }}
                    className="absolute right-1 top-1 p-1 opacity-0 group-hover:opacity-100 hover:text-red-400 text-gray-500 rounded transition-all"
                    title="Delete chapter"
                >
                    <Trash2 size={10} />
                </button>
            )}
        </div>
    );
});

/**
 * The chapter list for the open story.
 *
 * `isError`/`error`/`onRetry` are the caller's `useStoryChapters()` failure.
 * That query destructured `data` with a `= []` default and no `isError`, so a
 * failed fetch rendered "No chapters yet" under a **+** button that creates a
 * chapter — next to a story that already had several.
 */
export default React.memo(function ChapterSidebar({ chapters, activeChapterId, onSelectChapter, onCreateChapter, onDeleteChapter, onReorder, isLoading, isError, error, onRetry }) {
    const [creating, setCreating] = useState(false);
    const sensors = useSensors(
        useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    );

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

    const handleDragEnd = (event) => {
        const { active, over } = event;
        if (!over || active.id === over.id || !onReorder || !chapters) return;

        const oldIndex = chapters.findIndex(c => c.id === active.id);
        const newIndex = chapters.findIndex(c => c.id === over.id);
        if (oldIndex < 0 || newIndex < 0) return;

        onReorder(arrayMove(chapters, oldIndex, newIndex));
    };

    const canReorder = Boolean(onReorder) && (chapters?.length || 0) > 1;

    return (
        <div className="w-full border-t border-white/5 bg-gray-900/40 flex flex-col shrink-0 max-h-72 min-h-0">
            <div className="h-12 flex items-center justify-between px-3 border-b border-white/5 shrink-0">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Chapters</h4>
                <div className="flex items-center gap-1">
                    {canReorder && (
                        <GripVertical size={12} className="text-gray-500 opacity-40" title="Drag chapters to reorder" />
                    )}
                    <button onClick={handleCreate} disabled={creating} className="p-1 text-gray-400 hover:text-white hover:bg-white/10 rounded transition-colors disabled:opacity-30" title="New chapter">
                        <Plus size={14} />
                    </button>
                </div>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-1 min-h-0">
                {isLoading ? (
                    <div className="flex justify-center p-3"><Loader2 className="animate-spin text-gray-500" size={14} /></div>
                ) : isError ? (
                    <div className="p-2">
                        <QueryErrorState noun="chapters" error={error} onRetry={onRetry} />
                    </div>
                ) : chapters?.length === 0 ? (
                    <p className="text-2xs text-gray-500 text-center p-3">No chapters yet</p>
                ) : canReorder ? (
                    <DndContext
                        sensors={sensors}
                        collisionDetection={closestCenter}
                        onDragEnd={handleDragEnd}
                    >
                        <SortableContext
                            items={chapters.map(ch => ch.id)}
                            strategy={verticalListSortingStrategy}
                        >
                            {chapters.map(ch => (
                                <ChapterItem
                                    key={ch.id}
                                    chapter={ch}
                                    isActive={activeChapterId === ch.id}
                                    onSelect={onSelectChapter}
                                    onDelete={onDeleteChapter}
                                    hasDelete={Boolean(onDeleteChapter)}
                                />
                            ))}
                        </SortableContext>
                    </DndContext>
                ) : (
                    chapters?.map(ch => (
                        <ChapterItem
                            key={ch.id}
                            chapter={ch}
                            isActive={activeChapterId === ch.id}
                            onSelect={onSelectChapter}
                            onDelete={onDeleteChapter}
                            hasDelete={Boolean(onDeleteChapter)}
                        />
                    ))
                )}
            </div>
        </div>
    );
});
