import { memo, useState, useRef, useEffect } from 'react';
import clsx from 'clsx';
import {
    Activity, Check, ChevronLeft, ChevronRight, ChevronDown, Clock, MapPin,
    MessageSquare, Pencil, Pin, PinOff, RotateCcw, Undo2, Sparkles, Volume2, Trash2, ImageIcon
} from 'lucide-react';
import { thumbUrl, assetUrl } from '../../utils/assetUrl';
import { getAvatarUrl } from '../../hooks/useWorldVault';
import TavernMessage from './TavernMessage';
import ContextTracePanel from './ContextTracePanel';
import { useConfirmation } from '../../store/confirmationStore';

const MessageItem = memo(function MessageItem({ msg, linkedCharacter, activeChat, canRegenerate, onEdit, onDelete, onRegenerate, onRollback, onPin, onSwipe, onGenerateSwipe, onAvatarClick, onGenerateTTS, onIllustrate, ttsEnabled = false, voices = [], chatTtsVoiceId, characterVoiceId }) {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(msg.content);
    const [voiceMenuOpen, setVoiceMenuOpen] = useState(false);
    const voiceBtnRef = useRef(null);
    const { confirm } = useConfirmation();

    useEffect(() => {
        const close = (e) => voiceMenuOpen && !voiceBtnRef.current?.contains(e.target) && setVoiceMenuOpen(false);
        document.addEventListener('mousedown', close);
        return () => document.removeEventListener('mousedown', close);
    }, [voiceMenuOpen]);

    const hasVoices = Array.isArray(voices) && voices.length > 0;

    const meta = msg.message_metadata || {};
    const isNarrator = msg.kind === 'narrator' || meta.source === 'narrator';
    const isIdleSim = meta.source === 'idle_simulation' || meta.idle_simulation === true;
    const alternates = meta.alternates || null;
    const activeIndex = meta.active_index ?? 0;
    const altCount = alternates ? alternates.length : 0;
    if (meta.source === 'world_state') {
        return (
            <div className="flex items-center gap-3 w-full max-w-full self-center my-1.5 select-none">
                <div className="flex-1 h-px bg-gradient-to-r from-transparent via-gray-600/50 to-transparent" />
                <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-gray-800/70 border border-gray-700/50 text-xs text-gray-400 tracking-wide whitespace-nowrap">
                    {meta.location && (
                        <span className="flex items-center gap-1.5">
                            <MapPin size={10} className="text-amber-400" />
                            {meta.old_location && <span className="opacity-50">{meta.old_location} →</span>}
                            <span className="font-medium text-amber-100/90">{meta.location}</span>
                        </span>
                    )}
                    {meta.location && meta.time && <span className="opacity-40">·</span>}
                    {meta.time && (
                        <span className="flex items-center gap-1.5">
                            <Clock size={10} className="text-sky-400" />
                            {meta.old_time && <span className="opacity-50">{meta.old_time} →</span>}
                            <span className="font-medium text-sky-100/90">{meta.time}</span>
                        </span>
                    )}
                </div>
                <div className="flex-1 h-px bg-gradient-to-r from-gray-600/50 via-transparent to-transparent" />
            </div>
        );
    }

    const saveEdit = () => {
        const trimmed = draft.trim();
        if (!trimmed) return;
        onEdit?.(msg.id, trimmed);
        setEditing(false);
    };

    return (
        <div className={clsx(
            "flex gap-2 sm:gap-3 max-w-[90%] sm:max-w-[85%] group/message",
            msg.role === 'user' ? "self-end flex-row-reverse" : "self-start flex-row"
        )}>
            {msg.role !== 'user' && msg.role !== 'system' && (
                <button
                    type="button"
                    onClick={() => linkedCharacter?.avatar_path && onAvatarClick?.(getAvatarUrl(linkedCharacter.id))}
                    className={clsx(
                        "w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center shrink-0 overflow-hidden self-end",
                        linkedCharacter?.avatar_path && "cursor-pointer hover:border-blue-500/50 transition-colors"
                    )}
                >
                    {linkedCharacter?.avatar_path
                        ? <img src={getAvatarUrl(linkedCharacter.id)} alt="" className="w-full h-full object-cover" />
                        : <MessageSquare className="text-blue-400" size={12} />
                    }
                </button>
            )}
            <div className="flex flex-col max-w-full">
                <div className={clsx("text-xs mb-1", msg.role === 'user' ? "text-gray-500 text-right" : "text-gray-400")}>
                    {msg.role === 'user'
                        ? (activeChat?.persona_name || 'You')
                        : isNarrator
                            ? '✦ Narrator'
                        : msg.role === 'system'
                            ? '✦ System'
                        : (linkedCharacter?.name || 'AI')}
                    {msg.kind === 'image' && msg.image_path && (
                        <span className="ml-1.5 text-pink-400/80">· 🖼️ Image</span>
                    )}
                    {msg.kind === 'tool' && (
                        <span className="ml-1.5 text-purple-400/80">· 🔧 Tool</span>
                    )}
                    {isIdleSim && (
                        <span className="ml-1.5 text-amber-400/80">· 💤 Idle sim</span>
                    )}
                    {(meta.context_trace?.user_directive || meta.directive) && (
                        <span
                            className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300/90 text-3xs font-mono"
                            title={`Turn Directive: "${meta.context_trace?.user_directive || meta.directive}"`}
                        >
                            <span>🎯</span>
                            <span className="truncate max-w-[110px]">{meta.context_trace?.user_directive || meta.directive}</span>
                        </span>
                    )}
                </div>
                {editing ? (
                    <div className="flex flex-col gap-2">
                        <textarea
                            value={draft}
                            onChange={(e) => setDraft(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' && !e.shiftKey) {
                                    e.preventDefault();
                                    saveEdit();
                                }
                            }}
                            aria-label="Edit message content"
                            rows={3}
                            className="px-3 py-2 rounded-2xl text-sm bg-gray-900/80 border border-blue-500/40 text-gray-200 focus:outline-none resize-none"
                        />
                        <div className="flex gap-2 justify-end">
                            <button onClick={() => setEditing(false)} className="px-3 py-1.5 rounded-xl text-xs text-gray-400 hover:bg-white/5 transition-colors">Cancel</button>
                            <button onClick={saveEdit} className="px-3 py-1.5 rounded-xl text-xs bg-blue-600/30 text-blue-300 border border-blue-500/30 hover:bg-blue-600/50 transition-colors flex items-center gap-1">
                                <Check size={12} /> Save
                            </button>
                        </div>
                    </div>
                ) : (
                    <>
                        {(msg.role === 'char' || msg.role === 'assistant') ? (
                            <div className="flex flex-col gap-1.5 w-full">
                                {msg.content && <TavernMessage content={msg.content} />}
                                {ttsEnabled && meta.audio_path && (
                                    <audio src={assetUrl(meta.audio_path)} controls className="h-8 rounded w-full max-w-xs mt-1" />
                                )}
                                {msg.tool_calls?.length > 0 && (
                                    <div className="flex flex-wrap items-center gap-1.5">
                                        {typeof meta.orchestrator_depth === 'number' && (
                                            <span
                                                title={`Agentic loop depth ${meta.orchestrator_depth} / 5 (${5 - meta.orchestrator_depth} remaining)`}
                                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg bg-gray-800/40 border border-gray-700 text-xs text-gray-400 font-mono"
                                            >
                                                <Activity size={9} />
                                                Step {meta.orchestrator_depth}/{5}
                                            </span>
                                        )}
                                        {msg.tool_calls.map((tc, idx) => {
                                            const fn = tc.function || {};
                                            let argsPreview = '';
                                            try {
                                                const args = typeof fn.arguments === 'string'
                                                    ? JSON.parse(fn.arguments)
                                                    : (fn.arguments || {});
                                                argsPreview = Object.values(args)
                                                    .filter(Boolean).map(String).join(' · ').slice(0, 80);
                                            } catch {
                                                argsPreview = '';
                                            }
                                            return (
                                                <span
                                                    key={tc.id || idx}
                                                    title="Agentic tool call"
                                                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg bg-purple-500/10 border border-purple-500/25 text-xs text-purple-300 font-mono"
                                                >
                                                    <Activity size={9} />
                                                    {fn.name || 'tool'}
                                                    {argsPreview ? `: ${argsPreview}` : ''}
                                                </span>
                                            );
                                        })}
                                    </div>
                                )}
                                <ContextTracePanel trace={meta.context_trace} meta={meta} msg={msg} />
                                {msg.image_path && (
                                    <div className="mt-1">
                                        <img src={thumbUrl(msg.image_path)} alt="Attachment" loading="lazy" decoding="async" className="rounded-2xl max-w-full h-auto border border-white/10 shadow-lg" />
                                    </div>
                                )}
                                {altCount > 1 && (
                                    <div className="flex items-center gap-1.5 mt-0.5 select-none">
                                        <button
                                            onClick={() => onSwipe?.(msg.id, 'left')}
                                            className="p-0.5 min-w-6 min-h-6 inline-flex items-center justify-center rounded text-gray-600 hover:text-blue-400 transition-colors"
                                            title="Previous reply"
                                        >
                                            <ChevronLeft size={14} />
                                        </button>
                                        <span className="text-xs text-gray-600 font-mono tabular-nums">
                                            {activeIndex + 1}/{altCount}
                                        </span>
                                        <button
                                            onClick={() => onSwipe?.(msg.id, 'right')}
                                            className="p-0.5 min-w-6 min-h-6 inline-flex items-center justify-center rounded text-gray-600 hover:text-blue-400 transition-colors"
                                            title="Next reply"
                                        >
                                            <ChevronRight size={14} />
                                        </button>
                                    </div>
                                )}
                            </div>
                        ) : msg.role === 'user' ? (
                            <div className="text-sm leading-relaxed break-words text-gray-100">
                                <TavernMessage content={msg.content} alignRight />
                                {ttsEnabled && meta.audio_path && (
                                    <audio src={assetUrl(meta.audio_path)} controls className="h-8 rounded w-full max-w-xs mt-1" />
                                )}
                                {msg.image_path && (
                                    <div className="mt-3">
                                        <img src={thumbUrl(msg.image_path)} alt="Attachment" loading="lazy" decoding="async" className="rounded-xl max-w-full h-auto border border-white/10 shadow-lg" />
                                    </div>
                                )}
                            </div>
                        ) : msg.kind === 'tool' ? (
                            <div className="flex flex-wrap items-center gap-1.5">
                                {Array.isArray(msg.tool_calls) && msg.tool_calls.map((tc, idx) => {
                                    const fn = tc.function || {};
                                    let argsPreview = '';
                                    try {
                                        const args = typeof fn.arguments === 'string'
                                            ? JSON.parse(fn.arguments)
                                            : (fn.arguments || {});
                                        argsPreview = Object.values(args)
                                            .filter(Boolean).map(String).join(' · ').slice(0, 80);
                                    } catch {
                                        argsPreview = '';
                                    }
                                    return (
                                        <span
                                            key={tc.id || idx}
                                            title="Agentic tool call"
                                            className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-purple-500/10 border border-purple-500/25 text-xs text-purple-300 font-mono"
                                        >
                                            <Activity size={10} />
                                            {fn.name || 'tool'}
                                            {argsPreview ? `: ${argsPreview}` : ''}
                                        </span>
                                    );
                                })}
                            </div>
                        ) : (
                            <div className={clsx("px-3 sm:px-4 py-3 rounded-2xl text-sm leading-relaxed break-words", isNarrator ? "bg-purple-500/10 text-purple-100/90 border border-purple-500/20 rounded-tl-sm italic" : "bg-yellow-500/10 text-yellow-200/80 border border-yellow-500/15 rounded-tl-sm text-xs italic")}>
                                <span className="whitespace-pre-wrap">{msg.content}</span>
                                {msg.image_path && (
                                    <div className="mt-3">
                                        <img src={thumbUrl(msg.image_path)} alt="Attachment" loading="lazy" decoding="async" className="rounded-xl max-w-full h-auto border border-white/10 shadow-lg" />
                                    </div>
                                )}
                            </div>
                        )}
                        <div className="flex items-center gap-1 opacity-0 group-hover/message:opacity-100 focus-within:opacity-100 transition-opacity mt-0.5">
                            {(msg.role === 'user' || msg.role === 'char') && (
                                <>
                                    <button
                                        onClick={() => { setDraft(msg.content); setEditing(true); }}
                                        className="p-1 min-w-6 min-h-6 rounded-md text-gray-500 hover:text-blue-400 hover:bg-white/5 transition-colors"
                                        title="Edit message"
                                    >
                                        <Pencil size={11} />
                                    </button>
                                     <button
                                         onClick={async () => {
                                             const ok = await confirm({
                                                 title: 'Delete Message',
                                                 message: 'Delete this message?',
                                                 confirmText: 'Delete',
                                                 isDangerous: true,
                                             });
                                             if (ok) onDelete?.(msg.id);
                                         }}
                                         className="p-1 min-w-6 min-h-6 rounded-md text-gray-500 hover:text-red-400 hover:bg-white/5 transition-colors"
                                         title="Delete message"
                                     >
                                        <Trash2 size={11} />
                                    </button>
                                </>
                            )}
                            {msg.role === 'char' && altCount > 1 && (
                                <div className="flex items-center text-xs text-gray-500 font-mono px-1">
                                    <button
                                        onClick={() => onSwipe?.(msg.id, 'left')}
                                        disabled={activeIndex <= 0}
                                        className="p-1 min-w-6 min-h-6 hover:text-white disabled:opacity-30 transition-colors"
                                    >
                                        {'<'}
                                    </button>
                                    <span className="w-6 text-center select-none">
                                        {activeIndex + 1}/{altCount}
                                    </span>
                                    <button
                                        onClick={() => onSwipe?.(msg.id, 'right')}
                                        disabled={activeIndex >= altCount - 1}
                                        className="p-1 min-w-6 min-h-6 hover:text-white disabled:opacity-30 transition-colors"
                                    >
                                        {'>'}
                                    </button>
                                </div>
                            )}
                            {msg.role === 'char' && (
                                <button
                                    onClick={() => onGenerateSwipe?.(msg.id)}
                                    className="p-1 min-w-6 min-h-6 rounded-md text-gray-500 hover:text-purple-400 hover:bg-white/5 transition-colors"
                                    title="Generate alternate reply (Swipe)"
                                >
                                    <Sparkles size={11} />
                                </button>
                            )}
                            {(canRegenerate || msg.role === 'user') && (
                                <button
                                    onClick={() => onRegenerate?.(msg.id)}
                                    className="p-1 min-w-6 min-h-6 rounded-md text-gray-500 hover:text-green-400 hover:bg-white/5 transition-colors"
                                    title="Regenerate from here (Deletes following messages)"
                                >
                                    <RotateCcw size={11} />
                                </button>
                            )}
                            {ttsEnabled && (
                                <div className="relative">
                                    <button
                                        onClick={() => onGenerateTTS?.(msg.id)}
                                        className="p-1 min-w-6 min-h-6 rounded-md text-gray-500 hover:text-blue-400 hover:bg-white/5 transition-colors"
                                        title="Generate TTS"
                                    >
                                        <Volume2 size={11} />
                                    </button>
                                    {hasVoices && (
                                        <button
                                            ref={voiceBtnRef}
                                            onClick={(e) => { e.stopPropagation(); setVoiceMenuOpen(!voiceMenuOpen); }}
                                            className="p-0.5 min-w-6 min-h-6 -mr-0.5 rounded-md text-gray-500 hover:text-blue-400 hover:bg-white/5 transition-colors"
                                            title="Choose TTS voice (per-message override)"
                                        >
                                            <ChevronDown size={10} />
                                        </button>
                                    )}
                                    {voiceMenuOpen && hasVoices && (
                                        <div className="absolute z-50 mt-1 w-48 right-0 rounded-md border border-gray-700/60 bg-gray-900 shadow-lg overflow-hidden text-xs">
                                            {voices.map((v) => {
                                                const selected = v.id === chatTtsVoiceId;
                                                const isCharDefault = characterVoiceId && v.id === characterVoiceId;
                                                return (
                                                    <button
                                                        key={v.id}
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            onGenerateTTS?.(msg.id, v.id);
                                                            setVoiceMenuOpen(false);
                                                        }}
                                                        className={clsx(
                                                            "flex items-center justify-between w-full px-2 py-1.5 text-left hover:bg-white/5",
                                                            selected ? "text-blue-300" : "text-gray-400"
                                                        )}
                                                    >
                                                        <span>{v.name}</span>
                                                        <span className="flex items-center gap-0.5">
                                                            {isCharDefault && <span title="Character default">★</span>}
                                                            {selected && <Check size={10} />}
                                                        </span>
                                                    </button>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>
                            )}
                            <button
                                onClick={() => onIllustrate?.(msg.id)}
                                className="p-1 min-w-6 min-h-6 rounded-md text-gray-500 hover:text-purple-400 hover:bg-white/5 transition-colors"
                                title="Illustrate Message"
                            >
                                <ImageIcon size={11} />
                            </button>
                            <button
                                onClick={() => onRollback?.(msg.id)}
                                className="p-1 min-w-6 min-h-6 rounded-md text-gray-500 hover:text-red-400 hover:bg-white/5 transition-colors"
                                title="Rollback chat to here"
                            >
                                <Undo2 size={11} />
                            </button>
                            <button
                                onClick={() => onPin?.(msg.id, !!msg.pinned)}
                                className={clsx(
                                    "p-1 min-w-6 min-h-6 rounded-md hover:bg-white/5 transition-colors",
                                    msg.pinned ? "text-amber-400 hover:text-amber-300" : "text-gray-500 hover:text-amber-400"
                                )}
                                title={msg.pinned ? "Unpin message" : "Pin message (preserved in context)"}
                            >
                                {msg.pinned ? <Pin size={11} /> : <PinOff size={11} />}
                            </button>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
});

export default MessageItem;
