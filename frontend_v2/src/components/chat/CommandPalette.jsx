import { useEffect, useState } from 'react';
import { COMMANDS } from './chatCommands';

function CommandPalette({ message, activeCommand, onSelect }) {
    const matches = COMMANDS.filter(c => !activeCommand && c.cmd.startsWith(message.split(' ')[0].toLowerCase()));
    const [highlighted, setHighlighted] = useState(0);

    useEffect(() => {
        if (!matches.length) return undefined;
        const onKeyDown = (e) => {
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault();
                e.stopPropagation();
                setHighlighted((h) => {
                    const delta = e.key === 'ArrowDown' ? 1 : -1;
                    return (h + delta + matches.length) % matches.length;
                });
            } else if (e.key === 'Enter' || e.key === 'Tab') {
                const match = matches[highlighted];
                if (match) {
                    e.preventDefault();
                    e.stopPropagation();
                    onSelect(match);
                }
            }
        };
        window.addEventListener('keydown', onKeyDown, { capture: true });
        return () => window.removeEventListener('keydown', onKeyDown, { capture: true });
    }, [matches, highlighted, onSelect, message]);

    if (!message.startsWith('/')) return null;
    return (
        <div className="absolute bottom-full left-0 mb-2 w-full max-w-sm bg-gray-900/95 backdrop-blur-xl border border-gray-700/60 rounded-2xl shadow-2xl overflow-hidden z-50 animate-in fade-in slide-in-from-bottom-2">
            <div className="px-3 py-2 text-xs font-semibold text-gray-400 bg-gray-800/40 uppercase tracking-wider border-b border-gray-700/50">Commands</div>
            <div className="flex flex-col max-h-60 overflow-y-auto p-1">
                {matches.map((c, i) => (
                    <button
                        key={c.cmd}
                        onClick={() => onSelect(c)}
                        onMouseEnter={() => setHighlighted(i)}
                        className={`flex items-center gap-3 px-3 py-2.5 rounded-xl transition-colors text-left group ${i === highlighted ? 'bg-white/10' : 'hover:bg-white/5'}`}
                    >
                        <span className="text-lg opacity-80 group-hover:opacity-100 transition-opacity">{c.icon}</span>
                        <div className="flex flex-col">
                            <span className="text-sm font-medium text-gray-200">{c.cmd}</span>
                            <span className="text-xs text-gray-400">{c.desc}</span>
                        </div>
                    </button>
                ))}
            </div>
        </div>
    );
}

export default CommandPalette;
