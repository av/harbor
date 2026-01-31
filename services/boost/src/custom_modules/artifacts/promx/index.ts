import { BoostListener } from './listener';

const listener = new BoostListener();
const canvas = document.getElementById('moodCanvas');
const ctx = canvas.getContext('2d');
const valueListElement = document.getElementById('emotionValueList');

const CONSTANTS = {
  HANDLE_RADIUS: 10,
  EMOTION_ICON_RADIUS: 15,
  ICON_FONT_BASE_SIZE: 20,
  ICON_FONT_SCALE_MAX_ADDITION: 20,
  PLACEMENT_RADIUS_FACTOR: 0.7,
  INFLUENCE_RADIUS_FACTOR: 0.35,
  LERP_SPEED: 0.02,
  POSITION_LERP_SPEED: 0.12,
  MIN_DELTA: 0.001,
  PAUSE_ICON: 'https://unpkg.com/lucide-static@latest/icons/pause.svg',
  PLAY_ICON: 'https://unpkg.com/lucide-static@latest/icons/play.svg',
  SLOW_ICON: 'https://unpkg.com/lucide-static@latest/icons/snail.svg',
  FAST_ICON: 'https://unpkg.com/lucide-static@latest/icons/rabbit.svg',
};

const emotions = [
  { name: "Happiness", icon: "😄", color: "#FFD700", isNeutral: false },
  { name: "Love", icon: "❤️", color: "#FF69B4", isNeutral: false },
  { name: "Desire", icon: "🔥", color: "#FF4500", isNeutral: false },
  { name: "Surprise", icon: "😲", color: "#FFFF00", isNeutral: false },
  { name: "Confusion", icon: "😕", color: "#D3D3D3", isNeutral: false },
  { name: "Sarcasm", icon: "😏", color: "#008080", isNeutral: false },
  { name: "Anger", icon: "😠", color: "#DC143C", isNeutral: false },
  { name: "Disgust", icon: "🤢", color: "#556B2F", isNeutral: false },
  { name: "Fear", icon: "😱", color: "#800080", isNeutral: false },
  { name: "Sadness", icon: "😢", color: "#1E90FF", isNeutral: false },
  { name: "Guilt", icon: "😔", color: "#6A5ACD", isNeutral: false },
  { name: "Shame", icon: "🙈", color: "#A0522D", isNeutral: false },
  { name: "Neutral", icon: "😐", color: "#808080", isNeutral: true }
];

let state = {
  handlePos: { x: 0, y: 0 },
  targetHandlePos: { x: 0, y: 0 },
  isDraggingHandle: false,
  draggedEmotion: null,
  dragOffset: { x: 0, y: 0 },
  smoothedEmotionValues: {},
  lastUpdateTime: 0,
  paused: false,
  speed: 'slow',
  deltaTime: 0,
};

const emotionAnchors = [];
function resizeCanvas() {
  const container = document.getElementById('controllerContainer');
  canvas.width = container.clientWidth;
  canvas.height = container.clientHeight;
}

function getCenterX() { return canvas.width / 2; }
function getCenterY() { return canvas.height / 2; }

function lerp(start, end, factor) {
  return start + (end - start) * factor;
}

function calculateDistance(p1, p2) {
  return Math.sqrt(Math.pow(p1.x - p2.x, 2) + Math.pow(p1.y - p2.y, 2));
}

