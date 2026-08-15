import React, { useState, useEffect, useMemo } from 'react';
import { Users, BookOpen, MessageSquare, MapPin, Globe, RefreshCw } from 'lucide-react';
import { api } from '../api';

const NODE_COLORS = {
    character: '#8b5cf6',
    story: '#10b981',
    chat: '#3b82f6',
    lorebook: '#f59e0b',
    voice: '#ef4444',
    location: '#06b6d4',
};

const NODE_ICONS = {
    character: Users,
    story: BookOpen,
    chat: MessageSquare,
    lorebook: Globe,
    voice: Globe,
    location: MapPin,
};

export default function RelationshipGraph() {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState('all');

    useEffect(() => {
        fetchRelationships();
    }, []);

    const fetchRelationships = async () => {
        setLoading(true);
        try {
            const result = await api.get('/api/v2/relationships');
            setData(result);
        } catch {
            // silent
        } finally {
            setLoading(false);
        }
    };

    const nodes = useMemo(() => {
        if (!data) return [];
        const nodeMap = new Map();
        const edges = [];

        const addNode = (id, label, type) => {
            if (!nodeMap.has(id)) {
                nodeMap.set(id, { id, label, type });
            }
        };

        data.character_chats?.forEach(([charId, charName, chatId, chatName]) => {
            addNode(charId, charName, 'character');
            addNode(chatId, chatName, 'chat');
            edges.push({ source: charId, target: chatId });
        });

        data.character_stories?.forEach(({ character_id, character_name, story_id, story_title }) => {
            addNode(character_id, character_name, 'character');
            addNode(story_id, story_title, 'story');
            edges.push({ source: character_id, target: story_id });
        });

        data.story_lorebooks?.forEach(({ story_id, story_title, lorebook_id, lorebook_name }) => {
            addNode(story_id, story_title, 'story');
            addNode(lorebook_id, lorebook_name, 'lorebook');
            edges.push({ source: story_id, target: lorebook_id });
        });

        data.character_voices?.forEach(([voiceId, voiceName, charId, charName]) => {
            addNode(voiceId, voiceName, 'voice');
            addNode(charId, charName, 'character');
            edges.push({ source: charId, target: voiceId });
        });

        return { nodes: Array.from(nodeMap.values()), edges };
    }, [data]);

    const filteredNodes = useMemo(() => {
        if (filter === 'all') return nodes.nodes;
        return nodes.nodes.filter(n => n.type === filter);
    }, [nodes, filter]);

    const filteredEdges = useMemo(() => {
        const nodeIds = new Set(filteredNodes.map(n => n.id));
        return nodes.edges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target));
    }, [nodes.edges, filteredNodes]);

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64 text-gray-400">
                <RefreshCw className="animate-spin mr-2" size={20} />
                Loading relationships...
            </div>
        );
    }

    if (!data) {
        return (
            <div className="text-center py-12 text-gray-400">
                Failed to load relationships
            </div>
        );
    }

    return (
        <div className="p-6 max-w-6xl mx-auto">
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-2xl font-bold text-white mb-1">Relationship Graph</h1>
                    <p className="text-gray-400 text-sm">Visualize connections between characters, stories, and more</p>
                </div>
                <div className="flex items-center gap-2">
                    <select
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                        className="px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50"
                    >
                        <option value="all">All Entities</option>
                        <option value="character">Characters</option>
                        <option value="story">Stories</option>
                        <option value="chat">Chats</option>
                        <option value="lorebook">Lorebooks</option>
                        <option value="voice">Voices</option>
                    </select>
                    <button
                        onClick={fetchRelationships}
                        className="p-2 bg-gray-800 border border-white/10 rounded-lg text-gray-400 hover:text-white hover:border-white/20 transition-colors"
                        title="Refresh"
                    >
                        <RefreshCw size={16} />
                    </button>
                </div>
            </div>

            {filteredNodes.length === 0 ? (
                <div className="text-center py-12 text-gray-400">
                    No relationships found. Create characters, stories, and chats to see connections.
                </div>
            ) : (
                <div className="bg-gray-800/40 border border-white/10 rounded-xl p-4 overflow-x-auto">
                    <svg width={Math.max(800, filteredNodes.length * 120)} height={Math.max(600, filteredNodes.length * 80)} className="mx-auto">
                        <defs>
                            <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="28" refY="3.5" orient="auto">
                                <polygon points="0 0, 10 3.5, 0 7" fill="#4b5563" />
                            </marker>
                        </defs>
                        {filteredEdges.map((edge, idx) => {
                            const source = filteredNodes.find(n => n.id === edge.source);
                            const target = filteredNodes.find(n => n.id === edge.target);
                            if (!source || !target) return null;
                            return (
                                <line
                                    key={idx}
                                    x1={filteredNodes.indexOf(source) * 120 + 40}
                                    y1={filteredNodes.indexOf(source) * 80 + 40}
                                    x2={filteredNodes.indexOf(target) * 120 + 40}
                                    y2={filteredNodes.indexOf(target) * 80 + 40}
                                    stroke="#4b5563"
                                    strokeWidth="1.5"
                                    markerEnd="url(#arrowhead)"
                                />
                            );
                        })}
                        {filteredNodes.map((node, idx) => {
                            const Icon = NODE_ICONS[node.type] || Globe;
                            const x = idx * 120 + 40;
                            const y = idx * 80 + 40;
                            return (
                                <g key={node.id} transform={`translate(${x}, ${y})`}>
                                    <circle r="20" fill={NODE_COLORS[node.type] || '#6b7280'} opacity="0.2" />
                                    <circle r="12" fill={NODE_COLORS[node.type] || '#6b7280'} />
                                    <foreignObject x="-8" y="-8" width="16" height="16">
                                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '100%', height: '100%' }}>
                                            <Icon size={12} color="white" />
                                        </div>
                                    </foreignObject>
                                    <text
                                        x="0"
                                        y="32"
                                        textAnchor="middle"
                                        fill="#9ca3af"
                                        fontSize="10"
                                        fontFamily="sans-serif"
                                    >
                                        {node.label.length > 15 ? node.label.slice(0, 12) + '...' : node.label}
                                    </text>
                                </g>
                            );
                        })}
                    </svg>
                </div>
            )}
        </div>
    );
}
