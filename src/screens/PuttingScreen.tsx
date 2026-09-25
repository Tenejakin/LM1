import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Circle, Defs, LinearGradient, Line, Path, Stop } from 'react-native-svg';

import { ScreenHeader } from '@/components/ScreenHeader';
import { CaptureReview } from '@/components/CaptureReview';
import { ReadinessCard } from '@/components/ReadinessCard';
import { Eyebrow, MetricTile, PrimaryButton, SectionHeader, Surface } from '@/components/ui';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { colors, radii, spacing } from '@/theme';
import { Putt } from '@/types';
import {
  lateralMissCentimeters,
  paceLabel,
  puttRollMeters,
  startLineLabel,
} from '@/utils/putting';
import { useUnits } from '@/context/UnitsContext';

const METERS_TO_FEET = 3.28084;

export function PuttingScreen({ onOpenDevice, onOpenNormalShot }: { onOpenDevice: () => void; onOpenNormalShot: () => void }) {
  const insets = useSafeAreaInsets();
  const {
    state,
    status,
    isDemo,
    error,
    putts,
    activePutt,
    captureMode,
    ballDetected,
    armPutting,
    getLatestPuttRecoveryCandidate,
    saveRecoveredPutt,
    trigger,
    clearError,
  } = useLaunchMonitor();
  const [targetInput, setTargetInput] = useState('3.0');
  const [stimpInput, setStimpInput] = useState('10');
  const [recoveryCandidate, setRecoveryCandidate] = useState<Putt | null>(null);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [recoveryMessage, setRecoveryMessage] = useState<string | null>(null);
  const targetDistanceM = clamp(parseDecimal(targetInput) ?? 3, 0.5, 30);
  const stimpFeet = clamp(parseDecimal(stimpInput) ?? 10, 5, 15);
  const recentPutts = useMemo(() => putts.slice(0, 4), [putts]);
  const puttingArmed = state === 'armed' && captureMode === 'putting';
  const automaticCapture = !isDemo && Boolean(status?.automaticCapture);
  const isPiTest = !isDemo && !automaticCapture && status?.captureBackend === 'simulator';

  const handlePrimary = () => {
    if (state === 'offline' || state === 'error') onOpenDevice();
    else if (state === 'ready') void armPutting();
    else if (puttingArmed) void trigger();
    else if (state === 'armed') void armPutting();
  };

  const primaryLabel = automaticCapture && puttingArmed
    ? ballDetected ? 'Ball detected · waiting for putt' : 'Putting armed · place the ball'
    : state === 'ready'
    ? isPiTest ? 'Arm putting test' : 'Arm putting mode'
    : puttingArmed
      ? isDemo ? 'Simulate putt' : isPiTest ? 'Send test putt' : 'Manual putt trigger'
      : state === 'armed'
        ? 'Switch to putting mode'
        : state === 'processing'
          ? 'Analyzing putt'
          : state === 'connecting'
            ? 'Connecting'
            : 'Connect to LM1';

  const hero = puttingHero(state, captureMode, status?.fps, isPiTest);

  return (
    <ScrollView
      contentContainerStyle={[styles.content, { paddingTop: insets.top + spacing.md }]}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
    >
      <ScreenHeader title="Putting" subtitle="Pace & start-line monitor" state={state} demo={isDemo} />
      {automaticCapture && puttingArmed ? <ReadinessCard readiness={status?.readiness} /> : null}
      <CaptureReview />

      {error ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`${error}. Dismiss`}
          onPress={clearError}
          style={styles.errorBanner}
        >
          <Ionicons name="alert-circle" size={18} color={colors.red} />
          <Text style={styles.errorText}>{error}</Text>
          <Ionicons name="close" size={17} color={colors.textMuted} />
        </Pressable>
      ) : null}

      <Surface style={styles.setupCard}>
        <View style={styles.setupHeading}>
          <View style={[styles.putterIcon, puttingArmed && styles.putterIconArmed]}>
            <Ionicons name="flag" size={23} color={puttingArmed ? colors.accent : colors.textMuted} />
          </View>
          <View style={styles.setupCopy}>
            <Eyebrow>{hero.eyebrow}</Eyebrow>
            <Text style={styles.setupTitle}>{hero.title}</Text>
            <Text style={styles.setupBody}>{hero.body}</Text>
          </View>
        </View>

        <View style={styles.settingRow}>
          <SettingField
            label="Target distance"
            suffix="m"
            value={targetInput}
            onChangeText={(value) => setTargetInput(sanitizeDecimal(value))}
          />
          <SettingField
            label="Green speed"
            suffix="stimp"
            value={stimpInput}
            onChangeText={(value) => setStimpInput(sanitizeDecimal(value))}
          />
        </View>

        <PrimaryButton
          label={primaryLabel}
          icon={state === 'ready' ? 'radio' : puttingArmed ? 'ellipse' : 'link'}
          onPress={handlePrimary}
          disabled={state === 'processing' || state === 'connecting' || (automaticCapture && puttingArmed) || (state === 'armed' && !puttingArmed && ballDetected)}
          loading={state === 'processing' || state === 'connecting'}
        />
        {captureMode === 'putting' && (state === 'ready' || state === 'armed') ? (
          <PrimaryButton
            label="Switch to normal shot"
            icon="golf"
            variant="outline"
            onPress={onOpenNormalShot}
            disabled={ballDetected}
          />
        ) : null}
        {ballDetected && state === 'armed' ? (
          <Text style={styles.setupBody}>Remove the ball before switching capture modes.</Text>
        ) : null}
      </Surface>

      {!isDemo && state !== 'offline' && state !== 'connecting' ? (
        <Surface style={styles.setupCard}>
          <Text style={styles.setupTitle}>Missing a putt?</Text>
          <Text style={styles.setupBody}>Find the latest saved putting capture on this Pi, then choose whether to save it to your account.</Text>
          <PrimaryButton label="Find last Pi putt" variant="outline" loading={recoveryBusy} disabled={recoveryBusy}
            onPress={() => void (async () => {
              setRecoveryBusy(true);
              setRecoveryMessage(null);
              try {
                const candidate = await getLatestPuttRecoveryCandidate();
                setRecoveryCandidate(candidate);
                if (!candidate) setRecoveryMessage('No unsaved putt with usable measurements was found on this Pi.');
              } catch (caught) {
                setRecoveryMessage(caught instanceof Error ? caught.message : 'Could not read saved Pi captures.');
              } finally { setRecoveryBusy(false); }
            })()} />
          {recoveryCandidate ? <>
            <Text style={styles.setupBody}>Saved {new Date(recoveryCandidate.capturedAt).toLocaleString()} · ball speed {recoveryCandidate.ballSpeedMps.toFixed(2)} m/s · launch {recoveryCandidate.launchAngleDeg.toFixed(1)}°</Text>
            {recoveryCandidate.airborne ? <Text style={styles.errorText}>The ball was airborne; roll distance and pace will not be estimated.</Text> : null}
            <PrimaryButton label="Save this putt to my account" loading={recoveryBusy} disabled={recoveryBusy}
              onPress={() => void (async () => {
                setRecoveryBusy(true);
                setRecoveryMessage(null);
                try {
                  await saveRecoveredPutt(recoveryCandidate);
                  setRecoveryCandidate(null);
                  setRecoveryMessage('Putt saved to your Supabase account.');
                } catch (caught) {
                  setRecoveryMessage(caught instanceof Error ? caught.message : 'Could not save this putt.');
                } finally { setRecoveryBusy(false); }
              })()} />
          </> : null}
          {recoveryMessage ? <Text style={styles.setupBody}>{recoveryMessage}</Text> : null}
        </Surface>
      ) : null}

      {activePutt ? (
        <PuttResult putt={activePutt} targetDistanceM={targetDistanceM} stimpFeet={stimpFeet} />
      ) : (
        <Surface style={styles.emptyCard}>
          <View style={styles.emptyIcon}>
            <Ionicons name="golf-outline" size={28} color={colors.accent} />
          </View>
          <Text style={styles.emptyTitle}>Roll your first putt</Text>
          <Text style={styles.emptyBody}>Set the target distance, arm putting mode, and roll the ball. Results appear automatically.</Text>
        </Surface>
      )}

      {recentPutts.length ? (
        <View style={styles.section}>
          <SectionHeader title="Recent putts" />
          <View style={styles.listGap}>
            {recentPutts.map((putt) => (
              <PuttRow
                key={putt.id}
                putt={putt}
                targetDistanceM={targetDistanceM}
                stimpFeet={stimpFeet}
              />
            ))}
          </View>
        </View>
      ) : null}

      <View style={styles.modelNote}>
        <Ionicons name="information-circle-outline" size={17} color={colors.textMuted} />
        <Text style={styles.modelNoteText}>Roll distance is measured when the device supplies it; otherwise it is estimated from ball speed and the selected green speed.</Text>
      </View>
    </ScrollView>
  );
}