function getMousePos(event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top
  };
}
function setupEmotionAnchors() {
  emotionAnchors.length = 0;
  const nonNeutralEmotions = emotions.filter(e => !e.isNeutral);
  const currentCenterX = getCenterX();
  const currentCenterY = getCenterY();
  const placementRadius = Math.min(currentCenterX, currentCenterY) * CONSTANTS.PLACEMENT_RADIUS_FACTOR;
  const influenceRadius = Math.min(canvas.width, canvas.height) * CONSTANTS.INFLUENCE_RADIUS_FACTOR;

  let nonNeutralIndex = 0;
  emotions.forEach((emotion) => {
    let x, y;
    if (emotion.isNeutral) {
      x = currentCenterX;
      y = currentCenterY;
    } else {
      const angle = (nonNeutralIndex / nonNeutralEmotions.length) * 2 * Math.PI;
      x = currentCenterX + placementRadius * Math.cos(angle);
      y = currentCenterY + placementRadius * Math.sin(angle);
      nonNeutralIndex++;
    }

    emotionAnchors.push({
      ...emotion,
      x: x,
      y: y,
      targetX: x,
      targetY: y,
      displayX: x,
      displayY: y,
      D_influence: influenceRadius
    });
  });
}
function calculateEmotionValues() {
  const currentValues = {};
  const handlePosition = state.isDraggingHandle ? state.targetHandlePos : state.handlePos;

  emotionAnchors.forEach(anchor => {
    const anchorPosition = (state.draggedEmotion === anchor && anchor.targetX !== undefined && anchor.targetY !== undefined)
      ? { x: anchor.targetX, y: anchor.targetY }
      : { x: anchor.x, y: anchor.y };

    const dist = calculateDistance(handlePosition, anchorPosition);

    if (dist <= CONSTANTS.EMOTION_ICON_RADIUS) {
      currentValues[anchor.name] = 1.0;
    } else if (dist <= anchor.D_influence) {
      const normalizedDist = (dist - CONSTANTS.EMOTION_ICON_RADIUS) / (anchor.D_influence - CONSTANTS.EMOTION_ICON_RADIUS);
      const value = 1 - normalizedDist;
      currentValues[anchor.name] = Math.max(0, value);
    } else {
      currentValues[anchor.name] = 0;
    }
  });
  return currentValues;
}

function updateValueDisplay(values) {
  valueListElement.innerHTML = '';
  emotions.forEach(emotion => {
    const value = values[emotion.name] || 0;
    const listItem = document.createElement('li');
    listItem.classList.add('emotion-value-item');
    const barColor = emotion.isNeutral ? emotion.color : (emotionAnchors.find(a => a.name === emotion.name)?.color || '#4CAF50');
    listItem.innerHTML = `
          <span class="emotion-icon">${emotion.icon}</span>
          <span class="emotion-name">${emotion.name}</span>
          <div class="emotion-bar-container">
            <div class="emotion-bar" style="width: ${value * 100}%; background-color: ${barColor};"></div>
          </div>
          <span class="emotion-value-text">${value.toFixed(2)}</span>
        `;
    valueListElement.appendChild(listItem);
  });
}

