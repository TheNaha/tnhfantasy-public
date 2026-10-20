import { useEffect, useRef, useState } from 'react';
import { Download, FileJson, FileImage, Layers, Package } from 'lucide-react';
import { CARD_EXPORT_FORMATS, DEFAULT_CARD_EXPORT_FORMAT } from '../../api/characterCards';
import { useCharacterExportPreview } from '../../hooks/useCharacters';

const FORMAT_ICONS = {
    v2: FileImage,
    v3: Layers,
    json: FileJson,
    bundle: Package,
};

/** The optional sections a bundle can carry, and what each one is. */
const BUNDLE_SECTIONS = [
    { id: 'expressions', label: 'Expressions', hint: 'the emotion image set' },
    { id: 'voice', label: 'Voice', hint: 'the voice model binding' },
    { id: 'generation', label: 'Generation', hint: 'checkpoint and LoRA' },
    { id: 'world', label: 'World', hint: 'the world and its locations' },
    { id: 'lorebooks', label: 'Lorebooks', hint: 'the vault library' },
    { id: 'chat', label: 'Chat history', hint: 'the conversations' },
];

/**
 * Export format picker for a character card.
 *
 * The default entry reproduces the previous one-click export
 * (`/export` with no `format` query, `<name>_v2.png`); the other entries
 * request an explicit spec so the backend can target V2, V3, JSON, CHARX or
 * the native bundle.
 *
 * The bundle entry is FIRST for a TNHComyu character and the SillyTavern
 * formats follow, because a card can only express a fraction of what a
 * character here carries. The checklist says which parts, so the choice is
 * informed rather than a guess.
 */
export default function CharacterCardExportMenu({ character, onExport, disabled = false, label = 'Export' }) {
    const [open, setOpen] = useState(false);
    const [include, setInclude] = useState(['expressions', 'world', 'lorebooks', 'chat']);
    const containerRef = useRef(null);
    const { data: preview } = useCharacterExportPreview(character?.id, { enabled: open });

    useEffect(() => {
        if (!open) return undefined;

        const onPointerDown = (event) => {
            if (containerRef.current && !containerRef.current.contains(event.target)) {
                setOpen(false);
            }
        };
        const onKeyDown = (event) => {
            if (event.key === 'Escape') setOpen(false);
        };

        document.addEventListener('mousedown', onPointerDown);
        document.addEventListener('keydown', onKeyDown);
        return () => {
            document.removeEventListener('mousedown', onPointerDown);
            document.removeEventListener('keydown', onKeyDown);
        };
    }, [open]);

    const select = (format) => {
        setOpen(false);
        if (format === 'bundle') {
            onExport?.(character, format, include);
        } else {
            onExport?.(character, format);
        }
    };

    const notPortable = preview?.not_portable || [];

    return (
        <div className="relative" ref={containerRef}>
            <button
                type="button"
                disabled={disabled}
                onClick={() => setOpen((v) => !v)}
                aria-haspopup="menu"
                aria-expanded={open}
                aria-label={`${label} card for ${character?.name || 'character'}`}
                title={`${label} SillyTavern card`}
                className="flex items-center px-2 py-1.5 text-xs bg-white/5 text-gray-400 rounded-lg hover:bg-white/10 hover:text-white transition-colors disabled:opacity-50"
            >
                <Download size={14} />
            </button>

            {open && (
                <div
                    role="menu"
                    aria-label="Card export format"
                    data-testid="card-export-menu"
                    className="absolute right-0 z-40 mt-1 w-72 rounded-xl border border-white/10 bg-gray-900 p-1 shadow-2xl"
                >
                    {CARD_EXPORT_FORMATS.map((format) => {
                        const Icon = FORMAT_ICONS[format.id] || FileImage;
                        const isDefault = format.id === DEFAULT_CARD_EXPORT_FORMAT;
                        const isBundle = format.id === 'bundle';
                        return (
                            <div key={format.id} className="mb-1 last:mb-0">
                                <button
                                    type="button"
                                    role="menuitem"
                                    onClick={() => select(format.id)}
                                    className="flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left hover:bg-white/5 transition-colors"
                                >
                                    <Icon size={14} className="mt-0.5 shrink-0 text-gray-400" aria-hidden="true" />
                                    <span className="min-w-0">
                                        <span className="block text-xs font-medium text-gray-200">
                                            {format.label}
                                            {isDefault && <span className="ml-1.5 text-xs text-gray-500">default</span>}
                                        </span>
                                        <span className="block text-2xs leading-4 text-gray-500">
                                            {format.description}
                                        </span>
                                    </span>
                                </button>
                                {isBundle && (
                                    <div className="px-2.5 pb-2 pt-1">
                                        <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-gray-500">
                                            Include
                                        </p>
                                        <div className="flex flex-wrap gap-1">
                                            {BUNDLE_SECTIONS.map((section) => {
                                                const checked = include.includes(section.id);
                                                return (
                                                    <button
                                                        key={section.id}
                                                        type="button"
                                                        onClick={() =>
                                                            setInclude((prev) =>
                                                                prev.includes(section.id)
                                                                    ? prev.filter((s) => s !== section.id)
                                                                    : [...prev, section.id]
                                                            )
                                                        }
                                                        title={section.hint}
                                                        className={`rounded-md border px-1.5 py-0.5 text-2xs transition-colors ${
                                                            checked
                                                                ? 'border-fuchsia-500/40 bg-fuchsia-500/10 text-fuchsia-200'
                                                                : 'border-white/10 bg-white/5 text-gray-500 hover:text-gray-300'
                                                        }`}
                                                    >
                                                        {section.label}
                                                    </button>
                                                );
                                            })}
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}

                    {notPortable.length > 0 && (
                        <div
                            className="mx-1 mt-1 rounded-lg border border-amber-500/25 bg-amber-500/5 p-2"
                            data-testid="card-export-not-portable"
                        >
                            <p className="text-2xs font-semibold uppercase tracking-wider text-amber-300/80">
                                A card cannot carry
                            </p>
                            <ul className="mt-1 space-y-0.5">
                                {notPortable.map((feature) => (
                                    <li key={feature.name} className="text-2xs leading-4 text-amber-200/70">
                                        <span className="font-medium text-amber-200/90">{feature.name}</span>
                                        {feature.detail ? ` — ${feature.detail}` : ''}
                                    </li>
                                ))}
                            </ul>
                            <p className="mt-1.5 text-2xs leading-4 text-gray-500">
                                The TNHComfy bundle carries these.
                            </p>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
