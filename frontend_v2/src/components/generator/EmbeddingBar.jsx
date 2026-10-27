import { useState, useRef, useEffect, memo } from 'react';
import { Sparkles, Ban, SlidersHorizontal, Plus, X, Search, ExternalLink } from 'lucide-react';
import { Link } from 'react-router-dom';
import toast from 'react-hot-toast';
import {
    isNegativeEmbedding,
    parseActiveEmbeddings,
    toggleEmbeddingInPrompt,
    removeEmbeddingFromPrompt,
    setEmbeddingWeightInPrompt,
} from '../../utils/embeddingHelpers';

const WEIGHT_PRESETS = [0.8, 0.9, 1.0, 1.1, 1.2];

export const EmbeddingBar = memo(function EmbeddingBar({
    promptText = '',
    onChange,
    isNegative = false,
    embeddings = [],
}) {
    const [isMenuOpen, setIsMenuOpen] = useState(false);
    const [activeWeightPopup, setActiveWeightPopup] = useState(null); // embedding name
    const [searchQuery, setSearchQuery] = useState('');
    const menuRef = useRef(null);
    const popupRef = useRef(null);

    // Filter relevant embeddings based on heuristic
    const relevantEmbeddings = embeddings.filter((emb) => {
        const isNeg = isNegativeEmbedding(emb.name);
        return isNegative ? isNeg : !isNeg;
    });

    const activeList = parseActiveEmbeddings(promptText).filter((active) => {
        // Only show embeddings in this bar if they match or are already present
        const isNeg = isNegativeEmbedding(active.name);
        return isNegative ? isNeg : !isNeg;
    });

    // Close popups on click outside
    useEffect(() => {
        function handleClickOutside(event) {
            if (menuRef.current && !menuRef.current.contains(event.target)) {
                setIsMenuOpen(false);
            }
            if (popupRef.current && !popupRef.current.contains(event.target)) {
                setActiveWeightPopup(null);
            }
        }
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const handleToggle = (name) => {
        const next = toggleEmbeddingInPrompt(promptText, name);
        onChange(next);
        const added = next.includes(`embedding:${name}`);
        toast(added ? `Added embedding:${name}` : `Removed embedding:${name}`, {
            icon: isNegative ? '🚫' : '✨',
            duration: 1500,
        });
    };

    const handleRemove = (name) => {
        const next = removeEmbeddingFromPrompt(promptText, name);
        onChange(next);
        setActiveWeightPopup(null);
    };

    const handleWeightChange = (name, weight) => {
        const next = setEmbeddingWeightInPrompt(promptText, name, weight);
        onChange(next);
    };

    const filteredCatalog = embeddings.filter((emb) =>
        emb.name.toLowerCase().includes(searchQuery.toLowerCase())
    );

    return (
        <div className="flex flex-wrap items-center gap-1.5 pt-1 text-xs">
            <span className="flex items-center gap-1 font-semibold text-2xs uppercase tracking-wider text-gray-400">
                {isNegative ? (
                    <Ban size={12} className="text-pink-400" />
                ) : (
                    <Sparkles size={12} className="text-blue-400" />
                )}
                <span>Embeddings:</span>
            </span>

            {/* Active Embeddings with Weight Pills */}
            {activeList.map((active) => {
                const isPopupOpen = activeWeightPopup === active.name;

                return (
                    <div key={active.name} className="relative inline-flex items-center">
                        <div
                            className={`group inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border text-2xs font-medium transition-all shadow-sm ${
                                isNegative
                                    ? 'bg-pink-950/40 border-pink-700/60 text-pink-200 ring-1 ring-pink-500/20'
                                    : 'bg-blue-950/40 border-blue-700/60 text-blue-200 ring-1 ring-blue-500/20'
                            }`}
                        >
                            <span className="font-mono">{active.name}</span>

                            <button
                                type="button"
                                onClick={() => setActiveWeightPopup(isPopupOpen ? null : active.name)}
                                className={`px-1 rounded flex items-center gap-0.5 hover:bg-white/10 transition-colors ${
                                    active.weight !== 1.0 ? 'font-bold underline' : 'opacity-70'
                                }`}
                                title="Adjust embedding weight"
                            >
                                <SlidersHorizontal size={10} />
                                <span>{active.weight.toFixed(1)}</span>
                            </button>

                            <button
                                type="button"
                                onClick={() => handleRemove(active.name)}
                                className="text-gray-400 hover:text-red-400 transition-colors ml-0.5"
                                title={`Remove ${active.name}`}
                                aria-label={`Remove ${active.name}`}
                            >
                                <X size={11} />
                            </button>
                        </div>

                        {/* Weight Slider Popover */}
                        {isPopupOpen && (
                            <div
                                ref={popupRef}
                                className="absolute top-full mt-1.5 left-0 z-50 p-2.5 bg-gray-900/95 backdrop-blur-md border border-white/15 rounded-xl shadow-2xl min-w-[180px] space-y-2 animate-in fade-in zoom-in-95 duration-100"
                            >
                                <div className="flex justify-between items-center text-2xs text-gray-300">
                                    <span className="font-semibold">Weight:</span>
                                    <span className="font-mono text-blue-400">{active.weight.toFixed(2)}</span>
                                </div>

                                <input
                                    type="range"
                                    min="0.4"
                                    max="1.8"
                                    step="0.05"
                                    value={active.weight}
                                    onChange={(e) => handleWeightChange(active.name, parseFloat(e.target.value))}
                                    className="w-full accent-blue-500 cursor-pointer h-1.5 bg-gray-700 rounded-lg"
                                />

                                <div className="flex justify-between gap-1 pt-1">
                                    {WEIGHT_PRESETS.map((preset) => (
                                        <button
                                            key={preset}
                                            type="button"
                                            onClick={() => handleWeightChange(active.name, preset)}
                                            className={`px-1.5 py-0.5 text-2xs rounded border transition-colors ${
                                                active.weight === preset
                                                    ? 'bg-blue-600 border-blue-500 text-white font-bold'
                                                    : 'bg-black/30 border-white/10 text-gray-300 hover:bg-white/10'
                                            }`}
                                        >
                                            {preset}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                );
            })}

            {/* Quick-Suggestion Pills for Inactive Relevant Embeddings */}
            {relevantEmbeddings
                .filter((emb) => !activeList.some((act) => act.name === emb.name || act.name === emb.name.replace(/\.[^/.]+$/, '')))
                .slice(0, 4)
                .map((emb) => (
                    <button
                        key={emb.name}
                        type="button"
                        onClick={() => handleToggle(emb.name)}
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-2xs transition-all ${
                            isNegative
                                ? 'bg-pink-900/10 border-pink-900/30 text-pink-400/80 hover:bg-pink-900/30 hover:text-pink-200 hover:border-pink-700'
                                : 'bg-blue-900/10 border-blue-900/30 text-blue-400/80 hover:bg-blue-900/30 hover:text-blue-200 hover:border-blue-700'
                        }`}
                        title={`Click to add ${emb.name}`}
                    >
                        <Plus size={10} />
                        <span>{emb.name.replace(/\.[^/.]+$/, '')}</span>
                    </button>
                ))}

            {/* "+ Add" Dropdown for Browsing All Embeddings */}
            <div className="relative inline-flex items-center" ref={menuRef}>
                <button
                    type="button"
                    onClick={() => setIsMenuOpen(!isMenuOpen)}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md border border-white/10 bg-white/5 hover:bg-white/10 text-gray-300 text-2xs transition-all"
                    title="Browse or add all embeddings"
                >
                    <Plus size={10} />
                    <span>More</span>
                </button>

                {isMenuOpen && (
                    <div className="absolute top-full mt-1.5 left-0 z-50 w-64 p-2 bg-gray-900/95 backdrop-blur-md border border-white/15 rounded-xl shadow-2xl space-y-2 animate-in fade-in zoom-in-95 duration-100">
                        <div className="relative">
                            <Search size={12} className="absolute left-2.5 top-2.5 text-gray-400" />
                            <input
                                type="text"
                                value={searchQuery}
                                onChange={(e) => setSearchQuery(e.target.value)}
                                placeholder="Search embeddings..."
                                className="w-full bg-black/40 border border-white/10 rounded-lg pl-7 pr-2.5 py-1 text-xs text-white placeholder-gray-500 outline-none focus:border-blue-500"
                                autoFocus
                            />
                        </div>

                        <div className="max-h-48 overflow-y-auto space-y-1 pr-1 custom-scrollbar">
                            {filteredCatalog.length === 0 ? (
                                <div className="text-center py-4 space-y-2">
                                    <p className="text-2xs text-gray-400">No matching embeddings found.</p>
                                    <Link
                                        to="/discover"
                                        className="inline-flex items-center gap-1 text-2xs text-blue-400 hover:text-blue-300 underline"
                                    >
                                        <ExternalLink size={10} />
                                        Discover Embeddings on Civitai
                                    </Link>
                                </div>
                            ) : (
                                filteredCatalog.map((emb) => {
                                    const isAdded = activeList.some((act) => act.name === emb.name || act.name === emb.name.replace(/\.[^/.]+$/, ''));

                                    return (
                                        <button
                                            key={emb.name}
                                            type="button"
                                            onClick={() => {
                                                handleToggle(emb.name);
                                                setIsMenuOpen(false);
                                            }}
                                            className={`w-full flex items-center justify-between px-2 py-1.5 rounded-lg text-left text-xs transition-colors ${
                                                isAdded
                                                    ? 'bg-blue-600/20 text-blue-300 font-medium'
                                                    : 'hover:bg-white/5 text-gray-200'
                                            }`}
                                        >
                                            <span className="truncate">{emb.name}</span>
                                            {isAdded && <span className="text-2xs text-blue-400 font-bold">✓ Added</span>}
                                        </button>
                                    );
                                })
                            )}
                        </div>
                    </div>
                )}
            </div>

            {/* Zero Embeddings Helper CTA */}
            {embeddings.length === 0 && (
                <Link
                    to="/discover"
                    className="inline-flex items-center gap-1 text-2xs text-amber-400/90 hover:text-amber-300 underline transition-colors ml-1"
                >
                    <ExternalLink size={10} />
                    <span>Get Lazy Embeddings (Civitai)</span>
                </Link>
            )}
        </div>
    );
});

export default EmbeddingBar;
