// Perplexica (andypenno fork) WebSocket search round trip.
// Usage: node perplexica-search.mjs <ws_base_url> <chat_model> <embedding_model> <query>
// Connects with model params in the query string (connectionManager.js),
// sends a focusMode=webSearch message and prints the streamed reply.
// Exits 0 iff a non-empty reply was received before messageEnd.
const [wsBase, chatModel, embeddingModel, ...q] = process.argv.slice(2);
const query = q.join(' ') || 'What is Docker Compose?';
const params = new URLSearchParams({
  chatModel,
  chatModelProvider: 'ollama',
  embeddingModel,
  embeddingModelProvider: 'ollama',
});
const ws = new WebSocket(`${wsBase}/?${params}`);
let reply = '';
let sources = 0;
const bail = (msg) => { console.error(msg); process.exit(1); };
const timer = setTimeout(() => bail(`timeout; partial reply: ${reply.slice(0, 200)}`), 240000);
ws.onopen = () => {
  ws.send(JSON.stringify({
    type: 'message',
    message: {
      messageId: `harbor-it-${Date.now()}`,
      chatId: `harbor-it-chat-${Date.now()}`,
      content: query,
    },
    focusMode: 'webSearch',
    history: [],
  }));
};
ws.onmessage = (ev) => {
  let data;
  try { data = JSON.parse(ev.data); } catch { return; }
  if (data.type === 'error') bail(`backend error: ${data.data}`);
  if (data.type === 'sources') sources = (data.data || []).length;
  if (data.type === 'message') reply += data.data || '';
  if (data.type === 'messageEnd') {
    clearTimeout(timer);
    console.log(JSON.stringify({ sources, reply: reply.slice(0, 400) }));
    process.exit(reply.trim().length > 0 ? 0 : 1);
  }
};
ws.onerror = () => bail('websocket error');
