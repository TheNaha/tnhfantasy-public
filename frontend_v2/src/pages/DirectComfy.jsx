import { useState } from 'react';
import { Loader2, ExternalLink, Play } from 'lucide-react';
import { api } from '../api';

export default function DirectComfy() {
    const [url, setUrl] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const startSession = async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await api.post('/api/session');

            if (data.url) {
                setUrl(data.url);
            } else {
                throw new Error("No URL returned from backend");
            }
        } catch (e) {
            console.error(e);
            setError("Failed to start session. Make sure the backend is running and deployed.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="h-[calc(100vh-4rem)] flex flex-col">
            {!url ? (
                <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
                    <div className="max-w-md space-y-6">
                        <h1 className="text-3xl font-bold">Direct ComfyUI Access</h1>
                        <p className="text-gray-400">
                            Start a temporary session to access the raw ComfyUI interface.
                            This allows you to build custom workflows visually.
                        </p>

                        {error && (
                            <div className="p-4 bg-red-900/20 border border-red-800/50 rounded-lg text-red-200 text-sm">
                                {error}
                            </div>
                        )}

                        <button
                            onClick={startSession}
                            disabled={loading}
                            className="px-8 py-4 bg-blue-600 hover:bg-blue-500 rounded-xl font-bold text-white shadow-lg shadow-blue-900/20 transition-all transform hover:scale-[1.05] disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 mx-auto"
                        >
                            {loading ? (
                                <>
                                    <Loader2 className="animate-spin" size={24} />
                                    Starting Session...
                                </>
                            ) : (
                                <>
                                    <Play size={24} />
                                    Start Session
                                </>
                            )}
                        </button>

                        <p className="text-xs text-gray-500">
                            Note: Sessions are ephemeral. Workflows saved to the browser storage might be lost if you switch browsers.
                            Use "Save" in ComfyUI to download .json files.
                        </p>
                    </div>
                </div>
            ) : (
                <div className="flex-1 flex flex-col">
                    <div className="bg-gray-800 border-b border-gray-700 p-2 flex justify-between items-center px-4">
                        <span className="text-sm text-gray-400 flex items-center gap-2">
                            <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
                            Session Active
                        </span>
                        <a
                            href={url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-sm text-blue-400 hover:text-blue-300 flex items-center gap-1"
                        >
                            Open in New Tab <ExternalLink size={14} />
                        </a>
                    </div>
                    <iframe
                        src={url}
                        className="flex-1 w-full border-none bg-[#242424]"
                        title="ComfyUI Interface"
                    />
                </div>
            )}
        </div>
    );
}
