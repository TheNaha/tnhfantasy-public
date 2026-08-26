import React from 'react';

const FIELDS = [
    { key: 'temperature', label: 'Temp', min: 0, max: 2, step: 0.05 },
    { key: 'top_p', label: 'Top P', min: 0, max: 1, step: 0.01 },
    { key: 'max_output_tokens', label: 'Max Tokens', min: 16, max: 32768, step: 16, int: true },
    { key: 'frequency_penalty', label: 'Freq Pen', min: -2, max: 2, step: 0.1 },
    { key: 'presence_penalty', label: 'Pres Pen', min: -2, max: 2, step: 0.1 },
];

/**
 * Shared per-entity LLM sampling override controls (chat + story panels).
 * Blank field = inherit the global default configured in Settings.
 */
export default function SamplingControls({ values = {}, onChange }) {
    const anySet = FIELDS.some(f => values[f.key] != null);

    return (
        <div>
            <div className="flex items-center justify-between mb-1.5">
                <p className="text-xs text-gray-300 font-medium">Sampling</p>
                <span className="text-[10px] text-gray-500 font-mono">
                    {anySet ? 'custom overrides' : 'Global defaults'}
                </span>
            </div>
            <div className="grid grid-cols-2 gap-2">
                {FIELDS.map(({ key, label, min, max, step, int }) => (
                    <label key={key} className="flex flex-col gap-1">
                        <span className="text-[9px] uppercase tracking-wider text-gray-500 font-bold">{label}</span>
                        <div className="flex items-center gap-1">
                            <input
                                type="number"
                                min={min}
                                max={max}
                                step={step}
                                placeholder="global"
                                value={values[key] ?? ''}
                                onChange={(e) => onChange({
                                    [key]: e.target.value === ''
                                        ? null
                                        : (int ? parseInt(e.target.value, 10) : parseFloat(e.target.value))
                                })}
                                className="w-full bg-gray-800 border border-gray-700 text-xs rounded px-2 py-1 text-gray-300 focus:outline-none placeholder-gray-600"
                            />
                            {values[key] != null && (
                                <button
                                    onClick={() => onChange({ [key]: null })}
                                    title="Inherit global default"
                                    className="p-0.5 text-gray-500 hover:text-red-400 transition-colors"
                                >
                                    ×
                                </button>
                            )}
                        </div>
                    </label>
                ))}
            </div>
            {anySet && (
                <button
                    onClick={() => onChange(Object.fromEntries(FIELDS.map(f => [f.key, null])))}
                    className="mt-1.5 text-[9px] text-gray-500 hover:text-red-400 transition-colors"
                >
                    Reset all to global defaults
                </button>
            )}
        </div>
    );
}