function draw(currentEmotionValues) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  drawBackground(ctx, canvas);

  emotionAnchors.forEach(anchor => {
    const value = currentEmotionValues ? (currentEmotionValues[anchor.name] || 0) : 0;
    const dynamicFontSize = CONSTANTS.ICON_FONT_BASE_SIZE + (value * CONSTANTS.ICON_FONT_SCALE_MAX_ADDITION);
    const dynamicBgRadius = CONSTANTS.EMOTION_ICON_RADIUS + (value * CONSTANTS.EMOTION_ICON_RADIUS * 1.2);

    const baseOpacity = state.draggedEmotion === anchor ? 0.7 : 0.4;
    const dynamicOpacity = Math.min(0.9, baseOpacity + (value * 0.5));

    // Convert hex color to RGB and adjust saturation based on value
    const hexToRgb = (hex) => {
      const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
      return result ? {
        r: parseInt(result[1], 16),
        g: parseInt(result[2], 16),
        b: parseInt(result[3], 16)
      } : null;
    };

    const rgb = hexToRgb(anchor.color);
    if (rgb) {
      // Adjust saturation based on emotion value
      const saturationFactor = value; // 0 = completely desaturated, 1 = full saturation
      const gray = (rgb.r + rgb.g + rgb.b) / 3;
      const adjustedR = gray + (rgb.r - gray) * saturationFactor;
      const adjustedG = gray + (rgb.g - gray) * saturationFactor;
      const adjustedB = gray + (rgb.b - gray) * saturationFactor;

      ctx.fillStyle = `rgba(${Math.round(adjustedR)}, ${Math.round(adjustedG)}, ${Math.round(adjustedB)}, ${dynamicOpacity})`;
    }

    ctx.beginPath();
    ctx.arc(anchor.displayX, anchor.displayY, dynamicBgRadius, 0, 2 * Math.PI);
    ctx.fill();

    // Add strong layered glow effect
    if (value > 0.05) {
      // Outer glow layer - strongest and largest
      ctx.shadowColor = anchor.color;
      ctx.shadowBlur = 40 * value * value; // Quadratic scaling for dramatic effect
      ctx.fill();

      // Middle glow layer - medium intensity
      ctx.shadowBlur = 25 * value;
      ctx.fill();

      // Inner glow layer - sharp and bright
      ctx.shadowBlur = 12 * value;
      ctx.fill();

      // Reset shadow
      ctx.shadowBlur = 0;
      ctx.shadowColor = 'transparent';
    }

    // Draw the emoji with saturation effect
    ctx.font = `${dynamicFontSize}px Arial`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    // Apply saturation filter to the emoji based on value (0% to 120%)
    const saturationPercent = Math.round(value * 120);
    ctx.filter = `saturate(${saturationPercent}%)`;

    // Add text shadow for better visibility
    ctx.shadowColor = 'rgba(0, 0, 0, 0.8)';
    ctx.shadowBlur = 3;
    ctx.shadowOffsetX = 1;
    ctx.shadowOffsetY = 1;
    ctx.fillStyle = '#ffffff';
    ctx.fillText(anchor.icon, anchor.displayX, anchor.displayY + 2);

    // Reset filter and shadow
    ctx.filter = 'none';
    ctx.shadowColor = 'transparent';
    ctx.shadowBlur = 0;
    ctx.shadowOffsetX = 0;
    ctx.shadowOffsetY = 0;
  });

  if (state.handlePos.x === undefined || state.handlePos.y === undefined) {
    state.handlePos = { x: getCenterX(), y: getCenterY() };
  }

  ctx.beginPath();
  ctx.arc(state.handlePos.x, state.handlePos.y, CONSTANTS.HANDLE_RADIUS, 0, 2 * Math.PI);

  // Flat color for the handle
  ctx.fillStyle = 'rgba(100, 200, 255, 0.9)';
  ctx.fill();

  // Add outer glow
  ctx.shadowColor = 'rgba(100, 200, 255, 0.5)';
  ctx.shadowBlur = 15;
  ctx.fill();
  ctx.shadowBlur = 0;

  // Add border
  ctx.strokeStyle = 'rgba(150, 220, 255, 0.9)';
  ctx.lineWidth = 2;
  ctx.stroke();
}

function random(min, max) {
  if (max === undefined) {
    max = min;
    min = 0;
  }

  return Math.random() * (max - min) + min;
}

function randomInt(min, max) {
  return Math.floor(random(min, max));
}



function initBackground() {
  if (!window.stars) {
    window.stars = [];
    for (let i = 0; i < 150; i++) {
      window.stars.push({
        x: random(0, canvas.width),
        y: random(0, canvas.height),
        size: random(0.5, 3),
        speedX: random(-20, 20),
        speedY: random(-20, 20),
        brightness: random(0.2, 0.4),
        hue: random(0, 360),
        phase: random(0, Math.PI * 2)
      });
    }
  }
  if (!window.nebulae) {
    window.nebulae = [];
    for (let i = 0; i < 5; i++) {
      window.nebulae.push({
        x: random(0, canvas.width),
        y: random(0, canvas.height),
        radius: random(500, 1500),
        color: `hsl(${random(0, 360)}, 70%, 30%)`,
        opacity: random(0.1, 0.3),
        angle: random(0, Math.PI * 2),
        orbitRadius: random(canvas.width, canvas.width * 2),
        orbitSpeed: random(0.001, 0.002),
        centerX: random(0, canvas.width),
        centerY: random(0, canvas.height)
      });
    }
  }
}

