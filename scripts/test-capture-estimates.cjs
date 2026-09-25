const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

const directionExports = {};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/utils/direction.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, { exports: directionExports });
assert.equal(directionExports.directionLabel(0.4079), '0.4° R');
assert.equal(directionExports.directionLabel(-4.1082), '4.1° L');
assert.equal(directionExports.directionLabel(0), 'Straight');
assert.match(directionExports.DIRECTION_SIGN_NOTE, /toward the cameras.*away from the cameras/);

const club = {
  id: 'sand-wedge', label: 'Sand Wedge', carryFactor: 0.72,
  demoClubSpeedMps: 27, demoSmash: 1.16, demoLaunchDeg: 35, typicalSpinRpm: 9800,
};
const flightExports = {};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/utils/flight.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, { exports: flightExports, require() { return {}; } });
const moduleExports = {};
const source = ts.transpileModule(fs.readFileSync('src/utils/carry.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
vm.runInNewContext(source, {
  exports: moduleExports,
  require(name) {
    if (name === '@/utils/flight') return flightExports;
    assert.equal(name, '@/data/clubs');
    return { getClub: () => club, isClubId: (id) => id === club.id };
  },
});

const metric = (value) => ({ value, unit: 'm/s', status: value === null ? 'unavailable' : 'estimated', reason: 'camera result' });
const capture = {
  id: 'capture-1', captureId: 'capture-1', capturedAt: '2026-09-23T13:08:09Z',
  clubId: club.id, mode: 'full-shot', classification: 'motion-observed', frameCount: 250,
  captureDurationMs: 1030, impactFrameIndex: 118, coarseDepartureFrameIndex: 117,
  measurements: { metrics: {
    ballSpeedMps: metric(null), launchAngleDeg: metric(null), startDirectionDeg: metric(null),
  } },
};
assert.equal(moduleExports.estimateShotFromCapture(capture, club.id, 1), null,
  'motion alone must not create a shot from the club speed');
capture.measurements.metrics.ballSpeedMps = metric(11.6);
assert.equal(moduleExports.estimateShotFromCapture(capture, club.id, 1), null,
  'speed without a launch vector must remain a failed shot');
capture.measurements.metrics.launchAngleDeg = metric(25);
capture.measurements.metrics.startDirectionDeg = metric(1);
const shot = moduleExports.estimateShotFromCapture(capture, club.id, 1);
assert.equal(shot.ballSpeedMps, 11.6);
assert.equal(shot.clubSpeedMps, null, 'an untracked club must stay unavailable, not ball speed / profile smash');
assert.equal(shot.smashFactor, null, 'smash without a club speed must stay unavailable');
assert.equal(shot.strike, null, 'an unmeasured strike must not be assumed centred');
assert.ok(shot.unavailableReasons.clubSpeedMps, 'the missing club speed keeps a reason');
assert.equal(shot.metricConfidence.clubSpeedMps, undefined);
assert.equal(shot.metricConfidence.ballSpeedMps.source, 'device-estimate');
assert.equal(shot.measurementSource, 'camera-estimate');
assert.equal(shot.metricConfidence.estimatedCarryM.source, 'model-estimate', 'carry is calculated, never observed');
assert.match(shot.metricConfidence.estimatedCarryM.reason, /Landing is not observed/);
const chipSpin = shot.spinRpm;
capture.measurements.metrics.attackAngleDeg = metric(-10);
const steepShot = moduleExports.estimateShotFromCapture(capture, club.id, 1);
assert.ok(steepShot.spinRpm > chipSpin);
assert.ok(steepShot.estimatedCarryM > 0);
capture.measurements.metrics.estimatedCarryM = metric(999);
assert.notEqual(moduleExports.estimateShotFromCapture(capture, club.id, 1).estimatedCarryM, 999,
  'legacy Pi carry must be recalculated with the flight model');
assert.equal(moduleExports.assumedSpinRpm(club.id, 7.2139, -11.6598), 4242);
assert.equal(moduleExports.estimateCarryMeters({
  ballSpeedMps: 7.2139, launchAngleDeg: 23.8095, startDirectionDeg: -2.8204,
  clubId: club.id, spinRpm: 4242,
}), 4.0, 'app and Pi flight calculations must agree for the latest chip');
// Same inputs through the Pi's flight_model.py 2.0.0 (see raspberry_pi/tests/test_flight_model.py).
assert.equal(flightExports.impactSpinRpm('sand-wedge', 10, 29, -8), 3093);
const chipFlight = flightExports.simulateFlight(12.3, 29, -3, 3093);
assert.equal(Math.round(chipFlight.carryM * 10) / 10, 13.1);
assert.equal(Math.round(chipFlight.apexM * 1000) / 1000, 1.917);
assert.equal(Math.round(chipFlight.descentDeg * 100) / 100, 31.03);
const chipRoll = flightExports.rollMeters(chipFlight);
assert.equal(Math.round(chipRoll.rollM * 100) / 100, 13.13);
assert.equal(chipRoll.surface, 'green');
assert.equal(Math.round(flightExports.spinLoftDeg(29, -8) * 100) / 100, 49.57);
assert.equal(flightExports.spinLoftDeg(29.3, -14.8), null, 'impossible launch over attack has no loft');
capture.measurements.shotEvidence = { status: 'motion-only', clubFrames: 0, reason: 'Club not tracked' };
assert.equal(moduleExports.estimateShotFromCapture(capture, club.id, 2).ballSpeedMps, 11.6,
  'a measured ball must be kept when only the club track is missing');
capture.measurements.shotEvidence = { status: 'not-a-strike', clubFrames: 0, reason: 'Address nudge' };
assert.equal(moduleExports.estimateShotFromCapture(capture, club.id, 2), null,
  'movement the Pi classified as not a strike must not enter shot history');
capture.measurements.shotEvidence = { status: 'club-motion-observed', clubFrames: 5, reason: 'Club motion' };
capture.measurements.metrics.clubSpeedMps = metric(8);
const clubShot = moduleExports.estimateShotFromCapture(capture, club.id, 2);
assert.equal(clubShot.clubSpeedMps, 8);
assert.equal(clubShot.metricConfidence.spinRpm.source, 'model-estimate', 'club speed + attack give an impact spin estimate');
assert.equal(clubShot.spinRpm, flightExports.impactSpinRpm(club.id, 8, 25, -10));
const estimates = moduleExports.shotEstimates(clubShot);
assert.ok(estimates.totalM > estimates.flight.carryM, 'a chip rolls after landing');
assert.ok(Math.abs(estimates.dynamicLoftDeg - (estimates.spinLoftDeg - 10)) < 1e-9);
assert.equal(clubShot.smashFactor, 1.45, 'smash is derived only from two camera speeds');
assert.equal(clubShot.clubPathDeg, undefined, 'an unresolved club path stays unavailable');
assert.ok(clubShot.unavailableReasons.clubPathDeg);
capture.measurements.metrics.clubPathDeg = metric(-3.5);
const pathShot = moduleExports.estimateShotFromCapture(capture, club.id, 2);
assert.equal(pathShot.clubPathDeg, -3.5);
assert.equal(pathShot.attackAngleDeg, -10);
assert.equal(pathShot.metricConfidence.attackAngleDeg.source, 'device-estimate');
capture.measurements.metrics.strikeXmm = metric(4);
capture.measurements.metrics.strikeYmm = metric(-2);
assert.deepEqual({ ...moduleExports.estimateShotFromCapture(capture, club.id, 2).strike }, { xMm: 4, yMm: -2 });
const simExports = {};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/services/opengolfsim.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, { exports: simExports, URL, setTimeout, clearTimeout, require(name) {
  if (name === '@/utils/carry') return moduleExports;
  if (name === '@/data/clubs') return { isClubId: (id) => id === club.id };
  throw new Error(name);
} });
assert.ok(simExports.toOpenGolfSimCapture(capture));
capture.measurements.shotEvidence.status = 'motion-only';
assert.ok(simExports.toOpenGolfSimCapture(capture), 'a camera-measured ball reaches the simulator without a club track');
capture.measurements.shotEvidence.status = 'not-a-strike';
assert.equal(simExports.toOpenGolfSimCapture(capture), null, 'a non-strike cannot reach the simulator');
capture.measurements.shotEvidence.status = 'club-motion-observed';
capture.measurements.metrics.ballSpeedMps.value = NaN;
assert.equal(simExports.toOpenGolfSimCapture(capture), null, 'non-finite camera values cannot reach the simulator');
const compile = (file) => ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const shotValueExports = {};
vm.runInNewContext(compile('src/utils/shotValues.ts'), { exports: shotValueExports, require() { return {}; } });
const sessionExports = {};
const clubList = [{ id: 'pitching-wedge' }, { id: 'sand-wedge' }];
const bagExports = {};
vm.runInNewContext(compile('src/utils/bagClubs.ts'), { exports: bagExports, require(name) {
  assert.equal(name, '@/data/clubs');
  return { getClub: (id) => ({ label: id === 'sand-wedge' ? 'Sand Wedge' : 'Pitching Wedge' }), isClubId: (id) => ['sand-wedge', 'pitching-wedge'].includes(id) };
} });
vm.runInNewContext(compile('src/utils/session.ts'), { exports: sessionExports, require(name) {
  if (name === '@/utils/bagClubs') return bagExports;
  if (name === '@/data/clubs') return { clubs: clubList };
  if (name === '@/utils/carry') return moduleExports;
  if (name === '@/utils/shotValues') return shotValueExports;
  throw new Error(name);
} });
const sessionShot = (id, clubId, ballSpeedMps, extra = {}) => ({
  id, clubId, ballSpeedMps, launchAngleDeg: 28, startDirectionDeg: -2, spinRpm: 3000,
  clubSpeedMps: ballSpeedMps / 1.25, smashFactor: 1.25, attackAngleDeg: -8, ...extra,
});
const summaries = sessionExports.clubSummaries([
  sessionShot('a', 'sand-wedge', 12), sessionShot('b', 'sand-wedge', 13),
  sessionShot('c', 'sand-wedge', 40, { excluded: true }),
  sessionShot('d', 'pitching-wedge', 20), sessionShot('e', 'pitching-wedge', 21, { clubSpeedMps: null, smashFactor: null }),
]);
assert.deepEqual(Array.from(summaries, (item) => item.clubId), ['pitching-wedge', 'sand-wedge'], 'longest club first');
const wedge = summaries[1];
assert.equal(wedge.shots, 2, 'an excluded mishit does not count');
assert.ok(wedge.carryM.sd > 0 && wedge.gapToNextM === null);
assert.ok(Math.abs(summaries[0].gapToNextM - (summaries[0].carryM.mean - wedge.carryM.mean)) < 1e-9);
assert.equal(summaries[0].clubSpeedMps.count, 1, 'club averages use only camera-resolved club speeds');
assert.ok(wedge.offlineM.mean < 0, 'offline keeps the left sign of start direction');
assert.equal(sessionExports.spread([5]).sd, null);
// Two named sand wedges keep separate dispersion; the label follows the newest name.
const wedges = sessionExports.clubSummaries([
  sessionShot('v1', 'sand-wedge', 12, { bagClubId: 'bag-v', bagClubName: 'Vokey 56', capturedAt: '2026-09-25T10:00:00Z' }),
  sessionShot('v2', 'sand-wedge', 12.5, { bagClubId: 'bag-v', bagClubName: 'Vokey 56 bent', capturedAt: '2026-09-25T11:00:00Z' }),
  sessionShot('c1', 'sand-wedge', 14, { bagClubId: 'bag-c', bagClubName: 'RTX 58', startDirectionDeg: 3 }),
  sessionShot('p1', 'sand-wedge', 13),
]);
assert.deepEqual(Array.from(wedges, (item) => item.key).sort(), ['bag-c', 'bag-v', 'sand-wedge']);
assert.equal(wedges.find((item) => item.key === 'bag-v').label, 'Vokey 56 bent');
assert.equal(wedges.find((item) => item.key === 'sand-wedge').label, 'Sand Wedge');
// Named-club drafts are validated with the Pi's own face-size limits.
const draft = { name: ' Vokey 56 ', baseClubId: 'sand-wedge', loftDeg: '56', faceWidthMm: '78', faceHeightMm: '50' };
const saved = bagExports.bagClubFromDraft(draft);
assert.equal(saved.name, 'Vokey 56');
assert.deepEqual({ ...bagExports.bagClubCommand(saved) }, { id: saved.id, name: 'Vokey 56', faceWidthMm: 78, faceHeightMm: 50 });
assert.match(bagExports.bagClubFromDraft({ ...draft, faceWidthMm: '30' }), /Face width/);
assert.match(bagExports.bagClubFromDraft({ ...draft, faceHeightMm: '' }), /both/);
assert.match(bagExports.bagClubFromDraft({ ...draft, name: '' }), /name/);
assert.deepEqual({ ...bagExports.bagClubCommand({ ...saved, faceWidthMm: null, faceHeightMm: null }) }, { id: saved.id, name: 'Vokey 56' });
assert.equal(bagExports.parseBagClubs('not json').length, 0);
assert.equal(bagExports.parseBagClubs(JSON.stringify([saved, { id: 'x', name: 'y', baseClubId: 'putter' }])).length, 1);
// A capture from a named club lands on the shot.
capture.measurements.metrics.ballSpeedMps.value = 11.6;
capture.measurements.shotEvidence.status = 'club-motion-observed';
capture.bagClubId = 'bag-v'; capture.bagClubName = 'Vokey 56';
const bagShot = moduleExports.estimateShotFromCapture(capture, club.id, 3);
assert.equal(bagShot.bagClubId, 'bag-v');
assert.equal(bagShot.bagClubName, 'Vokey 56');
console.log('Camera shot requires camera-derived launch inputs.');
