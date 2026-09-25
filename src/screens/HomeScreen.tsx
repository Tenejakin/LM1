import Ionicons from '@expo/vector-icons/Ionicons';
import { LinearGradient } from 'expo-linear-gradient';
import React, { useEffect, useMemo, useState } from 'react';
import {
  Animated,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ScreenHeader } from '@/components/ScreenHeader';
import { CaptureReview } from '@/components/CaptureReview';
import { ReadinessCard } from '@/components/ReadinessCard';
import { SwingLoop } from '@/components/SwingLoop';
import { ClubSelector } from '@/components/ClubSelector';
import { directionLabel, ShotRow, StrikeMap, TrajectoryChart } from '@/components/ShotVisuals';
import { Eyebrow, HelpText, MetricTile, PrimaryButton, SectionHeader, StepRow, Surface } from '@/components/ui';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { useUnits } from '@/context/UnitsContext';
import { colors, radii, spacing } from '@/theme';
import { Shot } from '@/types';
import { shotEstimates } from '@/utils/carry';
import { shotClubLabel } from '@/utils/bagClubs';
import { measuredAttackAngle, measuredClubPath, measuredClubSpeed, measuredSmash } from '@/utils/shotValues';

export function HomeScreen({
  onOpenDevice,
  onOpenHistory,
  onOpenShot,
}: {
  onOpenDevice: () => void;
  onOpenHistory: () => void;
  onOpenShot: (shot: Shot) => void;
}) {
  const insets = useSafeAreaInsets();
  const {
    state,
    status,
    shots,
    activeShot,
    isDemo,
    error,
    ballDetected,
    captureMode,
    arm,
    trigger,
    clearError,
  } = useLaunchMonitor();
  const units = useUnits();
  const [pulse] = useState(() => new Animated.Value(0));
  const automaticCapture = !isDemo && Boolean(status?.automaticCapture);
  const isPiTest = !isDemo && !automaticCapture && status?.captureBackend === 'simulator';
  const switchingFromPutting = captureMode === 'putting' && (state === 'ready' || state === 'armed');

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, {
          toValue: 1,
          duration: 1_100,
          useNativeDriver: Platform.OS !== 'web',
        }),
        Animated.timing(pulse, {
          toValue: 0,
          duration: 1_100,
          useNativeDriver: Platform.OS !== 'web',
        }),
      ]),
    );
    if (state === 'armed' || state === 'processing') loop.start();
    else {
      loop.stop();
      pulse.setValue(0);
    }
    return () => loop.stop();
  }, [pulse, state]);

  const recentShots = shots.slice(0, 3);
  const heroCopy = useMemo(() => {
    switch (state) {
      case 'armed':
        if (captureMode === 'putting') return { eyebrow: 'Putting mode active', title: 'Switch to normal shot', note: 'Change mode before your next swing' };
        return isPiTest
          ? { eyebrow: 'Connection test armed', title: 'Ready to test the link', note: 'No camera is required' }
          : { eyebrow: 'Impact detection active', title: 'Ready for your swing', note: 'Camera buffer is rolling' };
      case 'processing':
        return isPiTest
          ? { eyebrow: 'Test event received', title: 'Checking live data…', note: 'The Pi is sending a synthetic result' }
          : { eyebrow: 'Capture received', title: 'Analyzing capture…', note: 'Checking ball motion and image evidence' };
      case 'connecting':
        return { eyebrow: 'Connecting', title: 'Finding your LM1', note: 'Keep your phone near the monitor' };
      case 'error':
      case 'offline':
        return { eyebrow: 'Not connected', title: 'Connect your LM1', note: 'Tap below and we will walk you through it' };
      default:
        if (captureMode === 'putting') return { eyebrow: 'Putting mode selected', title: 'Ready to switch modes', note: 'Choose normal shot before placing the ball' };
        return isPiTest
          ? { eyebrow: 'Connected', title: 'Everything is talking', note: 'Test mode — no camera needed yet' }
          : { eyebrow: 'Ready', title: status?.camera?.ballDetection?.state === 'calibrating' ? 'Keep the hitting area empty' : 'Place a ball in the hitting area', note: status ? `Camera running at ${status.fps} frames per second` : 'Connect a camera to begin' };
    }
  }, [captureMode, isPiTest, state, status]);

  const handlePrimary = () => {
    if (state === 'offline' || state === 'error') onOpenDevice();
    else if (state === 'ready') void arm();
    else if (state === 'armed') void (captureMode === 'putting' ? arm() : trigger());
  };

  const primaryLabel = switchingFromPutting
    ? state === 'armed' ? 'Switch to normal shot' : 'Arm normal shot'
    : automaticCapture && (state === 'ready' || state === 'armed')
    ? state === 'armed'
      ? ballDetected ? 'Ball detected · swing away' : 'Watching · place your ball'
      : 'Watching for your ball'
    : state === 'ready'
    ? isPiTest ? 'Start connection test' : 'Start tracking'
    : state === 'armed'
      ? isDemo ? 'Play a sample shot' : isPiTest ? 'Send a test shot' : 'Record a shot now'
      : state === 'processing'
        ? 'Reading your shot'
        : state === 'connecting'
          ? 'Connecting'
          : 'Connect your LM1';

  /** One line telling the player exactly what the button will do. */
  const primaryHint = switchingFromPutting
    ? ballDetected ? 'Remove the ball before changing modes.' : 'One tap changes the Pi to normal shot mode.'
    : automaticCapture && (state === 'ready' || state === 'armed')
    ? 'The camera triggers on its own — no need to press anything.'
    : state === 'ready'
      ? 'Starts watching the hitting area for your next strike.'
      : state === 'armed'
        ? 'Only needed if the camera does not pick the strike up by itself.'
        : null;
  const activeClubSpeed = activeShot ? measuredClubSpeed(activeShot) : null;
  const activeSmash = activeShot ? measuredSmash(activeShot) : null;
  const activeAttack = activeShot ? measuredAttackAngle(activeShot) : null;
  const activeClubPath = activeShot ? measuredClubPath(activeShot) : null;
  const activeEstimates = useMemo(() => (activeShot ? shotEstimates(activeShot) : null), [activeShot]);

  return (
    <ScrollView
      contentContainerStyle={[styles.content, { paddingTop: insets.top + spacing.md }]}
      showsVerticalScrollIndicator={false}
    >
      <ScreenHeader state={state} demo={isDemo} />

      {error ? (
        <View style={styles.errorBanner}>
          <View style={styles.errorTop}>
            <Ionicons name="alert-circle" size={18} color={colors.red} />
            <Text style={styles.errorText}>{error}</Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Dismiss this message"
              hitSlop={10}
              onPress={clearError}
            >
              <Ionicons name="close" size={18} color={colors.textMuted} />
            </Pressable>
          </View>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Open the Device tab to fix this"
            onPress={onOpenDevice}
            style={({ pressed }) => [styles.errorAction, pressed && styles.pressed]}
          >
            <Text style={styles.errorActionText}>Open Device to fix this</Text>
            <Ionicons name="arrow-forward" size={14} color={colors.accent} />
          </Pressable>
        </View>
      ) : null}

      <ClubSelector disabled={state === 'armed' || state === 'processing' || state === 'connecting'} />

      <LinearGradient
        colors={['#1B241C', '#101513', '#0E1214']}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={styles.hero}
      >
        <View style={styles.heroGlow} />
        <View style={styles.heroTop}>
          <View style={styles.heroCopy}>
            <Eyebrow>{heroCopy.eyebrow}</Eyebrow>
            <Text style={styles.heroTitle}>{heroCopy.title}</Text>
            <Text style={styles.heroNote}>{heroCopy.note}</Text>
          </View>
          <View style={styles.sensorWrap}>
            <Animated.View
              style={[
                styles.sensorPulse,
                {
                  opacity: pulse.interpolate({ inputRange: [0, 1], outputRange: [0.15, 0.02] }),
                  transform: [{ scale: pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 1.6] }) }],
                },
              ]}
            />
            <View style={[styles.sensor, state === 'armed' && styles.sensorArmed]}>
              <Ionicons
                name={state === 'processing' ? 'analytics' : 'scan'}
                size={24}
                color={state === 'offline' || state === 'error' ? colors.textDim : colors.accent}
              />
            </View>
          </View>
        </View>
        {state !== 'offline' && state !== 'error' && state !== 'connecting' ? (
          <Text style={styles.modeLabel}>CAPTURE MODE · {captureMode === 'putting' ? 'PUTTING' : 'NORMAL SHOT'}</Text>
        ) : null}
        <PrimaryButton
          label={primaryLabel}
          icon={state === 'ready' ? 'radio' : state === 'armed' ? 'flash' : 'link'}
          onPress={handlePrimary}
          disabled={state === 'processing' || state === 'connecting' || (switchingFromPutting && ballDetected) || (automaticCapture && !switchingFromPutting && (state === 'ready' || state === 'armed'))}
          loading={state === 'processing' || state === 'connecting'}
        />
        {primaryHint ? <Text style={styles.heroHint}>{primaryHint}</Text> : null}
      </LinearGradient>

      {automaticCapture && (state === 'ready' || state === 'armed') ? <ReadinessCard readiness={status?.readiness} /> : null}

      <CaptureReview />

      {activeShot && (!automaticCapture || activeShot.measurementSource) ? (
        <>
          <View style={styles.lastShotHeader}>
            <View>
              <Eyebrow>{activeShot.measurementSource ? 'Camera estimate' : activeShot.simulated ? 'Test shot' : 'Latest shot'}</Eyebrow>
              <Text style={styles.shotTitle}>Shot #{activeShot.number}</Text>
              <Text style={styles.shotClub}>{shotClubLabel(activeShot)}</Text>
            </View>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`Open details for shot ${activeShot.number}`}
              onPress={() => onOpenShot(activeShot)}
              style={({ pressed }) => [styles.reviewButton, pressed && styles.pressed]}
            >
              <Text style={styles.reviewText}>Review</Text>
              <Ionicons name="arrow-forward" size={15} color={colors.accent} />
            </Pressable>
          </View>

          <SwingLoop shot={activeShot} />

          <Surface style={styles.speedCard}>
            <View>
              <Eyebrow>Ball speed</Eyebrow>
              <View style={styles.speedRow}>
                <Text style={styles.speedValue}>{units.speed(activeShot.ballSpeedMps)}</Text>
                <Text style={styles.speedUnit}>{units.speedLabel}</Text>
              </View>
              <Text style={styles.speedSecondary}>
                {units.altSpeedWithUnit(activeShot.ballSpeedMps)}
              </Text>
            </View>
            <View style={styles.carryColumn}>
              <Text style={styles.carryLabel}>Estimated carry</Text>
              <View style={styles.carryValueRow}>
                <Text style={styles.carryValue}>{units.distance(activeShot.estimatedCarryM)}</Text>
                <Text style={styles.carryUnit}>{units.distanceLabel}</Text>
              </View>
              <Text style={styles.carryYards}>{units.altDistanceWithUnit(activeShot.estimatedCarryM)}</Text>
              {activeEstimates ? (
                <Text style={styles.carryYards}>
                  Total ~{units.distanceWithUnit(activeEstimates.totalM)} · apex {units.distanceWithUnit(activeEstimates.flight.apexM, 1)}
                </Text>
              ) : null}
              <View style={styles.confidencePill}>
                <Ionicons name="checkmark-circle" color={colors.accent} size={14} />
                <Text style={styles.confidenceText}>{activeShot.measurementSource ? 'Estimate · not yet validated' : `${Math.round(activeShot.confidence * 100)}% confidence`}</Text>
              </View>
            </View>
          </Surface>

          <View style={styles.metricsRow}>
            <MetricTile label="Club speed" value={activeClubSpeed === null ? '—' : units.speed(activeClubSpeed)} unit={units.speedLabel} />
            <MetricTile label="Smash" value={activeSmash === null ? '—' : activeSmash.toFixed(2)} accent />
            <MetricTile label="Launch" value={activeShot.launchAngleDeg.toFixed(1)} unit="deg" />
          </View>
          <View style={styles.metricsRow}>
            <MetricTile label="Attack angle" value={activeAttack === null ? '—' : activeAttack.toFixed(1)} unit="deg" />
            <MetricTile label="Club path" value={activeClubPath === null ? '—' : directionLabel(activeClubPath)} />
          </View>

          <View style={styles.visualGrid}>
            <Surface style={styles.visualCard}>
              <View style={styles.cardTitleRow}>
                <View>
                  <Eyebrow>Ball flight</Eyebrow>
                  <Text style={styles.cardTitle}>{directionLabel(activeShot.startDirectionDeg)}</Text>
                </View>
                <View style={styles.smallIcon}>
                  <Ionicons name="navigate" size={16} color={colors.cyan} />
                </View>
              </View>
              <TrajectoryChart shot={activeShot} compact />
            </Surface>
            <Surface style={styles.visualCard}>
              <View style={styles.cardTitleRow}>
                <View>
                  <Eyebrow>Strike</Eyebrow>
                  <Text style={styles.cardTitle}>Face map</Text>
                </View>
                <View style={styles.smallIcon}>
                  <Ionicons name="locate" size={16} color={colors.accent} />
                </View>
              </View>
              <StrikeMap shot={activeShot} compact />
            </Surface>
          </View>

          <View style={styles.section}>
            <SectionHeader title="Recent shots" action="View session" onAction={onOpenHistory} />
            <View style={styles.listGap}>
              {recentShots.map((shot) => (
                <ShotRow key={shot.id} shot={shot} onPress={() => onOpenShot(shot)} />
              ))}
            </View>
          </View>
        </>
      ) : (
        <Surface style={styles.emptyCard}>
          <View style={styles.emptyHeader}>
            <View style={styles.emptyIcon}>
              <Ionicons name="golf-outline" size={24} color={colors.accent} />
            </View>
            <View style={styles.emptyHeaderCopy}>
              <Text style={styles.emptyTitle}>Your next shot starts here</Text>
              <HelpText>Three steps and you are hitting.</HelpText>
            </View>
          </View>
          <View style={styles.steps}>
            <StepRow
              index={1}
              title="Connect your LM1"
              body="Turn on Bluetooth and stand near the monitor."
              done={state !== 'offline' && state !== 'error'}
            />
            <StepRow
              index={2}
              title="Pick the club you are hitting"
              body="Carry estimates use the club you choose above."
              done={state !== 'offline' && state !== 'error'}
            />
            <StepRow
              index={3}
              title="Place a ball and swing"
              body="Results appear here on their own after impact."
              done={shots.length > 0}
            />
          </View>
          {state === 'offline' || state === 'error' ? (
            <View style={styles.emptyActions}>
              <PrimaryButton label="Connect your LM1" icon="bluetooth" onPress={onOpenDevice} />
              <Text style={styles.emptyAside}>No monitor yet? Try the demo from the Device tab.</Text>
            </View>
          ) : null}
        </Surface>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { paddingHorizontal: spacing.md, paddingBottom: 110 },
  errorBanner: {
    backgroundColor: '#241718',
    borderColor: '#4C2929',
    borderRadius: radii.md,
    borderWidth: 1,
    gap: spacing.sm,
    marginBottom: spacing.md,
    padding: spacing.md,
  },
  errorTop: { alignItems: 'flex-start', flexDirection: 'row', gap: spacing.sm },
  errorText: { color: '#F0B0AC', flex: 1, fontSize: 13, fontWeight: '600', lineHeight: 18 },
  errorAction: { alignItems: 'center', flexDirection: 'row', gap: 5, minHeight: 32 },
  errorActionText: { color: colors.accent, fontSize: 13, fontWeight: '700' },
  hero: {
    borderColor: '#34402F',
    borderRadius: radii.xl,
    borderWidth: 1,
    marginBottom: spacing.xl,
    overflow: 'hidden',
    padding: spacing.lg,
  },
  heroGlow: {
    backgroundColor: colors.accent,
    borderRadius: 110,
    height: 180,
    opacity: 0.035,
    position: 'absolute',
    right: -50,
    top: -70,
    width: 180,
  },
  heroTop: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: spacing.lg },
  heroCopy: { flex: 1, paddingRight: spacing.md },
  heroTitle: { color: colors.text, fontSize: 27, fontWeight: '700', letterSpacing: -1, marginTop: 7 },
  heroNote: { color: colors.textMuted, fontSize: 13, fontWeight: '600', marginTop: 5 },
  heroHint: { color: colors.textMuted, fontSize: 12, lineHeight: 16, marginTop: spacing.sm, textAlign: 'center' },
  modeLabel: { color: colors.accent, fontSize: 11, fontWeight: '800', letterSpacing: 1.1, marginBottom: spacing.sm, textAlign: 'center' },
  sensorWrap: { alignItems: 'center', height: 64, justifyContent: 'center', width: 64 },
  sensorPulse: { backgroundColor: colors.accent, borderRadius: 32, height: 64, position: 'absolute', width: 64 },
  sensor: {
    alignItems: 'center',
    backgroundColor: colors.surfaceRaised,
    borderColor: colors.lineStrong,
    borderRadius: 25,
    borderWidth: 1,
    height: 50,
    justifyContent: 'center',
    width: 50,
  },
  sensorArmed: { backgroundColor: '#17221B', borderColor: '#45613E' },
  lastShotHeader: { alignItems: 'flex-end', flexDirection: 'row', justifyContent: 'space-between', marginBottom: spacing.md },
  shotTitle: { color: colors.text, fontSize: 24, fontWeight: '700', letterSpacing: -0.6, marginTop: 3 },
  shotClub: { color: colors.textMuted, fontSize: 12, fontWeight: '700', marginTop: 2 },
  reviewButton: { alignItems: 'center', flexDirection: 'row', gap: 5, paddingVertical: 6 },
  reviewText: { color: colors.accent, fontSize: 13, fontWeight: '700' },
  pressed: { opacity: 0.65 },
  speedCard: {
    alignItems: 'flex-end',
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
    padding: spacing.lg,
  },
  speedRow: { alignItems: 'baseline', flexDirection: 'row', gap: 8, marginTop: 2 },
  speedValue: { color: colors.text, fontSize: 56, fontWeight: '700', letterSpacing: -3.2 },
  speedUnit: { color: colors.textMuted, fontSize: 16, fontWeight: '700' },
  speedSecondary: { color: colors.textDim, fontSize: 12, fontWeight: '600', marginTop: -4 },
  carryColumn: { alignItems: 'flex-end', paddingBottom: 2 },
  carryLabel: { color: colors.textMuted, fontSize: 10, fontWeight: '800', letterSpacing: 0.8, textTransform: 'uppercase' },
  carryValueRow: { alignItems: 'baseline', flexDirection: 'row', gap: 4, marginTop: 2 },
  carryValue: { color: colors.accent, fontSize: 33, fontWeight: '700', letterSpacing: -1.4 },
  carryUnit: { color: colors.textMuted, fontSize: 12, fontWeight: '700' },
  carryYards: { color: colors.textDim, fontSize: 11, fontWeight: '600', marginTop: -2 },
  confidencePill: { alignItems: 'center', flexDirection: 'row', gap: 5, marginTop: 7 },
  confidenceText: { color: colors.textMuted, fontSize: 11, fontWeight: '700' },
  metricsRow: { flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.sm },
  visualGrid: { flexDirection: 'row', gap: spacing.sm },
  visualCard: { flex: 1, minHeight: 175, overflow: 'hidden', padding: spacing.md },
  cardTitleRow: { flexDirection: 'row', justifyContent: 'space-between' },
  cardTitle: { color: colors.text, fontSize: 16, fontWeight: '700', marginTop: 3 },
  smallIcon: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderRadius: 12, height: 32, justifyContent: 'center', width: 32 },
  section: { marginTop: spacing.xl },
  listGap: { gap: spacing.sm },
  emptyCard: { gap: spacing.lg, padding: spacing.lg },
  emptyHeader: { alignItems: 'center', flexDirection: 'row', gap: spacing.sm },
  emptyHeaderCopy: { flex: 1 },
  emptyIcon: { alignItems: 'center', backgroundColor: '#1B241A', borderRadius: 24, height: 48, justifyContent: 'center', width: 48 },
  emptyTitle: { color: colors.text, fontSize: 19, fontWeight: '700' },
  steps: { gap: spacing.md },
  emptyActions: { gap: spacing.sm },
  emptyAside: { color: colors.textMuted, fontSize: 12, lineHeight: 16, textAlign: 'center' },
});
