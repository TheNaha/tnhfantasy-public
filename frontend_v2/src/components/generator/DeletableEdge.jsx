import React from 'react';
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, useReactFlow } from '@xyflow/react';
import { X } from 'lucide-react';

export default function DeletableEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
}) {
  const { setEdges } = useReactFlow();
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const onEdgeClick = (evt, id) => {
    evt.stopPropagation();
    setEdges((edges) => edges.filter((e) => e.id !== id));
  };

  return (
    <>
      <BaseEdge path={edgePath} markerEnd={markerEnd} style={style} />
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: 'all',
          }}
          className="nodrag nopan group"
        >
          <button
            className="w-5 h-5 bg-gray-900 border border-gray-700 rounded-full flex items-center justify-center text-gray-500 hover:text-red-400 hover:border-red-500 hover:bg-gray-800 transition-colors cursor-pointer shadow-md opacity-60 hover:opacity-100"
            onClick={(event) => onEdgeClick(event, id)}
            title="Remove Connection"
          >
            <X size={12} strokeWidth={3} />
          </button>
        </div>
      </EdgeLabelRenderer>
    </>
  );
}
