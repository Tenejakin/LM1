import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Image, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Polygon } from 'react-native-svg';

import { ScreenHeader } from '@/components/ScreenHeader';
import { PrimaryButton, SectionHeader, Surface } from '@/components/ui';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { colors, radii, spacing } from '@/theme';
import type { AprilTagCalibration } from '@/types';

const APRILTAG_SIZE_MM = 100;

export function CalibrationScreen() {
  const insets = useSafeAreaInsets();
  const {
    state, status, isDemo, previewFrame, previewDetection, previewAprilTag, latestCalibrationImage,
    resetBallCalibration, captureAprilTagCalibration, getLatestCapturePreview,
    captureCalibrationImage, clearCalibrationImages, runLensCalibration,
    setTargetLine, clearTargetLine,
  } = useLaunchMonitor();
  const [clock, setClock] = useState(Date.now());
  const [tagCalibration, setTagCalibration] = useState<AprilTagCalibration | null>(null);
  const [capturingTag, setCapturingTag] = useState(false);
  const [tagMessage, setTagMessage] = useState<string | null>(null);
  const [resettingPlane, setResettingPlane] = useState(false);
  const [planeMessage, setPlaneMessage] = useState<string | null>(null);
  const [capturePreview, setCapturePreview] = useState<string | null>(null);
  const [captureMessage, setCaptureMessage] = useState<string | null>(null);
  const [loadingCapture, setLoadingCapture] = useState(false);
  const [capturingLensImage, setCapturingLensImage] = useState(false);
  const [lensCaptureMessage, setLensCaptureMessage] = useState<string | null>(null);
  const [clearingLensImages, setClearingLensImages] = useState(false);
  const [runningLensCalibration, setRunningLensCalibration] = useState(false);
  const [lensCalibrationMessage, setLensCalibrationMessage] = useState<string | null>(null);
  const [settingTargetLine, setSettingTargetLine] = useState(false);
  const [clearingTargetLine, setClearingTargetLine] = useState(false);
  const [targetLineMessage, setTargetLineMessage] = useState<string | null>(null);
  useEffect(() => {
    if (status?.groundCalibration !== undefined) setTagCalibration(status.groundCalibration);
  }, [status?.groundCalibration]);

  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const cameraReady = Boolean(
    status?.cameraConnected && previewFrame && previewDetection && clock - previewDetection.receivedAt < 10000,
  );
  const boardReady = cameraReady && !isDemo;
  const liveBallDetection = previewDetection && clock - previewDetection.receivedAt < 10000
    ? previewDetection.detection
    : undefined;
  const liveTag = previewAprilTag && clock - previewAprilTag.receivedAt < 10000
    ? previewAprilTag.calibration
    : undefined;
  const tagReady = boardReady && Boolean(liveTag?.detected && liveTag.corners);
  const lensTotalSaved = latestCalibrationImage?.totalSaved ?? status?.calibrationCapture?.totalSaved ?? 0;
  const lensTotalWithCorners = latestCalibrationImage?.totalWithCorners ?? status?.calibrationCapture?.totalWithCorners ?? 0;
  const calibrationLabel = useMemo(() => {
    if (tagCalibration) return 'AprilTag calibration saved';
    if (tagReady) return 'AprilTag locked - ready to capture';
    if (boardReady) return 'Searching for AprilTag 36h11 ID 0';
    return 'Waiting for live camera';
  }, [boardReady, tagCalibration, tagReady]);

  return (
    <ScrollView contentContainerStyle={[styles.content, { paddingTop: insets.top + spacing.md }]} showsVerticalScrollIndicator={false}>
      <ScreenHeader title="Calibration" subtitle="AprilTag metric reference" state={state} demo={isDemo} />

      <Surface style={styles.hero}>
        <View style={styles.heroIcon}><Ionicons name="scan" color={colors.accent} size={29} /></View>
        <View style={styles.heroCopy}>
          <Text style={styles.heroTitle}>{calibrationLabel}</Text>
          <Text style={styles.heroBody}>Use the printed {APRILTAG_SIZE_MM} mm AprilTag whenever LM1 is moved. It gives analysis a scale, target-line angle, and perspective transform.</Text>
        </View>
      </Surface>

      <View style={styles.section}>
        <SectionHeader title="Live target view" />
        <Surface style={styles.previewCard}>
          <View style={[styles.preview, { aspectRatio: status?.preview ? status.preview.width / status.preview.height : 1.6 }]}>
            {previewFrame && !isDemo ? (
              <Image accessibilityLabel="Live AprilTag calibration camera preview" source={{ uri: previewFrame }} style={styles.image} />
            ) : (
              <View style={styles.loading}>
                <ActivityIndicator color={colors.accent} />
                <Text style={styles.loadingText}>{isDemo ? 'Connect LM1 to use checkerboard calibration.' : 'Waiting for a camera preview…'}</Text>
              </View>
            )}
            {cameraReady && !liveTag?.corners ? <View pointerEvents="none" style={styles.frameGuide} /> : null}
            {liveTag?.detected && liveTag.corners ? <TagOverlay calibration={liveTag} /> : null}
            {liveBallDetection?.state === 'detected' && liveBallDetection.bounds ? (
              <BallOverlay bounds={liveBallDetection.bounds} />
            ) : null}
          </View>
          <View style={styles.previewStatus}>
            <View style={[styles.dot, { backgroundColor: tagReady ? colors.accent : colors.orange }]} />
            <Text style={styles.previewStatusText}>{tagReady ? `Tag locked · quality ${Math.round((liveTag?.quality ?? 0) * 100)}%` : liveTag?.message ?? (boardReady ? 'Keep all four AprilTag corners sharp and visible' : 'Camera preview required')}</Text>
          </View>
          <View style={styles.ballStatus}>
            <Ionicons
              name={liveBallDetection?.state === 'detected' ? 'checkmark-circle' : 'golf'}
              color={liveBallDetection?.state === 'detected' ? colors.accent : colors.textDim}
              size={17}
            />
            <Text style={[styles.previewStatusText, liveBallDetection?.state === 'detected' && styles.detectedText]}>
              {liveBallDetection?.state === 'detected'
                ? 'Ball detected by LM1'
                : liveBallDetection?.state === 'calibrating'
                  ? 'Learning empty plane - keep the ball removed'
                  : 'Waiting for ball inside the dashed detection area'}
            </Text>
          </View>
        </Surface>
      </View>

      <View style={styles.section}>
        <SectionHeader title="Lens calibration capture" />
        <Surface style={styles.captureCard}>
          <Text style={styles.planeBody}>
            Hold the printed checkerboard so it fills roughly half the frame and press Capture.
            Vary its tilt - forward/back and left/right, not just position - between shots.
            At least 12 diverse views with corners found are needed before running calibration.
          </Text>
          <View style={styles.lensCounterRow}>
            <View style={styles.lensCounter}>
              <Text style={styles.lensCounterValue}>{lensTotalSaved}</Text>
              <Text style={styles.lensCounterLabel}>saved</Text>
            </View>
            <View style={styles.lensCounter}>
              <Text style={[styles.lensCounterValue, styles.detectedText]}>{lensTotalWithCorners}</Text>
              <Text style={styles.lensCounterLabel}>corners found</Text>
            </View>
          </View>
          {latestCalibrationImage ? (
            <View style={styles.lensLatestRow}>
              <Image
                accessibilityLabel="Latest calibration capture"
                source={{ uri: `data:${latestCalibrationImage.image.mimeType};base64,${latestCalibrationImage.image.base64}` }}
                style={styles.lensLatestImage}
              />
              <View style={styles.lensLatestStatus}>
                <Ionicons
                  name={latestCalibrationImage.cornersFound ? 'checkmark-circle' : 'close-circle'}
                  color={latestCalibrationImage.cornersFound ? colors.accent : colors.orange}
                  size={20}
                />
                <Text style={styles.previewStatusText}>
                  {latestCalibrationImage.cornersFound
                    ? 'Corners found - keep this one'
                    : 'Corners not found - reposition and retry'}
                </Text>
              </View>
            </View>
          ) : null}
          <PrimaryButton
            label="Capture image"
            icon="camera"
            loading={capturingLensImage}
            disabled={!boardReady || capturingLensImage}
            onPress={() => void (async () => {
              setCapturingLensImage(true);
              setLensCaptureMessage(null);
              try {
                await captureCalibrationImage();
              } catch (caught) {
                setLensCaptureMessage(caught instanceof Error ? caught.message : 'Could not capture the calibration image.');
              } finally {
                setCapturingLensImage(false);
              }
            })()}
          />
          {lensCaptureMessage ? <Text style={styles.planeMessage}>{lensCaptureMessage}</Text> : null}
          <View style={styles.lensActionsRow}>
            <View style={styles.lensActionCell}>
              <PrimaryButton
                label="Clear images"
                icon="trash"
                variant="outline"
                loading={clearingLensImages}
                disabled={clearingLensImages || !lensTotalSaved}
                onPress={() => void (async () => {
                  setClearingLensImages(true);
                  setLensCalibrationMessage(null);
                  try {
                    await clearCalibrationImages();
                  } catch (caught) {
                    setLensCalibrationMessage(caught instanceof Error ? caught.message : 'Could not clear the calibration images.');
                  } finally {
                    setClearingLensImages(false);
                  }
                })()}
              />
            </View>
            <View style={styles.lensActionCell}>
              <PrimaryButton
                label="Run calibration"
                icon="calculator"
                loading={runningLensCalibration}
                disabled={runningLensCalibration || lensTotalWithCorners < 12}
                onPress={() => void (async () => {
                  setRunningLensCalibration(true);
                  setLensCalibrationMessage(null);
                  try {
                    const result = await runLensCalibration();
                    setLensCalibrationMessage(
                      `Saved - RMS ${result.rmsPx.toFixed(3)}px from ${result.viewsUsed}/${result.viewsTotal} views at ${result.imageSize[0]}x${result.imageSize[1]}.`,
                    );
                  } catch (caught) {
                    setLensCalibrationMessage(caught instanceof Error ? caught.message : 'Could not run lens calibration.');
                  } finally {
                    setRunningLensCalibration(false);
                  }
                })()}
              />
            </View>
          </View>
          {lensCalibrationMessage ? <Text style={styles.confirmation}>{lensCalibrationMessage}</Text> : null}
        </Surface>
      </View>

      <View style={styles.section}>
        <SectionHeader title="Target line" />
        <Surface style={styles.captureCard}>
          <Text style={styles.planeBody}>
            Start direction is measured against this line, not the tag&apos;s orientation, so the tag can sit
            at any angle. Roll a ball straight toward your target, wait for the capture, then set the line from it.
          </Text>
          <View style={styles.previewStatus}>
            <View style={[styles.dot, { backgroundColor: status?.targetLine ? colors.accent : colors.orange }]} />
            <Text style={styles.previewStatusText}>
              {status?.targetLine
                ? `Target line set · ${status.targetLine.headingDeg.toFixed(1)}° from tag +X · ${status.targetLine.points} track points`
                : 'Target line not set - speed and launch angle still work; start direction stays unavailable'}
            </Text>
          </View>
          <View style={styles.lensActionsRow}>
            <View style={styles.lensActionCell}>
              <PrimaryButton
                label="Clear line"
                icon="trash"
                variant="outline"
                loading={clearingTargetLine}
                disabled={clearingTargetLine || !status?.targetLine}
                onPress={() => void (async () => {
                  setClearingTargetLine(true);
                  setTargetLineMessage(null);
                  try {
                    await clearTargetLine();
                  } catch (caught) {
                    setTargetLineMessage(caught instanceof Error ? caught.message : 'Could not clear the target line.');
                  } finally {
                    setClearingTargetLine(false);
                  }
                })()}
              />
            </View>
            <View style={styles.lensActionCell}>
              <PrimaryButton
                label="Set from last roll"
                icon="navigate"
                loading={settingTargetLine}
                disabled={!boardReady || settingTargetLine}
                onPress={() => void (async () => {
                  setSettingTargetLine(true);
                  setTargetLineMessage(null);
                  try {
                    const line = await setTargetLine();
                    setTargetLineMessage(`Saved - ${line.headingDeg.toFixed(1)}° from ${line.points} points over ${(line.displacementM * 100).toFixed(0)} cm.`);
                  } catch (caught) {
                    setTargetLineMessage(caught instanceof Error ? caught.message : 'Could not set the target line.');
                  } finally {
                    setSettingTargetLine(false);
                  }
                })()}
              />
            </View>
          </View>
          {targetLineMessage ? <Text style={styles.confirmation}>{targetLineMessage}</Text> : null}
        </Surface>
      </View>

      <View style={styles.section}>
        <SectionHeader title="Initial empty-plane calibration" />
        <Surface style={styles.planeCard}>
          <Ionicons name="layers-outline" color={colors.orange} size={23} />
          <View style={styles.planeCopy}>
            <Text style={styles.planeTitle}>Reset background</Text>
            <Text style={styles.planeBody}>Remove the ball and all moving objects. Reset clears the saved ground calibration and target line. Place the AprilTag again and save its calibration afterward.</Text>
          </View>
          <PrimaryButton
            label="Reset empty plane"
            icon="refresh"
            loading={resettingPlane}
            disabled={!boardReady || resettingPlane}
            onPress={() => void (async () => {
              setResettingPlane(true);
              setPlaneMessage(null);
              try {
                await resetBallCalibration();
                setTagCalibration(null);
                setTagMessage(null);
                setPlaneMessage('Reset sent. Keep the detection area empty for a few seconds until it reports Waiting for ball.');
              } catch (caught) {
                setPlaneMessage(caught instanceof Error ? caught.message : 'Could not reset the empty plane.');
              } finally {
                setResettingPlane(false);
              }
            })()}
            variant="outline"
          />
          {planeMessage ? <Text style={styles.planeMessage}>{planeMessage}</Text> : null}
        </Surface>
      </View>

      <View style={styles.section}>
        <SectionHeader title="Latest impact frames" />
        <Surface style={styles.captureCard}>
          <Text style={styles.planeBody}>A contact sheet of the 200 fps impact burst. It shows the frames before and after the ball leaves the view.</Text>
          <PrimaryButton label="View latest frames" icon="film" loading={loadingCapture} disabled={!boardReady || loadingCapture} variant="outline" onPress={() => void (async () => {
            setLoadingCapture(true); setCaptureMessage(null);
            try {
              const capture = await getLatestCapturePreview();
              setCapturePreview(`data:${capture.mimeType};base64,${capture.base64}`);
            } catch (caught) { setCaptureMessage(caught instanceof Error ? caught.message : 'Could not load the impact frames.'); }
            finally { setLoadingCapture(false); }
          })()} />
          {capturePreview ? <Image accessibilityLabel="Latest impact capture contact sheet" source={{ uri: capturePreview }} style={styles.captureImage} /> : null}
          {captureMessage ? <Text style={styles.planeMessage}>{captureMessage}</Text> : null}
        </Surface>
      </View>

      <View style={styles.section}>
        <SectionHeader title="Before capture" />
        <Surface style={styles.steps}>
          <Step number="1" text="Place the target flat beside the ball, with its top edge parallel to the target line." />
          <Step number="2" text="Keep the complete black border and all four corners visible. Avoid glare, shadows, and a bent print." />
          <Step number="3" text="Print at 100% and confirm the ruler on the page measures exactly 100 mm." />
        </Surface>
      </View>

      <View style={styles.section}>
        <PrimaryButton
          label={tagCalibration ? 'AprilTag calibration saved' : 'Capture AprilTag calibration'}
          icon={tagCalibration ? 'checkmark-circle' : 'scan'}
          loading={capturingTag}
          disabled={!tagReady || capturingTag}
          onPress={() => void (async () => {
            setCapturingTag(true); setTagMessage(null);
            try {
              const calibration = await captureAprilTagCalibration();
              setTagCalibration(calibration);
              setTagMessage(`Saved ${calibration.pixelsPerMm?.toFixed(2) ?? '—'} px/mm · rotation ${calibration.rotationDeg?.toFixed(1) ?? '—'}°${calibration.distanceMm ? ` · distance ${Math.round(calibration.distanceMm)} mm` : ''}`);
            } catch (caught) { setTagMessage(caught instanceof Error ? caught.message : 'Could not capture the AprilTag calibration.'); }
            finally { setCapturingTag(false); }
          })()}
        />
        {tagMessage ? <Text style={styles.confirmation}>{tagMessage}</Text> : null}
        <Text style={styles.note}>Save the ground AprilTag calibration with the tag flat and fully visible. You may then remove it. Keep the camera position, lens focus, resolution and hitting surface fixed. Resetting the empty plane clears the saved geometry and target line; use the tag again to recalibrate. Lens calibration and club-marker geometry are still required for their respective measurements.</Text>
      </View>
    </ScrollView>
  );
}

