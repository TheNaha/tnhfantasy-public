import React, { useState } from 'react';
import { GitBranch, X, Loader2, GripVertical, Volume2, Pencil, Trash2, Check } from 'lucide-react';
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
import { QueryErrorState } from '../common/QueryState';

// `tts` is written by the backend's narration path (`TTS_BEAT_ROLE` in
// world_integration_service.py), so a beat authored by narration must be
// selectable here or the editor silently re-labels it.
const BEAT_ROLE_OPTIONS = ['user', 'narrator', 'system', 'tts'];

/**
 * `<` / `>` beside a beat that has more than one take.
 *
 * A chat has had this since swipes existed; a story did not, because retry used
 * to DROP the take it replaced. Now the takes accumulate on the beat and this
 * picks which one the chapter renders.
 */
const AlternateSwitcher = ({ beat, disabled, onSelect }) => {
    const alternates = Array.isArray(beat?.alternates) ? beat.alternates : [];
    if (alternates.length < 2) return null;
    const active = beat?.active_index ?? 0;
    return (
        <div className="flex items-center text-xs text-gray-500 font-mono" title="Alternate takes of this beat">
            <button
                type="button"
                onClick={() => onSelect(active - 1)}
                disabled={disabled || active <= 0}
                aria-label="Previous take"
                className="p-1 min-w-6 min-h-6 hover:text-white disabled:opacity-30 transition-colors"
            >
                {'<'}
            </button>
            <span className="w-6 text-center select-none">
                {active + 1}/{alternates.length}
            </span>
            <button
                type="button"
                onClick={() => onSelect(active + 1)}
                disabled={disabled || active >= alternates.length - 1}
                aria-label="Next take"
                className="p-1 min-w-6 min-h-6 hover:text-white disabled:opacity-30 transition-colors"
            >
                {'>'}
            </button>
        </div>
    );
};

