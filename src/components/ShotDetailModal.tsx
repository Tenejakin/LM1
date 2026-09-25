import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, GestureResponderEvent, Image, Modal, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { StrikeMap, TrajectoryChart } from '@/components/ShotVisuals';
import { Eyebrow, IconButton, MeasurementBadge, MeasurementLabel, MetricTile, Surface } from '@/components/ui';
import { getClub } from '@/data/clubs';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { useCloudSync } from '@/context/CloudSyncContext';
import { useUnits } from '@/context/UnitsContext';
import { colors, radii, spacing } from '@/theme';
import { CaptureFramePreview, ClubValueKey, MetricConfidence, Shot, ShotMetricKey } from '@/types';
import { ContactSheet } from '@/components/ContactSheet';
import { DIRECTION_SIGN_NOTE, directionLabel } from '@/utils/direction';
import { measuredAttackAngle, measuredClubPath, measuredClubSpeed, measuredSmash, measuredStrike } from '@/utils/shotValues';
import { shotEstimates } from '@/utils/carry';
import { shotClubLabel } from '@/utils/bagClubs';

export function ShotDetailModal({ shot, onClose }: { shot: Shot | null; onClose: () => void }) {
  return (
    <Modal animationType="slide" onRequestClose={onClose} presentationStyle="pageSheet" visible={Boolean(shot)}>
      {shot ? <ShotDetail shot={shot} onClose={onClose} /> : null}
    </Modal>
  );
}

interface MetricInfo {
  metric: ShotMetricKey;
  title: string;
  value: string;
}

