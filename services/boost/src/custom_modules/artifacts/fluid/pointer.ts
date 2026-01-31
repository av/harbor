export class Pointer {
  id: number;
  texcoordX: number;
  texcoordY: number;
  prevTexcoordX: number;
  prevTexcoordY: number;
  deltaX: number;
  deltaY: number;
  down: boolean;
  moved: boolean;
  radius: number;
  color: {
    r: number;
    g: number;
    b: number;
  };

  constructor() {
    this.id = -1;
    this.texcoordX = 0;
    this.texcoordY = 0;
    this.prevTexcoordX = 0;
    this.prevTexcoordY = 0;
    this.deltaX = 0;
    this.deltaY = 0;
    this.down = false;
    this.moved = false;
    this.radius = 0.005;
    this.color = {
      r: 0.005,
      g: 0.005,
      b: 0.005,
    };
  }
}
