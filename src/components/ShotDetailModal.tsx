import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, GestureResponderEvent, Image, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { StrikeMap, TrajectoryChart } from '@/components/ShotVisuals';
import { Eyebrow, IconButton, MetricTile, Surface } from '@/components/ui';
import { getClub } from '@/data/clubs';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { useUnits } from '@/context/UnitsContext';
import { colors, radii, spacing } from '@/theme';
import { CaptureFramePreview, Shot, ShotMetricKey } from '@/types';
import { ContactSheet } from '@/components/ContactSheet';

export function ShotDetailModal({ shot, onClose }: { shot: Shot | null; onClose: () => void }) {
  return (
    <Modal animationType="slide" onRequestClose={onClose} presentationStyle="pageSheet" visible={Boolean(shot)}>
      {shot ? <ShotDetail shot={shot} onClose={onClose} /> : null}
    </Modal>
  );
}

function ShotDetail({ shot, onClose }: { shot: Shot; onClose: () => void }) {
  const insets = useSafeAreaInsets();
  const units = useUnits();
  return (
    <View style={styles.root}>
      <ScrollView
        contentContainerStyle={[styles.content, { paddingTop: Math.max(insets.top, spacing.md) }]}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.header}>
          <View>
            <Eyebrow>Shot review</Eyebrow>
            <Text style={styles.title}>Shot #{shot.number}</Text>
            <Text style={styles.clubName}>{getClub(shot.clubId).label}</Text>
          </View>
          <IconButton icon="close" label="Close shot details" onPress={onClose} />
        </View>

        <Surface style={styles.hero}>
          <View style={styles.heroTop}>
            <View>
              <Eyebrow>Ball speed</Eyebrow>
              <View style={styles.speedRow}>
                <Text style={styles.speed}>{units.speed(shot.ballSpeedMps)}</Text>
                <Text style={styles.unit}>{units.speedLabel}</Text>
              </View>
              <Text style={styles.mph}>{units.altSpeedWithUnit(shot.ballSpeedMps)}</Text>
              <ConfidenceNote shot={shot} metric="ballSpeedMps" />
            </View>
            <View style={styles.heroAside}>
              <Text style={styles.carryLabel}>Estimated carry</Text>
              <View style={styles.carryRow}>
                <Text style={styles.carryValue}>{units.distance(shot.estimatedCarryM)}</Text>
                <Text style={styles.carryUnit}>{units.distanceLabel}</Text>
              </View>
              <Text style={styles.carryYards}>{units.altDistanceWithUnit(shot.estimatedCarryM)}</Text>
              <ConfidenceNote shot={shot} metric="estimatedCarryM" />
              <View style={styles.quality}>
                <Ionicons name="shield-checkmark" size={14} color={colors.accent} />
                <Text style={styles.qualityValue}>{shot.measurementSource ? 'Estimate' : `${Math.round(shot.confidence * 100)}%`}</Text>
                <Text style={styles.qualityLabel}>{shot.measurementSource ? 'Unvalidated' : 'confidence'}</Text>
              </View>
            </View>
          </View>
          <View style={styles.metricRow}>
            <MetricTile label="Club speed" value={units.speed(shot.clubSpeedMps)} unit={units.speedLabel} note={confidenceText(shot, 'clubSpeedMps')} />
            <MetricTile label="Smash" value={shot.smashFactor.toFixed(2)} accent note={confidenceText(shot, 'smashFactor')} />
            <MetricTile label="Launch" value={shot.launchAngleDeg.toFixed(1)} unit="deg" note={confidenceText(shot, 'launchAngleDeg')} />
          </View>
          <View style={styles.metricRowSecondary}>
            <MetricTile label="Backspin" value={Math.round(shot.spinRpm ?? 0).toLocaleString()} unit="rpm" note={confidenceText(shot, 'spinRpm')} />
            <MetricTile label="Spin axis" value={(shot.spinAxisDeg ?? 0).toFixed(1)} unit="deg" note={confidenceText(shot, 'spinAxisDeg')} />
            <MetricTile label="Direction" value={shot.startDirectionDeg.toFixed(1)} unit="deg" note={confidenceText(shot, 'startDirectionDeg')} />
          </View>
          <Text style={styles.carryNote}>Estimated values use the selected club and available launch data. The small percentage on each value is its confidence.</Text>
        </Surface>

        {shot.captureId ? <ContactSheet captureId={shot.captureId} card /> : null}

        {shot.captureId ? <ShotFrameReview shot={shot} /> : null}

        <Surface style={styles.visualCard}>
          <View style={styles.visualHeader}>
            <View>
              <Eyebrow>Initial trajectory</Eyebrow>
              <Text style={styles.visualTitle}>Ball flight</Text>
            </View>
            <Ionicons name="navigate" size={19} color={colors.cyan} />
          </View>
          <TrajectoryChart shot={shot} />
        </Surface>

        <Surface style={styles.visualCard}>
          <View style={styles.visualHeader}>
            <View>
              <Eyebrow>Estimated contact</Eyebrow>
              <Text style={styles.visualTitle}>Clubface strike</Text>
            </View>
            <Ionicons name="locate" size={19} color={colors.accent} />
          </View>
          <StrikeMap shot={shot} />
        </Surface>

        <View style={styles.technicalHeader}>
          <Text style={styles.technicalTitle}>Capture details</Text>
          <Text style={styles.technicalNote}>For diagnosis & replay</Text>
        </View>
        <Surface style={styles.technicalCard}>
          <DetailRow label="Frames retained" value={`${shot.frameCount}`} />
          <DetailRow label="Capture window" value={`${shot.captureDurationMs} ms`} />
          <DetailRow label="Confidence" value={shot.measurementSource ? 'Not validated' : `${Math.round(shot.confidence * 100)}%`} accent />
          <DetailRow label="Captured" value={formatTimestamp(shot.capturedAt)} last />
        </Surface>

        <Pressable
          accessibilityRole="button"
          onPress={onClose}
          style={({ pressed }) => [styles.doneButton, pressed && styles.donePressed]}
        >
          <Text style={styles.doneText}>Done</Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}

