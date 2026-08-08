import React, { useState } from 'react';
import { X, ChevronLeft, ChevronRight, Images } from 'lucide-react';
import clsx from 'clsx';

function buildUrl(filename) {
    if (!filename) return '';
    if (filename.startsWith('/')) return filename;
    return `/api/view/output/${filename}`;
}

function buildThumbUrl(filename) {
    if (!filename) return '';
    if (filename.startsWith('/')) return filename;
    return `/api/thumbnail/medium/${filename}`;
}

export default function SceneGallery({ title, images, compact, lightboxAction }) {
    const [selectedIdx, setSelectedIdx] = useState(null);

    if (!images || images.length === 0) {
        return (
            <div className="text-[10px] text-gray-500 text-center py-3 border border-dashed border-gray-700/50 rounded-lg">
                No scenes generated yet
            </div>
        );
    }

    const open = (idx) => setSelectedIdx(idx);

    return (
        <div>
            <div className={clsx('grid gap-1', compact ? 'grid-cols-3' : 'grid-cols-4')}>
                {images.map((filename, idx) => (
                    <button
                        key={filename}
                        onClick={() => open(idx)}
                        className="aspect-square rounded bg-gray-800/50 border border-white/5 overflow-hidden hover:border-blue-500/40 transition-colors group relative"
                        title={filename}
                    >
                        <img
                            src={buildThumbUrl(filename)}
                            alt=""
                            className="w-full h-full object-cover"
                            loading="lazy"
                            onError={(e) => { e.target.style.display = 'none'; }}
                        />
                        <span className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors" />
                    </button>
                ))}
            </div>

            {selectedIdx !== null && (
                <div className="fixed inset-0 z-[90] bg-black/85 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setSelectedIdx(null)}>
                    <div className="flex items-center justify-between w-full absolute top-0 left-0 right-0 px-4 py-3">
                        <span className="text-xs text-gray-400">{title || 'Scenes'}</span>
                        <div className="flex items-center gap-2">
                            {lightboxAction && (
                                <span onClick={(e) => e.stopPropagation()}>
                                    {lightboxAction(images[selectedIdx], selectedIdx)}
                                </span>
                            )}
                            <button className="p-2 text-gray-300 hover:text-white rounded-xl hover:bg-white/10 transition-colors" onClick={() => setSelectedIdx(null)}>
                                <X size={18} />
                            </button>
                        </div>
                    </div>
                    <button
                        className="p-2.5 text-gray-300 hover:text-white rounded-xl hover:bg-white/10 transition-colors mr-2"
                        onClick={(e) => { e.stopPropagation(); setSelectedIdx((selectedIdx - 1 + images.length) % images.length); }}
                    >
                        <ChevronLeft size={22} />
                    </button>
                    <div className="max-h-full max-w-full" onClick={(e) => e.stopPropagation()}>
                        <img
                            src={buildUrl(images[selectedIdx])}
                            alt=""
                            className="max-h-[85vh] max-w-full rounded-xl shadow-2xl object-contain"
                        />
                        <p className="text-[10px] text-gray-500 text-center mt-2 truncate">{images[selectedIdx]}</p>
                    </div>
                    <button
                        className="p-2.5 text-gray-300 hover:text-white rounded-xl hover:bg-white/10 transition-colors ml-2"
                        onClick={(e) => { e.stopPropagation(); setSelectedIdx((selectedIdx + 1) % images.length); }}
                    >
                        <ChevronRight size={22} />
                    </button>
                </div>
            )}
        </div>
    );
}

export function SceneCount({ count }) {
    if (!count) return null;
    return (
        <div className="flex items-center gap-1.5 mb-1.5">
            <Images size={12} className="text-gray-500" />
            <span className="text-[11px] text-gray-500">{count} scene{count !== 1 ? 's' : ''}</span>
        </div>
    );
}
