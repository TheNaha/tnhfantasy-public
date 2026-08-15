import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, GitBranch, Plus, MessageSquare, Clock } from 'lucide-react';
import { useBranches, useCreateBranch } from '../../hooks/useWorldVault';
import toast from 'react-hot-toast';

/**
 * ChatTimeline — Visual branch timeline for a chat.
 * Shows all branches as a vertical tree. Clicking a message switches the
 * active thread. A "+" button next to any message creates a new branch
 * from that point.
 */
export default function ChatTimeline({ chatId, activeBranch, onBranchChange, onNewBranch }) {
    const { data: branches = [], isLoading } = useBranches(chatId, activeBranch);
    const { mutate: createBranch } = useCreateBranch();
    const [expanded, setExpanded] = useState({});

    const handleCreateBranch = (messageId) => {
        createBranch({ chatId, messageId }, {
            onSuccess: (data) => {
                toast.success('New branch created');
                onNewBranch && onNewBranch(data);
            },
            onError: (e) => toast.error(`Failed: ${e.message}`),
        });
    };

    const toggleExpand = (branchId) => {
        setExpanded((prev) => ({ ...prev, [branchId]: !prev[branchId] }));
    };

    if (isLoading) {
        return <div className="p-4 text-sm text-gray-400">Loading branches...</div>;
    }

    return (
        <div className="space-y-2">
            {branches.map((branch) => {
                const isExpanded = expanded[branch.branch_id] ?? true;
                const isActive = branch.branch_id === activeBranch;
                return (
                    <motion.div
                        key={branch.branch_id}
                        className={`border rounded-lg transition-all ${
                            isActive
                                ? 'border-blue-500/30 bg-blue-500/5'
                                : 'border-gray-700 bg-gray-800/30'
                        }`}
                    >
                        <div
                            className="flex items-center justify-between p-3 cursor-pointer"
                            onClick={() => toggleExpand(branch.branch_id)}
                        >
                            <div className="flex items-center gap-2">
                                <GitBranch size={14} className={isActive ? 'text-blue-400' : 'text-gray-500'} />
                                <span className="text-sm font-medium text-white">
                                    {branch.branch_name || `Branch ${branch.branch_id.slice(0, 8)}`}
                                </span>
                                <span className="text-xs text-gray-500">
                                    ({branch.messages?.length || 0} messages)
                                </span>
                                {isActive && (
                                    <span className="text-xs px-2 py-0.5 bg-blue-500/20 text-blue-300 rounded">
                                        Active
                                    </span>
                                )}
                            </div>
                            <ChevronDown
                                size={14}
                                className={`text-gray-500 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                            />
                        </div>

                        <AnimatePresence initial={false}>
                            {isExpanded && (
                                <motion.div
                                    initial={{ height: 0, opacity: 0 }}
                                    animate={{ height: 'auto', opacity: 1 }}
                                    exit={{ height: 0, opacity: 0 }}
                                    transition={{ duration: 0.2 }}
                                    className="overflow-hidden"
                                >
                                    {branch.messages?.map((msg, idx) => (
                                        <div
                                            key={msg.id}
                                            className="flex items-start gap-3 p-3 border-t border-gray-700/50 last:border-0"
                                        >
                                            <div className="flex-1">
                                                <div className="flex items-center gap-2">
                                                    <span className={`text-xs px-1.5 py-0.5 rounded text-xs capitalize ${
                                                        msg.role === 'user' ? 'bg-gray-700 text-white' :
                                                        msg.role === 'char' ? 'bg-purple-700/30 text-purple-300' :
                                                        'bg-gray-700 text-gray-400'
                                                    }`}>
                                                        {msg.role === 'user' ? 'You' : msg.role === 'char' ? 'Character' : msg.role}
                                                    </span>
                                                    <Clock size={10} className="text-gray-600" />
                                                    <span className="text-xs text-gray-500">
                                                        {idx + 1}
                                                    </span>
                                                </div>
                                                <p
                                                    className="text-sm text-gray-300 mt-1 line-clamp-2 cursor-pointer"
                                                    onClick={() => onBranchChange && onBranchChange(branch.branch_id, msg.id)}
                                                    title="Click to switch to this message"
                                                >
                                                    {msg.content || '(no content)'}
                                                </p>
                                            </div>
                                            <button
                                                onClick={() => handleCreateBranch(msg.id)}
                                                className="p-1 text-gray-500 hover:text-gray-400"
                                                title="Branch from here"
                                            >
                                                <Plus size={12} />
                                            </button>
                                        </div>
                                    ))}
                                </motion.div>
                            )}
                        </AnimatePresence>
                    </motion.div>
                );
            })}
        </div>
    );
}
