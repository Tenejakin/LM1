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
import { ClubSelector } from '@/components/ClubSelector';
import { directionLabel, ShotRow, StrikeMap, TrajectoryChart } from '@/components/ShotVisuals';
import { Eyebrow, MetricTile, PrimaryButton, SectionHeader, Surface } from '@/components/ui';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { getClub } from '@/data/clubs';
import { colors, radii, spacing } from '@/theme';
import { Shot } from '@/types';
import { metersToYards } from '@/utils/carry';

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
    arm,
    trigger,
    clearError,
  } = useLaunchMonitor();
  const [pulse] = useState(() => new Animated.Value(0));
  const isPiTest = !isDemo && status?.captureBackend === 'simulator';

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
        return isPiTest
          ? { eyebrow: 'Connection test armed', title: 'Ready to test the link', note: 'No camera is required' }
          : { eyebrow: 'Impact detection active', title: 'Ready for your swing', note: 'Camera buffer is rolling' };
      case 'processing':
        return isPiTest
          ? { eyebrow: 'Test event received', title: 'Checking live data…', note: 'The Pi is sending a synthetic result' }
          : { eyebrow: 'Capture received', title: 'Analyzing shot…', note: 'Tracking ball and clubhead' };
      case 'connecting':
        return { eyebrow: 'Local connection', title: 'Finding your monitor', note: 'This usually takes a moment' };
      case 'error':
      case 'offline':
        return { eyebrow: 'Device offline', title: 'Connect your monitor', note: 'Use the Device tab to get started' };
      default:
        return isPiTest
          ? { eyebrow: 'Pi connected', title: 'Communication ready', note: 'Camera-free test mode' }
          : { eyebrow: 'System ready', title: 'Step in when ready', note: status ? `${status.fps} FPS · ${status.exposureUs} μs exposure` : 'All systems nominal' };
    }
  }, [isPiTest, state, status]);

  const handlePrimary = () => {
    if (state === 'offline' || state === 'error') onOpenDevice();
    else if (state === 'ready') void arm();
    else if (state === 'armed') void trigger();
  };

  const primaryLabel = state === 'ready'
    ? isPiTest ? 'Arm connection test' : 'Arm launch monitor'
    : state === 'armed'
      ? isDemo ? 'Simulate impact' : isPiTest ? 'Send test shot' : 'Manual impact trigger'
      : state === 'processing'
        ? 'Analyzing shot'
        : state === 'connecting'
          ? 'Connecting'
          : 'Connect device';

  return (
    <ScrollView
      contentContainerStyle={[styles.content, { paddingTop: insets.top + spacing.md }]}
      showsVerticalScrollIndicator={false}
    >
      <ScreenHeader state={state} demo={isDemo} />

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
        <PrimaryButton
          label={primaryLabel}
          icon={state === 'ready' ? 'radio' : state === 'armed' ? 'flash' : 'link'}
          onPress={handlePrimary}
          disabled={state === 'processing' || state === 'connecting'}
          loading={state === 'processing' || state === 'connecting'}
        />
      </LinearGradient>

      {activeShot ? (
        <>
          <View style={styles.lastShotHeader}>
            <View>
              <Eyebrow>{activeShot.simulated ? 'Synthetic link test' : 'Latest result'}</Eyebrow>
              <Text style={styles.shotTitle}>Shot #{activeShot.number}</Text>
              <Text style={styles.shotClub}>{getClub(activeShot.clubId).label}</Text>
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

          <Surface style={styles.speedCard}>
            <View>
              <Eyebrow>Ball speed</Eyebrow>
              <View style={styles.speedRow}>
                <Text style={styles.speedValue}>{activeShot.ballSpeedMps.toFixed(1)}</Text>
                <Text style={styles.speedUnit}>m/s</Text>
              </View>
              <Text style={styles.speedSecondary}>
                {(activeShot.ballSpeedMps * 2.23694).toFixed(1)} mph
              </Text>
            </View>
            <View style={styles.carryColumn}>
              <Text style={styles.carryLabel}>Estimated carry</Text>
              <View style={styles.carryValueRow}>
                <Text style={styles.carryValue}>{activeShot.estimatedCarryM}</Text>
                <Text style={styles.carryUnit}>m</Text>
              </View>
              <Text style={styles.carryYards}>{metersToYards(activeShot.estimatedCarryM)} yd</Text>
              <View style={styles.confidencePill}>
                <Ionicons name="checkmark-circle" color={colors.accent} size={14} />
                <Text style={styles.confidenceText}>{Math.round(activeShot.confidence * 100)}% confidence</Text>
              </View>
            </View>
          </Surface>

          <View style={styles.metricsRow}>
            <MetricTile label="Club speed" value={activeShot.clubSpeedMps.toFixed(1)} unit="m/s" />
            <MetricTile label="Smash" value={activeShot.smashFactor.toFixed(2)} accent />
            <MetricTile label="Launch" value={activeShot.launchAngleDeg.toFixed(1)} unit="deg" />
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
          <View style={styles.emptyIcon}>
            <Ionicons name="golf-outline" size={28} color={colors.accent} />
          </View>
          <Text style={styles.emptyTitle}>Your next shot starts here</Text>
          <Text style={styles.emptyBody}>Connect and arm the monitor. Results will appear automatically after impact.</Text>
        </Surface>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { paddingHorizontal: spacing.md, paddingBottom: 110 },
  errorBanner: {
    alignItems: 'center',
    backgroundColor: '#241718',
    borderColor: '#4C2929',
    borderRadius: radii.md,
    borderWidth: 1,
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.md,
    padding: spacing.md,
  },
  errorText: { color: '#F0B0AC', flex: 1, fontSize: 12, fontWeight: '600', lineHeight: 17 },
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
  heroNote: { color: colors.textMuted, fontSize: 12, fontWeight: '600', marginTop: 5 },
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
  shotClub: { color: colors.textMuted, fontSize: 11, fontWeight: '700', marginTop: 2 },
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
  speedSecondary: { color: colors.textDim, fontSize: 11, fontWeight: '600', marginTop: -5 },
  carryColumn: { alignItems: 'flex-end', paddingBottom: 2 },
  carryLabel: { color: colors.textMuted, fontSize: 9, fontWeight: '800', letterSpacing: 0.8, textTransform: 'uppercase' },
  carryValueRow: { alignItems: 'baseline', flexDirection: 'row', gap: 4, marginTop: 2 },
  carryValue: { color: colors.accent, fontSize: 33, fontWeight: '700', letterSpacing: -1.4 },
  carryUnit: { color: colors.textMuted, fontSize: 12, fontWeight: '700' },
  carryYards: { color: colors.textDim, fontSize: 10, fontWeight: '600', marginTop: -3 },
  confidencePill: { alignItems: 'center', flexDirection: 'row', gap: 5, marginTop: 7 },
  confidenceText: { color: colors.textMuted, fontSize: 10, fontWeight: '700' },
  metricsRow: { flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.sm },
  visualGrid: { flexDirection: 'row', gap: spacing.sm },
  visualCard: { flex: 1, minHeight: 175, overflow: 'hidden', padding: spacing.md },
  cardTitleRow: { flexDirection: 'row', justifyContent: 'space-between' },
  cardTitle: { color: colors.text, fontSize: 16, fontWeight: '700', marginTop: 3 },
  smallIcon: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderRadius: 12, height: 32, justifyContent: 'center', width: 32 },
  section: { marginTop: spacing.xl },
  listGap: { gap: spacing.sm },
  emptyCard: { alignItems: 'center', padding: spacing.xl },
  emptyIcon: { alignItems: 'center', backgroundColor: '#1B241A', borderRadius: 28, height: 56, justifyContent: 'center', marginBottom: spacing.md, width: 56 },
  emptyTitle: { color: colors.text, fontSize: 20, fontWeight: '700' },
  emptyBody: { color: colors.textMuted, fontSize: 13, lineHeight: 19, marginTop: spacing.sm, maxWidth: 270, textAlign: 'center' },
});