function TagOverlay({ calibration }: { calibration: AprilTagCalibration }) {
  const points = calibration.corners?.map(([x, y]) => `${x * 100},${y * 100}`).join(' ') ?? '';
  return (
    <Svg pointerEvents="none" preserveAspectRatio="none" style={StyleSheet.absoluteFill} viewBox="0 0 100 100">
      <Polygon fill="rgba(137, 255, 118, 0.12)" points={points} stroke={colors.accent} strokeWidth={0.8} />
    </Svg>
  );
}

function BallOverlay({ bounds }: { bounds: [number, number, number, number] }) {
  return (
    <View
      pointerEvents="none"
      style={[
        styles.ballOverlay,
        {
          left: `${bounds[0] * 100}%`,
          top: `${bounds[1] * 100}%`,
          width: `${bounds[2] * 100}%`,
          height: `${bounds[3] * 100}%`,
        },
      ]}
    />
  );
}

function Step({ number, text }: { number: string; text: string }) {
  return <View style={styles.step}><View style={styles.stepNumber}><Text style={styles.stepNumberText}>{number}</Text></View><Text style={styles.stepText}>{text}</Text></View>;
}

const styles = StyleSheet.create({
  content: { paddingBottom: 110, paddingHorizontal: spacing.md },
  section: { marginTop: spacing.xl },
  hero: { alignItems: 'center', flexDirection: 'row', padding: spacing.lg },
  heroIcon: { alignItems: 'center', backgroundColor: '#192219', borderRadius: 22, height: 52, justifyContent: 'center', marginRight: 13, width: 52 },
  heroCopy: { flex: 1 },
  heroTitle: { color: colors.text, fontSize: 17, fontWeight: '800' },
  heroBody: { color: colors.textMuted, fontSize: 11, lineHeight: 16, marginTop: 4 },
  previewCard: { overflow: 'hidden' },
  preview: { backgroundColor: colors.surfaceRaised, position: 'relative', width: '100%' },
  image: { height: '100%', resizeMode: 'cover', width: '100%' },
  loading: { alignItems: 'center', gap: spacing.sm, height: '100%', justifyContent: 'center' },
  loadingText: { color: colors.textMuted, fontSize: 11, fontWeight: '700', textAlign: 'center' },
  frameGuide: { borderColor: colors.accent, borderRadius: radii.sm, borderStyle: 'dashed', borderWidth: 2, bottom: '12%', left: '10%', position: 'absolute', right: '10%', top: '12%' },
  previewStatus: { alignItems: 'center', flexDirection: 'row', gap: spacing.sm, padding: spacing.md },
  ballStatus: { alignItems: 'center', borderTopColor: colors.line, borderTopWidth: 1, flexDirection: 'row', gap: spacing.sm, padding: spacing.md },
  ballOverlay: { borderColor: colors.orange, borderRadius: 999, borderWidth: 3, position: 'absolute' },
  detectedText: { color: colors.accent },
  dot: { borderRadius: 4, height: 7, width: 7 },
  previewStatusText: { color: colors.textMuted, flex: 1, fontSize: 10, fontWeight: '700' },
  steps: { gap: spacing.md, padding: spacing.lg },
  planeCard: { alignItems: 'center', flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, padding: spacing.md },
  planeCopy: { flex: 1, minWidth: 160 },
  planeTitle: { color: colors.text, fontSize: 14, fontWeight: '800' },
  planeBody: { color: colors.textMuted, fontSize: 10, lineHeight: 14, marginTop: 3 },
  planeMessage: { color: colors.accent, fontSize: 10, fontWeight: '700', lineHeight: 14, width: '100%' },
  captureCard: { gap: spacing.md, padding: spacing.md },
  captureImage: { aspectRatio: 1.6, borderRadius: radii.sm, width: '100%' },
  lensCounterRow: { flexDirection: 'row', gap: spacing.lg },
  lensCounter: { alignItems: 'center', flex: 1 },
  lensCounterValue: { color: colors.text, fontSize: 22, fontWeight: '800' },
  lensCounterLabel: { color: colors.textMuted, fontSize: 10, fontWeight: '700', marginTop: 2 },
  lensLatestRow: { alignItems: 'center', flexDirection: 'row', gap: spacing.sm },
  lensLatestImage: { borderRadius: radii.sm, height: 64, width: 96 },
  lensLatestStatus: { alignItems: 'center', flex: 1, flexDirection: 'row', gap: spacing.sm },
  lensActionsRow: { flexDirection: 'row', gap: spacing.sm },
  lensActionCell: { flex: 1 },
  step: { alignItems: 'flex-start', flexDirection: 'row', gap: 11 },
  stepNumber: { alignItems: 'center', backgroundColor: '#192219', borderRadius: 12, height: 24, justifyContent: 'center', width: 24 },
  stepNumberText: { color: colors.accent, fontSize: 11, fontWeight: '800' },
  stepText: { color: colors.textMuted, flex: 1, fontSize: 11, lineHeight: 16, paddingTop: 2 },
  confirmation: { color: colors.accent, fontSize: 11, fontWeight: '700', lineHeight: 16, marginTop: spacing.md, textAlign: 'center' },
  note: { color: colors.textDim, fontSize: 10, lineHeight: 15, marginTop: spacing.md, textAlign: 'center' },
});
