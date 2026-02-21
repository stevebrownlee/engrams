// Engrams Knowledge Graph Visualization (D3.js v7)

const NODE_COLORS = {
    decision: '#4A90D9',
    system_pattern: '#5CB85C',
    progress: '#F0AD4E',
    custom_data: '#999999',
};

const NODE_SHAPES = {
    decision: 'circle',
    system_pattern: 'rect',
    progress: 'diamond',
    custom_data: 'circle',
};

const NODE_SIZES = {
    decision: 8,
    system_pattern: 10,
    progress: 7,
    custom_data: 6,
};

let currentSimulation = null;

function renderGraph(data) {
    const container = document.getElementById('graph-container');
    if (!container || !data) return;

    // Clear previous
    container.innerHTML = '';
    if (currentSimulation) {
        currentSimulation.stop();
        currentSimulation = null;
    }

    if (!data.nodes || data.nodes.length === 0) {
        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#a0a0b0;">No graph data available</div>';
        return;
    }

    const width = container.clientWidth;
    const height = container.clientHeight;

    const svg = d3.select(container)
        .append('svg')
        .attr('width', width)
        .attr('height', height);

    // Zoom behavior
    const g = svg.append('g');
    const zoom = d3.zoom()
        .scaleExtent([0.1, 4])
        .on('zoom', (event) => g.attr('transform', event.transform));
    svg.call(zoom);

    // Create simulation
    const simulation = d3.forceSimulation(data.nodes)
        .force('link', d3.forceLink(data.edges)
            .id(d => d.id)
            .distance(80))
        .force('charge', d3.forceManyBody().strength(-200))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(20));

    currentSimulation = simulation;

    // Draw edges
    const link = g.append('g')
        .selectAll('line')
        .data(data.edges)
        .join('line')
        .attr('stroke', '#2a2a4a')
        .attr('stroke-opacity', 0.6)
        .attr('stroke-width', 1.5);

    // Edge labels
    const linkLabel = g.append('g')
        .selectAll('text')
        .data(data.edges)
        .join('text')
        .text(d => d.relationship || '')
        .attr('font-size', '8px')
        .attr('fill', '#666')
        .attr('text-anchor', 'middle');

    // Draw nodes
    const node = g.append('g')
        .selectAll('g')
        .data(data.nodes)
        .join('g')
        .call(d3.drag()
            .on('start', dragStarted)
            .on('drag', dragged)
            .on('end', dragEnded));

    // Node shapes
    node.each(function(d) {
        const el = d3.select(this);
        const color = NODE_COLORS[d.type] || '#999';
        const size = NODE_SIZES[d.type] || 8;

        if (NODE_SHAPES[d.type] === 'rect') {
            el.append('rect')
                .attr('width', size * 2)
                .attr('height', size * 2)
                .attr('x', -size)
                .attr('y', -size)
                .attr('rx', 3)
                .attr('fill', color)
                .attr('stroke', '#fff')
                .attr('stroke-width', 1.5);
        } else if (NODE_SHAPES[d.type] === 'diamond') {
            el.append('polygon')
                .attr('points', `0,${-size} ${size},0 0,${size} ${-size},0`)
                .attr('fill', color)
                .attr('stroke', '#fff')
                .attr('stroke-width', 1.5);
        } else {
            el.append('circle')
                .attr('r', size)
                .attr('fill', color)
                .attr('stroke', '#fff')
                .attr('stroke-width', 1.5);
        }
    });

    // Node labels
    node.append('text')
        .text(d => d.label || d.id)
        .attr('dx', 14)
        .attr('dy', 4)
        .attr('font-size', '10px')
        .attr('fill', '#e0e0e0');

    // Tooltip on hover
    node.append('title')
        .text(d => `${d.type}: ${d.label || d.id}`);

    // Highlight on hover
    node.on('mouseover', function() {
        d3.select(this).select('circle, rect, polygon').attr('stroke-width', 3);
    }).on('mouseout', function() {
        d3.select(this).select('circle, rect, polygon').attr('stroke-width', 1.5);
    });

    // Tick
    simulation.on('tick', () => {
        link
            .attr('x1', d => d.source.x)
            .attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x)
            .attr('y2', d => d.target.y);

        linkLabel
            .attr('x', d => (d.source.x + d.target.x) / 2)
            .attr('y', d => (d.source.y + d.target.y) / 2);

        node.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    // Drag handlers
    function dragStarted(event, d) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
    }

    function dragged(event, d) {
        d.fx = event.x;
        d.fy = event.y;
    }

    function dragEnded(event, d) {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
    }
}
