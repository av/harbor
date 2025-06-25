import { sleep } from './utils';

export class BoostListener {
  listeners: Record<string, Function[]>;
  websocket: WebSocket | null;

  constructor() {
    this.listeners = {};
    this.websocket = null;
  }

  on(event, callback) {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(callback);
  }
  off(event, callback) {
    if (this.listeners[event]) {
      this.listeners[event] = this.listeners[event].filter(
        (listener) => listener !== callback
      );
    }
  }

  emit(event, data) {
    if (this.listeners[event]) {
      this.listeners[event].forEach((callback) => callback(data));
    }
  }

  send(data) {
    if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
      this.websocket.send(JSON.stringify(data));
    } else {
      console.error("WebSocket is not open. Cannot send data.");
    }
  }

  processChunk(chunk) {
    try {
      const data = chunk;
      const text = data.object;

      if (text === "boost.listener.event") {
        return this.handleBoostEvent(data);
      }

      this.emit(text, data);
    } catch (e) {
      console.error("Error processing chunk:", e);
    }
  }

  handleBoostEvent(chunk) {
    const { event, data } = chunk;
    this.emit(event, data);
  }

  getChunkContent(chunk) {
    return chunk.choices.map((choice) => choice.delta.content).join("\n");
  }

  async listen() {
    try {
      const listenerId = "<<listener_id>>";
      const boostUrl = "<<boost_public_url>>".replace('http://', 'ws://').replace('https://', 'wss://');
      this.websocket = new WebSocket(
        `${boostUrl}/events/${listenerId}/ws`,
        [],
      );

      this.websocket.onopen = () => {
        this.emit('local.open', {})
      };

      this.websocket.onmessage = (event) => {
        const chunk = event.data;
        const parsed = JSON.parse(chunk);
        this.processChunk(parsed);
      };

      this.websocket.onclose = () => {
        this.emit('local.close', {});
      };

      this.websocket.onerror = (error) => {
        this.emit('local.error', { error });
      };
    } catch (error) {
      console.error("Error connecting to event stream:", error);
    }
  }
}
