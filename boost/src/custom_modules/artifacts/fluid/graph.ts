// d3 is available globally via CDN import

import { config } from "./config";
import { rnd } from "./utils";
import { Color } from './color';

interface GraphNode {
  id: string;
  label: string;
  x: number;
  y: number;
  fx?: number | null;
  fy?: number | null;
  vx?: number;
  vy?: number;
  highlighted?: boolean;
  color: Color;
}

interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
}

export class GraphVis {
  svg: any;
  simulation: any;
  link: any;
  node: any;
  width: number;
  height: number;
  container: any;
  linksGroup: any;
  nodesGroup: any;
  nodes: GraphNode[] = [];
  links: GraphLink[] = [];
  initialConcepts: Record<string, string[]> = {};

  constructor(initialConcepts: Record<string, string[]> = {}) {
    this.initialConcepts = initialConcepts;
  }

  init() {
    this.svg = d3
      .select("body")
      .append("svg")
      .attr("width", "100%")
      .attr("height", "100%");
    const zoom = d3
      .zoom()
      .scaleExtent([0.1, 4])
      .on("zoom", (event) => {
        this.container.attr("transform", event.transform);
      });

    if (config.GRAPH_ZOOM) {
      this.svg.call(zoom);
    }
    this.container = this.svg.append("g").attr("class", "container");
    this.linksGroup = this.container.append("g").attr("class", "links");
    this.nodesGroup = this.container.append("g").attr("class", "nodes");
    const defs = this.svg.append("defs");
    const glow = defs
      .append("filter")
      .attr("id", "glow")
      .attr("x", "-50%")
      .attr("y", "-50%")
      .attr("width", "200%")
      .attr("height", "200%");
    const glowStronger = defs
      .append("filter")
      .attr("id", "glowStronger")
      .attr("x", "-50%")
      .attr("y", "-50%")
      .attr("width", "200%")
      .attr("height", "200%");
    glow
      .append("feGaussianBlur")
      .attr("stdDeviation", "2")
      .attr("result", "coloredBlur");
    const feMerge = glow.append("feMerge");
    feMerge.append("feMergeNode").attr("in", "coloredBlur");
    feMerge.append("feMergeNode").attr("in", "SourceGraphic");
    glowStronger
      .append("feGaussianBlur")
      .attr("stdDeviation", "6")
      .attr("result", "coloredBlur");
    const feMergeStronger = glowStronger.append("feMerge");
    feMergeStronger.append("feMergeNode").attr("in", "coloredBlur");
    feMergeStronger.append("feMergeNode").attr("in", "SourceGraphic");
    this.updateDimensions();
    this.simulation = d3
      .forceSimulation()
      .alphaDecay(0.0)
      .force(
        "link",
        d3
          .forceLink()
          .id((d) => d.id)
          .distance(120)
          .strength(0.01)
      )
      .force("charge", d3.forceManyBody().strength(-80))
      .force("x", d3.forceX(this.width / 2).strength(0.01))
      .force("y", d3.forceY(this.height / 2).strength(0.01))
      .force("collide", d3.forceCollide().radius(config.GRAPH_TEXT_SIZE * 2));

    this.simulation.on("tick", () => this.ticked());
    this.populateInitialData();
    window.addEventListener("resize", () => {
      this.updateDimensions();
      this.simulation.force("x", d3.forceX(this.width / 2).strength(0.01));
      this.simulation.force("y", d3.forceY(this.height / 2).strength(0.01));
      this.simulation.alpha(1.0).restart();
    });
  }

  updateDimensions() {
    this.width = window.innerWidth;
    this.height = window.innerHeight;
    this.svg.attr("width", this.width).attr("height", this.height);
  }

  populateInitialData() {
    Object.values(this.initialConcepts).forEach((concepts) => {
      concepts.forEach((concept) => {
        this.addNode(concept);
      });
    });
  }

  addNode(label: string) {
    if (this.nodes.find((n) => n.id === label)) {
      console.log(`Node ${label} already exists`);
      return;
    }

    const newNode: GraphNode = {
      id: label,
      label: label,
      x: this.width / 2,
      y: 0,
      vx: rnd(-10, 10),
      vy: 100,
    };
    this.nodes.push(newNode);
    this.updateVisualization();
    return newNode;
  }