function PuttResult({
  putt,
  targetDistanceM,
  stimpFeet,
}: {
  putt: Putt;
  targetDistanceM: number;
  stimpFeet: number;
}) {
  const units = useUnits();
  const rollDistanceM = puttRollMeters(putt, stimpFeet);
  const missCm = lateralMissCentimeters(putt.launchDirectionDeg, targetDistanceM);

  return (
    <View style={styles.results}>
      <View style={styles.resultHeading}>
        <View>
          <Eyebrow>{putt.measurementSource ? 'Camera estimate - unvalidated' : putt.simulated ? 'Synthetic link test' : 'Latest result'}</Eyebrow>
          <Text style={styles.resultTitle}>Putt #{putt.number}</Text>
        </View>
        <View style={styles.confidencePill}>
          <Ionicons name="checkmark-circle" size={14} color={colors.accent} />
          <Text style={styles.confidenceText}>{putt.measurementSource ? 'Accuracy not validated' : Math.round(putt.confidence * 100) + '% confidence'}</Text>
        </View>
      </View>

      {putt.airborne ? (
        <Surface style={styles.paceCard}>
          <Text style={styles.errorText}>Ball airborne · {putt.launchAngleDeg.toFixed(1)}° launch. Roll distance and pace are unavailable for this capture.</Text>
        </Surface>
      ) : <Surface style={styles.paceCard}>
        <View>
          <Eyebrow>{putt.rollDistanceM === undefined ? 'Estimated roll' : 'Measured roll'}</Eyebrow>
          <View style={styles.rollRow}>
            <Text style={styles.rollValue}>{rollDistanceM.toFixed(2)}</Text>
            <Text style={styles.rollUnit}>m</Text>
          </View>
          <Text style={styles.rollFeet}>{(rollDistanceM * METERS_TO_FEET).toFixed(1)} ft</Text>
        </View>
        <View style={styles.paceSummary}>
          <Text style={styles.paceLabel}>Against {targetDistanceM.toFixed(1)} m</Text>
          <Text style={[styles.paceValue, Math.abs(rollDistanceM - targetDistanceM) <= 0.15 && styles.paceValueGood]}>
            {paceLabel(rollDistanceM, targetDistanceM)}
          </Text>
        </View>
      </Surface>}

      <View style={styles.metricsRow}>
        <MetricTile label="Ball speed" value={units.speed(putt.ballSpeedMps)} unit={units.speedLabel} accent />
        <MetricTile label="Putter speed" value={units.speed(putt.putterSpeedMps)} unit={units.speedLabel} />
        <MetricTile label="Smash" value={putt.smashFactor.toFixed(2)} />
      </View>

      {!putt.airborne ? <Surface style={styles.pathCard}>
        <View style={styles.pathHeader}>
          <View>
            <Eyebrow>Start line & pace</Eyebrow>
            <Text style={styles.pathTitle}>{startLineLabel(putt.launchDirectionDeg)}</Text>
          </View>
          <View style={styles.missCopy}>
            <Text style={styles.missLabel}>MISS AT HOLE</Text>
            <Text style={styles.missValue}>
              {Math.abs(missCm).toFixed(1)} cm {Math.abs(missCm) < 0.1 ? 'center' : missCm > 0 ? 'R' : 'L'}
            </Text>
          </View>
        </View>
        <PuttPath putt={putt} rollDistanceM={rollDistanceM} targetDistanceM={targetDistanceM} />
      </Surface> : null}

      <Surface style={styles.detailCard}>
        <DetailRow label="Launch direction" value={startLineLabel(putt.launchDirectionDeg)} />
        <DetailRow label="Launch angle" value={`${putt.launchAngleDeg.toFixed(1)}°`} />
        <DetailRow label="Skid distance" value={putt.skidDistanceM === undefined ? 'Not measured' : `${(putt.skidDistanceM * 100).toFixed(0)} cm`} />
        <DetailRow label="Face strike" value={puttStrikeLabel(putt)} />
      </Surface>
    </View>
  );
}

