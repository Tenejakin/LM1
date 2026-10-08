import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useEffect, useMemo, useState } from 'react';
import {
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ClubSelector } from '@/components/ClubSelector';
import { ScreenHeader } from '@/components/ScreenHeader';
import { directionLabel, StrikeMap, strikeLabel, TrajectoryChart } from '@/components/ShotVisuals';
import { Eyebrow, MetricTile, PrimaryButton, SectionHeader, Surface } from '@/components/ui';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { useOpenGolfSim } from '@/context/OpenGolfSimContext';
import { SpeedUnit, useUnits } from '@/context/UnitsContext';
import { getClub } from '@/data/clubs';
import { colors, radii, spacing } from '@/theme';
import { Shot } from '@/types';
import { estimateCarryMeters } from '@/utils/carry';
import { measuredClubSpeed, measuredSmash } from '@/utils/shotValues';
import { kmhToMps, mpsToKmh } from '@/utils/speed';

interface CalculatorInputs {
  ballSpeed: string;
  clubSpeed: string;
  launchAngle: string;
  startDirection: string;
  strikeX: string;
  strikeY: string;
}

const initialInputs: CalculatorInputs = {
  ballSpeed: '',
  clubSpeed: '',
  launchAngle: '',
  startDirection: '0',
  strikeX: '0',
  strikeY: '0',
};

const MPH_PER_MPS = 2.23694;

