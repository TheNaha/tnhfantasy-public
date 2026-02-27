import React, { memo, useId } from 'react';
import { Minus, Plus } from 'lucide-react';

export const NumberInput = memo(({ label, value, onChange, min, max, step = 1, className = "" }) => {
    const inputId = useId();

    const handleDecrement = () => {
        const newValue = Math.max(min, Number((value - step).toFixed(2)));
        onChange(newValue);
    };

    const handleIncrement = () => {
        const newValue = Math.min(max, Number((value + step).toFixed(2)));
        onChange(newValue);
    };

    const handleChange = (e) => {
        const val = parseFloat(e.target.value);
        if (isNaN(val)) return;
        onChange(val);
    };

    const handleBlur = () => {
        const val = Math.max(min, Math.min(max, value));
        onChange(Number(val.toFixed(2)));
    };

    return (
        <div className={className}>
            {label && (
                <div className="flex justify-between items-center mb-1">
                    <label htmlFor={inputId} className="text-xs font-medium text-gray-500 uppercase tracking-wider">{label}</label>
                </div>
            )}
            <div className="flex items-center gap-1 h-[34px]">
                <button
                    type="button"
                    onClick={handleDecrement}
                    disabled={value <= min}
                    className="h-full px-2.5 bg-gray-800 border border-gray-700 rounded-l-lg hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-gray-400 hover:text-white flex items-center justify-center"
                    aria-label={`Decrease ${label}`}
                >
                    <Minus size={14} />
                </button>
                <div className="flex-1 h-full relative group">
                    <input
                        id={inputId}
                        type="number"
                        value={value}
                        onChange={handleChange}
                        onBlur={handleBlur}
                        min={min}
                        max={max}
                        step={step}
                        className="w-full h-full bg-gray-900 border-y border-gray-700 text-center text-white text-sm focus:ring-1 focus:ring-blue-500 outline-none appearance-none"
                    />
                    {/* Visual indicator of range progress as a subtle background bar */}
                    <div
                        className="absolute bottom-0 left-0 h-0.5 bg-blue-500/50 pointer-events-none transition-all duration-300"
                        style={{ width: `${((value - min) / (max - min)) * 100}%` }}
                    />
                </div>
                <button
                    type="button"
                    onClick={handleIncrement}
                    disabled={value >= max}
                    className="h-full px-2.5 bg-gray-800 border border-gray-700 rounded-r-lg hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-gray-400 hover:text-white flex items-center justify-center"
                    aria-label={`Increase ${label}`}
                >
                    <Plus size={14} />
                </button>
            </div>
        </div>
    );
});

export default NumberInput;