function PuttPath({
  putt,
  rollDistanceM,
  targetDistanceM,
}: {
  putt: Putt;
  rollDistanceM: number;
  targetDistanceM: number;
}) {
  const startX = 160;
  const startY = 222;
  const targetY = 34;
  const rollRatio = clamp(rollDistanceM / targetDistanceM, 0, 1.35);
  const endY = startY - (startY - targetY) * Math.min(1, rollRatio);
  const endX = clamp(startX + putt.launchDirectionDeg * 15 * Math.min(1, rollRatio), 55, 265);

  return (
    <View accessibilityLabel={`Putt path ${startLineLabel(putt.launchDirectionDeg)}, ${paceLabel(rollDistanceM, targetDistanceM)}`}>
      <Svg height={230} width="100%" viewBox="0 0 320 250">
        <Defs>
          <LinearGradient id="puttTrail" x1="0" y1="1" x2="0" y2="0">
            <Stop offset="0" stopColor={colors.accent} stopOpacity="0.35" />
            <Stop offset="1" stopColor={colors.accent} stopOpacity="1" />
          </LinearGradient>
        </Defs>
        <Path d="M44 26 H276 V232 H44 Z" fill="#101A15" stroke={colors.lineStrong} strokeWidth="1.5" />
        <Line x1={startX} y1={startY} x2={startX} y2={targetY} stroke={colors.lineStrong} strokeDasharray="5 7" />
        <Circle cx={startX} cy={targetY} r="11" fill="#080B0D" stroke={colors.textMuted} strokeWidth="2" />
        <Circle cx={startX} cy={targetY} r="3" fill={colors.black} />
        <Path
          d={`M${startX} ${startY} Q${(startX + endX) / 2} ${(startY + endY) / 2} ${endX} ${endY}`}
          fill="none"
          stroke="url(#puttTrail)"
          strokeLinecap="round"
          strokeWidth="4"
        />
        <Circle cx={startX} cy={startY} r="8" fill={colors.white} />
        <Circle cx={endX} cy={endY} r="6" fill={colors.accent} />
        <Circle cx={endX} cy={endY} r="14" fill={colors.accent} opacity="0.13" />
      </Svg>
      <View style={styles.pathLabels}>
        <Text style={styles.pathEdgeLabel}>BALL</Text>
        <Text style={styles.pathScale}>{targetDistanceM.toFixed(1)} m target</Text>
        <Text style={styles.pathEdgeLabel}>HOLE</Text>
      </View>
    </View>
  );
}

