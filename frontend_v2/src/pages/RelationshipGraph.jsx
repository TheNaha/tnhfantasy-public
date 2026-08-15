import { useEffect, useMemo, useState } from 'react';
import { Users, BookOpen, MessageSquare, MapPin, Globe, Volume2, RefreshCw } from 'lucide-react';
import { useWorldVaultRelationships } from '../hooks/useWorldVault';

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
    voice: Volume2,
    location: MapPin,
};

const NODE_LABELS = {
    character: 'Characters',
    story: 'Stories',
    chat: 'Chats',
    lorebook: 'Lorebooks',
    voice: 'Voices',
    location: 'Locations',
};

const SVG_WIDTH = 900;
const SVG_HEIGHT = 700;
const CENTER_X = SVG_WIDTH / 2;
const CENTER_Y = SVG_HEIGHT / 2;

// Simple force-directed layout using a physics simulation.
// Runs in a requestAnimationFrame loop; no external libraries required.
function useForceDirectedLayout(nodes, edges, iterations = 300) {
    const [positions, setPositions] = useState(() => {
        // Random initial positions within the SVG viewport
        return new Map(
            nodes.map(n => [
                n.id,
                {
                    x: Math.random() * (SVG_WIDTH - 100) + 50,
                    y: Math.random() * (SVG_HEIGHT - 100) + 50,
                    vx: 0,
                    vy: 0,
                },
            ])
        );
    });

    useEffect(() => {
        if (!nodes.length) return;

        const pos = new Map();
        nodes.forEach(n => {
            pos.set(n.id, {
                x: Math.random() * (SVG_WIDTH - 100) + 50,
                y: Math.random() * (SVG_HEIGHT - 100) + 50,
                vx: 0,
                vy: 0,
            });
        });

        const k_repel = 6000; // repulsion strength
        const k_spring = 0.05; // spring strength
        const rest_length = 180; // ideal edge length
        const damping = 0.85;
        const bounds = 44; // keep nodes at least nodeRadius+20 from edges

        const edgeSet = new Set(edges.map(e => `${e.source}→${e.target}`));

        let frame = 0;
        const animate = () => {
            frame++;

            // Repulsion between all pairs
            for (let i = 0; i < nodes.length; i++) {
                for (let j = i + 1; j < nodes.length; j++) {
                    const a = pos.get(nodes[i].id);
                    const b = pos.get(nodes[j].id);
                    if (!a || !b) continue;
                    const dx = a.x - b.x;
                    const dy = a.y - b.y;
                    let dist = Math.sqrt(dx * dx + dy * dy) || 0.1;
                    if (dist < 2) dist = 2;
                    // Skip repulsion for connected nodes (handled by spring)
                    if (edgeSet.has(`${nodes[i].id}→${nodes[j].id}`) || edgeSet.has(`${nodes[j].id}→${nodes[i].id}`)) {
                        dist = Math.max(dist, rest_length * 0.6);
                    }
                    const force = k_repel / (dist * dist);
                    const fx = (dx / dist) * force;
                    const fy = (dy / dist) * force;
                    a.vx += fx;
                    a.vy += fy;
                    b.vx -= fx;
                    b.vy -= fy;
                }
            }

            // Spring attraction along edges
            for (const edge of edges) {
                const a = pos.get(edge.source);
                const b = pos.get(edge.target);
                if (!a || !b) continue;
                const dx = b.x - a.x;
                const dy = b.y - a.y;
                let dist = Math.sqrt(dx * dx + dy * dy) || 0.1;
                const force = k_spring * (dist - rest_length);
                const fx = (dx / dist) * force;
                const fy = (dy / dist) * force;
                a.vx += fx;
                a.vy += fy;
                b.vx -= fx;
                b.vy -= fy;
            }

            // Centering force + velocity integration + damping
            for (const n of nodes) {
                const p = pos.get(n.id);
                if (!p) continue;

                // Centering
                p.vx += (CENTER_X - p.x) * 0.0005;
                p.vy += (CENTER_Y - p.y) * 0.0005;

                p.vx *= damping;
                p.vy *= damping;

                p.x += p.vx;
                p.y += p.vy;

                // Keep inside bounds
                const minX = bounds;
                const maxX = SVG_WIDTH - bounds;
                const minY = bounds;
                const maxY = SVG_HEIGHT - bounds;
                if (p.x < minX) { p.x = minX; p.vx *= -0.3; }
                if (p.x > maxX) { p.x = maxX; p.vx *= -0.3; }
                if (p.y < minY) { p.y = minY; p.vy *= -0.3; }
                if (p.y > maxY) { p.y = maxY; p.vy *= -0.3; }
            }

            if (frame < iterations) {
                requestAnimationFrame(animate);
            } else {
                setPositions(new Map(pos));
            }
        };

        requestAnimationFrame(animate);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [nodes, edges]);

    return positions;
}

export default function RelationshipGraph() {
    const [filter, setFilter] = useState('all');

    const { data, isLoading, isError, refetch, isFetching } = useWorldVaultRelationships();

    const { nodes, edges } = useMemo(() => {
        if (!data) return { nodes: [], edges: [] };
        const nodeMap = new Map();
        const edgeList = [];

        const addNode = (id, label, type) => {
            if (!nodeMap.has(id)) {
                nodeMap.set(id, { id, label, type });
            }
            return id;
        };

        data.character_chats?.forEach(([charId, charName, chatId, chatName]) => {
            addNode(charId, charName, 'character');
            addNode(chatId, chatName, 'chat');
            edgeList.push({ source: charId, target: chatId });
        });

        data.character_stories?.forEach(({ character_id, character_name, story_id, story_title }) => {
            addNode(character_id, character_name, 'character');
            addNode(story_id, story_title, 'story');
            edgeList.push({ source: character_id, target: story_id });
        });

        data.story_lorebooks?.forEach(({ story_id, story_title, lorebook_id, lorebook_name }) => {
            addNode(story_id, story_title, 'story');
            addNode(lorebook_id, lorebook_name, 'lorebook');
            edgeList.push({ source: story_id, target: lorebook_id });
        });

        data.character_voices?.forEach(([voiceId, voiceName, charId, charName]) => {
            addNode(voiceId, voiceName, 'voice');
            addNode(charId, charName, 'character');
            edgeList.push({ source: charId, target: voiceId });
        });

        // New: Story ↔ Locations
        data.story_locations?.forEach(({ story_id, story_title, location_id, location_name }) => {
            addNode(story_id, story_title, 'story');
            addNode(location_id, location_name, 'location');
            edgeList.push({ source: story_id, target: location_id });
        });

        // New: Chat ↔ Locations
        data.chat_locations?.forEach(([chatId, chatName, locId, locName]) => {
            addNode(chatId, chatName, 'chat');
            addNode(locId, locName, 'location');
            edgeList.push({ source: chatId, target: locId });
        });

        return { nodes: Array.from(nodeMap.values()), edges: edgeList };
    }, [data]);

    // Run the force-directed physics simulation
    const positions = useForceDirectedLayout(nodes, edges, 500);

    const filteredNodes = useMemo(() => {
        if (filter === 'all') return nodes;
        return nodes.filter(n => n.type === filter);
    }, [nodes, filter]);

    const filteredEdges = useMemo(() => {
        const nodeIds = new Set(filteredNodes.map(n => n.id));
        return edges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target));
    }, [edges, filteredNodes]);

    if (isLoading) {
        return (
            <div className="flex items-center justify-center h-64 text-gray-400">
                <RefreshCw className="animate-spin mr-2" size={20} />
                Loading relationships...
            </div>
        );
    }

    if (isError) {
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
                    <p className="text-gray-400 text-sm">Drag nodes to reposition. Visualize connections between characters, stories, chats, and more.</p>
                </div>
                <div className="flex items-center gap-2">
                    <select
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                        className="px-3 py-2 bg-gray-800 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50"
                    >
                        <option value="all">All Entities</option>
                        {Object.entries(NODE_LABELS).map(([type, label]) => (
                            <option key={type} value={type}>{label}</option>
                        ))}
                    </select>
                    <button
                        onClick={() => refetch()}
                        className="p-2 bg-gray-800 border border-white/10 rounded-lg text-gray-400 hover:text-white hover:border-white/20 transition-colors"
                        title="Refresh"
                    >
                        <RefreshCw size={16} className={isFetching ? 'animate-spin' : ''} />
                    </button>
                </div>
            </div>

            {/* Legend */}
            <div className="flex flex-wrap gap-3 mb-4 text-xs">
                {Object.entries(NODE_LABELS).map(([type, label]) => {
                    const Icon = NODE_ICONS[type] || Globe;
                    return (
                        <div key={type} className="flex items-center gap-1.5 px-2.5 py-1 bg-gray-800/40 rounded-lg border border-white/5">
                            <Icon size={12} style={{ color: NODE_COLORS[type] }} />
                            <span className="text-gray-400">{label}</span>
                        </div>
                    );
                })}
            </div>

            {filteredNodes.length === 0 ? (
                <div className="text-center py-12 text-gray-400">
                    No relationships found. Create characters, stories, and chats to see connections.
                </div>
            ) : (
                <div className="bg-gray-800/40 border border-white/10 rounded-xl p-4 overflow-x-auto">
                    <svg width={SVG_WIDTH} height={SVG_HEIGHT} className="mx-auto">
                        <defs>
                            <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="28" refY="3.5" orient="auto">
                                <polygon points="0 0, 10 3.5, 0 7" fill="#4b5563" />
                            </marker>
                        </defs>
                        {/* Edges */}
                        {filteredEdges.map((edge, idx) => {
                            const sourcePos = positions.get(edge.source);
                            const targetPos = positions.get(edge.target);
                            if (!sourcePos || !targetPos) return null;
                            return (
                                <line
                                    key={idx}
                                    x1={sourcePos.x}
                                    y1={sourcePos.y}
                                    x2={targetPos.x}
                                    y2={targetPos.y}
                                    stroke="#4b5563"
                                    strokeWidth="1.5"
                                    markerEnd="url(#arrowhead)"
                                />
                            );
                        })}
                        {/* Nodes */}
                        {filteredNodes.map((node) => {
                            const Icon = NODE_ICONS[node.type] || Globe;
                            const color = NODE_COLORS[node.type] || '#6b7280';
                            const pos = positions.get(node.id);
                            if (!pos) return null;
                            const label = node.label;
                            return (
                                <g key={node.id} transform={`translate(${pos.x}, ${pos.y})`}>
                                    <circle r="22" fill={color} opacity="0.15" />
                                    <circle r="14" fill={color} />
                                    <foreignObject x="-8" y="-8" width="16" height="16">
                                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '100%', height: '100%' }}>
                                            <Icon size={12} color="white" />
                                        </div>
                                    </foreignObject>
                                    <text
                                        x="0"
                                        y="30"
                                        textAnchor="middle"
                                        fill="#9ca3af"
                                        fontSize="10"
                                        fontFamily="sans-serif"
                                    >
                                        {label}
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
