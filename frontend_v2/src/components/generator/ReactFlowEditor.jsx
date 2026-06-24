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
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useObjectInfo } from '../../hooks/useObjectInfo';
import { NodeRegistry } from '../../utils/NodeRegistry';
import ComfyNode from './ComfyNode';
import NodeSidebar from './NodeSidebar';

const nodeTypes = {
  comfy: ComfyNode,
};

const initialNodes = [];
const initialEdges = [];

export default function ReactFlowEditor({ providerId, onGraphChange }) {
  const { data: objectInfo, isLoading, error } = useObjectInfo(providerId);
  const registry = useMemo(() => objectInfo ? new NodeRegistry(objectInfo) : null, [objectInfo]);
  
  const [nodes, setNodes] = useNodesState(initialNodes);
  const [edges, setEdges] = useEdgesState(initialEdges);

  const onConnect = useCallback(
    (params) => setEdges((eds) => addEdge(params, eds)),
    [setEdges],
  );

  // Notify parent of graph changes so it can compile to ComfyUI JSON
  React.useEffect(() => {
    if (onGraphChange) {
      onGraphChange(nodes, edges);
    }
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

      const position = {
        x: event.clientX - 200, // naive offset
        y: event.clientY - 100,
      };

      const newNode = {
        id: `node_${Date.now()}`,
        type: 'comfy',
        position,
        data: { 
          nodeType: type, 
          registry,
          // Widgets are initialized later
          widgets: {}
        },
      };

      setNodes((nds) => nds.concat(newNode));
    },
    [setNodes, registry],
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

  if (error) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-red-500/10 rounded-2xl border border-red-500/20">
        <p className="text-red-400 font-medium text-center">
          Failed to load node definitions.<br/>
          <span className="text-sm opacity-75">{error.message}</span>
        </p>
      </div>
    );
  }



  return (
    <div className="w-full h-full relative flex rounded-2xl overflow-hidden border border-white/10 shadow-2xl glass-panel">
      {/* Sidebar for Node Palette */}
      <NodeSidebar registry={registry} />

      <div className="flex-1 h-full relative" onDrop={onDrop} onDragOver={onDragOver}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={(changes) => setNodes((nds) => applyNodeChanges(changes, nds))}
          onEdgesChange={(changes) => setEdges((eds) => applyEdgeChanges(changes, eds))}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          fitView
          className="bg-[#0B0E14]"
          defaultEdgeOptions={{
            style: { strokeWidth: 3, stroke: '#3B82F6' },
            type: 'smoothstep'
          }}
        >
          <Background color="#ffffff" variant="dots" gap={20} size={1} opacity={0.05} />
          <Controls className="fill-white/70 bg-white/5 border-white/10" />
          <MiniMap 
            nodeColor={() => '#3B82F6'} 
            maskColor="rgba(11, 14, 20, 0.8)"
            className="bg-white/5 border border-white/10 rounded-xl overflow-hidden" 
          />
        </ReactFlow>
      </div>
    </div>
  );
}
