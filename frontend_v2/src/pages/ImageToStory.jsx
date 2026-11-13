import React, { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
    Image as ImageIcon, Upload, BookOpen, Sparkles, ArrowRight, Loader2,
    FileText, RotateCcw,
} from 'lucide-react';
import { api } from '../api/client';
import toast from 'react-hot-toast';
import FormInput from '../components/common/FormInput';
import EmptyState from '../components/EmptyState';

/**
 * ImageToStory — Upload an image and generate a story chapter from it.
 *
 * The backend describes the image (vision-capable LLM or user prompt) and
 * writes a story opening. Returns a job id the frontend can poll.
 */
export default function ImageToStory() {
    const navigate = useNavigate();

    const [imageFile, setImageFile] = useState(null);
    const [imagePreview, setImagePreview] = useState(null);
    const [prompt, setPrompt] = useState('');
    const [title, setTitle] = useState('');
    const [genre, setGenre] = useState('');

    const [storyId, setStoryId] = useState(null);
    useEffect(() => {
        return () => {
            if (imagePreview && imagePreview.startsWith('blob:')) {
                URL.revokeObjectURL(imagePreview);
            }
        };
    }, [imagePreview]);


    const generateMutation = useMutation({
        mutationFn: async (formData) => {
            const resp = await api.post('/api/v2/stories/image-to-story', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });
            return resp?.data || resp;
        },
        onSuccess: () => {
            toast.success('Story generation started — check your stories', { id: 'image-to-story' });
        },
        onError: (err) => {
            toast.error(`Failed to generate story: ${err.message}`, { id: 'image-to-story-error' });
        },
    });

    const handleImageChange = (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        if (!file.type.startsWith('image/')) {
            toast.error('Please select an image file');
            return;
        }
        setImageFile(file);
        setImagePreview(URL.createObjectURL(file));
        // Clear any previous story result when a new image is chosen
        setStoryId(null);
    };

    const handleGenerate = (e) => {
        e.preventDefault();
        if (!imageFile) {
            toast.error('Please upload an image first');
            return;
        }

        const formData = new FormData();
        formData.append('image', imageFile);
        if (prompt) formData.append('prompt', prompt);
        if (title) formData.append('title', title);
        if (genre) formData.append('genre', genre);

        generateMutation.mutate(formData);
    };

    return (
        <div className="flex h-full flex-col bg-gray-900 text-white">
            <header className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-gray-800/50 shrink-0">
                <div className="flex items-center gap-2">
                    <ImageIcon size={18} className="text-blue-400" />
                    <h1 className="text-lg font-semibold">Image → Story</h1>
                </div>
                <p className="text-gray-400 text-sm">
                    Upload an image and generate a story chapter inspired by it.
                    The AI describes what it sees and writes an opening you can
                    continue in the story editor.
                </p>
            </header>

            <div className="flex-1 overflow-y-auto p-6 space-y-6">
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {/* Upload panel */}
                    <div className="space-y-4">
                        <div className="border-2 border-dashed border-gray-600/50 rounded-2xl p-8 text-center hover:border-blue-500/50 transition-colors group cursor-pointer relative">
                            <input
                                type="file"
                                accept="image/*"
                                onChange={handleImageChange}
                                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
                            />
                            <div className="flex flex-col items-center gap-3">
                                {imagePreview ? (
                                    <img
                                        src={imagePreview}
                                        alt="Preview"
                                        className="w-32 h-32 object-cover rounded-xl border border-white/10 shadow-lg"
                                    />
                                ) : (
                                    <Upload size={32} className="text-gray-500 group-hover:text-blue-400 transition-colors" />
                                )}
                                <p className="text-sm font-medium text-gray-300">
                                    {imageFile ? imageFile.name : 'Upload an image'}
                                </p>
                                <p className="text-xs text-gray-500">
                                    PNG, JPG, WEBP — up to 10 MB
                                </p>
                            </div>
                        </div>

                        <FormInput
                            label="Story Title (optional)"
                            value={title}
                            onChange={(e) => setTitle(e.target.value)}
                            placeholder="e.g. Whispers in the Fog"
                        />
                        <FormInput
                            label="Genre (optional)"
                            value={genre}
                            onChange={(e) => setGenre(e.target.value)}
                            placeholder="e.g. gothic horror, cyberpunk, space opera"
                        />
                        <FormInput
                            label="Your description (optional)"
                            value={prompt}
                            onChange={(e) => setPrompt(e.target.value)}
                            rows={4}
                            placeholder="Describe what you see, or leave blank for the AI to interpret the image"
                        />
                    </div>

                    {/* Preview / action panel */}
                    <div className="space-y-4">
                        {imagePreview && (
                            <div className="rounded-2xl border border-white/10 bg-black/40 p-4">
                                <img
                                    src={imagePreview}
                                    alt="Preview"
                                    className="w-full h-64 object-cover rounded-xl border border-white/10"
                                />
                                <div className="mt-3 flex items-center gap-2">
                                    <span className="text-xs text-gray-400 uppercase tracking-wider">Image ready for story generation</span>
                                </div>
                            </div>
                        )}

                        <button
                            onClick={handleGenerate}
                            disabled={!imageFile || generateMutation.isPending}
                            className={`w-full flex items-center justify-center gap-2 bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white font-bold px-6 py-3 rounded-xl transition-all transform active:scale-95 ${!imageFile || generateMutation.isPending ? 'opacity-50 cursor-not-allowed' : ''}`}
                        >
                            {generateMutation.isPending ? (
                                <>
                                    <Loader2 size={18} className="animate-spin" />
                                    Generating story…
                                </>
                            ) : (
                                <>
                                    <Sparkles size={18} />
                                    Generate Story from Image
                                </>
                            )}
                        </button>

                        {storyId && (
                            <div className="rounded-xl border border-green-500/30 bg-green-500/10 p-4">
                                <div className="flex items-center gap-2 mb-2">
                                    <FileText size={16} className="text-green-400" />
                                    <span className="text-sm font-semibold text-green-300">Story created</span>
                                </div>
                                <p className="text-xs text-gray-400 mb-3">
                                    Open the story to continue writing:
                                </p>
                                <button
                                    onClick={() => navigate(`/story/${storyId}`)}
                                    className="w-full bg-green-600 hover:bg-green-500 text-white px-4 py-2 rounded-lg font-medium transition-colors"
                                >
                                    Open Story <ArrowRight size={16} />
                                </button>
                            </div>
                        )}

                        <div className="rounded-lg border border-gray-700/50 bg-gray-800/30 p-4">
                            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">How it works</h3>
                            <ul className="text-sm text-gray-300 space-y-2 leading-relaxed">
                                <li className="flex items-start gap-2">
                                    <Sparkles size={14} className="text-yellow-400 mt-0.5 shrink-0" />
                                    Upload an image — the AI examines what&rsquo;s depicted.
                                </li>
                                <li className="flex items-start gap-2">
                                    <BookOpen size={14} className="text-blue-400 mt-0.5 shrink-0" />
                                    A story opening is written, inspired by the image.
                                </li>
                                <li className="flex items-start gap-2">
                                    <RotateCcw size={14} className="text-purple-400 mt-0.5 shrink-0" />
                                    Continue the story in the editor, chapter by chapter.
                                </li>
                            </ul>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