function ShotDetail({ shot, onClose }: { shot: Shot; onClose: () => void }) {
  const { retryShotImage, frameUploadProgress, startShotFrameUpload, setShotExcluded } = useLaunchMonitor();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const compact = width < 600;
  const units = useUnits();
  const [info, setInfo] = useState<MetricInfo | null>(null);
  const [uploadingImage, setUploadingImage] = useState(false);
  const [imageUploadError, setImageUploadError] = useState<string | null>(null);
  const [uploadedImagePath, setUploadedImagePath] = useState<string | null>(null);
  const [frameUploadError, setFrameUploadError] = useState<string | null>(null);
  const [startingFrames, setStartingFrames] = useState(false);
  useEffect(() => {
    setUploadedImagePath(null);
    setImageUploadError(null);
    setFrameUploadError(null);
  }, [shot.id]);
  const imageShot: Shot = uploadedImagePath ? { ...shot, cloudImagePath: uploadedImagePath } : shot;
  const retryImage = async () => {
    setUploadingImage(true);
    setImageUploadError(null);
    try {
      setUploadedImagePath(await retryShotImage(shot));
    } catch (caught) {
      setImageUploadError(caught instanceof Error ? caught.message : 'Could not upload the saved image.');
    } finally {
      setUploadingImage(false);
    }
  };
  const uploadFrames = async () => {
    setStartingFrames(true);
    setFrameUploadError(null);
    try {
      await startShotFrameUpload(shot);
    } catch (caught) {
      setFrameUploadError(caught instanceof Error ? caught.message : 'Could not start the frame upload.');
    } finally {
      setStartingFrames(false);
    }
  };
  const frameProgress = shot.captureId ? frameUploadProgress[shot.captureId] : undefined;
  // Only values the device graded can explain themselves; older shots have no grades.
  const explain = (metric: ShotMetricKey, title: string, value: string | null) =>
    qualityOf(shot, metric) ? () => setInfo({ metric, title,
      value: value === null || (metric !== 'estimatedCarryM' && qualityOf(shot, metric)?.source === 'club-estimate') ? 'Unavailable' : value }) : undefined;
  const summary = measurementSummary(shot);
  const tile = (metric: ShotMetricKey, title: string, value: string | null, unit?: string) => ({
    label: title,
    value: value === null || shot.metricConfidence?.[metric]?.source === 'club-estimate' ? '—' : value,
    unit,
    measurement: measurementOf(shot, metric),
    onPress: explain(metric, title, value === null ? null : unit ? `${value} ${unit}` : value),
  });
  const clubSpeed = measuredClubSpeed(shot);
  const smash = measuredSmash(shot);
  const strike = measuredStrike(shot);
  const estimates = shotEstimates(shot);
  const attack = measuredAttackAngle(shot);
  const clubPath = measuredClubPath(shot);
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
            <Text style={styles.clubName}>{shotClubLabel(shot)}</Text>
          </View>
          <IconButton icon="close" label="Close shot details" onPress={onClose} />
        </View>

        <Surface style={styles.hero}>
          <View style={[styles.heroTop, compact && styles.heroTopCompact]}>
            <View>
              <Eyebrow>Ball speed</Eyebrow>
              <View style={styles.speedRow}>
                <Text style={styles.speed}>{units.speed(shot.ballSpeedMps)}</Text>
                <Text style={styles.unit}>{units.speedLabel}</Text>
              </View>
              <Text style={styles.mph}>{units.altSpeedWithUnit(shot.ballSpeedMps)}</Text>
              <HeroMeasurement
                shot={shot}
                metric="ballSpeedMps"
                onPress={explain('ballSpeedMps', 'Ball speed', `${units.speed(shot.ballSpeedMps)} ${units.speedLabel}`)}
              />
            </View>
            <View style={[styles.heroAside, compact && styles.heroAsideCompact]}>
              <Text style={styles.carryLabel}>Estimated carry</Text>
              <View style={styles.carryRow}>
                <Text style={styles.carryValue}>{units.distance(shot.estimatedCarryM)}</Text>
                <Text style={styles.carryUnit}>{units.distanceLabel}</Text>
              </View>
              <Text style={styles.carryYards}>{units.altDistanceWithUnit(shot.estimatedCarryM)}</Text>
              <HeroMeasurement
                shot={shot}
                metric="estimatedCarryM"
                onPress={explain('estimatedCarryM', 'Estimated carry', `${units.distance(shot.estimatedCarryM)} ${units.distanceLabel}`)}
              />
              {shot.metricConfidence?.spinRpm?.source === 'club-estimate' ? (
                <Text style={styles.spinAssumption}>Carry uses assumed {Math.round(shot.spinRpm ?? 0).toLocaleString()} rpm backspin</Text>
              ) : null}
              <View style={styles.quality}>
                <Ionicons name="shield-checkmark" size={14} color={colors.accent} />
                {summary ? (
                  <Text style={styles.qualityValue}>
                    {summary.measured} measured <Text style={styles.qualityLabel}>·</Text> {summary.estimated} estimated
                    {summary.unavailable ? ` · ${summary.unavailable} unavailable` : ''}
                  </Text>
                ) : (
                  <>
                    <Text style={styles.qualityValue}>{shot.measurementSource ? 'Estimate' : `${Math.round(shot.confidence * 100)}%`}</Text>
                    <Text style={styles.qualityLabel}>{shot.measurementSource ? 'Unvalidated' : 'confidence'}</Text>
                  </>
                )}
              </View>
            </View>
          </View>
          <View style={styles.metricRow}>
            <MetricTile {...tile('clubSpeedMps', 'Club speed', clubSpeed === null ? null : units.speed(clubSpeed), units.speedLabel)} />
            <MetricTile {...tile('smashFactor', 'Smash', smash === null ? null : smash.toFixed(2))} accent />
            <MetricTile {...tile('launchAngleDeg', 'Launch', shot.launchAngleDeg.toFixed(1), 'deg')} />
          </View>
          <View style={styles.metricRowSecondary}>
            <MetricTile {...tile('attackAngleDeg', 'Attack angle', attack === null ? null : attack.toFixed(1), 'deg')} />
            <MetricTile {...tile('clubPathDeg', 'Club path', clubPath === null ? null : directionLabel(clubPath))} />
          </View>
          <View style={styles.metricRowSecondary}>
            <MetricTile {...tile('spinRpm', 'Backspin', Math.round(shot.spinRpm ?? 0).toLocaleString(), 'rpm')} />
            <MetricTile {...tile('spinAxisDeg', 'Spin axis', (shot.spinAxisDeg ?? 0).toFixed(1), 'deg')} />
            <MetricTile {...tile('startDirectionDeg', 'Direction', directionLabel(shot.startDirectionDeg))} />
          </View>
          <Text style={styles.directionNote}>{DIRECTION_SIGN_NOTE}</Text>
          <Text style={styles.carryNote}>
            {summary
              ? 'Measured values passed the camera checks. Estimated values did not pass every check; this is not a probability of accuracy. Tap a value to see its evidence.'
              : 'Estimated values use the selected club and available launch data.'}
          </Text>
        </Surface>

        {estimates ? (
          <Surface style={styles.estimatesCard}>
            <Eyebrow>Model estimates</Eyebrow>
            <Text style={styles.visualTitle}>Flight and impact</Text>
            <View style={styles.metricRowSecondary}>
              <MetricTile label="Total" value={units.distance(estimates.totalM)} unit={units.distanceLabel} />
              <MetricTile label="Roll" value={units.distance(estimates.rollM, 1)} unit={units.distanceLabel} />
              <MetricTile label="Offline" value={offlineLabel(estimates.flight.offlineM, units.distance)} unit={units.distanceLabel} />
            </View>
            <View style={styles.metricRowSecondary}>
              <MetricTile label="Apex" value={units.distance(estimates.flight.apexM, 1)} unit={units.distanceLabel} />
              <MetricTile label="Landing angle" value={estimates.flight.descentDeg.toFixed(0)} unit="deg" />
              <MetricTile label="Hang time" value={estimates.flight.flightTimeS.toFixed(1)} unit="s" />
            </View>
            <View style={styles.metricRowSecondary}>
              <MetricTile label="Dynamic loft" value={estimates.dynamicLoftDeg === null ? '—' : estimates.dynamicLoftDeg.toFixed(1)} unit="deg" />
              <MetricTile label="Spin loft" value={estimates.spinLoftDeg === null ? '—' : estimates.spinLoftDeg.toFixed(1)} unit="deg" />
            </View>
            <Text style={styles.carryNote}>
              Calculated, not observed: still-air flight fitted to tour averages, then roll on an assumed {estimates.surface}.
              Offline is the straight start line; curve is not modeled. Lofts come from launch and attack angle
              {estimates.spinLoftDeg === null
                ? (attack === null ? ' and need a measured attack angle.' : '; launch sits too far above this attack angle for the impact model, so the attack angle is likely off.')
                : ' with a rolling-contact impact model.'}
            </Text>
          </Surface>
        ) : null}

        <Pressable
          accessibilityRole="button"
          accessibilityHint="Session averages, dispersion and gapping ignore excluded shots"
          onPress={() => setShotExcluded(shot.id, !shot.excluded)}
          style={({ pressed }) => [styles.excludeButton, pressed && styles.donePressed]}
        >
          <Ionicons name={shot.excluded ? 'eye' : 'eye-off'} size={16} color={colors.textMuted} />
          <Text style={styles.excludeText}>{shot.excluded ? 'Excluded from session stats · include again' : 'Exclude from session stats'}</Text>
        </Pressable>

        {imageShot.cloudImagePath ? <CloudShotImages shot={imageShot} /> : shot.captureId ? <ContactSheet captureId={shot.captureId} card /> : null}

        {shot.captureId && !imageShot.cloudImagePath ? (
          <Surface style={styles.visualCard}>
            <Text style={styles.visualTitle}>Cloud image missing</Text>
            <Text style={styles.replayNote}>Upload this saved capture from the connected Pi to your private Bunny storage.</Text>
            <Pressable accessibilityRole="button" disabled={uploadingImage} onPress={() => void retryImage()}
              style={({ pressed }) => [styles.imageRetryButton, (pressed || uploadingImage) && styles.donePressed]}>
              {uploadingImage ? <ActivityIndicator color={colors.background} /> : <Text style={styles.doneText}>Upload shot image</Text>}
            </Pressable>
            {imageUploadError ? <Text style={styles.imageUploadError}>{imageUploadError}</Text> : null}
          </Surface>
        ) : null}

        {shot.captureId && shot.frameCount > 0 ? (
          <Surface style={styles.visualCard}>
            <Text style={styles.visualTitle}>Original camera frames</Text>
            <Text style={styles.replayNote}>
              {frameProgress ? `${frameProgress.uploaded} of ${frameProgress.total} full-resolution frames stored in Bunny`
                : `${shot.frameCount} full-resolution frames per camera are saved on the Pi.`}
            </Text>
            {frameProgress?.state === 'running' ? <ActivityIndicator color={colors.accent} /> : (
              <Pressable accessibilityRole="button" disabled={startingFrames} onPress={() => void uploadFrames()}
                style={({ pressed }) => [styles.imageRetryButton, (pressed || startingFrames) && styles.donePressed]}>
                {startingFrames ? <ActivityIndicator color={colors.background} />
                  : <Text style={styles.doneText}>{frameProgress?.state === 'complete' ? 'Check cloud frames' : 'Upload all original frames'}</Text>}
              </Pressable>
            )}
            {frameUploadError || frameProgress?.message ? <Text style={styles.imageUploadError}>{frameUploadError ?? frameProgress?.message}</Text> : null}
          </Surface>
        ) : null}

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
          <HeroMeasurement
            shot={shot}
            metric="strike"
            onPress={explain('strike', 'Clubface strike', strike ? `${strike.xMm.toFixed(0)} mm toe · ${strike.yMm.toFixed(0)} mm high` : null)}
          />
        </Surface>

        <View style={styles.technicalHeader}>
          <Text style={styles.technicalTitle}>Capture details</Text>
          <Text style={styles.technicalNote}>For diagnosis & replay</Text>
        </View>
        <Surface style={styles.technicalCard}>
          <DetailRow label="Frames retained" value={`${shot.frameCount}`} />
          <DetailRow label="Capture window" value={`${shot.captureDurationMs} ms`} />
          <DetailRow
            label={shot.measurementSource ? 'Camera accuracy' : summary ? 'Lowest estimate' : 'Confidence'}
            value={shot.measurementSource ? 'Not validated' : summary
              ? summary.lowest === undefined ? 'All measured' : `${Math.round(summary.lowest * 100)}%`
              : `${Math.round(shot.confidence * 100)}%`}
            accent
          />
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
      {info ? <MetricInfoWindow shot={shot} info={info} onClose={() => setInfo(null)} /> : null}
    </View>
  );
}

