import React from "react";

interface SliderProps {
  min: number;
  max: number;
  value: number;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

export const Slider = ({ min, max, value, onChange }: SliderProps) => {
  // Raw 0–1 ratio; the CSS calc() uses this to position the gradient stop at
  // the thumb center, accounting for the thumb's half-width offset.
  const ratio = (value - min) / (max - min);

  return (
    <input
      type="range"
      min={min}
      max={max}
      value={value}
      className="harbor-slider"
      style={{ "--slider-fill-ratio": ratio } as React.CSSProperties}
      onChange={onChange}
    />
  );
};
