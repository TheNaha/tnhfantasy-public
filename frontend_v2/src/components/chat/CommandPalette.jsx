import { COMMANDS } from './chatCommands';

function CommandPalette({ message, activeCommand, onSelect }) {
    if (!message.startsWith('/')) return null;
    return (
        <div className="absolute bottom-full left-0 mb-2 w-full max-w-sm bg-gray-900/95 backdrop-blur-xl border border-gray-700/60 rounded-2xl shadow-2xl overflow-hidden z-50 animate-in fade-in slide-in-from-bottom-2">
            <div className="px-3 py-2 text-xs font-semibold text-gray-400 bg-gray-800/40 uppercase tracking-wider border-b border-gray-700/50">Commands</div>
            <div className="flex flex-col max-h-60 overflow-y-auto p-1">
                {COMMANDS.filter(c => !activeCommand && c.cmd.startsWith(message.split(' ')[0].toLowerCase())).map((c) => (
                    <button
                        key={c.cmd}
                        onClick={() => onSelect(c)}
                        className="flex items-center gap-3 px-3 py-2.5 hover:bg-white/5 rounded-xl transition-colors text-left group"
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
