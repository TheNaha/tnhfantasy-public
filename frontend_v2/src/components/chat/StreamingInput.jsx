import { X } from 'lucide-react';

function StreamingInput({
    textareaRef,
    value,
    onChange,
    onKeyDown,
    placeholder,
    disabled,
    activeCommand,
    onClearCommand,
}) {
    return (
        <div className="flex items-center w-full bg-gray-900/80 border border-gray-700/50 rounded-2xl pl-10 sm:pl-12 pr-24 sm:pr-44 py-3.5 sm:py-4 transition-all shadow-inner focus-within:border-blue-500/50 focus-within:ring-1 focus-within:ring-blue-500/30">
            {activeCommand && (
                <div className="flex items-center gap-1.5 px-2 py-1 bg-blue-500/20 text-blue-300 rounded-lg text-sm font-medium mr-2 whitespace-nowrap select-none ml-2">
                    <span>{activeCommand.icon}</span>
                    {activeCommand.cmd}
                    <button onClick={onClearCommand} className="hover:text-white ml-1 opacity-60 hover:opacity-100 transition-opacity"><X size={14} /></button>
                </div>
            )}

            <textarea
                ref={textareaRef}
                value={value}
                onChange={onChange}
                onKeyDown={onKeyDown}
                placeholder={placeholder}
                className="flex-1 bg-transparent text-gray-200 placeholder-gray-500 focus:outline-none resize-none text-sm self-center min-h-[24px] max-h-[200px]"
                rows={1}
                disabled={disabled}
            />
        </div>
    );
}

export default StreamingInput;
