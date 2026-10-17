import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Download, Share2, BookOpen, Play, Pause, FileDown } from 'lucide-react';
import { api } from '../api';
import { assetUrl } from '../utils/assetUrl';
import { copyToClipboard } from '../utils/clipboard';
import toast from 'react-hot-toast';
import ExportModal from '../components/story/ExportModal';

export default function StoryReader() {
    const { token } = useParams();
    const navigate = useNavigate();
    const [showExport, setShowExport] = useState(false);

    const { data: story, isLoading: loading, isError, error } = useQuery({
        queryKey: ['published_story', token],
        queryFn: () => api.get(`/api/v2/stories/published/${token}`),
        enabled: !!token,
        retry: false,
    });

    /**
     * A dead share link says so, in place.
     *
     * `GET /api/v2/stories/published/{token}` 404s for a token that was never
     * issued, and 404s for a real story whose author has since unpublished it —
     * two different mistakes for the reader, one honest thing to say. It used to
     * toast and `navigate('/')`, and `/` redirects to `/roleplay`, so somebody
     * who clicked a shared link that had gone stale was silently dropped into the
     * workspace with no message, no error and no way to tell that the page they
     * asked for had never loaded. The redirect also raced the query: it fired on
     * `isError` before anything had a chance to render a failure.
     *
     * There is no "no token at all" case left to redirect for — the route is
     * `/read/story/:token`, so `token` is always present and an absent one is
     * this same dead link.
     */

    const handleShare = async () => {
        // `await navigator.clipboard.writeText(...)` in a try/catch catches the
        // REJECTION. On a non-secure origin the failure is a synchronous
        // TypeError on the dereference, before the promise exists — measured:
        // `http://100.150.0.4:5174` → `{"secure":false,"clip":false}`. The
        // catch did run for that case, but the message was the generic
        // "Could not copy link" on a device where copying works fine via the
        // textarea fallback the other four call sites already used.
        const copied = await copyToClipboard(window.location.href);
        if (copied) {
            toast.success('Link copied!');
        } else {
            toast.error('Could not copy link');
        }
    };

    const handleExport = async (format) => {
        try {
            // Binary formats (epub, comic, webtoon) resolve to a raw Response
            // (the api client returns it for non-JSON content types).
            const binaryFormats = ['epub', 'comic', 'webtoon'];
            const exportUrl = `/api/v2/stories/published/${token}/export?format=${format}`;
            // Comic/webtoon rendering can take a while on long chapters.
            const data = await api.get(exportUrl, { timeout: 180000 });
            let blob, filename;
            if (format === 'md' || format === 'markdown') {
                const md = typeof data === 'string' ? data
                    : data instanceof Response ? await data.text()
                        : data.content;
                blob = new Blob([md], { type: 'text/markdown' });
                filename = 'story.md';
            } else if (binaryFormats.includes(format)) {
                blob = data instanceof Response ? await data.blob() : new Blob([data]);
                filename = `story.${format === 'comic' ? 'pdf' : format === 'webtoon' ? 'png' : format}`;
            } else {
                // JSON
                const json = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
                blob = new Blob([json], { type: 'application/json' });
                filename = 'story.json';
            }
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            a.click();
            URL.revokeObjectURL(url);
            toast.success(`Exported as ${format.toUpperCase()}`);
        } catch (err) {
            toast.error(`Export failed: ${err.message}`);
        }
    };

    if (loading) {
        return <div className="p-6">Loading story...</div>;
    }

    if (isError || !story) {
        return (
            <div className="max-w-2xl mx-auto px-6 py-16 text-center" role="alert">
                <BookOpen size={32} className="mx-auto mb-4 text-gray-600" aria-hidden="true" />
                <h1 className="text-xl font-semibold text-white mb-2">This story link is invalid</h1>
                <p className="text-gray-400 mb-6">
                    It never existed, or it was unpublished by its author.
                    {error?.response?.status === 404 ? '' : ' Ask whoever shared it for a new link.'}
                </p>
                <button
                    onClick={() => navigate('/')}
                    className="inline-flex items-center gap-2 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-white rounded-lg transition-colors"
                >
                    <ArrowLeft size={16} aria-hidden="true" />
                    Go to the home page
                </button>
            </div>
        );
    }

    return (
        <>
        <div className="max-w-4xl mx-auto px-6 py-8">
            <div className="flex items-center justify-between mb-8">
                <button
                    onClick={() => navigate('/')}
                    className="flex items-center gap-2 text-gray-400 hover:text-white transition-colors"
                >
                    <ArrowLeft size={18} />
                    Back to Hub
                </button>
                <div className="flex items-center gap-3">
                    <button
                        onClick={() => handleExport('md')}
                        className="p-2 text-gray-400 hover:text-white"
                        title="Export as Markdown"
                    >
                        <Download size={18} />
                    </button>
                    <button
                        onClick={() => setShowExport(true)}
                        className="p-2 text-gray-400 hover:text-white"
                        title="Export & Publish"
                    >
                        <FileDown size={18} />
                    </button>
                    <button
                        onClick={handleShare}
                        className="p-2 text-gray-400 hover:text-white"
                        title="Share link"
                    >
                        <Share2 size={18} />
                    </button>
                </div>
            </div>

            <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6 }}
            >
                <h1 className="text-4xl font-bold text-white mb-4">{story.story?.title || 'Untitled'}</h1>

                {story.story?.description && (
                    <p className="text-gray-300 text-lg mb-6">{story.story.description}</p>
                )}

                {story.story?.memory && (
                    <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 mb-6">
                        <h3 className="text-sm font-medium text-gray-400 mb-2">Author's Note</h3>
                        <p className="text-gray-300">{story.story.memory}</p>
                    </div>
                )}

                {story.characters && story.characters.length > 0 && (
                    <div className="mb-8">
                        <h2 className="text-xl font-semibold text-white mb-3">Characters</h2>
                        <div className="flex flex-wrap gap-3">
                            {story.characters.map((c) => (
                                <div key={c.name} className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1">
                                    <span className="text-sm text-white">{c.name}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                <div className="prose prose-gray prose-invert max-w-none">
                    {story.chapters?.map((ch) => (
                        <motion.div
                            key={ch.chapter_number}
                            initial={{ opacity: 0, y: 20 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: 0.4, delay: ch.chapter_number * 0.1 }}
                            className="mb-12"
                        >
                            <h2 className="text-2xl font-bold text-white mb-4">
                                Chapter {ch.chapter_number}: {ch.title || 'Untitled'}
                            </h2>
                            <div
                                className="text-gray-300 leading-relaxed whitespace-pre-wrap"
                                dangerouslySetInnerHTML={{
                                    __html: ch.content
                                        .replace(/&/g, '&amp;')
                                        .replace(/</g, '&lt;')
                                        .replace(/>/g, '&gt;')
                                        .replace(/\*\*([\s\S]*?)\*\*/g, '<strong>$1</strong>')
                                        .replace(/\*([\s\S]*?)\*/g, '<em>$1</em>')
                                        .replace(/\n/g, '<br/>'),
                                }}
                            />
                            {ch.image_paths && ch.image_paths.length > 0 && (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                                    {ch.image_paths.map((img, i) => (
                                        <img
                                            key={i}
                                            src={img.startsWith('/static') ? img : assetUrl(img)}
                                            alt={`Chapter ${ch.chapter_number} illustration`}
                                            className="rounded-lg border border-gray-700"
                                        />
                                    ))}
                                </div>
                            )}
                        </motion.div>
                    ))}
                </div>
            </motion.div>
        </div>

        <ExportModal
            story={story?.story}
            storyId={story?.story?.id}
            token={token}
            isOpen={showExport}
            onClose={() => setShowExport(false)}
        />
        </>
    );
}