  linkNodes(fromLabel: string, toLabel: string) {
    const fromNode = this.nodes.find((n) => n.id === fromLabel);
    const toNode = this.nodes.find((n) => n.id === toLabel);

    if (!fromNode || !toNode) {
      throw new Error(
        `Cannot link: one or both nodes don't exist (${fromLabel}, ${toLabel})`
      );
    }

    if (
      this.links.some(
        (l) =>
          (l.source === fromLabel && l.target === toLabel) ||
          (l.source === toLabel && l.target === fromLabel)
      )
    ) {
      console.log(`Link between ${fromLabel} and ${toLabel} already exists`);
      return;
    }

    const newLink: GraphLink = {
      source: fromLabel,
      target: toLabel,
    };

    this.links.push(newLink);
    fromNode.highlighted = true;
    toNode.highlighted = true;
    this.updateVisualization();

    return newLink;
  }

  updateVisualization() {
    this.link = this.linksGroup
      .selectAll("line")
      .data(
        this.links,
        (d) => `${d.source.id || d.source}-${d.target.id || d.target}`
      );
    this.link.exit().remove();
    const linkEnter = this.link
      .enter()
      .append("line")
      .attr("class", "link")
      .attr("stroke", "#999")
      .attr("stroke-width", 2);
    this.link = linkEnter.merge(this.link);
    this.node = this.nodesGroup
      .selectAll(".node")
      .data(this.nodes, (d) => d.id);
    this.node.exit().remove();
    const nodeEnter = this.node.enter().append("g").attr("class", "node");

    if (config.NODES_DRAGGABLE) {
      nodeEnter.call(this.drag(this.simulation));
    }

    const fontSize = config.GRAPH_TEXT_SIZE;
    const rectSize = {
      width: (d) => d.label.length * (fontSize / 2) + fontSize * 2,
      height: (d) => fontSize * 2,
    };

    nodeEnter
      .append("rect")
      .attr("x", (d) => -rectSize.width(d) / 2)
      .attr("y", (d) => -rectSize.height(d) / 2)
      .attr("width", (d) => rectSize.width(d))
      .attr("height", (d) => rectSize.height(d))
      .attr("rx", (d) => rectSize.height(d) / 2)
      .attr("ry", (d) => rectSize.height(d) / 2)
      .style("fill", "#dedede") // always relevant_concepts color
      .style("stroke", "#e5e7eb")
      .style("stroke-width", 2)
      .style("filter", "url(#glow)")
      .attr("transform", "scale(0)")
      .transition()
      .duration(600)
      .ease(d3.easeElastic.period(0.75))
      .attr("transform", "scale(1)");
    nodeEnter
      .append("text")
      .attr("dy", fontSize / 3)
      .attr("text-anchor", "middle")
      .text((d) => d.label)
      .style("fill", "#2d2d2d")
      .style("font-weight", "600")
      .style("font-size", `${fontSize}px`)
      .style("text-shadow", "0 2px 4px rgba(0,0,0,0.3)")
      .attr("transform", "scale(0)")
      .transition()
      .duration(600)
      .ease(d3.easeElastic.period(0.75))
      .attr("transform", "scale(1)");
    this.node = nodeEnter.merge(this.node);
    this.simulation.nodes(this.nodes);
    this.simulation.force("link").links(this.links);
    this.simulation.alpha(1.0).restart();
    this.nodesGroup.raise();
  }

  drag(simulation: any) {
    const self = this;
    function dragstarted(event: any) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      event.subject.fx = event.subject.x;
      event.subject.fy = event.subject.y;
    }
    function dragged(event: any) {
      event.subject.fx = event.x;
      event.subject.fy = event.y;
    }
    function dragended(event: any) {
      if (!event.active) simulation.alphaTarget(0);
      event.subject.fx = null;
      event.subject.fy = null;
    }
    return d3
      .drag()
      .on("start", dragstarted)
      .on("drag", dragged)
      .on("end", dragended);
  }

  ticked() {
    this.container
      .selectAll(".link")
      .attr("x1", (d) => d.source.x)
      .attr("y1", (d) => d.source.y)
      .attr("x2", (d) => d.target.x)
      .attr("y2", (d) => d.target.y);
    this.container
      .selectAll(".node")
      .attr("transform", (d) => `translate(${d.x}, ${d.y})`);
  }
}
