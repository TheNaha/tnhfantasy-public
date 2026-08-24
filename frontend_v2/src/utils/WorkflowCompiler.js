function coerceWidget(value) {
    if (typeof value === 'string') {
        const trimmed = value.trim();
        if (trimmed !== '' && !isNaN(Number(trimmed))) {
            return Number(trimmed);
        }
    }
    return value;
}

export function compileReactFlowToComfy(nodes, edges) {
    const workflow = {};

    // First pass: create all node stubs
    for (const node of nodes) {
        const widgets = node.data.widgets ?? {};
        const coerced = {};
        for (const [k, v] of Object.entries(widgets)) {
            coerced[k] = coerceWidget(v);
        }
        workflow[node.id] = {
            inputs: coerced,
            class_type: node.data.nodeType,
            _meta: {
                title: node.data.nodeType
            }
        };
    }

    // Second pass: wire up the edges
    // In ReactFlow:
    // edge.source = source node ID
    // edge.sourceHandle = output index (as string)
    // edge.target = target node ID
    // edge.targetHandle = input name
    for (const edge of edges) {
        const targetNode = workflow[edge.target];
        if (targetNode) {
            // ComfyUI expects: "input_name": ["source_node_id", output_index_as_int]
            targetNode.inputs[edge.targetHandle] = [
                edge.source,
                parseInt(edge.sourceHandle || '0', 10)
            ];
        }
    }

    return workflow;
}
