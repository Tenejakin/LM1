import React, { useMemo } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Line, Text as SvgText } from 'react-native-svg';

import { Eyebrow, Surface } from '@/components/ui';
import { useUnits } from '@/context/UnitsContext';
import { getClub } from '@/data/clubs';
import { colors, spacing } from '@/theme';
import { ClubId, Shot } from '@/types';
import { shotEstimates } from '@/utils/carry';
import { clubSummaries, includedShots } from '@/utils/session';

const PALETTE: string[] = [colors.accent, colors.cyan, colors.orange, colors.red, colors.white, colors.textMuted];

/** Per-club averages, dispersion and gapping for the included shots of this session. */
export function SessionClubs({ shots }: { shots: Shot[] }) {
  const units = useUnits();
  const summaries = useMemo(() => clubSummaries(shots), [shots]);
  const excluded = shots.filter((shot) => shot.excluded).length;
  const color = useMemo(() => {
    const map = new Map<ClubId, string>();
    summaries.forEach((summary, index) => map.set(summary.clubId, PALETTE[index % PALETTE.length] ?? colors.textMuted));
    return map;
  }, [summaries]);
  if (!summaries.length) return null;
  const pm = (sd: number | null, digits = 1, format: (value: number, digits?: number) => string = (value, d) => value.toFixed(d)) =>
    sd === null ? '' : ` ± ${format(sd, digits)}`;
  return (
    <Surface style={styles.card}>
      <Eyebrow>Session by club</Eyebrow>
      <Text style={styles.title}>Averages, dispersion and gapping</Text>
      <DispersionPlot shots={shots} color={color} />
      {summaries.map((summary) => {
        const club = getClub(summary.clubId);
        const offline = summary.offlineM.mean;
        return (
          <View key={summary.clubId} style={styles.club}>
            <View style={styles.clubHeader}>
              <View style={[styles.swatch, { backgroundColor: color.get(summary.clubId) }]} />
              <Text style={styles.clubName}>{club.label}</Text>
              <Text style={styles.count}>{summary.shots} {summary.shots === 1 ? 'shot' : 'shots'}</Text>
            </View>
            <Text style={styles.line}>
              Carry {units.distance(summary.carryM.mean, 1)}{pm(summary.carryM.sd, 1, units.distance)} {units.distanceLabel}
              {' · '}Total {units.distance(summary.totalM.mean, 1)} {units.distanceLabel}
            </Text>
            <Text style={styles.line}>
              Offline {units.distance(Math.abs(offline), 1)} {units.distanceLabel} {Math.abs(offline) < 0.05 ? '' : offline < 0 ? 'L' : 'R'}
              {pm(summary.offlineM.sd, 1, units.distance)}
              {' · '}Launch {summary.launchAngleDeg.mean.toFixed(1)}°{pm(summary.launchAngleDeg.sd)}
            </Text>
            <Text style={styles.line}>
              Ball {units.speed(summary.ballSpeedMps.mean)}{pm(summary.ballSpeedMps.sd, 1, (v) => units.speed(v))} {units.speedLabel}
              {summary.clubSpeedMps ? ` · Club ${units.speed(summary.clubSpeedMps.mean)} ${units.speedLabel}` : ''}
              {summary.smashFactor ? ` · Smash ${summary.smashFactor.mean.toFixed(2)}` : ''}
            </Text>
            <Text style={styles.subtle}>
              {summary.attackAngleDeg ? `Attack ${summary.attackAngleDeg.mean.toFixed(1)}° · ` : ''}
              {summary.spinRpm ? `Spin ~${Math.round(summary.spinRpm.mean).toLocaleString()} rpm (estimate)` : ''}
            </Text>
            {summary.gapToNextM !== null ? (
              <Text style={styles.gap}>Gap to next club: {units.distance(summary.gapToNextM, 1)} {units.distanceLabel}</Text>
            ) : null}
          </View>
        );
      })}
      <Text style={styles.note}>
        ± is one standard deviation. Carry, total and offline are model estimates from the measured launch; club values
        count only shots where the camera resolved the club.{excluded ? ` ${excluded} excluded ${excluded === 1 ? 'shot is' : 'shots are'} left out.` : ''}
      </Text>
    </Surface>
  );
}

function DispersionPlot({ shots, color }: { shots: Shot[]; color: Map<ClubId, string> }) {
  const units = useUnits();
  const points = useMemo(() => includedShots(shots).flatMap((shot) => {
    const estimate = shotEstimates(shot);
    return estimate ? [{ id: shot.id, clubId: shot.clubId, x: estimate.flight.offlineM, y: estimate.flight.carryM }] : [];
  }), [shots]);
  if (points.length < 2) return null;
  const width = 300;
  const height = 180;
  const pad = 24;
  const maxCarry = Math.max(...points.map((point) => point.y)) * 1.1 || 1;
  const maxOffline = Math.max(1, ...points.map((point) => Math.abs(point.x))) * 1.2;
  const sx = (x: number) => width / 2 + (x / maxOffline) * (width / 2 - pad);
  const sy = (y: number) => height - pad - (y / maxCarry) * (height - 2 * pad);
  return (
    <View accessibilityLabel="Dispersion: carry against offline for each included shot" style={styles.plot}>
      <Svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`}>
        <Line x1={width / 2} y1={pad / 2} x2={width / 2} y2={height - pad} stroke={colors.line} strokeDasharray="4 4" />
        <Line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} stroke={colors.line} />
        {points.map((point) => (
          <Circle key={point.id} cx={sx(point.x)} cy={sy(point.y)} r={4} fill={color.get(point.clubId) ?? colors.textMuted} opacity={0.85} />
        ))}
        <SvgText x={pad} y={height - 6} fill={colors.textDim} fontSize={10}>L</SvgText>
        <SvgText x={width - pad} y={height - 6} fill={colors.textDim} fontSize={10} textAnchor="end">R</SvgText>
        <SvgText x={width / 2 + 4} y={pad} fill={colors.textDim} fontSize={10}>
          {`${units.distance(maxCarry)} ${units.distanceLabel}`}
        </SvgText>
      </Svg>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.sm, marginTop: spacing.md, padding: spacing.lg },
  title: { color: colors.text, fontSize: 18, fontWeight: '700' },
  plot: { marginVertical: spacing.xs },
  club: { borderTopColor: colors.line, borderTopWidth: 1, gap: 2, paddingTop: spacing.sm },
  clubHeader: { alignItems: 'center', flexDirection: 'row', gap: spacing.xs },
  swatch: { borderRadius: 5, height: 10, width: 10 },
  clubName: { color: colors.text, flex: 1, fontSize: 15, fontWeight: '700' },
  count: { color: colors.textMuted, fontSize: 12 },
  line: { color: colors.text, fontSize: 13, lineHeight: 18 },
  subtle: { color: colors.textMuted, fontSize: 12, lineHeight: 17 },
  gap: { color: colors.accent, fontSize: 12, fontWeight: '700', marginTop: 2 },
  note: { color: colors.textDim, fontSize: 11, lineHeight: 16 },
});