function CloudShotImages({ shot }: { shot: Shot }) {
  const { getShotImage } = useCloudSync();
  const [primaryUri, setPrimaryUri] = useState<string | null>(null);
  const [secondaryUri, setSecondaryUri] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setPrimaryUri(null);
    setSecondaryUri(null);
    setImageError(null);
    void getShotImage(shot.id).then((uri) => { if (!cancelled) setPrimaryUri(uri); })
      .catch((caught) => { if (!cancelled) setImageError(caught instanceof Error ? caught.message : 'Could not load the shot image.'); });
    if (shot.cloudSecondaryImagePath) {
      void getShotImage(shot.id, 'secondary').then((uri) => { if (!cancelled) setSecondaryUri(uri); })
        .catch((caught) => { if (!cancelled) setImageError(caught instanceof Error ? caught.message : 'Could not load the upper camera image.'); });
    }
    return () => { cancelled = true; };
  }, [getShotImage, shot.id, shot.cloudSecondaryImagePath]);
  return <Surface style={styles.visualCard}>
    <Text style={styles.visualTitle}>Shot capture</Text>
    {primaryUri ? <Image accessibilityLabel="Shot capture image" source={{ uri: primaryUri }} style={styles.cloudImage} /> : imageError ? null : <ActivityIndicator color={colors.accent} />}
    {secondaryUri ? <Image accessibilityLabel="Upper camera shot capture image" source={{ uri: secondaryUri }} style={styles.cloudImage} /> : null}
    {imageError ? <Text style={{ color: colors.red }}>{imageError}</Text> : null}
  </Surface>;
}

