import { useEffect, useState, useRef } from 'react';
import { Terminal, Loader2 } from 'lucide-react';
import { useWebSocket } from '../../../api/websocket';

export default function LiveConsoleTab({ providerId }) {
    const topic = `provider.logs.${providerId}`;
    const { isConnected, subscribe } = useWebSocket([topic]);
    const [logs, setLogs] = useState([]);
    const logsEndRef = useRef(null);

    useEffect(() => {
        // Assume backend emits 'provider.log' events to this room.
        const unsub = subscribe('provider.log', (data) => {
            if (data.provider_id === providerId) {
                setLogs((prev) => {
                    const newLogs = [...prev, data.message];
                    if (newLogs.length > 500) return newLogs.slice(-500); // Keep last 500 lines
                    return newLogs;
                });
            }
        });
        return () => unsub();
    }, [providerId, subscribe]);

    useEffect(() => {
        // Auto-scroll to bottom
        if (logsEndRef.current) {
            logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [logs]);

    return (
        <div className="rounded-xl border border-gray-800 bg-gray-950/70 p-4 h-[400px] flex flex-col">
            <div className="mb-2 flex items-center justify-between gap-3 shrink-0">
                <span className="font-medium text-sm text-white flex items-center gap-2">
                    <Terminal size={14} />
                    Live Console
                </span>
                <span className="text-xs text-gray-500 flex items-center gap-1.5">
                    {isConnected ? (
                        <><span className="w-2 h-2 rounded-full bg-green-500"></span> Connected</>
                    ) : (
                        <><Loader2 size={12} className="animate-spin" /> Connecting...</>
                    )}
                </span>
            </div>
            <div className="flex-1 overflow-y-auto font-mono text-[11px] leading-relaxed text-gray-300 whitespace-pre-wrap break-words rounded bg-black/40 p-3 ring-1 ring-inset ring-white/5 scrollbar-thin">
                {logs.length === 0 ? (
                    <span className="text-gray-600 italic">Waiting for logs...</span>
                ) : (
                    logs.map((log, i) => <div key={i}>{log}</div>)
                )}
                <div ref={logsEndRef} />
            </div>
        </div>
    );
}
