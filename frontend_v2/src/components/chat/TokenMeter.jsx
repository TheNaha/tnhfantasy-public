import React, { useEffect, useRef, useState } from 'react';
import { api } from '../../api/client';

/**
 * Live composer token estimate (debounced tiktoken call).
 * Renders nothing while the composer is empty.
 */
export default function TokenMeter({ text }) {
    const [tokens, setTokens] = useState(null);
    // Guards against a stale response overwriting a newer one, and against a
    // setState after unmount. The estimate is a POST that is fired on every
    // composer change with no cancellation, so typing quickly produced a queue of
    // in-flight requests that could resolve out of order — an older, larger
    // estimate landing last and the readout going backwards.
    const requestIdRef = useRef(0);

    useEffect(() => {
        const requestId = ++requestIdRef.current;
        const t = setTimeout(async () => {
            if (!text || !text.trim()) {
                setTokens(null);
                return;
            }
            try {
                const res = await api.post('/api/v2/world-vault/estimate-tokens', { text });
                // A newer keystroke has already been requested: this answer is
                // for text the user has moved on from.
                if (requestId !== requestIdRef.current) return;
                setTokens(res.tokens);
            } catch {
                // Meter is informational; stay silent on failure.
            }
        }, 500);
        return () => {
            clearTimeout(t);
            // Invalidate any in-flight request so it cannot setState after this
            // component's teardown, or after a newer request supersedes it.
            requestIdRef.current += 1;
        };
    }, [text]);

    if (tokens == null) return null;
    return (
        <span
            className="text-2xs text-gray-600 font-mono tabular-nums mr-1 select-none"
            title="Estimated tokens in the composer"
        >
            ~{tokens} tok
        </span>
    );
}