/** Signed offline distance as "1.2 L" / "0.8 R"; negative is left, matching start direction. */
function offlineLabel(meters: number, format: (meters: number, digits?: number) => string): string {
  if (Math.abs(meters) < 0.05) return '0';
  return `${format(Math.abs(meters), 1)} ${meters < 0 ? 'L' : 'R'}`;
}

function measurementOf(shot: Shot, metric: ShotMetricKey): MeasurementLabel | undefined {
  const quality = shot.metricConfidence?.[metric];
  if (!quality) return undefined;
  if (metric !== 'estimatedCarryM' && quality.source === 'club-estimate') return undefined;
  const measured = quality.source === 'measured';
  return { measured, confidence: measured || shot.measurementSource ? undefined : quality.confidence };
}

const CLUB_VALUE_KEYS: ClubValueKey[] = ['clubSpeedMps', 'smashFactor', 'strike', 'attackAngleDeg', 'clubPathDeg'];

/** The device grade, or for a value the camera did not resolve, the reason it is missing. */
function qualityOf(shot: Shot, metric: ShotMetricKey): MetricConfidence | undefined {
  const quality = shot.metricConfidence?.[metric];
  if (quality) return quality;
  const reason = CLUB_VALUE_KEYS.includes(metric as ClubValueKey)
    ? shot.unavailableReasons?.[metric as ClubValueKey] : undefined;
  return reason ? { confidence: 0, source: 'club-estimate', reason } : undefined;
}

