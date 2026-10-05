import { useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { Search, Command } from 'lucide-react';
import { useEscapeKey } from '../hooks/useEscapeKey';
import { EXPERT_TOOLS } from '../constants/navigation';

// Flat, searchable destinations. The expert rows are derived from
// EXPERT_TOOLS so this list cannot drift from the sidebar again; the remaining
// rows keep their own labels because those are search aliases for pages whose
// own titles differ (e.g. "Advanced Generator" for the "Advanced" page).
// There is deliberately no `{ label: 'Home', to: '/' }` row: `/` redirects to
// `/roleplay`, so it would be a second name for the row below.
const NAV_ITEMS = [
    { label: 'Gallery', to: '/gallery' },
    { label: 'Simple Generate', to: '/generate' },
    { label: 'Img2Img', to: '/img2img' },
    { label: 'Inpaint', to: '/inpaint' },
    { label: 'Advanced Generator', to: '/advanced' },
    { label: 'Batch Generate', to: '/batch-generate' },
    { label: 'Roleplay Home', to: '/roleplay' },
    { label: 'Play', to: '/chat' },
    { label: 'Stories', to: '/story' },
    // `/worlds` used to have a hand-written row here as well as the one
    // `EXPERT_TOOLS` contributes two lines below. Rows are keyed by
    // `${kind}:${label}` (`:122`), so that was a duplicate key and a duplicate
    // entry in the palette. `commandPaletteInvariants.test.js` now fails on any
    // repeated label.
    { label: 'Search everything', to: '/world-vault' },
    ...EXPERT_TOOLS.map(({ label, to }) => ({ label, to })),
    { label: 'Prompt Library', to: '/prompts' },
    { label: 'Installed Models', to: '/models/installed' },
    { label: 'Discover Models', to: '/models/discover' },
    { label: 'Providers', to: '/providers' },
    { label: 'Statistics', to: '/statistics' },
    { label: 'Settings', to: '/settings' },
];

const QUICK_ACTIONS = [
    { label: 'New Chat', to: '/chat?new=1' },
    { label: 'New Story', to: '/story' },
];

export default function GlobalCommandPalette({ onClose }) {
    const navigate = useNavigate();
    const [query, setQuery] = useState('');
    const [highlighted, setHighlighted] = useState(0);
    const inputRef = useRef(null);

    const items = useMemo(() => {
        const q = query.trim().toLowerCase();
        const all = [
            ...QUICK_ACTIONS.map((a) => ({ ...a, kind: 'action' })),
            ...NAV_ITEMS.map((n) => ({ ...n, kind: 'nav' })),
        ];
        if (!q) return all;
        return all.filter((item) => item.label.toLowerCase().includes(q));
    }, [query]);

    useEscapeKey(onClose);

    // Navigation keys only. Escape deliberately does NOT live here: every
    // `useEscapeKey` handler is a listener on the same `window` target in the
    // bubble phase, so `stopPropagation()` cannot disarm this one — and this
    // handler used to call `preventDefault()` without `stopPropagation()`, which
    // `useEscapeKey` does check, so it kept running underneath whatever dialog
    // the palette was opened over. One Escape closed the palette *and* the
    // dialog underneath it.
    useEffect(() => {
        inputRef.current?.focus();
        const onKeyDown = (e) => {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                setHighlighted((h) => Math.min(h + 1, items.length - 1));
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setHighlighted((h) => Math.max(h - 1, 0));
            } else if (e.key === 'Enter') {
                e.preventDefault();
                const item = items[highlighted];
                if (item) {
                    navigate(item.to);
                    onClose();
                }
            }
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [items, highlighted, navigate, onClose]);

    return (
        <div
            className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[15vh] bg-black/70 backdrop-blur-sm"
            onMouseDown={(e) => {
                if (e.target === e.currentTarget) onClose();
            }}
        >
            <motion.div
                initial={{ scale: 0.96, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.96, opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="w-full max-w-lg bg-gray-900 border border-white/10 rounded-3xl shadow-2xl overflow-hidden"
            >
                <div className="flex items-center gap-3 px-5 py-4 border-b border-white/5">
                    <Search size={18} className="text-gray-500 shrink-0" />
                    <input
                        ref={inputRef}
                        value={query}
                        onChange={(e) => {
                            setQuery(e.target.value);
                            setHighlighted(0);
                        }}
                        placeholder="Jump to a page or action…"
                        className="flex-1 bg-transparent text-gray-200 placeholder-gray-500 outline-none text-sm"
                        aria-label="Command palette search"
                    />
                    <span className="flex items-center gap-1 text-xs font-bold uppercase tracking-wider text-gray-500 bg-white/5 border border-white/10 rounded-md px-1.5 py-0.5">
                        <Command size={11} />
                        K
                    </span>
                </div>
                <div className="max-h-[45vh] overflow-y-auto custom-scrollbar p-2">
                    {items.map((item, i) => (
                        <button
                            key={`${item.kind}:${item.label}`}
                            onMouseEnter={() => setHighlighted(i)}
                            onClick={() => {
                                navigate(item.to);
                                onClose();
                            }}
                            className={`w-full flex items-center justify-between px-4 py-2.5 rounded-xl text-left transition-colors ${
                                i === highlighted ? 'bg-white/10 text-white' : 'text-gray-300 hover:bg-white/5'
                            }`}
                        >
                            <span className="text-sm font-medium">{item.label}</span>
                            <span className="text-xs uppercase tracking-wider text-gray-500 font-bold">
                                {item.kind === 'action' ? 'action' : 'page'}
                            </span>
                        </button>
                    ))}
                    {items.length === 0 && (
                        <p className="px-4 py-6 text-center text-sm text-gray-500">No matches for “{query}”</p>
                    )}
                </div>
                <div className="flex items-center gap-4 px-5 py-3 border-t border-white/5 text-xs font-medium text-gray-500">
                    <span><kbd className="kbd">↑</kbd> <kbd className="kbd">↓</kbd> navigate</span>
                    <span><kbd className="kbd">Enter</kbd> open</span>
                    <span><kbd className="kbd">Esc</kbd> close</span>
                </div>
            </motion.div>
        </div>
    );
}