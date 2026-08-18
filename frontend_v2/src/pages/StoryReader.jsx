import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Download, Share2, BookOpen, Play, Pause, FileDown } from 'lucide-react';
import { api } from '../api';
import toast from 'react-hot-toast';
import ExportModal from '../components/story/ExportModal';

export default function StoryReader() {
    const { token } = useParams();
    const navigate = useNavigate();
    const [showExport, setShowExport] = useState(false);

    const { data: story, isLoading: loading, isError } = useQuery({
        queryKey: ['published_story', token],
        queryFn: () => api.get(`/api/v2/stories/published/${token}`),
        enabled: !!token,
        retry: false,
    });

    useEffect(() => {
        if (isError) {
            toast.error('Story not found or no longer available');
            navigate('/');
        }
    }, [isError, navigate]);

    const handleShare = async () => {
        try {
            await navigator.clipboard.writeText(window.location.href);
            toast.success('Link copied!');
        } catch {
            toast.error('Could not copy link');
        }
    };

    const handleExport = async (format) => {
        try {
            // Binary formats (epub, comic, webtoon) need responseType: 'blob'
            const binaryFormats = ['epub', 'comic', 'webtoon'];
            const exportUrl = `/api/v2/stories/published/${token}/export?format=${format}`;
            const data = binaryFormats.includes(format)
                ? await api.get(exportUrl, { responseType: 'blob' })
                : await api.get(exportUrl);
            let blob, filename;
            if (format === 'md' || format === 'markdown') {
                blob = new Blob([data.content], { type: 'text/markdown' });
                filename = 'story.md';
            } else if (binaryFormats.includes(format)) {
                blob = data;
                filename = `story.${format === 'comic' ? 'pdf' : format === 'webtoon' ? 'png' : format}`;
            } else {
                // JSON
                blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
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

    if (!story) return null;

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
                                        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                                        .replace(/\*(.*?)\*/g, '<em>$1</em>')
                                        .replace(/\n/g, '<br/>'),
                                }}
                            />
                            {ch.image_paths && ch.image_paths.length > 0 && (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                                    {ch.image_paths.map((img, i) => (
                                        <img
                                            key={i}
                                            src={img.startsWith('/static') ? img : `/static/${img}`}
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
