import { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { X, UploadCloud, Loader2, Sparkles, Wand2, Tag, Copy } from 'lucide-react';
import toast from 'react-hot-toast';
import { useGeneratorStore } from '../../store/generatorStore';

export default function InterrogateModal({ isOpen, onClose }) {
    const setPrompt = useGeneratorStore((state) => state.setPrompt);
    const setNegativePrompt = useGeneratorStore((state) => state.setNegativePrompt);

    const [isLoading, setIsLoading] = useState(false);
    const [previewUrl, setPreviewUrl] = useState(null);
    const [result, setResult] = useState(null);

    const onDrop = useCallback(async (acceptedFiles) => {
        const file = acceptedFiles[0];
        if (!file) return;

        setPreviewUrl(URL.createObjectURL(file));
        setIsLoading(true);
        setResult(null);

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch('/api/generate/interrogate', {
                method: 'POST',
                body: formData,
            });

            if (!res.ok) {
                throw new Error(`Failed to interrogate image: ${res.statusText}`);
            }

            const data = await res.json();
            setResult(data);
            toast.success(
                data.source === 'embedded_metadata'
                    ? 'Extracted embedded generation parameters!'
                    : 'Interrogated image successfully!',
                { icon: '✨' }
            );
        } catch (err) {
            toast.error(err.message || 'Failed to interrogate image');
        } finally {
            setIsLoading(false);
        }
    }, []);

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        onDrop,
        accept: { 'image/*': ['.png', '.jpg', '.jpeg', '.webp'] },
        maxFiles: 1,
    });

    const handleApply = (replace = true) => {
        if (!result) return;
        if (replace) {
            setPrompt(result.prompt);
            if (result.negative_prompt) {
                setNegativePrompt(result.negative_prompt);
            }
            toast.success('Applied prompt & negative prompt!');
        } else {
            const currentPrompt = useGeneratorStore.getState().prompt;
            const updated = currentPrompt
                ? `${currentPrompt.trim()}, ${result.prompt}`
                : result.prompt;
            setPrompt(updated);
            toast.success('Appended prompt tags!');
        }
        onClose();
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
            <div className="relative w-full max-w-2xl bg-gray-900 border border-white/10 rounded-2xl shadow-2xl p-6 space-y-5 max-h-[90vh] overflow-y-auto">
                <div className="flex items-center justify-between border-b border-white/10 pb-4">
                    <h3 className="text-lg font-bold text-white flex items-center gap-2">
                        <Wand2 size={20} className="text-emerald-400" />
                        <span>Image Interrogator (Reverse Prompt)</span>
                    </h3>
                    <button
                        onClick={onClose}
                        className="text-gray-400 hover:text-white p-1 rounded-lg hover:bg-white/10 transition-colors"
                        aria-label="Close modal"
                    >
                        <X size={20} />
                    </button>
                </div>

                {/* Dropzone */}
                <div
                    {...getRootProps()}
                    className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${
                        isDragActive
                            ? 'border-emerald-500 bg-emerald-500/10'
                            : 'border-white/10 hover:border-emerald-500/50 bg-black/40'
                    }`}
                >
                    <input {...getInputProps()} />
                    {previewUrl ? (
                        <div className="space-y-3">
                            <img
                                src={previewUrl}
                                alt="Interrogated preview"
                                className="max-h-48 mx-auto rounded-lg object-contain shadow-lg border border-white/10"
                            />
                            <p className="text-xs text-gray-400">Click or drag another image to re-interrogate</p>
                        </div>
                    ) : (
                        <div className="space-y-2 py-4">
                            <UploadCloud size={36} className="mx-auto text-emerald-400" />
                            <p className="text-sm font-semibold text-white">
                                Drop an image here or click to browse
                            </p>
                            <p className="text-xs text-gray-400">
                                Supports PNG (with ComfyUI / A1111 / Civitai metadata), JPG, WebP
                            </p>
                        </div>
                    )}
                </div>

                {isLoading && (
                    <div className="flex items-center justify-center gap-2 text-emerald-400 text-sm py-4">
                        <Loader2 size={18} className="animate-spin" />
                        <span>Analyzing image & extracting prompts...</span>
                    </div>
                )}

                {/* Results Section */}
                {result && !isLoading && (
                    <div className="space-y-4 bg-black/40 p-4 rounded-xl border border-white/10 text-xs">
                        {result.source === 'embedded_metadata' && (
                            <div className="flex items-center gap-1.5 text-2xs text-emerald-300 font-semibold uppercase tracking-wider bg-emerald-950/40 px-2.5 py-1 rounded border border-emerald-800/60 w-fit">
                                <Sparkles size={12} />
                                <span>Found embedded {result.metadata?.format || 'generation'} metadata</span>
                            </div>
                        )}

                        <div className="space-y-1">
                            <label className="text-2xs font-bold text-blue-400 uppercase tracking-widest">
                                Detected Positive Prompt
                            </label>
                            <p className="p-2.5 bg-gray-950 rounded-lg text-gray-200 select-all border border-white/5 font-mono leading-relaxed">
                                {result.prompt}
                            </p>
                        </div>

                        {result.negative_prompt && (
                            <div className="space-y-1">
                                <label className="text-2xs font-bold text-pink-400 uppercase tracking-widest">
                                    Detected Negative Prompt
                                </label>
                                <p className="p-2.5 bg-gray-950 rounded-lg text-gray-300 select-all border border-white/5 font-mono leading-relaxed">
                                    {result.negative_prompt}
                                </p>
                            </div>
                        )}

                        {result.tags && result.tags.length > 0 && (
                            <div className="space-y-1.5 pt-1">
                                <label className="text-2xs font-bold text-gray-400 uppercase tracking-widest flex items-center gap-1">
                                    <Tag size={12} />
                                    <span>Individual Tags ({result.tags.length})</span>
                                </label>
                                <div className="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto custom-scrollbar">
                                    {result.tags.map((tag, i) => (
                                        <span
                                            key={i}
                                            className="px-2 py-0.5 rounded bg-white/5 border border-white/10 text-gray-300 text-2xs"
                                        >
                                            {tag}
                                        </span>
                                    ))}
                                </div>
                            </div>
                        )}

                        <div className="flex items-center justify-end gap-2 pt-3 border-t border-white/10">
                            <button
                                type="button"
                                onClick={() => handleApply(false)}
                                className="px-3 py-1.5 rounded-lg border border-white/10 bg-white/5 hover:bg-white/10 text-gray-300 transition-colors text-xs flex items-center gap-1.5"
                            >
                                <Copy size={13} />
                                <span>Append to Existing</span>
                            </button>
                            <button
                                type="button"
                                onClick={() => handleApply(true)}
                                className="px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold transition-colors text-xs flex items-center gap-1.5 shadow-lg shadow-emerald-600/30"
                            >
                                <Sparkles size={13} />
                                <span>Apply to Generator</span>
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