export function CalculatorScreen() {
  const insets = useSafeAreaInsets();
  const { state, isDemo, selectedClub } = useLaunchMonitor();
  const units = useUnits();
  const { speedUnit, setSpeedUnit } = units;
  const [inputs, setInputs] = useState<CalculatorInputs>(initialInputs);
  const [hasCalculated, setHasCalculated] = useState(false);

  const calculatedShot = useMemo<Shot | null>(() => {
    const ballInput = parseNumber(inputs.ballSpeed);
    const clubInput = parseNumber(inputs.clubSpeed);
    const launchAngleDeg = parseNumber(inputs.launchAngle);
    const startDirectionDeg = parseNumber(inputs.startDirection);
    const strikeX = parseNumber(inputs.strikeX);
    const strikeY = parseNumber(inputs.strikeY);

    if (
      ballInput === null ||
      clubInput === null ||
      launchAngleDeg === null ||
      startDirectionDeg === null ||
      strikeX === null ||
      strikeY === null
    ) return null;

    const ballSpeedMps = speedUnit === 'mph' ? ballInput / MPH_PER_MPS : kmhToMps(ballInput);
    const clubSpeedMps = speedUnit === 'mph' ? clubInput / MPH_PER_MPS : kmhToMps(clubInput);
    if (
      ballSpeedMps <= 0 || ballSpeedMps > 100 ||
      clubSpeedMps <= 0 || clubSpeedMps > 70 ||
      launchAngleDeg < -5 || launchAngleDeg > 60 ||
      Math.abs(startDirectionDeg) > 45 ||
      Math.abs(strikeX) > 40 ||
      Math.abs(strikeY) > 30
    ) return null;

    const baseShot: Shot = {
      id: 'manual-calculation',
      number: 0,
      capturedAt: new Date().toISOString(),
      clubId: selectedClub,
      ballSpeedMps,
      clubSpeedMps,
      smashFactor: ballSpeedMps / clubSpeedMps,
      launchAngleDeg,
      startDirectionDeg,
      strike: { xMm: strikeX, yMm: strikeY },
      confidence: 1,
      frameCount: 0,
      captureDurationMs: 0,
      estimatedCarryM: 0,
    };

    return { ...baseShot, estimatedCarryM: estimateCarryMeters(baseShot) };
  }, [inputs, selectedClub, speedUnit]);

  const updateInput = (key: keyof CalculatorInputs, value: string) => {
    setInputs((current) => ({ ...current, [key]: sanitizeNumericInput(value) }));
  };

  const changeUnit = (nextUnit: SpeedUnit) => {
    if (nextUnit === speedUnit) return;
    const convert = (value: string) => {
      const parsed = parseNumber(value);
      if (parsed === null) return value;
      const speedMps = speedUnit === 'mph' ? parsed / MPH_PER_MPS : kmhToMps(parsed);
      const converted = nextUnit === 'mph' ? speedMps * MPH_PER_MPS : mpsToKmh(speedMps);
      return converted.toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1');
    };
    setInputs((current) => ({
      ...current,
      ballSpeed: convert(current.ballSpeed),
      clubSpeed: convert(current.clubSpeed),
    }));
    setSpeedUnit(nextUnit);
  };

  const reset = () => {
    setInputs(initialInputs);
    setHasCalculated(false);
  };

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.flex}>
      <ScrollView
        contentContainerStyle={[styles.content, { paddingTop: insets.top + spacing.md }]}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        <ScreenHeader title="Calculator" subtitle="Manual shot model" state={state} demo={isDemo} />

        <Surface style={styles.introCard}>
          <View style={styles.introIcon}>
            <Ionicons name="calculator" size={24} color={colors.accent} />
          </View>
          <View style={styles.introCopy}>
            <Eyebrow>Manual analysis</Eyebrow>
            <Text style={styles.introTitle}>Enter a shot. See the full picture.</Text>
            <Text style={styles.introBody}>Results use the same calculations and visuals as a captured shot.</Text>
          </View>
        </Surface>

        <View style={styles.section}>
          <SectionHeader title="Club & units" />
          <ClubSelector />
          <View accessibilityRole="radiogroup" style={styles.unitSelector}>
            <UnitButton label="Kilometres per hour" shortLabel="km/h" selected={speedUnit === 'kmh'} onPress={() => changeUnit('kmh')} />
            <UnitButton label="Miles per hour" shortLabel="mph" selected={speedUnit === 'mph'} onPress={() => changeUnit('mph')} />
          </View>
          <Text style={styles.unitNote}>This is your app-wide speed unit — every screen follows it.</Text>
        </View>

        <View style={styles.section}>
          <SectionHeader title="Speed data" />
          <View style={styles.fieldRow}>
            <NumberField
              label="Ball speed"
              placeholder={speedUnit === 'kmh' ? '222.5' : '138.2'}
              suffix={speedUnit === 'kmh' ? 'km/h' : 'mph'}
              value={inputs.ballSpeed}
              onChangeText={(value) => updateInput('ballSpeed', value)}
            />
            <NumberField
              label="Club speed"
              placeholder={speedUnit === 'kmh' ? '152.6' : '94.8'}
              suffix={speedUnit === 'kmh' ? 'km/h' : 'mph'}
              value={inputs.clubSpeed}
              onChangeText={(value) => updateInput('clubSpeed', value)}
            />
          </View>
        </View>

        <View style={styles.section}>
          <SectionHeader title="Launch data" />
          <View style={styles.fieldRow}>
            <NumberField
              label="Launch angle"
              placeholder="14.2"
              suffix="deg"
              value={inputs.launchAngle}
              onChangeText={(value) => updateInput('launchAngle', value)}
            />
            <NumberField
              label="Start direction"
              placeholder="0"
              suffix="deg"
              helper="+ right / toward cameras · − left / away"
              value={inputs.startDirection}
              onChangeText={(value) => updateInput('startDirection', value)}
            />
          </View>
        </View>

        <View style={styles.section}>
          <SectionHeader title="Strike location" />
          <View style={styles.fieldRow}>
            <NumberField
              label="Horizontal"
              placeholder="0"
              suffix="mm"
              helper="− heel · + toe"
              value={inputs.strikeX}
              onChangeText={(value) => updateInput('strikeX', value)}
            />
            <NumberField
              label="Vertical"
              placeholder="0"
              suffix="mm"
              helper="− low · + high"
              value={inputs.strikeY}
              onChangeText={(value) => updateInput('strikeY', value)}
            />
          </View>
        </View>

        <View style={styles.actions}>
          <View style={styles.calculateAction}>
            <PrimaryButton
              label="Calculate shot"
              icon="calculator"
              disabled={!calculatedShot}
              onPress={() => {
                Keyboard.dismiss();
                setHasCalculated(true);
              }}
            />
          </View>
          <Pressable accessibilityRole="button" accessibilityLabel="Reset calculator" onPress={reset} style={styles.resetButton}>
            <Ionicons name="refresh" color={colors.textMuted} size={19} />
          </Pressable>
        </View>

        {!calculatedShot && (inputs.ballSpeed || inputs.clubSpeed || inputs.launchAngle) ? (
          <View style={styles.validationMessage}>
            <Ionicons name="information-circle" size={17} color={colors.orange} />
            <Text style={styles.validationText}>Complete the required fields with realistic values to calculate the shot.</Text>
          </View>
        ) : null}

        {hasCalculated && calculatedShot ? <CalculatorResults shot={calculatedShot} /> : null}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function CalculatorResults({ shot }: { shot: Shot }) {
  const club = getClub(shot.clubId);
  const units = useUnits();
  const clubSpeed = measuredClubSpeed(shot);
  const smash = measuredSmash(shot);
  const { state: openGolfSimState, sendShot } = useOpenGolfSim();
  const [sentToOpenGolfSim, setSentToOpenGolfSim] = useState(false);
  const openGolfSimConnected = openGolfSimState === 'connected';

  useEffect(() => setSentToOpenGolfSim(false), [shot]);

  return (
    <View style={styles.resultsSection}>
      <View style={styles.resultHeading}>
        <View>
          <Eyebrow>Calculated result</Eyebrow>
          <Text style={styles.resultTitle}>{club.label} model</Text>
        </View>
        <View style={styles.manualPill}>
          <Ionicons name="create-outline" size={13} color={colors.cyan} />
          <Text style={styles.manualText}>Manual</Text>
        </View>
      </View>

      <Surface style={styles.resultHero}>
        <View>
          <Eyebrow>Estimated carry</Eyebrow>
          <View style={styles.carryRow}>
            <Text style={styles.carryValue}>{units.distance(shot.estimatedCarryM)}</Text>
            <Text style={styles.carryUnit}>{units.distanceLabel}</Text>
          </View>
          <Text style={styles.carryYards}>{units.altDistanceWithUnit(shot.estimatedCarryM)}</Text>
        </View>
        <View style={styles.smashBlock}>
          <Text style={styles.smashLabel}>Smash factor</Text>
          <Text style={styles.smashValue}>{smash === null ? '—' : smash.toFixed(2)}</Text>
          <Text style={styles.smashQuality}>{smash === null ? 'Club not measured' : smashDescription(smash)}</Text>
        </View>
      </Surface>

      <View style={styles.metricRow}>
        <MetricTile label="Ball speed" value={units.speed(shot.ballSpeedMps)} unit={units.speedLabel} />
        <MetricTile label="Club speed" value={clubSpeed === null ? '—' : units.speed(clubSpeed)} unit={units.speedLabel} />
        <MetricTile label="Launch" value={shot.launchAngleDeg.toFixed(1)} unit="deg" />
      </View>

      <Surface style={styles.simulatorCard}>
        <View style={styles.simulatorCopy}>
          <Text style={styles.simulatorTitle}>OpenGolfSim</Text>
          <Text style={styles.simulatorBody}>
            {openGolfSimConnected
              ? 'Send this manual result to the connected simulator.'
              : 'Connect OpenGolfSim from the Device tab to send this result.'}
          </Text>
        </View>
        <View style={styles.simulatorAction}>
          <PrimaryButton
            label={sentToOpenGolfSim ? 'Shot sent' : 'Send shot'}
            icon={sentToOpenGolfSim ? 'checkmark-circle' : 'paper-plane-outline'}
            disabled={!openGolfSimConnected || sentToOpenGolfSim}
            onPress={() => setSentToOpenGolfSim(sendShot(shot))}
            variant="outline"
          />
        </View>
      </Surface>

      <Surface style={styles.visualCard}>
        <View style={styles.visualHeader}>
          <View>
            <Eyebrow>Calculated launch</Eyebrow>
            <Text style={styles.visualTitle}>{directionLabel(shot.startDirectionDeg)}</Text>
          </View>
          <Ionicons name="navigate" color={colors.cyan} size={19} />
        </View>
        <TrajectoryChart shot={shot} />
      </Surface>

      <Surface style={styles.visualCard}>
        <View style={styles.visualHeader}>
          <View>
            <Eyebrow>Entered strike</Eyebrow>
            <Text style={styles.visualTitle}>{strikeLabel(shot)}</Text>
          </View>
          <Ionicons name="locate" color={colors.accent} size={19} />
        </View>
        <StrikeMap shot={shot} />
      </Surface>

      <View style={styles.disclaimer}>
        <Ionicons name="flask-outline" size={17} color={colors.textMuted} />
        <Text style={styles.disclaimerText}>
          Carry is an estimate without measured spin, wind, altitude or temperature. Manual calculations are not added to shot history.
        </Text>
      </View>
    </View>
  );
}

