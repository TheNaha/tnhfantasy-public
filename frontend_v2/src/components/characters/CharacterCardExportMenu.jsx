import { useEffect, useRef, useState } from 'react';
import { Download, FileJson, FileImage, Layers } from 'lucide-react';
import { CARD_EXPORT_FORMATS, DEFAULT_CARD_EXPORT_FORMAT } from '../../api/characterCards';

const FORMAT_ICONS = {
    v2: FileImage,
    v3: Layers,
    json: FileJson,
};

/**
 * Export format picker for a character card.
 *
 * The default entry reproduces the previous one-click export
 * (`/export` with no `format` query, `<name>_v2.png`); the other entries
 * request an explicit spec so the backend can target V2, V3 or JSON.
 */
export default function CharacterCardExportMenu({ character, onExport, disabled = false, label = 'Export' }) {
    const [open, setOpen] = useState(false);
    const containerRef = useRef(null);

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
        onExport?.(character, format);
    };

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
                    className="absolute right-0 z-40 mt-1 w-64 rounded-xl border border-white/10 bg-gray-900 p-1 shadow-2xl"
                >
                    {CARD_EXPORT_FORMATS.map((format) => {
                        const Icon = FORMAT_ICONS[format.id] || FileImage;
                        const isDefault = format.id === DEFAULT_CARD_EXPORT_FORMAT;
                        return (
                            <button
                                key={format.id}
                                type="button"
                                role="menuitem"
                                onClick={() => select(format.id)}
                                className="flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left hover:bg-white/5 transition-colors"
                            >
                                <Icon size={14} className="mt-0.5 shrink-0 text-gray-400" aria-hidden="true" />
                                <span className="min-w-0">
                                    <span className="block text-xs font-medium text-gray-200">
                                        {format.label}
                                        {isDefault && <span className="ml-1.5 text-[10px] text-gray-500">default</span>}
                                    </span>
                                    <span className="block text-[11px] leading-4 text-gray-500">
                                        {format.description}
                                    </span>
                                </span>
                            </button>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
