import { lmap, rnd } from './utils';

export class Point {
  x: number;
  y: number;

  static random(rect: Rect): Point {
    return new Point(
      rnd(rect.x, rect.x + rect.width),
      rnd(rect.y, rect.y + rect.height),
    );
  }

  static unitDirection(angle: number): Point {
    return new Point(Math.cos(angle), Math.sin(angle));
  }

  constructor(x: number = 0, y: number = 0) {
    this.x = x;
    this.y = y;
  }

  set(x: number, y: number): Point {
    this.x = x;
    this.y = y;
    return this;
  }

  len(): number {
    return Math.sqrt(this.x * this.x + this.y * this.y);
  }

  copy(): Point {
    return new Point(this.x, this.y);
  }

  multiply(scalar: number): Point {
    return new Point(this.x * scalar, this.y * scalar);
  }

  add(point: Point): Point {
    return new Point(this.x + point.x, this.y + point.y);
  }
}

export class Rect {
  x: number;
  y: number;
  width: number;
  height: number;

  static fromDOMNode(node: HTMLElement): Rect {
    const rect = node.getBoundingClientRect();
    return new Rect(rect.left, rect.top, rect.width, rect.height);
  }

  constructor(x: number = 0, y: number = 0, width: number = 0, height: number = 0) {
    this.x = x;
    this.y = y;
    this.width = width;
    this.height = height;
  }

  set(x: number, y: number, width: number, height: number): Rect {
    this.x = x;
    this.y = y;
    this.width = width;
    this.height = height;
    return this;
  }

  copy(): Rect {
    return new Rect(this.x, this.y, this.width, this.height);
  }

  get center(): Point {
    return new Point(this.x + this.width / 2, this.y + this.height / 2);
  }

  get aspectRatio(): number {
    return this.width / this.height;
  }

  contains(point: Point): boolean {
    return (
      point.x >= this.x &&
      point.x <= this.x + this.width &&
      point.y >= this.y &&
      point.y <= this.y + this.height
    );
  }

  intersects(rect: Rect): boolean {
    return !(
      rect.x > this.x + this.width ||
      rect.x + rect.width < this.x ||
      rect.y > this.y + this.height ||
      rect.y + rect.height < this.y
    );
  }

  union(rect: Rect): Rect {
    const x = Math.min(this.x, rect.x);
    const y = Math.min(this.y, rect.y);
    const width = Math.max(this.x + this.width, rect.x + rect.width) - x;
    const height = Math.max(this.y + this.height, rect.y + rect.height) - y;
    return new Rect(x, y, width, height);
  }

  scale(factor: number): Rect {
    this.x *= factor;
    this.y *= factor;
    this.width *= factor;
    this.height *= factor;
    return this;
  }

  translate(dx: number, dy: number): Rect {
    this.x += dx;
    this.y += dy;
    return this;
  }

  toString(): string {
    return `Rect(${this.x}, ${this.y}, ${this.width}, ${this.height})`;
  }
}

export class Viewport extends Rect {
  static fromWindow(): Viewport {
    const viewport = new Viewport(window.innerWidth, window.innerHeight);

    window.addEventListener('resize', () => {
      viewport.set(0, 0, window.innerWidth, window.innerHeight);
    });

    return viewport;
  }

  constructor(width: number = 800, height: number = 600) {
    super(0, 0, width, height);
  }

  toUnitCoords(point: Point): Point {
    return new Point(
      lmap(point.x, this.x, this.x + this.width, 0, 1),
      lmap(point.y, this.y, this.y + this.height, 0, 1)
    );
  }
}