function drawBackground(ctx, canvas) {
  const nebulae = window.nebulae || [];
  for (let nebula of nebulae) {
    ctx.beginPath();
    nebula.x = nebula.centerX + Math.cos(nebula.angle) * nebula.orbitRadius;
    nebula.y = nebula.centerY + Math.sin(nebula.angle) * nebula.orbitRadius;
    nebula.angle += nebula.orbitSpeed;
    ctx.arc(nebula.x, nebula.y, nebula.radius, 0, Math.PI * 2);
    const gradient = ctx.createRadialGradient(nebula.x, nebula.y, 0, nebula.x, nebula.y, nebula.radius);
    gradient.addColorStop(0, `${nebula.color.slice(0, -1)}, ${nebula.opacity * 2})`);
    gradient.addColorStop(1, `${nebula.color.slice(0, -1)}, 0)`);
    ctx.fillStyle = gradient;
    ctx.fill();
  }

  const stars = window.stars || [];
  const dt = state.deltaTime || 0;
  for (let star of stars) {
    star.brightness = 0.35 * Math.sin(Date.now() * 0.001 + star.phase);
    ctx.fillStyle = `hsla(${star.hue}, 50%, 90%, ${star.brightness})`;
    ctx.beginPath();
    ctx.arc(star.x, star.y, star.size, 0, Math.PI * 2);
    ctx.fill();
    star.x += star.speedX * dt;
    star.y += star.speedY * dt;
    if (star.x > canvas.width) star.x = 0;
    if (star.x < 0) star.x = canvas.width;
    if (star.y > canvas.height) star.y = 0;
    if (star.y < 0) star.y = canvas.height;
    if (star.x === 0 || star.y === 0 || star.x === canvas.width || star.y === canvas.height) {
      star.hue = Math.random() * 360;
    }
  }
}



function handleMouseDown(e) {
  const mousePos = getMousePos(e);

  for (let i = emotionAnchors.length - 1; i >= 0; i--) {
    const anchor = emotionAnchors[i];
    const distToAnchor = calculateDistance(mousePos, { x: anchor.displayX, y: anchor.displayY });
    if (distToAnchor <= CONSTANTS.EMOTION_ICON_RADIUS) {
      state.draggedEmotion = anchor;
      state.dragOffset.x = mousePos.x - anchor.displayX;
      state.dragOffset.y = mousePos.y - anchor.displayY;
      state.isDraggingHandle = false;
      canvas.style.cursor = 'grabbing';
      return;
    }
  }

  const distToHandle = calculateDistance(mousePos, state.handlePos);
  if (distToHandle <= CONSTANTS.HANDLE_RADIUS) {
    state.isDraggingHandle = true;
    state.draggedEmotion = null;
    state.dragOffset.x = mousePos.x - state.handlePos.x;
    state.dragOffset.y = mousePos.y - state.handlePos.y;
    canvas.style.cursor = 'grabbing';
  } else {
    state.isDraggingHandle = true;
    state.draggedEmotion = null;
    state.handlePos.x = mousePos.x;
    state.handlePos.y = mousePos.y;
    state.targetHandlePos.x = mousePos.x;
    state.targetHandlePos.y = mousePos.y;
    state.dragOffset.x = 0;
    state.dragOffset.y = 0;
    canvas.style.cursor = 'grabbing';
  }
}

function handleMouseMove(e) {
  const mousePos = getMousePos(e);

  if (state.draggedEmotion) {
    const targetX = mousePos.x - state.dragOffset.x;
    const targetY = mousePos.y - state.dragOffset.y;
    const clampedX = Math.max(CONSTANTS.EMOTION_ICON_RADIUS, Math.min(canvas.width - CONSTANTS.EMOTION_ICON_RADIUS, targetX));
    const clampedY = Math.max(CONSTANTS.EMOTION_ICON_RADIUS, Math.min(canvas.height - CONSTANTS.EMOTION_ICON_RADIUS, targetY));

    if (!state.draggedEmotion.targetX) state.draggedEmotion.targetX = state.draggedEmotion.x;
    if (!state.draggedEmotion.targetY) state.draggedEmotion.targetY = state.draggedEmotion.y;

    state.draggedEmotion.targetX = clampedX;
    state.draggedEmotion.targetY = clampedY;
    canvas.style.cursor = 'grabbing';

    const currentValues = calculateEmotionValues();
    updateValueDisplay(currentValues);
  } else if (state.isDraggingHandle) {
    const newX = mousePos.x - state.dragOffset.x;
    const newY = mousePos.y - state.dragOffset.y;
    const clampedX = Math.max(CONSTANTS.HANDLE_RADIUS, Math.min(canvas.width - CONSTANTS.HANDLE_RADIUS, newX));
    const clampedY = Math.max(CONSTANTS.HANDLE_RADIUS, Math.min(canvas.height - CONSTANTS.HANDLE_RADIUS, newY));
    state.targetHandlePos.x = clampedX;
    state.targetHandlePos.y = clampedY;
    canvas.style.cursor = 'grabbing';

    const currentValues = calculateEmotionValues();
    updateValueDisplay(currentValues);
  } else {
    let onInteractiveElement = false;
    for (const anchor of emotionAnchors) {
      if (calculateDistance(mousePos, { x: anchor.displayX, y: anchor.displayY }) <= CONSTANTS.EMOTION_ICON_RADIUS) {
        canvas.style.cursor = 'grab';
        onInteractiveElement = true;
        break;
      }
    }
    if (!onInteractiveElement && calculateDistance(mousePos, state.handlePos) <= CONSTANTS.HANDLE_RADIUS) {
      canvas.style.cursor = 'grab';
      onInteractiveElement = true;
    }
    if (!onInteractiveElement) {
      canvas.style.cursor = 'pointer';
    }
  }
}

