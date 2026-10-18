import { useState, useRef, useEffect } from 'react';
import clsx from 'clsx';
import { Edit2, Lock, Unlock } from 'lucide-react';

/**
 * One labelled value with click-to-edit. `inline` drops the panel chrome and
 * the duplicate heading so the field can live inside a section that already
 * labels it — pass `fieldLabel` there, because the section heading is no
 * longer the field's own accessible name. `showLabel` keeps a visible caption
 * for the inline case where the surrounding section does not name this field.
 */
function ContextField({
    label,
    icon: Icon,
    value,
    placeholder,
    onSave,
    inline = false,
    showLabel = false,
    fieldLabel,
    locked = false,
    onToggleLock,
}) {
    const [editing, setEditing] = useState(false);
    const [localValue, setLocalValue] = useState(value || '');
    const inputRef = useRef(null);

    // eslint-disable-next-line react-hooks/set-state-in-effect
    useEffect(() => { setLocalValue(value || ''); }, [value]);

    const commit = () => {
        setEditing(false);
        const trimmed = localValue.trim();
        if (trimmed !== (value || '')) {
            onSave(trimmed || null);
        } else {
            setLocalValue(value || '');
        }
    };

    const body = (
        <>
            {editing ? (
                <input
                    ref={inputRef}
                    type="text"
                    value={localValue}
                    onChange={e => setLocalValue(e.target.value)}
                    onBlur={commit}
                    onKeyDown={e => {
                        if (e.key === 'Enter') commit();
                        if (e.key === 'Escape') {
                            setLocalValue(value || '');
                            setEditing(false);
                        }
                    }}
                    className="w-full bg-gray-950/50 border border-blue-500/50 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500/50"
                />
            ) : (
                <div
                    onClick={() => { setEditing(true); setTimeout(() => inputRef.current?.focus(), 0); }}
                    className="group cursor-pointer rounded-lg px-3 py-1.5 -mx-3 hover:bg-white/5 transition-colors flex items-center justify-between gap-2 min-h-[32px]"
                    title={value || placeholder}
                >
                    <span className={clsx("text-sm truncate", value ? "text-gray-200" : "text-gray-500 italic")}>
                        {value || placeholder}
                    </span>
                    <Edit2 size={12} className="shrink-0 text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
            )}
        </>
    );

    if (inline) {
        return (
            <div role="group" aria-label={fieldLabel || label}>
                {showLabel && (
                    <div className="flex items-center justify-between mb-1">
                        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider flex items-center gap-1.5">
                            {Icon && <Icon size={12} />} {label}
                        </p>
                        {onToggleLock && (
                            <button
                                type="button"
                                onClick={(e) => { e.stopPropagation(); onToggleLock(); }}
                                className={clsx(
                                    "p-0.5 rounded transition-colors text-2xs flex items-center gap-1",
                                    locked ? "text-amber-400 bg-amber-500/15" : "text-gray-500 hover:text-gray-300"
                                )}
                                title={locked ? "Locked: Protected from AI & Laya overwrites" : "Unlocked: Can be updated by Director/Statekeeper"}
                            >
                                {locked ? <Lock size={11} className="text-amber-400" /> : <Unlock size={11} />}
                                {locked && <span className="text-2xs font-mono font-bold text-amber-400">LOCK</span>}
                            </button>
                        )}
                    </div>
                )}
                {body}
            </div>
        );
    }

    return (
        <div className="glass-panel p-4 rounded-xl border border-white/5">
            <div className="flex items-center justify-between mb-3">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                    {Icon && <Icon size={12} />} {label}
                </h4>
                {onToggleLock && (
                    <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); onToggleLock(); }}
                        className={clsx(
                            "p-1 rounded transition-colors text-2xs flex items-center gap-1",
                            locked ? "text-amber-400 bg-amber-500/15" : "text-gray-500 hover:text-gray-300"
                        )}
                        title={locked ? "Locked: Protected from AI & Laya overwrites" : "Unlocked: Can be updated by Director/Statekeeper"}
                    >
                        {locked ? <Lock size={12} className="text-amber-400" /> : <Unlock size={12} />}
                        {locked && <span className="text-2xs font-mono font-bold text-amber-400">LOCK</span>}
                    </button>
                )}
            </div>
            {body}
        </div>
    );
}

export default ContextField;
