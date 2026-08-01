import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { BookOpen, Sparkles, Image as ImageIcon, Save, Undo2, Play, Settings, Type } from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';

export default function StorySandbox() {
    const [story, setStory] = useState("The ancient gates of Aethelgard stood before you, their iron surface cold in the twilight.");
    const [isGenerating, setIsGenerating] = useState(false);
    const [isPanelOpen, setIsPanelOpen] = useState(true);
    const [images, setImages] = useState([]);
    
    const textareaRef = useRef(null);

    // Auto-resize textarea
    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
            textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
        }
    }, [story]);

    const handleContinue = () => {
        setIsGenerating(true);
        // Simulate backend generation
        setTimeout(() => {
            setStory(prev => prev + " As you step forward, a low rumble echoes from deep within the city, followed by a faint, haunting melody that seems to beckon you inside.");
            setIsGenerating(false);
        }, 1500);
    };

    const handleGenerateIllustration = () => {
        toast('Generating scene illustration...', { icon: '🎨' });
        setTimeout(() => {
            setImages(prev => [...prev, {
                id: Date.now(),
                url: 'https://images.unsplash.com/photo-1518709268805-4e9042af9f23?q=80&w=1200&auto=format&fit=crop',
                caption: 'The ancient gates of Aethelgard'
            }]);
            toast.success('Illustration complete!');
        }, 2000);
    };

    return (
        <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="flex h-[calc(100vh-8rem)] lg:h-[calc(100vh-4rem)] -mx-2 sm:-mx-4 lg:-mx-8 -my-3 sm:-my-4 lg:-my-8 bg-[#0B0E14]"
        >
            {/* Main Story Editor */}
            <div className="flex-1 flex flex-col min-w-0 relative">
                {/* Header */}
                <div className="h-16 border-b border-white/5 flex items-center justify-between px-6 bg-gray-900/60 backdrop-blur-md z-10 shrink-0">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center">
                            <BookOpen className="text-indigo-400" size={20} />
                        </div>
                        <div>
                            <input 
                                type="text"
                                defaultValue="The Gates of Aethelgard"
                                className="bg-transparent font-semibold text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-500/50 rounded px-1 transition-all"
                            />
                            <p className="text-xs text-gray-500 px-1">Story Sandbox</p>
                        </div>
                    </div>
                    
                    <div className="flex items-center gap-2">
                        <button className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-300 hover:text-white bg-white/5 hover:bg-white/10 rounded-lg transition-colors border border-white/5">
                            <Save size={16} /> Save
                        </button>
                        <button 
                            onClick={() => setIsPanelOpen(!isPanelOpen)}
                            className={clsx(
                                "p-2 rounded-lg transition-colors border",
                                isPanelOpen ? "bg-indigo-500/20 text-indigo-400 border-indigo-500/30" : "bg-white/5 text-gray-400 border-white/5 hover:text-white hover:bg-white/10"
                            )}
                        >
                            <ImageIcon size={20} />
                        </button>
                    </div>
                </div>

                {/* Editor Content */}
                <div className="flex-1 overflow-y-auto custom-scrollbar flex justify-center p-6 lg:p-12">
                    <div className="w-full max-w-3xl relative">
                        <textarea
                            ref={textareaRef}
                            value={story}
                            onChange={(e) => setStory(e.target.value)}
                            className="w-full bg-transparent text-gray-300 text-lg md:text-xl leading-relaxed font-serif focus:outline-none resize-none min-h-[300px]"
                            placeholder="Begin your story here..."
                        />
                        
                        {isGenerating && (
                            <div className="flex items-center gap-2 text-indigo-400 font-serif mt-4 animate-pulse">
                                <Sparkles size={16} />
                                <span>The AI is weaving the next thread...</span>
                            </div>
                        )}
                    </div>
                </div>

                {/* Floating Action Bar */}
                <div className="absolute bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-2 p-2 rounded-2xl bg-gray-900/80 backdrop-blur-xl border border-white/10 shadow-2xl shadow-indigo-500/10">
                    <button 
                        className="p-3 text-gray-400 hover:text-white hover:bg-white/10 rounded-xl transition-all"
                        title="Undo"
                    >
                        <Undo2 size={20} />
                    </button>
                    
                    <div className="w-px h-8 bg-white/10 mx-2" />
                    
                    <button 
                        onClick={handleContinue}
                        disabled={isGenerating}
                        className={clsx(
                            "flex items-center gap-2 px-6 py-3 rounded-xl font-medium transition-all",
                            isGenerating 
                                ? "bg-indigo-500/50 text-white/50 cursor-not-allowed" 
                                : "bg-indigo-600 hover:bg-indigo-500 text-white shadow-[0_0_20px_rgba(79,70,229,0.4)] hover:shadow-[0_0_25px_rgba(79,70,229,0.6)]"
                        )}
                    >
                        {isGenerating ? (
                            <div className="flex items-center gap-2">
                                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                Generating
                            </div>
                        ) : (
                            <>
                                <Play size={18} fill="currentColor" className="opacity-80" />
                                Continue
                            </>
                        )}
                    </button>
                    
                    <div className="w-px h-8 bg-white/10 mx-2" />
                    
                    <button 
                        className="p-3 text-gray-400 hover:text-white hover:bg-white/10 rounded-xl transition-all"
                        title="Style Settings"
                    >
                        <Type size={20} />
                    </button>
                </div>
            </div>

            {/* Right Panel: Story Illustrations */}
            <AnimatePresence initial={false}>
                {isPanelOpen && (
                    <motion.div
                        initial={{ width: 0, opacity: 0 }}
                        animate={{ width: 380, opacity: 1 }}
                        exit={{ width: 0, opacity: 0 }}
                        transition={{ duration: 0.3, ease: "easeInOut" }}
                        className="hidden lg:flex flex-col border-l border-white/5 bg-gray-900/40 overflow-hidden shrink-0 relative"
                    >
                        <div className="h-16 border-b border-white/5 flex items-center justify-between px-4 shrink-0 bg-gray-900/60 backdrop-blur-md">
                            <h3 className="font-semibold text-gray-200 flex items-center gap-2">
                                <ImageIcon size={16} className="text-indigo-400" />
                                Story Illustrations
                            </h3>
                            <button className="text-gray-400 hover:text-white p-1 rounded hover:bg-white/10 transition-colors">
                                <Settings size={16} />
                            </button>
                        </div>
                        
                        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar space-y-4">
                            {images.map(img => (
                                <motion.div 
                                    initial={{ opacity: 0, scale: 0.95 }}
                                    animate={{ opacity: 1, scale: 1 }}
                                    key={img.id} 
                                    className="group relative rounded-xl overflow-hidden border border-white/10 shadow-lg"
                                >
                                    <img src={img.url} alt={img.caption} className="w-full h-auto object-cover" />
                                    <div className="absolute inset-x-0 bottom-0 p-3 bg-gradient-to-t from-black/90 to-transparent opacity-0 group-hover:opacity-100 transition-opacity">
                                        <p className="text-sm text-gray-200 line-clamp-2">{img.caption}</p>
                                    </div>
                                </motion.div>
                            ))}
                            
                            {images.length === 0 && (
                                <div className="h-40 border border-dashed border-gray-700 rounded-xl flex flex-col items-center justify-center text-gray-500 gap-2">
                                    <ImageIcon size={32} className="opacity-50" />
                                    <p className="text-sm">No illustrations yet</p>
                                </div>
                            )}
                        </div>

                        <div className="p-4 border-t border-white/5 bg-gray-900/80 backdrop-blur-md">
                            <button 
                                onClick={handleGenerateIllustration}
                                className="w-full flex items-center justify-center gap-2 py-3 bg-white/5 hover:bg-indigo-500/20 text-gray-300 hover:text-indigo-300 rounded-xl border border-white/10 hover:border-indigo-500/50 transition-all font-medium"
                            >
                                <Sparkles size={18} />
                                Illustrate Current Scene
                            </button>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.div>
    );
}