function measurementSummary(shot: Shot) {
  const entries = Object.entries(shot.metricConfidence ?? {});
  const unavailable = entries.filter(([key, item]) => key !== 'estimatedCarryM' && item?.source === 'club-estimate').length
    + Object.keys(shot.unavailableReasons ?? {}).length;
  const qualities = entries.filter(([key, item]) => key === 'estimatedCarryM' || item?.source !== 'club-estimate').map(([, item]) => item).filter((item) => item !== undefined);
  if (!qualities.length) return null;
  const estimates = qualities.filter((item) => item.source !== 'measured');
  return {
    measured: qualities.length - estimates.length,
    unavailable,
    estimated: estimates.length,
    lowest: estimates.length ? Math.min(...estimates.map((item) => item.confidence)) : undefined,
  };
}

function HeroMeasurement({ shot, metric, onPress }: { shot: Shot; metric: ShotMetricKey; onPress?: () => void }) {
  const label = measurementOf(shot, metric);
  if (!label) return null;
  return (
    <Pressable
      accessibilityHint="Shows how this value was measured or estimated"
      accessibilityRole="button"
      disabled={!onPress}
      hitSlop={8}
      onPress={onPress}
      style={({ pressed }) => [styles.heroMeasurement, pressed && styles.heroMeasurementPressed]}
    >
      <MeasurementBadge label={label} />
      {onPress ? <Ionicons name="information-circle-outline" size={14} color={colors.textDim} style={styles.heroInfoIcon} /> : null}
    </Pressable>
  );
}

const SOURCE_TEXT = {
  'measured': 'Tracked by the camera and passed every quality check.',
  'device-estimate': 'Worked out by the camera, but at least one quality check did not pass.',
  'model-estimate': 'Calculated from camera-measured values with a physics model; not observed directly.',
  'club-estimate': 'The camera did not resolve this value. Details below describe the model assumptions.',
} as const;

