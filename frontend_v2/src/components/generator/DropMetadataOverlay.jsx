import { useState, useEffect } from 'react';
import { UploadCloud, Sparkles, Loader2 } from 'lucide-react';
import toast from 'react-hot-toast';
import { extractPngInfo } from '../../utils/pngInfoReader';
import { useGeneratorStore } from '../../store/generatorStore';

export default function DropMetadataOverlay() {
    const [isDragging, setIsDragging] = useState(false);
    const [isProcessing, setIsProcessing] = useState(false);
    const setPrompt = useGeneratorStore((state) => state.setPrompt);
    const setNegativePrompt = useGeneratorStore((state) => state.setNegativePrompt);

    useEffect(() => {
        let dragCounter = 0;

        function handleDragEnter(e) {
            if (e.dataTransfer?.types?.includes('Files')) {
                dragCounter++;
                setIsDragging(true);
            }
        }

        function handleDragLeave(e) {
            if (e.dataTransfer?.types?.includes('Files')) {
                dragCounter--;
                if (dragCounter <= 0) {
                    setIsDragging(false);
                    dragCounter = 0;
                }
            }
        }

        function handleDragOver(e) {
            e.preventDefault();
        }

        async function handleDrop(e) {
            e.preventDefault();
            dragCounter = 0;
            setIsDragging(false);

            const file = e.dataTransfer?.files?.[0];
            if (!file || !file.type.startsWith('image/')) return;

            setIsProcessing(true);
            try {
                const info = await extractPngInfo(file);
                if (info.prompt) {
                    setPrompt(info.prompt);
                    if (info.negativePrompt) {
                        setNegativePrompt(info.negativePrompt);
                    }
                    toast.success(
                        info.source === 'embedded_metadata'
                            ? 'Extracted generation metadata from image!'
                            : 'Interrogated prompt from dropped image!',
                        { icon: '✨' }
                    );
                } else {
                    toast.error('No prompt or parameters detected in this image');
                }
            } catch (err) {
                toast.error(err.message || 'Failed to inspect dropped image');
            } finally {
                setIsProcessing(false);
            }
        }

        window.addEventListener('dragenter', handleDragEnter);
        window.addEventListener('dragleave', handleDragLeave);
        window.addEventListener('dragover', handleDragOver);
        window.addEventListener('drop', handleDrop);

        return () => {
            window.removeEventListener('dragenter', handleDragEnter);
            window.removeEventListener('dragleave', handleDragLeave);
            window.removeEventListener('dragover', handleDragOver);
            window.removeEventListener('drop', handleDrop);
        };
    }, [setPrompt, setNegativePrompt]);

    if (!isDragging && !isProcessing) return null;

    return (
        <div className="fixed inset-0 z-50 pointer-events-none flex items-center justify-center bg-blue-950/70 backdrop-blur-sm border-4 border-dashed border-blue-400 m-4 rounded-3xl animate-in fade-in duration-150">
            <div className="bg-gray-900/90 border border-white/20 p-8 rounded-2xl shadow-2xl text-center space-y-3 pointer-events-auto max-w-md">
                {isProcessing ? (
                    <>
                        <Loader2 size={48} className="mx-auto text-blue-400 animate-spin" />
                        <h3 className="text-lg font-bold text-white">Extracting Generation Metadata...</h3>
                        <p className="text-xs text-gray-400">Reading PNG chunks and prompt tokens</p>
                    </>
                ) : (
                    <>
                        <UploadCloud size={48} className="mx-auto text-blue-400 animate-bounce" />
                        <h3 className="text-lg font-bold text-white flex items-center justify-center gap-2">
                            <Sparkles size={18} className="text-yellow-400" />
                            <span>Drop to Load Parameters</span>
                        </h3>
                        <p className="text-xs text-gray-300">
                            Drop any Civitai, ComfyUI, or AI image to automatically extract and populate its prompts
                        </p>
                    </>
                )}
            </div>
        </div>
    );
}
