const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

async function main() {
  let receive;
  const events = [];
  const capture = { id: 'capture-123', classification: 'unconfirmed-departure', image: { mimeType: 'image/jpeg', base64: 'anBlZw==' }, warnings: ['No physical measurements'] };
  const send = (message) => {
    const wire = `${JSON.stringify(message)}\n`;
    for (let i = 0; i < wire.length; i += 7) receive(wire.slice(i, i + 7));
  };
  const exports = {};
  const source = ts.transpileModule(fs.readFileSync('src/services/device.ts', 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  vm.runInNewContext(source, {
    exports, setTimeout, clearTimeout,
    require(name) {
      assert.equal(name, '@/services/bleTransport');
      return { async connectBle(id, handler) {
        receive = handler;
        return { id: 'test', mtu: 247, disconnect() {}, async write(wire) {
          const request = JSON.parse(wire);
          if (request.type === 'status') assert.equal(request.mtu, 247);
          send({ type: 'response', id: request.id, data: request.type === 'status'
            ? { state: 'ready', protocolVersion: '2.13.0', automaticCapture: true }
            : [capture] });
        } };
      } };
    },
  });
  const client = new exports.DeviceClient();
  await client.connect(undefined, (event) => events.push(event), () => {});
  send({ type: 'ballPresence', data: { present: true } });
  send({ type: 'processing', data: { progress: 1 } });
  send({ type: 'capture', data: capture });
  send({ type: 'error', message: 'Capture unavailable' });
  assert.equal(events[2].data.id, capture.id);
  assert.equal(events[2].data.image.base64, capture.image.base64);
  assert.equal(events[3].type, 'captureError');
  assert.equal(events[3].data.message, 'Capture unavailable');
  assert.equal((await client.listCaptures())[0].id, capture.id);
  assert.equal(events.some((event) => event.type === 'shot'), false);
  client.disconnect();
  console.log('Capture client fragmented-BLE integration test passed.');
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