const BeatItem = React.memo(function BeatItem({ beat, idx, isUser, isStreaming, branchPending, branchingBeatId, onBranch, onUpdateBeat, onDeleteBeat, onSelectAlternate }) {
    const beatId = beat?.id || null;
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState('');
    const [draftRole, setDraftRole] = useState('user');
    const [saving, setSaving] = useState(false);
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

    const startEdit = () => {
        setDraft(beat?.content || '');
        const current = beat?.role || 'narrator';
        setDraftRole(BEAT_ROLE_OPTIONS.includes(current) ? current : 'narrator');
        setEditing(true);
    };

    const saveEdit = async () => {
        const text = draft.trim();
        if (!text || !beatId || saving) return;
        setSaving(true);
        try {
            await onUpdateBeat(beatId, { content: text, role: draftRole });
            setEditing(false);
        } finally {
            setSaving(false);
        }
    };

    return (
        <div
            ref={setNodeRef}
            style={style}
            {...attributes}
            {...(editing ? {} : listeners)}
            className={clsx(
                "group flex items-start gap-2 rounded-lg bg-white/[0.03] border px-2.5 py-1.5",
                editing ? "border-indigo-500/40" : "border-white/5 cursor-grab active:cursor-grabbing"
            )}
        >
            <span className={clsx(
                "mt-0.5 shrink-0 text-2xs font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded inline-flex items-center gap-1",
                isUser
                    ? "bg-blue-500/15 text-blue-300"
                    : beat?.role === 'tts'
                        ? "bg-sky-500/15 text-sky-300"
                        : "bg-purple-500/15 text-purple-300"
            )}>
                {beat?.role === 'tts' && <Volume2 size={9} />}
                {isUser ? 'user' : (beat?.role || 'narrator')}
            </span>
            {editing ? (
                <div className="flex-1 min-w-0 space-y-1.5">
                    <textarea
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) saveEdit();
                            if (e.key === 'Escape') setEditing(false);
                        }}
                        rows={3}
                        autoFocus
                        className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200 focus:outline-none focus:border-indigo-500/60 resize-y custom-scrollbar"
                    />
                    <div className="flex items-center gap-1.5">
                        <select
                            value={draftRole}
                            onChange={(e) => setDraftRole(e.target.value)}
                            className="bg-gray-900 border border-gray-700 rounded px-1.5 py-0.5 text-xs text-gray-300 focus:outline-none focus:border-indigo-500/60"
                            title="Beat role"
                        >
                            {BEAT_ROLE_OPTIONS.map((r) => (
                                <option key={r} value={r}>{r}</option>
                            ))}
                        </select>
                        <button
                            onClick={saveEdit}
                            disabled={!draft.trim() || saving || isStreaming}
                            className="flex items-center gap-1 text-xs px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-30 transition-colors"
                            title="Save beat (Ctrl+Enter)"
                        >
                            {saving ? <Loader2 size={10} className="animate-spin" /> : <Check size={10} />}
                            Save
                        </button>
                        <button
                            onClick={() => setEditing(false)}
                            disabled={saving}
                            className="text-xs px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 hover:bg-gray-700 transition-colors"
                        >
                            Cancel
                        </button>
                    </div>
                </div>
            ) : (
                <>
                    <p className="flex-1 text-xs text-gray-400 leading-relaxed min-w-0">{snippet || <span className="italic text-gray-600">(empty)</span>}</p>
                    {beat?.audio_path && (
                        <audio src={assetUrl(beat.audio_path)} controls className="shrink-0 h-7 w-44" title="Chapter narration" />
                    )}
                    <div className="ml-auto shrink-0 flex items-center gap-1 opacity-60 group-hover:opacity-100 transition-opacity">
                        {/* More than one take, and the switcher between them —
                            the story counterpart of the chat swipe arrows. */}
                        <AlternateSwitcher
                            beat={beat}
                            disabled={isStreaming}
                            onSelect={(index) => onSelectAlternate?.(beatId, index)}
                        />
                        <button
                            onClick={startEdit}
                            disabled={!beatId || isStreaming}
                            className="flex items-center gap-1 text-xs px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-300 hover:bg-indigo-500/20 disabled:opacity-20 transition-colors"
                            title="Edit this beat"
                        >
                            <Pencil size={10} />
                        </button>
                        <button
                            onClick={() => onDeleteBeat(beatId)}
                            disabled={!beatId || isStreaming}
                            className="flex items-center gap-1 text-xs px-1.5 py-0.5 rounded bg-red-500/10 text-red-300 hover:bg-red-500/20 disabled:opacity-20 transition-colors"
                            title="Delete this beat and its prose"
                        >
                            <Trash2 size={10} />
                        </button>
                    </div>
                    <button
                        onClick={() => onBranch(beatId)}
                        disabled={!beatId || isStreaming || branchPending || branchingBeatId === beatId}
                        className="shrink-0 opacity-60 group-hover:opacity-100 disabled:opacity-20 flex items-center gap-1 text-xs px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 hover:bg-amber-500/20 transition-colors"
                        title="Branch the story from this beat into a new chapter"
                    >
                        {branchingBeatId === beatId ? <Loader2 size={10} className="animate-spin" /> : <GitBranch size={10} />}
                        Branch
                    </button>
                </>
            )}
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
    onUpdateBeat,
    onDeleteBeat,
    onSelectAlternate,
    onClose,
    // `beats` is `activeChapter?.beats` from the page, and a failed chapters
    // fetch leaves `activeChapter` undefined — so this panel said "No beats
    // recorded yet" while the chapter it belongs to had a page of them. The
    // page passes its own failure down.
    beatsError = null,
    onRetryBeats,
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
                <h4 className="text-2xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
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
            {beatsError ? (
                <div className="py-1">
                    <QueryErrorState noun="story beats" error={beatsError} onRetry={onRetryBeats} className="!p-3" />
                </div>
            ) : beats.length === 0 ? (
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
                                        onUpdateBeat={onUpdateBeat}
                                        onDeleteBeat={onDeleteBeat}
                                        onSelectAlternate={onSelectAlternate}
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
