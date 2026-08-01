import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare, Send, Image as ImageIcon, Settings, PanelRightClose, PanelRightOpen, Paperclip, MoreVertical, Sparkles } from 'lucide-react';
import clsx from 'clsx';

export default function ChatWorkspace() {
    const [isRightPanelOpen, setIsRightPanelOpen] = useState(true);
    const [message, setMessage] = useState('');

    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex h-[calc(100vh-8rem)] lg:h-[calc(100vh-4rem)] -mx-2 sm:-mx-4 lg:-mx-8 -my-3 sm:-my-4 lg:-my-8"
        >
            {/* Left Panel: Chat Interface */}
            <div className="flex-1 flex flex-col min-w-0 bg-[#0B0E14] relative">
                {/* Chat Header */}
                <div className="h-16 border-b border-white/5 flex items-center justify-between px-4 lg:px-6 shrink-0 bg-gray-900/40 backdrop-blur-md z-10">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center overflow-hidden">
                            <MessageSquare className="text-blue-400" size={20} />
                        </div>
                        <div>
                            <h2 className="font-semibold text-gray-100 flex items-center gap-2">
                                Roleplay Session
                                <span className="px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 text-[10px] font-bold uppercase tracking-wider border border-blue-500/20">
                                    Active
                                </span>
                            </h2>
                            <p className="text-xs text-gray-500">No character selected</p>
                        </div>
                    </div>
                    
                    <div className="flex items-center gap-2">
                        <button className="p-2 text-gray-400 hover:text-gray-200 hover:bg-white/5 rounded-lg transition-colors">
                            <MoreVertical size={20} />
                        </button>
                        <button 
                            onClick={() => setIsRightPanelOpen(!isRightPanelOpen)}
                            className="p-2 text-gray-400 hover:text-gray-200 hover:bg-white/5 rounded-lg transition-colors hidden lg:flex"
                            title="Toggle Generator Panel"
                        >
                            {isRightPanelOpen ? <PanelRightClose size={20} /> : <PanelRightOpen size={20} />}
                        </button>
                    </div>
                </div>

                {/* Chat Messages Area */}
                <div className="flex-1 overflow-y-auto p-4 lg:p-6 space-y-6 custom-scrollbar flex flex-col">
                    <div className="flex-1 flex flex-col items-center justify-center text-center opacity-50">
                        <Sparkles className="w-12 h-12 text-blue-500 mb-4 opacity-50" />
                        <h3 className="text-lg font-medium text-gray-300">Welcome to the Story Sandbox</h3>
                        <p className="text-sm text-gray-500 max-w-md mt-2">
                            Select a character to begin chatting. The AI can automatically generate images, audio, and tools during the conversation.
                        </p>
                    </div>
                </div>

                {/* Chat Input Area */}
                <div className="p-4 lg:p-6 border-t border-white/5 bg-gray-900/40 backdrop-blur-md shrink-0">
                    <div className="max-w-4xl mx-auto relative group">
                        <textarea
                            value={message}
                            onChange={(e) => setMessage(e.target.value)}
                            placeholder="Type a message or use / to trigger commands..."
                            className="w-full bg-gray-900/80 border border-gray-700/50 rounded-2xl pl-12 pr-14 py-4 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50 transition-all resize-none shadow-inner"
                            rows={1}
                            style={{ minHeight: '60px', maxHeight: '200px' }}
                        />
                        <button className="absolute left-3 bottom-3 p-2 text-gray-400 hover:text-blue-400 transition-colors rounded-xl hover:bg-blue-500/10">
                            <Paperclip size={20} />
                        </button>
                        <button 
                            className={clsx(
                                "absolute right-3 bottom-3 p-2 transition-all rounded-xl",
                                message.trim() 
                                    ? "bg-blue-600 text-white shadow-[0_0_15px_rgba(37,99,235,0.4)] hover:bg-blue-500 hover:scale-105" 
                                    : "bg-gray-800 text-gray-500 cursor-not-allowed"
                            )}
                        >
                            <Send size={18} className={message.trim() ? "translate-x-0.5 -translate-y-0.5" : ""} />
                        </button>
                    </div>
                    <div className="max-w-4xl mx-auto mt-2 flex items-center justify-between px-2 text-[10px] text-gray-500">
                        <span>Press <kbd className="font-mono bg-gray-800 px-1 py-0.5 rounded border border-gray-700">Enter</kbd> to send</span>
                        <div className="flex gap-4">
                            <span className="flex items-center gap-1"><Sparkles size={12} /> Auto-Gen: On</span>
                        </div>
                    </div>
                </div>
            </div>

            {/* Right Panel: Generator / Context Parameters */}
            <AnimatePresence initial={false}>
                {isRightPanelOpen && (
                    <motion.div
                        initial={{ width: 0, opacity: 0 }}
                        animate={{ width: 400, opacity: 1 }}
                        exit={{ width: 0, opacity: 0 }}
                        transition={{ duration: 0.3, ease: "easeInOut" }}
                        className="hidden lg:flex flex-col border-l border-white/5 bg-gray-900/30 overflow-hidden shrink-0"
                    >
                        <div className="h-16 border-b border-white/5 flex items-center px-4 shrink-0 bg-gray-900/60 backdrop-blur-md">
                            <h3 className="font-semibold text-gray-200 flex items-center gap-2">
                                <Settings size={16} className="text-gray-400" />
                                Context & Generation
                            </h3>
                        </div>
                        
                        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
                            <div className="space-y-6">
                                {/* Section 1 */}
                                <div className="glass-panel p-4 rounded-xl border border-white/5">
                                    <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                                        <ImageIcon size={14} /> Image Generation
                                    </h4>
                                    <p className="text-sm text-gray-500 mb-4">
                                        The AI will automatically generate images when describing scenes or actions.
                                    </p>
                                    <div className="space-y-3">
                                        <label className="flex items-center justify-between cursor-pointer">
                                            <span className="text-sm text-gray-300">Auto-Generate</span>
                                            <div className="relative inline-block w-10 mr-2 align-middle select-none">
                                                <input type="checkbox" className="toggle-checkbox absolute block w-5 h-5 rounded-full bg-white border-4 appearance-none cursor-pointer transition-transform duration-200 ease-in-out" defaultChecked />
                                                <label className="toggle-label block overflow-hidden h-5 rounded-full bg-blue-500 cursor-pointer"></label>
                                            </div>
                                        </label>
                                    </div>
                                </div>
                                
                                {/* Section 2 */}
                                <div className="glass-panel p-4 rounded-xl border border-white/5">
                                    <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-4">Lorebooks</h4>
                                    <div className="text-sm text-gray-500 text-center py-4 border border-dashed border-gray-700/50 rounded-lg">
                                        No active lorebooks
                                    </div>
                                </div>
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.div>
    );
}
