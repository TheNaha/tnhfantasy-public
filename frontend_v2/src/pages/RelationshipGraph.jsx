import { useEffect, useMemo, useState, useCallback, useRef } from 'react';
import { Users, BookOpen, MessageSquare, MapPin, Globe, Volume2, RefreshCw, Save, RotateCcw, X, Pencil, Sparkles, Link, Plus, Trash2, CirclePlus } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useWorldVaultRelationships, useGraphLayout, useSaveGraphLayout, useDeleteGraphLayout, useGraphEdges, useCreateGraphEdge, useDeleteGraphEdge } from '../hooks/useWorldVaultSearch';
import RoleplayPageShell from '../components/RoleplayPageShell';
import { QueryErrorState } from '../components/common/QueryState';
import { TransformWrapper, TransformComponent } from 'react-zoom-pan-pinch';

const NODE_COLORS = {
    character: '#8b5cf6',
    story: '#10b981',
    chat: '#3b82f6',
    lorebook: '#f59e0b',
    voice: '#ef4444',
    location: '#06b6d4',
    scenario: '#ec4899',
};

const NODE_ICONS = {
    character: Users,
    story: BookOpen,
    chat: MessageSquare,
    lorebook: Globe,
    voice: Volume2,
    location: MapPin,
    scenario: Sparkles,
};

const NODE_LABELS = {
    character: 'Characters',
    story: 'Stories',
    chat: 'Chats',
    lorebook: 'Lorebooks',
    voice: 'Voices',
    location: 'Locations',
    scenario: 'Scenarios',
};

const SVG_WIDTH = 900;
const SVG_HEIGHT = 700;
const CENTER_X = SVG_WIDTH / 2;
const CENTER_Y = SVG_HEIGHT / 2;
const NODE_RADIUS = 22;