function SettingField({
  label,
  suffix,
  value,
  onChangeText,
}: {
  label: string;
  suffix: string;
  value: string;
  onChangeText: (value: string) => void;
}) {
  return (
    <View style={styles.settingField}>
      <Text style={styles.settingLabel}>{label}</Text>
      <View style={styles.settingInputWrap}>
        <TextInput
          accessibilityLabel={`${label}, ${suffix}`}
          inputMode="decimal"
          keyboardType="decimal-pad"
          onChangeText={onChangeText}
          selectionColor={colors.accent}
          style={styles.settingInput}
          value={value}
        />
        <Text style={styles.settingSuffix}>{suffix}</Text>
      </View>
    </View>
  );
}

function PuttRow({
  putt,
  targetDistanceM,
  stimpFeet,
}: {
  putt: Putt;
  targetDistanceM: number;
  stimpFeet: number;
}) {
  const units = useUnits();
  const rollDistanceM = puttRollMeters(putt, stimpFeet);
  return (
    <Surface style={styles.puttRow}>
      <View style={styles.puttNumber}>
        <Text style={styles.puttHash}>#</Text>
        <Text style={styles.puttNumberText}>{putt.number}</Text>
      </View>
      <View style={styles.puttMain}>
        <Text style={styles.puttDistance}>{putt.airborne ? 'Airborne' : `${rollDistanceM.toFixed(2)} m`}</Text>
        <Text style={styles.puttMeta}>{units.speedWithUnit(putt.ballSpeedMps)} · {startLineLabel(putt.launchDirectionDeg)}</Text>
      </View>
      <View style={styles.puttPace}>
        <Text style={styles.puttPaceValue}>{putt.airborne ? 'Roll unavailable' : paceLabel(rollDistanceM, targetDistanceM)}</Text>
        <Text style={styles.puttConfidence}>{putt.measurementSource ? 'Accuracy not validated' : Math.round(putt.confidence * 100) + '% confidence'}</Text>
      </View>
    </Surface>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.detailRow}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={styles.detailValue}>{value}</Text>
    </View>
  );
}

