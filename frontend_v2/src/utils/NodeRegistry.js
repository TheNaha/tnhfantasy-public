export class NodeRegistry {
    constructor(objectInfo) {
        this.objectInfo = objectInfo || {};
        // Group nodes by category for the sidebar
        this.categories = {};
        
        for (const [nodeType, def] of Object.entries(this.objectInfo)) {
            const category = def.category || 'unknown';
            if (!this.categories[category]) {
                this.categories[category] = [];
            }
            this.categories[category].push({
                type: nodeType,
                ...def
            });
        }
    }

    getNodeDef(nodeType) {
        return this.objectInfo[nodeType];
    }

    getInputs(nodeType) {
        const def = this.getNodeDef(nodeType);
        if (!def || !def.input) return { required: {}, optional: {} };
        return {
            required: def.input.required || {},
            optional: def.input.optional || {}
        };
    }

    getOutputs(nodeType) {
        const def = this.getNodeDef(nodeType);
        if (!def || !def.output) return [];
        return def.output.map((type, idx) => ({
            type,
            name: def.output_name ? def.output_name[idx] || type : type
        }));
    }

    getCategories() {
        return this.categories;
    }
}