function NumberField({
  label,
  value,
  placeholder,
  suffix,
  helper,
  onChangeText,
}: {
  label: string;
  value: string;
  placeholder: string;
  suffix: string;
  helper?: string;
  onChangeText: (value: string) => void;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <View style={styles.inputWrap}>
        <TextInput
          accessibilityLabel={`${label}, ${suffix}`}
          autoCorrect={false}
          inputMode="decimal"
          keyboardType="decimal-pad"
          onChangeText={onChangeText}
          placeholder={placeholder}
          placeholderTextColor={colors.textDim}
          returnKeyType="done"
          selectionColor={colors.accent}
          style={styles.input}
          value={value}
        />
        <Text style={styles.suffix}>{suffix}</Text>
      </View>
      <Text style={styles.fieldHelper}>{helper ?? 'Required'}</Text>
    </View>
  );
}

function UnitButton({
  label,
  shortLabel,
  selected,
  onPress,
}: {
  label: string;
  shortLabel: string;
  selected: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityLabel={label}
      accessibilityState={{ checked: selected }}
      onPress={onPress}
      style={({ pressed }) => [styles.unitButton, selected && styles.unitButtonSelected, pressed && styles.pressed]}
    >
      <Text style={[styles.unitText, selected && styles.unitTextSelected]}>{shortLabel}</Text>
    </Pressable>
  );
}