function handleMouseUp() {
  state.isDraggingHandle = false;
  state.draggedEmotion = null;
  canvas.style.cursor = 'pointer';
  updateAndDraw();
}

function updateAndDraw() {
  const currentValues = calculateEmotionValues();
  updateValueDisplay(currentValues);
  draw(currentValues);
}

function handleResize() {
  resizeCanvas();
  setupEmotionAnchors();

  // Find the neutral emotion anchor and position handle there
  const neutralAnchor = emotionAnchors.find(anchor => anchor.isNeutral);
  if (neutralAnchor) {
    state.handlePos = { x: neutralAnchor.x, y: neutralAnchor.y };
    state.targetHandlePos = { x: neutralAnchor.x, y: neutralAnchor.y };
  } else {
    const newCenterX = getCenterX();
    const newCenterY = getCenterY();
    state.handlePos = { x: newCenterX, y: newCenterY };
    state.targetHandlePos = { x: newCenterX, y: newCenterY };
  }

  state.smoothedEmotionValues = calculateEmotionValues();
  updateAndDraw();
}

function updateLoop(currentTime) {
  const deltaTime = currentTime - state.lastUpdateTime;
  state.deltaTime = deltaTime / 1000;
  state.lastUpdateTime = currentTime;
  let needsUpdate = false;

  const handleDistX = Math.abs(state.handlePos.x - state.targetHandlePos.x);
  const handleDistY = Math.abs(state.handlePos.y - state.targetHandlePos.y);
  if (handleDistX > CONSTANTS.MIN_DELTA || handleDistY > CONSTANTS.MIN_DELTA) {
    state.handlePos.x = lerp(state.handlePos.x, state.targetHandlePos.x, CONSTANTS.POSITION_LERP_SPEED);
    state.handlePos.y = lerp(state.handlePos.y, state.targetHandlePos.y, CONSTANTS.POSITION_LERP_SPEED);
    needsUpdate = true;
  }

  emotionAnchors.forEach(anchor => {
    if (anchor.targetX !== undefined && anchor.targetY !== undefined) {
      const distX = Math.abs(anchor.x - anchor.targetX);
      const distY = Math.abs(anchor.y - anchor.targetY);
      if (distX > CONSTANTS.MIN_DELTA || distY > CONSTANTS.MIN_DELTA) {
        anchor.x = lerp(anchor.x, anchor.targetX, CONSTANTS.POSITION_LERP_SPEED);
        anchor.y = lerp(anchor.y, anchor.targetY, CONSTANTS.POSITION_LERP_SPEED);
        needsUpdate = true;
      }
    }

    const displayDistX = Math.abs(anchor.displayX - anchor.x);
    const displayDistY = Math.abs(anchor.displayY - anchor.y);
    if (displayDistX > CONSTANTS.MIN_DELTA || displayDistY > CONSTANTS.MIN_DELTA) {
      anchor.displayX = lerp(anchor.displayX, anchor.x, CONSTANTS.POSITION_LERP_SPEED);
      anchor.displayY = lerp(anchor.displayY, anchor.y, CONSTANTS.POSITION_LERP_SPEED);
      needsUpdate = true;
    }
  });

  const currentEmotionValues = calculateEmotionValues();
  const targetEmotionValues = calculateEmotionValues();
  let emotionChanged = false;
  for (const emotionName in targetEmotionValues) {
    const target = targetEmotionValues[emotionName];
    const current = state.smoothedEmotionValues[emotionName] || 0;
    if (Math.abs(current - target) > CONSTANTS.MIN_DELTA) {
      state.smoothedEmotionValues[emotionName] = lerp(current, target, CONSTANTS.LERP_SPEED);
      emotionChanged = true;
    } else {
      state.smoothedEmotionValues[emotionName] = target;
    }
  }

  if (emotionChanged || needsUpdate || state.isDraggingHandle || state.draggedEmotion) {
    updateValueDisplay(currentEmotionValues);
  }

  draw(state.smoothedEmotionValues);
  requestAnimationFrame(updateLoop);
}