function useForceDirectedLayout(nodes, edges, iterations = 300, savedPositions = null) {
    const [positions, setPositions] = useState(() => {
        return new Map(
            nodes.map(n => [
                n.id,
                savedPositions?.get(n.id) || {
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
                x: savedPositions?.get(n.id)?.x ?? (Math.random() * (SVG_WIDTH - 100) + 50),
                y: savedPositions?.get(n.id)?.y ?? (Math.random() * (SVG_HEIGHT - 100) + 50),
                vx: 0,
                vy: 0,
            });
        });

        const k_repel = 6000;
        const k_spring = 0.05;
        const rest_length = 180;
        const damping = 0.85;
        const bounds = 44;

        const edgeSet = new Set(edges.map(e => `${e.source}→${e.target}`));

        let step = 0;
        const stepsTotal = iterations;
        const stepsPerFrame = nodes.length > 100 ? 2 : 6;
        let rafId = 0;

        const simulateStep = () => {
            for (let i = 0; i < nodes.length; i++) {
                for (let j = i + 1; j < nodes.length; j++) {
                    const a = pos.get(nodes[i].id);
                    const b = pos.get(nodes[j].id);
                    if (!a || !b) continue;
                    const dx = a.x - b.x;
                    const dy = a.y - b.y;
                    let dist = Math.sqrt(dx * dx + dy * dy) || 0.1;
                    if (dist < 2) dist = 2;
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

            let energy = 0;
            for (const n of nodes) {
                const p = pos.get(n.id);
                if (!p) continue;

                p.vx += (CENTER_X - p.x) * 0.0005;
                p.vy += (CENTER_Y - p.y) * 0.0005;

                p.vx *= damping;
                p.vy *= damping;

                p.x += p.vx;
                p.y += p.vy;

                energy += p.vx * p.vx + p.vy * p.vy;

                const minX = bounds;
                const maxX = SVG_WIDTH - bounds;
                const minY = bounds;
                const maxY = SVG_HEIGHT - bounds;
                if (p.x < minX) { p.x = minX; p.vx *= -0.3; }
                if (p.x > maxX) { p.x = maxX; p.vx *= -0.3; }
                if (p.y < minY) { p.y = minY; p.vy *= -0.3; }
                if (p.y > maxY) { p.y = maxY; p.vy *= -0.3; }
            }
            return energy;
        };

        const animate = () => {
            let settled = false;
            for (let s = 0; s < stepsPerFrame && step < stepsTotal; s++) {
                step++;
                const energy = simulateStep();
                if (energy < 0.05) {
                    settled = true;
                    break;
                }
            }

            if (settled || step >= stepsTotal) {
                setPositions(new Map(pos));
            } else {
                rafId = requestAnimationFrame(animate);
            }
        };

        rafId = requestAnimationFrame(animate);

        return () => cancelAnimationFrame(rafId);
    }, [nodes, edges, savedPositions, iterations]);

    const updatePosition = useCallback((nodeId, x, y) => {
        setPositions(prev => {
            const next = new Map(prev);
            const existing = next.get(nodeId) || { x: 0, y: 0, vx: 0, vy: 0 };
            next.set(nodeId, { ...existing, x, y, vx: 0, vy: 0 });
            return next;
        });
    }, []);

    return { positions, updatePosition };
}

function EditPanel({ node, onClose, onNavigate }) {
    const nodeRouteMap = {
        character: '/characters',
        story: '/story',
        chat: '/chat',
        lorebook: '/lorebooks',
        voice: '/voices',
        location: '/locations',
        scenario: '/scenarios',
    };

    const color = NODE_COLORS[node.type] || '#6b7280';
    const Icon = NODE_ICONS[node.type] || Globe;
    const route = nodeRouteMap[node.type];

    return (
        <div className="absolute top-4 right-4 w-72 bg-gray-800 border border-white/10 rounded-xl p-4 z-20 shadow-xl">
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-full flex items-center justify-center" style={{ backgroundColor: color + '30' }}>
                        <Icon size={16} style={{ color }} />
                    </div>
                    <div>
                        <p className="text-white text-sm font-medium truncate max-w-[160px]">{node.label}</p>
                        <p className="text-gray-400 text-xs capitalize">{node.type}</p>
                    </div>
                </div>
                <button onClick={onClose} aria-label="Close entity details" className="p-1 text-gray-400 hover:text-white transition-colors">
                    <X size={16} />
                </button>
            </div>
            {node.dangling && (
                <div className="mb-3 px-2 py-1.5 bg-red-500/10 border border-red-500/20 rounded-lg">
                    <p className="text-red-400 text-xs">Dangling link — referenced entity no longer exists</p>
                </div>
            )}
            <div className="flex flex-col gap-2">
                {route && (
                    <button
                        onClick={() => onNavigate(node)}
                        className="flex items-center gap-2 px-3 py-2 bg-blue-600/20 border border-blue-500/30 rounded-lg text-blue-400 text-sm hover:bg-blue-600/30 transition-colors"
                    >
                        <Pencil size={14} />
                        Edit {node.type}
                    </button>
                )}
                {node.type === 'story' || node.type === 'chat' ? (
                    <button
                        onClick={() => onNavigate(node, true)}
                        className="flex items-center gap-2 px-3 py-2 bg-gray-700/50 border border-white/10 rounded-lg text-gray-300 text-sm hover:bg-gray-700 transition-colors"
                    >
                        Open {node.type} page
                    </button>
                ) : null}
            </div>
        </div>
    );
}

function LinkDialog({ source, target, onClose, onCreate }) {
    const [relationType, setRelationType] = useState('');
    const [label, setLabel] = useState('');
    const [submitting, setSubmitting] = useState(false);

    const handleSubmit = (e) => {
        e.preventDefault();
        if (!relationType.trim()) return;
        setSubmitting(true);
        onCreate({
            source_entity_type: source.type,
            source_entity_id: source.id,
            target_entity_type: target.type,
            target_entity_id: target.id,
            relation_type: relationType.trim(),
            label: label.trim() || null,
        }).then(() => {
            setSubmitting(false);
            onClose();
        });
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
            <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
            <div className="bg-gray-800 border border-white/10 rounded-xl p-6 w-80 shadow-xl">
                <h3 className="text-white font-semibold mb-4">Link {source.label} → {target.label}</h3>
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label htmlFor="link-relation-type" className="block text-xs text-gray-400 mb-1">Relation type</label>
                        <input
                            id="link-relation-type"
                            value={relationType}
                            onChange={(e) => setRelationType(e.target.value)}
                            placeholder="e.g. enemy, references, sequel, loves"
                            className="w-full px-3 py-2 bg-gray-900 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50"
                        />
                    </div>
                    <div>
                        <label htmlFor="link-label" className="block text-xs text-gray-400 mb-1">Label (optional)</label>
                        <input
                            id="link-label"
                            value={label}
                            onChange={(e) => setLabel(e.target.value)}
                            placeholder="Human-readable edge label"
                            className="w-full px-3 py-2 bg-gray-900 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500/50"
                        />
                    </div>
                    <div className="flex justify-end gap-2 pt-2">
                        <button
                            type="button"
                            onClick={onClose}
                            className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={submitting || !relationType.trim()}
                            className="px-4 py-2 text-sm bg-cyan-500 text-slate-950 hover:bg-cyan-400 disabled:opacity-50 rounded-lg transition-colors"
                        >
                            {submitting ? 'Linking…' : 'Create link'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}

export default function RelationshipGraph() {
    const navigate = useNavigate();
    const [filter, setFilter] = useState('all');
    const [selectedNode, setSelectedNode] = useState(null);
    const [isDragging, setIsDragging] = useState(false);
    const [dragNodeId, setDragNodeId] = useState(null);
    const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
    const [linkingFrom, setLinkingFrom] = useState(null);
    const [linkDialog, setLinkDialog] = useState(null);
    const svgRef = useRef(null);

    const { data, isLoading, isError, error, refetch, isFetching } = useWorldVaultRelationships();
    const { data: savedLayout } = useGraphLayout('default');
    const saveLayout = useSaveGraphLayout();
    const deleteLayout = useDeleteGraphLayout();
    const { data: edgesData, isLoading: edgesLoading } = useGraphEdges();
    const createEdge = useCreateGraphEdge();
    const deleteEdge = useDeleteGraphEdge();

    const nodeRouteMap = useMemo(() => ({
        character: '/characters',
        story: '/story',
        chat: '/chat',
        lorebook: '/lorebooks',
        voice: '/voices',
        location: '/locations',
        scenario: '/scenarios',
    }), []);

    const handleNodeNavigate = useCallback((node, openPage = false) => {
        const base = nodeRouteMap[node.type];
        if (!base) return;
        if (openPage || (node.type !== 'story' && node.type !== 'chat')) {
            // A character node is a specific character, so it gets the same
            // `#char-<id>` deep link the World Timeline and Avatar Gallery use —
            // and that `Characters.jsx` already implements. Navigating to a bare
            // `/characters` opened the LIST, so the same affordance scrolled to
            // the character on two pages and dumped the user on an index on the
            // third.
            if (node.type === 'character' && node.id) {
                navigate(`${base}#char-${node.id}`);
            } else {
                navigate(base);
            }
        } else {
            navigate(`${base}/${node.id}`);
        }
        setSelectedNode(null);
    }, [navigate, nodeRouteMap]);

    const savedPositions = useMemo(() => {
        if (!savedLayout?.nodes) return null;
        const map = new Map();
        savedLayout.nodes.forEach(n => {
            map.set(n.entity_id, { x: n.x, y: n.y, vx: 0, vy: 0 });
        });
        return map;
    }, [savedLayout]);

    const { nodes, edges } = useMemo(() => {
        if (!data) return { nodes: [], edges: [] };
        const nodeMap = new Map();
        const edgeList = [];
        const edgeKey = (s, t, r) => `${s}→${t}::${r}`;
        const storedEdgeKeys = new Set();

        const addNode = (id, label, type, dangling = false) => {
            if (!nodeMap.has(id)) {
                nodeMap.set(id, { id, label, type, dangling });
            }
            return id;
        };

        const addEdge = (source, target, type, label = null, stored = false, id = null) => {
            const key = edgeKey(source, target, type);
            if (storedEdgeKeys.has(key)) return;
            edgeList.push({ source, target, type, label, stored, id });
            if (stored) storedEdgeKeys.add(key);
        };

        data.character_chats?.forEach(([charId, charName, chatId, chatName]) => {
            addNode(charId, charName, 'character');
            addNode(chatId, chatName, 'chat');
            addEdge(charId, chatId, 'character-chats');
        });

        data.character_stories?.forEach(({ character_id, character_name, story_id, story_title, dangling }) => {
            addNode(character_id, character_name, 'character', dangling);
            addNode(story_id, story_title, 'story');
            addEdge(character_id, story_id, 'character-stories');
        });

        data.story_lorebooks?.forEach(({ story_id, story_title, lorebook_id, lorebook_name, dangling }) => {
            addNode(story_id, story_title, 'story');
            addNode(lorebook_id, lorebook_name, 'lorebook', dangling);
            addEdge(story_id, lorebook_id, 'story-lorebooks');
        });

        data.chat_lorebooks?.forEach(({ chat_id, chat_title, lorebook_id, lorebook_name, dangling }) => {
            addNode(chat_id, chat_title, 'chat');
            addNode(lorebook_id, lorebook_name, 'lorebook', dangling);
            addEdge(chat_id, lorebook_id, 'chat-lorebooks');
        });

        data.character_lorebooks?.forEach(({ character_id, character_name, lorebook_id, lorebook_name, dangling }) => {
            addNode(character_id, character_name, 'character');
            addNode(lorebook_id, lorebook_name, 'lorebook', dangling);
            addEdge(character_id, lorebook_id, 'character-lorebooks');
        });

        data.character_voices?.forEach(([voiceId, voiceName, charId, charName]) => {
            addNode(voiceId, voiceName, 'voice');
            addNode(charId, charName, 'character');
            addEdge(charId, voiceId, 'character-voices');
        });

        data.chat_voices?.forEach(([voiceId, voiceName, chatId, chatName]) => {
            addNode(voiceId, voiceName, 'voice');
            addNode(chatId, chatName, 'chat');
            addEdge(chatId, voiceId, 'chat-voices');
        });

        data.story_locations?.forEach(({ story_id, story_title, location_id, location_name, dangling }) => {
            addNode(story_id, story_title, 'story');
            addNode(location_id, location_name, 'location', dangling);
            addEdge(story_id, location_id, 'story-locations');
        });

        data.chat_locations?.forEach(([chatId, chatName, locId, locName]) => {
            addNode(chatId, chatName, 'chat');
            addNode(locId, locName, 'location');
            addEdge(chatId, locId, 'chat-locations');
        });

        data.story_scenarios?.forEach(([storyId, storyTitle, scenarioId]) => {
            addNode(storyId, storyTitle, 'story');
            addNode(scenarioId, storyTitle, 'scenario');
            addEdge(storyId, scenarioId, 'story-scenarios');
        });

        data.chat_scenarios?.forEach(([chatId, chatName, scenarioId, scenarioTitle]) => {
            addNode(chatId, chatName, 'chat');
            addNode(scenarioId, scenarioTitle, 'scenario');
            addEdge(chatId, scenarioId, 'chat-scenarios');
        });

        // Stored (explicit) edges complement derived FK-based edges. A stored
        // edge with the same source+target+relation replaces its derived twin.
        (edgesData?.edges || []).forEach((e) => {
            addNode(e.source_entity_id, e.source_entity_id, e.source_entity_type);
            addNode(e.target_entity_id, e.target_entity_id, e.target_entity_type);
            addEdge(e.source_entity_id, e.target_entity_id, e.relation_type, e.label || null, true, e.id);
        });

        return { nodes: Array.from(nodeMap.values()), edges: edgeList };
    }, [data, edgesData]);

    const { positions, updatePosition } = useForceDirectedLayout(nodes, edges, 300, savedPositions);

    const filteredNodes = useMemo(() => {
        if (filter === 'all') return nodes;
        return nodes.filter(n => n.type === filter);
    }, [nodes, filter]);

    const filteredEdges = useMemo(() => {
        const nodeIds = new Set(filteredNodes.map(n => n.id));
        return edges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target));
    }, [edges, filteredNodes]);

    const handleSaveLayout = useCallback(() => {
        const nodesToSave = nodes.map(n => {
            const pos = positions.get(n.id);
            return {
                entity_type: n.type,
                entity_id: n.id,
                x: pos?.x ?? 0,
                y: pos?.y ?? 0,
            };
        });
        saveLayout.mutate({ name: 'default', nodes: nodesToSave }, {
            onSuccess: () => setHasUnsavedChanges(false),
        });
    }, [nodes, positions, saveLayout]);

    const handleResetLayout = useCallback(() => {
        // The button used to call `window.location.reload()`, which re-read the
        // saved layout and restored exactly what the user was trying to discard.
        // It now deletes it, and the layout re-runs force-directed because
        // `savedPositions` becomes null.
        deleteLayout.mutate(
            { name: 'default' },
            { onSuccess: () => { setHasUnsavedChanges(false); setSelectedNode(null); } },
        );
    }, [deleteLayout]);

    const handleMouseDown = useCallback((e, node) => {
        e.stopPropagation();
        setIsDragging(true);
        setDragNodeId(node.id);
        setSelectedNode(null);
    }, []);

    const handleMouseMove = useCallback((e) => {
        if (!isDragging || !dragNodeId || !svgRef.current) return;
        const svg = svgRef.current;
        const rect = svg.getBoundingClientRect();
        const scale = SVG_WIDTH / rect.width;
        const x = (e.clientX - rect.left) * scale;
        const y = (e.clientY - rect.top) * scale;
        updatePosition(dragNodeId, x, y);
        setHasUnsavedChanges(true);
    }, [isDragging, dragNodeId, updatePosition]);

    const handleMouseUp = useCallback(() => {
        setIsDragging(false);
        setDragNodeId(null);
    }, []);

    const handleNodeClick = useCallback((node) => {
        if (isDragging) return;
        if (linkingFrom) {
            if (linkingFrom.id === node.id) {
                setLinkingFrom(null);
                return;
            }
            setLinkDialog({ source: linkingFrom, target: node });
            setLinkingFrom(null);
            return;
        }
        setSelectedNode(prev => prev?.id === node.id ? null : node);
    }, [isDragging, linkingFrom]);

    const handleEdgeClick = useCallback((edge) => {
        if (!edge.stored || !edge.id) return;
        if (window.confirm(`Delete edge “${edge.label || edge.type}” (${edge.source} → ${edge.target})?`)) {
            deleteEdge.mutate({ edgeId: edge.id });
        }
    }, [deleteEdge]);

    useEffect(() => {
        if (isDragging) {
            window.addEventListener('mouseup', handleMouseUp);
            return () => window.removeEventListener('mouseup', handleMouseUp);
        }
    }, [isDragging, handleMouseUp]);

    if (isLoading || edgesLoading) {
        return (
            <div className="flex items-center justify-center h-64 text-gray-400">
                <RefreshCw className="animate-spin mr-2" size={20} />
                Loading relationships...
            </div>
        );
    }

    if (isError) {
        /* Detected the failure but rendered it as grey body text with no retry,
           while `refetch` was already destructured and used by the toolbar
           button two hundred lines below. */
        return <QueryErrorState noun="relationships" error={error} onRetry={() => refetch()} />;
    }

    return (
        <RoleplayPageShell
            title="Relationship Graph"
            description="Drag nodes to reposition. Click to select and edit. Save to persist layout."
            icon={Users}
            actions={
                <div className="flex items-center gap-2">
                    <select
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                        aria-label="Filter entities by type"
                        className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-cyan-300/50"
                    >
                        <option value="all">All Entities</option>
                        {Object.entries(NODE_LABELS).map(([type, label]) => (
                            <option key={type} value={type}>{label}</option>
                        ))}
                    </select>
                    <button
                        onClick={() => {
                            setLinkingFrom(null);
                            setLinkDialog(null);
                        }}
                        className={`rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm font-medium transition-colors ${linkingFrom ? 'bg-cyan-500/20 text-cyan-300' : 'text-slate-400 hover:bg-white/10 hover:text-white'}`}
                        title={linkingFrom ? 'Cancel link' : 'Link two nodes'}
                    >
                        <Link size={16} />
                        {linkingFrom ? 'Linking…' : 'Link'}
                    </button>
                    <button onClick={handleResetLayout} className="rounded-lg border border-white/10 bg-white/5 p-2 text-slate-400 transition hover:bg-white/10 hover:text-white" title="Reset layout">
                        <RotateCcw size={16} />
                    </button>
                    <button onClick={() => refetch()} className="rounded-lg border border-white/10 bg-white/5 p-2 text-slate-400 transition hover:bg-white/10 hover:text-white" title="Refresh">
                        <RefreshCw size={16} className={isFetching ? 'animate-spin' : ''} />
                    </button>
                    <button
                        onClick={handleSaveLayout}
                        disabled={!hasUnsavedChanges || saveLayout.isPending}
                        className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm transition-colors ${hasUnsavedChanges ? 'bg-cyan-500 text-slate-950 hover:bg-cyan-400' : 'cursor-not-allowed border border-white/10 bg-white/5 text-slate-500'}`}
                        title="Save layout"
                    >
                        <Save size={14} />
                        {saveLayout.isPending ? 'Saving...' : hasUnsavedChanges ? 'Save' : 'Saved'}
                    </button>
                </div>
            }
        >

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
                {hasUnsavedChanges && (
                    <div className="flex items-center gap-1.5 px-2.5 py-1 bg-yellow-500/10 border border-yellow-500/20 rounded-lg">
                        <span className="text-yellow-400">Unsaved changes</span>
                    </div>
                )}
            </div>

            {selectedNode && (
                <EditPanel
                    node={selectedNode}
                    onClose={() => setSelectedNode(null)}
                    onNavigate={handleNodeNavigate}
                />
            )}

            {linkDialog && (
                <LinkDialog
                    source={linkDialog.source}
                    target={linkDialog.target}
                    onClose={() => setLinkDialog(null)}
                    onCreate={createEdge.mutate}
                />
            )}

            {filteredNodes.length === 0 ? (
                <div className="text-center py-12 text-gray-400">
                    No relationships found. Create characters, stories, and chats to see connections.
                </div>
            ) : (
                <div className="bg-gray-800/40 border border-white/10 rounded-xl p-4 overflow-x-auto relative">
                    <TransformWrapper
                        initialScale={1}
                        minScale={0.1}
                        maxScale={4}
                        centerOnInit={true}
                    >
                        {({ zoomIn, zoomOut, resetTransform }) => (
                            <>
                                <div className="absolute top-2 right-2 flex flex-col gap-1 z-10">
                                    <button className="p-1.5 bg-gray-900 border border-white/10 rounded text-gray-400 hover:text-white" onClick={() => zoomIn()}>+</button>
                                    <button className="p-1.5 bg-gray-900 border border-white/10 rounded text-gray-400 hover:text-white" onClick={() => zoomOut()}>-</button>
                                    <button className="p-1.5 bg-gray-900 border border-white/10 rounded text-gray-400 hover:text-white" onClick={() => resetTransform()}>⟲</button>
                                </div>
                                <TransformComponent wrapperClass="w-full h-[600px] !block" contentClass="w-full h-full cursor-grab active:cursor-grabbing">
                                    <svg
                                        ref={svgRef}
                                        width={SVG_WIDTH}
                                        height={SVG_HEIGHT}
                                        className="mx-auto"
                                        style={{ overflow: 'visible' }}
                                        onMouseMove={handleMouseMove}
                                        onMouseUp={handleMouseUp}
                                        onMouseLeave={handleMouseUp}
                                    >
                                        <defs>
                                            <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="28" refY="3.5" orient="auto">
                                                <polygon points="0 0, 10 3.5, 0 7" fill="#4b5563" />
                                            </marker>
                                            <marker id="arrowhead-highlight" markerWidth="10" markerHeight="7" refX="28" refY="3.5" orient="auto">
                                                <polygon points="0 0, 10 3.5, 0 7" fill="#8b5cf6" />
                                            </marker>
                                        </defs>
                                        {filteredEdges.map((edge, idx) => {
                                            const sourcePos = positions.get(edge.source);
                                            const targetPos = positions.get(edge.target);
                                            if (!sourcePos || !targetPos) return null;
                                            const isHighlighted = selectedNode && (edge.source === selectedNode.id || edge.target === selectedNode.id);
                                            const isStored = edge.stored;
                                            const midX = (sourcePos.x + targetPos.x) / 2;
                                            const midY = (sourcePos.y + targetPos.y) / 2;
                                            return (
                                                <>
                                                    <line
                                                        key={`edge-${idx}`}
                                                        x1={sourcePos.x}
                                                        y1={sourcePos.y}
                                                        x2={targetPos.x}
                                                        y2={targetPos.y}
                                                        stroke={isStored ? '#8b5cf6' : isHighlighted ? '#8b5cf6' : '#4b5563'}
                                                        strokeWidth={isStored ? 2 : isHighlighted ? 2.5 : 1.5}
                                                        strokeDasharray={isStored ? null : '4 2'}
                                                        markerEnd={isStored || isHighlighted ? 'url(#arrowhead-highlight)' : 'url(#arrowhead)'}
                                                        opacity={selectedNode && !isHighlighted ? 0.3 : 1}
                                                        onClick={() => handleEdgeClick(edge)}
                                                        style={{ cursor: isStored ? 'pointer' : 'default' }}
                                                        title={isStored ? edge.label || edge.type : edge.type}
                                                    />
                                                    {isStored && edge.label && (
                                                        <text
                                                            x={midX}
                                                            y={midY - 4}
                                                            textAnchor="middle"
                                                            fontSize="10"
                                                            fill="#8b5cf6"
                                                            pointerEvents="none"
                                                        >
                                                            {edge.label}
                                                        </text>
                                                    )}
                                                </>
                                            );
                                        })}
                                        {filteredNodes.map((node) => {
                                            const Icon = NODE_ICONS[node.type] || Globe;
                                            const color = NODE_COLORS[node.type] || '#6b7280';
                                            const pos = positions.get(node.id);
                                            if (!pos) return null;
                                            const isSelected = selectedNode?.id === node.id;
                                            const isDimmed = selectedNode && !isSelected;
                                            return (
                                                <g
                                                    key={node.id}
                                                    transform={`translate(${pos.x}, ${pos.y})`}
                                                    style={{ cursor: isDragging && dragNodeId === node.id ? 'grabbing' : 'pointer' }}
                                                    onMouseDown={(e) => handleMouseDown(e, node)}
                                                    onClick={() => handleNodeClick(node)}
                                                >
                                                    <title>{node.label}{node.dangling ? ' (dangling)' : ''}</title>
                                                    {isSelected && (
                                                        <circle r={NODE_RADIUS + 6} fill="none" stroke={color} strokeWidth="2" opacity="0.6" />
                                                    )}
                                                    <circle r={NODE_RADIUS} fill={color} opacity={isDimmed ? 0.1 : 0.15} />
                                                    <circle r={14} fill={color} opacity={isDimmed ? 0.5 : 1} />
                                                    <foreignObject x="-8" y="-8" width="16" height="16">
                                                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '100%', height: '100%' }}>
                                                            <Icon size={12} color="white" />
                                                        </div>
                                                    </foreignObject>
                                                    <text
                                                        x="0"
                                                        y="30"
                                                        textAnchor="middle"
                                                        fill={isDimmed ? '#4b5563' : '#9ca3af'}
                                                        fontSize="10"
                                                        fontFamily="sans-serif"
                                                    >
                                                        {node.label}
                                                    </text>
                                                    {node.dangling && (
                                                        <circle r={4} cx={10} cy={-16} fill="#ef4444" />
                                                    )}
                                                </g>
                                            );
                                        })}
                                    </svg>
                                </TransformComponent>
                            </>
                        )}
                    </TransformWrapper>
                </div>
            )}
        </RoleplayPageShell>
    );
}