function puttingHero(state: string, mode: string, fps?: number, isPiTest = false) {
  if (state === 'armed' && mode === 'putting') return isPiTest
    ? { eyebrow: 'Connection test armed', title: 'Ready to test putting', body: 'Send a synthetic putt from the Raspberry Pi.' }
    : { eyebrow: 'Putting mode armed', title: 'Roll when ready', body: 'The capture window is watching the ball and putter.' };
  if (state === 'armed') return { eyebrow: 'Normal shot active', title: 'Switch to putting', body: 'Change mode before placing the ball for a putt.' };
  if (state === 'processing') return isPiTest
    ? { eyebrow: 'Test event received', title: 'Checking live data', body: 'The Pi is sending a synthetic putting result.' }
    : { eyebrow: 'Tracking roll', title: 'Analyzing putt', body: 'Calculating pace, start line, skid, and strike.' };
  if (state === 'offline' || state === 'error') return { eyebrow: 'Device offline', title: 'Connect to LM1', body: 'Use the Device tab, then return here to start putting.' };
  if (isPiTest) return { eyebrow: 'Pi connected', title: 'Putting link ready', body: 'Camera-free test mode is active.' };
  return { eyebrow: 'Putting session', title: 'Dial in pace and line', body: fps ? `${fps} FPS capture ready` : 'Set a target and arm the monitor.' };
}

function puttStrikeLabel(putt: Putt): string {
  if (!putt.strike) return 'Not measured';
  if (Math.abs(putt.strike.xMm) < 1) return 'Centered';
  return `${Math.abs(putt.strike.xMm).toFixed(0)} mm ${putt.strike.xMm > 0 ? 'toe' : 'heel'}`;
}

