const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const net = require('node:net');
const path = require('node:path');
const { WebSocket } = require('ws');

function waitForMessage(socket, predicate, timeoutMs = 5_000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Timed out waiting for WebSocket message.')), timeoutMs);
    const listener = (data) => {
      const message = JSON.parse(data.toString());
      if (!predicate(message)) return;
      clearTimeout(timer);
      socket.off('message', listener);
      resolve(message);
    };
    socket.on('message', listener);
  });
}

async function main() {
  const tcpServer = net.createServer();
  await new Promise((resolve) => tcpServer.listen(0, '127.0.0.1', resolve));
  const tcpPort = tcpServer.address().port;
  const probe = net.createServer();
  await new Promise((resolve) => probe.listen(0, '127.0.0.1', resolve));
  const bridgePort = probe.address().port;
  await new Promise((resolve) => probe.close(resolve));

  let receivedShot;
  tcpServer.on('connection', (socket) => {
    let buffer = '';
    socket.setEncoding('utf8');
    socket.on('error', () => {});
    socket.on('data', (chunk) => {
      buffer += chunk;
      const end = buffer.indexOf('\n');
      if (end < 0) return;
      receivedShot = JSON.parse(buffer.slice(0, end));
      socket.write(`${JSON.stringify({
        type: 'result',
        data: { result: { carry: 123, height: 20, roll: 7, total: 130, lateral: -2 } },
      })}\n`);
    });
  });

  const bridge = spawn(
    process.execPath,
    [
      path.join(__dirname, '..', 'bridge', 'opengolfsim-bridge.cjs'),
      '--listen-host=127.0.0.1',
      `--listen-port=${bridgePort}`,
      '--ogs-host=127.0.0.1',
      `--ogs-port=${tcpPort}`,
    ],
    { stdio: ['ignore', 'pipe', 'pipe'] },
  );

  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Bridge did not start.')), 5_000);
      bridge.stdout.on('data', (data) => {
        if (!data.toString().includes('bridge listening')) return;
        clearTimeout(timer);
        resolve();
      });
      bridge.once('exit', (code) => reject(new Error(`Bridge exited early with code ${code}.`)));
    });

    const socket = new WebSocket(`ws://127.0.0.1:${bridgePort}`);
    const connectedPromise = waitForMessage(socket, (message) => message.type === 'bridge');
    await new Promise((resolve, reject) => {
      socket.once('open', resolve);
      socket.once('error', reject);
    });
    const connected = await connectedPromise;
    assert.equal(connected.status, 'connected');

    const resultPromise = waitForMessage(socket, (message) => message.type === 'result');
    const shot = {
      type: 'shot',
      unit: 'metric',
      shot: { ballSpeed: 44.704, verticalLaunchAngle: 15.4, horizontalLaunchAngle: -2.1, spinSpeed: 3021, spinAxis: -0.5 },
    };
    socket.send(JSON.stringify(shot));
    const result = await resultPromise;

    assert.deepEqual(receivedShot, shot);
    assert.equal(result.data.result.total, 130);
    socket.close();
    console.log('OpenGolfSim bridge integration test passed.');
  } finally {
    bridge.kill();
    await new Promise((resolve) => tcpServer.close(resolve));
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
