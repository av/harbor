import { Color } from "./color";
import { FluidSim } from "./fluid";
import { GraphVis } from "./graph";
import { BoostListener } from "./listener";
import { Pointer } from "./pointer";
import { lmap, rnd } from "./utils";
import { Point, Viewport } from "./viewport";

export class Visualisation {
  fluidSim: FluidSim;
  graph: GraphVis;
  listener: BoostListener;
  viewport: Viewport;

  constructor() {
    this.viewport = Viewport.fromWindow();

    this.fluidSim = new FluidSim();
    this.graph = new GraphVis();
    this.listener = new BoostListener();
  }

  async init() {
    this.fluidSim.init();
    this.graph.init();

    this.listener.on("boost.concept", ({ label, hex_color }) => {
      const node = this.graph.addNode(label);
      if (!node) return;

      node.color = new Color(0.001, 0.001, 0.001);

      try {
        node.color = Color.fromHex(hex_color).mute(0.002);
      } catch (e) {}
    });

    this.listener.on("boost.linked_concepts", ({ concepts }) => {
      this.graph.linkNodes(concepts[0], concepts[1]);
    });

    this.listener.on("boost.intensity", ({ intensity }) => {
      this.fluidSim.noiseSpeed = lmap(intensity, 0, 1, 0, 50);
    });

    this.listener.on("boost.status", ({ status }) => {
      Array.from(document.querySelectorAll(".status")).forEach((el, index) => {
        if (index === 0) {
          el.textContent = status;
        } else {
          el.remove();
        }
      });
    });

    this.graph.simulation.on("tick.pointers", () => {
      this.fluidSim.pointers = this.graph.nodes.map((n) => {
        const p = new Pointer();
        const position = this.viewport.toUnitCoords(new Point(n.x, n.y));
        let velocity = this.viewport.toUnitCoords(new Point(n.vx, n.vy)).multiply(3);

        // if (velocity.len() < 0.001) {
        //   velocity = Point.unitDirection(rnd(Math.PI, Math.PI * 2)).multiply(0.01);
        // }

        p.moved = true;
        p.texcoordX = position.x;
        p.texcoordY = 1.0 - position.y;
        p.deltaX = velocity.x;
        p.deltaY = -velocity.y;
        p.color = n.highlighted ? n.color.toGlColor() : p.color;
        p.radius = 0.003;

        return p;
      });
    });

    await this.listener.listen();
  }
}
