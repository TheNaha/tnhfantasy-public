import React, { useEffect, useState } from 'react';
import { api } from '../../api/client';

/**
 * Live composer token estimate (debounced tiktoken call).
 * Renders nothing while the composer is empty.
 */
export default function TokenMeter({ text }) {
    const [tokens, setTokens] = useState(null);

    useEffect(() => {
        const t = setTimeout(async () => {
            if (!text || !text.trim()) {
                setTokens(null);
                return;
            }
            try {
                const res = await api.post('/api/v2/world-vault/estimate-tokens', { text });
                setTokens(res.tokens);
            } catch {
                // Meter is informational; stay silent on failure.
            }
        }, 500);
        return () => clearTimeout(t);
    }, [text]);

    if (tokens == null) return null;
    return (
        <span
            className="text-[9px] text-gray-600 font-mono tabular-nums mr-1 select-none"
            title="Estimated tokens in the composer"
        >
            ~{tokens} tok
        </span>
    );
}
