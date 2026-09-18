import Ionicons from '@expo/vector-icons/Ionicons';
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Defs, G, LinearGradient, Line, Path, Stop } from 'react-native-svg';

import { colors, radii, spacing } from '@/theme';
import { getClub } from '@/data/clubs';
import { Shot } from '@/types';
import { useUnits } from '@/context/UnitsContext';

export function StrikeMap({ shot, compact = false }: { shot: Shot; compact?: boolean }) {
  const x = Math.max(35, Math.min(245, 140 + shot.strike.xMm * 5.2));
  const y = Math.max(28, Math.min(112, 70 - shot.strike.yMm * 4));

  return (
    <View accessibilityLabel={`Strike ${strikeLabel(shot)}`} style={compact && styles.compactVisual}>
      <Svg width="100%" height={compact ? 105 : 150} viewBox="0 0 280 140">
        <Defs>
          <LinearGradient id="face" x1="0" y1="0" x2="1" y2="1">
            <Stop offset="0" stopColor="#252C2F" />
            <Stop offset="1" stopColor="#121719" />
          </LinearGradient>
        </Defs>
        <Path
          d="M30 43 Q30 25 49 23 L227 29 Q247 31 250 50 L255 94 Q256 110 238 113 L45 117 Q25 117 27 98 Z"
          fill="url(#face)"
          stroke={colors.lineStrong}
          strokeWidth="2"
        />
        {[48, 61, 74, 87, 100].map((lineY) => (
          <Path
            key={lineY}
            d={`M37 ${lineY} Q140 ${lineY - 3} 246 ${lineY + 1}`}
            stroke={colors.line}
            strokeWidth="1"
          />
        ))}
        <Line x1="140" y1="30" x2="140" y2="112" stroke={colors.lineStrong} strokeDasharray="4 6" />
        <Circle cx={x} cy={y} r="14" fill={colors.accent} opacity="0.15" />
        <Circle cx={x} cy={y} r="6" fill={colors.accent} />
        <Circle cx={x} cy={y} r="2" fill={colors.accentInk} />
        {!compact ? (
          <G>
            <Line x1={x} y1={y + 16} x2={x} y2="132" stroke={colors.accent} strokeDasharray="2 4" />
          </G>
        ) : null}
      </Svg>
      {!compact ? (
        <View style={styles.mapLabels}>
          <Text style={styles.mapEdgeLabel}>HEEL</Text>
          <Text style={styles.strikeText}>{strikeLabel(shot)}</Text>
          <Text style={styles.mapEdgeLabel}>TOE</Text>
        </View>
      ) : null}
    </View>
  );
}

export function TrajectoryChart({ shot, compact = false }: { shot: Shot; compact?: boolean }) {
  const endY = 54 - Math.min(17, Math.max(-17, shot.startDirectionDeg * 4));
  const controlY = endY + 18 - shot.launchAngleDeg * 0.5;
  return (
    <View accessibilityLabel={`Start direction ${directionLabel(shot.startDirectionDeg)}`}>
      <Svg width="100%" height={compact ? 116 : 155} viewBox="0 0 320 150">
        <Defs>
          <LinearGradient id="trail" x1="0" y1="1" x2="1" y2="0">
            <Stop offset="0" stopColor={colors.accent} stopOpacity="0.28" />
            <Stop offset="1" stopColor={colors.accent} stopOpacity="1" />
          </LinearGradient>
        </Defs>
        <Line x1="20" y1="126" x2="306" y2="126" stroke={colors.lineStrong} strokeWidth="1" />
        <Line x1="35" y1="126" x2="292" y2="40" stroke={colors.line} strokeDasharray="4 7" />
        <Path
          d={`M35 125 Q150 ${controlY + 28} 292 ${endY}`}
          fill="none"
          stroke="url(#trail)"
          strokeWidth="4"
          strokeLinecap="round"
        />
        {[0, 1, 2, 3].map((index) => {
          const cx = 35 + index * 65;
          const progress = index / 4;
          const cy = 125 * (1 - progress) + (controlY + 28) * progress - 16 * progress;
          return <Circle key={index} cx={cx} cy={cy} r="3" fill={colors.accent} opacity={0.35 + index * 0.16} />;
        })}
        <Circle cx="292" cy={endY} r="7" fill={colors.accent} />
        <Circle cx="292" cy={endY} r="15" fill={colors.accent} opacity="0.12" />
        <Circle cx="35" cy="125" r="5" fill={colors.white} />
      </Svg>
      {!compact ? (
        <View style={styles.trajectoryLabels}>
          <View>
            <Text style={styles.visualLabel}>LAUNCH</Text>
            <Text style={styles.visualValue}>{shot.launchAngleDeg.toFixed(1)}°</Text>
          </View>
          <View style={styles.alignRight}>
            <Text style={styles.visualLabel}>START LINE</Text>
            <Text style={styles.visualValue}>{directionLabel(shot.startDirectionDeg)}</Text>
          </View>
        </View>
      ) : null}
    </View>
  );
}

