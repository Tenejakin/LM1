import React, { useState } from 'react';
import { Image, Pressable, Text, View } from 'react-native';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { useOpenGolfSim } from '@/context/OpenGolfSimContext';
import { ContactSheet } from '@/components/ContactSheet';
import { Eyebrow, Surface } from '@/components/ui';
import { colors, spacing } from '@/theme';
import { DIRECTION_SIGN_NOTE, directionLabel } from '@/utils/direction';

export function CaptureReview({ history = false }: { history?: boolean }) {
  const { captures, isDemo, getCaptureFrame } = useLaunchMonitor();
  const { state: simState, sendCapture } = useOpenGolfSim();
  const [selected, setSelected] = useState(0);
  const [replay, setReplay] = useState<{ id: string; index: number; uri: string; secondaryUri?: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [simMessage, setSimMessage] = useState<string | null>(null);
  const capture = captures[history ? Math.min(selected, captures.length - 1) : 0];
  if (isDemo || !capture) return null;
  const metrics = capture.measurements?.metrics;
  const tracking = capture.measurements?.tracking;
  const evidence = capture.measurements?.shotEvidence;
  const notStrike = capture.mode === 'full-shot' && evidence?.status === 'not-a-strike';
  const noClub = capture.mode === 'full-shot' && evidence?.status === 'motion-only';
  const stereo = capture.measurements?.diagnostics?.stereo;
  const lowerTracked = tracking?.lowerFrames ?? capture.measurements?.diagnostics?.motionTrackedFrames;
  const pairedFrames = tracking?.pairedFrames ?? stereo?.frames;
  const pairedIndices = tracking?.pairedFrameIndices ?? stereo?.frameIndices;
  const spanMs = tracking?.spanMs ?? stereo?.spanMs;
  const stereoFailure = tracking?.stereoFailure ?? stereo?.failure;
  const monoFailure = tracking?.monoFailure ?? capture.measurements?.failure;
  const imageResidualPx = tracking?.imageResidualPx ?? stereo?.rmsPx;
  const detection = tracking?.detection ?? stereo?.detection;
  const failedSpeedChecks = metrics?.ballSpeedMps?.checks?.filter((check) => !check.passed) ?? [];
  const trackingFailed = capture.mode === 'full-shot' && capture.classification === 'motion-observed'
    && metrics?.ballSpeedMps?.value == null;
  const simReady = capture.mode === 'full-shot'
    && !notStrike && capture.classification === 'motion-observed'
    && ['ballSpeedMps', 'launchAngleDeg', 'startDirectionDeg'].every((key) => metrics?.[key]?.value != null);
  const current = replay?.id === capture.id ? replay : null;
  const index = current?.index ?? capture.imageFrameIndex;
  const hasContactWindow = typeof capture.lastStationaryFrameIndex === 'number' && typeof capture.firstMovingFrameIndex === 'number';
  const coarseDepartureIndex = capture.coarseDepartureFrameIndex ?? capture.impactFrameIndex;
  const step = async (offset: number) => {
    if (!capture.captureId || loading) return;
    setLoading(true);
    setError(null);
    try {
      const frame = await getCaptureFrame(capture.captureId, Math.max(0, Math.min(capture.frameCount - 1, index + offset)));
      setReplay({ id: capture.id, index: frame.frameIndex, uri: `data:${frame.mimeType};base64,${frame.base64}`, secondaryUri: frame.secondaryBase64 ? `data:${frame.mimeType};base64,${frame.secondaryBase64}` : undefined });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Frame unavailable');
    } finally { setLoading(false); }
  };
  return (
    <Surface style={{ padding: spacing.lg, marginVertical: spacing.md, gap: spacing.sm }}>
      <Eyebrow>Camera capture · {capture.clubId}</Eyebrow>
      <Text style={{ color: colors.text, fontSize: 22, fontWeight: '700' }}>
        {notStrike ? 'Not a strike · not counted' : trackingFailed ? 'Tracking failed · speed unavailable'
          : noClub ? 'Ball measured · club not tracked'
          : capture.classification === 'motion-observed' ? 'Ball motion captured' : 'Departure needs review'}
      </Text>
      {evidence ? <Text style={{ color: notStrike || noClub ? colors.orange : colors.textMuted }}>{evidence.reason}</Text> : null}
      {tracking?.source ? <Text style={{ color: colors.textMuted }}>
        Measurement source: {tracking.speedOnly ? 'two-camera, two-frame speed estimate' : tracking.source === 'stereo' ? 'two-camera trajectory' : 'single-camera estimate'}
      </Text> : null}
      {typeof lowerTracked === 'number' ? <Text style={{ color: colors.textMuted }}>
        Lower-camera motion track: {lowerTracked} frames
      </Text> : null}
      {typeof pairedFrames === 'number' ? <Text style={{ color: colors.textMuted }}>
        Two-camera ball matches: {pairedFrames} frames
        {pairedIndices?.length ? ` (${pairedIndices.map((index) => index + 1).join(', ')})` : ''}
        {typeof spanMs === 'number' ? ` over ${spanMs.toFixed(1)} ms` : ''}
      </Text> : null}
      {tracking?.speedOnly ? <Text style={{ color: colors.orange }}>
        Speed is the average between two ball positions{typeof tracking.speedUncertaintyPct === 'number' ? ` (about ±${tracking.speedUncertaintyPct.toFixed(0)}% sensitivity to a 1-pixel tracking error)` : ''}. Launch angle, direction and carry were not resolved.
      </Text> : null}
      {tracking?.monoFallback === 'used' ? <Text style={{ color: colors.textMuted }}>
        Stereo unavailable; the displayed launch values use a single-camera estimate.
      </Text> : null}
      {stereoFailure ? <Text style={{ color: colors.orange }}>Stereo: {stereoFailure}</Text> : null}
      {trackingFailed && monoFailure ? <Text style={{ color: colors.orange }}>Single camera: {monoFailure}</Text> : null}
      {!stereoFailure && typeof imageResidualPx === 'number' ? <Text style={{ color: colors.textMuted }}>
        Two-camera path fit: {imageResidualPx.toFixed(2)} px image error. Ball detected by {detection === 'independent-circles' ? 'independent circle matching' : 'camera-guided matching'}.
      </Text> : null}
      {typeof pairedFrames === 'number' && pairedFrames >= 3 && pairedFrames < 6 ? <Text style={{ color: colors.textMuted }}>
        Three clean paired frames can produce a measured-grade stereo track when every quality check passes.
      </Text> : null}
      {failedSpeedChecks.length ? <Text style={{ color: colors.orange }}>
        Speed is still an estimate because: {failedSpeedChecks.map((check) => check.label).join('; ')}.
      </Text> : null}
      {trackingFailed ? <Text style={{ color: colors.orange }}>
        No club-profile speed was measured or sent as this shot. The capture is retained for frame review.
      </Text> : null}
      <Text style={{ color: colors.textMuted }}>Reviewing frame {index + 1} of {capture.frameCount}</Text>
      <Text style={{ color: colors.textMuted }}>
        {hasContactWindow
          ? `Contact window · stationary frame ${capture.lastStationaryFrameIndex! + 1} to first-motion frame ${capture.firstMovingFrameIndex! + 1}`
          : `Coarse departure trigger · frame ${coarseDepartureIndex + 1} (not measured impact)`}
      </Text>
      <Image accessibilityLabel="Captured ball near departure, marked with a box; points indicate possible outgoing ball matches" source={{ uri: current?.uri ?? `data:${capture.image.mimeType};base64,${capture.image.base64}` }} style={{ width: '100%', aspectRatio: 1.6, resizeMode: 'contain' }} />
      <Text style={{ color: colors.textMuted }}>{capture.measuredFps ?? 'Unknown'} observed FPS · {capture.captureDurationMs} ms · {new Date(capture.capturedAt).toLocaleTimeString()}</Text>
      {(current?.secondaryUri || (!current && capture.secondaryImage)) ? <>
        <Eyebrow>Upper camera · matching frame</Eyebrow>
        <Image accessibilityLabel="Upper camera matching capture frame" source={{ uri: current?.secondaryUri ?? `data:${capture.secondaryImage!.mimeType};base64,${capture.secondaryImage!.base64}` }} style={{ width: '100%', aspectRatio: 1.6, resizeMode: 'contain' }} />
      </> : null}
      <Text style={{ color: colors.textMuted }}>Exact club contact can fall between exposures; the detector trigger is retained separately for diagnosis.</Text>
      {capture.captureId ? <ContactSheet captureId={capture.captureId} /> : null}
      {capture.captureId ? <View style={{ flexDirection: 'row', gap: spacing.lg }}>
        {[-1, 1].map((offset) => <Pressable key={offset} accessibilityRole="button" disabled={loading || (offset < 0 ? index === 0 : index >= capture.frameCount - 1)} onPress={() => void step(offset)} style={{ padding: spacing.sm }}><Text style={{ color: colors.accent }}>{offset < 0 ? 'Previous frame' : 'Next frame'}</Text></Pressable>)}
      </View> : null}
      {loading ? <Text style={{ color: colors.textMuted }}>Loading frame over Bluetooth…</Text> : null}
      {error ? <Text style={{ color: colors.red }}>{error}</Text> : null}
      {capture.measurements ? <View style={{ gap: spacing.sm }}>
        <Eyebrow>Launch measurements</Eyebrow>
        {Object.entries(capture.measurements.metrics).map(([key, metric]) => <View key={key}>
          <Text style={{ color: colors.text, fontWeight: '700' }}>{metricLabels[key] ?? key}: {metric.value === null ? 'Unavailable' : key === 'startDirectionDeg' ? directionLabel(metric.value) : `${metric.unit === 'm/s' ? (metric.value * 3.6).toFixed(1) : metric.value.toFixed(2)} ${metric.unit === 'm/s' ? 'km/h' : metric.unit}`} {metric.value !== null ? `(${metric.status})` : ''}</Text>
          <Text style={{ color: colors.textMuted, fontSize: 12 }}>{metric.reason}</Text>
          {key === 'startDirectionDeg' && metric.value !== null ? <Text style={{ color: colors.textMuted, fontSize: 12 }}>{DIRECTION_SIGN_NOTE}</Text> : null}
        </View>)}
      </View> : null}
      {simState === 'connected' ? (
        <View style={{ gap: 4 }}>
          {simReady && metrics?.spinRpm?.value == null ? <Text style={{ color: colors.textMuted, fontSize: 12 }}>
            Simulator spin uses a club assumption; spin and simulated carry are not measured.
          </Text> : null}
          <Pressable
            accessibilityRole="button"
            disabled={!simReady}
            onPress={() => {
              const sent = sendCapture(capture);
              setSimMessage(sent ? 'Sent camera speed, launch and direction to OpenGolfSim.' : 'Could not send this hit.');
            }}
            style={{ padding: spacing.sm, opacity: simReady ? 1 : 0.5 }}
          >
            <Text style={{ color: colors.accent, fontWeight: '700' }}>
              {simReady ? 'Send to OpenGolfSim' : notStrike ? 'Not sent · not a strike' : 'Send to OpenGolfSim (camera launch unavailable)'}
            </Text>
          </Pressable>
          {simMessage ? <Text style={{ color: colors.textMuted, fontSize: 12 }}>{simMessage}</Text> : null}
        </View>
      ) : null}
      {capture.warnings.map((warning) => <Text key={warning} style={{ color: colors.textMuted }}>{warning}</Text>)}
      {history && captures.length > 1 ? <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>{captures.map((item, i) => <Pressable key={item.id} accessibilityRole="button" onPress={() => { setSelected(i); setReplay(null); setError(null); }} style={{ padding: spacing.sm }}><Text style={{ color: i === selected ? colors.accent : colors.textMuted }}>Capture {captures.length - i}</Text></Pressable>)}</View> : null}
    </Surface>
  );
}

const metricLabels: Record<string, string> = {
  ballSpeedMps: 'Ball speed', clubSpeedMps: 'Club / putter speed', smashFactor: 'Smash factor',
  launchAngleDeg: 'Launch angle', startDirectionDeg: 'Start direction', strikeXmm: 'Strike toward toe',
  strikeYmm: 'Strike above center', spinRpm: 'Backspin', spinAxisDeg: 'Spin axis', estimatedCarryM: 'Estimated carry',
  rollDistanceM: 'Total roll distance', skidDistanceM: 'Skid distance',
};