function MetricInfoWindow({ shot, info, onClose }: { shot: Shot; info: MetricInfo; onClose: () => void }) {
  const quality = qualityOf(shot, info.metric);
  const missing = !shot.metricConfidence?.[info.metric];
  const label = measurementOf(shot, info.metric);
  if (!quality) return null;
  return (
    <View style={styles.infoOverlay}>
      <Pressable accessibilityLabel="Close explanation" onPress={onClose} style={styles.infoBackdrop} />
      <View accessibilityViewIsModal style={styles.infoCard}>
        <View style={styles.infoHeader}>
          <View style={styles.infoHeading}>
            <Eyebrow>{info.title}</Eyebrow>
            <Text style={styles.infoValue}>{info.value}</Text>
          </View>
          <IconButton icon="close" label="Close explanation" onPress={onClose} />
        </View>
        {label ? <MeasurementBadge label={label} /> : <Text style={styles.infoSource}>Unavailable</Text>}
        <Text style={styles.infoSource}>{missing ? 'The camera did not resolve this value on this shot.' : SOURCE_TEXT[quality.source]}</Text>
        <ScrollView style={styles.infoBody} contentContainerStyle={styles.infoBodyContent}>
          {quality.checks?.length ? (
            <View>
              <Text style={styles.infoSectionTitle}>Quality checks</Text>
              {quality.checks.map((check) => (
                <View key={check.label} style={styles.infoCheck}>
                  <Ionicons
                    name={check.passed ? 'checkmark-circle' : 'close-circle'}
                    size={15}
                    color={check.passed ? colors.accent : colors.orange}
                  />
                  <Text style={styles.infoCheckText}>{check.label}</Text>
                </View>
              ))}
            </View>
          ) : null}
          {quality.reason ? (
            <View>
              <Text style={styles.infoSectionTitle}>{missing ? 'Why it is unavailable' : 'How it was worked out'}</Text>
              <Text style={styles.infoReason}>{quality.reason}</Text>
            </View>
          ) : null}
        </ScrollView>
      </View>
    </View>
  );
}

