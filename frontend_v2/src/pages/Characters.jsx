import React from 'react';
import { motion } from 'framer-motion';
import { Users, Plus, Upload, Search, Filter } from 'lucide-react';
import EmptyState from '../components/EmptyState';

export default function Characters() {
    return (
        <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="flex flex-col h-full"
        >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6 lg:mb-8">
                <div>
                    <h1 className="text-2xl md:text-3xl font-bold text-gray-100 flex items-center gap-3">
                        <Users className="text-blue-500" />
                        Character Vault
                    </h1>
                    <p className="text-gray-400 mt-1 max-w-2xl text-sm">
                        Manage your roleplay characters. Import V2/V3 spec PNG cards or create new ones from scratch.
                    </p>
                </div>
                
                <div className="flex flex-wrap items-center gap-3">
                    <button className="btn-secondary flex items-center gap-2">
                        <Upload size={18} />
                        Import Card
                    </button>
                    <button className="btn-primary flex items-center gap-2">
                        <Plus size={18} />
                        Create Character
                    </button>
                </div>
            </div>

            <div className="glass-panel p-4 mb-6 flex flex-wrap gap-4 items-center">
                <div className="relative flex-1 min-w-[200px]">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
                    <input 
                        type="text" 
                        placeholder="Search characters by name, tags, or author..." 
                        className="w-full bg-gray-900/50 border border-gray-700/50 rounded-lg pl-10 pr-4 py-2 text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50 transition-all"
                    />
                </div>
                <button className="btn-secondary flex items-center gap-2 px-3">
                    <Filter size={18} />
                    Filters
                </button>
            </div>

            <div className="flex-1 rounded-xl border border-dashed border-gray-700/50 flex flex-col items-center justify-center p-8 text-center bg-gray-900/20">
                <EmptyState
                    icon={Users}
                    title="No Characters Found"
                    message="You haven't imported or created any characters yet. Start by importing a V2/V3 PNG character card."
                    action={
                        <button className="btn-primary mt-4 flex items-center gap-2">
                            <Upload size={18} />
                            Import PNG Card
                        </button>
                    }
                />
            </div>
        </motion.div>
    );
}
