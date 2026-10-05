import React, { useCallback, useMemo } from 'react';
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  Panel,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useObjectInfo } from '../../hooks/useObjectInfo';
import { NodeRegistry } from '../../utils/NodeRegistry';
import { PRESET_WORKFLOWS } from '../../utils/presets';
import ComfyNode from './ComfyNode';
import DeletableEdge from './DeletableEdge';
import NodeSidebar from './NodeSidebar';
import RegistryContext from './RegistryContext';

const nodeTypes = {
  comfy: ComfyNode,
};

const edgeTypes = {
  deletable: DeletableEdge,
};



export default function ReactFlowEditor({ providerId, onGraphChange }) {
  const { data: objectInfo, isLoading, error, isStale, staleData, refetch, isFetching } = useObjectInfo(providerId);
  // A failed load with a cached payload attached: render the stale nodes so the
  // editor stays usable, but never as if they were current. `useObjectInfo`
  // used to return that cache from `queryFn`, which React Query records as a
  // SUCCESS — so `error` was always undefined here and the palette rendered
  // from a possibly-days-old IndexedDB copy with no banner and no retry.
  const displayObjectInfo = error ? staleData : objectInfo;
  const registry = useMemo(() => displayObjectInfo ? new NodeRegistry(displayObjectInfo) : null, [displayObjectInfo]);
  
  // Load initial state from local storage
  const [initialNodes, initialEdges] = useMemo(() => {
    try {
      const saved = localStorage.getItem('tnh-comfy-workflow');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed.nodes && parsed.edges) return [parsed.nodes, parsed.edges];
      }
    } catch (e) {
      console.warn("Failed to parse saved workflow", e);
    }
    return [[], []];
  }, []);

  const [nodes, setNodes] = useNodesState(initialNodes);
  const [edges, setEdges] = useEdgesState(initialEdges);
  const [reactFlowInstance, setReactFlowInstance] = React.useState(null);

  const onConnect = useCallback(
    (params) => setEdges((eds) => addEdge(params, eds)),
    [setEdges],
  );

  // Notify parent of graph changes and save to local storage
  React.useEffect(() => {
    if (onGraphChange) {
      onGraphChange(nodes, edges);
    }
    localStorage.setItem('tnh-comfy-workflow', JSON.stringify({ nodes, edges }));
  }, [nodes, edges, onGraphChange]);

  // Define drag and drop handlers for a sidebar (Phase 4.3)
  const onDragOver = useCallback((event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (event) => {
      event.preventDefault();
      const type = event.dataTransfer.getData('application/reactflow');
      if (!type) return;
      if (!reactFlowInstance) return;

      const position = reactFlowInstance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      const newNode = {
        id: `node_${Date.now()}`,
        type: 'comfy',
        position,
        data: { 
          nodeType: type, 
          widgets: {}
        },
      };

      setNodes((nds) => nds.concat(newNode));
    },
    [setNodes, reactFlowInstance],
  );

  if (isLoading) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-black/50 rounded-2xl border border-white/5">
        <div className="flex flex-col items-center gap-4">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
          <p className="text-gray-400 font-medium">Fetching node definitions from provider...</p>
        </div>
      </div>
    );
  }

  if (error && !isStale) {
    // No cached payload to fall back on: there is nothing to show, so this is
    // the honest state — a failure, with the retry that `useObjectInfo` now
    // refetches on rather than the user having to clear IndexedDB by hand.
    return (
      <div className="w-full h-full flex flex-col items-center justify-center gap-4 bg-red-500/10 rounded-2xl border border-red-500/20">
        <p className="text-red-400 font-medium text-center">
          Failed to load node definitions.<br/>
          <span className="text-sm opacity-75">{error.message}</span>
        </p>
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          className="inline-flex items-center gap-2 px-3 py-1.5 bg-red-500/20 border border-red-500/40 text-red-200 text-sm font-medium rounded-lg hover:bg-red-500/30 transition-colors disabled:opacity-50"
        >
          {isFetching ? 'Retrying…' : 'Try again'}
        </button>
      </div>
    );
  }



  return (
    <RegistryContext.Provider value={registry}>
      {/* The stale banner. The palette below is usable but may not match the
          provider's current node set, and the user is the only one who can
          decide whether that matters for the graph they are about to run. */}
      {isStale && (
        <div role="alert" className="flex flex-wrap items-center gap-3 px-4 py-2 bg-amber-500/10 border-b border-amber-500/30 text-amber-200 text-sm">
          <span>
            Showing the last saved node list — the provider could not be reached.
          </span>
          <span className="text-amber-200/70 text-xs">{error?.message}</span>
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="ml-auto inline-flex items-center gap-2 px-3 py-1 bg-amber-500/20 border border-amber-500/40 text-amber-100 text-xs font-medium rounded-lg hover:bg-amber-500/30 transition-colors disabled:opacity-50"
          >
            {isFetching ? 'Retrying…' : 'Retry'}
          </button>
        </div>
      )}
      {/* `flex-col` below `sm`, not `flex`. This is the actual cause of the
          54px canvas at 360: the sidebar is `w-full`, and inside a *row* a
          `w-full` flex item's basis is the whole container, so the canvas's
          `basis-0 grow` had zero free space to grow into and measured 0px wide.
          Stacking the palette above the graph on a phone gives the canvas the
          full width, which is the only arrangement that works when the two
          cannot both be side by side. */}
      <div className="w-full h-full relative flex flex-col sm:flex-row rounded-2xl overflow-hidden border border-white/10 shadow-2xl glass-panel">
        {/* Sidebar for Node Palette */}
        <NodeSidebar registry={registry} />

        {/* `min-w-0` so the canvas keeps a floor the sidebar cannot eat, and
            `basis-0 grow` so it claims the remaining row rather than being
            measured against its content. Without it the flex item's automatic
            minimum size is the widest node, which is how a 54px canvas
            happened. */}
        <div className="flex-1 min-w-0 basis-0 grow h-full relative" onDrop={onDrop} onDragOver={onDragOver}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={(changes) => setNodes((nds) => applyNodeChanges(changes, nds))}
            onEdgesChange={(changes) => setEdges((eds) => applyEdgeChanges(changes, eds))}
            onConnect={onConnect}
            onInit={setReactFlowInstance}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            className="bg-[#0B0E14]"
            defaultEdgeOptions={{
              type: 'deletable',
              style: { strokeWidth: 3, stroke: '#3B82F6' },
            }}
          >
            <Panel position="top-right" className="bg-gray-900/80 backdrop-blur-md border border-gray-700 p-2 rounded-xl flex gap-2">
              <select 
                className="bg-gray-800 text-sm text-gray-200 border border-gray-600 rounded px-2 py-1 outline-none"
                onChange={(e) => {
                  const preset = PRESET_WORKFLOWS[e.target.value];
                  if (preset) {
                    setNodes(preset.nodes);
                    setEdges(preset.edges);
                  }
                  e.target.value = "";
                }}
                defaultValue=""
              >
                <option value="" disabled>Load Preset...</option>
                {Object.keys(PRESET_WORKFLOWS).map(k => (
                  <option key={k} value={k}>{PRESET_WORKFLOWS[k].name}</option>
                ))}
              </select>
            </Panel>
            <Background color="#ffffff" variant="dots" gap={20} size={1} opacity={0.05} />
            <Controls className="fill-white/70 bg-white/5 border-white/10" />
            <MiniMap 
              nodeColor={() => '#3B82F6'} 
              maskColor="rgba(11, 14, 20, 0.8)"
              className="border border-white/10 rounded-xl overflow-hidden" 
              style={{ backgroundColor: '#111827' }}
            />
          </ReactFlow>
        </div>
      </div>
    </RegistryContext.Provider>
  );
}
