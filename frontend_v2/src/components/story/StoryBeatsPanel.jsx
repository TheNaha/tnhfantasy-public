import React from 'react';
import { GitBranch, X, Loader2, GripVertical, Volume2 } from 'lucide-react';
import clsx from 'clsx';
import { assetUrl } from '../../utils/assetUrl';
import {
    DndContext,
    closestCenter,
    KeyboardSensor,
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

const BeatItem = React.memo(function BeatItem({ beat, idx, isUser, isStreaming, branchPending, branchingBeatId, onBranch }) {
    const beatId = beat?.id || null;
    const snippet = (beat?.content || '').length > 140
        ? (beat?.content || '').slice(0, 140) + '…'
        : (beat?.content || '');

    const {
        attributes,
        listeners,
        setNodeRef,
        transform,
        transition,
        isDragging,
    } = useSortable({ id: beatId || `beat-${idx}` });

    const style = {
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.4 : 1,
    };

    return (
        <div
            ref={setNodeRef}
            style={style}
            {...attributes}
            {...listeners}
            className="group flex items-start gap-2 rounded-lg bg-white/[0.03] border border-white/5 px-2.5 py-1.5 cursor-grab active:cursor-grabbing"
        >
            <span className={clsx(
                "mt-0.5 shrink-0 text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded inline-flex items-center gap-1",
                isUser
                    ? "bg-blue-500/15 text-blue-300"
                    : beat?.role === 'system_tts'
                        ? "bg-sky-500/15 text-sky-300"
                        : "bg-purple-500/15 text-purple-300"
            )}>
                {beat?.role === 'system_tts' && <Volume2 size={9} />}
                {isUser ? 'user' : (beat?.role || 'narrator')}
            </span>
            <p className="flex-1 text-xs text-gray-400 leading-relaxed min-w-0">{snippet || <span className="italic text-gray-600">(empty)</span>}</p>
            {beat?.audio_path && (
                <audio src={assetUrl(beat.audio_path)} controls className="shrink-0 h-7 w-44" title="Chapter narration" />
            )}
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
});

export default React.memo(function StoryBeatsPanel({
    beats,
    isStreaming,
    branchingBeatId,
    branchPending,
    onBranch,
    onReorder,
    onClose,
}) {
    const sensors = useSensors(
        useSensor(PointerSensor),
        useSensor(KeyboardSensor),
    );

    const handleDragEnd = (event) => {
        const { active, over } = event;
        if (!over || active.id === over.id || !onReorder) return;

        const oldIndex = beats.findIndex(b => (b?.id || `beat-${beats.indexOf(b)}`) === active.id);
        const newIndex = beats.findIndex(b => (b?.id || `beat-${beats.indexOf(b)}`) === over.id);
        if (oldIndex < 0 || newIndex < 0) return;

        const reordered = arrayMove(beats, oldIndex, newIndex);
        onReorder(reordered);
    };

    return (
        <div className="max-w-3xl mx-auto mb-3 max-h-56 overflow-y-auto custom-scrollbar rounded-xl border border-white/5 bg-gray-950/60 p-3 space-y-1.5">
            <div className="flex items-center justify-between mb-1.5">
                <h4 className="text-[11px] font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                    <GitBranch size={11} /> Story Beats
                </h4>
                <div className="flex items-center gap-1">
                    {!isStreaming && onReorder && (
                        <GripVertical size={12} className="text-gray-500 opacity-40" title="Drag beats to reorder" />
                    )}
                    <button
                        onClick={onClose}
                        className="p-1 text-gray-500 hover:text-white hover:bg-white/10 rounded transition-colors"
                        title="Close beats panel"
                    >
                        <X size={12} />
                    </button>
                </div>
            </div>
            {beats.length === 0 ? (
                <p className="text-xs text-gray-500 text-center py-2">No beats recorded yet. Use the beat input below or press Continue.</p>
            ) : (
                <DndContext
                    sensors={sensors}
                    collisionDetection={closestCenter}
                    onDragEnd={handleDragEnd}
                >
                    <SortableContext
                        items={beats.map((b, i) => b?.id || `beat-${i}`)}
                        strategy={verticalListSortingStrategy}
                    >
                        <div className="relative">
                            {beats.map((beat, idx) => {
                                const isUser = beat?.role === 'user';
                                return (
                                    <BeatItem
                                        key={beat?.id || idx}
                                        beat={beat}
                                        idx={idx}
                                        isUser={isUser}
                                        isStreaming={isStreaming}
                                        branchPending={branchPending}
                                        branchingBeatId={branchingBeatId}
                                        onBranch={onBranch}
                                    />
                                );
                            })}
                        </div>
                    </SortableContext>
                </DndContext>
            )}
        </div>
    );
});
