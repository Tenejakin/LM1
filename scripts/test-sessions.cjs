const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

// Minimal loader: transpiles src/**/*.ts on demand and resolves '@/...' imports.
const cache = new Map();
function load(name) {
  const file = path.join('src', `${name}.ts`);
  if (cache.has(file)) return cache.get(file).exports;
  const module = { exports: {} };
  cache.set(file, module);
  const source = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  vm.runInNewContext(source, {
    module, exports: module.exports, Math, Number, Array, Map, Set, Date, JSON, String, Object, RegExp, Boolean, Error, console,
    require(request) {
      if (request.startsWith('@/')) return load(request.slice(2));
      throw new Error(`Unexpected import ${request} from ${file}`);
    },
  });
  return module.exports;
}

const sessions = load('utils/sessions');
const input = load('utils/referenceInput');

const near = (actual, expected, tolerance = 1e-6) =>
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} is not within ${tolerance} of ${expected}`);

function shot(overrides) {
  return {
    id: 's1', number: 1, capturedAt: '2026-09-29T10:00:00.000Z', clubId: 'sand-wedge',
    ballSpeedMps: 30, clubSpeedMps: 25, smashFactor: 1.2, launchAngleDeg: 30, startDirectionDeg: 2,
    strike: null, confidence: 0.5, frameCount: 100, captureDurationMs: 400, estimatedCarryM: 60,
    spinRpm: 8000, spinAxisDeg: 0, attackAngleDeg: -5, clubPathDeg: 1,
    metricConfidence: { spinRpm: { confidence: 0.4, source: 'model-estimate' } },
    ...overrides,
  };
}

// --- reference input: unit conversion and signs -----------------------------------------
const mph = { speedUnit: 'mph', distanceUnit: 'yd' };
const kmh = { speedUnit: 'kmh', distanceUnit: 'm' };
const draft = (overrides) => ({ ...input.draftFromReference(null, mph), ...overrides });

let parsed = input.referenceFromDraft(draft({ ballSpeed: '67.1', launchAngle: '30.5', carry: '65' }), mph);
assert.equal(typeof parsed, 'object');
near(parsed.ballSpeedMps, 67.1 / 2.2369362920544);
near(parsed.carryM, 65 / 1.0936132983377);
assert.equal(parsed.clubSpeedMps, null);
assert.equal(parsed.device, 'GC3');

parsed = input.referenceFromDraft(draft({ ballSpeed: '108', carry: '60' }), kmh);
near(parsed.ballSpeedMps, 30);
near(parsed.carryM, 60);

// Left/right toggles become negative/positive; empty fields stay null.
parsed = input.referenceFromDraft(draft({ ballSpeed: '60', launchDirection: '2.5', launchDirectionSide: 'L',
  spinAxis: '4', spinAxisSide: 'R', clubPath: '3', clubPathSide: 'L', attackAngle: '-4.5' }), mph);
assert.equal(parsed.startDirectionDeg, -2.5);
assert.equal(parsed.spinAxisDeg, 4);
assert.equal(parsed.clubPathDeg, -3);
assert.equal(parsed.attackAngleDeg, -4.5);
assert.equal(parsed.spinRpm, null);

// Round trip through the draft returns what was typed.
const back = input.draftFromReference(parsed, mph);
assert.equal(back.launchDirection, '2.5');
assert.equal(back.launchDirectionSide, 'L');
assert.equal(back.clubPathSide, 'L');
assert.equal(back.ballSpeed, '60');
assert.equal(back.attackAngle, '-4.5');

// Validation.
assert.match(input.referenceFromDraft(draft({}), mph), /at least one value/);
assert.match(input.referenceFromDraft(draft({ ballSpeed: 'abc' }), mph), /Ball speed must be a number/);
assert.match(input.referenceFromDraft(draft({ ballSpeed: '900' }), mph), /Ball speed must be between/);
assert.match(input.referenceFromDraft(draft({ ballSpeed: '60', clubSpeed: '20' }), mph), /Ball speed divided by club speed/);
assert.match(input.referenceFromDraft(draft({ carry: '80', total: '70' }), mph), /Total cannot be shorter than carry/);
assert.match(input.referenceFromDraft(draft({ device: '  ', ballSpeed: '60' }), mph), /Name the launch monitor/);
near(input.referenceFromDraft(draft({ ballSpeed: '60,5' }), mph).ballSpeedMps, 60.5 / 2.2369362920544); // decimal comma

// --- comparison ----------------------------------------------------------------------------
const ref = (values) => ({ device: 'GC3', enteredAt: '2026-09-29T10:01:00.000Z', ...values });
const shots = [
  shot({ id: 'a', number: 1, ballSpeedMps: 30, launchAngleDeg: 30, startDirectionDeg: 2, reference: ref({ ballSpeedMps: 29, launchAngleDeg: 32, startDirectionDeg: 1 }) }),
  shot({ id: 'b', number: 2, ballSpeedMps: 32, launchAngleDeg: 28, startDirectionDeg: -1, reference: ref({ ballSpeedMps: 30, launchAngleDeg: 31, startDirectionDeg: -1 }) }),
  shot({ id: 'c', number: 3, ballSpeedMps: 31, reference: undefined }), // no reference: ignored
  shot({ id: 'd', number: 4, ballSpeedMps: 99, reference: ref({ ballSpeedMps: 10 }), excluded: true }), // excluded: ignored
];
const comparison = sessions.referenceComparison(shots);
assert.equal(comparison.referencedShots, 2);
const byKey = Object.fromEntries(comparison.metrics.map((item) => [item.metric.key, item]));
assert.equal(byKey.ballSpeedMps.pairs.length, 2);
near(byKey.ballSpeedMps.delta.mean, 1.5); // (+1, +2)
near(byKey.ballSpeedMps.meanAbsDelta, 1.5);
near(byKey.ballSpeedMps.meanAbsPct, (1.5 / 29.5) * 100);
near(byKey.launchAngleDeg.delta.mean, -2.5); // (-2, -3)
near(byKey.startDirectionDeg.delta.mean, 0.5); // (+1, 0)
assert.equal(byKey.startDirectionDeg.meanAbsPct, null); // signed angles carry no percentage
assert.equal(byKey.clubSpeedMps, undefined); // reference gave no club speed

// Smash derives from the reference's two speeds and compares with LM1's measured smash.
const smashShot = shot({ id: 'e', smashFactor: 1.2, reference: ref({ ballSpeedMps: 30, clubSpeedMps: 25 }) });
near(sessions.referenceValue(smashShot.reference, 'smashFactor'), 1.2);
assert.equal(sessions.referenceValue(ref({ ballSpeedMps: 30 }), 'smashFactor'), null);

// LM1 club values are never taken from a club-profile estimate.
const estimatedClub = shot({ clubSpeedMps: 27, metricConfidence: { clubSpeedMps: { confidence: 0.2, source: 'club-estimate' } } });
assert.equal(sessions.lm1Value(estimatedClub, 'clubSpeedMps'), null);
assert.equal(sessions.lm1Value(shot({ clubSpeedMps: null }), 'clubSpeedMps'), null);

// Spin axis: the app's 0 placeholder never counts; a camera axis is flipped to the reference sign (positive = fade).
assert.equal(sessions.lm1Value(shot({ spinAxisDeg: 0, metricConfidence: { spinAxisDeg: { confidence: 0.15, source: 'club-estimate' } } }), 'spinAxisDeg'), null);
assert.equal(sessions.lm1Value(shot({ spinAxisDeg: 0 }), 'spinAxisDeg'), null);
assert.equal(sessions.lm1Value(shot({ spinAxisDeg: 6, metricConfidence: { spinAxisDeg: { confidence: 0.8, source: 'measured' } } }), 'spinAxisDeg'), -6);

// Spin source labelling.
assert.equal(sessions.lm1SpinEstimated(shot({})), true);
assert.equal(sessions.lm1SpinEstimated(shot({ metricConfidence: { spinRpm: { confidence: 0.9, source: 'measured' } } })), false);

// Per-club split keeps named clubs apart.
const clubs = sessions.clubComparisons([
  shot({ id: 'p', bagClubId: 'bag-1', bagClubName: 'Vokey 56', reference: ref({ ballSpeedMps: 29 }) }),
  shot({ id: 'q', bagClubId: 'bag-2', bagClubName: 'Cleveland 56', reference: ref({ ballSpeedMps: 31 }) }),
  shot({ id: 'r', bagClubId: 'bag-2', bagClubName: 'Cleveland 56', reference: ref({ ballSpeedMps: 30 }) }),
]);
assert.equal(clubs.length, 2);
assert.equal(clubs[0].label, 'Cleveland 56');
assert.equal(clubs[0].shots, 2);

// --- sessions ------------------------------------------------------------------------------
const list = [
  { id: 'old', name: 'Old', startedAt: '2026-09-01T10:00:00.000Z', endedAt: '2026-09-01T11:00:00.000Z' },
  { id: 'new', name: 'New', startedAt: '2026-09-20T10:00:00.000Z', endedAt: '2026-09-20T11:00:00.000Z' },
  { id: 'open', name: 'Open', startedAt: '2026-09-10T10:00:00.000Z', endedAt: null },
];
const ids = (items) => Array.from(items, (item) => item.id);
assert.deepEqual(ids(sessions.sortSessions(list)), ['open', 'new', 'old']);
const filed = [shot({ id: '1', sessionId: 'new' }), shot({ id: '2' }), shot({ id: '3', sessionId: 'old' })];
assert.deepEqual(ids(sessions.sessionShots(filed, 'new')), ['1']);
assert.deepEqual(ids(sessions.sessionShots(filed, null)), ['2']);
assert.equal(sessions.parseSessions('not json').length, 0);
assert.deepEqual(ids(sessions.parseSessions(JSON.stringify([{ id: 'x', name: 'X', startedAt: 't' }, { id: 5 }]))), ['x']);
assert.ok(sessions.newSessionId() !== sessions.newSessionId());

// --- CSV -------------------------------------------------------------------------------------
const csv = sessions.sessionCsv({ id: 'new', name: 'GC3, test "1"', startedAt: 't' }, [
  shot({ id: 'a', number: 1, reference: ref({ ballSpeedMps: 29, launchAngleDeg: 32, notes: 'thin, low' }) }),
  shot({ id: 'b', number: 2, capturedAt: '2026-09-29T09:00:00.000Z' }),
], {
  speedLabel: 'kmh', distanceLabel: 'm', speed: (mps) => mps * 3.6, distance: (meters) => meters,
});
const lines = csv.split('\n');
assert.equal(lines.length, 3);
const columns = lines[0].split(',');
assert.ok(columns.includes('lm1_ball_kmh') && columns.includes('ref_ball_kmh'));
assert.ok(lines[1].startsWith('2,2026-09-29T09:00:00.000Z')); // sorted by time, oldest first
function cells(line) {
  const out = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') { cell += '"'; i += 1; }
      else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') { out.push(cell); cell = ''; }
    else cell += ch;
  }
  out.push(cell);
  return out;
}
const row = cells(lines[2]);
assert.equal(row[2], 'GC3, test "1"'); // session name survives quoting
assert.ok(row.includes('thin, low'));
assert.equal(row[columns.indexOf('ref_ball_kmh')], '104.4'); // 29 m/s
assert.equal(row[columns.indexOf('lm1_ball_kmh')], '108.0'); // 30 m/s
assert.equal(row[columns.indexOf('lm1_spin_source')], 'model');
assert.equal(cells(lines[1])[columns.indexOf('ref_ball_kmh')], ''); // no reference: blank, not zero
assert.equal(cells(lines[1]).length, columns.length);
assert.equal(cells(lines[2]).length, columns.length);

console.log('session and reference tests passed');
