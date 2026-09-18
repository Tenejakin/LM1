import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Image, Pressable, Text, View } from 'react-native';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { Eyebrow, Surface } from '@/components/ui';
import { colors, spacing } from '@/theme';

// A saved sheet never changes, so keep it for the app session instead of
// re-sending it over BLE whenever a card re-renders or a shot is reopened.
const sheetCache = new Map<string, string>();

export function ContactSheet({ captureId, card = false }: { captureId: string; card?: boolean }) {
  const { getCaptureContactSheet } = useLaunchMonitor();
  const [uri, setUri] = useState<string | null>(() => sheetCache.get(captureId) ?? null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const cached = sheetCache.get(captureId);
    setUri(cached ?? null);
    setError(null);
    if (cached) return;
    let cancelled = false;
    getCaptureContactSheet(captureId)
      .then((sheet) => {
        const next = `data:${sheet.mimeType};base64,${sheet.base64}`;
        sheetCache.set(captureId, next);
        if (!cancelled) setUri(next);
      })
      .catch((caught) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : 'Contact sheet unavailable.');
      });
    return () => { cancelled = true; };
  }, [attempt, captureId, getCaptureContactSheet]);

  const content = (
    <View style={{ gap: spacing.sm }}>
      <Eyebrow>Contact sheet</Eyebrow>
      <Text style={{ color: colors.textMuted, fontSize: 12 }}>
        12 frames from 30 before to 16 after the marked departure frame · left to right, top to bottom
      </Text>
      <View style={{ width: '100%', aspectRatio: 640 / 300, justifyContent: 'center', alignItems: 'center' }}>
        {uri ? (
          <Image
            accessibilityLabel="Contact sheet of frames around the ball departure"
            source={{ uri }}
            style={{ width: '100%', height: '100%', resizeMode: 'contain' }}
          />
        ) : error ? null : <ActivityIndicator color={colors.accent} />}
      </View>
      {error ? (
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md, flexWrap: 'wrap' }}>
          <Text style={{ color: colors.red, flexShrink: 1 }}>{error}</Text>
          <Pressable accessibilityRole="button" onPress={() => setAttempt((value) => value + 1)} style={{ padding: spacing.sm }}>
            <Text style={{ color: colors.accent }}>Retry</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );

  return card ? <Surface style={{ padding: spacing.lg, gap: spacing.sm }}>{content}</Surface> : content;
}
