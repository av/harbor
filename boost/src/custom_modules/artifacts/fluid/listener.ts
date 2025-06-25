import { sleep } from './utils';

export class BoostListener {
  listeners: Record<string, Function[]>;

  constructor() {
    this.listeners = {};
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

  processChunk(chunk) {
    try {
      const data = JSON.parse(chunk.replace(/data: /, ""));
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
      const boostUrl = "<<boost_public_url>>";

      const response = await fetch(
        `${boostUrl}/events/${listenerId}`,
        {
          headers: {
            Authorization: "Bearer sk-boost",
          },
        }
      );

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body.getReader();

      async function consume() {
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            console.log("Stream complete");
            break;
          }

          try {
            const blob = new TextDecoder().decode(value);
            const chunks = blob.split("\n\n");

            for (const chunk of chunks) {
              if (chunk.trim()) {
                this.processChunk(chunk);
              }
            }
          } catch (e) {
            console.error("Error processing data:", e);
          }

          await sleep(10);
        }
      }

      await consume.call(this);
    } catch (error) {
      console.error("Error connecting to event stream:", error);
    }
  }
}
