import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Image, LayoutChangeEvent, Pressable, StyleSheet, Text, View } from 'react-native';

import { Surface } from '@/components/ui';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { colors, radii, spacing } from '@/theme';
import { CaptureClip, Shot } from '@/types';

/** Frames before and after the ball's first moving frame: club approach, contact, launch. */
const FRAMES_BEFORE = 10;
const FRAMES_AFTER = 9;
const BATCH = 8;
const FRAME_INTERVAL_MS = 90;
const SENSOR_FRAME_MS = 1000 / 242;
const CACHE_LIMIT = 8;

type ClipFrame = CaptureClip['frames'][number];
interface LoadedClip { frames: ClipFrame[]; impact: number; aspect: number }

// Frames cross BLE at ~12-16 KB/s, so a loop is fetched once per capture and kept.
const clipCache = new Map<string, LoadedClip>();

function remember(captureId: string, clip: LoadedClip) {
  clipCache.delete(captureId);
  clipCache.set(captureId, clip);
  while (clipCache.size > CACHE_LIMIT) clipCache.delete(clipCache.keys().next().value!);
}

/**
 * The captured swing as a slow-motion loop. Tap the picture to stop on a frame, then
 * step with the arrows or tap the bar to jump; tap again to resume.
 */
export function SwingLoop({ shot }: { shot: Pick<Shot, 'captureId' | 'firstMovingFrameIndex' | 'impactFrameIndex' | 'frameCount'> }) {
  const { getCaptureClip, isDemo, deviceId, state } = useLaunchMonitor();
  const captureId = shot.captureId;
  const impact = shot.firstMovingFrameIndex ?? shot.impactFrameIndex;
  const connected = !isDemo && Boolean(deviceId) && state !== 'offline' && state !== 'connecting' && state !== 'error';
  const [clip, setClip] = useState<LoadedClip | null>(() => (captureId ? clipCache.get(captureId) ?? null : null));
  const [progress, setProgress] = useState<{ loaded: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [position, setPosition] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [barWidth, setBarWidth] = useState(1);
  const loadingFor = useRef<string | null>(null);

  useEffect(() => {
    setPosition(0);
    setPlaying(true);
    setError(null);
    if (!captureId || impact == null) return;
    const cached = clipCache.get(captureId);
    setClip(cached ?? null);
    if (cached || !connected || loadingFor.current === captureId) return;
    loadingFor.current = captureId;
    let cancelled = false;
    const start = Math.max(0, impact - FRAMES_BEFORE);
    const end = Math.min(Math.max(shot.frameCount - 1, 0), impact + FRAMES_AFTER);
    const total = end - start + 1;
    void (async () => {
      const frames: ClipFrame[] = [];
      let aspect = 1.5;
      try {
        for (let first = start; first <= end; first += BATCH) {
          setProgress({ loaded: frames.length, total });
          const batch = await getCaptureClip(captureId, first, Math.min(BATCH, end - first + 1));
          if (cancelled) return;
          frames.push(...batch.frames);
          aspect = batch.cropBox[2] / Math.max(1, batch.cropBox[3]);
        }
        const loaded = { frames, impact, aspect };
        remember(captureId, loaded);
        setClip(loaded);
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : 'Could not load the swing.');
      } finally {
        if (loadingFor.current === captureId) loadingFor.current = null;
        if (!cancelled) setProgress(null);
      }
    })();
    return () => { cancelled = true; };
  }, [captureId, impact, connected, getCaptureClip, shot.frameCount]);

  useEffect(() => {
    if (!clip || !playing) return;
    const timer = setInterval(() => setPosition((current) => (current + 1) % clip.frames.length), FRAME_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [clip, playing]);

  if (!captureId || impact == null) return null;
  if (!clip) {
    if (!connected && !error) return null;
    return (
      <Surface style={styles.card}>
        <View style={[styles.placeholder, { aspectRatio: 1.5 }]}>
          {error ? (
            <Text style={styles.error}>Swing unavailable: {error}</Text>
          ) : (
            <>
              <ActivityIndicator color={colors.accent} />
              <Text style={styles.hint}>
                Loading swing{progress ? ` · ${progress.loaded}/${progress.total} frames` : ''}
              </Text>
            </>
          )}
        </View>
      </Surface>
    );
  }

  const frame = clip.frames[Math.min(position, clip.frames.length - 1)];
  if (!frame) return null;
  const impactPosition = clip.frames.findIndex((item) => item.frameIndex === clip.impact);
  const offset = frame.frameIndex - clip.impact;
  const impactFrame = clip.frames[impactPosition];
  const offsetMs = frame.timeMs != null && impactFrame?.timeMs != null
    ? frame.timeMs - impactFrame.timeMs : offset * SENSOR_FRAME_MS;
  const label = offset === 0 ? 'Ball starts moving'
    : `${offset > 0 ? '+' : '−'}${Math.abs(offset)} ${Math.abs(offset) === 1 ? 'frame' : 'frames'} · ${Math.abs(offsetMs).toFixed(1)} ms ${offset > 0 ? 'after' : 'before'}`;
  const step = (delta: number) => {
    setPlaying(false);
    setPosition((current) => (current + delta + clip.frames.length) % clip.frames.length);
  };
  const jump = (x: number) => {
    setPlaying(false);
    setPosition(Math.max(0, Math.min(clip.frames.length - 1, Math.round((x / barWidth) * (clip.frames.length - 1)))));
  };

  return (
    <Surface style={styles.card}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={playing ? 'Pause the swing on this frame' : 'Resume the swing loop'}
        onPress={() => setPlaying((value) => !value)}
        style={[styles.stage, { aspectRatio: clip.aspect }]}
      >
        {clip.frames.map((item, index) => (
          <Image
            key={item.frameIndex}
            accessibilityIgnoresInvertColors
            source={{ uri: `data:image/jpeg;base64,${item.base64}` }}
            style={[StyleSheet.absoluteFill, { opacity: index === position ? 1 : 0 }]}
            resizeMode="contain"
          />
        ))}
        {!playing ? (
          <View style={styles.pausedBadge}>
            <Ionicons name="pause" size={12} color={colors.text} />
            <Text style={styles.pausedText}>Paused · tap to play</Text>
          </View>
        ) : null}
      </Pressable>
      <View style={styles.controls}>
        <Pressable accessibilityRole="button" accessibilityLabel="Previous frame" hitSlop={8} onPress={() => step(-1)} style={styles.stepButton}>
          <Ionicons name="chevron-back" size={18} color={colors.text} />
        </Pressable>
        <View style={styles.middle}>
          <Text style={[styles.frameLabel, offset === 0 && styles.frameLabelImpact]}>{label}</Text>
          <Pressable
            accessibilityRole="adjustable"
            accessibilityLabel="Swing position; tap to jump to a frame"
            onLayout={(event: LayoutChangeEvent) => setBarWidth(Math.max(1, event.nativeEvent.layout.width))}
            onPress={(event) => jump(event.nativeEvent.locationX)}
            style={styles.bar}
          >
            <View style={[styles.barFill, { width: `${((position + 1) / clip.frames.length) * 100}%` }]} />
            {impactPosition >= 0 ? (
              <View style={[styles.impactMark, { left: `${(impactPosition / Math.max(1, clip.frames.length - 1)) * 100}%` }]} />
            ) : null}
          </Pressable>
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel="Next frame" hitSlop={8} onPress={() => step(1)} style={styles.stepButton}>
          <Ionicons name="chevron-forward" size={18} color={colors.text} />
        </Pressable>
      </View>
    </Surface>
  );
}

const styles = StyleSheet.create({
  card: { marginBottom: spacing.sm, overflow: 'hidden', padding: spacing.sm },
  stage: { backgroundColor: colors.black, borderRadius: radii.sm, overflow: 'hidden', width: '100%' },
  placeholder: { alignItems: 'center', backgroundColor: colors.black, borderRadius: radii.sm, gap: spacing.xs, justifyContent: 'center', padding: spacing.md, width: '100%' },
  hint: { color: colors.textMuted, fontSize: 12 },
  error: { color: colors.textMuted, fontSize: 12, textAlign: 'center' },
  pausedBadge: {
    alignItems: 'center', backgroundColor: '#000000A0', borderRadius: radii.pill, flexDirection: 'row', gap: 4,
    left: spacing.xs, paddingHorizontal: 8, paddingVertical: 4, position: 'absolute', top: spacing.xs,
  },
  pausedText: { color: colors.text, fontSize: 11, fontWeight: '700' },
  controls: { alignItems: 'center', flexDirection: 'row', gap: spacing.xs, marginTop: spacing.xs },
  stepButton: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderRadius: 6, height: 32, justifyContent: 'center', width: 32 },
  middle: { flex: 1, gap: 6 },
  frameLabel: { color: colors.textMuted, fontSize: 12, fontWeight: '600', textAlign: 'center' },
  frameLabelImpact: { color: colors.accent },
  bar: { backgroundColor: colors.surfaceRaised, borderRadius: 4, height: 8, justifyContent: 'center' },
  barFill: { backgroundColor: colors.lineStrong, borderRadius: 4, height: 8 },
  impactMark: { backgroundColor: colors.accent, borderRadius: 2, height: 14, marginLeft: -2, position: 'absolute', width: 4 },
});
