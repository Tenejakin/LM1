import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Image, Modal, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { PrimaryButton, SectionHeader, Surface } from '@/components/ui';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { colors, spacing } from '@/theme';
import type { StereoCalibrationAction, StereoCalibrationOptions, StereoCalibrationStatus } from '@/types';
import { stereoCalibrationScore } from '@/utils/stereoCalibrationScore';

export function StereoCalibrationScreen({ onClose }: { onClose: () => void }) {
  const insets = useSafeAreaInsets();
  const { stereoCalibration, previewFrame, secondaryPreviewFrame, status, isDemo } = useLaunchMonitor();
  const [data, setData] = useState<StereoCalibrationStatus | null>(null);
  const [busy, setBusy] = useState<StereoCalibrationAction | null>(null);
  const [message, setMessage] = useState('');
  const [columns, setColumns] = useState('5');
  const [rows, setRows] = useState('5');
  const [square, setSquare] = useState('25');
  const pending = useRef(false);
  const mounted = useRef(true);
  const supported = !isDemo && Number(status?.protocolVersion?.split('.')[1] ?? 0) >= 24;
  const connected = supported && Boolean(status?.cameraConnected) && (status?.camera?.cameraCount ?? 0) === 2;

  const run = useCallback(async (action: StereoCalibrationAction, options?: StereoCalibrationOptions) => {
    if (pending.current) return;
    pending.current = true;
    setBusy(action);
    if (action !== 'status') setMessage('');
    try {
      const result = await stereoCalibration(action, options);
      if (!mounted.current) return;
      setData(result);
      if (action === 'capture') setMessage('Synchronized pair saved. Move and tilt the board before the next capture.');
      if (action === 'activate') setMessage('Fixed camera pair activated. Check the ground AprilTag calibration, then validate known ball positions.');
    } catch (error) {
      if (mounted.current) setMessage(error instanceof Error ? error.message : 'Stereo calibration failed.');
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(null);
    }
  }, [stereoCalibration]);

  useEffect(() => {
    mounted.current = true;
    if (supported) void run('status');
    // Keep shot detection paused while this screen is open; the Pi lease expires
    // if the phone disconnects. Sessions and active calibration remain on disk.
    const timer = setInterval(() => { if (supported && !pending.current) void run('status'); }, 30_000);
    return () => {
      mounted.current = false;
      clearInterval(timer);
      if (supported) void stereoCalibration('end').catch(() => undefined);
    };
  }, [run, stereoCalibration, supported]);

  const start = () => {
    const options = { columns: Number(columns), rows: Number(rows), squareMm: Number(square.replace(',', '.')) };
    if (!Number.isInteger(options.columns) || !Number.isInteger(options.rows)
      || options.columns < 3 || options.columns > 15 || options.rows < 3 || options.rows > 15
      || !Number.isFinite(options.squareMm) || options.squareMm < 3 || options.squareMm > 100) {
      setMessage('Enter 3–15 inner corners per side and a measured square size between 3 and 100 mm.');
      return;
    }
    if (data?.sessionId) {
      Alert.alert('Start a new set of pairs?', 'The previous session stays on the Pi. Your active calibration will not change.', [
        { text: 'Cancel', style: 'cancel' }, { text: 'Start new set', onPress: () => void run('start', options) },
      ]);
    } else void run('start', options);
  };
  const candidate = data?.candidate;
  const fitScore = candidate ? stereoCalibrationScore(candidate) : null;
  const fitLabel = candidate?.passed
    ? fitScore! >= 90 ? 'Excellent' : fitScore! >= 80 ? 'Good' : 'Pass'
    : 'Needs work';

  return (
    <Modal animationType="slide" onRequestClose={() => { if (!pending.current) onClose(); }}>
      <ScrollView style={styles.root} contentContainerStyle={[styles.content, { paddingTop: insets.top + 16, paddingBottom: insets.bottom + 24 }]}>
        <SectionHeader title="Calibrate camera pair" />
        <Text style={styles.body}>One rigid pair. Two synchronized views. Keep the cameras and lens focus fixed; move only the checkerboard.</Text>
        <PrimaryButton label="Back to calibration" variant="outline" disabled={Boolean(busy)} onPress={onClose} />
        {!supported ? <Text style={styles.warning}>Connect to LM1 with Pi service 0.37.0 or newer to use paired calibration.</Text> : null}
        <Surface style={styles.card}>
          <Text style={styles.title}>1 · Prepare</Text>
          <Text style={styles.body}>Calibrate both lenses first at the current capture resolution. Use a flat, rigid checkerboard with accurately measured squares. Count INNER corners, not squares. No AprilTag is needed during this step.</Text>
          <View style={styles.fields}>
            {[['Columns', columns, setColumns], ['Rows', rows, setRows], ['Square mm', square, setSquare]].map(([label, value, setter]) => (
              <View style={styles.field} key={String(label)}>
                <Text style={styles.label}>{String(label)}</Text>
                <TextInput accessibilityLabel={String(label)} value={String(value)} editable={!busy}
                  keyboardType="decimal-pad" onChangeText={setter as (value: string) => void} style={styles.input} />
              </View>
            ))}
          </View>
          <PrimaryButton label={data?.sessionId ? 'Start new set of pairs' : 'Start paired calibration'}
            disabled={!connected || Boolean(busy)} loading={busy === 'start'} onPress={start} />
          {data?.board ? <Text style={styles.body}>Current set: {data.board.columns} × {data.board.rows} inner corners, {data.board.squareMm} mm squares. Field changes apply only to a new set.</Text> : null}
        </Surface>
        <Surface style={styles.card}>
          <Text style={styles.title}>2 · Capture varied pairs</Text>
          <Text style={styles.body}>Hold the complete board still in BOTH views. Capture at least 16 distinct positions: left, centre, right, higher, lower, nearer and farther. Tilt forward/back and sideways. Avoid glare, blur and image edges.</Text>
          <Text style={styles.warning}>Shot detection is paused while this screen is open. These are live previews, not saved calibration images.</Text>
          {([['Bottom camera', previewFrame], ['Top camera', secondaryPreviewFrame]] as const).map(([label, uri]) => (
            <View key={label}>
              <Text style={styles.label}>{label}</Text>
              {uri ? <Image accessibilityLabel={`${label} live preview`} source={{ uri }} style={styles.preview} />
                : <Text style={styles.body}>Waiting for camera preview…</Text>}
            </View>
          ))}
          <Text style={styles.count}>{data?.pairs ?? 0} / {data?.minimumPairs ?? 16} minimum pairs</Text>
          {message ? <Text accessibilityLiveRegion="polite" style={styles.message}>{message}</Text> : null}
          <PrimaryButton label="Capture synchronized pair" icon="camera" loading={busy === 'capture'}
            disabled={!connected || !data?.sessionId || Boolean(busy) || (data?.pairs ?? 0) >= (data?.maximumPairs ?? 48)}
            onPress={() => void run('capture')} />
        </Surface>
        <Surface style={styles.card}>
          <Text style={styles.title}>3 · Solve and validate</Text>
          <Text style={styles.body}>Every fourth pair is reserved for validation and excluded from the solve. Passing checks does not yet prove absolute ball-measurement accuracy.</Text>
          <PrimaryButton label="Solve camera pair" loading={busy === 'solve'} disabled={!connected || Boolean(busy) || (data?.pairs ?? 0) < (data?.minimumPairs ?? 16)} onPress={() => void run('solve')} />
          {candidate ? <>
            <Text style={styles.title}>{candidate.passed ? 'Validation passed' : 'More work needed'}</Text>
            <Text accessibilityLabel={`Calibration fit score ${fitScore} out of 100`} style={styles.score}>
              Fit score {fitScore}/100 · {fitLabel}
            </Text>
            <Text style={styles.body}>100-point target: training ≤0.35 px, unseen-view ≤0.50 px and worst view ≤1.00 px. The score shows margin within LM1's validation limits; it does not measure real-world shot accuracy.</Text>
            <Text style={styles.body}>Camera separation: {candidate.baselineMm.toFixed(1)} mm{ '\n' }
              Training error: {candidate.rmsPx.toFixed(2)} px ({candidate.trainingPairs} pairs){ '\n' }
              Unseen-view error: {candidate.validationRmsPx.toFixed(2)} px ({candidate.validationPairs} pairs){ '\n' }
              Worst validation view: {candidate.validationMaxPx.toFixed(2)} px</Text>
            {candidate.failures.map(failure => <Text key={failure} style={styles.warning}>{failure}</Text>)}
            <Text style={styles.body}>Check that the separation is plausible for your mount. Activation backs up the previous stereo calibration; lens and ground files are preserved.</Text>
            <PrimaryButton label={data?.active?.id === candidate.id ? 'This calibration is active' : 'Use this calibration'}
              loading={busy === 'activate'} disabled={!connected || Boolean(busy) || !candidate.passed || data?.active?.id === candidate.id}
              onPress={() => Alert.alert('Use this camera pair?', 'Apply the validated fixed relationship to future shots? Existing shot history is unchanged.', [
                { text: 'Cancel', style: 'cancel' }, { text: 'Use calibration', onPress: () => void run('activate', { candidateId: candidate.id }) },
              ])} />
          </> : null}
          <Text style={styles.body}>{data?.active ? `Saved active pair: ${stereoCalibrationScore(data.active)}/100 fit score · ${data.active.baselineMm.toFixed(1)} mm separation. Recalibrate if either camera or its lens moves.` : 'No fixed-pair calibration saved yet. Existing ground-tag geometry remains in use.'}</Text>
        </Surface>
        <Text style={styles.body}>Remove the board before closing this screen. After activation: check the ground AprilTag, then measure known stationary ball positions before trusting speed and launch estimates. Zero direction remains left → right across the bottom camera.</Text>
      </ScrollView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  content: { padding: spacing.md, gap: spacing.md },
  card: { padding: spacing.md, gap: spacing.md },
  title: { color: colors.text, fontWeight: '700', fontSize: 17 },
  body: { color: colors.textMuted, fontSize: 13, lineHeight: 20 },
  warning: { color: colors.orange, fontSize: 13, lineHeight: 20 },
  message: { color: colors.accent, fontSize: 14, lineHeight: 21 },
  fields: { flexDirection: 'row', gap: spacing.sm },
  field: { flex: 1, gap: spacing.xs },
  label: { color: colors.textMuted, fontSize: 12, marginBottom: 6 },
  input: { color: colors.text, padding: 12, borderWidth: 1, borderColor: colors.line, borderRadius: 8 },
  preview: { width: '100%', aspectRatio: 1.6, borderRadius: 10, backgroundColor: colors.black },
  count: { color: colors.accent, fontSize: 21, fontWeight: '700' },
  score: { color: colors.accent, fontSize: 23, fontWeight: '800' },
});
