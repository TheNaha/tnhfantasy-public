import { useState } from 'react';

function ContextSlider({ activeChat, onChange }) {
    const serverVal = activeChat?.max_context_tokens || 4096;
    const [localVal, setLocalVal] = useState(serverVal);
    const [prevServerVal, setPrevServerVal] = useState(serverVal);

    // Sync when the server value changes (e.g. different chat selected) without useEffect
    if (serverVal !== prevServerVal) {
        setPrevServerVal(serverVal);
        setLocalVal(serverVal);
    }
    
    return (
        <input
            type="range"
            min="2048"
            max="131072"
            step="2048"
            value={localVal}
            onChange={(e) => setLocalVal(parseInt(e.target.value))}
            onMouseUp={() => onChange(localVal)}
            onTouchEnd={() => onChange(localVal)}
            onKeyUp={(e) => { if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') onChange(localVal); }}
            className="w-full accent-blue-500 min-h-[24px]"
            title="Max tokens sent to the LLM. Higher = remembers more but costs more."
        />
    );
}

export default ContextSlider;
