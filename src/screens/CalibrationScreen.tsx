import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Image, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Polygon } from 'react-native-svg';

import { ScreenHeader } from '@/components/ScreenHeader';
import { StereoCalibrationScreen } from '@/screens/StereoCalibrationScreen';
import { PrimaryButton, SectionHeader, Surface } from '@/components/ui';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { colors, radii, spacing } from '@/theme';
import type { AprilTagCalibration, CalibrationCamera, ShotCoverage, ShotCoverageRating } from '@/types';

const APRILTAG_SIZE_MM = 100;

export function CalibrationScreen() {
  const [stereoOpen, setStereoOpen] = useState(false);
  const insets = useSafeAreaInsets();
  const {
    state, status, isDemo, previewFrame, secondaryPreviewFrame, previewDetection, previewAprilTag, latestCalibrationImage,
    resetBallCalibration, captureAprilTagCalibration, getLatestCapturePreview,
    captureCalibrationImage, clearCalibrationImages, runLensCalibration,
    getShotCoverage,
  } = useLaunchMonitor();
  const [clock, setClock] = useState(Date.now());
  const [lensCamera, setLensCamera] = useState<CalibrationCamera>('primary');
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
  const [coverage, setCoverage] = useState<ShotCoverage | null>(null);
  const [checkingCoverage, setCheckingCoverage] = useState(false);
  const [coverageMessage, setCoverageMessage] = useState<string | null>(null);
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
  const dualCamera = (status?.camera?.cameraCount ?? 1) >= 2;
  const secondaryCameraIndex = status?.camera?.secondaryCameraIndex ?? 1;
  const primaryCameraIndex = status?.camera?.primaryCameraIndex ?? 0;
  // Only the selected camera's own counts may drive its capture UI, so a view
  // saved for one lens can never be counted toward the other one's 12.
  const lensCounts = status?.calibrationCapture?.cameras?.[lensCamera]
    ?? (lensCamera === 'primary' ? status?.calibrationCapture : undefined);
  const lensImage = latestCalibrationImage?.camera === lensCamera ? latestCalibrationImage : null;
  const lensTotalSaved = lensImage?.totalSaved ?? lensCounts?.totalSaved ?? 0;
  const lensTotalWithCorners = lensImage?.totalWithCorners ?? lensCounts?.totalWithCorners ?? 0;
  const lensInstalled = status?.lensCalibration?.[lensCamera];
  const lensCameraLabel = lensCamera === 'primary'
    ? `Lower camera (CAM${primaryCameraIndex})`
    : `Upper camera (CAM${secondaryCameraIndex})`;
  const lensPreviewFrame = lensCamera === 'primary' ? previewFrame : secondaryPreviewFrame;
  const lensPreviewReady = Boolean(lensPreviewFrame) && boardReady && (lensCamera === 'primary' || dualCamera);
  const calibrationLabel = useMemo(() => {
    if (tagCalibration) return 'AprilTag calibration saved';
    if (tagReady) return 'AprilTag locked - ready to capture';
    if (boardReady) return 'Searching for AprilTag 36h11 ID 0';
    return 'Waiting for live camera';
  }, [boardReady, tagCalibration, tagReady]);

  return (
    <ScrollView contentContainerStyle={[styles.content, { paddingTop: insets.top + spacing.md }]} showsVerticalScrollIndicator={false}>
      <ScreenHeader title="Calibration" subtitle="AprilTag metric reference" state={state} demo={isDemo} />
      <PrimaryButton label="Calibrate both cameras as a fixed pair" icon="scan" onPress={() => setStereoOpen(true)} />
      {stereoOpen ? <StereoCalibrationScreen onClose={() => setStereoOpen(false)} /> : null}

      <Surface style={styles.hero}>
        <View style={styles.heroIcon}><Ionicons name="scan" color={colors.accent} size={29} /></View>
        <View style={styles.heroCopy}>
          <Text style={styles.heroTitle}>{calibrationLabel}</Text>
          <Text style={styles.heroBody}>Use the printed {APRILTAG_SIZE_MM} mm AprilTag whenever LM1 is moved. It establishes ground level, tilt and scale. The bottom camera defines left-to-right zero direction.</Text>
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
                  : 'Place the ball in the left-half green zone on the Device camera view'}
            </Text>
          </View>
        </Surface>
      </View>

      <View style={styles.section}>
        <SectionHeader title="Lens calibration capture" />
        <Surface style={styles.captureCard}>
          <View style={styles.cameraTabs}>
            <CameraTab
              label={`Lower CAM${primaryCameraIndex}`}
              hint="detection"
              selected={lensCamera === 'primary'}
              onPress={() => {
                setLensCamera('primary');
                setLensCaptureMessage(null);
                setLensCalibrationMessage(null);
              }}
            />
            <CameraTab
              label={`Upper CAM${secondaryCameraIndex}`}
              hint={dualCamera ? 'second view' : 'not streaming'}
              disabled={!dualCamera}
              selected={lensCamera === 'secondary'}
              onPress={() => {
                setLensCamera('secondary');
                setLensCaptureMessage(null);
                setLensCalibrationMessage(null);
              }}
            />
          </View>
          <View style={styles.lensPreview}>
            {lensPreviewFrame && !isDemo ? (
              <Image
                accessibilityLabel={`${lensCameraLabel} calibration preview`}
                source={{ uri: lensPreviewFrame }}
                style={styles.image}
              />
            ) : (
              <View style={styles.loading}>
                <Text style={styles.loadingText}>
                  {isDemo
                    ? 'Connect LM1 to use checkerboard calibration.'
                    : lensCamera === 'secondary' && !dualCamera
                      ? 'The upper camera is not streaming. Enable dual camera mode on LM1 first.'
                      : 'Waiting for a camera preview…'}
                </Text>
              </View>
            )}
          </View>
          <Text style={styles.planeBody}>
            Calibrating {lensCameraLabel}. Each camera keeps its own set of views and its own
            saved intrinsics, so capture a full batch for one camera before switching.
            Hold the printed checkerboard so it fills roughly half of this preview and press Capture.
            Vary its tilt - forward/back and left/right, not just position - between shots.
            At least 12 diverse views with corners found are needed before running calibration.
          </Text>
          <View style={styles.previewStatus}>
            <View style={[styles.dot, { backgroundColor: lensInstalled ? colors.accent : colors.orange }]} />
            <Text style={styles.previewStatusText}>
              {lensInstalled
                ? `Intrinsics saved · RMS ${lensInstalled.rmsPx?.toFixed(3) ?? '—'}px from ${lensInstalled.views ?? 0} views at ${lensInstalled.imageSize?.[0] ?? '—'}x${lensInstalled.imageSize?.[1] ?? '—'}`
                : 'No lens calibration saved for this camera yet'}
            </Text>
          </View>
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
          {lensImage ? (
            <View style={styles.lensLatestRow}>
              {lensImage.image ? (
                <Image
                  accessibilityLabel="Latest calibration capture"
                  source={{ uri: `data:${lensImage.image.mimeType};base64,${lensImage.image.base64}` }}
                  style={styles.lensLatestImage}
                />
              ) : null}
              <View style={styles.lensLatestStatus}>
                <Ionicons
                  name={lensImage.cornersFound ? 'checkmark-circle' : 'close-circle'}
                  color={lensImage.cornersFound ? colors.accent : colors.orange}
                  size={20}
                />
                <Text style={styles.previewStatusText}>
                  {lensImage.error
                    ? lensImage.error
                    : lensImage.cornersFound
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
            disabled={!lensPreviewReady || capturingLensImage}
            onPress={() => void (async () => {
              setCapturingLensImage(true);
              setLensCaptureMessage(null);
              try {
                await captureCalibrationImage(lensCamera);
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
                    await clearCalibrationImages(lensCamera);
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
                    const result = await runLensCalibration(lensCamera);
                    setLensCalibrationMessage(
                      `${lensCameraLabel} saved - RMS ${result.rmsPx.toFixed(3)}px from ${result.viewsUsed}/${result.viewsTotal} views at ${result.imageSize[0]}x${result.imageSize[1]}.`
                      + (lensCamera === 'primary' ? ' Ground calibration and target line were cleared; capture the AprilTag again.' : ''),
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
        <SectionHeader title="Automatic target line" />
        <Surface style={styles.captureCard}>
          <Text style={styles.planeBody}>
            Zero direction runs left to right across the bottom camera, projected onto the ground.
            Align the monitor with your intended shot line. No calibration roll is needed.
            The AprilTag establishes ground level, tilt and scale; its rotation does not set the target.
            Saved manual target lines are ignored by Pi service 0.36.1 and newer.
          </Text>
        </Surface>
      </View>

      <View style={styles.section}>
        <SectionHeader title="Shot coverage" />
        <Surface style={styles.captureCard}>
          <Text style={styles.planeBody}>
            At about 240 fps a driver ball moves roughly 30 cm between frames. Launch values need the
            ball in at least 3 frames after impact, so what matters is how much of its path this camera
            sees. Place a ball where you hit from, then check. Uses the saved lens and AprilTag calibration
            of the lower camera.
          </Text>
          <PrimaryButton
            label={coverage ? 'Check again' : 'Check coverage'}
            icon="speedometer"
            variant="outline"
            loading={checkingCoverage}
            disabled={!boardReady || checkingCoverage || !tagCalibration}
            onPress={() => void (async () => {
              setCheckingCoverage(true);
              setCoverageMessage(null);
              try {
                setCoverage(await getShotCoverage());
              } catch (caught) {
                setCoverageMessage(caught instanceof Error ? caught.message : 'Could not check shot coverage.');
              } finally {
                setCheckingCoverage(false);
              }
            })()}
          />
          {!tagCalibration ? (
            <Text style={styles.planeMessage}>Save the AprilTag calibration first; coverage is projected through it.</Text>
          ) : null}
          {coverageMessage ? <Text style={styles.planeMessage}>{coverageMessage}</Text> : null}
          {coverage ? (
            <View style={styles.coverage}>
              <Text style={styles.previewStatusText}>
                {coverage.fps} fps · {coverage.frameIntervalMs} ms per frame · ball {Math.round(coverage.ballDiameterPx)} px wide,
                {' '}{(coverage.cameraToBallMm / 10).toFixed(0)} cm from the lens · {(coverage.downrangePathMm / 10).toFixed(0)} cm visible
                downrange, {(coverage.behindBallMm / 10).toFixed(0)} cm behind the ball
              </Text>
              <View style={[styles.coverageRow, styles.coverageHeader]}>
                <Text style={[styles.coverageShot, styles.coverageHeaderText]}>Shot</Text>
                <Text style={[styles.coverageCell, styles.coverageHeaderText]}>Per frame</Text>
                <Text style={[styles.coverageCell, styles.coverageHeaderText]}>In view</Text>
                <Text style={[styles.coverageCell, styles.coverageHeaderText]}>Frames</Text>
              </View>
              {coverage.shots.map((shot) => (
                <View key={shot.id} style={styles.coverageRow}>
                  <View style={styles.coverageShot}>
                    <Text style={styles.coverageLabel}>{shot.label}</Text>
                    <Text style={styles.coverageHint}>{shot.ballSpeedMps} m/s · {shot.launchDeg}°</Text>
                  </View>
                  <Text style={styles.coverageCell}>{(shot.travelPerFrameMm / 10).toFixed(1)} cm</Text>
                  <Text style={styles.coverageCell}>{(shot.visiblePathMm / 10).toFixed(0)} cm</Text>
                  <View style={styles.coverageCell}>
                    <Text style={[styles.coverageFrames, { color: ratingColor(shot.rating) }]}>
                      {shot.framesMin}–{shot.framesMax}
                    </Text>
                    <Text style={[styles.coverageHint, { color: ratingColor(shot.rating) }]}>{ratingLabel(shot.rating)}</Text>
                  </View>
                </View>
              ))}
              {coverage.notes.map((note) => (
                <View key={note} style={styles.coverageNote}>
                  <Ionicons name="bulb-outline" color={colors.orange} size={15} />
                  <Text style={styles.previewStatusText}>{note}</Text>
                </View>
              ))}
              <Text style={styles.note}>
                Geometry only: a frame counts when the whole ball is inside the image. Lighting, blur and the club
                passing over the ball can still lose frames.
              </Text>
            </View>
          ) : null}
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
          <Step number="1" text="Place the tag flat beside the ball and fully visible in both cameras. Its rotation does not define the target line." />
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
              const lines = [`Lower camera: ${describeGroundPose(calibration)}`];
              if (calibration.secondary) lines.push(`Top camera: ${describeGroundPose(calibration.secondary)}`);
              else if (calibration.secondaryError) lines.push(`Top camera not calibrated: ${calibration.secondaryError}`);
              setTagMessage(lines.join('\n'));
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

function describeGroundPose(calibration: AprilTagCalibration) {
  const pose = calibration.groundPose;
  if (pose?.cameraHeightMm === undefined) return `saved ${calibration.pixelsPerMm?.toFixed(2) ?? '—'} px/mm`;
  return `${Math.round(pose.cameraHeightMm)} mm high · tilted ${pose.cameraPitchDeg?.toFixed(1) ?? '—'}° down · pose error ${pose.errorPx?.toFixed(2) ?? '—'} px`;
}

function CameraTab({ label, hint, selected, disabled, onPress }: {
  label: string;
  hint: string;
  selected: boolean;
  disabled?: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="tab"
      accessibilityState={{ selected, disabled: Boolean(disabled) }}
      disabled={disabled}
      onPress={onPress}
      style={[styles.cameraTab, selected && styles.cameraTabSelected, disabled && styles.cameraTabDisabled]}
    >
      <Text style={[styles.cameraTabLabel, selected && styles.detectedText]}>{label}</Text>
      <Text style={styles.cameraTabHint}>{hint}</Text>
    </Pressable>
  );
}

function ratingColor(rating: ShotCoverageRating) {
  if (rating === 'good') return colors.accent;
  if (rating === 'marginal') return colors.orange;
  return colors.red;
}

function ratingLabel(rating: ShotCoverageRating) {
  if (rating === 'good') return 'good';
  if (rating === 'marginal') return 'just enough';
  return 'too few';
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
  coverage: { gap: spacing.sm },
  coverageRow: { alignItems: 'center', borderTopColor: colors.line, borderTopWidth: 1, flexDirection: 'row', paddingVertical: spacing.sm },
  coverageHeader: { borderTopWidth: 0, paddingBottom: 0 },
  coverageHeaderText: { color: colors.textDim, fontSize: 9, fontWeight: '800', textTransform: 'uppercase' },
  coverageShot: { flex: 1.3 },
  coverageCell: { alignItems: 'flex-end', color: colors.text, flex: 1, fontSize: 12, fontWeight: '700', textAlign: 'right' },
  coverageLabel: { color: colors.text, fontSize: 13, fontWeight: '800' },
  coverageHint: { color: colors.textDim, fontSize: 9, fontWeight: '700', marginTop: 1 },
  coverageFrames: { fontSize: 15, fontWeight: '800' },
  coverageNote: { alignItems: 'flex-start', flexDirection: 'row', gap: spacing.sm },
  cameraTabs: { flexDirection: 'row', gap: spacing.sm },
  cameraTab: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderColor: colors.line, borderRadius: radii.sm, borderWidth: 1, flex: 1, paddingVertical: spacing.sm },
  cameraTabSelected: { backgroundColor: '#192219', borderColor: colors.accent },
  cameraTabDisabled: { opacity: 0.45 },
  cameraTabLabel: { color: colors.text, fontSize: 12, fontWeight: '800' },
  cameraTabHint: { color: colors.textDim, fontSize: 9, fontWeight: '700', marginTop: 2 },
  lensPreview: { aspectRatio: 1.6, backgroundColor: colors.surfaceRaised, borderRadius: radii.sm, overflow: 'hidden', width: '100%' },
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