function parseNumber(value: string): number | null {
  const normalized = value.trim().replace(',', '.');
  if (!normalized || normalized === '-' || normalized === '.') return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function sanitizeNumericInput(value: string): string {
  return value.replace(/[^0-9,.-]/g, '').replace(/(?!^)-/g, '');
}

function smashDescription(smash: number): string {
  if (smash >= 1.45) return 'Highly efficient';
  if (smash >= 1.3) return 'Efficient strike';
  if (smash >= 1) return 'Moderate transfer';
  return 'Check inputs';
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { paddingBottom: 120, paddingHorizontal: spacing.md },
  introCard: { alignItems: 'center', flexDirection: 'row', padding: spacing.lg },
  introIcon: { alignItems: 'center', backgroundColor: colors.accentWash, borderRadius: 6, height: 52, justifyContent: 'center', marginRight: spacing.md, width: 52 },
  introCopy: { flex: 1 },
  introTitle: { color: colors.text, fontSize: 18, fontWeight: '700', letterSpacing: -0.4, marginTop: 4 },
  introBody: { color: colors.textMuted, fontSize: 11, lineHeight: 16, marginTop: 4 },
  section: { marginTop: spacing.xl },
  unitSelector: { backgroundColor: colors.surface, borderColor: colors.line, borderRadius: radii.md, borderWidth: 1, flexDirection: 'row', gap: 5, padding: 5 },
  unitNote: { color: colors.textMuted, fontSize: 12, lineHeight: 16, marginTop: spacing.xs },
  unitButton: { alignItems: 'center', borderRadius: radii.sm, flex: 1, justifyContent: 'center', minHeight: 42 },
  unitButtonSelected: { backgroundColor: colors.accent },
  unitText: { color: colors.textMuted, fontSize: 13, fontWeight: '800' },
  unitTextSelected: { color: colors.accentInk },
  pressed: { opacity: 0.74 },
  fieldRow: { flexDirection: 'row', gap: spacing.sm },
  field: { flex: 1 },
  fieldLabel: { color: colors.textMuted, fontSize: 10, fontWeight: '800', letterSpacing: 0.7, marginBottom: 7, textTransform: 'uppercase' },
  inputWrap: { alignItems: 'center', backgroundColor: colors.surface, borderColor: colors.lineStrong, borderRadius: radii.md, borderWidth: 1, flexDirection: 'row', minHeight: 58, paddingHorizontal: spacing.md },
  input: { color: colors.text, flex: 1, fontSize: 21, fontWeight: '700', minWidth: 0, paddingVertical: 0 },
  suffix: { color: colors.textDim, fontSize: 10, fontWeight: '800' },
  fieldHelper: { color: colors.textDim, fontSize: 9, fontWeight: '600', marginTop: 6, minHeight: 12 },
  actions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.xl },
  calculateAction: { flex: 1 },
  resetButton: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderColor: colors.line, borderRadius: radii.md, borderWidth: 1, justifyContent: 'center', width: 56 },
  validationMessage: { alignItems: 'center', backgroundColor: '#241E16', borderRadius: radii.sm, flexDirection: 'row', gap: 8, marginTop: spacing.md, padding: 11 },
  validationText: { color: '#DDB985', flex: 1, fontSize: 10, lineHeight: 15 },
  resultsSection: { marginTop: spacing.xxl },
  resultHeading: { alignItems: 'flex-end', flexDirection: 'row', justifyContent: 'space-between', marginBottom: spacing.md },
  resultTitle: { color: colors.text, fontSize: 24, fontWeight: '700', letterSpacing: -0.7, marginTop: 3 },
  manualPill: { alignItems: 'center', backgroundColor: colors.accentWash, borderRadius: radii.pill, flexDirection: 'row', gap: 5, paddingHorizontal: 10, paddingVertical: 7 },
  manualText: { color: colors.cyan, fontSize: 10, fontWeight: '800' },
  resultHero: { alignItems: 'flex-end', flexDirection: 'row', justifyContent: 'space-between', padding: spacing.lg },
  carryRow: { alignItems: 'baseline', flexDirection: 'row', gap: 6, marginTop: 2 },
  carryValue: { color: colors.accent, fontSize: 55, fontWeight: '700', letterSpacing: -3 },
  carryUnit: { color: colors.textMuted, fontSize: 16, fontWeight: '700' },
  carryYards: { color: colors.textDim, fontSize: 11, fontWeight: '700', marginTop: -6 },
  smashBlock: { alignItems: 'flex-end', paddingBottom: 2 },
  smashLabel: { color: colors.textMuted, fontSize: 9, fontWeight: '800', letterSpacing: 0.7, textTransform: 'uppercase' },
  smashValue: { color: colors.text, fontSize: 35, fontWeight: '700', letterSpacing: -1.5, marginTop: 3 },
  smashQuality: { color: colors.textDim, fontSize: 9, fontWeight: '700' },
  metricRow: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
  simulatorCard: { alignItems: 'center', flexDirection: 'row', marginTop: spacing.sm, padding: spacing.md },
  simulatorCopy: { flex: 1, paddingRight: spacing.md },
  simulatorTitle: { color: colors.text, fontSize: 13, fontWeight: '800' },
  simulatorBody: { color: colors.textMuted, fontSize: 9, lineHeight: 14, marginTop: 3 },
  simulatorAction: { minWidth: 120 },
  visualCard: { marginTop: spacing.sm, overflow: 'hidden', padding: spacing.lg },
  visualHeader: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  visualTitle: { color: colors.text, fontSize: 18, fontWeight: '700', marginTop: 3, textTransform: 'capitalize' },
  disclaimer: { alignItems: 'flex-start', flexDirection: 'row', gap: 9, marginTop: spacing.md, paddingHorizontal: spacing.sm },
  disclaimerText: { color: colors.textMuted, flex: 1, fontSize: 10, lineHeight: 15 },
});
