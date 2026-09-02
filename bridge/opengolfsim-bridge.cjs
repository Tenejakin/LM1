#!/usr/bin/env node

const net = require('node:net');
const { WebSocketServer } = require('ws');

const MAX_MESSAGE_BYTES = 64 * 1024;

function option(name, fallback) {
  const prefix = `--${name}=`;
  const argument = process.argv.slice(2).find((value) => value.startsWith(prefix));
  return argument ? argument.slice(prefix.length) : fallback;
}

const listenHost = option('listen-host', '0.0.0.0');
const listenPort = Number(option('listen-port', '3112'));
const ogsHost = option('ogs-host', '127.0.0.1');
const ogsPort = Number(option('ogs-port', '3111'));

if (!Number.isInteger(listenPort) || !Number.isInteger(ogsPort)) {
  throw new Error('Bridge ports must be whole numbers.');
}

const server = new WebSocketServer({ host: listenHost, port: listenPort, maxPayload: MAX_MESSAGE_BYTES });

server.on('connection', (webSocket) => {
  const tcpSocket = net.createConnection({ host: ogsHost, port: ogsPort });
  let buffer = '';

  const sendBridgeStatus = (status, message) => {
    if (webSocket.readyState === webSocket.OPEN) {
      webSocket.send(JSON.stringify({ type: 'bridge', status, ...(message ? { message } : {}) }));
    }
  };

  tcpSocket.setEncoding('utf8');
  tcpSocket.setNoDelay(true);

  tcpSocket.on('connect', () => sendBridgeStatus('connected'));
  tcpSocket.on('data', (chunk) => {
    buffer += chunk;
    let lineEnd = buffer.indexOf('\n');
    while (lineEnd >= 0) {
      const line = buffer.slice(0, lineEnd).trim();
      buffer = buffer.slice(lineEnd + 1);
      if (line && webSocket.readyState === webSocket.OPEN) webSocket.send(line);
      lineEnd = buffer.indexOf('\n');
    }
  });
  tcpSocket.on('error', (error) => {
    sendBridgeStatus('error', `OpenGolfSim TCP error: ${error.message}`);
    webSocket.close(1011, 'OpenGolfSim TCP connection failed');
  });
  tcpSocket.on('close', () => {
    if (webSocket.readyState === webSocket.OPEN) webSocket.close(1011, 'OpenGolfSim TCP connection closed');
  });

  webSocket.on('message', (data) => {
    const message = data.toString();
    try {
      JSON.parse(message);
    } catch {
      sendBridgeStatus('error', 'The app sent malformed JSON.');
      return;
    }

    if (tcpSocket.writable) tcpSocket.write(`${message.trim()}\n`);
  });
  webSocket.on('close', () => tcpSocket.destroy());
  webSocket.on('error', () => tcpSocket.destroy());
});

server.on('listening', () => {
  console.log(`Pinpoint OpenGolfSim bridge listening on ws://${listenHost}:${listenPort}`);
  console.log(`Forwarding to OpenGolfSim Desktop at ${ogsHost}:${ogsPort}`);
  console.log('Keep this terminal open while using the mobile app.');
});

server.on('error', (error) => {
  console.error(`Bridge failed: ${error.message}`);
  process.exitCode = 1;
});

function shutdown() {
  server.close(() => process.exit(0));
  for (const client of server.clients) client.terminate();
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
