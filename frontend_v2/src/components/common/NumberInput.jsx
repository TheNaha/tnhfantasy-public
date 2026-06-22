import { memo, useId } from 'react';

export const NumberInput = memo(({ label, value, onChange, min, max, step = 1, className = "" }) => {
    const inputId = useId();

    const handleChange = (e) => {
        const val = parseFloat(e.target.value);
        if (isNaN(val)) {
            // allow intermediate typing
            onChange(e.target.value);
            return;
        }
        onChange(val);
    };

    const handleBlur = () => {
        // Only clamp the minimum, allow exceeding max
        if (typeof value === 'string' && value === "") {
             onChange(min);
        } else {
             const val = Math.max(min, Number(value));
             onChange(Number(val.toFixed(2)));
        }
    };

    const handleSliderChange = (e) => {
        onChange(Number(e.target.value));
    };

    return (
        <div className={`space-y-1 ${className}`}>
            {label && (
                <div className="flex justify-between items-center mb-1">
                    <label htmlFor={inputId} className="text-[11px] font-bold text-gray-400 uppercase tracking-widest px-1">{label}</label>
                    <input
                        id={inputId}
                        type="number"
                        value={value}
                        onChange={handleChange}
                        onBlur={handleBlur}
                        step={step}
                        className="w-16 bg-[#0B0E14] border border-white/10 rounded-lg px-1.5 py-1 text-center text-white text-sm focus:ring-2 focus:ring-blue-500/50 outline-none appearance-none transition-all shadow-inner"
                    />
                </div>
            )}
            <input
                type="range"
                min={min}
                max={max}
                step={step}
                value={Math.min(Math.max(Number(value) || min, min !== undefined ? min : 0), max !== undefined ? max : 100)}
                onChange={handleSliderChange}
                aria-label={label ? `${label} slider` : 'Range slider'}
                className="w-full h-1.5 bg-gray-800 rounded-lg appearance-none cursor-pointer accent-blue-500"
            />
        </div>
    );
});

export default NumberInput;