function parseDecimal(value: string): number | null {
  const normalized = value.trim().replace(',', '.');
  if (!normalized || normalized === '.') return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function sanitizeDecimal(value: string): string {
  return value.replace(/[^0-9,.]/g, '').replace(/([,.].*)[,.]/g, '$1');
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

const styles = StyleSheet.create({
  content: { paddingBottom: 120, paddingHorizontal: spacing.md },
  errorBanner: { alignItems: 'center', backgroundColor: '#241718', borderColor: '#4C2929', borderRadius: radii.md, borderWidth: 1, flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.md, padding: spacing.md },
  errorText: { color: '#F0B0AC', flex: 1, fontSize: 12, fontWeight: '600', lineHeight: 17 },
  setupCard: { padding: spacing.lg },
  setupHeading: { alignItems: 'center', flexDirection: 'row', marginBottom: spacing.lg },
  putterIcon: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderRadius: 20, height: 52, justifyContent: 'center', marginRight: 13, width: 52 },
  putterIconArmed: { backgroundColor: '#192219' },
  setupCopy: { flex: 1 },
  setupTitle: { color: colors.text, fontSize: 19, fontWeight: '700', letterSpacing: -0.4, marginTop: 3 },
  setupBody: { color: colors.textMuted, fontSize: 10, lineHeight: 15, marginTop: 4 },
  settingRow: { flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.md },
  settingField: { flex: 1 },
  settingLabel: { color: colors.textMuted, fontSize: 9, fontWeight: '800', letterSpacing: 0.7, marginBottom: 6, textTransform: 'uppercase' },
  settingInputWrap: { alignItems: 'center', backgroundColor: colors.background, borderColor: colors.lineStrong, borderRadius: radii.md, borderWidth: 1, flexDirection: 'row', minHeight: 52, paddingHorizontal: spacing.md },
  settingInput: { color: colors.text, flex: 1, fontSize: 20, fontWeight: '700', minWidth: 0, paddingVertical: 0 },
  settingSuffix: { color: colors.textDim, fontSize: 9, fontWeight: '800' },
  results: { marginTop: spacing.xl },
  resultHeading: { alignItems: 'flex-end', flexDirection: 'row', justifyContent: 'space-between', marginBottom: spacing.md },
  resultTitle: { color: colors.text, fontSize: 24, fontWeight: '700', letterSpacing: -0.6, marginTop: 3 },
  confidencePill: { alignItems: 'center', backgroundColor: '#192219', borderRadius: radii.pill, flexDirection: 'row', gap: 5, paddingHorizontal: 10, paddingVertical: 7 },
  confidenceText: { color: colors.accent, fontSize: 9, fontWeight: '800' },
  paceCard: { alignItems: 'flex-end', flexDirection: 'row', justifyContent: 'space-between', padding: spacing.lg },
  rollRow: { alignItems: 'baseline', flexDirection: 'row', gap: 6, marginTop: 2 },
  rollValue: { color: colors.accent, fontSize: 50, fontWeight: '700', letterSpacing: -2.8 },
  rollUnit: { color: colors.textMuted, fontSize: 15, fontWeight: '700' },
  rollFeet: { color: colors.textDim, fontSize: 10, fontWeight: '700', marginTop: -5 },
  paceSummary: { alignItems: 'flex-end', flex: 1, paddingBottom: 3, paddingLeft: spacing.md },
  paceLabel: { color: colors.textMuted, fontSize: 9, fontWeight: '800', letterSpacing: 0.7, textTransform: 'uppercase' },
  paceValue: { color: colors.orange, fontSize: 16, fontWeight: '800', marginTop: 5, textAlign: 'right' },
  paceValueGood: { color: colors.accent },
  metricsRow: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
  pathCard: { marginTop: spacing.sm, overflow: 'hidden', padding: spacing.lg },
  pathHeader: { alignItems: 'flex-end', flexDirection: 'row', justifyContent: 'space-between' },
  pathTitle: { color: colors.text, fontSize: 19, fontWeight: '700', marginTop: 3 },
  missCopy: { alignItems: 'flex-end' },
  missLabel: { color: colors.textDim, fontSize: 8, fontWeight: '800', letterSpacing: 0.8 },
  missValue: { color: colors.cyan, fontSize: 13, fontWeight: '800', marginTop: 4 },
  pathLabels: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between', marginTop: -6 },
  pathEdgeLabel: { color: colors.textDim, fontSize: 8, fontWeight: '800', letterSpacing: 0.9 },
  pathScale: { color: colors.textMuted, fontSize: 10, fontWeight: '700' },
  detailCard: { marginTop: spacing.sm, paddingHorizontal: spacing.lg },
  detailRow: { alignItems: 'center', borderBottomColor: colors.line, borderBottomWidth: 1, flexDirection: 'row', justifyContent: 'space-between', minHeight: 44 },
  detailLabel: { color: colors.textMuted, fontSize: 11, fontWeight: '600' },
  detailValue: { color: colors.text, fontSize: 11, fontWeight: '800' },
  emptyCard: { alignItems: 'center', marginTop: spacing.xl, padding: spacing.xl },
  emptyIcon: { alignItems: 'center', backgroundColor: '#1B241A', borderRadius: 28, height: 56, justifyContent: 'center', marginBottom: spacing.md, width: 56 },
  emptyTitle: { color: colors.text, fontSize: 20, fontWeight: '700' },
  emptyBody: { color: colors.textMuted, fontSize: 12, lineHeight: 18, marginTop: spacing.sm, maxWidth: 280, textAlign: 'center' },
  section: { marginTop: spacing.xl },
  listGap: { gap: spacing.sm },
  puttRow: { alignItems: 'center', flexDirection: 'row', minHeight: 74, paddingHorizontal: spacing.md },
  puttNumber: { alignItems: 'baseline', backgroundColor: colors.surfaceRaised, borderRadius: 12, flexDirection: 'row', height: 42, justifyContent: 'center', marginRight: spacing.md, width: 46 },
  puttHash: { color: colors.textDim, fontSize: 10, fontWeight: '700' },
  puttNumberText: { color: colors.text, fontSize: 15, fontWeight: '800' },
  puttMain: { flex: 1 },
  puttDistance: { color: colors.text, fontSize: 20, fontWeight: '800' },
  puttMeta: { color: colors.textMuted, fontSize: 9, fontWeight: '600', marginTop: 2 },
  puttPace: { alignItems: 'flex-end', maxWidth: 112 },
  puttPaceValue: { color: colors.accent, fontSize: 10, fontWeight: '800', textAlign: 'right' },
  puttConfidence: { color: colors.textDim, fontSize: 8, fontWeight: '700', marginTop: 4 },
  modelNote: { alignItems: 'flex-start', flexDirection: 'row', gap: 9, marginTop: spacing.lg, paddingHorizontal: spacing.sm },
  modelNoteText: { color: colors.textMuted, flex: 1, fontSize: 9, lineHeight: 14 },
});