function confidenceText(shot: Shot, metric: ShotMetricKey): string | undefined {
  const quality = shot.metricConfidence?.[metric];
  if (!quality) return undefined;
  const label = quality.source === 'measured' ? 'measured' : quality.source === 'device-estimate' ? 'camera estimate' : 'club estimate';
  return `${Math.round(quality.confidence * 100)}% · ${label}`;
}

function ConfidenceNote({ shot, metric }: { shot: Shot; metric: ShotMetricKey }) {
  const value = confidenceText(shot, metric);
  return value ? <Text style={styles.confidenceNote}>{value}</Text> : null;
}

function ShotFrameReview({ shot }: { shot: Shot }) {
  const { getCaptureFrame } = useLaunchMonitor();
  const initialIndex = Math.max(0, Math.min(shot.frameCount - 1, shot.firstMovingFrameIndex ?? shot.impactFrameIndex ?? 0));
  const [frameIndex, setFrameIndex] = useState(initialIndex);
  const [frame, setFrame] = useState<CaptureFramePreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timelineWidth, setTimelineWidth] = useState(1);
  const cache = useRef(new Map<number, CaptureFramePreview>());

  useEffect(() => {
    setFrameIndex(initialIndex);
    setFrame(null);
    setError(null);
    cache.current.clear();
  }, [initialIndex, shot.captureId]);

  useEffect(() => {
    if (!shot.captureId) return;
    const cached = cache.current.get(frameIndex);
    if (cached) {
      setFrame(cached);
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void getCaptureFrame(shot.captureId, frameIndex)
      .then((nextFrame) => {
        if (cancelled) return;
        cache.current.set(frameIndex, nextFrame);
        setFrame(nextFrame);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : 'Could not load this frame.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [frameIndex, getCaptureFrame, shot.captureId]);

  const frameCount = frame?.frameCount ?? shot.frameCount;
  const selectFromTimeline = (event: GestureResponderEvent) => {
    const ratio = Math.max(0, Math.min(1, event.nativeEvent.locationX / timelineWidth));
    setFrameIndex(Math.round(ratio * Math.max(0, frameCount - 1)));
  };
  const previewUri = frame ? `data:${frame.mimeType};base64,${frame.base64}` : null;
  const contactWindow = shot.lastStationaryFrameIndex !== undefined && shot.firstMovingFrameIndex !== undefined
    ? [shot.lastStationaryFrameIndex, shot.firstMovingFrameIndex] as const
    : null;
  const framePercent = (index: number) => frameCount > 1 ? index / (frameCount - 1) * 100 : 0;

  return (
    <Surface style={styles.replayCard}>
      <View style={styles.visualHeader}>
        <View>
          <Eyebrow>Camera capture</Eyebrow>
          <Text style={styles.visualTitle}>Frame-by-frame replay</Text>
        </View>
        <Text style={styles.frameCounter}>{frameIndex + 1} / {frameCount}</Text>
      </View>
      <View style={styles.frameViewport}>
        {previewUri ? <Image source={{ uri: previewUri }} style={styles.frameImage} /> : null}
        {loading ? <View style={styles.frameLoading}><ActivityIndicator color={colors.accent} /></View> : null}
      </View>
      <Pressable
        accessibilityLabel="Select capture frame"
        accessibilityRole="adjustable"
        onLayout={(event) => setTimelineWidth(event.nativeEvent.layout.width)}
        onPress={selectFromTimeline}
        style={styles.timeline}
      >
        <View style={[styles.timelineProgress, { width: `${frameCount > 1 ? frameIndex / (frameCount - 1) * 100 : 0}%` }]} />
        {contactWindow ? (
          <View style={[styles.contactWindow, {
            left: `${framePercent(contactWindow[0])}%`,
            width: `${Math.max(0.6, framePercent(contactWindow[1]) - framePercent(contactWindow[0]))}%`,
          }]} />
        ) : shot.impactFrameIndex !== undefined ? (
          <View style={[styles.impactMarker, { left: `${framePercent(shot.impactFrameIndex)}%` }]} />
        ) : null}
        {shot.coarseDepartureFrameIndex !== undefined ? (
          <View style={[styles.coarseMarker, { left: `${framePercent(shot.coarseDepartureFrameIndex)}%` }]} />
        ) : null}
      </Pressable>
      <View style={styles.frameControls}>
        <FrameButton icon="play-back" label="10 frames back" disabled={frameIndex === 0 || loading} onPress={() => setFrameIndex((value) => Math.max(0, value - 10))} />
        <FrameButton icon="chevron-back" label="Previous frame" disabled={frameIndex === 0 || loading} onPress={() => setFrameIndex((value) => Math.max(0, value - 1))} />
        <Text style={styles.frameTime}>{frame?.timeMs?.toFixed(1) ?? '—'} ms</Text>
        <FrameButton icon="chevron-forward" label="Next frame" disabled={frameIndex >= frameCount - 1 || loading} onPress={() => setFrameIndex((value) => Math.min(frameCount - 1, value + 1))} />
        <FrameButton icon="play-forward" label="10 frames forward" disabled={frameIndex >= frameCount - 1 || loading} onPress={() => setFrameIndex((value) => Math.min(frameCount - 1, value + 10))} />
      </View>
      <Text style={styles.replayNote}>
        {contactWindow
          ? `Orange is the contact window: stationary frame ${contactWindow[0] + 1} to first-motion frame ${contactWindow[1] + 1}. The gray tick is the later detector trigger.`
          : 'Orange is the best available departure estimate. A gray tick is the sampled detector trigger, not measured impact.'}
      </Text>
      {error ? <Text style={styles.replayError}>{error}</Text> : null}
    </Surface>
  );
}

function FrameButton({ icon, label, disabled, onPress }: { icon: React.ComponentProps<typeof Ionicons>['name']; label: string; disabled: boolean; onPress: () => void }) {
  return (
    <Pressable accessibilityLabel={label} accessibilityRole="button" disabled={disabled} onPress={onPress} style={({ pressed }) => [styles.frameButton, disabled && styles.frameButtonDisabled, pressed && styles.frameButtonPressed]}>
      <Ionicons name={icon} size={19} color={colors.text} />
    </Pressable>
  );
}

function DetailRow({
  label,
  value,
  accent,
  last,
}: {
  label: string;
  value: string;
  accent?: boolean;
  last?: boolean;
}) {
  return (
    <View style={[styles.detailRow, last && styles.detailRowLast]}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={[styles.detailValue, accent && styles.detailAccent]}>{value}</Text>
    </View>
  );
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value));
}

const styles = StyleSheet.create({
  root: { backgroundColor: colors.background, flex: 1 },
  content: { paddingBottom: 50, paddingHorizontal: spacing.md },
  header: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between', marginBottom: spacing.xl },
  title: { color: colors.text, fontSize: 28, fontWeight: '700', letterSpacing: -0.9, marginTop: 3 },
  clubName: { color: colors.accent, fontSize: 11, fontWeight: '800', marginTop: 2 },
  hero: { padding: spacing.lg },
  heroTop: { alignItems: 'flex-start', flexDirection: 'row', justifyContent: 'space-between' },
  speedRow: { alignItems: 'baseline', flexDirection: 'row', gap: 7, marginTop: 1 },
  speed: { color: colors.text, fontSize: 58, fontWeight: '700', letterSpacing: -3.4 },
  unit: { color: colors.textMuted, fontSize: 16, fontWeight: '700' },
  mph: { color: colors.textDim, fontSize: 11, fontWeight: '700', marginTop: -5 },
  heroAside: { alignItems: 'flex-end' },
  carryLabel: { color: colors.textMuted, fontSize: 9, fontWeight: '800', letterSpacing: 0.7, textTransform: 'uppercase' },
  carryRow: { alignItems: 'baseline', flexDirection: 'row', gap: 4, marginTop: 2 },
  carryValue: { color: colors.accent, fontSize: 35, fontWeight: '700', letterSpacing: -1.4 },
  carryUnit: { color: colors.textMuted, fontSize: 12, fontWeight: '700' },
  carryYards: { color: colors.textDim, fontSize: 10, fontWeight: '700', marginTop: -4 },
  quality: { alignItems: 'center', flexDirection: 'row', gap: 4, marginTop: 8 },
  qualityValue: { color: colors.text, fontSize: 11, fontWeight: '800' },
  qualityLabel: { color: colors.textDim, fontSize: 9, fontWeight: '600' },
  metricRow: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.lg },
  metricRowSecondary: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
  confidenceNote: { color: colors.textDim, fontSize: 8, fontWeight: '700', marginTop: 3 },
  carryNote: { color: colors.textDim, fontSize: 9, lineHeight: 13, marginTop: spacing.sm },
  visualCard: { marginTop: spacing.sm, overflow: 'hidden', padding: spacing.lg },
  replayCard: { gap: spacing.md, marginTop: spacing.sm, overflow: 'hidden', padding: spacing.lg },
  visualHeader: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  visualTitle: { color: colors.text, fontSize: 19, fontWeight: '700', marginTop: 3 },
  frameCounter: { color: colors.accent, fontSize: 12, fontWeight: '800' },
  frameViewport: { aspectRatio: 1.6, backgroundColor: colors.background, borderRadius: radii.sm, overflow: 'hidden', position: 'relative', width: '100%' },
  frameImage: { height: '100%', resizeMode: 'cover', width: '100%' },
  frameLoading: { alignItems: 'center', backgroundColor: 'rgba(8, 11, 12, 0.55)', bottom: 0, justifyContent: 'center', left: 0, position: 'absolute', right: 0, top: 0 },
  timeline: { backgroundColor: colors.line, borderRadius: 4, height: 14, justifyContent: 'center', overflow: 'visible' },
  timelineProgress: { backgroundColor: colors.accent, borderRadius: 4, height: 6 },
  impactMarker: { backgroundColor: colors.orange, bottom: -2, position: 'absolute', top: -2, width: 2 },
  contactWindow: { backgroundColor: colors.orange, borderRadius: 2, bottom: -2, minWidth: 3, opacity: 0.9, position: 'absolute', top: -2 },
  coarseMarker: { backgroundColor: colors.textDim, bottom: -1, position: 'absolute', top: -1, width: 2 },
  frameControls: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  frameButton: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderRadius: radii.sm, height: 38, justifyContent: 'center', width: 42 },
  frameButtonDisabled: { opacity: 0.35 },
  frameButtonPressed: { opacity: 0.7 },
  frameTime: { color: colors.textMuted, fontSize: 11, fontWeight: '800', minWidth: 58, textAlign: 'center' },
  replayNote: { color: colors.textDim, fontSize: 9, lineHeight: 13 },
  replayError: { color: colors.red, fontSize: 10, fontWeight: '700' },
  technicalHeader: { alignItems: 'flex-end', flexDirection: 'row', justifyContent: 'space-between', marginBottom: spacing.md, marginTop: spacing.xl },
  technicalTitle: { color: colors.text, fontSize: 19, fontWeight: '700' },
  technicalNote: { color: colors.textDim, fontSize: 10, fontWeight: '600' },
  technicalCard: { paddingHorizontal: spacing.lg },
  detailRow: { borderBottomColor: colors.line, borderBottomWidth: 1, flexDirection: 'row', justifyContent: 'space-between', paddingVertical: spacing.md },
  detailRowLast: { borderBottomWidth: 0 },
  detailLabel: { color: colors.textMuted, fontSize: 12, fontWeight: '600' },
  detailValue: { color: colors.text, fontSize: 12, fontWeight: '800' },
  detailAccent: { color: colors.accent },
  doneButton: { alignItems: 'center', backgroundColor: colors.accent, borderRadius: radii.md, justifyContent: 'center', marginTop: spacing.xl, minHeight: 54 },
  donePressed: { opacity: 0.8, transform: [{ scale: 0.99 }] },
  doneText: { color: colors.accentInk, fontSize: 15, fontWeight: '800' },
});