function ShotFrameReview({ shot }: { shot: Shot }) {
  const { getCaptureFrame } = useLaunchMonitor();
  const { getCloudShotFrame } = useCloudSync();
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
    void getCloudShotFrame(shot.id, frameIndex).catch(() => getCaptureFrame(shot.captureId!, frameIndex))
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
  }, [frameIndex, getCaptureFrame, getCloudShotFrame, shot.captureId, shot.id]);

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
      {frame?.secondaryBase64 ? <>
        <Eyebrow>Upper camera · matching frame</Eyebrow>
        <View style={styles.frameViewport}>
          <Image accessibilityLabel="Upper camera matching capture frame" source={{ uri: `data:${frame.mimeType};base64,${frame.secondaryBase64}` }} style={styles.frameImage} />
        </View>
      </> : null}
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
  heroTopCompact: { flexDirection: 'column' },
  speedRow: { alignItems: 'baseline', flexDirection: 'row', gap: 7, marginTop: 1 },
  speed: { color: colors.text, fontSize: 58, fontWeight: '700', letterSpacing: -3.4 },
  unit: { color: colors.textMuted, fontSize: 16, fontWeight: '700' },
  mph: { color: colors.textDim, fontSize: 11, fontWeight: '700', marginTop: -5 },
  heroAside: { alignItems: 'flex-end', flexShrink: 1, minWidth: 0 },
  heroAsideCompact: { alignItems: 'flex-start', alignSelf: 'stretch', borderTopColor: colors.line, borderTopWidth: 1, marginTop: spacing.lg, paddingTop: spacing.md },
  spinAssumption: { color: colors.textDim, fontSize: 10, lineHeight: 15, marginTop: spacing.xs },
  carryLabel: { color: colors.textMuted, fontSize: 9, fontWeight: '800', letterSpacing: 0.7, textTransform: 'uppercase' },
  carryRow: { alignItems: 'baseline', flexDirection: 'row', gap: 4, marginTop: 2 },
  carryValue: { color: colors.accent, fontSize: 35, fontWeight: '700', letterSpacing: -1.4 },
  carryUnit: { color: colors.textMuted, fontSize: 12, fontWeight: '700' },
  carryYards: { color: colors.textDim, fontSize: 10, fontWeight: '700', marginTop: -4 },
  quality: { alignItems: 'center', flexDirection: 'row', flexWrap: 'wrap', gap: 4, marginTop: 8, maxWidth: '100%' },
  qualityValue: { color: colors.text, flexShrink: 1, fontSize: 11, fontWeight: '800' },
  qualityLabel: { color: colors.textDim, fontSize: 9, fontWeight: '600' },
  metricRow: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.lg },
  metricRowSecondary: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
  heroMeasurement: { alignItems: 'center', alignSelf: 'flex-start', flexDirection: 'row', gap: 4 },
  heroMeasurementPressed: { opacity: 0.7 },
  heroInfoIcon: { marginTop: 6 },
  infoOverlay: { bottom: 0, justifyContent: 'center', left: 0, padding: spacing.md, position: 'absolute', right: 0, top: 0 },
  infoBackdrop: { backgroundColor: 'rgba(0, 0, 0, 0.6)', bottom: 0, left: 0, position: 'absolute', right: 0, top: 0 },
  infoCard: { backgroundColor: colors.surfaceRaised, borderColor: colors.lineStrong, borderRadius: radii.lg, borderWidth: 1, maxHeight: '75%', padding: spacing.lg },
  infoHeader: { alignItems: 'flex-start', flexDirection: 'row', justifyContent: 'space-between' },
  infoHeading: { flex: 1, paddingRight: spacing.sm },
  infoValue: { color: colors.text, fontSize: 24, fontWeight: '700', letterSpacing: -0.8, marginTop: 3 },
  infoSource: { color: colors.textMuted, fontSize: 12, lineHeight: 17, marginTop: spacing.sm },
  infoBody: { marginTop: spacing.md },
  infoBodyContent: { gap: spacing.md },
  infoSectionTitle: { color: colors.textMuted, fontSize: 10, fontWeight: '800', letterSpacing: 0.8, marginBottom: spacing.xs, textTransform: 'uppercase' },
  infoCheck: { alignItems: 'flex-start', flexDirection: 'row', gap: 7, paddingVertical: 4 },
  infoCheckText: { color: colors.text, flex: 1, fontSize: 12, lineHeight: 17 },
  infoReason: { color: colors.textMuted, fontSize: 12, lineHeight: 18 },
  carryNote: { color: colors.textDim, fontSize: 9, lineHeight: 13, marginTop: spacing.sm },
  directionNote: { color: colors.textDim, fontSize: 10, lineHeight: 15, marginTop: spacing.sm },
  visualCard: { marginTop: spacing.sm, overflow: 'hidden', padding: spacing.lg },
  replayCard: { gap: spacing.md, marginTop: spacing.sm, overflow: 'hidden', padding: spacing.lg },
  visualHeader: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  visualTitle: { color: colors.text, fontSize: 19, fontWeight: '700', marginTop: 3 },
  estimatesCard: { gap: spacing.xs, marginTop: spacing.md, padding: spacing.lg },
  excludeButton: { alignItems: 'center', alignSelf: 'flex-start', flexDirection: 'row', gap: spacing.xs, marginTop: spacing.md, paddingVertical: spacing.xs },
  excludeText: { color: colors.textMuted, fontSize: 13, fontWeight: '600' },
  frameCounter: { color: colors.accent, fontSize: 12, fontWeight: '800' },
  frameViewport: { aspectRatio: 1.6, backgroundColor: colors.background, borderRadius: radii.sm, overflow: 'hidden', position: 'relative', width: '100%' },
  frameImage: { height: '100%', resizeMode: 'cover', width: '100%' },
  cloudImage: { width: '100%', aspectRatio: 1.6, resizeMode: 'contain' },
  imageRetryButton: { alignItems: 'center', alignSelf: 'flex-start', backgroundColor: colors.accent, borderRadius: radii.sm, justifyContent: 'center', marginTop: spacing.md, minHeight: 42, paddingHorizontal: spacing.md },
  imageUploadError: { color: colors.red, fontSize: 12, marginTop: spacing.sm },
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
