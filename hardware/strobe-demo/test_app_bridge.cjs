// App bridge validation 0.2.0: actual Pi payloads plus resolved metric forwarding.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
function load(path, requireFn) {
  const exports = {};
  const code = ts.transpileModule(fs.readFileSync(path, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  vm.runInNewContext(code, { exports, require: requireFn });
  return exports;
}
const flight = load('src/utils/flight.ts', () => ({}));
const carry = load('src/utils/carry.ts', name => {
  if (name === '@/utils/flight') return flight;
  assert.equal(name, '@/data/clubs');
  return { isClubId: id => id === 'lob-wedge', getClub: () => ({id:'lob-wedge',typicalSpinRpm:10000}) };
});
const captures = JSON.parse(fs.readFileSync(process.argv[2] || 'output/app-bridge-captures-v0.1.0.json'));
assert.equal(captures.length, 10);
captures.forEach((capture, index) => {
  const shot = carry.estimateShotFromCapture(capture, 'lob-wedge', index+1);
  assert.ok(shot, `${capture.id} must register in the app`);
  assert.equal(shot.id, capture.id);
  assert.equal(shot.ballSpeedMps, capture.measurements.metrics.ballSpeedMps.value);
  assert.equal(shot.launchAngleDeg, capture.measurements.metrics.launchAngleDeg.value);
  assert.equal(shot.clubSpeedMps, null);
  assert.equal(shot.attackAngleDeg ?? null, null);
  assert.equal(shot.metricConfidence.startDirectionDeg.confidence, .05);
  assert.match(shot.metricConfidence.startDirectionDeg.reason, /unmeasured/);
  assert.equal(shot.measurementSource, 'camera-estimate');
  assert.ok(Number.isFinite(shot.estimatedCarryM));
});
const failed = JSON.parse(JSON.stringify(captures[0]));
failed.measurements.metrics.ballSpeedMps.value = null;
assert.equal(carry.estimateShotFromCapture(failed, 'lob-wedge', 1), null);
console.log('PASS: 10 real strobe captures register as app shots; missing tracking does not invent a shot.');
const stereo = JSON.parse(JSON.stringify(captures[0]));
const values = {clubSpeedMps:5,smashFactor:1.2,attackAngleDeg:-4,clubPathDeg:-2.5,startDirectionDeg:3.2};
for (const [key,value] of Object.entries(values)) {
  stereo.measurements.metrics[key]={value,unit:'deg',status:'estimated',reason:'Provisional paired-flash test',confidence:.2};
}
const stereoShot=carry.estimateShotFromCapture(stereo,'lob-wedge',11);
for (const [key,value] of Object.entries(values)) assert.equal(stereoShot[key],value);
const visible=load('src/utils/shotValues.ts',()=>({}));
assert.equal(visible.measuredClubSpeed(stereoShot),5);
assert.equal(visible.measuredSmash(stereoShot),1.2);
assert.equal(visible.measuredAttackAngle(stereoShot),-4);
assert.equal(visible.measuredClubPath(stereoShot),-2.5);
const direction=load('src/utils/direction.ts',()=>({}));
assert.equal(direction.directionLabel(stereoShot.startDirectionDeg),'3.2° R');
assert.equal(direction.directionLabel(stereoShot.clubPathDeg),'2.5° L');
console.log('PASS: resolved club speed, smash, attack, club path and signed direction reach app displays.');
