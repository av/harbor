export class Color {
  r: number;
  g: number;
  b: number;

  static fromHex(hex: string): Color {
    if (!/^#([0-9A-F]{3}){1,2}$/i.test(hex)) {
      throw new Error("Invalid hex color format");
    }
    const bigint = parseInt(hex.slice(1), 16);
    const r = (bigint >> 16) & 255;
    const g = (bigint >> 8) & 255;
    const b = bigint & 255;
    return new Color(r / 255, g / 255, b / 255);
  }

  static fromRgb(r: number, g: number, b: number): Color {
    return new Color(r / 255, g / 255, b / 255);
  }

  constructor(r: number, g: number, b: number) {
    this.r = r;
    this.g = g;
    this.b = b;
  }

  mute(factor: number): Color {
    return new Color(
      this.r * factor,
      this.g * factor,
      this.b * factor,
    )
  }

  toGlColor(): { r: number; g: number; b: number } {
    return {
      r: this.r,
      g: this.g,
      b: this.b,
    };
  }
}