export function ShotRow({ shot, onPress }: { shot: Shot; onPress: () => void }) {
  const club = getClub(shot.clubId);
  const units = useUnits();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Open shot ${shot.number}, ${club.label}, ball speed ${units.speed(shot.ballSpeedMps)} ${units.spokenSpeedLabel}, estimated carry ${units.distance(shot.estimatedCarryM)} ${units.spokenDistanceLabel}`}
      onPress={onPress}
      style={({ pressed }) => [styles.shotRow, pressed && styles.shotRowPressed]}
    >
      <View style={styles.shotNumber}>
        <Text style={styles.shotHash}>#</Text>
        <Text style={styles.shotNumberText}>{shot.number}</Text>
      </View>
      <View style={styles.shotMain}>
        <Text style={styles.shotSpeed}>{units.speed(shot.ballSpeedMps)}</Text>
        <Text style={styles.shotUnit}>{club.shortLabel} · {units.speedLabel}</Text>
      </View>
      <View style={styles.shotMeta}>
        <Text style={styles.shotSmash}>{shot.smashFactor.toFixed(2)} smash</Text>
        <Text style={styles.shotDirection}>{units.distanceWithUnit(shot.estimatedCarryM)}</Text>
      </View>
      <Ionicons name="chevron-forward" size={18} color={colors.textDim} />
    </Pressable>
  );
}

export function directionLabel(value: number): string {
  if (Math.abs(value) < 0.05) return 'Straight';
  return `${Math.abs(value).toFixed(1)}° ${value > 0 ? 'R' : 'L'}`;
}

export function strikeLabel(shot: Shot): string {
  const horizontal = Math.abs(shot.strike.xMm) < 1
    ? 'centered'
    : `${Math.abs(shot.strike.xMm).toFixed(0)} mm ${shot.strike.xMm > 0 ? 'toe' : 'heel'}`;
  const vertical = Math.abs(shot.strike.yMm) < 1
    ? ''
    : ` · ${Math.abs(shot.strike.yMm).toFixed(0)} mm ${shot.strike.yMm > 0 ? 'high' : 'low'}`;
  return `${horizontal}${vertical}`;
}

const styles = StyleSheet.create({
  compactVisual: { marginVertical: -10 },
  mapLabels: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: -2,
  },
  mapEdgeLabel: { color: colors.textDim, fontSize: 9, fontWeight: '800', letterSpacing: 1.1 },
  strikeText: { color: colors.text, fontSize: 13, fontWeight: '700', textTransform: 'capitalize' },
  trajectoryLabels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: -8,
  },
  visualLabel: { color: colors.textDim, fontSize: 9, fontWeight: '800', letterSpacing: 1.1 },
  visualValue: { color: colors.text, fontSize: 17, fontWeight: '700', marginTop: 3 },
  alignRight: { alignItems: 'flex-end' },
  shotRow: {
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderColor: colors.line,
    borderRadius: radii.md,
    borderWidth: 1,
    flexDirection: 'row',
    gap: spacing.md,
    minHeight: 76,
    paddingHorizontal: spacing.md,
  },
  shotRowPressed: { backgroundColor: colors.surfaceRaised, transform: [{ scale: 0.99 }] },
  shotNumber: {
    alignItems: 'baseline',
    backgroundColor: colors.surfaceRaised,
    borderRadius: 12,
    flexDirection: 'row',
    justifyContent: 'center',
    height: 44,
    width: 48,
  },
  shotHash: { color: colors.textDim, fontSize: 11, fontWeight: '700' },
  shotNumberText: { color: colors.text, fontSize: 16, fontWeight: '800' },
  shotMain: { flex: 1 },
  shotSpeed: { color: colors.text, fontSize: 24, fontWeight: '700', letterSpacing: -0.8 },
  shotUnit: { color: colors.textMuted, fontSize: 10, fontWeight: '600', marginTop: -2 },
  shotMeta: { alignItems: 'flex-end', gap: 4 },
  shotSmash: { color: colors.text, fontSize: 12, fontWeight: '700' },
  shotDirection: { color: colors.textMuted, fontSize: 11, fontWeight: '600' },
});
