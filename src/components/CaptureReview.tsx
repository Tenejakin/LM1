import React, { useState } from 'react';
import { Image, Pressable, Text, View } from 'react-native';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { useOpenGolfSim } from '@/context/OpenGolfSimContext';
import { ContactSheet } from '@/components/ContactSheet';
import { Eyebrow, Surface } from '@/components/ui';
import { colors, spacing } from '@/theme';
import { estimateShotFromCapture } from '@/utils/carry';

export function CaptureReview({ history = false }: { history?: boolean }) {
  const { captures, isDemo, getCaptureFrame, selectedClub } = useLaunchMonitor();
  const { state: simState, sendCapture, sendShot } = useOpenGolfSim();
  const [selected, setSelected] = useState(0);
  const [replay, setReplay] = useState<{ id: string; index: number; uri: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [simMessage, setSimMessage] = useState<string | null>(null);
  const capture = captures[history ? Math.min(selected, captures.length - 1) : 0];
  if (isDemo || !capture) return null;
  const metrics = capture.measurements?.metrics;
  const estimatedShot = estimateShotFromCapture(capture, selectedClub, 0);
  const measuredSimReady = ['ballSpeedMps', 'launchAngleDeg', 'startDirectionDeg'].every((key) => metrics?.[key]?.value != null);
  const simReady = estimatedShot !== null || measuredSimReady;
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
      setReplay({ id: capture.id, index: frame.frameIndex, uri: `data:${frame.mimeType};base64,${frame.base64}` });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Frame unavailable');
    } finally { setLoading(false); }
  };
  return (
    <Surface style={{ padding: spacing.lg, marginVertical: spacing.md, gap: spacing.sm }}>
      <Eyebrow>Camera capture · {capture.clubId}</Eyebrow>
      <Text style={{ color: colors.text, fontSize: 22, fontWeight: '700' }}>
        {capture.classification === 'motion-observed' ? 'Ball motion captured' : 'Departure needs review'}
      </Text>
      <Text style={{ color: colors.textMuted }}>Reviewing frame {index + 1} of {capture.frameCount}</Text>
      <Text style={{ color: colors.textMuted }}>
        {hasContactWindow
          ? `Contact window · stationary frame ${capture.lastStationaryFrameIndex! + 1} to first-motion frame ${capture.firstMovingFrameIndex! + 1}`
          : `Coarse departure trigger · frame ${coarseDepartureIndex + 1} (not measured impact)`}
      </Text>
      <Image accessibilityLabel="Captured ball near departure, marked with a box; points indicate possible outgoing ball matches" source={{ uri: current?.uri ?? `data:${capture.image.mimeType};base64,${capture.image.base64}` }} style={{ width: '100%', aspectRatio: 1.6, resizeMode: 'contain' }} />
      <Text style={{ color: colors.textMuted }}>{capture.measuredFps ?? 'Unknown'} observed FPS · {capture.captureDurationMs} ms · {new Date(capture.capturedAt).toLocaleTimeString()}</Text>
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
          <Text style={{ color: colors.text, fontWeight: '700' }}>{metricLabels[key] ?? key}: {metric.value === null ? 'Unavailable' : `${metric.unit === 'm/s' ? (metric.value * 3.6).toFixed(1) : metric.value.toFixed(2)} ${metric.unit === 'm/s' ? 'km/h' : metric.unit}`} {metric.value !== null ? `(${metric.status})` : ''}</Text>
          <Text style={{ color: colors.textMuted, fontSize: 12 }}>{metric.reason}</Text>
        </View>)}
      </View> : null}
      {simState === 'connected' ? (
        <View style={{ gap: 4 }}>
          <Pressable
            accessibilityRole="button"
            disabled={!simReady}
            onPress={() => {
              const sent = estimatedShot ? sendShot(estimatedShot) : sendCapture(capture);
              setSimMessage(sent
                ? estimatedShot
                  ? 'Sent the completed shot to OpenGolfSim; unavailable camera values used the displayed club estimates.'
                  : 'Sent ball speed, launch and direction to OpenGolfSim.'
                : 'Could not send this hit.');
            }}
            style={{ padding: spacing.sm, opacity: simReady ? 1 : 0.5 }}
          >
            <Text style={{ color: colors.accent, fontWeight: '700' }}>
              {simReady ? 'Send to OpenGolfSim' : 'Send to OpenGolfSim (departure is not a confirmed shot)'}
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