function serializeEmotionValues() {
  const currentValues = calculateEmotionValues();
  return JSON.stringify(
    Object.fromEntries(
      Object.entries(currentValues).map(([key, value]) => [key, parseFloat(value.toFixed(2))])
    )
  );
}

canvas.addEventListener('mousedown', handleMouseDown);
canvas.addEventListener('mousemove', handleMouseMove);
canvas.addEventListener('mouseup', handleMouseUp);
window.addEventListener('resize', handleResize);

async function init() {
  resizeCanvas();
  setupEmotionAnchors();

  // Find the neutral emotion anchor and position handle there
  const neutralAnchor = emotionAnchors.find(anchor => anchor.isNeutral);
  if (neutralAnchor) {
    state.handlePos = { x: neutralAnchor.x, y: neutralAnchor.y };
    state.targetHandlePos = { x: neutralAnchor.x, y: neutralAnchor.y };
  } else {
    state.handlePos = { x: getCenterX(), y: getCenterY() };
    state.targetHandlePos = { x: state.handlePos.x, y: state.handlePos.y };
  }

  emotionAnchors.forEach(anchor => {
    anchor.targetX = anchor.x;
    anchor.targetY = anchor.y;
    anchor.displayX = anchor.x;
    anchor.displayY = anchor.y;
  });

  state.smoothedEmotionValues = calculateEmotionValues();
  updateAndDraw();
  state.lastUpdateTime = performance.now();
  requestAnimationFrame(updateLoop);

  const playPause = document.querySelector('.boost-control.play-pause');

  playPause.addEventListener('click', () => {
    if (state.paused) {
      state.paused = false;
      playPause?.firstChild?.setAttribute('src', CONSTANTS.PAUSE_ICON);
      listener.send({ event: 'boost.resume' });
    } else {
      state.paused = true;
      playPause?.firstChild?.setAttribute('src', CONSTANTS.PLAY_ICON);
      listener.send({ event: 'boost.pause' });
    }
  });

  const speed = document.querySelector('.boost-control.speed');
  speed.addEventListener('click', () => {
    if (state.speed === 'slow') {
      state.speed = 'fast';
      speed?.firstChild?.setAttribute('src', CONSTANTS.FAST_ICON);
      listener.send({ event: 'boost.speed', data: 'fast' });
    } else {
      state.speed = 'slow';
      speed?.firstChild?.setAttribute('src', CONSTANTS.SLOW_ICON);
      listener.send({ event: 'boost.speed', data: 'slow' });
    }
  });

  const connectionIndicator = document.querySelector('.connection-indicator');

  listener.on('boost.status', ({ status }) => {
    Array.from(document.querySelectorAll('.boost-status')).forEach((el, index) => {
      if (index === 0) {
        el.textContent = status;
      } else {
        el.remove();
      }
    });
  });

  listener.on('local.open', () => {
    connectionIndicator.classList.add('connected');
    connectionIndicator.classList.remove('disconnected');
  })

  listener.on('local.close', () => {
    connectionIndicator.classList.remove('connected');
    connectionIndicator.classList.add('disconnected');
  });

  listener.on('local.error', () => {
    connectionIndicator.classList.remove('connected');
    connectionIndicator.classList.add('disconnected');
  });

  let lastSentState = serializeEmotionValues();
  setInterval(() => {
    const currentState = serializeEmotionValues();

    if (currentState !== lastSentState) {
      listener.send({
        event: 'boost.emotion_values',
        data: JSON.parse(currentState)
      });

      lastSentState = currentState;
    }
  }, 100)

  await listener.listen();
  requestAnimationFrame(() => {
    handleResize();
    initBackground();
  });
}

init().catch(console.error);
